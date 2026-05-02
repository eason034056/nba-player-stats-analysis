"""
explore_odds_api_extensions.py — The Odds API NBA player-prop market exploration.

This script is the ground-truth reference per
`CLAUDE.md § External API Wrappers` rule #1: "Exploration script first
(Forge). Before implementing ... or any new external API client, create
scripts/explore_<provider>_api.py that calls 2-3 real endpoints and
pretty-prints raw responses."

It is DELIBERATELY dep-free (stdlib `urllib` only) so it stays runnable in
any venv without extra installs. It is NOT used by production code — it
exists so that:

1. Forge can re-run it before implementing the new SUPPORTED_MARKETS set
   to confirm The Odds API has not silently renamed market keys (this has
   bitten Sports Lab before — see `backend/app/services/odds_theoddsapi.py`
   header notes).
2. Sentinel can copy the same probe pattern for the live integration
   test gated behind `RUN_INTEGRATION=1`.
3. The per-market quota measurement can be re-verified against future
   The Odds API plan changes.

Output:
- prints HTTP status, `x-requests-last` (this-call cost), `x-requests-used`,
  `x-requests-remaining`, and the first ~500 bytes of every response body
- ends with a summary table: which of the 9 candidate market keys are
  direct-supported vs not-available
- writes raw responses to /tmp/odds_explore_<label>.json so a later
  reviewer can diff schemas

Usage:
    cd <repo-root>
    python3 scripts/explore_odds_api_extensions.py

Requires .env at repo root with:
    ODDS_API_KEY=...
    ODDS_API_BASE_URL=https://api.the-odds-api.com  (or paid plan host)

CAUTION:
- Each populated single-market call costs 1 request unit (per Scout's
  2026-05-02 measurement). The script makes ~14 paid calls per full run
  (~14 units). Do NOT loop this script in a cron — it will burn the
  monthly 500-unit free tier in <2 days. Run manually, on demand.
- Empty-bookmakers responses (e.g. `player_field_goals` for NBA) cost 0.
- HTTP 422 INVALID_MARKET responses cost 0.
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


# --- env loading (lightweight; avoid pulling python-dotenv just for a script) ---
def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        # don't clobber explicit shell exports
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_REPO_ROOT = Path(__file__).resolve().parent.parent
_load_env_file(_REPO_ROOT / ".env")
_load_env_file(_REPO_ROOT / "backend" / ".env")

API_KEY = os.environ.get("ODDS_API_KEY")
BASE_URL = os.environ.get("ODDS_API_BASE_URL", "https://api.the-odds-api.com")
SPORT = "basketball_nba"

# --- 9 candidate markets from SPO-10 plan §3.1 + up to 3 variants each ---
# Each entry: (label, [variant_market_keys...]). Probe in order; stop on first 2xx.
CANDIDATES: list[tuple[str, list[str]]] = [
    ("3PM", ["player_threes", "player_three_pointers_made"]),
    ("STL", ["player_steals", "player_steals_alternate"]),
    # FTM canonical key: `player_frees_made` per The Odds API docs page
    # `the-odds-api.com/sports-odds-data/betting-markets.html`. The "frees"
    # spelling (not "free_throws") was missed in Scout's initial probe — see
    # research_odds_api_markets.md §3.3 for the post-review correction.
    # Currently a `[schema-valid-no-current-inventory]` market: HTTP 200 +
    # bookmakers=[] + 0-unit cost on every probe to date.
    ("FTM", ["player_frees_made", "player_freethrows_made", "player_free_throws"]),
    # FGA: docs only list `player_field_goals` (likely FGM, not FGA).
    # No `_attempted`/`_attempts` variant exists for NBA in the docs.
    ("FGA", ["player_field_goals", "player_field_goals_attempted", "player_field_goal_attempts"]),
    # 3PA: not in The Odds API NBA market list per docs. No variant exists.
    ("3PA", ["player_threes_attempted", "player_three_pointers_attempted", "player_three_point_attempts"]),
    ("R+A", ["player_rebounds_assists"]),
    ("P+R", ["player_points_rebounds"]),
    ("P+A", ["player_points_assists"]),
    ("DD",  ["player_double_double", "player_doubles_double", "player_dd"]),
]

# 5-market URL used for the Addendum 1 quota measurement (CEO requirement).
QUOTA_MULTI_MARKETS = "player_points,player_rebounds,player_assists,player_threes,player_steals"


def _http_get(path: str, params: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    """Pure-stdlib GET that returns (status, headers, body). Headers lowercased."""
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
    path = Path("/tmp") / f"odds_explore_{label}.json"
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


def _has_populated_bookmakers(body: bytes) -> bool:
    """A 200 with `bookmakers: []` means the market key is recognised by the
    schema but no bookmaker offers it for this event. We treat that as
    'effectively not-available' for downstream Phase 1 decisions."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False
    return bool(data.get("bookmakers"))


