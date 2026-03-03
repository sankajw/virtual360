import streamlit as st
import pandas as pd
import io
import hashlib
import sqlite3
import json
import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import streamlit.components.v1 as components

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
st.set_page_config(page_title="Dexxora | Virtual360", layout="wide")

# /tmp is always writable — on Streamlit Cloud AND locally
DB_PATH = "/tmp/virtual360_users.db"

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def get_db():
    """Return a SQLite connection to the writable /tmp database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Create tables if they don't exist, then seed from st.secrets / defaults.
    Only seeds on the very first run (empty tables).
    """
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username      TEXT PRIMARY KEY,
                display_name  TEXT NOT NULL,
                role          TEXT NOT NULL,
                tenant_access  TEXT NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_name TEXT PRIMARY KEY,
                tenant_type TEXT NOT NULL DEFAULT 'Commercial'
            )
        """)
        conn.commit()

        # Seed tenants
        tcount = conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        if tcount == 0:
            for name, ttype in [("EDEN Tenant", "Residential"), ("Thaala Tenant", "Commercial")]:
                conn.execute("INSERT OR IGNORE INTO tenants VALUES (?,?)", (name, ttype))
            conn.commit()

        # Seed users
        ucount = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if ucount == 0:
            for uname, ud in _get_seed_users().items():
                conn.execute(
                    "INSERT OR IGNORE INTO users VALUES (?,?,?,?,?)",
                    (uname, ud["display_name"], ud["role"],
                     json.dumps(ud["tenant_access"]), ud["password_hash"])
                )
            conn.commit()


def load_tenants_from_db() -> list:
    """Return sorted list of (tenant_name, tenant_type) tuples from the DB."""
    with get_db() as conn:
        rows = conn.execute("SELECT tenant_name, tenant_type FROM tenants ORDER BY tenant_name").fetchall()
    return [{"name": r["tenant_name"], "type": r["tenant_type"]} for r in rows]


def get_tenant_names() -> list:
    """Return just a list of tenant name strings (for dropdowns)."""
    return [t["name"] for t in load_tenants_from_db()]


def add_tenant_to_db(tenant_name: str, tenant_type: str):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO tenants VALUES (?,?)", (tenant_name, tenant_type))
        conn.commit()


def delete_tenant_from_db(tenant_name: str):
    with get_db() as conn:
        conn.execute("DELETE FROM tenants WHERE tenant_name = ?", (tenant_name,))
        conn.commit()


def _get_seed_users() -> dict:
    """Read initial users from st.secrets, falling back to defaults."""
    try:
        raw = st.secrets.get("users", {})
        if raw:
            return {
                uname: {
                    "password_hash": udata["password_hash"],
                    "role":          udata["role"],
                    "tenant_access":  list(udata["tenant_access"]),
                    "display_name":  udata["display_name"],
                }
                for uname, udata in raw.items()
            }
    except Exception:
        pass
    # Hard-coded fallback
    return {
        "admin": {
            "password_hash": hash_pw("Admin@123"),
            "role":          "admin",
            "tenant_access":  ["EDEN Tenant", "Thaala Tenant"],
            "display_name":  "Administrator",
        },
        "eden_user": {
            "password_hash": hash_pw("Eden@123"),
            "role":          "user",
            "tenant_access":  ["EDEN Tenant"],
            "display_name":  "EDEN Staff",
        },
        "thaala_user": {
            "password_hash": hash_pw("Thaala@123"),
            "role":          "user",
            "tenant_access":  ["Thaala Tenant"],
            "display_name":  "Thaala Staff",
        },
    }


def load_users_from_db() -> dict:
    """Load all users from the /tmp SQLite database into a plain dict."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM users").fetchall()
    return {
        row["username"]: {
            "display_name":  row["display_name"],
            "role":          row["role"],
            "tenant_access":  json.loads(row["tenant_access"]),
            "password_hash": row["password_hash"],
        }
        for row in rows
    }


def save_user_to_db(username: str, ud: dict):
    """Insert or replace a single user record."""
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO users VALUES (?,?,?,?,?)",
            (username, ud["display_name"], ud["role"],
             json.dumps(ud["tenant_access"]), ud["password_hash"])
        )
        conn.commit()


def delete_user_from_db(username: str):
    """Delete a user from the database."""
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()


def save_users_to_secrets(users: dict):
    """
    Compatibility shim — persists all users to SQLite.
    Called wherever the old secrets-based save was used.
    """
    for uname, ud in users.items():
        save_user_to_db(uname, ud)
    # Keep session_state in sync
    st.session_state.users = load_users_from_db()


