"""
bdl_odds_provider.py - BALLDONTLIE implementation of OddsProvider.

``BdlOddsProvider`` is the NBA provider. The name matches
``settings.nba_odds_provider`` when that value is ``balldontlie``. It
composes the existing ``BdlClient`` (one HTTP layer, the shared limiter),
``BdlPropsAdapter``, and ``BdlPlayerDirectory``. It does not open a
second HTTP client.

Games are matched by the Eastern date plus team codes. Commence time is
not a join key: the same game is 01:00Z on BALLDONTLIE and 01:10Z on
The Odds API for Boston at Philadelphia. ``list_events`` still filters
the requested UTC window by the game's ``datetime``, after one
``/v1/games?dates[]=`` call for the Eastern dates that window covers.

This module is not imported by a route or a job. The gateway imports it
only when ``nba_odds_provider`` is ``balldontlie``. The default remains
``theoddsapi``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.bdl_client import BdlClient
from app.services.bdl_player_directory import BdlPlayerDirectory
from app.services.bdl_props_adapter import BdlPropsAdapter
from app.services.odds_provider import EventOdds, EventStatus, ProviderEvent, RateStatus
from app.services.slate_date import NBA_SLATE_TZ

logger = logging.getLogger(__name__)

# BALLDONTLIE spells the Clippers ``LA Clippers``. The Odds API spelling
# is ``Los Angeles Clippers``. ``canonical_team_code`` already maps both
# to LAC. Emitting the Odds API spelling keeps ``home_team`` comparable
# across providers. No other full_name in the recorded game files differs.
_ODDS_API_TEAM_NAME: dict[str, str] = {
    "LA Clippers": "Los Angeles Clippers",
}

_STATUS_BY_STATE: dict[str, EventStatus] = {
    "scheduled": "scheduled",
    "in_progress": "in_progress",
    "final": "final",
}


def _as_utc(moment: datetime) -> datetime:
    """Naive datetimes are UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _parse_utc(value: Any) -> datetime | None:
    """Parse one ISO timestamp. ``Z`` means UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def et_dates_covering(start_utc: datetime, end_utc: datetime) -> list[str]:
    """Eastern calendar dates touched by the UTC window, oldest first.

    One ``list_games`` call sends every date as ``dates[]``. A US game
    day touches at most two of these dates.
    """
    start = _as_utc(start_utc).astimezone(NBA_SLATE_TZ).date()
    end = _as_utc(end_utc).astimezone(NBA_SLATE_TZ).date()
    if end < start:
        return []
    dates: list[str] = []
    cursor = start
    while cursor <= end:
        dates.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return dates


def odds_api_team_name(full_name: str) -> str:
    """Odds API full-name spelling for a BALLDONTLIE ``full_name``."""
    return _ODDS_API_TEAM_NAME.get(full_name, full_name)


def team_code(full_name: str, abbreviation: str) -> str:
    """Canonical code. The Clippers abbreviation ``LAC`` stays ``LAC``."""
    from app.services.daily_analysis import canonical_team_code

    if abbreviation:
        coded = canonical_team_code(abbreviation, league="nba")
        if coded:
            return coded
    return canonical_team_code(full_name, league="nba")


def slate_date_et(commence_time: str) -> str:
    """Eastern calendar date of an ISO commence time. Empty when unusable."""
    moment = _parse_utc(commence_time)
    if moment is None:
        return ""
    return moment.astimezone(NBA_SLATE_TZ).date().isoformat()


def games_match(
    *,
    odds_home: str,
    odds_away: str,
    odds_commence: str,
    bdl_game: dict[str, Any],
) -> bool:
    """True when the Odds API event and the BDL game are the same matchup.

    The join is the Eastern date plus the home and away codes. The two
    commence times are not compared. Boston at Philadelphia is 01:10Z on
    The Odds API and 01:00Z on BALLDONTLIE, and both are 2026-11-10 in
    New York.
    """
    home = bdl_game.get("home_team") if isinstance(bdl_game.get("home_team"), dict) else {}
    away = bdl_game.get("visitor_team") if isinstance(bdl_game.get("visitor_team"), dict) else {}
    bdl_date = bdl_game.get("date") if isinstance(bdl_game.get("date"), str) else ""
    odds_date = slate_date_et(odds_commence)
    if not bdl_date or not odds_date or bdl_date != odds_date:
        return False
    home_code = team_code(str(home.get("full_name") or ""), str(home.get("abbreviation") or ""))
    away_code = team_code(str(away.get("full_name") or ""), str(away.get("abbreviation") or ""))
    return (
        team_code(odds_home, "") == home_code
        and team_code(odds_away, "") == away_code
        and bool(home_code)
        and bool(away_code)
    )


class BdlOddsProvider:
    """OddsProvider backed by BALLDONTLIE. NBA only.

    Usage:
        provider = BdlOddsProvider(client)
        events = await provider.list_events("nba", start, end)
        board = await provider.get_event_props("nba", events[0].event_id, ("player_points",))

    ``list_events`` remembers each game. ``get_event_props`` uses that
    game's ``datetime`` as the tip, so rows updated after tip are dropped.
    A props call made before any ``list_events`` has no tip and keeps
    every timestamp.
    """

    name = "balldontlie"

    def __init__(
        self,
        client: BdlClient | None = None,
        directory: BdlPlayerDirectory | None = None,
        adapter: BdlPropsAdapter | None = None,
    ) -> None:
        self._client = client
        self._directory = directory
        self._adapter = adapter or BdlPropsAdapter()
        self._games: dict[str, dict[str, Any]] = {}

    def _require_client(self) -> BdlClient:
        """The shared client. Built on first use when the caller did not pass one."""
        if self._client is None:
            self._client = BdlClient()
        return self._client

    def _require_directory(self) -> BdlPlayerDirectory:
        if self._directory is None:
            self._directory = BdlPlayerDirectory(self._require_client())
        return self._directory

    async def list_events(
        self,
        league: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[ProviderEvent]:
        """Games whose ``datetime`` falls in ``[start_utc, end_utc]``.

        One ``list_games`` call covers the Eastern dates of that window.
        ``slate_date`` is the game's own ``date`` field, which is the
        Eastern date, not a conversion of ``datetime``.
        """
        self._require_nba(league)
        dates = et_dates_covering(start_utc, end_utc)
        if not dates:
            return []
        payload = await self._require_client().list_games(dates=dates)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return []
        start = _as_utc(start_utc)
        end = _as_utc(end_utc)
        events: list[ProviderEvent] = []
        for game in data:
            if not isinstance(game, dict):
                continue
            tip = _parse_utc(game.get("datetime"))
            if tip is None or tip < start or tip > end:
                continue
            event = self._provider_event(game)
            if event is None:
                continue
            self._games[event.event_id] = game
            events.append(event)
        return events

    async def get_event_props(
        self,
        league: str,
        event_id: str,
        markets: tuple[str, ...],
    ) -> EventOdds:
        """Props for one BALLDONTLIE game id, in the Odds API bookmaker shape.

        ``event_id`` is the decimal game id. A non-digit id raises before
        a request is sent.
        """
        return await self._props_filtered(league, event_id, markets, None)

    async def rate_status(self) -> RateStatus:
        """Last BALLDONTLIE rate-limit headers on this client.

        ``recorded`` is false until a response has carried a header.
        ``used`` is ``limit - remaining`` when both headers were present.
        This is not the Odds API quota object.
        """
        status = self._require_client().rate_status()
        limit = status.get("limit")
        remaining = status.get("remaining")
        used = None
        if isinstance(limit, int) and isinstance(remaining, int):
            used = limit - remaining
        recorded = limit is not None or remaining is not None
        return RateStatus(
            provider=self.name,
            remaining=remaining if isinstance(remaining, int) else None,
            used=used,
            last=None,
            recorded=recorded,
        )

    async def get_events(
        self,
        sport: str = "basketball_nba",
        regions: str = "us",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        *,
        league: str | None = None,
    ) -> list[dict[str, Any]]:
        """Event dicts with the Odds API keys routes already read.

        ``id`` is the decimal game id. ``home_team`` and ``away_team`` use
        the Odds API spelling. ``regions`` is ignored: the recorded games
        call has no region.
        """
        del sport, regions
        self._require_nba(league or "nba")
        if date_from is None or date_to is None:
            now = datetime.now(timezone.utc)
            date_from = date_from or now
            date_to = date_to or (now + timedelta(days=1))
        events = await self.list_events(league or "nba", date_from, date_to)
        return [self._raw_event(event) for event in events]

    async def get_event_odds(
        self,
        sport: str = "basketball_nba",
        event_id: str = "",
        regions: str = "us",
        markets: str = "",
        odds_format: str = "american",
        bookmakers: list[str] | None = None,
        *,
        league: str | None = None,
    ) -> dict[str, Any]:
        """One event's board in the Odds API event-odds shape.

        Prices stay American, which is the only price the recorded props
        carry. ``regions`` is ignored. ``bookmakers`` is the vendor filter,
        with ``bally_bet`` mapped to ``ballybet``.
        """
        del sport, regions, odds_format
        self._require_nba(league or "nba")
        market_keys = tuple(part.strip() for part in markets.split(",") if part.strip())
        board = await self._props_filtered(
            league or "nba",
            event_id,
            market_keys,
            bookmakers,
        )
        game = self._games.get(str(_game_id(event_id)))
        event = self._provider_event(game) if isinstance(game, dict) else None
        body: dict[str, Any] = {
            "id": str(event_id),
            "sport_key": "basketball_nba",
            "bookmakers": board.bookmakers,
        }
        if event is not None:
            body["commence_time"] = event.commence_time
            body["home_team"] = event.home_team
            body["away_team"] = event.away_team
        return body

    async def get_event_odds_with_usage(
        self,
        sport: str = "basketball_nba",
        event_id: str = "",
        regions: str = "us",
        markets: str = "",
        odds_format: str = "american",
        bookmakers: list[str] | None = None,
        *,
        league: str | None = None,
    ) -> tuple[dict[str, Any], None]:
        """Same body as ``get_event_odds``. Usage is None.

        The gateway stores Odds API quota only when usage is present.
        BALLDONTLIE's remaining count stays on ``rate_status`` so it is
        not written into the Odds API quota key.
        """
        data = await self.get_event_odds(
            sport=sport,
            event_id=event_id,
            regions=regions,
            markets=markets,
            odds_format=odds_format,
            bookmakers=bookmakers,
            league=league,
        )
        return data, None

    async def _props_filtered(
        self,
        league: str,
        event_id: str,
        markets: tuple[str, ...],
        bookmakers: list[str] | None,
    ) -> EventOdds:
        """``get_event_props``, then the bookmaker filter applied to the rows.

        The public ``get_event_props`` has no bookmaker argument. The
        gateway still passes ``bookmakers`` into ``get_event_odds``. The
        filter is applied by adapting once with that argument instead of
        fetching twice.
        """
        self._require_nba(league)
        game_id = _game_id(event_id)
        payload = await self._require_client().get_player_props(game_id=game_id)
        rows = payload.get("data") if isinstance(payload, dict) else None
        dict_rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        player_ids = sorted(
            {row["player_id"] for row in dict_rows if isinstance(row.get("player_id"), int)}
        )
        names = await self._require_directory().names_for(player_ids) if player_ids else {}
        game = self._games.get(str(game_id))
        tip = _parse_utc(game.get("datetime")) if isinstance(game, dict) else None
        books = self._adapter.to_bookmakers(
            dict_rows,
            names,
            game_datetime=tip,
            markets=markets if markets else None,
            bookmakers=bookmakers,
        )
        return EventOdds(
            bookmakers=books,
            fetched_at=datetime.now(timezone.utc),
            provider=self.name,
            player_ids=dict(self._adapter.last_player_ids),
        )

    def _provider_event(self, game: dict[str, Any]) -> ProviderEvent | None:
        """One recorded game object to ``ProviderEvent``, or None when the status is unknown."""
        state = game.get("status_state")
        status = _STATUS_BY_STATE.get(state) if isinstance(state, str) else None
        if status is None:
            logger.info("bdl_game_status_skipped id=%s status_state=%s", game.get("id"), state)
            return None
        home = game.get("home_team") if isinstance(game.get("home_team"), dict) else {}
        away = game.get("visitor_team") if isinstance(game.get("visitor_team"), dict) else {}
        home_full = str(home.get("full_name") or "")
        away_full = str(away.get("full_name") or "")
        commence = game.get("datetime") if isinstance(game.get("datetime"), str) else ""
        slate = game.get("date") if isinstance(game.get("date"), str) else ""
        return ProviderEvent(
            event_id=str(game.get("id")),
            commence_time=commence,
            home_team=odds_api_team_name(home_full),
            away_team=odds_api_team_name(away_full),
            home_code=team_code(home_full, str(home.get("abbreviation") or "")),
            away_code=team_code(away_full, str(away.get("abbreviation") or "")),
            status=status,
            slate_date=slate,
        )

    @staticmethod
    def _raw_event(event: ProviderEvent) -> dict[str, Any]:
        """The event dict ``get_events`` callers already index."""
        return {
            "id": event.event_id,
            "sport_key": "basketball_nba",
            "commence_time": event.commence_time,
            "home_team": event.home_team,
            "away_team": event.away_team,
        }

    @staticmethod
    def _require_nba(league: str) -> None:
        """This provider does not serve WNBA. WNBA stays on The Odds API."""
        key = (league or "").strip().lower()
        if key != "nba":
            raise ValueError(f"BdlOddsProvider only serves nba, not {league!r}")


def _game_id(event_id: str) -> int:
    """Decimal game id. A hex Odds API id raises before HTTP."""
    text = str(event_id).strip()
    if not text.isdigit():
        raise ValueError(f"BALLDONTLIE game id must be digits, not {event_id!r}")
    return int(text)


_SINGLETON: BdlOddsProvider | None = None


def get_bdl_odds_provider() -> BdlOddsProvider:
    """The process-wide provider. The client is created on the first request."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = BdlOddsProvider()
    return _SINGLETON

