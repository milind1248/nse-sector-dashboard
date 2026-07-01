"""
Deployment protection gate.
Both checks must pass: HMAC-signed license key + allowed host header.
A cloner who has no secrets.toml [deploy] section is blocked immediately.
Even with a forged key they are blocked by the host check.
"""
import hmac
import hashlib
import os
import streamlit as st

_ALLOWED_HOSTS = {"marketsector.streamlit.app", "localhost", "127.0.0.1"}
_DEPLOYMENT_ID = "marketsector"


def _expected_license() -> str:
    try:
        secret = bytes.fromhex(st.secrets["admin"]["secret_key"])
        return hmac.new(secret, _DEPLOYMENT_ID.encode(), hashlib.sha256).hexdigest()
    except Exception:
        return ""


def enforce_deployment_gate():
    # Bypass during automated page tests (set by backend/page_tester.py)
    if os.environ.get("NSE_TESTING") == "1":
        return

    host    = st.context.headers.get("host", "").lower().split(":")[0]
    ok_host = host in _ALLOWED_HOSTS

    try:
        provided = st.secrets["deploy"]["license_key"]
        ok_key   = bool(provided) and hmac.compare_digest(provided, _expected_license())
    except Exception:
        ok_key = False

    if not (ok_host and ok_key):
        st.markdown("## 🔒 Unauthorised Deployment")
        st.info(
            "This application is only licensed to run at its official deployment. "
            "Cloned or forked copies are not authorised to operate."
        )
        st.stop()
