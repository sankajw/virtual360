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
    Create tables if they don't exist, run any schema migrations,
    then seed from st.secrets / defaults on first run.
    """
    with get_db() as conn:
        # ── Create tables ────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username      TEXT PRIMARY KEY,
                display_name  TEXT NOT NULL,
                role          TEXT NOT NULL,
                tenant_access TEXT NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_name TEXT PRIMARY KEY,
                tenant_type TEXT NOT NULL DEFAULT 'Commercial'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tenant_types (
                type_name TEXT PRIMARY KEY
            )
        """)
        conn.commit()

        # ── Migrations ───────────────────────────────────────────────
        # 1. Rename hotel_access → tenant_access in users table if old column exists
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "hotel_access" in cols and "tenant_access" not in cols:
            conn.execute("ALTER TABLE users RENAME COLUMN hotel_access TO tenant_access")
            conn.commit()

        # 2. Add tenant_type to tenants if missing (older DB without it)
        tcols = [r[1] for r in conn.execute("PRAGMA table_info(tenants)").fetchall()]
        if "tenant_type" not in tcols:
            conn.execute("ALTER TABLE tenants ADD COLUMN tenant_type TEXT NOT NULL DEFAULT 'Commercial'")
            conn.commit()

        # 3. Rename hotel_name → tenant_name in tenants table if old column exists
        tcols2 = [r[1] for r in conn.execute("PRAGMA table_info(tenants)").fetchall()]
        if "hotel_name" in tcols2 and "tenant_name" not in tcols2:
            conn.execute("ALTER TABLE tenants RENAME COLUMN hotel_name TO tenant_name")
            conn.commit()

        # 4. Migrate existing usernames to include @dexxora360 suffix
        old_users = conn.execute(
            "SELECT username FROM users WHERE username NOT LIKE '%@dexxora360'"
        ).fetchall()
        for row in old_users:
            old_name = row["username"]
            new_name = old_name + "@dexxora360"
            # Only rename if the new name doesn't already exist
            exists = conn.execute(
                "SELECT 1 FROM users WHERE username = ?", (new_name,)
            ).fetchone()
            if not exists:
                conn.execute(
                    "UPDATE users SET username = ? WHERE username = ?",
                    (new_name, old_name)
                )
        conn.commit()

        # ── Seed tenant types ─────────────────────────────────────────
        ttcount = conn.execute("SELECT COUNT(*) FROM tenant_types").fetchone()[0]
        if ttcount == 0:
            default_types = ["Commercial", "Residential", "Retail", "Industrial", "Hospitality", "Mixed-Use", "Other"]
            for t in default_types:
                conn.execute("INSERT OR IGNORE INTO tenant_types VALUES (?)", (t,))
            conn.commit()

        # ── Seed tenants ─────────────────────────────────────────────
        tcount = conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        if tcount == 0:
            for name, ttype in [("EDEN Tenant", "Residential"), ("Thaala Tenant", "Commercial")]:
                conn.execute("INSERT OR IGNORE INTO tenants VALUES (?,?)", (name, ttype))
            conn.commit()

        # ── Seed users ───────────────────────────────────────────────
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


def update_tenant_type_in_db(tenant_name: str, new_type: str):
    with get_db() as conn:
        conn.execute("UPDATE tenants SET tenant_type = ? WHERE tenant_name = ?",
                     (new_type, tenant_name))
        conn.commit()


def load_tenant_types_from_db() -> list:
    """Return sorted list of tenant type strings from the DB."""
    with get_db() as conn:
        rows = conn.execute("SELECT type_name FROM tenant_types ORDER BY type_name").fetchall()
    return [r["type_name"] for r in rows]


def add_tenant_type_to_db(type_name: str):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO tenant_types VALUES (?)", (type_name,))
        conn.commit()


