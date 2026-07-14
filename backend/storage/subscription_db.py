"""
Monetization storage: groups, per-group page access, subscription grants,
and payment history. profiles.subscription_tier doubles as the user's
current group name; profiles.subscription_status doubles as the
suspend/activate flag ('active' | 'suspended') — see scripts/supabase_schema.sql.
"""
from datetime import date

from backend.storage.db import get_conn


# ── Groups ──────────────────────────────────────────────────────────────────

def list_groups() -> list[dict]:
    con = get_conn()
    rows = con.execute("""
        SELECT name, display_name, price_inr, is_default, sort_order
        FROM auth_groups ORDER BY sort_order, name
    """).fetchall()
    con.close()
    cols = ["name", "display_name", "price_inr", "is_default", "sort_order"]
    return [dict(zip(cols, r)) for r in rows]


def upsert_group(name: str, display_name: str, price_inr: float, is_default: bool = False,
                  sort_order: int = 0) -> None:
    con = get_conn()
    if is_default:
        con.execute("UPDATE auth_groups SET is_default = FALSE WHERE name != %s", (name,))
    con.execute("""
        INSERT INTO auth_groups (name, display_name, price_inr, is_default, sort_order)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (name) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            price_inr    = EXCLUDED.price_inr,
            is_default   = EXCLUDED.is_default,
            sort_order   = EXCLUDED.sort_order
    """, (name, display_name, price_inr, is_default, sort_order))
    con.commit()
    con.close()


def delete_group(name: str) -> tuple[bool, str]:
    con = get_conn()
    row = con.execute("SELECT is_default FROM auth_groups WHERE name = %s", (name,)).fetchone()
    if row is None:
        con.close()
        return False, "Group not found."
    if row[0]:
        con.close()
        return False, "Cannot delete the default group."
    con.execute("DELETE FROM auth_groups WHERE name = %s", (name,))
    con.commit()
    con.close()
    return True, ""


def _default_group() -> str:
    con = get_conn()
    row = con.execute("SELECT name FROM auth_groups WHERE is_default = TRUE LIMIT 1").fetchone()
    con.close()
    return row[0] if row else "silver"


# ── Group → page access ────────────────────────────────────────────────────

