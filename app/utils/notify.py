"""
Admin email notifications via Web3Forms — the same access key already used
by app/pages/15_📧_Contact.py.

Web3Forms' free plan rejects server-side (Python) POST requests — confirmed:
calling https://api.web3forms.com/submit directly from Python returns
403 "Use our API in client side ... (Pro plan is required)". So this fires
the same JS fetch() Contact.py already uses, but invisibly and automatically
instead of from a visible form — it's a real browser request, which Web3Forms
accepts, just triggered without the visitor doing anything.

Two-step because a component rendered right before st.rerun() gets torn down
before its JS can run: queue_notification() stashes the message in
st.session_state (same pattern as the existing "_flash" messages), and
render_pending_notification() — called from render_auth_sidebar() so it runs
on literally every page — pops and fires it on the *next* page load, a stable
render that has time to complete the fetch.
"""
import json

import streamlit as st
import streamlit.components.v1 as components


def _js_str(s: str) -> str:
    """JSON-encode for safe embedding in a <script> tag, guarding against a
    user-supplied note/message containing '</script>' breaking out of it."""
    return json.dumps(s).replace("</", "<\\/")


def queue_notification(subject: str, message: str) -> None:
    st.session_state["_pending_notification"] = (subject, message)


def render_pending_notification() -> None:
    pending = st.session_state.pop("_pending_notification", None)
    if pending is None:
        return
    try:
        key = st.secrets["contact"]["web3forms_key"]
    except Exception:
        return
    subject, message = pending
    components.html(
        f"""
        <script>
        fetch('https://api.web3forms.com/submit', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json', 'Accept': 'application/json'}},
          body: JSON.stringify({{
            access_key: {_js_str(key)},
            subject: {_js_str(subject)},
            from_name: 'Market Sector Analysis',
            message: {_js_str(message)},
          }}),
        }}).catch(function() {{}});
        </script>
        """,
        height=0,
    )