def delete_tenant_type_from_db(type_name: str):
    with get_db() as conn:
        conn.execute("DELETE FROM tenant_types WHERE type_name = ?", (type_name,))
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
        "admin@dexxora360": {
            "password_hash": hash_pw("Admin@123"),
            "role":          "admin",
            "tenant_access":  ["EDEN Tenant", "Thaala Tenant"],
            "display_name":  "Administrator",
        },
        "eden_user@dexxora360": {
            "password_hash": hash_pw("Eden@123"),
            "role":          "user",
            "tenant_access":  ["EDEN Tenant"],
            "display_name":  "EDEN Staff",
        },
        "thaala_user@dexxora360": {
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
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    access_col = "tenant_access" if "tenant_access" in cols else "hotel_access"
    return {
        row["username"]: {
            "display_name":  row["display_name"],
            "role":          row["role"],
            "tenant_access": json.loads(row[access_col]),
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

    if "tenant_types" not in st.session_state:
        st.session_state.tenant_types = load_tenant_types_from_db()

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

        DOMAIN = "@dexxora360"

        # Username row: input + fixed suffix badge
        u_col, suf_col = st.columns([3, 2])
        with u_col:
            username_prefix = st.text_input("Username", placeholder="Enter username")
        with suf_col:
            st.markdown(
                f"<div style='margin-top:28px;background:#e8edf3;border:1px solid #c8d3de;"
                f"border-radius:6px;padding:8px 10px;color:#2E3B4E;font-weight:600;"
                f"font-size:0.95rem;text-align:center;'>{DOMAIN}</div>",
                unsafe_allow_html=True,
            )
        username = (username_prefix.strip() + DOMAIN) if username_prefix.strip() else ""
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
        DOMAIN = "@dexxora360"

        # ── Dialog: Add New User ──────────────────────────────────────
        @st.dialog("➕ Add New User")
        def dialog_add_user():
            with st.form("dlg_add_user_form", clear_on_submit=True):
                nu_col, nu_suf = st.columns([3, 2])
                with nu_col:
                    nu_prefix = st.text_input("Username")
                with nu_suf:
                    st.markdown(
                        f"<div style='margin-top:28px;background:#e8edf3;border:1px solid #c8d3de;"
                        f"border-radius:6px;padding:8px 10px;color:#2E3B4E;font-weight:600;"
                        f"font-size:0.9rem;text-align:center;'>{DOMAIN}</div>",
                        unsafe_allow_html=True,
                    )
                nd  = st.text_input("Display Name")
                nr  = st.selectbox("Role", ["user", "admin"])
                nh  = st.multiselect("Tenant Access", get_tenant_names(),
                                     default=get_tenant_names()[:1])
                np1 = st.text_input("Password",         type="password")
                np2 = st.text_input("Confirm Password", type="password")
                c1, c2 = st.columns(2)
                add = c1.form_submit_button("✅ Add User",    use_container_width=True, type="primary")
                c2.form_submit_button(      "✖ Cancel",       use_container_width=True)
            if add:
                nu = (nu_prefix.strip() + DOMAIN) if nu_prefix.strip() else ""
                if not nu_prefix.strip() or not np1:
                    st.error("Username and password are required.")
                elif nu in st.session_state.users:
                    st.error(f"Username **{nu}** already exists.")
                elif np1 != np2:
                    st.error("Passwords do not match.")
                elif not nh:
                    st.error("Select at least one tenant.")
                else:
                    st.session_state.users[nu] = {
                        "password_hash": hash_pw(np1),
                        "role":          nr,
                        "tenant_access": nh,
                        "display_name":  nd or nu_prefix.strip(),
                    }
                    save_users_to_secrets(st.session_state.users)
                    st.session_state.users = load_users_from_db()
                    st.session_state._dlg_action = None
                    st.session_state._dlg_target = None
                    st.rerun()

        # ── Dialog: Edit User ─────────────────────────────────────────
        @st.dialog("✏️ Edit User")
        def dialog_edit_user(username):
            ud            = st.session_state.users.get(username, {})
            valid_tenants = get_tenant_names()
            safe_acc      = [a for a in ud.get("tenant_access", []) if a in valid_tenants]
            with st.form("dlg_edit_form", clear_on_submit=False):
                st.markdown(f"**Username:** `{username}`")
                eu_dname  = st.text_input("Display Name", value=ud.get("display_name", ""))
                eu_role   = st.selectbox("Role", ["user", "admin"],
                                         index=0 if ud.get("role") == "user" else 1)
                eu_access = st.multiselect("Tenant Access", valid_tenants, default=safe_acc)
                c1, c2 = st.columns(2)
                save = c1.form_submit_button("✅ Save", use_container_width=True, type="primary")
                c2.form_submit_button(       "✖ Cancel", use_container_width=True)
            if save:
                if not eu_access:
                    st.error("Select at least one tenant.")
                else:
                    updated = dict(st.session_state.users[username])
                    updated["display_name"]  = eu_dname.strip() or username
                    updated["role"]          = eu_role
                    updated["tenant_access"] = eu_access
                    st.session_state.users[username] = updated
                    save_user_to_db(username, updated)
                    # Reload fresh from DB so grid reflects changes immediately
                    st.session_state.users = load_users_from_db()
                    st.session_state._dlg_action = None
                    st.session_state._dlg_target = None
                    st.rerun()

        # ── Dialog: Change Password ───────────────────────────────────
        @st.dialog("🔑 Change Password")
        def dialog_change_pw(username):
            st.markdown(f"**Username:** `{username}`")
            with st.form("dlg_pw_form", clear_on_submit=True):
                p1 = st.text_input("New Password",     type="password")
                p2 = st.text_input("Confirm Password", type="password")
                c1, c2 = st.columns(2)
                save = c1.form_submit_button("✅ Update", use_container_width=True, type="primary")
                c2.form_submit_button(       "✖ Cancel",  use_container_width=True)
            if save:
                if not p1:
                    st.error("Password cannot be empty.")
                elif p1 != p2:
                    st.error("Passwords do not match.")
                else:
                    updated = dict(st.session_state.users[username])
                    updated["password_hash"] = hash_pw(p1)
                    save_user_to_db(username, updated)
                    st.session_state.users = load_users_from_db()
                    st.session_state._dlg_action = None
                    st.session_state._dlg_target = None
                    st.rerun()

        # ── Dialog: Delete User ───────────────────────────────────────
        @st.dialog("🗑️ Delete User")
        def dialog_delete_user(username):
            st.warning(f"Are you sure you want to delete **{username}**? This cannot be undone.", icon="⚠️")
            c1, c2 = st.columns(2)
            if c1.button("🗑️ Yes, Delete", use_container_width=True, type="primary"):
                # Remove from session state
                if username in st.session_state.users:
                    del st.session_state.users[username]
                # Remove from DB
                delete_user_from_db(username)
                # Reload fresh from DB
                st.session_state.users = load_users_from_db()
                st.session_state._dlg_action = None
                st.session_state._dlg_target = None
                st.rerun()
            if c2.button("✖ Cancel", use_container_width=True):
                st.session_state._dlg_action = None
                st.session_state._dlg_target = None
                st.rerun()

        # ── Trigger state for dialogs ─────────────────────────────────
        for key in ["_dlg_action", "_dlg_target"]:
            if key not in st.session_state:
                st.session_state[key] = None

        # ── Toolbar: Add New button ───────────────────────────────────
        btn_col, _ = st.columns([1, 5])
        if btn_col.button("➕ Add New User", type="primary", use_container_width=True):
            st.session_state._dlg_action = "add"
            st.session_state._dlg_target = None

        st.markdown("---")

        # ── User Grid ────────────────────────────────────────────────
        users_list = list(st.session_state.users.items())
        if not users_list:
            st.info("No users found.")
        else:
            # Header row
            hc = st.columns([2.5, 2, 1.5, 2.5, 2])
            for col, label in zip(hc, ["Username", "Display Name", "Role", "Tenant Access", "Actions"]):
                col.markdown(f"**{label}**")
            st.markdown("<hr style='margin:4px 0 8px 0;'>", unsafe_allow_html=True)

            for uname, ud in users_list:
                rc = st.columns([2.5, 2, 1.5, 2.5, 2])
                rc[0].markdown(f"`{uname}`")
                rc[1].markdown(ud["display_name"])
                badge_color = "#2E7D32" if ud["role"] == "admin" else "#1565C0"
                rc[2].markdown(
                    f"<span style='background:{badge_color};color:white;padding:2px 10px;"
                    f"border-radius:12px;font-size:0.8rem;'>{ud['role'].capitalize()}</span>",
                    unsafe_allow_html=True,
                )
                rc[3].markdown(", ".join(ud["tenant_access"]) or "—")

                # Action buttons
                ab1, ab2, ab3 = rc[4].columns(3)
                if ab1.button("✏️", key=f"edit_{uname}", help="Edit user"):
                    st.session_state._dlg_action = "edit"
                    st.session_state._dlg_target = uname
                if ab2.button("🔑", key=f"pw_{uname}", help="Change password"):
                    st.session_state._dlg_action = "pw"
                    st.session_state._dlg_target = uname
                if uname != st.session_state.current_user:
                    if ab3.button("🗑️", key=f"del_{uname}", help="Delete user"):
                        st.session_state._dlg_action = "delete"
                        st.session_state._dlg_target = uname

        # ── Open correct dialog based on action state ─────────────────
        action = st.session_state._dlg_action
        target = st.session_state._dlg_target
        if action == "add":
            dialog_add_user()
        elif action == "edit" and target:
            dialog_edit_user(target)
        elif action == "pw" and target:
            dialog_change_pw(target)
        elif action == "delete" and target:
            dialog_delete_user(target)

    # ── TAB 2 : Tenant Management ─────────────────────────────────────
    with tab_tenants:

        # ── Section A: Tenant Types ───────────────────────────────────
        st.subheader("🗂️ Tenant Types")
        cur_types = load_tenant_types_from_db()
        if cur_types:
            st.dataframe(
                pd.DataFrame({"Tenant Type": cur_types}),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("No tenant types defined yet.")

        tt_add_col, tt_del_col = st.columns(2)

        with tt_add_col:
            with st.form("add_type_form", clear_on_submit=True):
                new_type_name = st.text_input("New Tenant Type", placeholder="e.g. Co-Working")
                add_type_btn  = st.form_submit_button("➕ Add Type", use_container_width=True)
            if add_type_btn:
                nt = new_type_name.strip()
                if not nt:
                    st.error("Type name cannot be empty.")
                elif nt in cur_types:
                    st.error("Type already exists.")
                else:
                    add_tenant_type_to_db(nt)
                    st.session_state.tenant_types = load_tenant_types_from_db()
                    st.success(f"Tenant type **{nt}** added.")
                    st.rerun()

        with tt_del_col:
            with st.form("del_type_form", clear_on_submit=True):
                del_type = st.selectbox(
                    "Delete Tenant Type",
                    cur_types if cur_types else ["(none)"],
                    key="del_type_sel",
                )
                del_type_btn = st.form_submit_button("🗑️ Delete Type", type="primary",
                                                      use_container_width=True)
            if del_type_btn and del_type != "(none)":
                delete_tenant_type_from_db(del_type)
                st.session_state.tenant_types = load_tenant_types_from_db()
                st.success(f"Tenant type **{del_type}** deleted.")
                st.rerun()

        st.markdown("---")

        # ── Section B: Tenants ────────────────────────────────────────
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
        tcol_add, tcol_edit, tcol_del = st.columns(3)

        # ── Add ──────────────────────────────────────────────────────
        with tcol_add:
            st.subheader("➕ Add Tenant")
            live_types = load_tenant_types_from_db()
            with st.form("add_tenant_form", clear_on_submit=True):
                new_tenant_name = st.text_input("Tenant Name", placeholder="e.g. Marina Bay Tower")
                new_tenant_type = st.selectbox(
                    "Tenant Type",
                    live_types if live_types else ["(no types defined)"]
                )
                add_tenant_btn = st.form_submit_button("Add Tenant", use_container_width=True)

            if add_tenant_btn:
                hn = new_tenant_name.strip()
                if not hn:
                    st.error("Tenant name cannot be empty.")
                elif hn in get_tenant_names():
                    st.error("Tenant already exists.")
                elif not live_types:
                    st.error("Please add at least one Tenant Type first.")
                else:
                    add_tenant_to_db(hn, new_tenant_type)
                    st.session_state.tenants = load_tenants_from_db()
                    st.success(f"**{hn}** added.")
                    st.rerun()

        # ── Edit (type only) ─────────────────────────────────────────
        with tcol_edit:
            st.subheader("✏️ Edit Tenant Type")
            tenant_name_list = get_tenant_names()
            live_types_edit  = load_tenant_types_from_db()
            # Build a lookup: name → current type
            tenant_type_map  = {t["name"]: t["type"] for t in load_tenants_from_db()}
            with st.form("edit_tenant_form", clear_on_submit=False):
                edit_tenant = st.selectbox(
                    "Select Tenant",
                    tenant_name_list if tenant_name_list else ["(none)"],
                    key="edit_tenant_sel",
                )
                # Pre-select current type
                cur_type = tenant_type_map.get(edit_tenant, "")
                safe_idx = live_types_edit.index(cur_type) if cur_type in live_types_edit else 0
                new_type = st.selectbox(
                    "New Tenant Type",
                    live_types_edit if live_types_edit else ["(no types defined)"],
                    index=safe_idx,
                    key="edit_tenant_type_sel",
                )
                edit_btn = st.form_submit_button("Update Type", use_container_width=True)

            if edit_btn and edit_tenant != "(none)":
                if not live_types_edit:
                    st.error("No tenant types available.")
                else:
                    update_tenant_type_in_db(edit_tenant, new_type)
                    st.session_state.tenants = load_tenants_from_db()
                    st.success(f"**{edit_tenant}** updated to *{new_type}*.")
                    st.rerun()

        # ── Delete ───────────────────────────────────────────────────
        with tcol_del:
            st.subheader("🗑️ Delete Tenant")
            st.warning("Assessment data will NOT be removed.", icon="⚠️")
            with st.form("del_tenant_form", clear_on_submit=True):
                del_tenant = st.selectbox(
                    "Select Tenant",
                    tenant_name_list if tenant_name_list else ["(none)"],
                    key="del_tenant_sel",
                )
                del_tenant_btn = st.form_submit_button("Delete Tenant", type="primary",
                                                       use_container_width=True)

            if del_tenant_btn and del_tenant != "(none)":
                delete_tenant_from_db(del_tenant)
                for uname, ud in st.session_state.users.items():
                    if del_tenant in ud["tenant_access"]:
                        ud["tenant_access"] = [t for t in ud["tenant_access"] if t != del_tenant]
                        save_user_to_db(uname, ud)
                st.session_state.tenants = load_tenants_from_db()
                st.session_state.users   = load_users_from_db()
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

    valid_tenant_names = get_tenant_names()
    safe_tenant_access = [t for t in tenant_access if t in valid_tenant_names]

    f_col, clr_col = st.columns([4, 1])
    with f_col:
        tenant_filter = st.multiselect(
            "Filter View", valid_tenant_names, default=safe_tenant_access,
            key="assess_filter")
    with clr_col:
        st.markdown('<p style="margin-bottom:28px;"></p>', unsafe_allow_html=True)
        clear_btn = st.button("🗑️ Clear My Data", use_container_width=True)

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
            if clear_btn:
                other = st.session_state.tenant_data[
                    ~st.session_state.tenant_data["Tenant Name"].isin(tenant_access)
                ]
                st.session_state.tenant_data = other.reset_index(drop=True)
                st.rerun()
        else:
            st.warning("No data matches the selected filters.")

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# NAV RAIL  (Streamlit sidebar styled as icon rail)
# ─────────────────────────────────────────────

RAIL_CSS = """
<style>
/* Shrink sidebar to icon-width */
[data-testid="stSidebar"] {
    min-width: 64px !important;
    max-width: 64px !important;
    background: #1a2535 !important;
}
[data-testid="stSidebar"] > div:first-child {
    padding: 0.5rem 0 !important;
    width: 64px !important;
}
/* Hide sidebar collapse arrow */
[data-testid="collapsedControl"] { display: none !important; }

/* Style every button in sidebar as an icon button */
[data-testid="stSidebar"] button {
    width: 52px !important;
    height: 52px !important;
    margin: 2px auto !important;
    padding: 0 !important;
    border-radius: 10px !important;
    border: none !important;
    background: transparent !important;
    color: #9ab0c8 !important;
    font-size: 1.3rem !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    cursor: pointer !important;
    transition: background .15s, color .15s !important;
}
[data-testid="stSidebar"] button:hover {
    background: #243448 !important;
    color: #fff !important;
}
[data-testid="stSidebar"] button[kind="primary"] {
    background: #2563eb !important;
    color: #fff !important;
}
[data-testid="stSidebar"] button[kind="primary"]:hover {
    background: #1d50c8 !important;
}
/* Hide any text labels streamlit adds */
[data-testid="stSidebar"] .stButton p { display: none !important; }
/* Hide markdown / other noise */
[data-testid="stSidebar"] hr { border-color: #2e3f52 !important; margin: 4px 6px !important; }

/* Top-right user badge */
#np-topbar {
    position: fixed; top: 10px; right: 16px;
    display: flex; align-items: center; gap: 7px;
    z-index: 9999;
    background: #1a2535;
    border: 1px solid #2e3f52;
    border-radius: 20px;
    padding: 3px 12px 3px 8px;
}
.np-avatar {
    width: 30px; height: 30px; border-radius: 50%;
    background: #2563eb;
    display: flex; align-items: center; justify-content: center;
    color: #fff; font-weight: 700; font-size: .85rem;
}
.np-uname { color: #c9d8e8; font-size: .79rem; font-weight: 600; white-space: nowrap; }
.np-urole {
    background: #2e4a66; color: #7ec8e3;
    border-radius: 10px; padding: 1px 7px;
    font-size: .67rem; font-weight: 700; white-space: nowrap;
}
</style>
"""


def render_nav_rail(display_name, role, active_tab, is_admin):
    """Slim icon rail using Streamlit sidebar + top-right user badge."""
    st.markdown(RAIL_CSS, unsafe_allow_html=True)

    # ── Top-right user badge ──────────────────────────────────────
    avatar = display_name[0].upper() if display_name else "U"
    short  = display_name.split("@")[0] if "@" in display_name else display_name
    role_label = "Admin" if role == "admin" else "User"
    st.markdown(
        f"<div id='np-topbar'>"
        f"<div class='np-avatar'>{avatar}</div>"
        f"<span class='np-uname'>{short}</span>"
        f"<span class='np-urole'>{role_label}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Sidebar icon buttons ──────────────────────────────────────
    with st.sidebar:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # Logo icon (non-clickable)
        st.markdown(
            "<div style='width:52px;height:52px;margin:2px auto;display:flex;"
            "align-items:center;justify-content:center;font-size:1.4rem;'>🏗️</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<hr>", unsafe_allow_html=True)

        if is_admin:
            if st.button("🏢", key="nav_assess",
                         type="primary" if active_tab == "assessment" else "secondary",
                         help="Assessment", use_container_width=False):
                st.session_state.active_tab = "assessment"
                st.rerun()

            if st.button("⚙️", key="nav_admin",
                         type="primary" if active_tab == "admin" else "secondary",
                         help="Admin Panel", use_container_width=False):
                st.session_state.active_tab = "admin"
                st.rerun()
        else:
            if st.button("🏢", key="nav_assess",
                         type="primary",
                         help="Assessment", use_container_width=False):
                st.session_state.active_tab = "assessment"
                st.rerun()

        # Push logout to bottom
        st.markdown(
            "<div style='position:absolute;bottom:20px;left:0;width:64px;'>"
            "<hr style='border-color:#2e3f52;margin:0 6px 4px;'>",
            unsafe_allow_html=True,
        )
        if st.button("🚪", key="nav_logout", help="Logout", use_container_width=False):
            for k in ["logged_in","current_user","current_role","active_tab",
                      "_dlg_action","_dlg_target"]:
                st.session_state.pop(k, None)
            st.session_state.logged_in  = False
            st.session_state.active_tab = "assessment"
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# MAIN SHELL
# ─────────────────────────────────────────────
if not st.session_state.logged_in:
    show_login()
else:
    ud       = st.session_state.users[st.session_state.current_user]
    is_admin = st.session_state.current_role == "admin"

    render_nav_rail(
        display_name=ud["display_name"],
        role=st.session_state.current_role,
        active_tab=st.session_state.active_tab,
        is_admin=is_admin,
    )

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
