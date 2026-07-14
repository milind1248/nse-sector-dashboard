"""
Supabase (Postgres) persistence for user profiles created via Supabase Auth
(Google OAuth + email/password). Schema lives in scripts/supabase_schema.sql;
this module only does CRUD against the already-created `profiles` table.

`id` is the UUID from Supabase Auth's auth.users.id — the same id the
Supabase SDK returns in the session's user object after sign-in/sign-up/OAuth
exchange, and the same id Paper Trading now uses as its `trader_id`
(see backend/storage/paper_trading_db.py).
"""
from datetime import datetime

from backend.storage.db import get_conn


def upsert_profile(user_id: str, email: str, full_name: str | None,
                    avatar_url: str | None, auth_provider: str) -> bool:
    """Insert a new profile row or refresh it on every login.

    full_name/avatar_url only overwrite existing values when the new value is
    non-null — email/password logins after an initial Google sign-in
    shouldn't blank out the avatar Google provided, and vice versa.

    Returns True if this call actually created the row (a genuinely new
    user), False if it updated an existing one — xmax = 0 is a standard
    Postgres idiom that's true only for a fresh insert, never for a row
    touched via the ON CONFLICT path.
    """
    now = datetime.now()
    con = get_conn()
    row = con.execute("""
        INSERT INTO profiles (id, email, full_name, avatar_url, auth_provider,
                               created_at, last_login_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            email         = EXCLUDED.email,
            full_name     = COALESCE(EXCLUDED.full_name, profiles.full_name),
            avatar_url    = COALESCE(EXCLUDED.avatar_url, profiles.avatar_url),
            last_login_at = EXCLUDED.last_login_at
        RETURNING (xmax = 0) AS inserted
    """, (user_id, email, full_name, avatar_url, auth_provider, now, now)).fetchone()
    con.commit()
    con.close()
    return bool(row[0]) if row else False


def get_profile(user_id: str) -> dict | None:
    con = get_conn()
    row = con.execute("""
        SELECT id, email, full_name, avatar_url, auth_provider,
               subscription_tier, subscription_status, created_at, last_login_at,
               phone, alt_email, address
        FROM profiles WHERE id = %s
    """, (user_id,)).fetchone()
    con.close()
    if row is None:
        return None
    cols = ["id", "email", "full_name", "avatar_url", "auth_provider",
            "subscription_tier", "subscription_status", "created_at", "last_login_at",
            "phone", "alt_email", "address"]
    return dict(zip(cols, row))


def touch_last_login(user_id: str) -> None:
    con = get_conn()
    con.execute("UPDATE profiles SET last_login_at = %s WHERE id = %s",
                (datetime.now(), user_id))
    con.commit()
    con.close()


def update_profile(user_id: str, full_name: str | None, phone: str | None,
                    alt_email: str | None, address: str | None) -> None:
    con = get_conn()
    con.execute("""
        UPDATE profiles SET full_name = %s, phone = %s, alt_email = %s, address = %s
        WHERE id = %s
    """, (full_name, phone, alt_email, address, user_id))
    con.commit()
    con.close()