def main() -> int:
    if not API_KEY:
        print("ERROR: ODDS_API_KEY missing. Populate .env at repo root.", file=sys.stderr)
        return 2

    # 1) Pick a live NBA event_id (events endpoint is FREE — x-requests-last=0)
    print("# Step 1: list events to grab a live event_id (cost: 0)")
    status, headers, body = _http_get(f"/v4/sports/{SPORT}/events", {})
    if status != 200:
        print(f"  /events FAILED: HTTP {status} {body[:300]!r}", file=sys.stderr)
        return 3
    events = json.loads(body)
    if not events:
        print("  no events available — script cannot probe per-event markets", file=sys.stderr)
        return 4
    event_id = events[0]["id"]
    print(f"  picked event_id={event_id} ({events[0].get('away_team')} @ {events[0].get('home_team')})")
    print(f"  starting quota: {_quota(headers)}")

    # 2) Quota measurement — Addendum 1 (CEO MUST-DO)
    print("\n# Step 2: quota measurement (per-call vs per-market billing)")
    print("## 2a) single-market call: markets=player_threes")
    status, headers, body = _http_get(
        f"/v4/sports/{SPORT}/events/{event_id}/odds",
        {"regions": "us", "markets": "player_threes", "oddsFormat": "american"},
    )
    quota_a = _quota(headers)
    _save("quota_single", body)
    print(f"  HTTP {status}, quota={quota_a}")

    print("## 2b) free spacer: /v4/sports (must remain x-requests-last=0)")
    status, headers, _ = _http_get("/v4/sports", {})
    print(f"  HTTP {status}, quota={_quota(headers)}")

    print(f"## 2c) multi-market call: markets={QUOTA_MULTI_MARKETS} (5 markets)")
    status, headers, body = _http_get(
        f"/v4/sports/{SPORT}/events/{event_id}/odds",
        {"regions": "us", "markets": QUOTA_MULTI_MARKETS, "oddsFormat": "american"},
    )
    quota_c = _quota(headers)
    _save("quota_multi", body)
    print(f"  HTTP {status}, quota={quota_c}")

    # Interpret billing model based on x-requests-last delta
    last_a = int(quota_a["last"] or 0)
    last_c = int(quota_c["last"] or 0)
    print(f"\n  Billing analysis: single-call charged {last_a} unit(s); 5-market call charged {last_c} unit(s).")
    if last_c == 1:
        billing = "per-call (1 unit regardless of N markets)"
    elif last_c == 5 and last_a == 1:
        billing = "per-market (1 unit per populated market in URL)"
    else:
        billing = f"unexpected (last_a={last_a}, last_c={last_c}); inspect manually"
    print(f"  → Billing model: {billing}")

    # 3) Probe each candidate market (with variants, capped at 3 per CLAUDE.md anti-burn rule)
    print("\n# Step 3: probe 9 candidate markets (max 3 variants each)")
    summary: list[tuple[str, str, str]] = []  # (label, winning_key_or_none, classification)
    for label, variants in CANDIDATES:
        winner_key: Optional[str] = None
        classification = "[not-available]"
        for idx, key in enumerate(variants[:3]):  # cap = 3 variants
            v_label = f"{label.lower().replace('+','').replace(' ','')}_v{idx+1}"
            status, headers, body = _http_get(
                f"/v4/sports/{SPORT}/events/{event_id}/odds",
                {"regions": "us", "markets": key, "oddsFormat": "american"},
            )
            _print_probe(v_label, key, status, headers, body)
            if status == 200:
                if _has_populated_bookmakers(body):
                    winner_key = key
                    classification = "[direct-supported]"
                    break
                # Valid schema key but bookmakers=[]; record but keep trying variants
                if winner_key is None:
                    winner_key = key
                    classification = "[valid-but-empty]"
            time.sleep(0.2)  # be polite to the API
        summary.append((label, winner_key or "(none)", classification))

    # 4) Final summary
    print("\n# Step 4: summary table")
    print(f"{'stat':<6}{'winning market key':<40}{'classification'}")
    print("-" * 80)
    for label, key, cls in summary:
        print(f"{label:<6}{key:<40}{cls}")

    # End-of-run quota
    status, headers, _ = _http_get("/v4/sports", {})
    print(f"\nFinal quota: {_quota(headers)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