# Initialise DB on every cold start
init_db()


# ─────────────────────────────────────────────
# SESSION STATE BOOTSTRAP
# ─────────────────────────────────────────────
def init_state():
    defaults = {
        "logged_in":    False,
        "current_user": None,
        "current_role": None,
        "active_tab":   "assessment",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if "users" not in st.session_state:
        st.session_state.users = load_users_from_db()

    if "tenants" not in st.session_state:
        st.session_state.tenants = load_tenants_from_db()

    if "tenant_data" not in st.session_state:
        st.session_state.tenant_data = pd.DataFrame(columns=[
            "Date Added", "Tenant Name", "Name of Area", "Category", "Coverage (SQFT)"
        ])
    if "last_category" not in st.session_state:
        st.session_state.last_category = "Suite/Room"


init_state()

# ─────────────────────────────────────────────
# PDF GENERATOR
# ─────────────────────────────────────────────
def generate_pdf(df: pd.DataFrame) -> bytes:
    buf  = io.BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=letter)
    styl = getSampleStyleSheet()
    rows  = [list(df.columns)] + df.values.tolist()
    table = Table(rows)
    table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#2E3B4E")),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE",      (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1,  0), 10),
    ]))
    doc.build([
        Paragraph("Dexxora Pvt Ltd",                               styl["Title"]),
        Paragraph("Virtual360 Area Assessment Report",              styl["Heading2"]),
        Paragraph(f"Generated on: {datetime.now():%Y-%m-%d %H:%M}", styl["Normal"]),
        Spacer(1, 20),
        table,
        Paragraph(
            f"<br/><br/>© {datetime.now().year} Dexxora Pvt Ltd. All rights reserved.",
            styl["Normal"]
        ),
    ])
    return buf.getvalue()

# ─────────────────────────────────────────────
# LOGIN PAGE
# ─────────────────────────────────────────────
def show_login():
    _, col, _ = st.columns([1, 1.4, 1])
    with col:
        st.markdown("""
        <div style='text-align:center;padding:40px 0 10px 0;'>
            <h2 style='color:#2E3B4E;margin-bottom:2px;'>🏢 Dexxora Pvt Ltd</h2>
            <p style='color:#666;font-size:1rem;margin-top:0;'>Virtual360 Cost Assessment</p>
        </div>""", unsafe_allow_html=True)

        st.markdown("""
        <div style='background:#f7f9fc;border:1px solid #e0e7ef;border-radius:12px;
                    padding:32px 36px 28px 36px;box-shadow:0 2px 12px rgba(46,59,78,.08);'>
        """, unsafe_allow_html=True)

        st.markdown(
            "<h4 style='color:#2E3B4E;margin-bottom:18px;text-align:center;'>Sign In</h4>",
            unsafe_allow_html=True,
        )
        username = st.text_input("Username", placeholder="Enter username")
        password = st.text_input("Password", type="password", placeholder="Enter password")

        if st.button("🔐 Login", use_container_width=True, type="primary"):
            users = st.session_state.users
            if username in users and users[username]["password_hash"] == hash_pw(password):
                st.session_state.logged_in    = True
                st.session_state.current_user = username
                st.session_state.current_role = users[username]["role"]
                st.rerun()
            else:
                st.error("Invalid username or password.")

        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown(
            f"<p style='text-align:center;color:#aaa;font-size:.78rem;margin-top:18px;'>"
            f"© {datetime.now().year} Dexxora Pvt Ltd. All rights reserved.</p>",
            unsafe_allow_html=True,
        )

