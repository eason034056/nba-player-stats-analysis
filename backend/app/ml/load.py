"""Read-only season-window loads for the dataset export.

Each season is one query. The caller asks for a bounded window (the output
seasons plus the previous season for form features). Nothing here runs at
API startup, and nothing writes.

The DSN comes from the environment variable named by the caller. Connection
errors are rewritten so the DSN and its password do not appear.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlsplit

import asyncpg

from app.dsn import redact_secrets
from app.ml.sources import (
    require_absence_source,
    require_feature_source,
    require_label_source,
)

_URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")

GAMES_SQL = """
SELECT league, bdl_game_id, season, date, datetime_utc, season_type,
       home_team_id, visitor_team_id
FROM games
WHERE league = $1 AND season = $2
ORDER BY date, bdl_game_id
"""

STATS_SQL = """
SELECT league, bdl_game_id, bdl_player_id, bdl_team_id, season, date, dnp,
       seconds_played, pts, reb, ast, fg3m, stl, blk
FROM player_game_stats
WHERE league = $1 AND season = $2
ORDER BY bdl_player_id, date, bdl_game_id
"""

# Label loader. This may read the target game's final result. It is not a
# feature query: prop_actuals is registered as a label source, and the SELECT
# does not touch player_prop_snapshots or predictions.
ACTUALS_SQL = """
SELECT a.league, a.bdl_game_id, a.bdl_player_id, a.market, a.actual_value
FROM prop_actuals a
JOIN games g ON g.league = a.league AND g.bdl_game_id = a.bdl_game_id
WHERE a.league = $1 AND g.season = $2
"""

# Opening rows only. snapshot_at <= T is applied in Python with the same T as
# the rest of the row. Doing it here would need a second copy of the NULL-tip
# rule and would ignore a non-default --hours-before-tip.
GAME_ODDS_SQL = """
SELECT o.league, o.bdl_game_id, o.book_key, o.snapshot_kind, o.snapshot_at,
       o.spread_home_value, o.total_value
FROM game_odds_snapshots o
JOIN games g ON g.league = o.league AND g.bdl_game_id = o.bdl_game_id
WHERE o.league = $1
  AND g.season = $2
  AND o.snapshot_kind = 'opening'
  AND o.snapshot_at IS NOT NULL
