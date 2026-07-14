"""
Per-visitor login via Supabase Auth (Google OAuth + email/password).

Separate from app/utils/auth.py (single shared site-owner admin password) —
a different concern with a different secret and a different session lifetime.
Do not touch auth.py from here.

Session is deliberately NOT persisted in a cookie: it lives only in
st.session_state for the current browser tab, same as the existing admin
login and Paper Trading's `trader_id` placeholder.

The Google OAuth round trip's PKCE code_verifier is carried server-side
(backend/storage/oauth_flow_db.py), not in a browser cookie — on Streamlit
Cloud the app renders inside nested iframes and the flow completes in a
separate tab, and a cookie set that deep did not reliably survive the trip
in production testing. A random flow_id travels instead in redirect_to's
query string, which Supabase's PKCE redirect preserves alongside its own
"code" param.

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
import secrets as _secrets
from urllib.parse import urlencode

import streamlit as st

logger = logging.getLogger(__name__)


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
    st.session_state["_show_auth_dialog"] = False


# ── Public session accessors ────────────────────────────────────────────────────

def current_user() -> dict | None:
    return st.session_state.get("_user")


def is_logged_in() -> bool:
    return "_user" in st.session_state


def logout():
    st.session_state.pop("_user", None)
    st.session_state["_show_auth_dialog"] = False


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
    """Renders a Google-branded link that starts the OAuth round trip.

    Not a regular st.button + JS redirect: st.components.v1.html renders in a
    sandboxed iframe, and browsers block top-level navigation from a
    sandboxed iframe unless explicitly permitted — window.top.location.href
    there is silently blocked. A hand-rendered <a> via st.markdown lives
    directly in the page's own DOM (same mechanism app/utils/logo.py already
    uses), not inside any iframe, so it navigates reliably — same property
    st.link_button had, needed here instead because st.link_button's icon=
    only accepts an emoji/Material-Symbols string, never Google's real
    multicolor "G" mark. It opens in a new tab; that tab completes the OAuth
    round trip and ends up signed in there — acceptable given session state
    isn't persisted across tabs anyway (see module docstring).

    The code_verifier is stored server-side (oauth_flow_db), keyed by a fresh
    flow_id that rides along in redirect_to's query string — regenerated on
    every render of this button, not only on click, for the same reason the
    old cookie was: nothing here can know exactly when the link gets clicked,
    so each render's flow_id/verifier pair is simply the one that matters,
    the one baked into the currently-displayed link's href.
    """
    cfg = _supabase_config()
    if cfg is None:
        return
    from supabase_auth.helpers import generate_pkce_challenge, generate_pkce_verifier

    from backend.storage import oauth_flow_db

    url, _key = cfg
    verifier = generate_pkce_verifier()
    challenge = generate_pkce_challenge(verifier)
    flow_id = _secrets.token_urlsafe(16)
    try:
        oauth_flow_db.store_flow(flow_id, verifier)
    except Exception as e:
        logger.warning("Failed to store OAuth flow state: %s", e)
        st.caption("Google sign-in is temporarily unavailable.")
        return

    redirect_to = f"{_app_url()}/?nse_flow={flow_id}"
    params = urlencode({
        "provider": "google",
        "redirect_to": redirect_to,
        "code_challenge": challenge,
        "code_challenge_method": "s256",
    })
    authorize_url = f"{url}/auth/v1/authorize?{params}"
    st.markdown(f"""
        <style>
        .nse-google-btn {{
            display:flex;align-items:center;justify-content:center;gap:10px;
            width:100%;box-sizing:border-box;
            padding:0.4rem 0.75rem;min-height:2.5rem;
            border:1px solid rgba(230,237,243,0.2);border-radius:0.5rem;
            background-color:transparent;color:#E6EDF3;
            font-family:inherit;font-size:1rem;text-decoration:none;
            transition:border-color .2s ease,color .2s ease;
        }}
        .nse-google-btn:hover {{ border-color:#2979FF;color:#2979FF; }}
        </style>
        <a class="nse-google-btn" href="{authorize_url}" target="_blank" rel="noopener noreferrer">
          <svg width="18" height="18" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0;">
            <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
            <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
            <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
            <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
          </svg>
          <span>Continue with Google</span>
        </a>
    """, unsafe_allow_html=True)


def handle_oauth_callback():
    """Call once, from app/Home.py only — Supabase's Site URL/redirect_to points there."""
    error_desc = st.query_params.get("error_description") or st.query_params.get("error")
    code = st.query_params.get("code")
    flow_id = st.query_params.get("nse_flow")
    if not code and not error_desc:
        return
    st.query_params.pop("code", None)
    st.query_params.pop("error", None)
    st.query_params.pop("error_description", None)
    st.query_params.pop("nse_flow", None)

    if error_desc:
        logger.warning("Google OAuth callback returned an error: %s", error_desc)
        st.session_state["_auth_flash"] = ("error", f"Google sign-in failed: {error_desc}")
        st.rerun()

    from backend.storage import oauth_flow_db
    try:
        verifier = oauth_flow_db.pop_flow(flow_id) if flow_id else None
    except Exception as e:
        logger.warning("Failed to look up OAuth flow state: %s", e)
        verifier = None
    if not verifier:
        logger.warning("Google OAuth callback: code present but flow_id %r not found/expired", flow_id)
        st.session_state["_auth_flash"] = (
            "error", "Google sign-in failed: this link expired or was already used. Please try again."
        )
        st.rerun()

    client = _new_client()
    if client is None:
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
    st.rerun()


# ── Sidebar UI ────────────────────────────────────────────────────────────────────

def _on_dialog_dismiss():
    """Dismissing via the X, Esc, or clicking outside only closes the dialog on
    the frontend — it doesn't touch our own _show_auth_dialog flag, which would
    otherwise stay True and pop the dialog straight back open on the next
    rerun (e.g. navigating to another page)."""
    st.session_state["_show_auth_dialog"] = False


@st.dialog("Sign In", on_dismiss=_on_dialog_dismiss)
def _auth_dialog():
    # Above the tabs, not just under the Google button — st.tabs renders both
    # tab bodies every run, so this covers the Sign Up (email) path too,
    # which otherwise has no consent language of its own.
    st.caption(
        "By continuing, you agree to our [Terms of Service](/Disclaimer) "
        "and acknowledge that you have read our [Privacy Policy](/Disclaimer)."
    )
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
            f"<div style='font-size:13px;margin:2px 0 6px 0;'>"
            f"<span style='color:#2979FF;font-weight:600'>Welcome</span>, "
            f"<b style='color:#4ade80'>{user['full_name']}</b></div>",
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
