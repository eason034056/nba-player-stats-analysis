"""Write parsed injury-report rows into Postgres.

``ingest_report`` parses one stored PDF and inserts its rows.
``ingest_store`` does that for every PDF in the cache. A second call
with the same PDF writes nothing new. A later PDF with the same title
minute updates the columns a report can correct, including status and
reason, and deletes rows for that minute that the new file does not
name. A PDF that will not parse records an error on
``source_refreshes``. The first failure for that minute is
``complete = false``. A later failure keeps an earlier complete row
complete and still stores the error. The batch continues.

``injury_rows_as_of`` reads the rows of the latest report with
``report_at <= T``. T is tip-off minus 3 hours when you omit ``as_of``.

There is no HTTP route. Nothing here publishes a player list.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

import asyncpg

from app.services.injury_report_parser import (
    InjuryRow,
    ParseFailure,
    ParsedReport,
    parse_pdf,
)
from app.services.injury_report_store import LocalInjuryReportStore
from app.services.injury_report_types import RunReport, Stored

logger = logging.getLogger(__name__)

# Must match the value added to source_refreshes.source in migration 006.
# 'injuries' stays the BALLDONTLIE list.
OFFICIAL_SOURCE = "injuries_nba_official"

# Official injury PDFs are NBA. Bound into SQL so the league is not a literal.
# There is no WNBA source here.
LEAGUE = "nba"

# BALLDONTLIE sometimes stores a shorter abbreviation than the PDF.
_ABBR_ALIASES = {
    "GS": "GSW",
    "NY": "NYK",
    "NO": "NOP",
    "SA": "SAS",
    "PHO": "PHX",
    "WSH": "WAS",
    "UTAH": "UTA",
}

# bdl_player_id and match_method stay null on insert and are not updated.
# A later match must survive a re-ingest. A resolved game id stays when
# this file cannot resolve the game: the written value is
# COALESCE(EXCLUDED, stored). The WHERE compares that same value, so a
# miss is not a change. An identical row makes RETURNING empty.
_INSERT_ROW = """
INSERT INTO nba_injury_report_rows (
    league, report_at, game_date, game_time_et, matchup, team_name,
    bdl_game_id, bdl_team_id, player_raw, bdl_player_id, match_method,
    status, reason, category, previous_status,
    not_yet_submitted, all_players_available
) VALUES (
    $1, $2, $3, $4, $5, $6,
    $7, $8, $9, NULL, NULL,
    $10, $11, $12, $13,
    $14, $15
)
ON CONFLICT ON CONSTRAINT nba_injury_report_rows_natural_key DO UPDATE
SET game_time_et = EXCLUDED.game_time_et,
    bdl_game_id = COALESCE(EXCLUDED.bdl_game_id, nba_injury_report_rows.bdl_game_id),
    bdl_team_id = COALESCE(EXCLUDED.bdl_team_id, nba_injury_report_rows.bdl_team_id),
    status = EXCLUDED.status,
    reason = EXCLUDED.reason,
    category = EXCLUDED.category,
    previous_status = EXCLUDED.previous_status,
    all_players_available = EXCLUDED.all_players_available
WHERE nba_injury_report_rows.game_time_et IS DISTINCT FROM EXCLUDED.game_time_et
   OR nba_injury_report_rows.bdl_game_id IS DISTINCT FROM COALESCE(EXCLUDED.bdl_game_id, nba_injury_report_rows.bdl_game_id)
   OR nba_injury_report_rows.bdl_team_id IS DISTINCT FROM COALESCE(EXCLUDED.bdl_team_id, nba_injury_report_rows.bdl_team_id)
   OR nba_injury_report_rows.status IS DISTINCT FROM EXCLUDED.status
   OR nba_injury_report_rows.reason IS DISTINCT FROM EXCLUDED.reason
   OR nba_injury_report_rows.category IS DISTINCT FROM EXCLUDED.category
   OR nba_injury_report_rows.previous_status IS DISTINCT FROM EXCLUDED.previous_status
   OR nba_injury_report_rows.all_players_available IS DISTINCT FROM EXCLUDED.all_players_available