ORDER BY o.bdl_game_id, o.book_key
"""

READ_QUERIES = (GAMES_SQL, STATS_SQL, ACTUALS_SQL, GAME_ODDS_SQL)


class LoadError(RuntimeError):
    """A dataset read failed. The message has no DSN and no password."""


@dataclass(frozen=True, slots=True)
class GameRecord:
    """Schedule fields for one game. Scores are not loaded."""

    league: str
    bdl_game_id: int
    season: int
    game_date: date
    datetime_utc: datetime | None
    season_type: str
    home_team_id: int | None
    visitor_team_id: int | None = None


@dataclass(frozen=True, slots=True)
class StatRecord:
    """One ``player_game_stats`` row. DNP lines have null counting stats."""

    league: str
    bdl_game_id: int
    bdl_player_id: int
    bdl_team_id: int
    season: int
    game_date: date
    dnp: bool
    seconds_played: int | None
    pts: int | None
    reb: int | None
    ast: int | None
    fg3m: int | None
    stl: int | None
    blk: int | None


@dataclass(frozen=True, slots=True)
class GameOddsRecord:
    """One ``game_odds_snapshots`` row loaded for the opening-odds features.

    ``spread_home_value`` and ``total_value`` are NULL when the book did not
    post that number. A NULL is not a zero. ``snapshot_at`` may be NULL on
    an opening row; the feature rule then drops the row.
    """

    league: str
    bdl_game_id: int
    book_key: str
    snapshot_kind: str
    snapshot_at: datetime | None
    spread_home_value: float | None
    total_value: float | None


@dataclass(frozen=True, slots=True)
class InjuryRecord:
    """One ``injury_snapshots`` row.

    ``status`` is NULL when the row is a removal (``listed`` false) or when
    the feed sent a blank status. This loader does not map the word to a
    probability.
    """

    league: str
    snapshot_at: datetime
    bdl_player_id: int
    listed: bool
    status: str | None


@dataclass(frozen=True, slots=True)
class LineupRecord:
    """One ``game_lineups`` row. ``starter`` is the actual tip-off flag."""

    league: str
    bdl_game_id: int
    bdl_player_id: int
    bdl_team_id: int | None
    starter: bool


@dataclass(frozen=True, slots=True)
class ProjectedStarterRow:
    """One projected starter on one published version.

    ``updated_at`` is when the provider published the version.
    ``first_seen_at`` is when this application stored it. An as-of read
    keeps versions with ``first_seen_at <= T`` and then picks the newest
    ``updated_at``.
    """

    league: str
    bdl_game_id: int
    bdl_team_id: int
    updated_at: datetime
    first_seen_at: datetime
    bdl_player_id: int


@dataclass(frozen=True, slots=True)
class TeamAbsenceInputs:
    """Rows a live ``team_absences`` call needs for one team and one game.

    The stats are the team's last 10 games before the target date, each
    candidate's latest earlier game (so a trade is visible), and the target
    game's own rows. Injuries are every snapshot for those candidates,
    including rows after T. The time cutoff is applied by ``team_absences``,
    not here.
    """

    target_date: date
    season: int
    stats: tuple[StatRecord, ...]
    injuries: tuple[InjuryRecord, ...]


@dataclass(frozen=True, slots=True)
class ActualRecord:
    """One ``prop_actuals`` value. NULL means void or unknown, not zero."""

    league: str
    bdl_game_id: int
    bdl_player_id: int
    market: str
    actual_value: int | None


def load_span(season_start: int, season_end: int) -> range:
    """Seasons to read for features, inclusive.

    The first season is the year before ``season_start``, so an output row
    early in ``season_start`` still sees the previous season. ``season_end``
    is included. Output rows themselves are a subset; see
    :func:`output_span`.
    """
    _check_season_bounds(season_start, season_end)
    return range(season_start - 1, season_end + 1)


def output_span(season_start: int, season_end: int) -> range:
    """Output seasons, inclusive. ``2015:2025`` contains both 2015 and 2025."""
    _check_season_bounds(season_start, season_end)
    return range(season_start, season_end + 1)


def _check_season_bounds(season_start: int, season_end: int) -> None:
    if season_end < season_start:
        raise LoadError("season end is before season start")


def dsn_from_env(env_name: str) -> str:
    """Return the DSN stored in ``env_name``. The value is not logged.

    Raises:
        LoadError: the name is empty or the variable is unset or blank.
            The message names the variable and does not include a URL.
    """
    if not env_name or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for ch in env_name):
        raise LoadError("dsn env var name is invalid")
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise LoadError(f"environment variable {env_name} is not set")
    return value


def _raw_password_pieces(dsn: str) -> tuple[str, ...]:
    """Return the userinfo password and the pieces split by ``#``, ``/``, ``?``.

    ``urlsplit`` treats those characters as a fragment, a path, or a query, so
    ``.password`` is empty. asyncpg then raises with the first piece in the
    message, because it reads that text as a port.
    """
    userinfo = dsn.split("://", 1)[-1].rsplit("@", 1)[0]
    if ":" not in userinfo:
        return ()
    password = userinfo.split(":", 1)[1]
    if not password:
        return ()
    pieces = [password]
    for part in re.split(r"[/#?]", password):
        if part and part not in pieces:
            pieces.append(part)
    pieces.sort(key=len, reverse=True)
    return tuple(pieces)


def sanitize_error(exc: BaseException, dsn: str | None = None) -> str:
    """Return ``exc``'s message with the DSN and its password removed.

    A masked URL is still a DSN, so any URL is replaced with ``[dsn]``.
    A password that contains ``#``, ``/``, or ``?`` is removed in pieces,
    because the whole URL is not what the driver puts in the error.
    """
    secrets: list[str] = []
    if dsn and len(dsn) >= 4:
        secrets.append(dsn)
        try:
            password = urlsplit(dsn).password or ""
        except ValueError:
            password = ""
        if len(password) >= 4:
            secrets.append(password)
        for piece in _raw_password_pieces(dsn):
            if len(piece) >= 4 and piece not in secrets:
                secrets.append(piece)
    secrets.sort(key=len, reverse=True)
    text = redact_secrets(str(exc), tuple(secrets))
    if dsn:
        text = text.replace(dsn, "[dsn]")
    text = _URL_IN_TEXT.sub("[dsn]", text)
    return text or "database connection failed"


async def connect_readonly(dsn: str) -> asyncpg.Connection:
    """Open a session that cannot write. The DSN is never put in an error.

    A ``ValueError`` from the driver means the address could not be read
    (a raw ``#`` or ``?`` in the password is the usual cause). That text is
    replaced with a fixed message, because the driver percent-decodes the
    password before it writes the error.

    Raises:
        LoadError: the DSN cannot be read, the server cannot be reached, or
            the session cannot be made read-only. An unreadable DSN uses a
            fixed message. Other messages pass through :func:`sanitize_error`.
    """
    try:
        conn = await asyncpg.connect(
            dsn,
            timeout=10,
            command_timeout=120,
            server_settings={"default_transaction_read_only": "on"},
        )
    except ValueError:
        raise LoadError(
            "invalid DSN: percent-encode every special character in the password"
        ) from None
    except Exception as exc:
        raise LoadError(sanitize_error(exc, dsn)) from None
    return conn


async def _fetch(conn: asyncpg.Connection, sql: str, *args: object) -> list[asyncpg.Record]:
    try:
        async with conn.transaction(readonly=True):
            return await conn.fetch(sql, *args)
    except Exception as exc:
        raise LoadError(sanitize_error(exc)) from None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _game(record: asyncpg.Record) -> GameRecord:
    return GameRecord(
        league=str(record["league"]),
        bdl_game_id=int(record["bdl_game_id"]),
        season=int(record["season"]),
        game_date=record["date"],
        datetime_utc=record["datetime_utc"],
        season_type=str(record["season_type"]),
        home_team_id=_optional_int(record["home_team_id"]),
        visitor_team_id=_optional_int(record["visitor_team_id"]),
    )


def _stat(record: asyncpg.Record) -> StatRecord:
    return StatRecord(
        league=str(record["league"]),
        bdl_game_id=int(record["bdl_game_id"]),
        bdl_player_id=int(record["bdl_player_id"]),
        bdl_team_id=int(record["bdl_team_id"]),
        season=int(record["season"]),
        game_date=record["date"],
        dnp=bool(record["dnp"]),
        seconds_played=_optional_int(record["seconds_played"]),
        pts=_optional_int(record["pts"]),
        reb=_optional_int(record["reb"]),
        ast=_optional_int(record["ast"]),
        fg3m=_optional_int(record["fg3m"]),
        stl=_optional_int(record["stl"]),
        blk=_optional_int(record["blk"]),
    )


def _game_odds(record: asyncpg.Record) -> GameOddsRecord:
    return GameOddsRecord(
        league=str(record["league"]),
        bdl_game_id=int(record["bdl_game_id"]),
        book_key=str(record["book_key"]),
        snapshot_kind=str(record["snapshot_kind"]),
        snapshot_at=record["snapshot_at"],
        spread_home_value=_optional_float(record["spread_home_value"]),
        total_value=_optional_float(record["total_value"]),
    )


def _actual(record: asyncpg.Record) -> ActualRecord:
    return ActualRecord(
        league=str(record["league"]),
        bdl_game_id=int(record["bdl_game_id"]),
        bdl_player_id=int(record["bdl_player_id"]),
        market=str(record["market"]),
        actual_value=_optional_int(record["actual_value"]),
    )


async def load_feature_rows(
    conn: asyncpg.Connection,
    *,
    league: str,
    seasons: range,
) -> tuple[list[GameRecord], list[StatRecord]]:
    """Load ``games`` and ``player_game_stats`` one season at a time.

    Both names are checked against the feature allow-list before any query.
    Scores are not selected. ``player_prop_snapshots`` is not queried.
    """
    require_feature_source("games")
    require_feature_source("player_game_stats")
    games: list[GameRecord] = []
    stats: list[StatRecord] = []
    for season in seasons:
        for record in await _fetch(conn, GAMES_SQL, league, season):
            games.append(_game(record))
        for record in await _fetch(conn, STATS_SQL, league, season):
            stats.append(_stat(record))
    return games, stats


async def load_opening_game_odds(
    conn: asyncpg.Connection,
    *,
    league: str,
    seasons: range,
) -> list[GameOddsRecord]:
    """Load opening game odds, one season at a time.

    The allow-list is checked before any query. The SQL keeps
    ``snapshot_kind = 'opening'`` and a non-NULL ``snapshot_at``. Rows after
    T are still returned. :func:`app.ml.game_odds.opening_odds_features`
    drops them with the same T as the rest of the row. Closing and live
    rows are not selected. ``player_prop_snapshots`` is not queried.
    """
    require_feature_source("game_odds_snapshots")
    rows: list[GameOddsRecord] = []
    for season in seasons:
        for record in await _fetch(conn, GAME_ODDS_SQL, league, season):
            rows.append(_game_odds(record))
    return rows


async def load_labels(
    conn: asyncpg.Connection,
    *,
    league: str,
    seasons: range,
) -> list[ActualRecord]:
    """Load ``prop_actuals`` for the output seasons, one season at a time.

    This is the label loader. It may see the target game's final result.
    Those values are not features.
    """
    require_label_source("prop_actuals")
    actuals: list[ActualRecord] = []
    for season in seasons:
        for record in await _fetch(conn, ACTUALS_SQL, league, season):
            actuals.append(_actual(record))
    return actuals


# Season-scoped reads for the training export. snapshot_at and first_seen_at
# are not filtered here: each row's T is applied in Python so a non-default
# hours_before_tip and the NULL-tip midnight stay in one place.
INJURIES_SQL = """
SELECT league, snapshot_at, bdl_player_id, listed, status
FROM injury_snapshots
WHERE league = $1
ORDER BY bdl_player_id, snapshot_at
"""

LINEUPS_SQL = """
SELECT l.league, l.bdl_game_id, l.bdl_player_id, l.bdl_team_id, l.starter
FROM game_lineups l
JOIN games g ON g.league = l.league AND g.bdl_game_id = l.bdl_game_id
WHERE l.league = $1 AND g.season = $2
ORDER BY l.bdl_game_id, l.bdl_player_id
"""

PROJECTED_SQL = """
SELECT l.league, l.bdl_game_id, l.bdl_team_id, l.updated_at, l.first_seen_at,
       p.bdl_player_id
FROM projected_lineups l
JOIN games g ON g.league = l.league AND g.bdl_game_id = l.bdl_game_id
JOIN projected_lineup_players p
  ON p.league = l.league
 AND p.bdl_game_id = l.bdl_game_id
 AND p.bdl_team_id = l.bdl_team_id
 AND p.updated_at = l.updated_at
WHERE l.league = $1 AND g.season = $2
ORDER BY l.bdl_game_id, l.bdl_team_id, l.updated_at, p.bdl_player_id
"""

COVERAGE_SQL = "SELECT to_regclass('public.source_covered') AS name"

# Live path. One team, one game. The last-10 cutoff is the target game's
# date, the same prior-date rule as the rest of the dataset. Injury rows are
# not limited by snapshot_at in SQL.
ABSENCE_GAME_SQL = """
SELECT season, date
FROM games
WHERE league = $1 AND bdl_game_id = $2
"""

TEAM_WINDOW_SQL = """
SELECT bdl_game_id
FROM (
    SELECT DISTINCT bdl_game_id, date
    FROM player_game_stats
    WHERE league = $1 AND bdl_team_id = $2 AND date < $3
) team_games
ORDER BY date DESC, bdl_game_id DESC
LIMIT 10
"""

_STAT_COLUMNS = """
league, bdl_game_id, bdl_player_id, bdl_team_id, season, date, dnp,
seconds_played, pts, reb, ast, fg3m, stl, blk
"""

TEAM_WINDOW_STATS_SQL = f"""
SELECT {_STAT_COLUMNS}
FROM player_game_stats
WHERE league = $1 AND bdl_team_id = $2 AND bdl_game_id = ANY($3::bigint[])
"""

LATEST_PRIOR_SQL = f"""
SELECT DISTINCT ON (bdl_player_id) {_STAT_COLUMNS}
FROM player_game_stats
WHERE league = $1 AND bdl_player_id = ANY($2::integer[]) AND date < $3
ORDER BY bdl_player_id, date DESC, bdl_game_id DESC
"""

TARGET_TEAM_STATS_SQL = f"""
SELECT {_STAT_COLUMNS}
FROM player_game_stats
WHERE league = $1 AND bdl_game_id = $2 AND bdl_team_id = $3
"""

# No snapshot_at predicate. team_absences applies T, including the NULL-tip
# midnight, so this query cannot drift from --hours-before-tip.
PLAYER_INJURIES_SQL = """
SELECT league, snapshot_at, bdl_player_id, listed, status
FROM injury_snapshots
WHERE league = $1 AND bdl_player_id = ANY($2::integer[])
ORDER BY bdl_player_id, snapshot_at
"""

ABSENCE_QUERIES = (
    INJURIES_SQL,
    LINEUPS_SQL,
    PROJECTED_SQL,
    COVERAGE_SQL,
    ABSENCE_GAME_SQL,
    TEAM_WINDOW_SQL,
    TEAM_WINDOW_STATS_SQL,
    LATEST_PRIOR_SQL,
    TARGET_TEAM_STATS_SQL,
    PLAYER_INJURIES_SQL,
)


def _injury(record: asyncpg.Record) -> InjuryRecord:
    status = record["status"]
    return InjuryRecord(
        league=str(record["league"]),
        snapshot_at=record["snapshot_at"],
        bdl_player_id=int(record["bdl_player_id"]),
        listed=bool(record["listed"]),
        status=None if status is None else str(status),
    )


def _lineup(record: asyncpg.Record) -> LineupRecord:
    return LineupRecord(
        league=str(record["league"]),
        bdl_game_id=int(record["bdl_game_id"]),
        bdl_player_id=int(record["bdl_player_id"]),
        bdl_team_id=_optional_int(record["bdl_team_id"]),
        starter=bool(record["starter"]),
    )


def _projected(record: asyncpg.Record) -> ProjectedStarterRow:
    return ProjectedStarterRow(
        league=str(record["league"]),
        bdl_game_id=int(record["bdl_game_id"]),
        bdl_team_id=int(record["bdl_team_id"]),
        updated_at=record["updated_at"],
        first_seen_at=record["first_seen_at"],
        bdl_player_id=int(record["bdl_player_id"]),
    )


async def injury_coverage_status(conn: asyncpg.Connection) -> tuple[str, str]:
    """Return ``(unknown, note)`` until ``source_covered`` has a reader.

    Migration 005 is not on this branch. A missing relation and a relation
    this module does not know how to read both mean the same thing: do not
    treat a player with no injury row as healthy.

    The note names the relation. It does not contain a DSN.
    """
    require_absence_source("injury_snapshots")
    rows = await _fetch(conn, COVERAGE_SQL)
    present = bool(rows) and rows[0]["name"] is not None
    if not present:
        return "unknown", "source_covered is not in the schema"
    return "unknown", "source_covered is present but this export does not read its columns"


async def load_injuries(conn: asyncpg.Connection, *, league: str) -> list[InjuryRecord]:
    """Load every injury snapshot for the league.

    The training export filters ``snapshot_at <= T`` per game afterwards.
    """
    require_absence_source("injury_snapshots")
    return [_injury(record) for record in await _fetch(conn, INJURIES_SQL, league)]


async def load_lineups(
    conn: asyncpg.Connection,
    *,
    league: str,
    seasons: range,
) -> list[LineupRecord]:
    """Load ``game_lineups`` one season at a time."""
    require_absence_source("game_lineups")
    rows: list[LineupRecord] = []
    for season in seasons:
        for record in await _fetch(conn, LINEUPS_SQL, league, season):
            rows.append(_lineup(record))
    return rows


async def load_projected_starters(
    conn: asyncpg.Connection,
    *,
    league: str,
    seasons: range,
) -> list[ProjectedStarterRow]:
    """Load projected starters one season at a time.

    Versions whose ``first_seen_at`` is after T stay in this list. The
    starter rule drops them.
    """
    require_absence_source("projected_lineups")
    require_absence_source("projected_lineup_players")
    rows: list[ProjectedStarterRow] = []
    for season in seasons:
        for record in await _fetch(conn, PROJECTED_SQL, league, season):
            rows.append(_projected(record))
    return rows


def _dedupe_stats(rows: Sequence[StatRecord]) -> tuple[StatRecord, ...]:
    seen: set[tuple[int, int]] = set()
    ordered: list[StatRecord] = []
    for row in rows:
        key = (row.bdl_game_id, row.bdl_player_id)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(row)
    return tuple(ordered)


async def load_team_absence_inputs(
    conn: asyncpg.Connection,
    *,
    league: str,
    team: int,
    game: int,
) -> TeamAbsenceInputs:
    """Load one team's absence inputs without the rest of the history.

    This is the live path. It reads the target game, that team's last 10
    earlier games, the latest earlier game of each player who appeared in
    that window, the target game's rows for the team, and those players'
    injury snapshots. It does not read other seasons as a block and it does
    not filter injury rows by T.
    """
    require_feature_source("games")
    require_feature_source("player_game_stats")
    require_absence_source("injury_snapshots")
    found = await _fetch(conn, ABSENCE_GAME_SQL, league, game)
    if not found:
        raise LoadError(f"game {game} was not found")
    target_date = found[0]["date"]
    season = int(found[0]["season"])
    window = await _fetch(conn, TEAM_WINDOW_SQL, league, team, target_date)
    game_ids = [int(record["bdl_game_id"]) for record in window]
    stats: list[StatRecord] = []
    if game_ids:
        for record in await _fetch(conn, TEAM_WINDOW_STATS_SQL, league, team, game_ids):
            stats.append(_stat(record))
    candidate_ids = sorted({row.bdl_player_id for row in stats})
    if candidate_ids:
        for record in await _fetch(conn, LATEST_PRIOR_SQL, league, candidate_ids, target_date):
            stats.append(_stat(record))
    for record in await _fetch(conn, TARGET_TEAM_STATS_SQL, league, game, team):
        stats.append(_stat(record))
    injuries: list[InjuryRecord] = []
    if candidate_ids:
        for record in await _fetch(conn, PLAYER_INJURIES_SQL, league, candidate_ids):
            injuries.append(_injury(record))
    return TeamAbsenceInputs(
        target_date=target_date,
        season=season,
        stats=_dedupe_stats(stats),
        injuries=tuple(injuries),
    )
