"""
explore_odds_api_wnba.py — The Odds API WNBA player-prop market verification.

This script is the Phase 0 ground-truth reference for the WNBA rollout
(SPO-31, parent epic SPO-29). It exists per `CLAUDE.md § External API
Wrappers` rule #1 (Exploration script first) and rule #3 (research must
cite curl output).

Mirrors `scripts/explore_odds_api_extensions.py` (NBA-side, SPO-12) in
structure and intent. Stdlib only — runnable from any venv with no extra
installs, so Forge/Sentinel can re-run on demand to detect schema drift.

What it does:
1. Lists upcoming WNBA events (`/v4/sports/basketball_wnba/events`)
   and picks the first one — used to anchor per-event market probes.
2. Probes each of the 12 NBA-supported markets against the
   `/events/{eventId}/odds?markets=...` endpoint to classify it as one
   of:
     - hard-supported       (HTTP 200 + `bookmakers` non-empty)
     - schema-valid+empty   (HTTP 200 + `bookmakers=[]`)
     - not-in-schema        (HTTP 4xx, market key rejected)
3. Captures `x-requests-used` / `x-requests-remaining` / `x-requests-last`
   on every call so quota burn is auditable.
4. Saves each raw response body to `/tmp/odds_wnba_<label>.json` so the
   research doc can include the first ~500 bytes as curl evidence.

Output: prints HTTP status, quota headers, body excerpt for every probe,
then a final 12-row summary table and total quota delta.

Usage:
    cd <repo-root>
    python3 scripts/explore_odds_api_wnba.py

Requires .env at repo root with:
    ODDS_API_KEY=...
    ODDS_API_BASE_URL=https://api.the-odds-api.com (default)

CAUTION (cost):
- Each populated single-market call costs 1 request unit (per-market
  billing, confirmed in SPO-12 — see `explore_odds_api_extensions.py`
  header). A full run probes 12 markets = ~12 units worst-case, less if
  some markets are not-in-schema (422 costs 0) or empty (0 cost). Run
  on demand only — DO NOT cron-loop.
- /events listing is free (`x-requests-last=0`).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError


# --- env loading (mirror NBA-side script — avoid python-dotenv dep) ---
def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_REPO_ROOT = Path(__file__).resolve().parent.parent
_load_env_file(_REPO_ROOT / ".env")
_load_env_file(_REPO_ROOT / "backend" / ".env")

API_KEY = os.environ.get("ODDS_API_KEY")
BASE_URL = os.environ.get("ODDS_API_BASE_URL", "https://api.the-odds-api.com")
SPORT = "basketball_wnba"

# 12-market candidate list — EXACT keys named in SPO-31 ticket §Scope.
# These mirror NBA's currently-supported markets minus FTM/FGM (Tier B
# graceful-degrade on NBA side) plus BLK/TOV (which are not yet in
# `daily_analysis.SUPPORTED_MARKETS` for NBA but were listed in the
# ticket as canonical 12 — Scout will flag the inventory gap in the
# research doc but probe what the ticket explicitly enumerates).
CANDIDATE_MARKETS: list[str] = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_steals",
    "player_blocks",
    "player_turnovers",
    "player_double_double",
    "player_points_rebounds",
    "player_points_assists",
    "player_rebounds_assists",
    "player_points_rebounds_assists",
]

# Core 3 — used by the gate-1 decision in SPO-31. If ANY of these are
# `not-in-schema`, the ticket says STOP and ping CTO.
CORE_MARKETS = {"player_points", "player_rebounds", "player_assists"}


def _http_get(path: str, params: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    """Pure-stdlib GET. Returns (status, lowercased-headers, body)."""
    qp = dict(params)
    qp["apiKey"] = API_KEY or ""
    url = f"{BASE_URL}{path}?{urlencode(qp)}"
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=30) as resp:
            body = resp.read()
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, headers, body
    except HTTPError as e:
        body = e.read()
        headers = {k.lower(): v for k, v in (e.headers or {}).items()}
        return e.code, headers, body


def _quota(headers: dict[str, str]) -> dict[str, Optional[str]]:
    return {
        "used": headers.get("x-requests-used"),
        "remaining": headers.get("x-requests-remaining"),
        "last": headers.get("x-requests-last"),
    }


def _save(label: str, body: bytes) -> Path:
    path = Path("/tmp") / f"odds_wnba_{label}.json"
    path.write_bytes(body)
    return path


def _print_probe(label: str, market_key: str, status: int, headers: dict[str, str], body: bytes) -> None:
    q = _quota(headers)
    saved = _save(label, body)
    excerpt = body[:500].decode("utf-8", errors="replace")
    print(f"\n--- {label} :: markets={market_key} ---")
    print(f"  HTTP {status}")
    print(f"  x-requests-used:      {q['used']}")
    print(f"  x-requests-remaining: {q['remaining']}")
    print(f"  x-requests-last:      {q['last']}")
    print(f"  body saved to:        {saved}")
    print(f"  body[:500]:           {excerpt!r}")


def _classify(status: int, body: bytes) -> str:
    """Classify a probe response per SPO-31 ticket labels.

    - `hard-supported`:    HTTP 200 + bookmakers non-empty (real lines posted)
    - `schema-valid+empty`: HTTP 200 + bookmakers = []
    - `not-in-schema`:     HTTP 4xx (API rejected the market key)
    - `unexpected`:        anything else (5xx, malformed JSON) — needs manual review
    """
    if status == 200:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return "unexpected"
        return "hard-supported" if data.get("bookmakers") else "schema-valid+empty"
    if 400 <= status < 500:
        return "not-in-schema"
    return "unexpected"


def main() -> int:
    if not API_KEY:
        print("ERROR: ODDS_API_KEY missing. Populate .env at repo root.", file=sys.stderr)
        return 2

    # Step 1: list upcoming WNBA events to grab an event_id (free — x-requests-last=0)
    print("# Step 1: list upcoming WNBA events (cost: 0)")
    status, headers, body = _http_get(f"/v4/sports/{SPORT}/events", {})
    _save("events_list", body)
    if status != 200:
        print(f"  /events FAILED: HTTP {status}", file=sys.stderr)
        print(f"  body[:500]: {body[:500]!r}", file=sys.stderr)
        # IMPORTANT: a 404 on /events with HTTP 200 on /sports would imply
        # `basketball_wnba` is not on the API at all — Gate 1 scope-cut.
        return 3
    try:
        events = json.loads(body)
    except json.JSONDecodeError:
        print(f"  /events returned non-JSON body: {body[:500]!r}", file=sys.stderr)
        return 3

    starting_quota = _quota(headers)
    print(f"  HTTP {status}, starting quota: {starting_quota}")
    print(f"  events returned: {len(events)}")

    if not events:
        # No upcoming WNBA games (e.g. off-season). The script cannot probe
        # per-event markets in this state — bail with an actionable error.
        # The reviewer/owner can re-run during the regular season.
        print(
            "  ERROR: no upcoming WNBA events. Re-run during the WNBA "
            "regular season (May–Oct) when fixtures are live.",
            file=sys.stderr,
        )
        return 4

    event = events[0]
    event_id = event["id"]
    print(
        f"  picked event_id={event_id} "
        f"({event.get('away_team')} @ {event.get('home_team')}, "
        f"commence_time={event.get('commence_time')})"
    )

    # Step 2: probe each of the 12 candidate markets one at a time so we
    # can classify each independently (a multi-market call would hide
    # which specific key was empty vs schema-valid).
    print(f"\n# Step 2: probe {len(CANDIDATE_MARKETS)} candidate markets (one per call)")
    summary: list[tuple[str, str, str]] = []  # (market_key, classification, notes)
    for market_key in CANDIDATE_MARKETS:
        label = market_key  # safe filename — already snake_case
        status, headers, body = _http_get(
            f"/v4/sports/{SPORT}/events/{event_id}/odds",
            {"regions": "us", "markets": market_key, "oddsFormat": "american"},
        )
        _print_probe(label, market_key, status, headers, body)
        classification = _classify(status, body)
        # Extract notes for the summary: bookmaker count if applicable.
        notes = ""
        if classification == "hard-supported":
            try:
                bms = json.loads(body).get("bookmakers", [])
                notes = f"bookmakers={len(bms)}"
            except json.JSONDecodeError:
                notes = "json-decode-failed"
        elif classification == "not-in-schema":
            # Show enough body to identify the error_code from the API.
            notes = body[:160].decode("utf-8", errors="replace").replace("\n", " ")
        summary.append((market_key, classification, notes))
        time.sleep(0.2)  # be polite to the API

    # Step 3: print final summary table
    print("\n# Step 3: summary table (per SPO-31 §Scope deliverable)")
    print(f"{'market_key':<36}{'classification':<22}notes")
    print("-" * 90)
    for market_key, cls, notes in summary:
        print(f"{market_key:<36}{cls:<22}{notes}")

    # Gate-1 check: any core market missing from schema?
    missing_core = [m for m, cls, _ in summary if m in CORE_MARKETS and cls == "not-in-schema"]
    if missing_core:
        print(
            f"\n⚠ GATE-1 FIRED: core markets not in WNBA schema: {missing_core}. "
            "Per SPO-31 §Gate behaviour, do NOT close `done` — reassign to CTO "
            "`in_review` and escalate Gate 1 (scope re-cut) to CEO via SPO-29."
        )

    # End-of-run quota — re-call free /sports to read the post-run counter
    status, headers, _ = _http_get("/v4/sports", {})
    ending_quota = _quota(headers)
    print(f"\n# Step 4: quota burn")
    print(f"  starting (after /events): {starting_quota}")
    print(f"  ending (after all probes): {ending_quota}")
    try:
        burn = int(ending_quota["used"] or 0) - int(starting_quota["used"] or 0)
        print(f"  paid units consumed:       {burn}")
    except (TypeError, ValueError):
        print("  paid units consumed:       (could not compute from headers)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