RETURNING 1
"""

# One row per (league, source, refreshed_at).
# An incomplete row is replaced. A call that wrote rows replaces a
# complete row and may clear error. A later failure (error set, zero
# rows written) records error and leaves complete, rows_seen, and
# rows_written alone. An identical retry matches none of those and
# leaves the row in place.
_INSERT_REFRESH = """
INSERT INTO source_refreshes (
    league, source, refreshed_at, complete, rows_seen, rows_written, error
) VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (league, source, refreshed_at) DO UPDATE
SET complete = CASE
        WHEN source_refreshes.complete AND EXCLUDED.rows_written = 0
        THEN source_refreshes.complete
        ELSE EXCLUDED.complete
    END,
    rows_seen = CASE
        WHEN source_refreshes.complete AND EXCLUDED.rows_written = 0
        THEN source_refreshes.rows_seen
        ELSE EXCLUDED.rows_seen
    END,
    rows_written = CASE
        WHEN source_refreshes.complete AND EXCLUDED.rows_written = 0
        THEN source_refreshes.rows_written
        ELSE EXCLUDED.rows_written
    END,
    error = EXCLUDED.error
WHERE source_refreshes.complete = false
   OR EXCLUDED.rows_written > 0
   OR EXCLUDED.error IS NOT NULL
RETURNING complete
"""

# The newest successful file for one report minute replaces that minute.
# A stored natural key that is absent from this file is deleted.
# league and report_at are the same on every parsed row, so the other
# five key columns decide which stored rows stay. Another report_at
# is outside this DELETE.
_DELETE_ABSENT = """
DELETE FROM nba_injury_report_rows AS stored
WHERE stored.league = $1
  AND stored.report_at = $2
  AND NOT EXISTS (
      SELECT 1
      FROM jsonb_to_recordset($3::jsonb) AS kept(
          game_date date,
          matchup text,
          team_name text,
          player_raw text,
          not_yet_submitted boolean
      )
      WHERE kept.game_date = stored.game_date
        AND kept.matchup = stored.matchup
        AND kept.team_name = stored.team_name
        AND kept.player_raw = stored.player_raw
        AND kept.not_yet_submitted = stored.not_yet_submitted
  )
RETURNING 1
"""

_GAMES_ON_DATES = """
SELECT g.date, g.bdl_game_id, g.home_team_id, g.visitor_team_id,
       g.postponed,
       ht.abbreviation AS home_abbr, vt.abbreviation AS away_abbr,
       ht.full_name AS home_name, vt.full_name AS away_name
