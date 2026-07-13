"""
Per-visitor login via Supabase Auth (Google OAuth + email/password).

Separate from app/utils/auth.py (single shared site-owner admin password) —
a different concern with a different secret and a different session lifetime.
Do not touch auth.py from here.

Session is deliberately NOT persisted in a cookie: it lives only in
st.session_state for the current browser tab, same as the existing admin
login and Paper Trading's `trader_id` placeholder. One short-lived cookie is
still needed regardless — carrying the PKCE code_verifier across the external
Google -> Supabase -> app redirect, which st.session_state cannot survive.

Without [supabase] url/anon_key configured in secrets.toml, every function
here is a safe no-op — render_auth_sidebar() shows nothing rather than
raising, mirroring auth.py's "silently disabled without secrets" philosophy.

Each Supabase call gets a *fresh, uncached* client (see _new_client) rather
than a shared st.cache_resource singleton: the SDK's auth client keeps
per-call state (PKCE verifier, session) in an in-memory storage object on the
client instance, which would leak across concurrent visitors on the same
Streamlit server process if the client were shared.
"""
import logging
from urllib.parse import urlencode

import streamlit as st
import streamlit.components.v1 as components

logger = logging.getLogger(__name__)

_PKCE_COOKIE = "nse_pkce_verifier"


def _supabase_config() -> tuple[str, str] | None:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["anon_key"]
        if not url or not key:
            return None
        return url.rstrip("/"), key
    except Exception:
        return None


def _new_client():
    cfg = _supabase_config()
    if cfg is None:
        return None
    from supabase import create_client
    url, key = cfg
    return create_client(url, key)


def _app_url() -> str:
    host = st.context.headers.get("host", "localhost:8501")
    scheme = "http" if host.startswith("localhost") or host.startswith("127.0.0.1") else "https"
    return f"{scheme}://{host}"


def _set_cookie(name: str, value: str, max_age_seconds: int):
    secure = not _app_url().startswith("http://")
    flags = "Path=/; SameSite=Lax" + ("; Secure" if secure else "")
    components.html(
        f"<script>document.cookie = \"{name}={value}; Max-Age={max_age_seconds}; {flags}\";</script>",
        height=0,
    )


def _clear_cookie(name: str):
    components.html(
        f"<script>document.cookie = \"{name}=; Max-Age=0; Path=/; SameSite=Lax\";</script>",
        height=0,
    )


def _friendly_error(e: Exception) -> str:
    return getattr(e, "message", None) or str(e) or "Something went wrong. Please try again."


def _extract_name_avatar(user) -> tuple[str | None, str | None]:
    meta = user.user_metadata or {}
    full_name = meta.get("full_name") or meta.get("name")
    avatar_url = meta.get("avatar_url") or meta.get("picture")
    return full_name, avatar_url


def _login_user(user, auth_provider: str):
    from backend.storage import profiles_db
    full_name, avatar_url = _extract_name_avatar(user)
    display_name = full_name or (user.email.split("@")[0] if user.email else "there")
    profiles_db.upsert_profile(user.id, user.email, full_name, avatar_url, auth_provider)
    st.session_state["_user"] = {
        "id": user.id,
        "email": user.email,
        "full_name": display_name,
        "avatar_url": avatar_url,
    }


# ── Public session accessors ────────────────────────────────────────────────────

def current_user() -> dict | None:
    return st.session_state.get("_user")


def is_logged_in() -> bool:
    return "_user" in st.session_state


def logout():
    st.session_state.pop("_user", None)


# ── Email / password ─────────────────────────────────────────────────────────────

def sign_in_with_password(email: str, password: str) -> tuple[bool, str]:
    client = _new_client()
    if client is None:
        return False, "Sign-in is not configured."
    try:
        resp = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        return False, _friendly_error(e)
    if resp.user is None:
        return False, "Invalid email or password."
    _login_user(resp.user, "email")
    return True, ""


def sign_up(email: str, password: str, full_name: str) -> tuple[bool, str]:
    client = _new_client()
    if client is None:
        return False, "Sign-up is not configured."
    try:
        resp = client.auth.sign_up({
            "email": email,
            "password": password,
            # Without this, Supabase falls back to the dashboard's static
            # Site URL for the confirmation email link — wrong whenever the
            # sign-up didn't happen from that exact origin (e.g. local
            # testing vs production). Always point at wherever this request
            # actually came from, same as the Google button's redirect_to.
            "options": {"data": {"full_name": full_name}, "email_redirect_to": _app_url()},
        })
    except Exception as e:
        return False, _friendly_error(e)
    if resp.user is None:
        return False, "Sign-up failed. Please try again."
    if resp.session is None:
        return False, "Account created — check your email to confirm it, then sign in."
    _login_user(resp.user, "email")
    return True, ""


# ── Google OAuth (PKCE) ──────────────────────────────────────────────────────────

