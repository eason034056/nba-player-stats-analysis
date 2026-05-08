"""
date_utils.py – Date normalization and timezone conversion

Converts date strings returned by the Planner (such as "tomorrow", "today") to YYYY-MM-DD,
using the user's local timezone, and then converts them to UTC for The Odds API queries.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple


def normalize_date(date_str: str) -> str:
    """
    Converts a colloquial date string to YYYY-MM-DD, using the local timezone.

    - "tomorrow" / "tomorow" / "tommorow" → tomorrow's date in local time
    - "today" → today's date in local time
    - "2025-03-13" → returns as is (already in standard format)
    - "" or invalid input → ""

    Returns:
        A string in YYYY-MM-DD format, or "" for invalid/empty input
    """
    if not date_str or not isinstance(date_str, str):
        return ""
    s = date_str.strip().lower()
    # Use local timezone (user's timezone)
    now_local = datetime.now().astimezone()
    today = now_local.date()

    if s in ("tomorrow", "tomorow", "tommorow"):
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if s == "today":
        return today.strftime("%Y-%m-%d")
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            datetime(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except ValueError:
            return ""
    return ""


def date_to_utc_range(date_yyyy_mm_dd: str) -> Optional[Tuple[datetime, datetime]]:
    """
    Converts a YYYY-MM-DD string (interpreted as a local date) to a UTC time range for The Odds API.

    The Odds API uses UTC for commenceTimeFrom/commenceTimeTo.
    This function converts "that day 00:00 ~ 23:59 local time" to the corresponding UTC interval.

    Args:
        date_yyyy_mm_dd: e.g. "2025-03-13"

    Returns:
        (date_from_utc, date_to_utc), or None (if date is invalid)
    """
    if not date_yyyy_mm_dd or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_yyyy_mm_dd):
        return None
    try:
        y, mo, d = map(int, date_yyyy_mm_dd.split("-"))
        local_tz = datetime.now().astimezone().tzinfo
        start_local = datetime(y, mo, d, 0, 0, 0, tzinfo=local_tz)
        end_local = datetime(y, mo, d, 23, 59, 59, tzinfo=local_tz)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        return (start_utc, end_utc)
    except (ValueError, TypeError):
        return None
