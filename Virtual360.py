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
    Create the users table if it doesn't exist, then seed it from
    st.secrets (Streamlit Cloud) or fall back to hard-coded defaults.
    Only seeds on the very first run (empty table).
    """
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username     TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                role         TEXT NOT NULL,
                hotel_access TEXT NOT NULL,   -- JSON array
                password_hash TEXT NOT NULL
            )
        """)
        conn.commit()

        # Seed only when table is empty
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            seed_users = _get_seed_users()
            for uname, ud in seed_users.items():
                conn.execute(
                    "INSERT OR IGNORE INTO users VALUES (?,?,?,?,?)",
                    (uname, ud["display_name"], ud["role"],
                     json.dumps(ud["hotel_access"]), ud["password_hash"])
                )
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
                    "hotel_access":  list(udata["hotel_access"]),
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
            "hotel_access":  ["EDEN Hotel", "Thaala Hotel"],
            "display_name":  "Administrator",
        },
        "eden_user": {
            "password_hash": hash_pw("Eden@123"),
            "role":          "user",
            "hotel_access":  ["EDEN Hotel"],
            "display_name":  "EDEN Staff",
        },
        "thaala_user": {
            "password_hash": hash_pw("Thaala@123"),
            "role":          "user",
            "hotel_access":  ["Thaala Hotel"],
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
            "hotel_access":  json.loads(row["hotel_access"]),
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
             json.dumps(ud["hotel_access"]), ud["password_hash"])
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

    if "hotel_data" not in st.session_state:
        st.session_state.hotel_data = pd.DataFrame(columns=[
            "Date Added", "Hotel Name", "Name of Area", "Category", "Coverage (SQM)"
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
            <h2 style='color:#2E3B4E;margin-bottom:2px;'>🏨 Dexxora Pvt Ltd</h2>
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

    tab_users, tab_data, tab_export = st.tabs([
        "👥 User Management", "📊 All Hotel Data", "📥 Export Reports"
    ])

    # ── TAB 1 : User Management ──────────────────────────────────────
    with tab_users:
        st.subheader("Current Users")
        st.dataframe(
            pd.DataFrame([{
                "Username":     u,
                "Display Name": d["display_name"],
                "Role":         d["role"].capitalize(),
                "Hotel Access": ", ".join(d["hotel_access"]),
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
                nh   = st.multiselect("Hotel Access",
                                      ["EDEN Hotel", "Thaala Hotel"],
                                      default=["EDEN Hotel"])
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
                    st.error("Select at least one hotel.")
                else:
                    st.session_state.users[nu] = {
                        "password_hash": hash_pw(np1),
                        "role":          nr,
                        "hotel_access":  nh,
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

        # Edit hotel access
        st.markdown("---")
        st.subheader("🏨 Edit Hotel Access")
        with st.form("edit_access_form"):
            ea_u    = st.selectbox("Select User",
                                   list(st.session_state.users.keys()), key="ea_u")
            cur_acc = st.session_state.users.get(ea_u, {}).get("hotel_access", [])
            new_acc = st.multiselect("Hotel Access",
                                     ["EDEN Hotel", "Thaala Hotel"],
                                     default=cur_acc, key="ea_acc")
            ea_btn  = st.form_submit_button("Update Access")

        if ea_btn:
            if not new_acc:
                st.error("At least one hotel must be selected.")
            else:
                st.session_state.users[ea_u]["hotel_access"] = new_acc
                save_users_to_secrets(st.session_state.users)
                st.success(f"Hotel access for **{ea_u}** updated.")
                st.rerun()

    # ── TAB 2 : All Hotel Data ───────────────────────────────────────
    with tab_data:
        st.subheader("All Assessment Records")
        if st.session_state.hotel_data.empty:
            st.info("No assessment data recorded yet.")
        else:
            hf = st.multiselect(
                "Filter by Hotel",
                ["EDEN Hotel", "Thaala Hotel"],
                default=["EDEN Hotel", "Thaala Hotel"],
                key="adm_hf",
            )
            vdf = st.session_state.hotel_data[
                st.session_state.hotel_data["Hotel Name"].isin(hf)
            ]
            st.dataframe(vdf, use_container_width=True, hide_index=True)
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Records", len(vdf))
            c2.metric("Total SQM",     f"{vdf['Coverage (SQM)'].sum():,.1f}")
            c3.metric("Hotels",        vdf["Hotel Name"].nunique())

        st.markdown("---")
        if st.button("🗑️ Clear ALL Data", type="primary"):
            st.session_state.hotel_data = pd.DataFrame(
                columns=st.session_state.hotel_data.columns)
            st.success("All data cleared.")
            st.rerun()

    # ── TAB 3 : Export Reports ───────────────────────────────────────
    with tab_export:
        st.subheader("Export Assessment Report")
        if st.session_state.hotel_data.empty:
            st.info("No data to export yet.")
        else:
            eh = st.multiselect(
                "Include Hotels",
                ["EDEN Hotel", "Thaala Hotel"],
                default=["EDEN Hotel", "Thaala Hotel"],
                key="adm_eh",
            )
            edf = st.session_state.hotel_data[
                st.session_state.hotel_data["Hotel Name"].isin(eh)
            ]
            if not edf.empty:
                st.download_button(
                    label="📥 Download PDF Report",
                    data=generate_pdf(edf),
                    file_name=f"Dexxora_Assessment_{datetime.now():%Y%m%d}.pdf",
                    mime="application/pdf",
                )
            else:
                st.warning("No data for selected hotels.")

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
    hotel_access = user_data["hotel_access"]

    st.markdown("<h3 style='color:#2E3B4E;margin-bottom:-10px;'>Dexxora Pvt Ltd</h3>",
                unsafe_allow_html=True)
    st.title("🏨 Virtual360 Cost Assessment")
    st.markdown("---")
    st.subheader("📍 Quick Data Entry")

    with st.form("entry_form", clear_on_submit=True):
        f1, f2, f3, f4, f5 = st.columns([1.5, 2.5, 2, 1, 1])
        with f1:
            hotel_choice = st.selectbox("Hotel Name", hotel_access)
        with f2:
            area_name = st.text_input("Name of Area")
        with f3:
            cats  = ["Suite/Room", "Restaurant & Bar", "Lobby",
                     "Function Venue", "Outdoor", "Gym", "Other"]
            d_idx = cats.index(st.session_state.last_category) \
                    if st.session_state.last_category in cats else 0
            cat   = st.selectbox("Category", cats, index=d_idx)
        with f4:
            sqm = st.number_input("SQM", min_value=0.0, step=1.0)
        with f5:
            st.markdown('<p style="margin-bottom:32px;"></p>', unsafe_allow_html=True)
            submitted = st.form_submit_button("➕ Add", use_container_width=True)

    if submitted:
        if area_name and sqm > 0:
            new_row = pd.DataFrame({
                "Date Added":     [datetime.now().strftime("%Y-%m-%d")],
                "Hotel Name":     [hotel_choice],
                "Name of Area":   [area_name],
                "Category":       [cat],
                "Coverage (SQM)": [sqm],
            })
            st.session_state.hotel_data = pd.concat(
                [st.session_state.hotel_data, new_row], ignore_index=True)
            st.session_state.last_category = cat
            st.rerun()
        else:
            st.error("Please fill Name of Area and SQM.")

    st.markdown("---")

    hotel_filter = st.sidebar.multiselect(
        "Filter View", hotel_access, default=hotel_access)

    if not st.session_state.hotel_data.empty:
        st.subheader("📊 Assessment Inventory")
        disp_df = st.session_state.hotel_data[
            st.session_state.hotel_data["Hotel Name"].isin(hotel_access)
        ]
        edited = st.data_editor(
            disp_df, num_rows="dynamic",
            use_container_width=True, key="main_editor",
        )
        if not edited.equals(disp_df):
            other = st.session_state.hotel_data[
                ~st.session_state.hotel_data["Hotel Name"].isin(hotel_access)
            ]
            st.session_state.hotel_data = pd.concat([other, edited], ignore_index=True)
            st.rerun()

        exp_df = edited[edited["Hotel Name"].isin(hotel_filter)]
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
                other = st.session_state.hotel_data[
                    ~st.session_state.hotel_data["Hotel Name"].isin(hotel_access)
                ]
                st.session_state.hotel_data = other.reset_index(drop=True)
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
            if st.button("🏨 Assessment", use_container_width=True,
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
