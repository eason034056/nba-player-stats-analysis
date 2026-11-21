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
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlsplit

import asyncpg

from app.dsn import redact_secrets
from app.ml.sources import require_feature_source, require_label_source

_URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")

GAMES_SQL = """
SELECT league, bdl_game_id, season, date, datetime_utc, season_type, home_team_id
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

READ_QUERIES = (GAMES_SQL, STATS_SQL, ACTUALS_SQL)


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


def _game(record: asyncpg.Record) -> GameRecord:
    return GameRecord(
        league=str(record["league"]),
        bdl_game_id=int(record["bdl_game_id"]),
        season=int(record["season"]),
        game_date=record["date"],
        datetime_utc=record["datetime_utc"],
        season_type=str(record["season_type"]),
        home_team_id=_optional_int(record["home_team_id"]),
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
