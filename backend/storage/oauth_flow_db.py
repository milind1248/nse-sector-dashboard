"""
Server-side PKCE verifier storage for the Google OAuth login flow.
Schema lives in scripts/supabase_schema.sql (oauth_pkce_flow table).

Not a browser cookie: on Streamlit Cloud the app renders inside nested
iframes and the OAuth round trip completes in a separate tab, and a cookie
set that deep did not reliably survive the trip in production. Instead the
flow_id travels in redirect_to's query string (Supabase's PKCE redirect
preserves extra query params alongside its own "code" param), and the
verifier itself stays server-side the whole time.
"""
from datetime import datetime, timedelta

from backend.storage.db import get_conn

_MAX_AGE = timedelta(minutes=10)


def store_flow(flow_id: str, code_verifier: str) -> None:
    con = get_conn()
    con.execute(
        "INSERT INTO oauth_pkce_flow (flow_id, code_verifier, created_at) VALUES (%s, %s, %s)",
        (flow_id, code_verifier, datetime.now()),
    )
    con.commit()
    con.close()


def pop_flow(flow_id: str) -> str | None:
    """Fetch and delete the verifier for flow_id in one round trip — one-time use.
    Returns None if the id is unknown or older than _MAX_AGE."""
    con = get_conn()
    row = con.execute(
        "DELETE FROM oauth_pkce_flow WHERE flow_id = %s RETURNING code_verifier, created_at",
        (flow_id,),
    ).fetchone()
    con.commit()
    con.close()
    if row is None:
        return None
    verifier, created_at = row
    if datetime.now(created_at.tzinfo) - created_at > _MAX_AGE:
        return None
    return verifier
