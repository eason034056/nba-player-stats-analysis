"""SPO-135e: NBA event reads block on the cached injury snapshot.

The request path reads Redis key ``injuries:nba:latest`` and does not
construct a BALLDONTLIE client. A posted name is matched with
``match_injury_entry``, the same helper daily picks use. Snapshot rows
and Odds API descriptions have no ``bdl_player_id``, so the id argument
stays unset. One description in the recorded player_points capture is
relabeled to the recorded Out row's name. Only ``player_name`` changes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pytest

from app.services.nba_injuries import NBA_INJURIES_CACHE_KEY
from tests.test_spo121_bulk_reads import _FakeCache, _FakeDB, _points_rows
from tests.test_spo135c_bdl_injury_status import _entry


class _Csv:
    """Same stats for every name, so the blend does not depend on the log."""

    def get_player_stats(self, **_kwargs):
        return {
            "p_over": 0.72,
            "p_under": 0.21,
            "n_games": 20,
            "game_logs": [{"team": "Hawks", "value": 18} for _ in range(12)],
        }

    def latest_team(self, _name: str) -> str:
        return "Atlanta Hawks"

    def latest_position(self, _name: str) -> str:
        return "G"


def _relabel(rows: list[dict], source: str, target: str) -> list[dict]:
    """Copy recorded rows. Only ``player_name`` changes, and only for ``source``."""
    relabeled = []
    for row in rows:
        copied = dict(row)
        if copied.get("player_name") == source:
            copied["player_name"] = target
        relabeled.append(copied)
    return relabeled


def _rows_for(out_name: str) -> tuple[str, list[dict], str]:
    event_id, rows = _points_rows()
    posted = sorted({row["player_name"] for row in rows})
    assert "Dyson Daniels" in posted
    source = next(name for name in posted if name != "Dyson Daniels")
    return event_id, _relabel(rows, source, out_name), "Dyson Daniels"


def _install(monkeypatch, rows, *, injury_body):
    cache = _FakeCache()
    if injury_body is not None:
        cache.store[NBA_INJURIES_CACHE_KEY] = injury_body
    monkeypatch.setattr("app.services.event_reads.cache_service", cache)
    monkeypatch.setattr("app.services.cache.cache_service", cache)
    monkeypatch.setattr("app.services.event_reads.db_service", _FakeDB(rows))
    return cache


def _fresh(entries: list[dict]) -> dict:
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }


def _by_player(payload, name: str):
    rows = [item for item in payload.reads if item.player == name]
    assert rows
    return rows


def test_reads_block_an_out_player_from_the_cached_snapshot(monkeypatch) -> None:
    """Out nulls combined_probability. A healthy posted name keeps a number.

    The BALLDONTLIE client must not be constructed. WNBA is a different
    route and does not call this loader.
    """

    class _Boom:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("BDL client constructed on the request path")

    monkeypatch.setattr("app.services.bdl_client.BdlClient", _Boom)
    out = _entry("Out")
    event_id, rows, healthy = _rows_for(out["player"])
    _install(monkeypatch, rows, injury_body=_fresh([out]))

    from app.services.event_reads import get_event_reads

    payload = asyncio.run(
        get_event_reads(event_id, market="player_points", csv_service=_Csv())
    )
    blocked = _by_player(payload, out["player"])
    open_rows = _by_player(payload, healthy)
    assert {item.combined_probability for item in blocked} == {None}
    assert all(item.signals is not None for item in blocked)
    assert all(item.combined_probability is not None for item in open_rows)
    assert all(0.0 < item.combined_probability < 1.0 for item in open_rows)


def test_missing_snapshot_warns_once_and_reads_keep_a_blend(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    out = _entry("Out")
    event_id, rows, _healthy = _rows_for(out["player"])
    _install(monkeypatch, rows, injury_body=None)

    from app.services.event_reads import get_event_reads

    with caplog.at_level(logging.WARNING):
        payload = asyncio.run(
            get_event_reads(event_id, market="player_points", csv_service=_Csv())
        )
    warnings = [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING and "missing" in record.getMessage()
    ]
    assert len(warnings) == 1
    assert "http" not in warnings[0].getMessage().lower()
    assert all(
        item.combined_probability is not None
        for item in _by_player(payload, out["player"])
    )


def test_stale_snapshot_warns_once_and_reads_keep_a_blend(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    out = _entry("Out")
    event_id, rows, _healthy = _rows_for(out["player"])
    stale_at = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    _install(
        monkeypatch,
        rows,
        injury_body={"fetched_at": stale_at, "entries": [out]},
    )

    from app.services.event_reads import get_event_reads

    with caplog.at_level(logging.WARNING):
        payload = asyncio.run(
            get_event_reads(event_id, market="player_points", csv_service=_Csv())
        )
    warnings = [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING and "stale" in record.getMessage()
    ]
    assert len(warnings) == 1
    assert all(
        item.combined_probability is not None
        for item in _by_player(payload, out["player"])
    )
