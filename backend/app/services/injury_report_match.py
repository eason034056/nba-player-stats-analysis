"""Write match decisions onto ``nba_injury_report_rows``.

The insert in ``injury_report_ingest`` leaves ``bdl_player_id`` and
``match_method`` null, and its ``DO UPDATE`` does not touch them. This
module fills a null ``match_method`` after that insert. A method that
is already set, including the QA value ``held``, is left alone.

Matched ids are upserted into ``players`` first. The injury row has a
foreign key to that table. Unmatched rows stay, with a null id and a
method name. The review list is the return value. An optional path
receives JSON lines for the non-G-League misses. There is no HTTP route.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import asyncpg

from app.services.injury_report_names import (
    CatalogPlayer,
    PlayerCatalog,
    is_g_league,
    match_report_name,
)

logger = logging.getLogger(__name__)

_OPEN_ROWS = """
SELECT id, game_date, team_name, bdl_game_id, bdl_team_id,
       player_raw, reason, category
FROM nba_injury_report_rows
WHERE league = $1
  AND report_at = $2
  AND player_raw <> ''
  AND match_method IS NULL
ORDER BY id
"""

_GAME_SEASONS = """
SELECT bdl_game_id, season
FROM games
WHERE league = $1 AND bdl_game_id = ANY($2::bigint[])
"""

_STAT_MEMBERSHIPS = """
SELECT bdl_player_id, bdl_team_id, season
FROM player_game_stats
WHERE league = $1
"""

_PLAYER_ROWS = """
SELECT bdl_player_id, first_name, last_name, display_name, position
FROM players
WHERE league = $1
"""

_UPSERT_PLAYER = """
INSERT INTO players (
    league, bdl_player_id, first_name, last_name, display_name, position
) VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (league, bdl_player_id) DO UPDATE SET
    first_name = EXCLUDED.first_name,
    last_name = EXCLUDED.last_name,
    display_name = EXCLUDED.display_name,
    position = EXCLUDED.position
"""

_UPDATE_ROW = """
UPDATE nba_injury_report_rows
SET bdl_player_id = $2,
    match_method = $3
WHERE id = $1
  AND match_method IS NULL
