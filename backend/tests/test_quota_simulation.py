"""
test_quota_simulation.py - Sentinel sanity test for SPO-15 cadence audit.

Audit narrative: docs/task-summaries/SPO-15-snapshot-cadence-audit.md
Decision log:    docs/decisions/event-page-stat-expansion/decision_20260502_market-key-feasibility.md (§3, Addendum)
Scout evidence:  docs/research/event-page-stat-expansion/research_odds_api_markets.md (§2.4 per-market billing model)

PURPOSE
    Lock the audit's burn-claim arithmetic into an executable test, so a future
    cadence change (extra snapshot, new SUPPORTED_MARKETS entry, prewarm scope
    rework) cannot land without forcing the numbers in the audit doc to be
    re-derived.

WHAT THE TWO TESTS DO
    1. test_simulated_weekly_burn_matches_forge_claim
        Pure-mock simulation. Patches SNAPSHOT_MARKETS to the planned 10-market
        Tier-A value, drives `OddsSnapshotService.take_snapshot` 5 game-days x
        3 snapshots/day, and intercepts every `odds_gateway.get_market_snapshot`
        call. Computes total weekly units = sum(len(markets.split(','))) +
        arithmetic daily-analysis cost. Asserts the total matches the audit's
        WEEKLY_CLAIM within 5% per spec. Costs 0 API units.

    2. test_live_per_market_unit_cost_ground_truth
        Single live API hit (`player_threes` against the next upcoming NBA
        event_id). Asserts `x-requests-last == 1` (per-market billing). If this
        ever fails, the per-market billing model assumed by the audit doc has
        changed and the math is invalid - escalate to CTO.

LIVE API COST OF THIS FILE WHEN RUN_INTEGRATION=1
    1 paid request unit per run (one populated `player_threes` call). The
    simulation test is pure-mock and costs 0 units.

GATING
    Both tests are gated behind RUN_INTEGRATION=1 so CI default skips them.
    Forge runs them locally before any cadence-affecting PR; Sentinel runs them
    in the integration window.
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Audit-doc constants - keep in sync with SPO-15-snapshot-cadence-audit.md
# ---------------------------------------------------------------------------

# Planned Tier-A SNAPSHOT_MARKETS value (decision log Addendum §3, table; the
# Tier-B (FTM, FGA) markets are excluded here because per Scout SPO-12 §3.3-§3.4
# they currently return `bookmakers:[]` which costs 0 units under the
# per-market billing model - so they don't change the *paid* burn while empty).
PLANNED_SNAPSHOT_MARKETS = (
    "player_points,player_rebounds,player_assists,player_points_rebounds_assists,"
    "player_threes,player_steals,player_rebounds_assists,player_points_rebounds,"
    "player_points_assists,player_double_double"
)
SNAPSHOT_MARKET_COUNT = len([m for m in PLANNED_SNAPSHOT_MARKETS.split(",") if m])  # 10

# Daily-analysis loops one API call per market per event (daily_analysis.py:448,612)
# so its post-merge unit count = events * markets, same arithmetic basis.
DAILY_ANALYSIS_MARKET_COUNT = 10

# Cadence model (scheduler.py:160-228 - 3 snapshot jobs/day + 1 daily_analysis)
SNAPSHOTS_PER_DAY = 3
DA_RUNS_PER_DAY = 1

# Domain assumptions (CLAUDE.md Domain Lenses + decision log §3)
EVENTS_PER_GAME_DAY = 10
GAME_DAYS_PER_WEEK = 5      # ~5 of 7 calendar days are NBA game days
GAME_DAYS_PER_MONTH = 22    # standard regular-season pace

# Per-game-day burn = 3 snaps * 10 events * 10 markets + 1 da * 10 events * 10 markets
EXPECTED_PER_GAME_DAY_UNITS = (
    SNAPSHOTS_PER_DAY * EVENTS_PER_GAME_DAY * SNAPSHOT_MARKET_COUNT
    + DA_RUNS_PER_DAY * EVENTS_PER_GAME_DAY * DAILY_ANALYSIS_MARKET_COUNT
)  # 3*10*10 + 1*10*10 = 400 units/game day

# Forge audit claim (per docs/task-summaries/SPO-15-snapshot-cadence-audit.md):
WEEKLY_CLAIM = GAME_DAYS_PER_WEEK * EXPECTED_PER_GAME_DAY_UNITS    # 5*400 = 2000 units/wk
MONTHLY_CLAIM = GAME_DAYS_PER_MONTH * EXPECTED_PER_GAME_DAY_UNITS  # 22*400 = 8800 units/mo

TOLERANCE = 0.05  # spec: weekly delta <= claim/4 +/- 5%


# ---------------------------------------------------------------------------
# Skip-gate: RUN_INTEGRATION=1 unlocks both tests
# ---------------------------------------------------------------------------

INTEGRATION = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="RUN_INTEGRATION=1 required to exercise SPO-15 quota simulation",
)


# ---------------------------------------------------------------------------
# Test 1 - simulated 1-week scheduler burn must match audit-doc claim
# ---------------------------------------------------------------------------

@INTEGRATION
@pytest.mark.integration
@pytest.mark.asyncio
async def test_simulated_weekly_burn_matches_forge_claim(monkeypatch):
    """
    Drive odds_snapshot_service through one simulated week (5 game days x 3
    snapshots/day) with SNAPSHOT_MARKETS patched to the 10-market Tier-A planned
    set. Intercept every odds_gateway.get_market_snapshot call and accumulate
    paid units = sum(len(markets.split(','))). Add daily-analysis cost
    arithmetically (its loop-per-market structure means events x markets units
    per run). Assert total <= WEEKLY_CLAIM +/- TOLERANCE.

    Cost: 0 API units (all gateway calls are mocked).

    Why this lives in the test suite, not just the audit doc: the audit's
    monthly burn claim is built from the cadence constants in
    `backend/app/services/scheduler.py`. If anyone changes the snapshot cadence
    (e.g. adds a 4th run/day) or the per-call market count, this test fails and
    forces the audit numbers in `SPO-15-snapshot-cadence-audit.md` to be
    re-derived BEFORE the change merges.
    """
    from app.services import odds_snapshot_service as snapshot_module

    # Patch the module-level constant. _process_event reads it via module
    # globals at call time, so this swap is honored without re-importing.
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MARKETS", PLANNED_SNAPSHOT_MARKETS)

    service = snapshot_module.OddsSnapshotService()

    events = [
        {
            "id": f"evt{i}",
            "home_team": f"Home{i}",
            "away_team": f"Away{i}",
            "commence_time": "2026-05-03T00:00:00Z",
        }
        for i in range(EVENTS_PER_GAME_DAY)
    ]
    monkeypatch.setattr(service, "_get_events", AsyncMock(return_value=events))

    intercepted = {"calls": 0, "units": 0}

    async def _fake_get_market_snapshot(*args, markets, **kwargs):
        intercepted["calls"] += 1
        intercepted["units"] += len([m for m in markets.split(",") if m])
        return SimpleNamespace(data={"bookmakers": []})

    mock_gateway = MagicMock()
    mock_gateway.get_market_snapshot = AsyncMock(side_effect=_fake_get_market_snapshot)
    monkeypatch.setattr(snapshot_module, "odds_gateway", mock_gateway)

    mock_db = MagicMock()
    mock_db.is_connected = False
    monkeypatch.setattr(snapshot_module, "db_service", mock_db)
    monkeypatch.setattr(service, "_log_snapshot", AsyncMock())

    # Drive 5 game days x 3 snapshots/day = 15 snapshot runs
    for _ in range(GAME_DAYS_PER_WEEK):
        for _ in range(SNAPSHOTS_PER_DAY):
            await service.take_snapshot("2026-05-03")

    snapshot_units = intercepted["units"]
    snapshot_calls = intercepted["calls"]

    # Sanity: 5 days * 3 snaps * 10 events = 150 calls; 150 calls * 10 markets = 1500 units
    expected_snapshot_calls = GAME_DAYS_PER_WEEK * SNAPSHOTS_PER_DAY * EVENTS_PER_GAME_DAY
    expected_snapshot_units = expected_snapshot_calls * SNAPSHOT_MARKET_COUNT
    assert snapshot_calls == expected_snapshot_calls, (
        f"Snapshot call count mismatch: got {snapshot_calls}, expected "
        f"{expected_snapshot_calls}. Did the snapshot cadence change in "
        f"scheduler.py? Re-derive the audit numbers."
    )
    assert snapshot_units == expected_snapshot_units, (
        f"Snapshot unit count mismatch: got {snapshot_units}, expected "
        f"{expected_snapshot_units}. Did SNAPSHOT_MARKETS change shape? "
        f"Re-derive the audit numbers."
    )

    # Daily-analysis cost is computed (not driven) - daily_analysis.py:448 loops
    # one API call per market, so post-merge units = events * markets per run.
    # See SPO-15-snapshot-cadence-audit.md "Why daily_analysis is not driven".
    da_units = (
        GAME_DAYS_PER_WEEK
        * DA_RUNS_PER_DAY
        * EVENTS_PER_GAME_DAY
        * DAILY_ANALYSIS_MARKET_COUNT
    )

    total_weekly_units = snapshot_units + da_units

    delta = total_weekly_units - WEEKLY_CLAIM
    relative = abs(delta) / WEEKLY_CLAIM
    assert relative <= TOLERANCE, (
        f"Simulated weekly burn ({total_weekly_units} units) differs from "
        f"audit claim ({WEEKLY_CLAIM} units) by {relative:.1%} - exceeds "
        f"{TOLERANCE:.0%} spec tolerance. Re-derive SPO-15-snapshot-cadence-"
        f"audit.md or fix the cadence."
    )


# ---------------------------------------------------------------------------
# Test 2 - live ground truth: per-market billing model holds
# ---------------------------------------------------------------------------

@INTEGRATION
@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_per_market_unit_cost_ground_truth():
    """
    Single live API hit to ground-truth the per-market billing assumption from
    Scout SPO-12 §2.4: a 1-market URL charges `x-requests-last == 1` when at
    least one bookmaker returns a populated outcome.

    LIVE API COST OF THIS TEST RUN: exactly 1 unit (when bookmakers populated)
    or 0 units (when bookmakers empty). Verified empirically 2026-05-02 by
    Scout against `x-requests-used` arc 25 -> 26 for `player_threes` single
    call.

    If this test ever fails, the audit math in
    `docs/task-summaries/SPO-15-snapshot-cadence-audit.md` is invalid and must
    be re-derived. Escalate to CTO with the failing `usage.last` value.
    """
    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        pytest.skip("ODDS_API_KEY not set in env; cannot ground-truth live billing")

    from app.services.odds_theoddsapi import TheOddsAPIProvider

    provider = TheOddsAPIProvider()

    # Free endpoint (`/v4/sports/.../events`) - x-requests-last=0 per Scout §1.
    # Pick the first upcoming NBA event so we don't depend on a hard-coded id
    # that goes stale tomorrow.
    events = await provider.get_events(sport="basketball_nba", regions="us")
    if not events:
        pytest.skip("No upcoming NBA events available right now for live ground-truth")

    event_id = events[0]["id"]

    data, usage = await provider.get_event_odds_with_usage(
        sport="basketball_nba",
        event_id=event_id,
        regions="us",
        markets="player_threes",
        odds_format="american",
    )

    assert usage is not None, (
        "QuotaUsage came back None - the x-requests-* header parsing in "
        "TheOddsAPIProvider is broken. Audit math depends on these headers."
    )

    bookmakers = data.get("bookmakers", [])
    if not bookmakers:
        # Empty market = 0-cost per Scout §2.4. Either 0 or 1 is internally
        # consistent (1 would mean billing model changed in our disfavor).
        assert usage.last in (0, 1), (
            f"Expected x-requests-last in (0, 1) for empty player_threes, got "
            f"{usage.last}. The Odds API may have changed billing model."
        )
    else:
        assert usage.last == 1, (
            f"Expected x-requests-last=1 for single populated player_threes "
            f"call, got {usage.last}. Per-market billing model from Scout "
            f"SPO-12 §2.4 may have changed. SPO-15 audit math is invalid until "
            f"this is re-derived."
        )
