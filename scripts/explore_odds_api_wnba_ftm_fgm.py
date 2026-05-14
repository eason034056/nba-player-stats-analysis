"""
explore_odds_api_wnba_ftm_fgm.py — Phase 0 follow-up probe.

Probes `player_frees_made` (FTM) and `player_field_goals` (FGM) on
`basketball_wnba` to fill the verification gap flagged in
docs/research/wnba-rollout/odds_api_wnba_markets.md §6.

Why a second script (instead of editing `explore_odds_api_wnba.py`):
- The original script's 12-market list is locked to the SPO-31 ticket §Scope
  and has been audited in Lens / Sentinel review of SPO-31. Reordering it now
  would invalidate the "probed list = ticket scope" property the research
  doc cites. A targeted follow-up probe keeps Phase 0's audit trail intact.
- FTM/FGM verification is a Phase 2 (SPO-33) Lens-review block, not a Phase 0
  re-scope.

Cost: ≤ 2 paid units (1 per populated market, 0 for empty/not-in-schema).

Anchors on the SPO-31 §3.1 event id `efb5e7faabc4ea9406b9b479ae805b38`
(Storm @ Tempo) and falls back to the first live event if that anchor has
concluded. Output mirrors `explore_odds_api_wnba.py` so the research doc
appends cleanly under the same evidence format.
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

# Phase 0 §3.1 anchor — Storm @ Tempo, 2026-05-13T23:00:00Z.
PHASE0_ANCHOR_EVENT_ID = "efb5e7faabc4ea9406b9b479ae805b38"

# The two markets Phase 0 explicitly did NOT probe (§6).
FOLLOWUP_MARKETS = [
    "player_frees_made",   # NBA Tier-B; never probed on WNBA in SPO-31.
    "player_field_goals",  # NBA Tier-B; never probed on WNBA in SPO-31.
]


def _http_get(path: str, params: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
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


def _classify(status: int, body: bytes) -> str:
    if status == 200:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return "unexpected"
        return "hard-supported" if data.get("bookmakers") else "schema-valid+empty"
    if 400 <= status < 500:
        return "not-in-schema"
    return "unexpected"


def _resolve_event_id() -> Optional[str]:
    """Try the Phase 0 anchor; fall back to first live event if it has concluded."""
    status, _headers, _body = _http_get(
        f"/v4/sports/{SPORT}/events/{PHASE0_ANCHOR_EVENT_ID}/odds",
        {"regions": "us", "markets": "player_points", "oddsFormat": "american"},
    )
    if status == 200:
        return PHASE0_ANCHOR_EVENT_ID

    # Fallback: pull live events (FREE — x-requests-last=0).
    status, _headers, body = _http_get(f"/v4/sports/{SPORT}/events", {})
    if status != 200:
        return None
    try:
        events = json.loads(body)
    except json.JSONDecodeError:
        return None
    return events[0]["id"] if events else None


def main() -> int:
    if not API_KEY:
        print("ERROR: ODDS_API_KEY missing. Populate .env at repo root.", file=sys.stderr)
        return 2

    event_id = _resolve_event_id()
    if not event_id:
        print("ERROR: could not resolve a live WNBA event id.", file=sys.stderr)
        return 3
    print(f"# Probing event_id={event_id}\n")

    summary: list[tuple[str, str, int, str]] = []
    starting_used: Optional[int] = None

    for market_key in FOLLOWUP_MARKETS:
        status, headers, body = _http_get(
            f"/v4/sports/{SPORT}/events/{event_id}/odds",
            {"regions": "us", "markets": market_key, "oddsFormat": "american"},
        )
        q = _quota(headers)
        if starting_used is None and q["used"] is not None:
            try:
                starting_used = int(q["used"])
            except ValueError:
                pass
        classification = _classify(status, body)
        excerpt = body[:500].decode("utf-8", errors="replace")
        save_path = Path("/tmp") / f"odds_wnba_{market_key}.json"
        save_path.write_bytes(body)

        print(f"--- {market_key} ---")
        print(f"  HTTP {status}")
        print(f"  classification:       {classification}")
        print(f"  x-requests-used:      {q['used']}")
        print(f"  x-requests-remaining: {q['remaining']}")
        print(f"  x-requests-last:      {q['last']}")
        print(f"  body saved to:        {save_path}")
        print(f"  body[:500]:           {excerpt!r}\n")
        summary.append((market_key, classification, status, q.get("last") or ""))
        time.sleep(0.2)

    print("# Summary")
    print(f"{'market_key':<24}{'classification':<22}HTTP  units")
    print("-" * 64)
    for market_key, cls, status, last in summary:
        print(f"{market_key:<24}{cls:<22}{status:<5} {last}")

    # Ending quota
    status, headers, _ = _http_get("/v4/sports", {})
    print(f"\nending x-requests-used: {_quota(headers)['used']} (started at {starting_used})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