def get_group_pages(group_name: str) -> list[str]:
    con = get_conn()
    rows = con.execute(
        "SELECT page_key FROM group_page_access WHERE group_name = %s ORDER BY page_key",
        (group_name,)
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def set_group_pages(group_name: str, page_keys: list[str]) -> None:
    con = get_conn()
    con.execute("DELETE FROM group_page_access WHERE group_name = %s", (group_name,))
    for pk in page_keys:
        con.execute(
            "INSERT INTO group_page_access (group_name, page_key) VALUES (%s, %s)",
            (group_name, pk)
        )
    con.commit()
    con.close()


# ── Users ───────────────────────────────────────────────────────────────────

def list_users(search: str | None = None) -> list[dict]:
    con = get_conn()
    sql = """
        SELECT p.id, p.email, p.full_name, p.subscription_tier, p.subscription_status,
               p.last_login_at, p.created_at,
               (SELECT MAX(period_end) FROM user_subscriptions
                WHERE user_id = p.id AND status = 'active') AS current_period_end
        FROM profiles p
    """
    params: tuple = ()
    if search:
        sql += " WHERE p.email ILIKE %s OR p.full_name ILIKE %s"
        like = f"%{search}%"
        params = (like, like)
    sql += " ORDER BY p.created_at DESC NULLS LAST"
    rows = con.execute(sql, params).fetchall()
    con.close()
    cols = ["id", "email", "full_name", "subscription_tier", "subscription_status",
            "last_login_at", "created_at", "current_period_end"]
    return [dict(zip(cols, r)) for r in rows]


def suspend_user(user_id: str) -> None:
    con = get_conn()
    con.execute("UPDATE profiles SET subscription_status = 'suspended' WHERE id = %s", (user_id,))
    con.commit()
    con.close()


def activate_user(user_id: str) -> None:
    con = get_conn()
    con.execute("UPDATE profiles SET subscription_status = 'active' WHERE id = %s", (user_id,))
    con.commit()
    con.close()


def set_user_group_override(user_id: str, group_name: str) -> None:
    con = get_conn()
    con.execute("UPDATE profiles SET subscription_tier = %s WHERE id = %s", (group_name, user_id))
    con.commit()
    con.close()


# ── Subscriptions ───────────────────────────────────────────────────────────

def create_subscription(user_id: str, group_name: str, period_start: date, period_end: date,
                         created_by: str | None = None, notes: str | None = None) -> int:
    con = get_conn()
    row = con.execute("""
        INSERT INTO user_subscriptions (user_id, group_name, period_start, period_end,
                                         created_by, notes)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (user_id, group_name, period_start, period_end, created_by, notes)).fetchone()
    sub_id = row[0]
    con.execute("UPDATE profiles SET subscription_tier = %s WHERE id = %s", (group_name, user_id))
    con.commit()
    con.close()
    return sub_id


def list_subscriptions(user_id: str | None = None) -> list[dict]:
    con = get_conn()
    sql = """
        SELECT s.id, s.user_id, p.email, s.group_name, s.period_start, s.period_end,
               s.status, s.created_by, s.notes, s.created_at
        FROM user_subscriptions s JOIN profiles p ON p.id = s.user_id
    """
    params: tuple = ()
    if user_id:
        sql += " WHERE s.user_id = %s"
        params = (user_id,)
    sql += " ORDER BY s.created_at DESC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    cols = ["id", "user_id", "email", "group_name", "period_start", "period_end",
            "status", "created_by", "notes", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


def expire_subscriptions() -> int:
    """Daily sweep: expire subscriptions past period_end, reverting each affected
    user to their next-active subscription's group or the default group."""
    con = get_conn()
    expired = con.execute("""
        UPDATE user_subscriptions SET status = 'expired'
        WHERE status = 'active' AND period_end < CURRENT_DATE
        RETURNING user_id
    """).fetchall()
    affected_users = {r[0] for r in expired}
    default_group = _default_group()

    for user_id in affected_users:
        still_active = con.execute("""
            SELECT group_name FROM user_subscriptions
            WHERE user_id = %s AND status = 'active'
              AND period_start <= CURRENT_DATE AND period_end >= CURRENT_DATE
            ORDER BY period_end DESC LIMIT 1
        """, (user_id,)).fetchone()
        new_group = still_active[0] if still_active else default_group
        con.execute("UPDATE profiles SET subscription_tier = %s WHERE id = %s",
                    (new_group, user_id))

    con.commit()
    con.close()
    return len(affected_users)


# ── Payments ────────────────────────────────────────────────────────────────

def record_payment(user_id: str, subscription_id: int | None, amount_inr: float,
                    payment_date: date, payment_ref: str | None = None,
                    verified_by: str | None = None, notes: str | None = None) -> int:
    con = get_conn()
    row = con.execute("""
        INSERT INTO payment_history (user_id, subscription_id, amount_inr, payment_date,
                                      payment_ref, verified_by, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (user_id, subscription_id, amount_inr, payment_date, payment_ref, verified_by, notes)
    ).fetchone()
    con.commit()
    con.close()
    return row[0]


def list_payments(user_id: str | None = None) -> list[dict]:
    con = get_conn()
    sql = """
        SELECT pay.id, pay.user_id, p.email, pay.subscription_id, pay.amount_inr,
               pay.payment_date, pay.payment_ref, pay.verified_by, pay.notes, pay.created_at,
               pay.status
        FROM payment_history pay JOIN profiles p ON p.id = pay.user_id
    """
    params: tuple = ()
    if user_id:
        sql += " WHERE pay.user_id = %s"
        params = (user_id,)
    sql += " ORDER BY pay.payment_date DESC, pay.created_at DESC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    cols = ["id", "user_id", "email", "subscription_id", "amount_inr",
            "payment_date", "payment_ref", "verified_by", "notes", "created_at", "status"]
    return [dict(zip(cols, r)) for r in rows]


# ── Pricing QR code ─────────────────────────────────────────────────────────

def get_qr_code() -> tuple[bytes, str] | None:
    con = get_conn()
    row = con.execute(
        "SELECT image, mime_type FROM payment_qr_code WHERE id = 'default'"
    ).fetchone()
    con.close()
    if row is None or row[0] is None:
        return None
    return bytes(row[0]), row[1]


def set_qr_code(image_bytes: bytes, mime_type: str) -> None:
    con = get_conn()
    con.execute("""
        UPDATE payment_qr_code SET image = %s, mime_type = %s, updated_at = now()
        WHERE id = 'default'
    """, (image_bytes, mime_type))
    con.commit()
    con.close()


# ── Payment claims (user-submitted, pending admin review) ──────────────────

def submit_payment_claim(user_id: str, requested_group: str, amount_inr: float,
                          payment_date: date, payment_ref: str | None,
                          screenshot_bytes: bytes, screenshot_mime: str,
                          notes: str | None = None) -> int:
    con = get_conn()
    row = con.execute("""
        INSERT INTO payment_history (user_id, subscription_id, amount_inr, payment_date,
                                      payment_ref, notes, status, requested_group,
                                      screenshot, screenshot_mime)
        VALUES (%s, NULL, %s, %s, %s, %s, 'pending', %s, %s, %s)
        RETURNING id
    """, (user_id, amount_inr, payment_date, payment_ref, notes, requested_group,
          screenshot_bytes, screenshot_mime)).fetchone()
    con.commit()
    con.close()
    return row[0]


def get_pending_claim(user_id: str) -> dict | None:
    con = get_conn()
    row = con.execute("""
        SELECT id, requested_group, amount_inr, payment_date, created_at
        FROM payment_history WHERE user_id = %s AND status = 'pending'
        ORDER BY created_at DESC LIMIT 1
    """, (user_id,)).fetchone()
    con.close()
    if row is None:
        return None
    cols = ["id", "requested_group", "amount_inr", "payment_date", "created_at"]
    return dict(zip(cols, row))


def list_pending_payments() -> list[dict]:
    con = get_conn()
    rows = con.execute("""
        SELECT pay.id, pay.user_id, p.email, pay.requested_group, pay.amount_inr,
               pay.payment_date, pay.payment_ref, pay.notes, pay.created_at
        FROM payment_history pay JOIN profiles p ON p.id = pay.user_id
        WHERE pay.status = 'pending'
        ORDER BY pay.created_at ASC
    """).fetchall()
    con.close()
    cols = ["id", "user_id", "email", "requested_group", "amount_inr",
            "payment_date", "payment_ref", "notes", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


def get_payment_screenshot(payment_id: int) -> tuple[bytes, str] | None:
    con = get_conn()
    row = con.execute(
        "SELECT screenshot, screenshot_mime FROM payment_history WHERE id = %s",
        (payment_id,)
    ).fetchone()
    con.close()
    if row is None or row[0] is None:
        return None
    return bytes(row[0]), row[1]


def approve_payment(payment_id: int, period_start: date, period_end: date,
                     verified_by: str) -> None:
    con = get_conn()
    row = con.execute(
        "SELECT user_id, requested_group FROM payment_history WHERE id = %s",
        (payment_id,)
    ).fetchone()
    con.close()
    if row is None:
        return
    user_id, requested_group = row

    sub_id = create_subscription(
        user_id, requested_group, period_start, period_end,
        created_by=verified_by, notes="Approved from Pending Payments",
    )

    con = get_conn()
    con.execute("""
        UPDATE payment_history
        SET status = 'verified', subscription_id = %s, verified_by = %s
        WHERE id = %s
    """, (sub_id, verified_by, payment_id))
    con.commit()
    con.close()


def reject_payment(payment_id: int, verified_by: str, notes: str | None = None) -> None:
    con = get_conn()
    con.execute("""
        UPDATE payment_history
        SET status = 'rejected', verified_by = %s,
            notes = COALESCE(%s, notes)
        WHERE id = %s
    """, (verified_by, notes, payment_id))
    con.commit()
    con.close()
