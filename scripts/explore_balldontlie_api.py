#!/usr/bin/env python3
"""Probe BALLDONTLIE and print the raw shape.

This is the ground-truth script for the Sports Lab external-API policy.
Run it when a path or a field looks wrong. It calls three recorded
endpoints and prints the status, the rate-limit headers, and the first
500 characters of the body. It does not print the API key.

Recorded paths (see backend/tests/fixtures/bdl/):

    GET /v1/games?dates[]=YYYY-MM-DD&per_page=100
    GET /v1/player_injuries?per_page=100
    GET /v2/odds?dates[]=YYYY-MM-DD&per_page=100

Also recorded, not called here because the bodies are large or the
trial key only allows 5 requests per minute:

    GET /v2/odds/player_props?game_id=
    GET /nba/v1/projected_lineups?game_ids[]=
    GET /v1/players?player_ids[]=

Usage:
    python3 scripts/explore_balldontlie_api.py
    python3 scripts/explore_balldontlie_api.py 2026-11-11

Requires BALLDONTLIE_API_KEY in the environment or in .env at the repo
root or backend/.env. The header is ``Authorization: <key>`` with no
Bearer prefix. A 429 stops the script. It does not retry in a loop.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

BASE_URL = "https://api.balldontlie.io"
_RATE_HEADER_NAMES = (
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
)


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines into the environment without overriding it."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


_REPO_ROOT = Path(__file__).resolve().parent.parent
_load_env_file(_REPO_ROOT / ".env")
_load_env_file(_REPO_ROOT / "backend" / ".env")


def _redact(text: str, api_key: str) -> str:
    """Remove the key if a body ever echoes it."""
    if api_key and api_key in text:
        return text.replace(api_key, "[redacted]")
    return text


def _http_get(
    path: str,
    query: list[tuple[str, str]],
    api_key: str,
) -> tuple[int, dict[str, str], bytes]:
    """GET one path. Returns status, lower-cased headers, and raw body."""
    url = BASE_URL + path
    if query:
        url = url + "?" + urlencode(query)
    request = Request(
        url,
        method="GET",
        headers={"Authorization": api_key},
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
            headers = {name.lower(): value for name, value in response.headers.items()}
            return response.status, headers, body
    except HTTPError as exc:
        body = exc.read()
        headers = {name.lower(): value for name, value in (exc.headers or {}).items()}
        return exc.code, headers, body


def _rate(headers: dict[str, str]) -> dict[str, Optional[str]]:
    """The three rate-limit headers. Other headers are dropped on purpose."""
    return {name: headers.get(name) for name in _RATE_HEADER_NAMES}


def _print_probe(path: str, status: int, headers: dict[str, str], body: bytes, api_key: str) -> None:
    """Print status, rate-limit numbers, and a redacted body excerpt."""
    rate = _rate(headers)
    excerpt = _redact(body[:500].decode("utf-8", errors="replace"), api_key)
    print(f"\n--- {path} ---")
    print(f"  HTTP {status}")
    print(f"  x-ratelimit-limit:     {rate['x-ratelimit-limit']}")
    print(f"  x-ratelimit-remaining: {rate['x-ratelimit-remaining']}")
    print(f"  x-ratelimit-reset:     {rate['x-ratelimit-reset']}")
    print(f"  body[:500]:            {excerpt!r}")


def _eastern_today() -> str:
    """BALLDONTLIE ``dates[]`` values are Eastern game dates."""
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def main(argv: list[str]) -> int:
    """Probe games, injuries, and game lines for one Eastern date."""
    api_key = os.environ.get("BALLDONTLIE_API_KEY", "")
    if not api_key:
        print("ERROR: BALLDONTLIE_API_KEY is missing.", file=sys.stderr)
        return 2

    game_date = argv[1] if len(argv) > 1 else _eastern_today()
    probes: list[tuple[str, list[tuple[str, str]]]] = [
        ("/v1/games", [("dates[]", game_date), ("per_page", "100")]),
        ("/v1/player_injuries", [("per_page", "100")]),
        ("/v2/odds", [("dates[]", game_date), ("per_page", "100")]),
    ]

    print(f"# BALLDONTLIE probe date={game_date}")
    for path, query in probes:
        try:
            status, headers, body = _http_get(path, query, api_key)
        except URLError:
            print(f"\n--- {path} ---", file=sys.stderr)
            print("  request failed before a response", file=sys.stderr)
            return 1
        _print_probe(path, status, headers, body, api_key)
        if status == 429:
            print(
                "  HTTP 429. Not retrying. Wait until x-ratelimit-reset.",
                file=sys.stderr,
            )
            return 1
        remaining = headers.get("x-ratelimit-remaining")
        if remaining == "0":
            print("  remaining is 0. Not sending another call in this window.")
            return 0
        if status >= 400:
            return 1
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            print("  body was not JSON", file=sys.stderr)
            return 1
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list):
            print(f"  data length:           {len(data)}")
            meta = payload.get("meta") if isinstance(payload, dict) else None
            if isinstance(meta, dict) and "next_cursor" in meta:
                print(f"  next_cursor:           {meta.get('next_cursor')}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
