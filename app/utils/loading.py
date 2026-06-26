"""
Shared loading helpers — consistent loading UX across all pages.
Uses st.status() for multi-step loads, st.spinner() for single-step.
"""
import streamlit as st
from datetime import date, timedelta
import calendar


def data_freshness_bar(
    latest_date: date | None,
    record_count: int | None = None,
    source: str = "NSDL",
    next_update_label: str | None = None,
) -> None:
    """Show a slim data-freshness info bar below the page header."""
    if latest_date is None:
        return

    today = date.today()
    days_old = (today - latest_date).days

    if days_old == 0:
        age_txt = "Updated today"
        age_color = "#00C853"
    elif days_old <= 3:
        age_txt = f"Updated {days_old}d ago"
        age_color = "#64DD17"
    elif days_old <= 16:
        age_txt = f"Updated {days_old}d ago"
        age_color = "#FFD600"
    else:
        age_txt = f"Last updated {latest_date.strftime('%d %b %Y')}"
        age_color = "#FF6D00"

    # Next NSDL publish date
    if next_update_label is None:
        y, m = today.year, today.month
        last_day = calendar.monthrange(y, m)[1]
        if today.day < 15:
            nxt = date(y, m, 15)
        elif today.day < last_day:
            nxt = date(y, m, last_day)
        else:
            nxt = date(y, m + 1 if m < 12 else 1, 15)
        days_to_next = (nxt - today).days
        next_update_label = (
            f"Next NSDL update: {nxt.strftime('%d %b %Y')}"
            + (f" (in {days_to_next}d)" if days_to_next > 0 else " — today!")
        )

    parts = []
    if record_count:
        parts.append(f"**{record_count}** records")
    parts.append(f"Source: **{source}**")
    parts.append(f"<span style='color:{age_color}'>{age_txt}</span>")
    parts.append(next_update_label)

    st.markdown(
        "<small>" + " &nbsp;·&nbsp; ".join(parts) + "</small>",
        unsafe_allow_html=True,
    )
    st.markdown("")  # spacing


def loading_status(steps: list[tuple[str, str]]) -> "st.status":
    """
    Return an st.status context manager pre-configured with step labels.
    Usage:
        with loading_status([("step1", "Reading DB..."), ("step2", "Building chart...")]) as s:
            data = load()
            s.update(label="Done!", state="complete")
    """
    first_label = steps[0][1] if steps else "Loading..."
    return st.status(first_label, expanded=False)


def spinner_db(msg: str = "Reading from database..."):
    """Spinner for DB reads — sets expectation it's fast."""
    return st.spinner(f"⏳ {msg}")


def spinner_network(source: str, detail: str = ""):
    """Spinner for network calls — warns user it may take a moment."""
    return st.spinner(
        f"🌐 Fetching from {source}{'  · ' + detail if detail else ''}  "
        f"— this may take a few seconds…"
    )
