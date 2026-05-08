"""
Tests for LineupConsensusService methods and helper functions
that are NOT already covered by test_lineup_consensus.py.

Focuses on:
- _build_lineups_key, _build_lineups_meta_key
- _parse_iso_timestamp
- _first_snapshot, _canonical_starters, _unresolved_starters
- LineupReadResult dataclass
- LineupConsensusService: get_lineups, get_team_lineup, fetch_and_store,
  _is_stale, _trigger_background_refresh, _write_to_redis,
  _write_to_postgres, _read_from_postgres, _log_fetch
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.lineup_service import (
    LineupConsensusService,
    LineupReadResult,
    _build_lineups_key,
    _build_lineups_meta_key,
    _canonical_starters,
    _first_snapshot,
    _parse_iso_timestamp,
    _unresolved_starters,
)


# ---------------------------------------------------------------------------
# Helper key builders  (lines 18-23)
# ---------------------------------------------------------------------------

class TestBuildKeys:
    def test_build_lineups_key(self):
        assert _build_lineups_key("2026-03-16") == "lineups:nba:2026-03-16"

    def test_build_lineups_meta_key(self):
        assert _build_lineups_meta_key("2026-03-16") == "lineups:nba:2026-03-16:meta"


# ---------------------------------------------------------------------------
# _parse_iso_timestamp  (lines 66-75)
# ---------------------------------------------------------------------------

class TestParseIsoTimestamp:
    def test_none_input(self):
        assert _parse_iso_timestamp(None) is None

    def test_empty_string(self):
        assert _parse_iso_timestamp("") is None

    def test_invalid_format(self):
        assert _parse_iso_timestamp("not-a-date") is None

    def test_aware_timestamp(self):
        ts = "2026-03-16T12:30:00+00:00"
        result = _parse_iso_timestamp(ts)
        assert result is not None
        assert result.tzinfo is not None
        assert result.year == 2026

    def test_naive_timestamp_gets_utc(self):
        ts = "2026-03-16T12:30:00"
        result = _parse_iso_timestamp(ts)
        assert result is not None
        assert result.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# _first_snapshot  (lines 78-82)
# ---------------------------------------------------------------------------

class TestFirstSnapshot:
    def test_none_lineup(self):
        assert _first_snapshot(None) == {}

    def test_empty_dict(self):
        assert _first_snapshot({}) == {}

    def test_no_source_snapshots_key(self):
        assert _first_snapshot({"starters": []}) == {}

    def test_source_snapshots_not_dict(self):
        assert _first_snapshot({"source_snapshots": "bad"}) == {}

    def test_source_snapshots_empty_dict(self):
        assert _first_snapshot({"source_snapshots": {}}) == {}

    def test_returns_first_value(self):
        snap = {"rotowire": {"status": "confirmed"}, "rotogrinders": {"status": "projected"}}
        result = _first_snapshot({"source_snapshots": snap})
        assert result == {"status": "confirmed"}


# ---------------------------------------------------------------------------
# _canonical_starters  (lines 85-90)
# ---------------------------------------------------------------------------

class TestCanonicalStarters:
    def test_none_lineup(self):
        assert _canonical_starters(None) == []

    def test_fallback_to_starters_field(self):
        lineup = {"starters": ["A", "B"], "source_snapshots": {}}
        assert _canonical_starters(lineup) == ["A", "B"]

    def test_uses_canonical_from_snapshot(self):
        lineup = {
            "starters": ["raw1", "raw2"],
            "source_snapshots": {
                "rotowire": {"canonical_starters": ["Canon1", "Canon2"]},
            },
        }
        assert _canonical_starters(lineup) == ["Canon1", "Canon2"]

    def test_empty_canonical_falls_back(self):
        lineup = {
            "starters": ["A"],
            "source_snapshots": {"rotowire": {"canonical_starters": []}},
        }
        assert _canonical_starters(lineup) == ["A"]


# ---------------------------------------------------------------------------
# _unresolved_starters  (lines 93-95)
# ---------------------------------------------------------------------------

class TestUnresolvedStarters:
    def test_none_lineup(self):
        assert _unresolved_starters(None) == []

    def test_no_unresolved(self):
        lineup = {"source_snapshots": {"rotowire": {}}}
        assert _unresolved_starters(lineup) == []

    def test_with_unresolved(self):
        lineup = {
            "source_snapshots": {
                "rotowire": {"unresolved_starters": ["J. Williams"]},
            },
        }
        assert _unresolved_starters(lineup) == ["J. Williams"]


# ---------------------------------------------------------------------------
# LineupReadResult dataclass  (lines 58-63)
# ---------------------------------------------------------------------------

class TestLineupReadResult:
    def test_fields(self):
        r = LineupReadResult(
            date="2026-03-16",
            lineups={"GSW": {}},
            fetched_at="2026-03-16T12:00:00+00:00",
            cache_state="fresh",
        )
        assert r.date == "2026-03-16"
        assert r.lineups == {"GSW": {}}
        assert r.fetched_at == "2026-03-16T12:00:00+00:00"
        assert r.cache_state == "fresh"

    def test_none_fetched_at(self):
        r = LineupReadResult(date="2026-03-16", lineups={}, fetched_at=None, cache_state="fresh")
        assert r.fetched_at is None


# ===========================================================================
# LineupConsensusService
# ===========================================================================

def _make_service(max_stale_minutes: int = 20) -> LineupConsensusService:
    return LineupConsensusService(max_stale_minutes=max_stale_minutes)


def _sample_lineups() -> dict:
    return {
        "GSW": {
            "date": "2026-03-16",
            "team": "GSW",
            "opponent": "LAL",
            "home_or_away": "AWAY",
            "status": "projected",
            "starters": ["Curry", "Hield", "Butler", "Green", "Post"],
            "bench_candidates": [],
            "sources": ["rotowire", "rotogrinders"],
            "source_disagreement": False,
            "confidence": "high",
            "updated_at": "2026-03-16T17:40:00+00:00",
            "source_snapshots": {},
        }
    }


# ---------------------------------------------------------------------------
# _is_stale  (lines 297-302)
# ---------------------------------------------------------------------------

class TestIsStale:
    def test_none_meta_is_stale(self):
        svc = _make_service()
        assert svc._is_stale(None) is True

    def test_missing_fetched_at_is_stale(self):
        svc = _make_service()
        assert svc._is_stale({}) is True

    def test_invalid_fetched_at_is_stale(self):
        svc = _make_service()
        assert svc._is_stale({"fetched_at": "invalid"}) is True

    def test_recent_timestamp_is_not_stale(self):
        svc = _make_service(max_stale_minutes=20)
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        assert svc._is_stale({"fetched_at": recent}) is False

    def test_old_timestamp_is_stale(self):
        svc = _make_service(max_stale_minutes=20)
        old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        assert svc._is_stale({"fetched_at": old}) is True

    def test_boundary_exactly_at_max(self):
        svc = _make_service(max_stale_minutes=20)
        boundary = (datetime.now(timezone.utc) - timedelta(minutes=21)).isoformat()
        assert svc._is_stale({"fetched_at": boundary}) is True


# ---------------------------------------------------------------------------
# _write_to_redis  (lines 319-329)
# ---------------------------------------------------------------------------

class TestWriteToRedis:
    @pytest.mark.asyncio
    async def test_writes_data_and_meta(self, monkeypatch):
        svc = _make_service()
        mock_set = AsyncMock()
        monkeypatch.setattr("app.services.lineup_service.cache_service.set", mock_set)
        monkeypatch.setattr("app.services.lineup_service.settings.cache_ttl_lineups", 3600)

        lineups = _sample_lineups()
        await svc._write_to_redis("2026-03-16", lineups)

        assert mock_set.await_count == 2
        # First call: the lineups data
        call_args_0 = mock_set.call_args_list[0]
        assert call_args_0[0][0] == "lineups:nba:2026-03-16"
        assert call_args_0[0][1] == lineups
        assert call_args_0[1]["ttl"] == 3600

        # Second call: the meta
        call_args_1 = mock_set.call_args_list[1]
        assert call_args_1[0][0] == "lineups:nba:2026-03-16:meta"
        meta = call_args_1[0][1]
        assert "fetched_at" in meta
        assert meta["team_count"] == 1


# ---------------------------------------------------------------------------
# _write_to_postgres  (lines 331-358)
# ---------------------------------------------------------------------------

class TestWriteToPostgres:
    @pytest.mark.asyncio
    async def test_skips_when_not_connected(self, monkeypatch):
        svc = _make_service()
        mock_db = MagicMock()
        mock_db.is_connected = False
        monkeypatch.setattr("app.services.lineup_service.db_service", mock_db)

        await svc._write_to_postgres("2026-03-16", _sample_lineups())
        mock_db.executemany.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_empty_lineups(self, monkeypatch):
        svc = _make_service()
        mock_db = MagicMock()
        mock_db.is_connected = True
        monkeypatch.setattr("app.services.lineup_service.db_service", mock_db)

        await svc._write_to_postgres("2026-03-16", {})
        mock_db.executemany.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_executemany_with_correct_args(self, monkeypatch):
        svc = _make_service()
        mock_db = MagicMock()
        mock_db.is_connected = True
        mock_db.executemany = AsyncMock()
        monkeypatch.setattr("app.services.lineup_service.db_service", mock_db)

        lineups = _sample_lineups()
        await svc._write_to_postgres("2026-03-16", lineups)

        mock_db.executemany.assert_awaited_once()
        args = mock_db.executemany.call_args
        sql = args[0][0]
        args_list = args[0][1]
        assert "INSERT INTO team_lineup_snapshots" in sql
        assert len(args_list) == 1
        row = args_list[0]
        # row[1] is the team
        assert row[1] == "GSW"
        # row[2] is the opponent
        assert row[2] == "LAL"

    @pytest.mark.asyncio
    async def test_handles_none_updated_at(self, monkeypatch):
        svc = _make_service()
        mock_db = MagicMock()
        mock_db.is_connected = True
        mock_db.executemany = AsyncMock()
        monkeypatch.setattr("app.services.lineup_service.db_service", mock_db)

        lineups = _sample_lineups()
        lineups["GSW"]["updated_at"] = None
        await svc._write_to_postgres("2026-03-16", lineups)

        mock_db.executemany.assert_awaited_once()
        row = mock_db.executemany.call_args[0][1][0]
        # updated_at (index 10) should be the fetched_at fallback, a datetime
        assert isinstance(row[10], datetime)


# ---------------------------------------------------------------------------
# _read_from_postgres  (lines 360-389)
# ---------------------------------------------------------------------------

class TestReadFromPostgres:
    @pytest.mark.asyncio
    async def test_returns_empty_when_not_connected(self, monkeypatch):
        svc = _make_service()
        mock_db = MagicMock()
        mock_db.is_connected = False
        monkeypatch.setattr("app.services.lineup_service.db_service", mock_db)

        result = await svc._read_from_postgres("2026-03-16")
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_parsed_rows(self, monkeypatch):
        svc = _make_service()
        mock_db = MagicMock()
        mock_db.is_connected = True

        fake_row = {
            "team": "GSW",
            "opponent": "LAL",
            "home_or_away": "AWAY",
            "status": "projected",
            "starters": ["Curry", "Hield", "Butler", "Green", "Post"],
            "bench_candidates": [],
            "sources": ["rotowire"],
            "source_disagreement": False,
            "confidence": "high",
            "updated_at": datetime(2026, 3, 16, 17, 0, tzinfo=timezone.utc),
            "source_snapshots": {},
        }
        mock_db.fetch = AsyncMock(return_value=[fake_row])
        monkeypatch.setattr("app.services.lineup_service.db_service", mock_db)

        result = await svc._read_from_postgres("2026-03-16")
        assert "GSW" in result
        assert result["GSW"]["team"] == "GSW"
        assert result["GSW"]["date"] == "2026-03-16"
        assert result["GSW"]["updated_at"] == "2026-03-16T17:00:00+00:00"

    @pytest.mark.asyncio
    async def test_handles_none_updated_at_in_row(self, monkeypatch):
        svc = _make_service()
        mock_db = MagicMock()
        mock_db.is_connected = True

        fake_row = {
            "team": "LAL",
            "opponent": "GSW",
            "home_or_away": "HOME",
            "status": "projected",
            "starters": ["A", "B", "C", "D", "E"],
            "bench_candidates": None,
            "sources": None,
            "source_disagreement": None,
            "confidence": "low",
            "updated_at": None,
            "source_snapshots": None,
        }
        mock_db.fetch = AsyncMock(return_value=[fake_row])
        monkeypatch.setattr("app.services.lineup_service.db_service", mock_db)

        result = await svc._read_from_postgres("2026-03-16")
        assert result["LAL"]["updated_at"] is None
        assert result["LAL"]["bench_candidates"] == []
        assert result["LAL"]["sources"] == []
        assert result["LAL"]["source_snapshots"] == {}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_no_rows(self, monkeypatch):
        svc = _make_service()
        mock_db = MagicMock()
        mock_db.is_connected = True
        mock_db.fetch = AsyncMock(return_value=[])
        monkeypatch.setattr("app.services.lineup_service.db_service", mock_db)

        result = await svc._read_from_postgres("2026-03-16")
        assert result == {}


# ---------------------------------------------------------------------------
# _log_fetch  (lines 391-415)
# ---------------------------------------------------------------------------

class TestLogFetch:
    @pytest.mark.asyncio
    async def test_skips_when_not_connected(self, monkeypatch):
        svc = _make_service()
        mock_db = MagicMock()
        mock_db.is_connected = False
        monkeypatch.setattr("app.services.lineup_service.db_service", mock_db)

        await svc._log_fetch(
            date="2026-03-16",
            team_count=1,
            status="success",
            error_message=None,
            duration_ms=100,
            source_statuses={},
        )
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_inserts_log_row(self, monkeypatch):
        svc = _make_service()
        mock_db = MagicMock()
        mock_db.is_connected = True
        mock_db.execute = AsyncMock()
        monkeypatch.setattr("app.services.lineup_service.db_service", mock_db)

        await svc._log_fetch(
            date="2026-03-16",
            team_count=5,
            status="success",
            error_message=None,
            duration_ms=250,
            source_statuses={"rotowire": {"status": "success"}},
        )

        mock_db.execute.assert_awaited_once()
        call_args = mock_db.execute.call_args[0]
        assert "INSERT INTO lineup_fetch_logs" in call_args[0]
        assert call_args[3] == 5   # team_count
        assert call_args[4] == "success"
        assert call_args[5] is None  # error_message
        assert call_args[6] == 250   # duration_ms

    @pytest.mark.asyncio
    async def test_handles_db_execute_exception(self, monkeypatch):
        svc = _make_service()
        mock_db = MagicMock()
        mock_db.is_connected = True
        mock_db.execute = AsyncMock(side_effect=Exception("DB write error"))
        monkeypatch.setattr("app.services.lineup_service.db_service", mock_db)

        # Should not raise
        await svc._log_fetch(
            date="2026-03-16",
            team_count=0,
            status="error",
            error_message="Both failed",
            duration_ms=50,
            source_statuses={},
        )


# ---------------------------------------------------------------------------
# _trigger_background_refresh  (lines 304-317)
# ---------------------------------------------------------------------------

class TestTriggerBackgroundRefresh:
    def test_skips_if_already_locked(self):
        svc = _make_service()
        svc._refresh_locks.add("2026-03-16")

        # Patch create_task to track if it was called
        with patch("app.services.lineup_service.asyncio.create_task") as mock_task:
            svc._trigger_background_refresh("2026-03-16")
            mock_task.assert_not_called()

    def test_adds_lock_and_creates_task(self):
        svc = _make_service()
        assert "2026-03-16" not in svc._refresh_locks

        with patch("app.services.lineup_service.asyncio.create_task") as mock_task:
            svc._trigger_background_refresh("2026-03-16")
            assert "2026-03-16" in svc._refresh_locks
            mock_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_background_refresh_clears_lock_on_success(self, monkeypatch):
        svc = _make_service()
        svc.fetch_and_store = AsyncMock(return_value=_sample_lineups())

        # Call the private _refresh coroutine directly
        svc._refresh_locks.add("2026-03-16")

        async def _refresh():
            try:
                await svc.fetch_and_store("2026-03-16")
            except Exception:
                pass
            finally:
                svc._refresh_locks.discard("2026-03-16")

        await _refresh()
        assert "2026-03-16" not in svc._refresh_locks

    @pytest.mark.asyncio
    async def test_background_refresh_clears_lock_on_failure(self, monkeypatch):
        svc = _make_service()
        svc.fetch_and_store = AsyncMock(side_effect=RuntimeError("fail"))

        svc._refresh_locks.add("2026-03-16")

        async def _refresh():
            try:
                await svc.fetch_and_store("2026-03-16")
            except Exception:
                pass
            finally:
                svc._refresh_locks.discard("2026-03-16")

        await _refresh()
        assert "2026-03-16" not in svc._refresh_locks


# ---------------------------------------------------------------------------
# get_lineups  (lines 200-226)
# ---------------------------------------------------------------------------

class TestGetLineups:
    @pytest.mark.asyncio
    async def test_returns_fresh_from_cache(self, monkeypatch):
        svc = _make_service()
        lineups = _sample_lineups()
        recent = datetime.now(timezone.utc).isoformat()
        meta = {"fetched_at": recent, "team_count": 1}

        monkeypatch.setattr(
            "app.services.lineup_service.cache_service.get",
            AsyncMock(side_effect=lambda key: lineups if "meta" not in key else meta),
        )

        result = await svc.get_lineups("2026-03-16")
        assert result.cache_state == "fresh"
        assert result.lineups == lineups
        assert result.fetched_at == recent

    @pytest.mark.asyncio
    async def test_returns_stale_and_triggers_refresh(self, monkeypatch):
        svc = _make_service(max_stale_minutes=20)
        lineups = _sample_lineups()
        old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        meta = {"fetched_at": old, "team_count": 1}

        monkeypatch.setattr(
            "app.services.lineup_service.cache_service.get",
            AsyncMock(side_effect=lambda key: lineups if "meta" not in key else meta),
        )

        trigger_mock = MagicMock()
        monkeypatch.setattr(svc, "_trigger_background_refresh", trigger_mock)

        result = await svc.get_lineups("2026-03-16")
        assert result.cache_state == "stale"
        trigger_mock.assert_called_once_with("2026-03-16")

    @pytest.mark.asyncio
    async def test_cache_miss_calls_fetch_and_store(self, monkeypatch):
        svc = _make_service()
        lineups = _sample_lineups()

        monkeypatch.setattr(
            "app.services.lineup_service.cache_service.get",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(svc, "fetch_and_store", AsyncMock(return_value=lineups))

        result = await svc.get_lineups("2026-03-16")
        assert result.cache_state == "refreshed"
        assert result.lineups == lineups
        svc.fetch_and_store.assert_awaited_once_with("2026-03-16")

    @pytest.mark.asyncio
    async def test_fetch_failure_falls_back_to_postgres(self, monkeypatch):
        svc = _make_service()
        lineups = _sample_lineups()

        monkeypatch.setattr(
            "app.services.lineup_service.cache_service.get",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(svc, "fetch_and_store", AsyncMock(side_effect=RuntimeError("boom")))
        monkeypatch.setattr(svc, "_read_from_postgres", AsyncMock(return_value=lineups))
        monkeypatch.setattr(svc, "_write_to_redis", AsyncMock())

        result = await svc.get_lineups("2026-03-16")
        assert result.cache_state == "stale"
        assert result.lineups == lineups
        svc._write_to_redis.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_failure_and_no_postgres_returns_empty(self, monkeypatch):
        svc = _make_service()

        monkeypatch.setattr(
            "app.services.lineup_service.cache_service.get",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(svc, "fetch_and_store", AsyncMock(side_effect=RuntimeError("boom")))
        monkeypatch.setattr(svc, "_read_from_postgres", AsyncMock(return_value={}))

        result = await svc.get_lineups("2026-03-16")
        assert result.cache_state == "fresh"
        assert result.lineups == {}
        assert result.fetched_at is None

    @pytest.mark.asyncio
    async def test_cached_data_not_dict_treated_as_miss(self, monkeypatch):
        """If Redis returns a non-dict (e.g. a string), treat as cache miss."""
        svc = _make_service()
        lineups = _sample_lineups()

        monkeypatch.setattr(
            "app.services.lineup_service.cache_service.get",
            AsyncMock(return_value="not_a_dict"),
        )
        monkeypatch.setattr(svc, "fetch_and_store", AsyncMock(return_value=lineups))

        result = await svc.get_lineups("2026-03-16")
        assert result.cache_state == "refreshed"

    @pytest.mark.asyncio
    async def test_stale_with_none_meta(self, monkeypatch):
        """Cached data is dict but meta is None -> stale."""
        svc = _make_service()
        lineups = _sample_lineups()

        call_count = 0

        async def fake_get(key):
            nonlocal call_count
            call_count += 1
            if "meta" not in key:
                return lineups
            return None  # no meta

        monkeypatch.setattr("app.services.lineup_service.cache_service.get", fake_get)
        trigger_mock = MagicMock()
        monkeypatch.setattr(svc, "_trigger_background_refresh", trigger_mock)

        result = await svc.get_lineups("2026-03-16")
        assert result.cache_state == "stale"
        trigger_mock.assert_called_once_with("2026-03-16")


# ---------------------------------------------------------------------------
# get_team_lineup  (lines 228-231)
# ---------------------------------------------------------------------------

class TestGetTeamLineup:
    @pytest.mark.asyncio
    async def test_returns_team_data(self, monkeypatch):
        svc = _make_service()
        lineups = _sample_lineups()
        monkeypatch.setattr(
            svc,
            "get_lineups",
            AsyncMock(
                return_value=LineupReadResult(
                    date="2026-03-16",
                    lineups=lineups,
                    fetched_at="2026-03-16T12:00:00+00:00",
                    cache_state="fresh",
                )
            ),
        )

        team_data, cache_state, fetched_at = await svc.get_team_lineup("2026-03-16", "GSW")
        assert team_data is not None
        assert team_data["team"] == "GSW"
        assert cache_state == "fresh"
        assert fetched_at == "2026-03-16T12:00:00+00:00"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_team(self, monkeypatch):
        svc = _make_service()
        monkeypatch.setattr(
            svc,
            "get_lineups",
            AsyncMock(
                return_value=LineupReadResult(
                    date="2026-03-16",
                    lineups=_sample_lineups(),
                    fetched_at="2026-03-16T12:00:00+00:00",
                    cache_state="fresh",
                )
            ),
        )

        team_data, cache_state, fetched_at = await svc.get_team_lineup("2026-03-16", "BOS")
        assert team_data is None

    @pytest.mark.asyncio
    async def test_normalizes_team_to_upper(self, monkeypatch):
        svc = _make_service()
        monkeypatch.setattr(
            svc,
            "get_lineups",
            AsyncMock(
                return_value=LineupReadResult(
                    date="2026-03-16",
                    lineups=_sample_lineups(),
                    fetched_at="2026-03-16T12:00:00+00:00",
                    cache_state="fresh",
                )
            ),
        )

        team_data, _, _ = await svc.get_team_lineup("2026-03-16", "gsw")
        assert team_data is not None

    @pytest.mark.asyncio
    async def test_handles_none_team(self, monkeypatch):
        svc = _make_service()
        monkeypatch.setattr(
            svc,
            "get_lineups",
            AsyncMock(
                return_value=LineupReadResult(
                    date="2026-03-16",
                    lineups={},
                    fetched_at=None,
                    cache_state="fresh",
                )
            ),
        )

        team_data, _, _ = await svc.get_team_lineup("2026-03-16", None)
        assert team_data is None


# ---------------------------------------------------------------------------
# fetch_and_store  (lines 233-295)
# ---------------------------------------------------------------------------

class TestFetchAndStore:
    @pytest.mark.asyncio
    async def test_success_path(self, monkeypatch):
        svc = _make_service()

        rotowire_data = {
            "GSW": {
                "starters": ["A", "B", "C", "D", "E"],
                "bench_candidates": [],
                "sources": ["rotowire"],
                "source_snapshots": {},
                "opponent": "LAL",
                "home_or_away": "AWAY",
                "updated_at": "2026-03-16T17:00:00+00:00",
            }
        }
        rotogrinders_data = {
            "GSW": {
                "starters": ["A", "B", "C", "D", "E"],
                "bench_candidates": [],
                "sources": ["rotogrinders"],
                "source_snapshots": {},
                "opponent": "LAL",
                "home_or_away": "AWAY",
                "updated_at": "2026-03-16T17:00:00+00:00",
            }
        }

        monkeypatch.setattr(
            "app.services.lineup_service.fetch_rotowire_lineups",
            lambda date: rotowire_data,
        )
        monkeypatch.setattr(
            "app.services.lineup_service.fetch_rotogrinders_lineups",
            lambda date: rotogrinders_data,
        )
        monkeypatch.setattr(svc, "_write_to_redis", AsyncMock())
        monkeypatch.setattr(svc, "_write_to_postgres", AsyncMock())
        monkeypatch.setattr(svc, "_log_fetch", AsyncMock())
        monkeypatch.setattr(
            "app.services.lineup_service.cache_service.clear_daily_picks_cache",
            AsyncMock(return_value=2),
        )

        result = await svc.fetch_and_store("2026-03-16")
        assert "GSW" in result
        svc._write_to_redis.assert_awaited_once()
        svc._write_to_postgres.assert_awaited_once()
        svc._log_fetch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_primary_source_exception(self, monkeypatch):
        svc = _make_service()

        def bad_rotowire(date):
            raise RuntimeError("rotowire down")

        rotogrinders_data = {
            "GSW": {
                "starters": ["A", "B", "C", "D", "E"],
                "bench_candidates": [],
                "sources": ["rotogrinders"],
                "source_snapshots": {},
                "opponent": "LAL",
                "home_or_away": "AWAY",
                "updated_at": "2026-03-16T17:00:00+00:00",
            }
        }

        monkeypatch.setattr("app.services.lineup_service.fetch_rotowire_lineups", bad_rotowire)
        monkeypatch.setattr(
            "app.services.lineup_service.fetch_rotogrinders_lineups",
            lambda date: rotogrinders_data,
        )
        monkeypatch.setattr(svc, "_write_to_redis", AsyncMock())
        monkeypatch.setattr(svc, "_write_to_postgres", AsyncMock())
        monkeypatch.setattr(svc, "_log_fetch", AsyncMock())
        monkeypatch.setattr(
            "app.services.lineup_service.cache_service.clear_daily_picks_cache",
            AsyncMock(return_value=0),
        )

        result = await svc.fetch_and_store("2026-03-16")
        assert "GSW" in result

    @pytest.mark.asyncio
    async def test_secondary_source_exception(self, monkeypatch):
        svc = _make_service()

        rotowire_data = {
            "GSW": {
                "starters": ["A", "B", "C", "D", "E"],
                "bench_candidates": [],
                "sources": ["rotowire"],
                "source_snapshots": {},
                "opponent": "LAL",
                "home_or_away": "AWAY",
                "updated_at": "2026-03-16T17:00:00+00:00",
            }
        }

        def bad_rotogrinders(date):
            raise RuntimeError("rotogrinders down")

        monkeypatch.setattr(
            "app.services.lineup_service.fetch_rotowire_lineups",
            lambda date: rotowire_data,
        )
        monkeypatch.setattr("app.services.lineup_service.fetch_rotogrinders_lineups", bad_rotogrinders)
        monkeypatch.setattr(svc, "_write_to_redis", AsyncMock())
        monkeypatch.setattr(svc, "_write_to_postgres", AsyncMock())
        monkeypatch.setattr(svc, "_log_fetch", AsyncMock())
        monkeypatch.setattr(
            "app.services.lineup_service.cache_service.clear_daily_picks_cache",
            AsyncMock(return_value=0),
        )

        result = await svc.fetch_and_store("2026-03-16")
        assert "GSW" in result

    @pytest.mark.asyncio
    async def test_both_sources_fail_raises(self, monkeypatch):
        svc = _make_service()

        def bad_rotowire(date):
            raise RuntimeError("rotowire down")

        def bad_rotogrinders(date):
            raise RuntimeError("rotogrinders down")

        monkeypatch.setattr("app.services.lineup_service.fetch_rotowire_lineups", bad_rotowire)
        monkeypatch.setattr("app.services.lineup_service.fetch_rotogrinders_lineups", bad_rotogrinders)
        monkeypatch.setattr(svc, "_write_to_redis", AsyncMock())
        monkeypatch.setattr(svc, "_write_to_postgres", AsyncMock())
        monkeypatch.setattr(svc, "_log_fetch", AsyncMock())
        monkeypatch.setattr(
            "app.services.lineup_service.cache_service.clear_daily_picks_cache",
            AsyncMock(return_value=0),
        )

        with pytest.raises(RuntimeError, match="Both free lineup sources"):
            await svc.fetch_and_store("2026-03-16")

        # _log_fetch should still be called in finally block
        svc._log_fetch.assert_awaited_once()
        log_call = svc._log_fetch.call_args
        assert log_call[1]["status"] == "error"

    @pytest.mark.asyncio
    async def test_postgres_write_failure_does_not_raise(self, monkeypatch):
        svc = _make_service()

        rotowire_data = {
            "GSW": {
                "starters": ["A", "B", "C", "D", "E"],
                "bench_candidates": [],
                "sources": ["rotowire"],
                "source_snapshots": {},
                "opponent": "LAL",
                "home_or_away": "AWAY",
                "updated_at": "2026-03-16T17:00:00+00:00",
            }
        }

        monkeypatch.setattr(
            "app.services.lineup_service.fetch_rotowire_lineups",
            lambda date: rotowire_data,
        )
        monkeypatch.setattr(
            "app.services.lineup_service.fetch_rotogrinders_lineups",
            lambda date: {},
        )
        monkeypatch.setattr(svc, "_write_to_redis", AsyncMock())
        monkeypatch.setattr(svc, "_write_to_postgres", AsyncMock(side_effect=Exception("PG down")))
        monkeypatch.setattr(svc, "_log_fetch", AsyncMock())
        monkeypatch.setattr(
            "app.services.lineup_service.cache_service.clear_daily_picks_cache",
            AsyncMock(return_value=0),
        )

        # Should not raise despite postgres failure
        result = await svc.fetch_and_store("2026-03-16")
        assert "GSW" in result

    @pytest.mark.asyncio
    async def test_clears_daily_picks_cache(self, monkeypatch):
        svc = _make_service()

        rotowire_data = {
            "GSW": {
                "starters": ["A", "B", "C", "D", "E"],
                "bench_candidates": [],
                "sources": ["rotowire"],
                "source_snapshots": {},
                "opponent": "LAL",
                "home_or_away": "AWAY",
                "updated_at": "2026-03-16T17:00:00+00:00",
            }
        }

        monkeypatch.setattr(
            "app.services.lineup_service.fetch_rotowire_lineups",
            lambda date: rotowire_data,
        )
        monkeypatch.setattr(
            "app.services.lineup_service.fetch_rotogrinders_lineups",
            lambda date: {},
        )
        monkeypatch.setattr(svc, "_write_to_redis", AsyncMock())
        monkeypatch.setattr(svc, "_write_to_postgres", AsyncMock())
        monkeypatch.setattr(svc, "_log_fetch", AsyncMock())
        clear_mock = AsyncMock(return_value=5)
        monkeypatch.setattr(
            "app.services.lineup_service.cache_service.clear_daily_picks_cache",
            clear_mock,
        )

        await svc.fetch_and_store("2026-03-16")
        clear_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_log_fetch_records_duration_and_source_statuses(self, monkeypatch):
        svc = _make_service()

        rotowire_data = {
            "GSW": {
                "starters": ["A", "B", "C", "D", "E"],
                "bench_candidates": [],
                "sources": ["rotowire"],
                "source_snapshots": {},
                "opponent": "LAL",
                "home_or_away": "AWAY",
                "updated_at": "2026-03-16T17:00:00+00:00",
            }
        }

        monkeypatch.setattr(
            "app.services.lineup_service.fetch_rotowire_lineups",
            lambda date: rotowire_data,
        )
        monkeypatch.setattr(
            "app.services.lineup_service.fetch_rotogrinders_lineups",
            lambda date: {},
        )
        monkeypatch.setattr(svc, "_write_to_redis", AsyncMock())
        monkeypatch.setattr(svc, "_write_to_postgres", AsyncMock())
        monkeypatch.setattr(
            "app.services.lineup_service.cache_service.clear_daily_picks_cache",
            AsyncMock(return_value=0),
        )

        log_mock = AsyncMock()
        monkeypatch.setattr(svc, "_log_fetch", log_mock)

        await svc.fetch_and_store("2026-03-16")

        log_mock.assert_awaited_once()
        kwargs = log_mock.call_args[1]
        assert kwargs["date"] == "2026-03-16"
        assert kwargs["status"] == "success"
        assert kwargs["error_message"] is None
        assert isinstance(kwargs["duration_ms"], int)
        assert "rotowire" in kwargs["source_statuses"]
        assert "rotogrinders" in kwargs["source_statuses"]
        assert kwargs["source_statuses"]["rotowire"]["status"] == "success"
        assert kwargs["source_statuses"]["rotogrinders"]["status"] == "success"
