"""NBA projected lineups from BALLDONTLIE ``GET /nba/v1/projected_lineups``.

One slate is one logical fetch. Game ids come from ``GET /v1/games`` for
that Eastern date and are reused from Redis for 36 hours. The HTTP client
is the existing ``BdlClient.list_projected_lineups``. This module does not
add query parameters. The recorded ``game_ids[]`` request sends no
``per_page`` and no ``cursor``, and the recorded page holds 25 rows. A
slate of more than 12 games is split into calls of at most 12 ids (24
team rows, under that page).

A team missing from a published ``data`` list produces no ``TeamLineup``.
An empty ``data`` list, or an empty games list, means the slate is not
published yet: nothing is cached as "no games", and the caller leaves
stored lineups in place. Names go through ``normalize_source_players``
and ``make_source_lineup``. Confidence is ``medium`` for a complete five
with no unresolved name, and ``low`` otherwise. There is no second
source, so disagreement is false and confidence is never ``high``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from app.services.cache import cache_service
from app.services.lineup_source_support import make_source_lineup, normalize_source_players
from app.settings import settings

logger = logging.getLogger(__name__)

# Same 36-hour window as the tip cache. The tip key stays ``status`` plus
# ``tips_utc``. Game ids live on this sibling key.
SLATE_GAMES_CACHE_TTL_SECONDS = 36 * 60 * 60
# Recorded default page is 25 rows. Two teams per game, so 12 games stay
# on one page without sending ``per_page``.
MAX_GAME_IDS_PER_CALL = 12
LINEUP_SOURCE = "balldontlie"


class ProjectedLineupClient(Protocol):
    """The two ``BdlClient`` methods this fetch uses."""

    async def list_games(
        self,
        *,
        dates: list[str] | None = None,
        per_page: int = 100,
    ) -> dict[str, Any]: ...

    async def list_projected_lineups(self, *, game_ids: list[int]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ProjectedLineupWrite:
    """One team version to store when the parent rows exist.

    ``updated_at`` is BALLDONTLIE's timestamp. ``players`` is
    ``(bdl_player_id, position)`` in the recorded lineup order.
    """

    game_id: int
    team_id: int
    status: str | None
    updated_at: datetime
    players: tuple[tuple[int, str | None], ...]


@dataclass(frozen=True)
class BdlLineupFetch:
    """Lineups for the live API, plus the rows the 002 write can attempt.

    ``misses`` counts team rows that were dropped or that cannot be stored
    as a version (unknown team, bad row, missing ``updated_at``, a starter
    with no player id). It does not count a parent-row miss. That check
    happens at insert time.
    """

    lineups: dict[str, dict[str, Any]]
    writes: tuple[ProjectedLineupWrite, ...]
    misses: int


def slate_games_cache_key(slate_date: str) -> str:
    """Redis key for one slate's game ids and home/away codes.

    Args:
        slate_date: Eastern game date, ``YYYY-MM-DD``.

    Returns:
        ``lineup:v1:nba:slate-games:<slate_date>``.
    """
    return f"lineup:v1:nba:slate-games:{slate_date}"


def open_lineup_client() -> Any:
    """Open a ``BdlClient`` with the configured key.

    Raises:
        RuntimeError: ``BALLDONTLIE_API_KEY`` is empty. The message does
            not contain the key.
    """
    from app.services.bdl_client import BdlClient

    api_key = settings.balldontlie_api_key.get_secret_value().strip()
    if not api_key:
        raise RuntimeError("BALLDONTLIE_API_KEY is unset")
    return BdlClient(api_key=api_key)


def _canonical_code(full_name: str, abbreviation: str) -> str:
    """Canonical team code. The Clippers abbreviation ``LAC`` stays ``LAC``.

    Same rule as ``bdl_odds_provider.team_code``.
    """
    from app.services.daily_analysis import canonical_team_code

    if abbreviation:
        coded = canonical_team_code(abbreviation, league="nba")
        if coded:
            return coded
    return canonical_team_code(full_name, league="nba")


def _team_side(team: object) -> tuple[int | None, str]:
    """``(team_id, code)`` from one games-payload team object."""
    if not isinstance(team, dict):
        return None, ""
    team_id = team.get("id")
    if not isinstance(team_id, int):
        return None, ""
    full_name = team.get("full_name") if isinstance(team.get("full_name"), str) else ""
    abbreviation = team.get("abbreviation") if isinstance(team.get("abbreviation"), str) else ""
    return team_id, _canonical_code(full_name, abbreviation)


def games_from_payload(payload: object) -> list[dict[str, Any]]:
    """Game ids and home/away codes from one ``list_games`` body.

    The body is the object ``BdlClient.list_games`` returns (``data`` plus
    ``meta``). A non-object, or a body whose ``data`` is not a list, raises
    so the caller does not cache it and does not replace stored lineups.

    Args:
        payload: Raw games JSON object.

    Returns:
        One dict per game, in payload order, with duplicate ids dropped.

    Raises:
        ValueError: The body is not a games object.
    """
    if not isinstance(payload, dict):
        raise ValueError("games payload is not an object")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("games payload has no data list")
    games: list[dict[str, Any]] = []
    seen: set[int] = set()
    for game in data:
        if not isinstance(game, dict):
            continue
        game_id = game.get("id")
        if not isinstance(game_id, int) or game_id in seen:
            continue
        seen.add(game_id)
        home_id, home_code = _team_side(game.get("home_team"))
        away_id, away_code = _team_side(game.get("visitor_team"))
        games.append(
            {
                "game_id": game_id,
                "home_team_id": home_id,
                "home_code": home_code,
                "away_team_id": away_id,
                "away_code": away_code,
            }
        )
    return games


def _parse_cached_games(raw: object) -> list[dict[str, Any]] | None:
    """Return a cached slate, or None when the caller should read again.

    An empty list is not a slate. BALLDONTLIE returns that before the
    day's games are published, and caching it would hide the real slate
    for the rest of the TTL.
    """
    if not isinstance(raw, dict):
        return None
    games = raw.get("games")
    if not isinstance(games, list):
        return None
    parsed: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict) or not isinstance(game.get("game_id"), int):
            return None
        home_id = game.get("home_team_id")
        away_id = game.get("away_team_id")
        home_code = game.get("home_code")
        away_code = game.get("away_code")
        parsed.append(
            {
                "game_id": game["game_id"],
                "home_team_id": home_id if isinstance(home_id, int) else None,
                "home_code": home_code if isinstance(home_code, str) else "",
                "away_team_id": away_id if isinstance(away_id, int) else None,
                "away_code": away_code if isinstance(away_code, str) else "",
            }
        )
    if not parsed:
        return None
    return parsed


def _chunks(game_ids: list[int], size: int) -> list[list[int]]:
    """Split ``game_ids`` into lists of at most ``size`` ids."""
    if size < 1:
        raise ValueError("chunk size must be at least 1")
    return [game_ids[index : index + size] for index in range(0, len(game_ids), size)]


def _parse_updated_at(value: object) -> datetime | None:
    """Parse a BALLDONTLIE ``updated_at``. ``Z`` means UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _starter_names(slots: object) -> tuple[list[str], tuple[tuple[int, str | None], ...], bool]:
    """Names and player ids from one recorded ``lineup`` array.

    Returns:
        Display names in array order, ``(player_id, position)`` for slots
        that have an int id, and whether any named starter lacked an id.
    """
    if not isinstance(slots, list):
        return [], (), True
    names: list[str] = []
    players: list[tuple[int, str | None]] = []
    missing_id = False
    for slot in slots:
        if not isinstance(slot, dict):
            missing_id = True
            continue
        player = slot.get("player") if isinstance(slot.get("player"), dict) else {}
        first = player.get("first_name") if isinstance(player.get("first_name"), str) else ""
        last = player.get("last_name") if isinstance(player.get("last_name"), str) else ""
        name = " ".join(part for part in (first.strip(), last.strip()) if part)
        position = slot.get("position") if isinstance(slot.get("position"), str) else None
        player_id = player.get("id")
        if name:
            names.append(name)
            if isinstance(player_id, int):
                players.append((player_id, position))
            else:
                missing_id = True
        elif isinstance(player_id, int):
            missing_id = True
    return names, tuple(players), missing_id


