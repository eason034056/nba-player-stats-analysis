from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any

from app.services.cache import cache_service
from app.services.db import db_service
from app.services.lineup_provider_bdl import (
    LINEUP_SOURCE,
    BdlLineupFetch,
    ProjectedLineupWrite,
    fetch_nba_lineups,
)
from app.settings import settings

logger = logging.getLogger(__name__)


def _build_lineups_key(date: str, league: str = "nba") -> str:
    """Redis key for one NBA slate date.

    The key is ``lineups:nba:{date}``. ``league`` must be ``nba``.

    Raises:
        ValueError: ``league`` is not ``nba``.
    """
    if league != "nba":
        raise ValueError(f"Unsupported league for lineup cache: {league!r}")
    return f"lineups:nba:{date}"


def _build_lineups_meta_key(date: str, league: str = "nba") -> str:
    """Redis meta key beside ``_build_lineups_key``."""
    return f"{_build_lineups_key(date, league)}:meta"


UPSERT_LINEUP_SQL = """
INSERT INTO team_lineup_snapshots (
    date, team, opponent, home_or_away, status,
    starters, bench_candidates, sources,
    source_disagreement, confidence, updated_at, source_snapshots, fetched_at
) VALUES (
    $1, $2, $3, $4, $5,
    $6::jsonb, $7::jsonb, $8::jsonb,
    $9, $10, $11, $12::jsonb, $13
)
-- ⚠️ Must match the SPO-35 widened UNIQUE constraint
-- (date, team, league) — Postgres ON CONFLICT requires an exact
-- column-tuple match. The league column is omitted from the column
-- list above, so the DEFAULT 'nba' fills it in for NBA writes and
-- the inference resolves against the existing NBA row. The league
-- column stays on the key because BALLDONTLIE ids can overlap. This
-- writer does not insert a non-nba league.
ON CONFLICT (date, team, league)
DO UPDATE SET
    opponent = EXCLUDED.opponent,
    home_or_away = EXCLUDED.home_or_away,
    status = EXCLUDED.status,
    starters = EXCLUDED.starters,
    bench_candidates = EXCLUDED.bench_candidates,
    sources = EXCLUDED.sources,
    source_disagreement = EXCLUDED.source_disagreement,
    confidence = EXCLUDED.confidence,
    updated_at = EXCLUDED.updated_at,
    source_snapshots = EXCLUDED.source_snapshots,
    fetched_at = EXCLUDED.fetched_at
"""

INSERT_FETCH_LOG_SQL = """
INSERT INTO lineup_fetch_logs (
    date, fetched_at, team_count, status, error_message, duration_ms, source_statuses, league
) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
"""


@dataclass
class LineupReadResult:
    date: str
    lineups: dict[str, dict[str, Any]]
    fetched_at: str | None
    cache_state: str


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def confirmation_status(lineup: dict[str, Any] | None) -> str | None:
    """Confirmation for one team lineup.

    ``confirmed`` when any ``source_snapshots`` entry has
    ``status == "confirmed"``. One confirmation is enough.

    ``projected`` when the record has a snapshot or a starter and
    nobody reported confirmed. ``expected`` falls here.

    ``None`` when there is no lineup record.

    The existing ``status`` field is a different word. It stays
    ``projected``, ``partial``, or ``unavailable`` from the starter
    count. This function does not change that field.
    """
    if not lineup:
        return None
    snapshots = lineup.get("source_snapshots") or {}
    if not isinstance(snapshots, dict):
        snapshots = {}
    saw_snapshot = False
    for snapshot in snapshots.values():
        if not isinstance(snapshot, dict):
            continue
        saw_snapshot = True
        reported = str(snapshot.get("status") or "").strip().lower()
        if reported == "confirmed":
            return "confirmed"
    starters = lineup.get("starters") or []
    if saw_snapshot or starters:
        return "projected"
    return None


