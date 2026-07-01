"""
Admin authentication utilities.

Security model:
- bcrypt hash of admin password stored in .streamlit/secrets.toml [admin] section
- secrets.toml is gitignored — hash never reaches GitHub
- On login, a time-stamped HMAC token (signed with secret_key from secrets.toml)
  is stored in st.session_state; is_admin() re-derives and compares it in constant time
- Without [admin] section in secrets.toml, verify_password() always returns False
  and is_admin() always returns False — admin UI simply never appears
"""
import hashlib
import hmac
import time

import bcrypt
import streamlit as st

_SESSION_EXPIRY = 1800  # 30 minutes


def _secret_key() -> bytes:
    try:
        return bytes.fromhex(st.secrets["admin"]["secret_key"])
    except Exception:
        return b""


def _make_token(ts: float) -> str:
    return hmac.new(_secret_key(), f"admin:{ts}".encode(), hashlib.sha256).hexdigest()


def is_admin() -> bool:
    """True only if the current session holds a valid, unexpired HMAC-signed token."""
    ts    = st.session_state.get("_admin_ts", 0)
    token = st.session_state.get("_admin_token", "")
    if not token or time.time() - ts > _SESSION_EXPIRY:
        if token:
            logout()
        return False
    expected = _make_token(ts)
    return hmac.compare_digest(token, expected)


def verify_password(entered: str) -> bool:
    """Check entered password against stored bcrypt hash. Returns False if no hash configured."""
    try:
        stored = st.secrets["admin"]["password_hash"].encode()
        return bcrypt.checkpw(entered.encode(), stored)
    except Exception:
        return False


def logout():
    """Clear admin session tokens."""
    for key in ("_admin_token", "_admin_ts"):
        st.session_state.pop(key, None)


def login_form() -> bool:
    """
    Render a centered admin login form.
    Returns True the moment a correct password is submitted (caller should st.rerun()).
    """
    try:
        st.secrets["admin"]["password_hash"]
    except Exception:
        st.error(
            "Admin credentials not configured. "
            "Run `python scripts/setup_admin.py` to set an admin password."
        )
        return False

    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.markdown("### 🔐 Admin Login")
        with st.form("_admin_login_form", clear_on_submit=True):
            pwd       = st.text_input("Password", type="password", placeholder="Enter admin password")
            submitted = st.form_submit_button("Login", width='stretch', type="primary")
        if submitted:
            if verify_password(pwd):
                ts = time.time()
                st.session_state["_admin_ts"]    = ts
                st.session_state["_admin_token"] = _make_token(ts)
                return True
            else:
                st.error("Incorrect password.")
    return False


def require_admin():
    """
    Call at the top of any admin-only page.
    Shows login form and stops page execution if not authenticated.
    """
    if not is_admin():
        login_form_result = login_form()
        if login_form_result:
            st.rerun()
        st.stop()


def session_remaining_minutes() -> int:
    """Return how many minutes remain in the current admin session."""
    ts = st.session_state.get("_admin_ts", 0)
    remaining = max(0, _SESSION_EXPIRY - (time.time() - ts))
    return int(remaining // 60)
