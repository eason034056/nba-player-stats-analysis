"""
date_utils.py – 日期正規化與時區轉換

將 Planner 回傳的 date（如 "tomorrow"、"today"）轉成 YYYY-MM-DD，
並以使用者本地時區為準，查詢 The Odds API 時再轉成 UTC。
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple


def normalize_date(date_str: str) -> str:
    """
    將口語化日期轉成 YYYY-MM-DD，以本地時區為準。

    - "tomorrow" / "tomorow" / "tommorow" → 本地明天的日期
    - "today" → 本地今天的日期
    - "2025-03-13" → 原樣回傳（已為標準格式）
    - "" 或無效 → ""

    Returns:
        YYYY-MM-DD 字串，或 "" 表示無效/空
    """
    if not date_str or not isinstance(date_str, str):
        return ""
    s = date_str.strip().lower()
    # 使用本地時區（使用者所在時區）
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
    將 YYYY-MM-DD（視為本地日期）轉成 The Odds API 用的 UTC 時間範圍。

    The Odds API 的 commenceTimeFrom/commenceTimeTo 使用 UTC。
    此函數將「該日 00:00 ～ 23:59 本地時間」轉成對應的 UTC 區間。

    Args:
        date_yyyy_mm_dd: 如 "2025-03-13"

    Returns:
        (date_from_utc, date_to_utc) 或 None（若日期無效）
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