def _render_google_button():
    """Renders a link button that starts the Google OAuth round trip.

    Not a regular st.button + JS redirect: st.components.v1.html renders in a
    sandboxed iframe, and browsers block top-level navigation from a
    sandboxed iframe unless explicitly permitted — window.top.location.href
    there is silently blocked. st.link_button renders a real <a> in the page
    itself, so it always navigates. It opens in a new tab (Streamlit's own
    behavior for link_button); the new tab completes the OAuth round trip and
    ends up signed in there — acceptable given session state isn't persisted
    across tabs anyway (see module docstring).

    The PKCE cookie is (re)set on every render of this button, not only on
    click, since components.html can't know when the link is actually
    clicked — regenerating it each render just means the cookie always
    reflects the most recent verifier, which is the one that matters.
    """
    cfg = _supabase_config()
    if cfg is None:
        return
    from supabase_auth.helpers import generate_pkce_challenge, generate_pkce_verifier

    url, _key = cfg
    verifier = generate_pkce_verifier()
    challenge = generate_pkce_challenge(verifier)
    params = urlencode({
        "provider": "google",
        "redirect_to": _app_url(),
        "code_challenge": challenge,
        "code_challenge_method": "s256",
    })
    authorize_url = f"{url}/auth/v1/authorize?{params}"

    secure = not _app_url().startswith("http://")
    flags = "Path=/; SameSite=Lax" + ("; Secure" if secure else "")
    components.html(
        f'<script>document.cookie = "{_PKCE_COOKIE}={verifier}; Max-Age=600; {flags}";</script>',
        height=0,
    )
    st.link_button("Continue with Google", authorize_url, width="stretch")


def handle_oauth_callback():
    """Call once, from app/Home.py only — Supabase's Site URL/redirect_to points there."""
    error_desc = st.query_params.get("error_description") or st.query_params.get("error")
    code = st.query_params.get("code")
    if not code and not error_desc:
        return
    st.query_params.pop("code", None)
    st.query_params.pop("error", None)
    st.query_params.pop("error_description", None)

    if error_desc:
        logger.warning("Google OAuth callback returned an error: %s", error_desc)
        st.session_state["_auth_flash"] = ("error", f"Google sign-in failed: {error_desc}")
        st.rerun()

    verifier = st.context.cookies.get(_PKCE_COOKIE)
    if not verifier:
        logger.warning("Google OAuth callback: code present but nse_pkce_verifier cookie missing")
        st.session_state["_auth_flash"] = (
            "error", "Google sign-in failed: your session expired before the redirect completed. Please try again."
        )
        _clear_cookie(_PKCE_COOKIE)
        st.rerun()

    client = _new_client()
    if client is None:
        _clear_cookie(_PKCE_COOKIE)
        st.rerun()

    try:
        resp = client.auth.exchange_code_for_session({
            "auth_code": code, "code_verifier": verifier,
        })
        if resp.user is not None:
            _login_user(resp.user, "google")
        else:
            logger.warning("Google OAuth exchange_code_for_session returned no user")
            st.session_state["_auth_flash"] = ("error", "Google sign-in failed. Please try again.")
    except Exception as e:
        logger.warning("Google OAuth exchange_code_for_session failed: %s", e)
        st.session_state["_auth_flash"] = ("error", f"Google sign-in failed: {_friendly_error(e)}")
    _clear_cookie(_PKCE_COOKIE)
    st.rerun()


# ── Sidebar UI ────────────────────────────────────────────────────────────────────

@st.dialog("Sign In")
def _auth_dialog():
    tab_in, tab_up = st.tabs(["Sign In", "Sign Up"])

    with tab_in:
        with st.form("_signin_form"):
            email = st.text_input("Email", key="_si_email")
            pwd = st.text_input("Password", type="password", key="_si_pwd")
            submitted = st.form_submit_button("Sign In", width="stretch", type="primary")
        if submitted:
            ok, msg = sign_in_with_password(email, pwd)
            if ok:
                st.session_state["_show_auth_dialog"] = False
                st.rerun()
            else:
                st.error(msg)

        st.markdown("<div style='text-align:center;color:#666;margin:8px 0;'>or</div>",
                    unsafe_allow_html=True)
        _render_google_button()
        st.caption("Opens in a new tab — you'll be signed in there.")

    with tab_up:
        with st.form("_signup_form"):
            name = st.text_input("Full name", key="_su_name")
            email2 = st.text_input("Email", key="_su_email")
            pwd2 = st.text_input("Password", type="password", key="_su_pwd",
                                  help="At least 6 characters.")
            submitted2 = st.form_submit_button("Sign Up", width="stretch", type="primary")
        if submitted2:
            ok, msg = sign_up(email2, pwd2, name)
            if ok:
                st.session_state["_show_auth_dialog"] = False
                st.rerun()
            elif "confirm" in msg.lower():
                st.info(msg)
            else:
                st.error(msg)


def render_auth_sidebar():
    """Call inside `with st.sidebar:` on every page. No-op if Supabase isn't configured."""
    if _supabase_config() is None:
        return

    flash = st.session_state.pop("_auth_flash", None)
    if flash:
        kind, msg = flash
        (st.error if kind == "error" else st.success)(msg)

    user = current_user()
    if user:
        st.markdown(
            f"<div style='font-size:12px;color:#8899bb;margin:2px 0 6px 0;'>"
            f"welcome <b style='color:#ddd'>{user['full_name']}</b></div>",
            unsafe_allow_html=True,
        )
        if st.button("Sign out", key="_auth_signout", width="stretch"):
            logout()
            st.rerun()
        return

    if st.button("🔓 Sign In", key="_auth_signin_trigger", width="stretch"):
        st.session_state["_show_auth_dialog"] = True

    if st.session_state.get("_show_auth_dialog"):
        _auth_dialog()
