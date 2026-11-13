"""
odds_provider.py - Odds provider contract

Callers ask for a league. A provider turns that league into whatever the
upstream API needs and returns the shapes below. The Odds API client in
``odds_theoddsapi.py`` is the only provider registered in this change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Optional, Protocol, runtime_checkable


# League key used by routes, jobs, and the gateway. Not an upstream sport key.
League = Literal["nba", "wnba"]

# Game state on ProviderEvent. The Odds API events list has no status field,
# so that provider reports "scheduled" for every row it returns.
EventStatus = Literal["scheduled", "in_progress", "final"]


@dataclass(frozen=True)
class ProviderEvent:
    """One game, independent of which provider listed it.

    ``event_id`` is the id callers already store (Odds API hex today).
    ``home_team`` and ``away_team`` use the Odds API full-name spelling.
    ``home_code`` and ``away_code`` are the canonical team codes.
    ``commence_time`` is ISO UTC. ``slate_date`` is the America/New_York date.
    """

    event_id: str
    commence_time: str
    home_team: str
    away_team: str
    home_code: str
    away_code: str
    status: EventStatus
    slate_date: str


@dataclass(frozen=True)
class EventOdds:
    """Bookmaker board for one event.

    ``bookmakers`` is the Odds API list: each item has ``key``, ``title``,
    and ``markets``. Downstream parsers read that list and nothing else.
    ``player_ids`` maps an outcome description to a provider player id.
    The Odds API leaves it empty.
    """

    bookmakers: list[dict[str, Any]]
    fetched_at: datetime
    provider: str
    player_ids: dict[str, int]


@dataclass(frozen=True)
class RateStatus:
    """Quota snapshot for /metrics.

    ``recorded`` is false when nothing has been stored yet. The HTTP body
    still uses remaining, used, total, and remaining_ratio.
    """

    provider: str
    remaining: Optional[int] = None
    used: Optional[int] = None
    last: Optional[int] = None
    recorded: bool = False

    @property
    def total(self) -> Optional[int]:
        if self.remaining is None or self.used is None:
            return None
        return self.remaining + self.used

    @property
    def remaining_ratio(self) -> Optional[float]:
        total = self.total
        if total in (None, 0) or self.remaining is None:
            return None
        return self.remaining / total


@runtime_checkable
class OddsProvider(Protocol):
    """Provider operations keyed by league.

    ``name`` is the cache-key segment (``theoddsapi`` for the client in
    this change). ``list_events`` returns games in ``[start_utc, end_utc]``.
    ``get_event_props`` returns the board for one event and the given
    market keys. ``rate_status`` is the quota reading /metrics shows.
    ``get_events`` and ``get_event_odds`` stay on the protocol so the
    existing HTTP methods keep the same parameter names. Pass ``league``
    to select the sport key inside the provider. ``sport`` remains for a
    caller that already holds a sport key.
    """

    name: str

    async def list_events(
        self,
        league: League,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[ProviderEvent]:
        """Games for ``league`` whose commence time is queried in UTC."""

    async def get_event_props(
        self,
        league: League,
        event_id: str,
        markets: tuple[str, ...],
    ) -> EventOdds:
        """Odds board for one event. ``markets`` is a tuple of market keys."""

    async def rate_status(self) -> RateStatus:
        """Latest stored quota for this provider."""

    async def get_events(
        self,
        sport: str,
        regions: str,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        *,
        league: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Raw event list. ``league`` selects the sport key when set."""

    async def get_event_odds(
        self,
        sport: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str = "american",
        bookmakers: Optional[list[str]] = None,
        *,
        league: Optional[str] = None,
    ) -> dict[str, Any]:
        """Raw odds payload. ``league`` selects the sport key when set."""


@dataclass(frozen=True)
class QuotaUsage:
    """
    Odds API quota usage information.

    - remaining: Number of remaining allowed requests
    - used: Number of requests already used
    - last: Number used in the most recent request
    """

    remaining: Optional[int] = None
    used: Optional[int] = None
    last: Optional[int] = None

    @property
    def total(self) -> Optional[int]:
        if self.remaining is None or self.used is None:
            return None
        return self.remaining + self.used

    @property
    def remaining_ratio(self) -> Optional[float]:
        total = self.total
        if total in (None, 0) or self.remaining is None:
            return None
        return self.remaining / total


class OddsAPIError(Exception):
    """
    Odds API error exception class.

    Used to encapsulate all errors related to external odds APIs.
    Contains status code and message for debugging and error handling.

    Attributes:
        status_code: HTTP status code (e.g., 401, 404, 500)
        message: Error message
    """

    def __init__(self, message: str, status_code: Optional[int] = None):
        """
        Initialize OddsAPIError

        Args:
            message: Error message
            status_code: HTTP status code (optional)
        """
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

    def __str__(self) -> str:
        """
        String representation

        Status code is included if present.
        """
        if self.status_code:
            return f"[{self.status_code}] {self.message}"
        return self.message