"""


@dataclass(frozen=True)
class UnmatchedName:
    """One non-G-League name the catalog did not take.

    ``player_raw`` is the printed report name. This object is the review
    list. It is not a route.
    """

    report_at: datetime
    team_name: str
    player_raw: str
    match_method: str


async def match_report_rows(
    conn: asyncpg.Connection,
    *,
    league: str,
    report_at: datetime,
    catalog: PlayerCatalog,
    review_path: Path | None = None,
) -> list[UnmatchedName]:
    """Fill null match columns for one league and one report minute.

    Rows whose ``match_method`` is already set are not read. A matched
    id is inserted into ``players`` before the injury row points at it.
    G League misses are updated and are not returned.

    Args:
        conn: An open connection. The caller owns it.
        league: ``nba``.
        report_at: The report minute just stored.
        catalog: The BDL name list for this pass.
        review_path: Append JSON lines here when set. ``None`` writes no file.

    Returns:
        The non-G-League misses, in row id order.
    """
    rows = await conn.fetch(_OPEN_ROWS, league, report_at)
    if not rows:
        return []
    seasons = await _seasons_by_game(conn, league, rows)
    by_id = {player.bdl_player_id: player for player in catalog.players}
    updates: list[tuple[int, int | None, str]] = []
    review: list[UnmatchedName] = []
    for row in rows:
        season = seasons.get(row["bdl_game_id"])
        if season is None:
            season = season_start_year(row["game_date"])
        decision = match_report_name(
            row["player_raw"],
            team_id=row["bdl_team_id"],
            season=season,
            catalog=catalog,
            g_league=is_g_league(row["reason"], row["category"]),
        )
        updates.append((row["id"], decision.bdl_player_id, decision.match_method))
        if decision.on_review_list:
            review.append(
                UnmatchedName(
                    report_at=report_at,
                    team_name=row["team_name"],
                    player_raw=row["player_raw"],
                    match_method=decision.match_method,
                )
            )
    async with conn.transaction():
        matched_ids = {
            player_id
            for _row_id, player_id, _method in updates
            if player_id is not None
        }
        for player_id in sorted(matched_ids):
            player = by_id.get(player_id)
            if player is None:
                continue
            await conn.execute(
                _UPSERT_PLAYER,
                league,
                player.bdl_player_id,
                player.first_name,
                player.last_name,
                _display_name(player),
                player.position,
            )
        for row_id, player_id, method in updates:
            await conn.execute(_UPDATE_ROW, row_id, player_id, method)
    _write_review(review_path, review)
    logger.info(
        "injury_report_match rows=%s review=%s",
        len(updates),
        len(review),
    )
    return review


async def memberships_from_stats(
    conn: asyncpg.Connection, league: str
) -> dict[int, frozenset[tuple[int, int]]]:
    """``(team_id, season)`` pairs already stored in ``player_game_stats``."""
    grouped: dict[int, set[tuple[int, int]]] = {}
    for row in await conn.fetch(_STAT_MEMBERSHIPS, league):
        grouped.setdefault(int(row["bdl_player_id"]), set()).add(
            (int(row["bdl_team_id"]), int(row["season"]))
        )
    return {player_id: frozenset(pairs) for player_id, pairs in grouped.items()}


async def catalog_from_database(conn: asyncpg.Connection, league: str) -> PlayerCatalog:
    """Names and stat teams already in Postgres. No network call.

    A player with a null ``first_name`` uses the last space in
    ``display_name`` as the split. There is no current team here: the
    ``players`` table does not store one. Pass ``/v1/players`` pages to
    ``catalog_from_player_pages`` when a rookie has no stat row yet.
    """
    memberships = await memberships_from_stats(conn, league)
    players: list[CatalogPlayer] = []
    for row in await conn.fetch(_PLAYER_ROWS, league):
        first = row["first_name"] if isinstance(row["first_name"], str) else ""
        last = row["last_name"] if isinstance(row["last_name"], str) else ""
        if not first or not last:
            split = _split_display(row["display_name"] or "")
            if split is None:
                continue
            first, last = split
        player_id = int(row["bdl_player_id"])
        players.append(
            CatalogPlayer(
                bdl_player_id=player_id,
                first_name=first,
                last_name=last,
                position=row["position"] if isinstance(row["position"], str) else None,
                memberships=memberships.get(player_id, frozenset()),
                current_team_id=None,
                draft_year=None,
            )
        )
    return PlayerCatalog(tuple(players))


def season_start_year(game_date: date) -> int:
    """NBA season start year for a calendar date.

    October begins the next season. A January game still belongs to the
    season that started the previous October. This is the fallback when
    the row has no resolved game.
    """
    if game_date.month >= 10:
        return game_date.year
    return game_date.year - 1


async def _seasons_by_game(
    conn: asyncpg.Connection,
    league: str,
    rows: list[asyncpg.Record],
) -> dict[int, int]:
    game_ids = [row["bdl_game_id"] for row in rows if row["bdl_game_id"] is not None]
    if not game_ids:
        return {}
    found = await conn.fetch(_GAME_SEASONS, league, game_ids)
    return {int(row["bdl_game_id"]): int(row["season"]) for row in found}


def _display_name(player: CatalogPlayer) -> str:
    return " ".join(part for part in (player.first_name, player.last_name) if part)


def _split_display(display_name: str) -> tuple[str, str] | None:
    """Last space splits a display name. One token is not a first and a last."""
    text = display_name.strip()
    if " " not in text:
        return None
    first, last = text.rsplit(" ", 1)
    if not first or not last:
        return None
    return first, last


def _write_review(path: Path | None, review: list[UnmatchedName]) -> None:
    """Append one JSON object per miss. Names are not logged."""
    if path is None or not review:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for entry in review:
            handle.write(
                json.dumps(
                    {
                        "report_at": entry.report_at.isoformat(),
                        "team_name": entry.team_name,
                        "player_raw": entry.player_raw,
                        "match_method": entry.match_method,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
