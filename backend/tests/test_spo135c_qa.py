"""QA checks for SPO-135c: request path, retry cap, window edges, name keys."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from app.services.bdl_client import BdlClient
from app.services.nba_injuries import (
    NBA_INJURIES_CACHE_KEY,
    load_nba_pick_injuries,
    match_injury_entry,
)
from app.services.pick_signals import (
    adjustment_total,
    build_nba_signals,
    combined_probability,
    injury_blocks_combined,
    projection_adjustment,
)
from app.services.scheduler import nba_injury_refresh_in_window
from app.settings import Settings
from tests.test_spo135c_bdl_injury_status import (
    _CHICAGO,
    _Clock,
    _entry,
    _picks_for,
)

_NY = ZoneInfo("America/New_York")


def test_leftover_nba_injury_source_env_is_ignored(monkeypatch) -> None:
    monkeypatch.setenv("NBA_INJURY_SOURCE", "espn_cbs")
    loaded = Settings()
    assert not hasattr(loaded, "nba_injury_source")


def test_picks_reads_and_nba_agent_tools_do_not_construct_bdl_client(
    monkeypatch, caplog
) -> None:
    """Request paths only read Redis. A BDL constructor must not run."""

    class _Boom:
        def __init__(self, *args, **kwargs):
            raise AssertionError("BDL client constructed on the request path")

    monkeypatch.setattr("app.services.bdl_client.BdlClient", _Boom)
    caplog.set_level(logging.WARNING)
    out = _entry("Out")
    picks = _picks_for([out["player"], "Dyson Daniels"], [out])
    assert {row.injury_status for row in picks if row.player_name == out["player"]} == {
        "Out"
    }

    class _Cache:
        async def get(self, key):
            assert key == NBA_INJURIES_CACHE_KEY
            return {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "entries": [out],
            }

    loaded = asyncio.run(load_nba_pick_injuries(cache=_Cache()))
    assert loaded is not None
    assert loaded[0]["status"] == "Out"

    signals, combined, _total = build_nba_signals(
        side="over",
        line=24.5,
        player_name=out["player"],
        market_probability=0.58,
        injury_status=None,
    )
    # The helper blends when the caller passes no injury word. /reads
    # now passes the cache word; a missing snapshot is what leaves it None.
    assert combined is not None
    assert 0.0 < combined < 1.0
    assert [signal.key for signal in signals] == [
        "market",
        "last10",
        "history",
        "defense",
    ]

    from tests.test_spo131_qa import _agent_path, _seed

    body = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "entries": [out],
    }
    historical = _agent_path(monkeypatch, _seed(body))
    report = asyncio.run(
        historical.get_official_injury_report(out["team"], league="nba")
    )
    assert report["details"]["injuries"]


def test_suffix_is_kept_so_a_unique_jr_row_does_not_attach_to_the_stem() -> None:
    """A unique 'Gary Trent Jr.' row does not attach to 'Gary Trent'.

    The applied QA check recorded the old player_name_key fallback,
    which dropped Jr/III and then matched the stem. That fallback is
    gone. Two different full names are not ambiguous. The id still
    wins when the caller has one. Picks do not pass a bdl_player_id.
    """
    junior = {
        "player": "Gary Trent Jr.",
        "status": "Out",
        "raw_status": "Out",
        "bdl_player_id": 999,
    }
    senior = {
        "player": "Gary Trent",
        "status": "Questionable",
        "raw_status": "Questionable",
        "bdl_player_id": 1,
    }
    assert match_injury_entry([junior], "Gary Trent Jr.") is junior
    assert match_injury_entry([junior], "Gary Trent") is None
    assert match_injury_entry([junior, senior], "Gary Trent Jr.") is junior
    assert match_injury_entry([junior, senior], "Gary Trent") is senior
    assert match_injury_entry([junior], "Gary Trent Jr.", 999) is junior
    assert match_injury_entry([junior, senior], "other", 999) is junior


def test_injury_retry_after_http_date_and_garbage_are_capped() -> None:
    clock = _Clock()
    client = BdlClient(
        api_key="unit-test-bdl-key",
        transport=httpx.MockTransport(lambda _req: httpx.Response(200)),
        redis=MagicMock(),
        sleep=clock.sleep,
        clock=clock.time,
        rate_limit_policy="injury",
    )
    far = format_datetime(
        datetime.fromtimestamp(clock.now, tz=timezone.utc) + timedelta(hours=24)
    )
    long_wait = client._injury_backoff_seconds(
        httpx.Response(429, headers={"Retry-After": far})
    )
    assert long_wait == 60
    garbage = client._injury_backoff_seconds(
        httpx.Response(429, headers={"Retry-After": "not-a-delay"})
    )
    assert 30 <= garbage <= 59


def test_window_covers_dst_and_a_late_west_coast_tip() -> None:
    winter_open = datetime(2026, 1, 15, 11, 0, tzinfo=_CHICAGO)
    winter_last = datetime(2026, 1, 16, 0, 59, tzinfo=_CHICAGO)
    winter_closed = datetime(2026, 1, 16, 1, 0, tzinfo=_CHICAGO)
    # 10:30 PM PT in January is 00:30 CT, still inside the hour-0 slot.
    late_tip = datetime(2026, 1, 16, 0, 30, tzinfo=_CHICAGO)
    summer_open = datetime(2026, 6, 15, 11, 0, tzinfo=_CHICAGO)
    ny_last = datetime(2026, 6, 16, 1, 59, tzinfo=_NY)
    ny_closed = datetime(2026, 6, 16, 2, 0, tzinfo=_NY)
    before_open = datetime(2026, 1, 15, 10, 59, tzinfo=_CHICAGO)
    assert nba_injury_refresh_in_window(winter_open) is True
    assert nba_injury_refresh_in_window(winter_last) is True
    assert nba_injury_refresh_in_window(winter_closed) is False
    assert nba_injury_refresh_in_window(late_tip) is True
    assert nba_injury_refresh_in_window(summer_open) is True
    assert nba_injury_refresh_in_window(ny_last) is True
    assert nba_injury_refresh_in_window(ny_closed) is False
    assert nba_injury_refresh_in_window(before_open) is False


def test_stale_previous_snapshot_after_a_failed_refresh_stays_null() -> None:
    out = _entry("Out")
    stale_at = (
        datetime.now(timezone.utc) - timedelta(hours=6, seconds=1)
    ).isoformat()

    class _Cache:
        async def get(self, key):
            return {"fetched_at": stale_at, "entries": [out]}

    loaded = asyncio.run(load_nba_pick_injuries(cache=_Cache()))
    assert loaded is None


def test_corrupt_snapshot_warns_once_and_is_not_healthy(caplog) -> None:
    out = _entry("Out")

    class _Bad:
        async def get(self, key):
            return {"fetched_at": datetime.now(timezone.utc).isoformat(), "entries": "nope"}

    caplog.set_level(logging.WARNING)
    loaded = asyncio.run(load_nba_pick_injuries(cache=_Bad()))
    assert loaded is None
    warnings = [r for r in caplog.records if "malformed" in r.getMessage()]
    assert len(warnings) == 1
    picks = _picks_for([out["player"]], None)
    assert {pick.injury_status for pick in picks} == {None}
    assert all(pick.combined_probability is not None for pick in picks)


def test_omitting_the_projection_slot_does_not_change_combined_probability() -> None:
    signals, missing_p, missing_adj = build_nba_signals(
        side="over",
        line=24.5,
        player_name="Test Player",
        market_probability=0.58,
        last10_values=[30, 30, 30, 30, 30, 30, 10, 10, 10, 10],
        history_rate=0.62,
        opponent_rank=8,
        projected_value=None,
    )
    assert [signal.key for signal in signals] == [
        "market",
        "last10",
        "history",
        "defense",
    ]
    assert "projection" not in [signal.key for signal in signals]
    expected = adjustment_total(
        last10_hits=6,
        history_rate=0.62,
        defense_rank_value=8,
        edge_for_side=None,
        side="over",
    )
    assert missing_adj == pytest.approx(expected)
    assert projection_adjustment(None) == 0.0
    assert missing_p == combined_probability(
        side="over", market_probability=0.58, adjustment=expected
    )
    assert missing_p is not None
    assert 0.0 < missing_p < 1.0
    # Doubtful does not block. Questionable does not block.
    assert injury_blocks_combined("Doubtful") is False
    assert injury_blocks_combined("Questionable") is False


def test_signal_helper_blends_when_no_injury_word_is_passed() -> None:
    """build_nba_signals blends when the caller passes no injury word.

    /reads used to do that. It now passes the cache status. A missing
    snapshot is what still leaves the word unset. Out still blocks.
    Doubtful does not.
    """
    _signals, combined, _total = build_nba_signals(
        side="over",
        line=24.5,
        player_name="Jimmy Butler",
        market_probability=0.6,
        injury_status=None,
    )
    assert injury_blocks_combined("Out") is True
    assert injury_blocks_combined("Doubtful") is False
    assert combined is not None
    assert 0.0 < combined < 1.0
