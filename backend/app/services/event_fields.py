"""NBA event clock and per-team lineup confirmation.

``commence_time`` stays the UTC timestamp the Odds API sends.
``commence_time_et`` is that same instant in America/New_York, with the
offset, so a winter tip is ``-05:00`` and a summer tip is ``-04:00``.
``display_tz`` is the label ``ET`` for both.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.models.schemas import EventLineupStatus, NBAEvent
from app.services.lineup_service import confirmation_status

EASTERN = ZoneInfo("America/New_York")
DISPLAY_TZ = "ET"


def commence_time_et(value: datetime | str | None) -> str | None:
    """ISO 8601 tip in America/New_York, or None when ``value`` does not parse."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(EASTERN).isoformat()


def event_lineup_status(
    home_team: str,
    away_team: str,
    lineups: dict[str, dict[str, Any]],
) -> EventLineupStatus:
    """Confirmation for the two clubs on an event.

    ``lineups`` is keyed by canonical team code, which is how the lineup
    service stores a slate. Full Odds API names (``Los Angeles Lakers``)
    are mapped with ``canonical_team_code`` before the lookup.
    """
    from app.services.daily_analysis import canonical_team_code

    def _one(name: str) -> str | None:
        code = canonical_team_code(name, league="nba")
        if not code:
            return None
        return confirmation_status(lineups.get(code))

    return EventLineupStatus(home=_one(home_team), away=_one(away_team))


def enrich_nba_event(event: NBAEvent, lineups: dict[str, dict[str, Any]]) -> NBAEvent:
    """Return ``event`` with the ET clock and the lineup confirmation."""
    return event.model_copy(
        update={
            "commence_time_et": commence_time_et(event.commence_time),
            "display_tz": DISPLAY_TZ,
            "lineup_status": event_lineup_status(event.home_team, event.away_team, lineups),
        }
    )