class LineupConsensusService:
    """NBA lineups from BALLDONTLIE projected lineups.

    One fetch is stored in Redis and in ``team_lineup_snapshots``.
    ``league`` must be ``nba``; it is stored on the fetch log so the row
    matches the ``league`` column. When ``games``, ``teams``, and
    ``players`` rows already exist, the same poll also writes
    ``projected_lineups``. A missing parent does not fail the live fetch.
    """

    def __init__(self, max_stale_minutes: int = 20, league: str = "nba"):
        if league != "nba":
            raise ValueError(f"Unsupported league for lineups: {league!r}")
        self.max_stale_minutes = max_stale_minutes
        self.league = league
        self._refresh_locks: set[str] = set()

    async def get_lineups(self, date: str) -> LineupReadResult:
        cache_key = _build_lineups_key(date, league=self.league)
        meta_key = _build_lineups_meta_key(date, league=self.league)

        cached_data = await cache_service.get(cache_key)
        cached_meta = await cache_service.get(meta_key)
        if isinstance(cached_data, dict):
            fetched_at = (cached_meta or {}).get("fetched_at")
            if self._is_stale(cached_meta):
                self._trigger_background_refresh(date)
                return LineupReadResult(date=date, lineups=cached_data, fetched_at=fetched_at, cache_state="stale")
            state = "stale" if self._is_stale(cached_meta) else "fresh"
            return LineupReadResult(date=date, lineups=cached_data, fetched_at=fetched_at, cache_state=state)

        try:
            lineups = await self.fetch_and_store(date)
            return LineupReadResult(
                date=date,
                lineups=lineups,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                cache_state="refreshed",
            )
        except Exception:
            pg_lineups = await self._read_from_postgres(date)
            if pg_lineups:
                await self._write_to_redis(date, pg_lineups)
                return LineupReadResult(date=date, lineups=pg_lineups, fetched_at=datetime.now(timezone.utc).isoformat(), cache_state="stale")
            return LineupReadResult(date=date, lineups={}, fetched_at=None, cache_state="fresh")

    async def peek_lineups(self, date: str) -> dict[str, dict[str, Any]]:
        """Lineups already stored for ``date``. Does not call BALLDONTLIE.

        The events route reads this so a cold cache does not fetch
        projected lineups while listing games. A Redis miss falls
        through to PostgreSQL. Any failure is an empty slate, and the
        event's lineup status stays null.
        """
        try:
            cached = await cache_service.get(_build_lineups_key(date, league=self.league))
        except Exception:
            cached = None
        if isinstance(cached, dict):
            return cached
        try:
            stored = await self._read_from_postgres(date)
        except Exception:
            return {}
        return stored or {}

    async def get_team_lineup(self, date: str, team: str) -> tuple[dict[str, Any] | None, str, str | None]:
        result = await self.get_lineups(date)
        normalized_team = str(team or "").upper()
        return result.lineups.get(normalized_team), result.cache_state, result.fetched_at

    async def fetch_and_store(self, date: str) -> dict[str, dict[str, Any]]:
        started = time.time()
        status = "success"
        error_message = None
        source_statuses: dict[str, Any] = {}
        lineups: dict[str, dict[str, Any]] = {}

        try:
            fetched = await fetch_nba_lineups(date)
            lineups = fetched.lineups
            source_statuses[LINEUP_SOURCE] = {
                "status": "success",
                "team_count": len(lineups),
                "team_misses": fetched.misses,
            }

            await self._write_to_redis(date, lineups)
            try:
                await self._write_to_postgres(date, lineups)
                await self._delete_omitted_snapshots(date, lineups)
            except Exception as exc:
                print(f"⚠️ 寫入 lineup PostgreSQL 失敗（不影響主流程）: {type(exc).__name__}")

            try:
                refresh = await self._write_projected_lineups(fetched)
                source_statuses[LINEUP_SOURCE]["projected_rows_written"] = refresh["rows_written"]
                source_statuses[LINEUP_SOURCE]["projected_misses"] = refresh["misses"]
            except Exception as exc:
                logger.warning(
                    "projected_lineups dual-write skipped (%s)",
                    type(exc).__name__,
                )

            deleted = await cache_service.clear_daily_picks_cache(league="nba")
            if deleted > 0:
                print(f"🗑️ lineup refresh cleared {deleted} daily picks cache keys")

            return lineups

        except Exception as exc:
            status = "error"
            error_message = type(exc).__name__
            source_statuses[LINEUP_SOURCE] = {
                "status": "error",
                "message": type(exc).__name__,
            }
            raise
        finally:
            duration_ms = int((time.time() - started) * 1000)
            await self._log_fetch(
                date=date,
                team_count=len(lineups),
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
                source_statuses=source_statuses,
            )

    def _is_stale(self, meta: dict[str, Any] | None) -> bool:
        fetched_at = _parse_iso_timestamp((meta or {}).get("fetched_at"))
        if fetched_at is None:
            return True
        age_minutes = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 60
        return age_minutes > self.max_stale_minutes

    def _trigger_background_refresh(self, date: str) -> None:
        if date in self._refresh_locks:
            return
        self._refresh_locks.add(date)

        async def _refresh() -> None:
            try:
                await self.fetch_and_store(date)
            except Exception as exc:
                print(f"⚠️ 背景 lineup refresh 失敗: {date} - {exc}")
            finally:
                self._refresh_locks.discard(date)

        asyncio.create_task(_refresh())

    async def _write_to_redis(self, date: str, lineups: dict[str, dict[str, Any]]) -> None:
        ttl = settings.cache_ttl_lineups
        await cache_service.set(
            _build_lineups_key(date, league=self.league), lineups, ttl=ttl
        )
        await cache_service.set(
            _build_lineups_meta_key(date, league=self.league),
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "team_count": len(lineups),
            },
            ttl=ttl,
        )

    async def _write_to_postgres(self, date: str, lineups: dict[str, dict[str, Any]]) -> None:
        if not db_service.is_connected or not lineups:
            return

        fetched_at = datetime.now(timezone.utc)
        parsed_date = date_type.fromisoformat(date)
        args_list: list[tuple[Any, ...]] = []
        for lineup in lineups.values():
            updated_at = _parse_iso_timestamp(lineup.get("updated_at")) or fetched_at
            args_list.append(
                (
                    parsed_date,
                    lineup.get("team"),
                    lineup.get("opponent"),
                    lineup.get("home_or_away"),
                    lineup.get("status"),
                    json.dumps(lineup.get("starters") or []),
                    json.dumps(lineup.get("bench_candidates") or []),
                    json.dumps(lineup.get("sources") or []),
                    bool(lineup.get("source_disagreement")),
                    lineup.get("confidence"),
                    updated_at,
                    json.dumps(lineup.get("source_snapshots") or {}),
                    fetched_at,
                )
            )

        await db_service.executemany(UPSERT_LINEUP_SQL, args_list)

    async def _delete_omitted_snapshots(self, date: str, lineups: dict[str, dict[str, Any]]) -> None:
        """Drop NBA snapshot rows for teams this fetch did not return.

        An empty slate deletes every NBA row for that date, so a later
        cache miss does not keep a badge for a lineup BALLDONTLIE omitted.
        """
        if not db_service.is_connected:
            return
        await db_service.execute(
            """
            DELETE FROM team_lineup_snapshots
            WHERE date = $1 AND league = 'nba' AND NOT (team = ANY($2::text[]))
            """,
            date_type.fromisoformat(date),
            list(lineups.keys()),
        )

    async def _projected_parents_exist(self, row: ProjectedLineupWrite) -> bool:
        """True when ``games``, ``teams``, and every starter ``players`` row exist."""
        game = await db_service.fetchrow(
            "SELECT 1 AS ok FROM games WHERE league = 'nba' AND bdl_game_id = $1",
            row.game_id,
        )
        if game is None:
            return False
        team = await db_service.fetchrow(
            "SELECT 1 AS ok FROM teams WHERE league = 'nba' AND bdl_team_id = $1",
            row.team_id,
        )
        if team is None:
            return False
        if not row.players:
            return True
        player_ids = [player_id for player_id, _position in row.players]
        found = await db_service.fetch(
            """
            SELECT bdl_player_id FROM players
            WHERE league = 'nba' AND bdl_player_id = ANY($1::int[])
            """,
            player_ids,
        )
        return {item["bdl_player_id"] for item in found} == set(player_ids)

    async def _insert_projected_version(self, row: ProjectedLineupWrite, seen_at: datetime) -> None:
        """Insert one version. A replay keeps the original ``first_seen_at``."""
        if db_service._pool is None:
            return
        async with db_service._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO projected_lineups (
                        league, bdl_game_id, bdl_team_id, updated_at, first_seen_at, status
                    ) VALUES ('nba', $1, $2, $3, $4, $5)
                    ON CONFLICT (league, bdl_game_id, bdl_team_id, updated_at) DO NOTHING
                    """,
                    row.game_id,
                    row.team_id,
                    row.updated_at,
                    seen_at,
                    row.status,
                )
                if row.players:
                    await conn.executemany(
                        """
                        INSERT INTO projected_lineup_players (
                            league, bdl_game_id, bdl_team_id, updated_at, bdl_player_id, position
                        ) VALUES ('nba', $1, $2, $3, $4, $5)
                        ON CONFLICT (league, bdl_game_id, bdl_team_id, updated_at, bdl_player_id)
                        DO NOTHING
                        """,
                        [
                            (row.game_id, row.team_id, row.updated_at, player_id, position)
                            for player_id, position in row.players
                        ],
                    )

    async def _write_projected_lineups(self, fetched: BdlLineupFetch) -> dict[str, int | bool]:
        """Write 002 rows when parents exist. Never raises for a missing parent.

        ``source_refreshes.complete`` is true only when every mapped row
        was written. A poll that wrote nothing does not record
        ``complete = true``. The live snapshot write has already finished.
        """
        seen = len(fetched.writes) + fetched.misses
        if not db_service.is_connected or seen == 0:
            return {"rows_seen": seen, "rows_written": 0, "misses": fetched.misses, "recorded": False}
        written = 0
        parent_misses = 0
        seen_at = datetime.now(timezone.utc)
        for row in fetched.writes:
            try:
                if not await self._projected_parents_exist(row):
                    parent_misses += 1
                    logger.info(
                        "projected lineup parent miss game_id=%s team_id=%s",
                        row.game_id,
                        row.team_id,
                    )
                    continue
                await self._insert_projected_version(row, seen_at)
                written += 1
            except Exception as exc:
                parent_misses += 1
                logger.warning(
                    "projected lineup insert skipped game_id=%s (%s)",
                    row.game_id,
                    type(exc).__name__,
                )
        misses = parent_misses + fetched.misses
        complete = misses == 0 and written == len(fetched.writes) and written > 0
        error = None if complete else "projected lineup rows were not all written"
        await db_service.execute(
            """
            INSERT INTO source_refreshes (
                league, source, refreshed_at, complete, rows_seen, rows_written, error
            ) VALUES ('nba', 'projected_lineups', $1, $2, $3, $4, $5)
            """,
            seen_at,
            complete,
            seen,
            written,
            error,
        )
        return {
            "rows_seen": seen,
            "rows_written": written,
            "misses": misses,
            "recorded": True,
        }

    async def _read_from_postgres(self, date: str) -> dict[str, dict[str, Any]]:
        if not db_service.is_connected:
            return {}
        rows = await db_service.fetch(
            """
            SELECT team, opponent, home_or_away, status, starters, bench_candidates,
                   sources, source_disagreement, confidence, updated_at, source_snapshots
            FROM team_lineup_snapshots
            WHERE date = $1
            ORDER BY team
            """,
            date_type.fromisoformat(date),
        )
        lineups: dict[str, dict[str, Any]] = {}
        for row in rows:
            lineups[row["team"]] = {
                "date": date,
                "team": row["team"],
                "opponent": row.get("opponent"),
                "home_or_away": row.get("home_or_away"),
                "status": row.get("status"),
                "starters": row.get("starters") or [],
                "bench_candidates": row.get("bench_candidates") or [],
                "sources": row.get("sources") or [],
                "source_disagreement": bool(row.get("source_disagreement")),
                "confidence": row.get("confidence"),
                "updated_at": row.get("updated_at").isoformat() if row.get("updated_at") else None,
                "source_snapshots": row.get("source_snapshots") or {},
            }
        return lineups

    async def _log_fetch(
        self,
        *,
        date: str,
        team_count: int,
        status: str,
        error_message: str | None,
        duration_ms: int,
        source_statuses: dict[str, Any],
    ) -> None:
        if not db_service.is_connected:
            return
        try:
            await db_service.execute(
                INSERT_FETCH_LOG_SQL,
                date_type.fromisoformat(date),
                datetime.now(timezone.utc),
                team_count,
                status,
                error_message,
                duration_ms,
                json.dumps(source_statuses),
                self.league,
            )
        except Exception as exc:
            print(f"⚠️ 寫入 lineup fetch log 失敗: {exc}")


lineup_service = LineupConsensusService(max_stale_minutes=settings.lineup_stale_minutes)