def _apply_confidence(lineup: dict[str, Any]) -> None:
    """Set single-source confidence. A complete resolved five is medium."""
    snapshot = (lineup.get("source_snapshots") or {}).get(LINEUP_SOURCE) or {}
    unresolved = snapshot.get("unresolved_starters") or []
    starters = lineup.get("starters") or []
    if len(starters) == 5 and not unresolved:
        lineup["confidence"] = "medium"
    else:
        lineup["confidence"] = "low"
    lineup["source_disagreement"] = False


def _side_for(game: dict[str, Any], team_id: object) -> dict[str, str] | None:
    """Home or away label for ``team_id`` on one cached game."""
    if not isinstance(team_id, int):
        return None
    home_id = game.get("home_team_id")
    away_id = game.get("away_team_id")
    home_code = game.get("home_code") or ""
    away_code = game.get("away_code") or ""
    if team_id == home_id and home_code:
        return {"code": home_code, "opponent": away_code, "home_or_away": "HOME"}
    if team_id == away_id and away_code:
        return {"code": away_code, "opponent": home_code, "home_or_away": "AWAY"}
    return None


def map_projected_rows(
    date: str,
    games: list[dict[str, Any]],
    rows: list[object],
) -> BdlLineupFetch:
    """Turn recorded projected-lineup rows into ``TeamLineup`` dicts.

    A team id that is not a side on ``games`` is dropped and counted.
    An empty ``rows`` list returns no lineups.

    Args:
        date: Slate date stored on each lineup.
        games: Output of ``games_from_payload`` or the slate cache.
        rows: ``data`` arrays from ``list_projected_lineups``, concatenated.

    Returns:
        Live lineups keyed by team code, the 002 write rows, and the miss count.
    """
    by_game = {game["game_id"]: game for game in games}
    lineups: dict[str, dict[str, Any]] = {}
    writes: list[ProjectedLineupWrite] = []
    misses = 0
    for row in rows:
        if not isinstance(row, dict):
            misses += 1
            continue
        game = by_game.get(row.get("game_id"))
        side = _side_for(game, row.get("team_id")) if game is not None else None
        if side is None:
            misses += 1
            logger.info(
                "bdl projected lineup team miss game_id=%s team_id=%s",
                row.get("game_id"),
                row.get("team_id"),
            )
            continue
        names, players, missing_id = _starter_names(row.get("lineup"))
        normalized = normalize_source_players(names, side["code"], LINEUP_SOURCE)
        updated_at = row.get("updated_at") if isinstance(row.get("updated_at"), str) else None
        status = row.get("status") if isinstance(row.get("status"), str) else ""
        lineup = make_source_lineup(
            date=date,
            team=side["code"],
            opponent=side["opponent"],
            home_or_away=side["home_or_away"],
            starters=normalized["display"],
            bench_candidates=[],
            source=LINEUP_SOURCE,
            source_status=status,
            raw_starters=names,
            canonical_starters=normalized["canonical"],
            unresolved_starters=normalized["unresolved"],
            normalization_warnings=normalized["warnings"],
            updated_at=updated_at,
        )
        snapshot = lineup["source_snapshots"][LINEUP_SOURCE]
        if updated_at:
            snapshot["updated_at"] = updated_at
        _apply_confidence(lineup)
        lineups[side["code"]] = lineup
        parsed_updated = _parse_updated_at(updated_at)
        if missing_id or parsed_updated is None or not isinstance(row.get("game_id"), int):
            misses += 1
            continue
        if not isinstance(row.get("team_id"), int):
            misses += 1
            continue
        writes.append(
            ProjectedLineupWrite(
                game_id=row["game_id"],
                team_id=row["team_id"],
                status=status or None,
                updated_at=parsed_updated,
                players=players,
            )
        )
    return BdlLineupFetch(lineups=lineups, writes=tuple(writes), misses=misses)


