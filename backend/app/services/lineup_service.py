from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any

from app.services.cache import cache_service
from app.services.db import db_service
from app.services.lineup_provider_rotogrinders import fetch_rotogrinders_lineups
from app.services.lineup_provider_rotowire import fetch_rotowire_lineups
from app.settings import settings


def _build_lineups_key(date: str) -> str:
    return f"lineups:nba:{date}"


def _build_lineups_meta_key(date: str) -> str:
    return f"lineups:nba:{date}:meta"


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
ON CONFLICT (date, team)
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
    date, fetched_at, team_count, status, error_message, duration_ms, source_statuses
) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
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


def _first_snapshot(lineup: dict[str, Any] | None) -> dict[str, Any]:
    snapshots = (lineup or {}).get("source_snapshots") or {}
    if not isinstance(snapshots, dict) or not snapshots:
        return {}
    return next(iter(snapshots.values()))


def _canonical_starters(lineup: dict[str, Any] | None) -> list[str]:
    snapshot = _first_snapshot(lineup)
    canonical = list(snapshot.get("canonical_starters") or [])
    if canonical:
        return canonical
    return list((lineup or {}).get("starters") or [])


def _unresolved_starters(lineup: dict[str, Any] | None) -> list[str]:
    snapshot = _first_snapshot(lineup)
    return list(snapshot.get("unresolved_starters") or [])


def build_consensus_lineups(
    *,
    date: str,
    primary_source: dict[str, dict[str, Any]],
    secondary_source: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    teams = sorted(set(primary_source) | set(secondary_source))
    consensus: dict[str, dict[str, Any]] = {}

    for team in teams:
        primary = primary_source.get(team)
        secondary = secondary_source.get(team)
        base = primary or secondary
        if not base:
            continue

        primary_starters = list((primary or {}).get("starters") or [])
        secondary_starters = list((secondary or {}).get("starters") or [])
        primary_canonical = _canonical_starters(primary)
        secondary_canonical = _canonical_starters(secondary)
        primary_unresolved = _unresolved_starters(primary)
        secondary_unresolved = _unresolved_starters(secondary)
        starters = primary_starters or secondary_starters
        bench_candidates = list(
            dict.fromkeys((base.get("bench_candidates") or []) + (secondary or {}).get("bench_candidates", []))
        )
        updated_candidates = [
            value
            for value in (
                (primary or {}).get("updated_at"),
                (secondary or {}).get("updated_at"),
            )
            if value
        ]
        updated_at = max(updated_candidates) if updated_candidates else None

        sources = []
        snapshots: dict[str, Any] = {}
        if primary:
            sources.extend(primary.get("sources") or ["rotowire"])
            snapshots.update(primary.get("source_snapshots") or {})
        if secondary:
            sources.extend(secondary.get("sources") or ["rotogrinders"])
            snapshots.update(secondary.get("source_snapshots") or {})
        sources = list(dict.fromkeys(sources))

        has_primary = len(primary_starters) == 5
        has_secondary = len(secondary_starters) == 5
        has_primary_canonical = len(primary_canonical) == 5 and not primary_unresolved
        has_secondary_canonical = len(secondary_canonical) == 5 and not secondary_unresolved
        has_unresolved = bool(primary_unresolved or secondary_unresolved)
        if has_unresolved:
            source_disagreement = False
            confidence = "low"
        elif has_primary_canonical and has_secondary_canonical:
            difference_count = len(set(primary_canonical) ^ set(secondary_canonical))
            source_disagreement = difference_count > 0
            if difference_count == 0:
                confidence = "high"
            elif difference_count <= 2:
                confidence = "medium"
            else:
                confidence = "low"
        elif has_primary or has_secondary:
            source_disagreement = False
            confidence = "low"
        else:
            source_disagreement = False
            confidence = "low"

        if has_unresolved:
            status = "partial" if starters else "unavailable"
        elif len(starters) == 5:
            status = "projected"
        elif starters:
            status = "partial"
        else:
            status = "unavailable"

        consensus[team] = {
            "date": date,
            "team": team,
            "opponent": base.get("opponent", ""),
            "home_or_away": base.get("home_or_away", ""),
            "status": status,
            "starters": starters[:5],
            "bench_candidates": bench_candidates[:7],
            "sources": sources,
            "source_disagreement": source_disagreement,
            "confidence": confidence,
            "updated_at": updated_at,
            "source_snapshots": snapshots,
        }

    return consensus


class LineupConsensusService:
    def __init__(self, max_stale_minutes: int = 20):
        self.max_stale_minutes = max_stale_minutes
        self._refresh_locks: set[str] = set()

    async def get_lineups(self, date: str) -> LineupReadResult:
        cache_key = _build_lineups_key(date)
        meta_key = _build_lineups_meta_key(date)

        cached_data = await cache_service.get(cache_key)
        cached_meta = await cache_service.get(meta_key)
        if isinstance(cached_data, dict):
            fetched_at = (cached_meta or {}).get("fetched_at")
            if self._is_stale(cached_meta):
                self._trigger_background_refresh(date)
                return LineupReadResult(date=date, lineups=cached_data, fetched_at=fetched_at, cache_state="stale")
            return LineupReadResult(date=date, lineups=cached_data, fetched_at=fetched_at, cache_state="fresh")

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
            primary_source, secondary_source = await asyncio.gather(
                asyncio.to_thread(fetch_rotowire_lineups, date),
                asyncio.to_thread(fetch_rotogrinders_lineups, date),
                return_exceptions=True,
            )

            if isinstance(primary_source, Exception):
                source_statuses["rotowire"] = {"status": "error", "message": str(primary_source)}
                primary_payload = {}
            else:
                source_statuses["rotowire"] = {"status": "success", "team_count": len(primary_source)}
                primary_payload = primary_source

            if isinstance(secondary_source, Exception):
                source_statuses["rotogrinders"] = {"status": "error", "message": str(secondary_source)}
                secondary_payload = {}
            else:
                source_statuses["rotogrinders"] = {"status": "success", "team_count": len(secondary_source)}
                secondary_payload = secondary_source

            lineups = build_consensus_lineups(
                date=date,
                primary_source=primary_payload,
                secondary_source=secondary_payload,
            )

            if not lineups and not primary_payload and not secondary_payload:
                raise RuntimeError("Both free lineup sources returned no usable data")

            await self._write_to_redis(date, lineups)
            try:
                await self._write_to_postgres(date, lineups)
            except Exception as exc:
                print(f"⚠️ 寫入 lineup PostgreSQL 失敗（不影響主流程）: {exc}")

            deleted = await cache_service.clear_daily_picks_cache()
            if deleted > 0:
                print(f"🗑️ lineup refresh cleared {deleted} daily picks cache keys")

            return lineups

        except Exception as exc:
            status = "error"
            error_message = str(exc)
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
        await cache_service.set(_build_lineups_key(date), lineups, ttl=ttl)
        await cache_service.set(
            _build_lineups_meta_key(date),
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
            )
        except Exception as exc:
            print(f"⚠️ 寫入 lineup fetch log 失敗: {exc}")


lineup_service = LineupConsensusService(max_stale_minutes=settings.lineup_stale_minutes)
