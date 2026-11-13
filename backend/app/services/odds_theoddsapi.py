"""
odds_theoddsapi.py - The Odds API Implementation

Implements the OddsProvider interface and interacts with The Odds API v4.
API Documentation: https://the-odds-api.com/liveapi/guides/v4/

The Odds API is a third-party service specializing in providing sports betting odds,
supporting various sports and bookmakers.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

import httpx

from app.settings import settings
from app.services.odds_provider import (
    EventOdds,
    OddsAPIError,
    OddsProvider,
    ProviderEvent,
    QuotaUsage,
    RateStatus,
)

logger = logging.getLogger(__name__)

# League key → The Odds API sport key. Callers pass the league.
# The sport key is only used to build /v4/sports/{sport_key}/...
SPORT_KEY_BY_LEAGUE: dict[str, str] = {
    "nba": "basketball_nba",
    "wnba": "basketball_wnba",
}


def normalize_league(league: str) -> str:
    """Return ``nba`` or ``wnba``. Raise ``ValueError`` for anything else."""
    key = (league or "").strip().lower()
    if key not in SPORT_KEY_BY_LEAGUE:
        raise ValueError(
            f"Unknown league: {league!r}. "
            f"Registered: {sorted(SPORT_KEY_BY_LEAGUE)}"
        )
    return key


def sport_key_for_league(league: str) -> str:
    """Return the Odds API sport key for ``league``.

    Raises:
        ValueError: ``league`` is not nba or wnba. The message says
        ``Unsupported league`` so existing daily-analysis checks still match.
    """
    key = (league or "").strip().lower()
    try:
        return SPORT_KEY_BY_LEAGUE[key]
    except KeyError:
        raise ValueError(
            f"Unsupported league: {league!r}. "
            f"Registered: {sorted(SPORT_KEY_BY_LEAGUE)}"
        ) from None


def league_for_sport_key(sport: str) -> str:
    """Return the league for an Odds API sport key.

    Used when a stored hot-key member still carries ``sport``.

    Raises:
        ValueError: ``sport`` is not a registered sport key.
    """
    for league, sport_key in SPORT_KEY_BY_LEAGUE.items():
        if sport_key == sport:
            return league
    raise ValueError(
        f"Unknown sport: {sport!r}. "
        f"Registered: {sorted(SPORT_KEY_BY_LEAGUE.values())}"
    )


class TheOddsAPIProvider(OddsProvider):
    """
    Implementation of The Odds API v4.

    Handles HTTP communication with The Odds API,
    including retry logic and error handling.

    API Endpoints:
    - GET /v4/sports/{sport}/events - get event list
    - GET /v4/sports/{sport}/events/{eventId}/odds - get odds for a specific event
    """

    name = "theoddsapi"

    def sport_key_for(self, league: str) -> str:
        """Map ``league`` to the Odds API sport key. See ``sport_key_for_league``."""
        return sport_key_for_league(league)

    def __init__(self):
        """
        Initialize The Odds API Provider

        Retrieves from settings:
        - base_url: Base API URL
        - api_key: API key (for authentication)
        """
        self.base_url = settings.odds_api_base_url
        self.api_key = settings.odds_api_key

    async def _make_request(
        self,
        endpoint: str,
        params: Dict[str, Any],
        max_retries: int = 3
    ) -> Tuple[Any, Optional[QuotaUsage]]:
        """
        Send an HTTP GET request to The Odds API

        Includes retry with backoff: 
        If the request fails, will retry up to max_retries times.

        httpx: modern Python HTTP client
        - Supports async/await
        - Better suited for async applications than requests

        Args:
            endpoint: API endpoint path (e.g. "/v4/sports/basketball_nba/events")
            params: query parameters as dict
            max_retries: maximum number of retries

        Returns:
            JSON data from the API response

        Raises:
            OddsAPIError: if all retries fail
        """
        # Add API key to parameters
        params["apiKey"] = self.api_key

        url = f"{self.base_url}{endpoint}"

        last_error = None

        # Retry loop
        for attempt in range(max_retries):
            try:
                # Use async with to ensure the connection is properly closed
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url, params=params)
                    usage = self._build_quota_usage(response)
                    self._log_quota_usage(
                        endpoint=endpoint,
                        status_code=response.status_code,
                        usage=usage,
                    )

                    # Check response status code
                    if response.status_code == 200:
                        return response.json(), usage

                    # Handle various error status codes
                    if response.status_code == 401:
                        raise OddsAPIError("Invalid API key", 401)
                    elif response.status_code == 404:
                        raise OddsAPIError("Resource not found", 404)
                    elif response.status_code == 422:
                        raise OddsAPIError(
                            f"Invalid parameters: {response.text}",
                            422
                        )
                    elif response.status_code == 429:
                        # Rate limit exceeded; need to wait and retry
                        raise OddsAPIError("Rate limit exceeded", 429)
                    else:
                        raise OddsAPIError(
                            f"API error: {response.text}",
                            response.status_code
                        )

            except httpx.TimeoutException:
                last_error = OddsAPIError("Request timeout")
            except httpx.RequestError as e:
                last_error = OddsAPIError(f"Request error: {str(e)}")
            except OddsAPIError as e:
                # For 401 (authentication error) and 422 (parameter error), no need to retry
                if e.status_code in [401, 422]:
                    raise
                last_error = e

        # All retries failed
        raise last_error or OddsAPIError("Unknown error after retries")

    def _build_quota_usage(self, response: httpx.Response) -> QuotaUsage:
        return QuotaUsage(
            remaining=self._parse_header_int(response.headers.get("x-requests-remaining")),
            used=self._parse_header_int(response.headers.get("x-requests-used")),
            last=self._parse_header_int(response.headers.get("x-requests-last")),
        )

    def _log_quota_usage(
        self,
        endpoint: str,
        status_code: int,
        usage: QuotaUsage,
    ) -> None:
        logger.info(
            "odds_api_quota %s",
            json.dumps(
                {
                    "endpoint": endpoint,
                    "status_code": status_code,
                    "remaining": usage.remaining,
                    "used": usage.used,
                    "last": usage.last,
                    "total": usage.total,
                },
                sort_keys=True,
            ),
        )

    @staticmethod
    def _parse_header_int(value: Optional[str]) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def get_events(
        self,
        sport: str = "basketball_nba",
        regions: str = "us",
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        *,
        league: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get NBA event list

        Calls The Odds API events endpoint
        API Endpoint: GET /v4/sports/{sport}/events

        API Docs: https://the-odds-api.com/liveapi/guides/v4/#get-events

        Args:
            sport: sport key, default "basketball_nba"
            regions: region code, default "us"
            date_from: start date filter (optional)
            date_to: end date filter (optional)

        Returns:
            List of events, each event includes:
            - id: event ID
            - sport_key: sport key
            - home_team: home team name
            - away_team: away team name
            - commence_time: start time (ISO 8601)

        Example:
            >>> provider = TheOddsAPIProvider()
            >>> events = await provider.get_events()
            >>> for event in events:
            ...     print(f"{event['away_team']} @ {event['home_team']}")
        """
        if league is not None:
            sport = sport_key_for_league(league)
        endpoint = f"/v4/sports/{sport}/events"

        params = {}

        # Date filtering (if provided)
        # The Odds API only accepts YYYY-MM-DDTHH:MM:SSZ format, no microseconds
        if date_from:
            params["commenceTimeFrom"] = date_from.strftime("%Y-%m-%dT%H:%M:%SZ")
        if date_to:
            params["commenceTimeTo"] = date_to.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Send request
        data, _ = await self._make_request(endpoint, params)

        # API returns a list of events (array)
        return data if isinstance(data, list) else []

    async def get_event_odds(
        self,
        sport: str = "basketball_nba",
        event_id: str = "",
        regions: str = "us",
        markets: str = "player_points",
        odds_format: str = "american",
        bookmakers: Optional[List[str]] = None,
        *,
        league: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get player props odds for a given event

        Calls The Odds API event odds endpoint
        API Endpoint: GET /v4/sports/{sport}/events/{eventId}/odds

        API Docs: https://the-odds-api.com/liveapi/guides/v4/#get-event-odds

        Note: Player props (e.g. player_points) are "non-featured" markets,
        so must use the event-specific endpoint, not /odds

        Args:
            sport: sport key
            event_id: event ID (obtained from get_events)
            regions: region code (influences available bookmakers)
            markets: market type (e.g. player_points, player_rebounds, etc.)
            odds_format: odds format
                - "american": American (-110, +150)
                - "decimal": Decimal (1.91, 2.50)
            bookmakers: specific bookmakers to query (optional)

        Returns:
            Odds data, including:
            - id: event ID
            - sport_key: sport key
            - bookmakers: list of bookmakers, each includes markets and outcomes

        Example:
            >>> odds = await provider.get_event_odds(
            ...     event_id="abc123",
            ...     markets="player_points"
            ... )
            >>> for bookmaker in odds['bookmakers']:
            ...     print(f"{bookmaker['key']}: {len(bookmaker['markets'])} markets")
        """
        if league is not None:
            sport = sport_key_for_league(league)
        endpoint = f"/v4/sports/{sport}/events/{event_id}/odds"

        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format
        }

        # If specific bookmakers are given
        if bookmakers:
            params["bookmakers"] = ",".join(bookmakers)

        # Send request
        data, _ = await self._make_request(endpoint, params)

        return data

    async def get_event_odds_with_usage(
        self,
        sport: str = "basketball_nba",
        event_id: str = "",
        regions: str = "us",
        markets: str = "player_points",
        odds_format: str = "american",
        bookmakers: Optional[List[str]] = None,
        *,
        league: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], Optional[QuotaUsage]]:
        if league is not None:
            sport = sport_key_for_league(league)
        endpoint = f"/v4/sports/{sport}/events/{event_id}/odds"

        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format
        }

        if bookmakers:
            params["bookmakers"] = ",".join(bookmakers)

        data, usage = await self._make_request(endpoint, params)
        return data, usage

    async def list_events(
        self,
        league: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[ProviderEvent]:
        """Events in the UTC window, as ``ProviderEvent`` rows.

        The HTTP call is ``get_events(league=...)`` with the same
        ``commenceTimeFrom`` / ``commenceTimeTo`` parameters.
        """
        raw = await self.get_events(
            league=league,
            regions="us",
            date_from=start_utc,
            date_to=end_utc,
        )
        return [self._provider_event(item, league) for item in raw]

    async def get_event_props(
        self,
        league: str,
        event_id: str,
        markets: tuple[str, ...],
    ) -> EventOdds:
        """Odds board for ``markets``.

        Sends the same query as ``get_event_odds_with_usage`` with
        ``regions=us``, ``oddsFormat=american``, and no bookmaker filter.
        ``markets`` are joined in the order given, comma-separated.
        """
        data, _usage = await self.get_event_odds_with_usage(
            league=league,
            event_id=event_id,
            regions="us",
            markets=",".join(markets),
            odds_format="american",
            bookmakers=None,
        )
        books = data.get("bookmakers") if isinstance(data, dict) else None
        return EventOdds(
            bookmakers=list(books) if isinstance(books, list) else [],
            fetched_at=datetime.now(timezone.utc),
            provider=self.name,
            player_ids={},
        )

    async def rate_status(self) -> RateStatus:
        """Quota last stored by the gateway under ``QUOTA_USAGE_KEY``.

        An empty cache returns ``recorded=False``. The numbers are the
        same fields ``get_quota_usage`` reads.
        """
        from app.services.cache import cache_service
        from app.services.odds_gateway import QUOTA_USAGE_KEY

        cached = await cache_service.get(QUOTA_USAGE_KEY)
        if not cached:
            return RateStatus(provider=self.name, recorded=False)
        return RateStatus(
            provider=self.name,
            remaining=cached.get("remaining"),
            used=cached.get("used"),
            last=cached.get("last"),
            recorded=True,
        )

    @staticmethod
    def _provider_event(raw: dict[str, Any], league: str) -> ProviderEvent:
        """Map one Odds API event object onto ``ProviderEvent``.

        The events payload has no game status, so ``status`` is
        ``scheduled``. ``slate_date`` is the Eastern calendar date of
        ``commence_time``. Team codes go through ``canonical_team_code``.
        """
        from app.services.daily_analysis import canonical_team_code
        from app.services.slate_date import nba_slate_date

        commence = str(raw.get("commence_time") or "")
        slate = ""
        if commence:
            try:
                moment = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                slate = nba_slate_date(moment)[0]
            except ValueError:
                slate = ""
        home = str(raw.get("home_team") or "")
        away = str(raw.get("away_team") or "")
        return ProviderEvent(
            event_id=str(raw.get("id") or ""),
            commence_time=commence,
            home_team=home,
            away_team=away,
            home_code=canonical_team_code(home, league=league),
            away_code=canonical_team_code(away, league=league),
            status="scheduled",
            slate_date=slate,
        )


# Create a global instance
odds_provider = TheOddsAPIProvider()
