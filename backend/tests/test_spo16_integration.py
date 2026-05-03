"""
SPO-16 live integration tests against The Odds API.

Gated behind RUN_INTEGRATION=1 (per `CLAUDE.md § External API Wrappers` rule
#2 and pytest.ini's `integration` marker). Default behavior: pytest skips
these unless the env var is set, so day-to-day unit-test runs do NOT burn
quota.

Two tests in this file:

1. `test_player_threes_returns_populated_payload` — Tier-A live hit on
   `player_threes` (3PM). This is the SPO-16 §5 anti-hallucination guard:
   "at least ONE @pytest.mark.integration test against the live Odds API for
   at least ONE Tier-A market new in this ticket". Cost: 1 quota unit per
   run (per-market billing, see decision §3).

2. `test_player_field_goals_disambiguation_fgm_signature` — SPO-16 §4: probe
   `player_field_goals` once on a populated event and assert the median
   `point` value is < 10 (FGM signature; FGA would cluster 10-20). On
   `bookmakers: []` it skips with a "no inventory yet" note rather than
   asserting blindly. Cost: 1 quota unit (or 0 if empty).

Both tests use `urllib` directly (matching `scripts/explore_odds_api_extensions.py`)
so we don't tangle the test harness with the production `OddsGateway` (which
applies caching/rate-limiting we'd have to mock around).

⚠ DO NOT run these in CI without explicit opt-in. The Odds API quota is paid
and finite. Eason invokes them locally before merge.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest


# Skip the entire module unless RUN_INTEGRATION=1 is set.
if os.environ.get("RUN_INTEGRATION") != "1":
    pytest.skip(
        "RUN_INTEGRATION=1 not set; skipping live The Odds API tests "
        "(see CLAUDE.md § External API Wrappers rule #2)",
        allow_module_level=True,
    )


# Reuse the same env-loading + endpoint-shape conventions as
# scripts/explore_odds_api_extensions.py — keeps this test grounded in the
# Scout-validated probe pattern.
def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_load_env_file(_REPO_ROOT / ".env")
_load_env_file(_REPO_ROOT / "backend" / ".env")

API_KEY = os.environ.get("ODDS_API_KEY")
BASE_URL = os.environ.get(
    "ODDS_API_BASE_URL", "https://api.the-odds-api.com"
)
SPORT = "basketball_nba"


def _http_get_json(path: str, params: dict[str, str]) -> tuple[int, dict[str, Any]]:
    qp = dict(params)
    qp["apiKey"] = API_KEY or ""
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(qp)}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body.decode("utf-8", errors="replace")}


def _pick_event_id() -> str | None:
    """Grab a live NBA event_id (this endpoint is FREE — 0 units charged)."""
    status, data = _http_get_json(f"/v4/sports/{SPORT}/events", {})
    if status != 200 or not isinstance(data, list) or not data:
        return None
    return data[0].get("id")


@pytest.fixture(scope="module")
def event_id() -> str:
    if not API_KEY:
        pytest.fail(
            "ODDS_API_KEY not set — populate .env at repo root before "
            "running RUN_INTEGRATION=1 tests"
        )
    eid = _pick_event_id()
    if not eid:
        pytest.skip("No live NBA events available right now")
    return eid


@pytest.mark.integration
def test_player_threes_returns_populated_payload(event_id: str) -> None:
    """Anti-hallucination guard #5.2: confirm `player_threes` still exists
    and returns the expected Over/Under outcome shape on a live event."""
    status, data = _http_get_json(
        f"/v4/sports/{SPORT}/events/{event_id}/odds",
        {"regions": "us", "markets": "player_threes", "oddsFormat": "american"},
    )
    assert status == 200, f"player_threes probe failed: HTTP {status}, body={data}"

    bookmakers = data.get("bookmakers", [])
    if not bookmakers:
        pytest.skip(
            "player_threes has no inventory on this event right now — "
            "the market key is still valid (200 OK), just unpopulated. "
            "Re-run on a different event or before tip-off."
        )

    # Sanity-check the outcome shape we depend on in
    # _process_event's standard Over/Under flow.
    first_market = bookmakers[0].get("markets", [{}])[0]
    assert first_market.get("key") == "player_threes"
    outcomes = first_market.get("outcomes", [])
    assert outcomes, "Bookmaker had a player_threes market but no outcomes"

    sample = outcomes[0]
    # The fields the parser actually uses
    assert "name" in sample, "outcome missing `name` (Over/Under)"
    assert sample["name"] in ("Over", "Under"), (
        f"Unexpected outcome.name={sample['name']!r} for player_threes; "
        "if this changed, the standard parser will silently drop rows."
    )
    assert "description" in sample, "outcome missing `description` (player name)"
    assert "point" in sample, "outcome missing `point` (line value)"
    assert "price" in sample, "outcome missing `price` (American odds)"


@pytest.mark.integration
def test_player_field_goals_disambiguation_fgm_signature(event_id: str) -> None:
    """SPO-16 §4: assert `player_field_goals` is FGM (made) by checking the
    median `point` < 10. FGM thresholds cluster 5-10; FGA 10-20.

    Skips on `bookmakers: []` (still common for this market — see Scout §3.4)
    rather than asserting blindly. On assertion failure, the message tells
    the next runner exactly what to escalate to CTO with."""
    status, data = _http_get_json(
        f"/v4/sports/{SPORT}/events/{event_id}/odds",
        {"regions": "us", "markets": "player_field_goals", "oddsFormat": "american"},
    )
    assert status == 200, (
        f"player_field_goals probe failed: HTTP {status}; if this becomes "
        f"422 INVALID_MARKET, the market key was renamed/removed — escalate "
        f"to CTO + Scout per CLAUDE.md anti-hallucination rule #3."
    )

    bookmakers = data.get("bookmakers", [])
    if not bookmakers:
        pytest.skip(
            "player_field_goals has no inventory yet — disambiguation deferred. "
            "When bookmakers eventually post, this test will run and ground-"
            "truth the FGM-vs-FGA hypothesis automatically."
        )

    # Collect every `point` value across bookmakers/outcomes for this event.
    points: list[float] = []
    for bm in bookmakers:
        for market in bm.get("markets", []):
            if market.get("key") != "player_field_goals":
                continue
            for outcome in market.get("outcomes", []):
                p = outcome.get("point")
                if p is not None:
                    points.append(float(p))

    assert points, (
        "Bookmakers existed but no points collected — outcome shape may have "
        "changed; escalate to CTO with the populated response."
    )

    median = statistics.median(points)
    # Save the populated response so a CTO can diff it on escalation.
    artifact = Path("/tmp") / "spo16_player_field_goals_populated.json"
    artifact.write_text(json.dumps(data, indent=2))

    assert median < 10, (
        f"player_field_goals median(point)={median:.1f} suggests FGA pattern "
        f"(median ≥ 10), not FGM. ESCALATE to CTO with sample at {artifact} — "
        f"plan v4 may need a new 'historical-only / no API binding' UX class. "
        f"Do NOT auto-rename the metric; per Override 3 of the decision log "
        f"Addendum 1, the answer might be that Eason wanted FGA-attempted "
        f"which has no API contract."
    )