FROM games g
JOIN teams ht ON ht.league = g.league AND ht.bdl_team_id = g.home_team_id
JOIN teams vt ON vt.league = g.league AND vt.bdl_team_id = g.visitor_team_id
WHERE g.league = $1 AND g.date = ANY($2::date[])
ORDER BY g.bdl_game_id
"""


@dataclass(frozen=True)
class IngestOutcome:
    """What one PDF did when it was ingested.

    ``tag`` is ``stored`` (rows were written or a failure row was saved),
    ``unchanged`` (the same report was already stored), ``failed``
    (the PDF did not parse, or the write failed), or ``dry_run``
    (parsed only). ``rows_written`` counts rows this call inserted,
    corrected, or deleted. An identical retry reports 0. A changed
    status counts. A player missing from the new file counts.
    """

    tag: Literal["stored", "unchanged", "failed", "dry_run"]
    filename: str
    report_at: datetime | None
    rows_seen: int
    rows_written: int
    error: str | None


@dataclass(frozen=True)
class _Resolved:
    bdl_game_id: int | None
    bdl_team_id: int | None


def canonical_abbr(code: str) -> str:
    """Fold a team abbreviation to the PDF form. ``GS`` becomes ``GSW``."""
    text = (code or "").strip().upper()
    return _ABBR_ALIASES.get(text, text)


async def ingest_report(
    conn: asyncpg.Connection,
    stored: Stored,
    *,
    dry_run: bool = False,
    league: str = LEAGUE,
) -> IngestOutcome:
    """Parse ``stored`` and insert its rows.

    ``ingest_report`` reads the PDF from ``stored.path``. Re-running it
    for the same report inserts nothing new. A PDF that changes a
    corrected column updates that row. A player or team note that the
    new file drops is deleted for that same report minute. ``dry_run``
    true parses and resolves game ids, then writes nothing.

    Args:
        conn: An open connection. The caller owns it.
        stored: A PDF the cache already saved.
        dry_run: When true, do not insert.
        league: League code stored on each row. The default is ``nba``.

    Returns:
        An ``IngestOutcome``. A bad PDF returns ``tag="failed"`` and
        does not raise.
    """
    filename = stored.path.name
    try:
        data = stored.path.read_bytes()
    except OSError as exc:
        return await _record_failure(
            conn,
            filename=filename,
            report_at=_stamp(stored.last_modified_utc) or _stamp(stored.fetched_at),
            error=f"{type(exc).__name__}",
            dry_run=dry_run,
            league=league,
        )
    parsed = parse_pdf(
        data,
        last_modified=_stamp(stored.last_modified_utc),
        filename=filename,
    )
    if isinstance(parsed, ParseFailure):
        report_at = parsed.report_at or _stamp(stored.fetched_at)
        return await _record_failure(
            conn,
            filename=filename,
            report_at=report_at,
            error=parsed.error,
            dry_run=dry_run,
            league=league,
        )
    return await _write_report(conn, filename, parsed, dry_run=dry_run, league=league)


async def ingest_store(
    conn: asyncpg.Connection,
    store: LocalInjuryReportStore,
    *,
    dry_run: bool = False,
    league: str = LEAGUE,
) -> list[IngestOutcome]:
    """Ingest every stored PDF. One bad file does not stop the rest.

    ``ingest_store`` walks ``store.iter_stored`` and calls
    ``ingest_report``. Pass ``dry_run=True`` to parse without writing.

    Args:
        conn: An open connection.
        store: The SPO-149 cache.
        dry_run: When true, write nothing.
        league: League code passed to each ``ingest_report``. The default is ``nba``.

    Returns:
        One outcome per stored PDF, in path order.
    """
    outcomes: list[IngestOutcome] = []
    for stored in store.iter_stored():
        try:
            outcomes.append(await ingest_report(conn, stored, dry_run=dry_run, league=league))
        except Exception as exc:
            logger.warning("injury report ingest failed (%s)", type(exc).__name__)
            outcomes.append(
                IngestOutcome(
                    tag="failed",
                    filename=stored.path.name,
                    report_at=None,
                    rows_seen=0,
                    rows_written=0,
                    error=type(exc).__name__,
                )
            )
    return outcomes


async def ingest_fetch_results(report: RunReport) -> None:
    """Ingest PDFs a fetch just stored.

    The scheduler calls this after ``fetch_current_slot``, and only
    from the job that runs when ``INJURY_PDF_FETCH_ENABLED`` is true.
    A missing database pool returns without writing. Player names are
    not logged.

    Args:
        report: The fetch ``RunReport``. Objects that are not a
            ``RunReport`` are ignored.
    """
    results = getattr(report, "results", None)
    if not isinstance(results, tuple):
        return
    stored = [item for item in results if isinstance(item, Stored)]
    if not stored:
        return
    from app.services.db import db_service

    if not db_service.is_connected or db_service._pool is None:
        logger.info("injury report ingest skipped; database is not connected")
        return
    async with db_service._pool.acquire() as conn:
        for item in stored:
            try:
                outcome = await ingest_report(conn, item, dry_run=False)
            except Exception as exc:
                logger.warning("injury report ingest failed (%s)", type(exc).__name__)
                continue
            logger.info(
                "injury report ingest %s rows_seen=%s rows_written=%s",
                outcome.tag,
                outcome.rows_seen,
                outcome.rows_written,
            )


async def injury_rows_as_of(
    conn: asyncpg.Connection,
    bdl_game_id: int,
    *,
    league: str = LEAGUE,
    as_of: datetime | None = None,
) -> list[asyncpg.Record]:
    """Rows from the latest official report with ``report_at <= T``.

    ``injury_rows_as_of`` calls ``injury_report_rows_asof``. T is
    ``as_of`` when you pass it. Otherwise T is ``game_as_of`` (tip-off
    minus 3 hours). A report timestamp equal to T is returned. A report
    one second later is not, even if that row is in the table.

    Args:
        conn: An open connection.
        bdl_game_id: The game to read.
        league: ``nba``.
        as_of: An aware instant used as T. None uses the game's tip.

    Returns:
        The rows of that one report. Empty when no report is at or before T.
    """
    if as_of is None:
        return list(await conn.fetch(
            "SELECT * FROM injury_report_rows_asof($1, $2)",
            league,
            bdl_game_id,
        ))
    return list(await conn.fetch(
        "SELECT * FROM injury_report_rows_asof($1, $2, $3)",
        league,
        bdl_game_id,
        as_of,
    ))


async def _write_report(
    conn: asyncpg.Connection,
    filename: str,
    parsed: ParsedReport,
    *,
    dry_run: bool,
    league: str = LEAGUE,
) -> IngestOutcome:
    resolved = await _resolve(conn, parsed.rows, league)
    if dry_run:
        return IngestOutcome(
            tag="dry_run",
            filename=filename,
            report_at=parsed.report_at,
            rows_seen=len(parsed.rows),
            rows_written=0,
            error=None,
        )
    try:
        async with conn.transaction():
            written = 0
            for row, ids in zip(parsed.rows, resolved, strict=True):
                inserted = await conn.fetch(
                    _INSERT_ROW,
                    league,
                    parsed.report_at,
                    row.game_date,
                    row.game_time_et,
                    row.matchup,
                    row.team_name,
                    ids.bdl_game_id,
                    ids.bdl_team_id,
                    row.player_raw,
                    row.status,
                    row.reason,
                    row.category,
                    row.previous_status,
                    row.not_yet_submitted,
                    row.all_players_available,
                )
                written += len(inserted)
            # Same transaction as the upserts. dry_run returned above,
            # so this DELETE does not run then. report_at is this file's
            # minute only.
            kept = json.dumps([
                {
                    "game_date": row.game_date.isoformat(),
                    "matchup": row.matchup,
                    "team_name": row.team_name,
                    "player_raw": row.player_raw,
                    "not_yet_submitted": row.not_yet_submitted,
                }
                for row in parsed.rows
            ])
            removed = await conn.fetch(
                _DELETE_ABSENT,
                league,
                parsed.report_at,
                kept,
            )
            written += len(removed)
            refresh = await conn.fetch(
                _INSERT_REFRESH,
                league,
                OFFICIAL_SOURCE,
                parsed.report_at,
                True,
                len(parsed.rows),
                written,
                None,
            )
    except Exception as exc:
        logger.warning("injury report write failed (%s)", type(exc).__name__)
        return await _record_failure(
            conn,
            filename=filename,
            report_at=parsed.report_at,
            error=type(exc).__name__,
            dry_run=False,
            league=league,
        )
    if written == 0 and not refresh:
        tag: Literal["stored", "unchanged"] = "unchanged"
    else:
        tag = "stored"
    return IngestOutcome(
        tag=tag,
        filename=filename,
        report_at=parsed.report_at,
        rows_seen=len(parsed.rows),
        rows_written=written,
        error=None,
    )


async def _record_failure(
    conn: asyncpg.Connection,
    *,
    filename: str,
    report_at: datetime | None,
    error: str,
    dry_run: bool,
    league: str = LEAGUE,
) -> IngestOutcome:
    if report_at is None:
        return IngestOutcome(
            tag="failed",
            filename=filename,
            report_at=None,
            rows_seen=0,
            rows_written=0,
            error=error,
        )
    if not dry_run:
        await conn.fetch(
            _INSERT_REFRESH,
            league,
            OFFICIAL_SOURCE,
            report_at,
            False,
            0,
            0,
            error,
        )
    return IngestOutcome(
        tag="failed",
        filename=filename,
        report_at=report_at,
        rows_seen=0,
        rows_written=0,
        error=error,
    )


async def _resolve(
    conn: asyncpg.Connection, rows: tuple[InjuryRow, ...], league: str
) -> list[_Resolved]:
    dates = list({row.game_date for row in rows})
    found: dict[tuple[date, str, str], tuple[int, int, int, bool]] = {}
    if dates:
        for game in await conn.fetch(_GAMES_ON_DATES, league, dates):
            key = (game["date"], canonical_abbr(game["away_abbr"] or ""), canonical_abbr(game["home_abbr"] or ""))
            current = found.get(key)
            postponed = bool(game["postponed"])
            # Prefer a game that was not postponed. The lowest id wins a tie.
            if current is None or (current[3] and not postponed):
                found[key] = (
                    int(game["bdl_game_id"]),
                    int(game["visitor_team_id"]),
                    int(game["home_team_id"]),
                    postponed,
                )
    resolved: list[_Resolved] = []
    for row in rows:
        away, _, home = row.matchup.partition("@")
        game = found.get((row.game_date, canonical_abbr(away), canonical_abbr(home)))
        if game is None:
            resolved.append(_Resolved(None, None))
            continue
        game_id, away_id, home_id, _postponed = game
        team_id: int | None = None
        if row.team_abbr and canonical_abbr(row.team_abbr) == canonical_abbr(away):
            team_id = away_id
        elif row.team_abbr and canonical_abbr(row.team_abbr) == canonical_abbr(home):
            team_id = home_id
        resolved.append(_Resolved(game_id, team_id))
    return resolved


def _stamp(value: str | None) -> datetime | None:
    """Parse a ``Z`` timestamp from a sidecar. Bad text returns None."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)