# ─────────────────────────────────────────────
# ADMIN PANEL
# ─────────────────────────────────────────────
def show_admin_panel():
    st.markdown("## ⚙️ Admin Panel")
    st.caption(
        "User changes are saved to a SQLite database in `/tmp`. "
        "Seed credentials are loaded from `st.secrets` on first run."
    )
    st.markdown("---")

    tab_users, tab_tenants, tab_data, tab_export = st.tabs([
        "👥 User Management", "🏢 Tenant Management", "📊 All Tenant Data", "📥 Export Reports"
    ])

    # ── TAB 1 : User Management ──────────────────────────────────────
    with tab_users:
        st.subheader("Current Users")
        st.dataframe(
            pd.DataFrame([{
                "Username":     u,
                "Display Name": d["display_name"],
                "Role":         d["role"].capitalize(),
                "Tenant Access": ", ".join(d["tenant_access"]),
            } for u, d in st.session_state.users.items()]),
            use_container_width=True, hide_index=True,
        )

        st.markdown("---")
        col_add, col_manage = st.columns(2)

        # Add user
        with col_add:
            st.subheader("➕ Add New User")
            with st.form("add_user_form", clear_on_submit=True):
                nu   = st.text_input("Username")
                nd   = st.text_input("Display Name")
                nr   = st.selectbox("Role", ["user", "admin"])
                nh   = st.multiselect("Tenant Access",
                                      get_tenant_names(),
                                      default=get_tenant_names()[:1])
                np1  = st.text_input("Password",         type="password")
                np2  = st.text_input("Confirm Password", type="password")
                add  = st.form_submit_button("Add User", use_container_width=True)

            if add:
                if not nu or not np1:
                    st.error("Username and password are required.")
                elif nu in st.session_state.users:
                    st.error("Username already exists.")
                elif np1 != np2:
                    st.error("Passwords do not match.")
                elif not nh:
                    st.error("Select at least one tenant.")
                else:
                    st.session_state.users[nu] = {
                        "password_hash": hash_pw(np1),
                        "role":          nr,
                        "tenant_access":  nh,
                        "display_name":  nd or nu,
                    }
                    save_users_to_secrets(st.session_state.users)
                    st.success(f"User **{nu}** created.")
                    st.rerun()

        # Change password + delete
        with col_manage:
            st.subheader("🔑 Change Password")
            with st.form("change_pw_form", clear_on_submit=True):
                su  = st.selectbox("Select User", list(st.session_state.users.keys()), key="su_chg")
                p1  = st.text_input("New Password",     type="password", key="cpw1")
                p2  = st.text_input("Confirm Password", type="password", key="cpw2")
                chg = st.form_submit_button("Update Password", use_container_width=True)

            if chg:
                if not p1:
                    st.error("Password cannot be empty.")
                elif p1 != p2:
                    st.error("Passwords do not match.")
                else:
                    st.session_state.users[su]["password_hash"] = hash_pw(p1)
                    save_users_to_secrets(st.session_state.users)
                    st.success(f"Password for **{su}** updated.")

            st.markdown("---")
            st.subheader("🗑️ Delete User")
            deletable = [u for u in st.session_state.users
                         if u != st.session_state.current_user]
            with st.form("del_user_form", clear_on_submit=True):
                du  = st.selectbox("Select User to Delete",
                                   deletable if deletable else ["(none)"], key="su_del")
                db  = st.form_submit_button("Delete User", type="primary",
                                             use_container_width=True)

            if db and du != "(none)":
                del st.session_state.users[du]
                save_users_to_secrets(st.session_state.users)
                st.success(f"User **{du}** deleted.")
                st.rerun()

        # Edit tenant access
        st.markdown("---")
        st.subheader("🏢 Edit Tenant Access")
        with st.form("edit_access_form"):
            ea_u    = st.selectbox("Select User",
                                   list(st.session_state.users.keys()), key="ea_u")
            cur_acc = st.session_state.users.get(ea_u, {}).get("tenant_access", [])
            new_acc = st.multiselect("Tenant Access",
                                     get_tenant_names(),
                                     default=cur_acc, key="ea_acc")
            ea_btn  = st.form_submit_button("Update Access")

        if ea_btn:
            if not new_acc:
                st.error("At least one tenant must be selected.")
            else:
                st.session_state.users[ea_u]["tenant_access"] = new_acc
                save_users_to_secrets(st.session_state.users)
                st.success(f"Tenant access for **{ea_u}** updated.")
                st.rerun()

    # ── TAB 2 : Tenant Management ─────────────────────────────────────
    with tab_tenants:
        st.subheader("🏢 Tenants")

        tenants = st.session_state.tenants
        if tenants:
            st.dataframe(
                pd.DataFrame([{"Tenant Name": t["name"], "Tenant Type": t["type"]} for t in tenants]),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("No tenants added yet.")

        st.markdown("---")
        tcol_add, tcol_del = st.columns(2)

        with tcol_add:
            st.subheader("➕ Add New Tenant")
            TENANT_TYPES = ["Commercial", "Residential", "Retail", "Industrial", "Hospitality", "Mixed-Use", "Other"]
            with st.form("add_tenant_form", clear_on_submit=True):
                new_tenant_name = st.text_input("Tenant Name", placeholder="e.g. Marina Bay Tower")
                new_tenant_type = st.selectbox("Tenant Type", TENANT_TYPES)
                add_tenant_btn  = st.form_submit_button("Add Tenant", use_container_width=True)

            if add_tenant_btn:
                hn = new_tenant_name.strip()
                if not hn:
                    st.error("Tenant name cannot be empty.")
                elif hn in get_tenant_names():
                    st.error("Tenant already exists.")
                else:
                    add_tenant_to_db(hn, new_tenant_type)
                    st.session_state.tenants = load_tenants_from_db()
                    st.success(f"Tenant **{hn}** ({new_tenant_type}) added.")
                    st.rerun()

        with tcol_del:
            st.subheader("🗑️ Delete Tenant")
            st.warning("Deleting a tenant will NOT remove its assessment data.", icon="⚠️")
            tenant_name_list = get_tenant_names()
            with st.form("del_tenant_form", clear_on_submit=True):
                del_tenant = st.selectbox(
                    "Select Tenant to Delete",
                    tenant_name_list if tenant_name_list else ["(none)"],
                    key="del_tenant_sel",
                )
                del_tenant_btn = st.form_submit_button("Delete Tenant", type="primary",
                                                       use_container_width=True)

            if del_tenant_btn and del_tenant != "(none)":
                delete_tenant_from_db(del_tenant)
                # Remove from all user tenant_access lists
                for uname, ud in st.session_state.users.items():
                    if del_tenant in ud["tenant_access"]:
                        ud["tenant_access"] = [t for t in ud["tenant_access"] if t != del_tenant]
                        save_user_to_db(uname, ud)
                st.session_state.tenants = load_tenants_from_db()
                st.session_state.users  = load_users_from_db()
                st.success(f"Tenant **{del_tenant}** deleted.")
                st.rerun()

    # ── TAB 3 : All Tenant Data ───────────────────────────────────────
    with tab_data:
        st.subheader("All Assessment Records")
        if st.session_state.tenant_data.empty:
            st.info("No assessment data recorded yet.")
        else:
            hf = st.multiselect(
                "Filter by Tenant",
                get_tenant_names(),
                default=get_tenant_names(),
                key="adm_hf",
            )
            vdf = st.session_state.tenant_data[
                st.session_state.tenant_data["Tenant Name"].isin(hf)
            ]
            st.dataframe(vdf, use_container_width=True, hide_index=True)
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Records", len(vdf))
            c2.metric("Total SQFT",     f"{vdf['Coverage (SQFT)'].sum():,.1f}")
            c3.metric("Tenants",        vdf["Tenant Name"].nunique())

        st.markdown("---")
        if st.button("🗑️ Clear ALL Data", type="primary"):
            st.session_state.tenant_data = pd.DataFrame(
                columns=st.session_state.tenant_data.columns)
            st.success("All data cleared.")
            st.rerun()

    # ── TAB 3 : Export Reports ───────────────────────────────────────
    with tab_export:
        st.subheader("Export Assessment Report")
        if st.session_state.tenant_data.empty:
            st.info("No data to export yet.")
        else:
            eh = st.multiselect(
                "Include Tenants",
                get_tenant_names(),
                default=get_tenant_names(),
                key="adm_eh",
            )
            edf = st.session_state.tenant_data[
                st.session_state.tenant_data["Tenant Name"].isin(eh)
            ]
            if not edf.empty:
                st.download_button(
                    label="📥 Download PDF Report",
                    data=generate_pdf(edf),
                    file_name=f"Dexxora_Assessment_{datetime.now():%Y%m%d}.pdf",
                    mime="application/pdf",
                )
            else:
                st.warning("No data for selected tenants.")

# ─────────────────────────────────────────────
# ASSESSMENT PAGE
# ─────────────────────────────────────────────
def show_assessment():
    components.html("""
    <script>
    var inp = window.parent.document.querySelectorAll("input[type=text]");
    if (inp.length > 0) inp[0].focus();
    </script>""", height=0)

    user_data    = st.session_state.users[st.session_state.current_user]
    tenant_access = user_data["tenant_access"]

    st.markdown("<h3 style='color:#2E3B4E;margin-bottom:-10px;'>Dexxora Pvt Ltd</h3>",
                unsafe_allow_html=True)
    st.title("🏢 Virtual360 Cost Assessment")
    st.markdown("---")
    st.subheader("📍 Quick Data Entry")

    with st.form("entry_form", clear_on_submit=True):
        f1, f2, f3, f4, f5 = st.columns([1.5, 2.5, 2, 1, 1])
        with f1:
            tenant_choice = st.selectbox("Tenant Name", tenant_access)
        with f2:
            area_name = st.text_input("Name of Area")
        with f3:
            cats  = ["Suite/Room", "Restaurant & Bar", "Lobby",
                     "Function Venue", "Outdoor", "Gym", "Other"]
            d_idx = cats.index(st.session_state.last_category) \
                    if st.session_state.last_category in cats else 0
            cat   = st.selectbox("Category", cats, index=d_idx)
        with f4:
            sqm = st.number_input("SQFT", min_value=0.0, step=1.0)
        with f5:
            st.markdown('<p style="margin-bottom:32px;"></p>', unsafe_allow_html=True)
            submitted = st.form_submit_button("➕ Add", use_container_width=True)

    if submitted:
        if area_name and sqm > 0:
            new_row = pd.DataFrame({
                "Date Added":     [datetime.now().strftime("%Y-%m-%d")],
                "Tenant Name":     [tenant_choice],
                "Name of Area":   [area_name],
                "Category":       [cat],
                "Coverage (SQFT)": [sqm],
            })
            st.session_state.tenant_data = pd.concat(
                [st.session_state.tenant_data, new_row], ignore_index=True)
            st.session_state.last_category = cat
            st.rerun()
        else:
            st.error("Please fill Name of Area and SQFT.")

    st.markdown("---")

    tenant_filter = st.sidebar.multiselect(
        "Filter View", tenant_access, default=tenant_access)

    # Refresh hotel list in case admin added new ones
    # tenants refreshed above

    if not st.session_state.tenant_data.empty:
        st.subheader("📊 Assessment Inventory")
        disp_df = st.session_state.tenant_data[
            st.session_state.tenant_data["Tenant Name"].isin(tenant_access)
        ]
        edited = st.data_editor(
            disp_df, num_rows="dynamic",
            use_container_width=True, key="main_editor",
        )
        if not edited.equals(disp_df):
            other = st.session_state.tenant_data[
                ~st.session_state.tenant_data["Tenant Name"].isin(tenant_access)
            ]
            st.session_state.tenant_data = pd.concat([other, edited], ignore_index=True)
            st.rerun()

        exp_df = edited[edited["Tenant Name"].isin(tenant_filter)]
        if not exp_df.empty:
            st.markdown("### 📥 Export Report")
            e1, _ = st.columns([1, 3])
            with e1:
                st.download_button(
                    label="📥 Download PDF Report",
                    data=generate_pdf(exp_df),
                    file_name=f"Dexxora_Assessment_{datetime.now():%Y%m%d}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            if st.sidebar.button("🗑️ Clear My Data", use_container_width=True):
                other = st.session_state.tenant_data[
                    ~st.session_state.tenant_data["Tenant Name"].isin(tenant_access)
                ]
                st.session_state.tenant_data = other.reset_index(drop=True)
                st.rerun()
        else:
            st.warning("No data matches the selected filters.")

# ─────────────────────────────────────────────
# MAIN SHELL
# ─────────────────────────────────────────────
if not st.session_state.logged_in:
    show_login()
else:
    ud       = st.session_state.users[st.session_state.current_user]
    is_admin = st.session_state.current_role == "admin"

    with st.sidebar:
        st.markdown(f"### 👤 {ud['display_name']}")
        st.markdown(f"*Role: {'Admin' if is_admin else 'User'}*")
        st.markdown("---")

        if is_admin:
            if st.button("🏢 Assessment", use_container_width=True,
                         type="primary" if st.session_state.active_tab == "assessment" else "secondary"):
                st.session_state.active_tab = "assessment"
                st.rerun()
            if st.button("⚙️ Admin Panel", use_container_width=True,
                         type="primary" if st.session_state.active_tab == "admin" else "secondary"):
                st.session_state.active_tab = "admin"
                st.rerun()
            st.markdown("---")

        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.logged_in    = False
            st.session_state.current_user = None
            st.session_state.current_role = None
            st.session_state.active_tab   = "assessment"
            st.rerun()

    if is_admin and st.session_state.active_tab == "admin":
        show_admin_panel()
    else:
        show_assessment()

    st.markdown("---")
    st.markdown(
        f"<div style='text-align:center;color:#888;font-size:.8rem;padding:20px;'>"
        f"© {datetime.now().year} Dexxora Pvt Ltd. All rights reserved.</div>",
        unsafe_allow_html=True,
    )