async def _load_slate_games(
    date: str,
    client: ProjectedLineupClient,
    cache: Any,
) -> list[dict[str, Any]]:
    """Game ids for ``date``, from the slate cache or one ``list_games`` call."""
    key = slate_games_cache_key(date)
    cached: object = None
    try:
        cached = await cache.get(key)
    except Exception:
        logger.warning("slate games cache read failed for %s", date)
    parsed = _parse_cached_games(cached)
    if parsed is not None:
        return parsed
    payload = await client.list_games(dates=[date], per_page=100)
    games = games_from_payload(payload)
    if not games:
        return games
    try:
        await cache.set(key, {"games": games}, SLATE_GAMES_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("slate games cache write failed for %s", date)
    return games


async def _load_projected_rows(
    client: ProjectedLineupClient,
    game_ids: list[int],
) -> tuple[list[object], int]:
    """Concatenated ``data`` rows, in chunks of ``MAX_GAME_IDS_PER_CALL``."""
    rows: list[object] = []
    misses = 0
    for chunk in _chunks(game_ids, MAX_GAME_IDS_PER_CALL):
        payload = await client.list_projected_lineups(game_ids=chunk)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("projected lineups payload has no data list")
        for row in payload["data"]:
            if isinstance(row, dict):
                rows.append(row)
            else:
                misses += 1
    return rows, misses


async def fetch_nba_lineups(
    date: str,
    *,
    client: ProjectedLineupClient | None = None,
    cache: Any | None = None,
) -> BdlLineupFetch:
    """Fetch projected lineups for one Eastern slate date.

    A passed ``client`` is left open. The default client is closed here.
    A fresh slate-games cache skips ``list_games``. ``list_projected_lineups``
    still runs, because the lineup itself is not stored under that key.
    An empty games list returns no lineups, does not call
    ``list_projected_lineups``, and is not written to the slate cache.

    Args:
        date: Eastern slate date, ``YYYY-MM-DD``.
        client: ``BdlClient`` or a stand-in with the same two methods.
        cache: Object with ``get`` and ``set``. Defaults to ``cache_service``.

    Returns:
        Live lineups and the versions that can be written to 002.

    Raises:
        RuntimeError: The API key is unset and no client was passed.
        ValueError: A response body is not the recorded object shape.
    """
    owns_client = client is None
    if client is None:
        client = open_lineup_client()
    if cache is None:
        cache = cache_service
    try:
        games = await _load_slate_games(date, client, cache)
        game_ids = [game["game_id"] for game in games]
        if not game_ids:
            return BdlLineupFetch(lineups={}, writes=(), misses=0)
        rows, row_misses = await _load_projected_rows(client, game_ids)
        fetched = map_projected_rows(date, games, rows)
        return BdlLineupFetch(
            lineups=fetched.lineups,
            writes=fetched.writes,
            misses=fetched.misses + row_misses,
        )
    finally:
        if owns_client:
            await client.aclose()
