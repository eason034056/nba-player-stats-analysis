"""Record the Odds API bodies that SPO-98 did not capture.

Reads ``ODDS_API_KEY`` from the environment. Does not read a key from
argv, so the key does not land in shell history as a flag.

Calls, in order:

1. ``GET /v4/sports/basketball_nba/events`` — free. Picks the first
   listed event. Writes nothing over the SPO-98 events file.
2. One ``GET /v4/sports/basketball_nba/events/{id}/odds`` with every
   unrecorded market in a single ``markets=`` parameter,
   ``regions=us``, ``bookmakers=draftkings,fanduel``,
   ``oddsFormat=american``. Saves that body as
   ``odds_api_event_odds__nba_expanded_markets.json``.

Each response is written as the raw bytes. The only edit is removing
``apiKey`` if it appears in those bytes. Quota headers are printed
for every call:

    x-requests-used
    x-requests-remaining
    x-requests-last

Usage (from ``backend/``)::

    ODDS_API_KEY=... python tests/fixtures/odds_api/record_fixtures.py

Exit 0 after the NBA odds body is saved. Exit 2 when the key is
missing or the NBA events list is empty (no file is written).
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Same directory as this file's package; the JSON lives one level up.
_FIXTURES_DIR = Path(__file__).resolve().parent.parent

NBA_EXPANDED_MARKETS = "odds_api_event_odds__nba_expanded_markets.json"

# Keep this tuple aligned with tests.fixtures.odds_api.UNRECORDED_MARKET_KEYS.
UNRECORDED_MARKET_KEYS: tuple[str, ...] = (
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_steals",
    "player_frees_made",
    "player_field_goals",
    "player_rebounds_assists",
    "player_points_rebounds",
    "player_points_assists",
    "player_points_rebounds_assists",
    "player_double_double",
)

_HEADER_USED = "x-requests-used"
_HEADER_REMAINING = "x-requests-remaining"
_HEADER_LAST = "x-requests-last"


def strip_api_key(raw: bytes, api_key: str) -> bytes:
    """Drop the key from raw response bytes. Leave every other byte.

    The Odds API puts the key in the query string, not the body. This
    still removes it if a body or an error page echoes the request URL.
    """
    if not api_key or api_key.encode("utf-8") not in raw:
        return raw
    return raw.replace(api_key.encode("utf-8"), b"")


def _print_quota(label: str, headers: dict[str, str]) -> None:
    """Print the three quota headers for one call."""
    print(f"{label}")
    print(f"  {_HEADER_USED}: {headers.get(_HEADER_USED, '')}")
    print(f"  {_HEADER_REMAINING}: {headers.get(_HEADER_REMAINING, '')}")
    print(f"  {_HEADER_LAST}: {headers.get(_HEADER_LAST, '')}")


def _request(url: str) -> tuple[int, dict[str, str], bytes]:
    """GET ``url``. Returns status, header map, and raw body bytes."""
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            header_map = {key.lower(): value for key, value in resp.headers.items()}
            return resp.status, header_map, resp.read()
    except urllib.error.HTTPError as exc:
        header_map = {key.lower(): value for key, value in exc.headers.items()}
        return exc.code, header_map, exc.read()


def _url(base: str, path: str, params: dict[str, str]) -> str:
    """Build a URL. ``params`` must already include ``apiKey``."""
    query = urllib.parse.urlencode(params)
    return f"{base}{path}?{query}"


def _save(name: str, raw: bytes, api_key: str) -> Path:
    """Write a body under fixtures/. Strip the key, change nothing else."""
    path = _FIXTURES_DIR / name
    path.write_bytes(strip_api_key(raw, api_key))
    return path


def _events(base: str, api_key: str, sport: str) -> tuple[int, dict[str, str], bytes]:
    """Free events list for ``sport``. Prints quota headers."""
    url = _url(base, f"/v4/sports/{sport}/events", {"apiKey": api_key})
    status, headers, body = _request(url)
    _print_quota(f"GET /v4/sports/{sport}/events", headers)
    return status, headers, body


def _odds(
    base: str,
    api_key: str,
    sport: str,
    event_id: str,
) -> tuple[int, dict[str, str], bytes]:
    """One odds call. Every unrecorded market is in ``markets``."""
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": ",".join(UNRECORDED_MARKET_KEYS),
        "bookmakers": "draftkings,fanduel",
        "oddsFormat": "american",
    }
    url = _url(base, f"/v4/sports/{sport}/events/{event_id}/odds", params)
    status, headers, body = _request(url)
    _print_quota(
        f"GET /v4/sports/{sport}/events/{event_id}/odds "
        f"markets={params['markets']}",
        headers,
    )
    return status, headers, body


def _first_event_id(raw: bytes) -> str | None:
    """First ``id`` in an events-list body, or None if the list is empty."""
    import json

    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or not data:
        return None
    event_id = data[0].get("id")
    if not event_id:
        return None
    return str(event_id)


def main() -> int:
    """Record one NBA odds body. The events list is free and is not saved."""
    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        print("ODDS_API_KEY is not set; no request was sent and no file was written.")
        return 2

    base = os.environ.get("ODDS_API_BASE_URL", "https://api.the-odds-api.com").rstrip(
        "/"
    )

    status, _headers, body = _events(base, api_key, "basketball_nba")
    if status != 200:
        print(f"NBA events list failed with HTTP {status}; no fixture written.")
        print(strip_api_key(body, api_key).decode("utf-8", errors="replace")[:500])
        return 2
    event_id = _first_event_id(body)
    if not event_id:
        print("NBA events list is empty; no fixture written.")
        return 2

    status, _headers, body = _odds(base, api_key, "basketball_nba", event_id)
    if status != 200:
        print(f"NBA odds call failed with HTTP {status}; no fixture written.")
        print(strip_api_key(body, api_key).decode("utf-8", errors="replace")[:500])
        return 2
    saved = _save(NBA_EXPANDED_MARKETS, body, api_key)
    print(f"wrote {saved}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
