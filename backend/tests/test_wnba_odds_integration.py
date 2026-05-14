"""
SPO-33 — WNBA live integration tests against The Odds API.

Gated behind ``RUN_INTEGRATION=1`` (per `CLAUDE.md § External API Wrappers`
rule #2). Default behavior: pytest skips this entire module so day-to-day
runs do NOT burn the paid Odds API quota. Pattern mirrors
``test_spo16_integration.py``.

Tests in this file:

1. ``test_wnba_events_endpoint_live`` — hit
   ``/v4/sports/basketball_wnba/events`` directly; assert the schema match
   that Forge's ``wnba.get_events`` route relies on. Free (0 quota units).
   This is the only place we prove the WNBA ``sport_key`` actually exists
   on the API — if The Odds API ever renames it, this test fails
   immediately rather than the UI silently rendering empty event lists.

2. ``test_wnba_player_points_returns_populated_payload`` — probe
   ``player_points`` on a live WNBA event and assert the Over/Under shape
   the NBA parser already handles 1:1. This is the SPO-33 "mandatory
   integration test" deliverable. Cost: 1 quota unit per run (per-market
   billing, same as NBA SPO-12 measurement).

3. ``test_wnba_double_double_binary_shape`` — probe
   ``player_double_double`` and assert the binary Yes/No contract (no
   ``point`` field). Verifies the DD-binary parser path established in
   SPO-26 ports to WNBA. Cost: 1 quota unit if populated, 0 if empty.

4. ``test_wnba_player_steals_empty_bookmakers_graceful`` — probe a market
   Phase 0 classified as ``schema-valid+empty`` (``player_steals``);
   assert the response is well-formed even when ``bookmakers: []``, so
   the empty-bookmakers UX guard from SPO-26 fires gracefully (no 500,
   no schema drift). Cost: 0 quota units.

Anchor event id captured from SPO-31 Phase 0's research doc
(``docs/research/wnba-rollout/odds_api_wnba_markets.md`` §3.1) — Storm @
Tempo, 2026-05-13T23:00:00Z. Falls back to a live ``/events`` probe when
the anchor has concluded.

⚠ DO NOT run these in CI without explicit opt-in. The Odds API quota is
paid and finite. Eason invokes them locally before merge.

Verification commands:

    # Default (skip — 0 units burned)
    .venv/bin/pytest tests/test_wnba_odds_integration.py -v

    # Live (≤ 2 paid units consumed)
    RUN_INTEGRATION=1 .venv/bin/pytest tests/test_wnba_odds_integration.py -v
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest


# Skip the entire module unless RUN_INTEGRATION=1.
if os.environ.get("RUN_INTEGRATION") != "1":
    pytest.skip(
        "RUN_INTEGRATION=1 not set; skipping live The Odds API WNBA tests "
        "(see CLAUDE.md § External API Wrappers rule #2)",
        allow_module_level=True,
    )


# Reuse the same .env loading pattern as test_spo16_integration.py.
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
BASE_URL = os.environ.get("ODDS_API_BASE_URL", "https://api.the-odds-api.com")
SPORT = "basketball_wnba"

# Captured in SPO-31 Phase 0 research doc §3.1 — Storm @ Tempo 2026-05-13.
# Falls back to a live /events probe if this event has concluded.
PHASE0_ANCHOR_EVENT_ID = "efb5e7faabc4ea9406b9b479ae805b38"


def _http_get_json(path: str, params: dict[str, str]) -> tuple[int, Any]:
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


def _pick_live_event_id() -> str | None:
    """Pull a live WNBA event_id — /events is FREE (0 quota units)."""
    status, data = _http_get_json(f"/v4/sports/{SPORT}/events", {})
    if status != 200 or not isinstance(data, list) or not data:
        return None
    return data[0].get("id")


@pytest.fixture(scope="module")
def event_id() -> str:
    """
    Resolve the integration-test target event:
    1. Try the SPO-31 Phase 0 anchor (Storm @ Tempo).
    2. If 404 (concluded), pick the first live event.
    3. If no live events at all, skip — not a failure.
    """
    if not API_KEY:
        pytest.fail(
            "ODDS_API_KEY not set — populate .env at repo root before running "
            "RUN_INTEGRATION=1 tests"
        )

    status, _data = _http_get_json(
        f"/v4/sports/{SPORT}/events/{PHASE0_ANCHOR_EVENT_ID}/odds",
        {"regions": "us", "markets": "player_points", "oddsFormat": "american"},
    )
    if status == 200:
        return PHASE0_ANCHOR_EVENT_ID

    eid = _pick_live_event_id()
    if not eid:
        pytest.skip(
            "No live WNBA events available right now — integration test "
            "cannot run without a real event id"
        )
    return eid


@pytest.mark.integration
def test_wnba_events_endpoint_live() -> None:
    """
    Anti-hallucination: the only place we assert ``basketball_wnba`` exists
    on the API. Free probe (0 units). If The Odds API renames the sport
    key, this test fails immediately rather than letting the WNBA UI render
    silent empties.
    """
    status, data = _http_get_json(f"/v4/sports/{SPORT}/events", {})
    assert status == 200, f"Unexpected status {status} body={data!r}"
    assert isinstance(data, list), f"Expected list, got {type(data).__name__}"
    if not data:
        pytest.skip("No WNBA events on the wire right now — schema check N/A")

    first = data[0]
    for key in ("id", "sport_key", "home_team", "away_team", "commence_time"):
        assert key in first, f"Missing required key {key!r} in event {first!r}"
    assert first["sport_key"] == SPORT, (
        f"Unexpected sport_key {first['sport_key']!r}; expected {SPORT!r}"
    )


@pytest.mark.integration
def test_wnba_player_points_returns_populated_payload(event_id: str) -> None:
    """
    SPO-33 mandatory integration test. Confirms WNBA ``player_points`` carries
    the Over/Under shape NBA's parser handles 1:1. Cost: 1 quota unit.

    Asserts:
    - HTTP 200
    - ``bookmakers`` array present
    - if populated, each Over/Under outcome has ``description`` (player),
      ``point`` (line), and ``price`` (American odds).
    """
    status, data = _http_get_json(
        f"/v4/sports/{SPORT}/events/{event_id}/odds",
        {"regions": "us", "markets": "player_points", "oddsFormat": "american"},
    )
    assert status == 200, f"Unexpected status {status} body={data!r}"
    assert isinstance(data, dict)
    assert "bookmakers" in data

    if not data["bookmakers"]:
        pytest.skip(
            "player_points returned empty bookmakers — Phase 0 classified "
            "this as hard-supported on 2026-05-13, but this specific event "
            "may not have inventory yet; not a regression"
        )

    found_over_under = False
    for bookmaker in data["bookmakers"]:
        assert "key" in bookmaker
        for market in bookmaker.get("markets", []):
            if market.get("key") != "player_points":
                continue
            for outcome in market.get("outcomes", []):
                name = (outcome.get("name") or "").lower()
                if name in ("over", "under"):
                    assert "description" in outcome, f"Missing description on {outcome!r}"
                    assert "point" in outcome, f"Missing point on {outcome!r}"
                    assert "price" in outcome, f"Missing price on {outcome!r}"
                    found_over_under = True

    assert found_over_under, (
        "Expected at least one Over/Under outcome in player_points payload; "
        "found none — schema may have drifted from Phase 0 evidence"
    )


@pytest.mark.integration
def test_wnba_double_double_binary_shape(event_id: str) -> None:
    """
    SPO-33 §"DD-binary parsing path verified for WNBA". Asserts the binary
    contract for ``player_double_double``: ``name in {yes, no}`` and NO
    ``point`` field. If The Odds API ever starts emitting a ``point`` for
    DD, the contract changes and the parser needs to be revisited — this
    test catches that immediately.

    Cost: 1 unit if populated, 0 if empty.
    """
    status, data = _http_get_json(
        f"/v4/sports/{SPORT}/events/{event_id}/odds",
        {
            "regions": "us",
            "markets": "player_double_double",
            "oddsFormat": "american",
        },
    )
    assert status == 200, f"Unexpected status {status} body={data!r}"
    assert isinstance(data, dict)
    assert "bookmakers" in data

    if not data["bookmakers"]:
        pytest.skip(
            "player_double_double returned empty bookmakers — not posted on "
            "this specific event right now"
        )

    found_binary_outcome = False
    for bookmaker in data["bookmakers"]:
        for market in bookmaker.get("markets", []):
            if market.get("key") != "player_double_double":
                continue
            for outcome in market.get("outcomes", []):
                name = (outcome.get("name") or "").lower()
                if name in ("yes", "no"):
                    assert "point" not in outcome, (
                        f"Unexpected `point` on DD outcome {outcome!r} — "
                        "binary contract violated; binary-parser logic needs "
                        "to be revisited"
                    )
                    assert "price" in outcome
                    assert "description" in outcome
                    found_binary_outcome = True

    assert found_binary_outcome, "Expected at least one Yes/No outcome on DD market"


@pytest.mark.integration
def test_wnba_player_steals_empty_bookmakers_graceful(event_id: str) -> None:
    """
    SPO-33 acceptance criterion: markets Phase 0 classified as
    ``schema-valid+empty`` (``player_steals`` / ``player_blocks`` /
    ``player_turnovers``) must return well-formed JSON with ``bookmakers: []``
    so the existing SPO-26 empty-bookmakers UX guard fires gracefully —
    NOT a 500 or schema drift.

    Cost: 0 quota units (empty markets are unbilled — SPO-12 measurement).

    If bookmakers HAVE started posting steals by the time this runs (Phase 0
    noted WNBA bookmaker product launches lag NBA by ~4 weeks), the test
    still passes — we are asserting the schema is well-formed, not that
    inventory stays empty forever.
    """
    status, data = _http_get_json(
        f"/v4/sports/{SPORT}/events/{event_id}/odds",
        {
            "regions": "us",
            "markets": "player_steals",
            "oddsFormat": "american",
        },
    )
    assert status == 200, f"Unexpected status {status} body={data!r}"
    assert isinstance(data, dict)
    for key in ("id", "sport_key", "home_team", "away_team", "bookmakers"):
        assert key in data, f"Missing required key {key!r} in steals response"
    assert data["sport_key"] == SPORT
    assert isinstance(data["bookmakers"], list), (
        f"bookmakers must be a list (even if empty); got "
        f"{type(data['bookmakers']).__name__}"
    )
