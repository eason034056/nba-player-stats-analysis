"""Prediction time T for one game.

T is ``games.datetime_utc`` minus ``hours_before_tip``. The default is 3
hours everywhere in this package. A NULL tip is not replaced with a guessed
tip time: T is then 00:00 America/New_York on ``games.date``, minus the same
offset, and the row is counted as a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_HOURS_BEFORE_TIP = 3
NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc

T_RULE = (
    "T = games.datetime_utc - hours_before_tip. "
    "When datetime_utc is NULL, T is 00:00 America/New_York on games.date "
    "minus hours_before_tip. That fallback is counted in metadata. "
    "It is not a guessed tip time."
)


@dataclass(frozen=True, slots=True)
class AsOf:
    """T for one game, and whether the tip time was missing.

    ``as_of`` is timezone-aware UTC. ``tip_fallback`` is true when
    ``games.datetime_utc`` was NULL.
    """

    as_of: datetime
    tip_fallback: bool
    hours_before_tip: float


def prediction_instant(
    game_date: date,
    datetime_utc: datetime | None,
    hours_before_tip: float = DEFAULT_HOURS_BEFORE_TIP,
) -> AsOf:
    """Return T for a game.

    Args:
        game_date: ``games.date``. Used only when ``datetime_utc`` is NULL.
        datetime_utc: ``games.datetime_utc``. Aware when present. NULL takes
            the New York midnight fallback.
        hours_before_tip: Hours subtracted from the tip. Defaults to 3.
            Negative values are rejected.

    Returns:
        The UTC instant T and the fallback flag.

    Raises:
        ValueError: ``hours_before_tip`` is negative, or ``datetime_utc``
            has no timezone.
    """
    if hours_before_tip < 0:
        raise ValueError("hours_before_tip must be >= 0")
    if datetime_utc is None:
        midnight = datetime(
            game_date.year, game_date.month, game_date.day, tzinfo=NEW_YORK
        )
        tip = midnight.astimezone(UTC)
        fallback = True
    else:
        if datetime_utc.tzinfo is None or datetime_utc.tzinfo.utcoffset(datetime_utc) is None:
            raise ValueError("datetime_utc must be timezone-aware")
        tip = datetime_utc.astimezone(UTC)
        fallback = False
    as_of = tip - timedelta(hours=hours_before_tip)
    return AsOf(as_of=as_of, tip_fallback=fallback, hours_before_tip=hours_before_tip)
