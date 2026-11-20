#!/usr/bin/env python3
"""Probe the two BALLDONTLIE paths the SPO-138 history backfill reads.

The backfill walks whole seasons through:

    GET /v1/games?seasons[]=YYYY&per_page=100
    GET /v1/stats?seasons[]=YYYY&per_page=100

``seasons[]=2000`` is the 2000-01 season. For each season given, this
fetches page 1 of both paths and prints the status, rate-limit headers,
row count, next_cursor, and a per-field null profile. One page is 100
rows, so the profile is a sample of a few games, not a season.

``--game-id`` asks for single games instead, by a path the walk never uses:

    GET /v1/games/<id>
    GET /v1/stats?game_ids[]=<id>&per_page=100

For a page holding one game, each team's player points are printed beside
its score, with its minutes. This is how an upstream gap is shown to be
BALLDONTLIE's and not the walk's.

Usage:
    python3 scripts/explore_bdl_backfill.py
    python3 scripts/explore_bdl_backfill.py 2000 2025
    python3 scripts/explore_bdl_backfill.py 2000 --save-fixtures
    python3 scripts/explore_bdl_backfill.py 2025 1900 abc --endpoints stats --save-fixtures
    python3 scripts/explore_bdl_backfill.py 2025 --endpoints games --season-type playoffs --save-fixtures
    python3 scripts/explore_bdl_backfill.py 2000 --endpoints stats --cursor 272160 --save-fixtures
    python3 scripts/explore_bdl_backfill.py --game-id 48851 --game-id 434 --save-fixtures

--save-fixtures writes each response to backend/tests/fixtures/bdl/ as
``<endpoint>__season<value>_<variant>.json`` (or
``<endpoint>__season<value>_<season_type>_<variant>.json``,
``<endpoint>__season<value>_cursor<cursor>_page.json`` for a later page, and
``<endpoint>__game<id>_<variant>.json`` for one game) in the
``{request, status, elapsed_s, rate_headers, response}`` shape that
backend/tests/test_bdl_client.py reads. The variant is ``page1`` when
rows came back (``record`` for the one object of ``/v1/games/<id>``),
``empty`` for HTTP 200 with no rows, and ``http<status>`` for an error. A non-JSON body is stored under ``response._raw``. The run
stops after the first non-200 response.

Key loading, the request, and key redaction come from
explore_balldontlie_api.py in this directory.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode

from explore_balldontlie_api import BASE_URL, _http_get, _rate, _redact

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_DIR = _REPO_ROOT / "backend" / "tests" / "fixtures" / "bdl"
_ENDPOINTS = ("games", "stats")
_DNP_MINUTES = {None, "", "0", "00", "0:00", "00:00"}
_SAMPLE_WIDTH = 40


def _flatten(row: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Nested objects become dotted names: ``player.height``."""
    flat: dict[str, Any] = {}
    for key, value in row.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{name}."))
        else:
            flat[name] = value
    return flat


def _null_profile(rows: list[dict[str, Any]]) -> list[tuple[str, int, int, Any]]:
    """Per field: rows where it is null, rows where the key is absent, one non-null sample."""
    flat_rows = [_flatten(row) for row in rows]
    fields = sorted({name for flat in flat_rows for name in flat})
    profile: list[tuple[str, int, int, Any]] = []
    for name in fields:
        null = sum(1 for flat in flat_rows if name in flat and flat[name] is None)
        missing = sum(1 for flat in flat_rows if name not in flat)
        sample = next((flat[name] for flat in flat_rows if flat.get(name) is not None), None)
        profile.append((name, null, missing, sample))
    return profile


def _print_profile(rows: list[dict[str, Any]]) -> None:
    """Fields with any null or absent value get a row; the rest are listed by name."""
    profile = _null_profile(rows)
    gaps = [entry for entry in profile if entry[1] or entry[2]]
    filled = [name for name, null, missing, _ in profile if not null and not missing]
    total = len(rows)
    if gaps:
        print(f"  {'field':<28} {'null':>8} {'absent':>8}  sample")
        for name, null, missing, sample in gaps:
            shown = repr(sample)[:_SAMPLE_WIDTH]
            print(f"  {name:<28} {null:>4}/{total:<3} {missing:>4}/{total:<3}  {shown}")
    else:
        print("  no null or absent values on this page")
    print(f"  always filled ({len(filled)}): {', '.join(filled)}")


def _print_stats_shape(rows: list[dict[str, Any]]) -> None:
    """How many games one page spans, and how many rows look like DNP."""
    game_ids = {row["game"]["id"] for row in rows if isinstance(row.get("game"), dict)}
    dnp = sum(1 for row in rows if row.get("min") in _DNP_MINUTES)
    minute_samples = sorted({str(row.get("min")) for row in rows})[:8]
    print(f"  distinct games on page: {len(game_ids)}")
    print(f"  rows with min in {sorted(map(str, _DNP_MINUTES))}: {dnp}")
    print(f"  min value samples: {minute_samples}")
    if len(game_ids) == 1:
        _print_team_totals(rows)


def _minutes(raw: Any) -> float:
    """``"13:44"`` or ``"16"`` as minutes; no minutes is 0."""
    if raw in (None, ""):
        return 0.0
    minutes, _, seconds = str(raw).partition(":")
    return int(minutes) + int(seconds or 0) / 60


def _print_team_totals(rows: list[dict[str, Any]]) -> None:
    """Each team's player points beside its score, and its minutes: 240 plus 25 per overtime."""
    game = rows[0]["game"]
    print(f"  period: {game['period']}")
    for side in ("visitor", "home"):
        team_id = game[f"{side}_team_id"]
        lines = [row for row in rows if row["team"]["id"] == team_id]
        points = sum(row["pts"] or 0 for row in lines)
        minutes = sum(_minutes(row["min"]) for row in lines)
        print(
            f"  {side} team {team_id}: {len(lines)} lines, {points} player points"
            f" (score {game[f'{side}_team_score']}), {minutes:.1f} minutes"
        )


def _save_fixture(
    name: str,
    url: str,
    status: int,
    elapsed_s: float,
    headers: dict[str, str],
    response: dict[str, Any],
) -> Path:
    """Write one capture in the shape test_bdl_client.py expects."""
    capture = {
        "request": url,
        "status": status,
        "elapsed_s": round(elapsed_s, 2),
        "rate_headers": _rate(headers),
        "response": response,
    }
    path = _FIXTURE_DIR / name
    path.write_text(json.dumps(capture, indent=1, ensure_ascii=False) + "\n")
    return path


def _print_games_shape(rows: list[dict[str, Any]]) -> None:
    """What a season_type filter is checked against: the postseason flag, dates, and Cup stages."""
    postseason = sorted({str(row.get("postseason")) for row in rows})
    dates = sorted(str(row.get("date")) for row in rows)
    stages = sorted({str(row.get("ist_stage")) for row in rows})
    print(f"  postseason values: {postseason}")
    print(f"  dates: {dates[0]} .. {dates[-1]}")
    print(f"  ist_stage values: {stages}")


def _season_label(season: str) -> str:
    """``2000`` is the 2000-01 season. A non-numeric value is shown as sent."""
    if not season.isdigit():
        return season
    year = int(season)
    return f"{year}-{(year + 1) % 100:02d}"


def _fixture_name(
    endpoint: str,
    season: str,
    season_type: str | None,
    cursor: int | None,
    status: int,
    rows: list[Any],
) -> str:
    """The variant comes from the response, not from what the probe expected."""
    if status != 200:
        variant = f"http{status}"
    elif rows:
        variant = "page1" if cursor is None else "page"
    else:
        variant = "empty"
    filtered = f"_{season_type}" if season_type else ""
    at = f"_cursor{cursor}" if cursor is not None else ""
    return f"{endpoint}__season{season}{filtered}{at}_{variant}.json"


def _game_fixture_name(endpoint: str, game_id: int, status: int, rows: list[Any]) -> str:
    """``/v1/games/<id>`` returns one object, saved as ``record``; ``/v1/stats`` returns a page."""
    if status != 200:
        variant = f"http{status}"
    elif not rows:
        variant = "empty"
    else:
        variant = "record" if endpoint == "games" else "page1"
    return f"{endpoint}__game{game_id}_{variant}.json"


def _probe(
    season: str,
    endpoint: str,
    api_key: str,
    save: bool,
    season_type: str | None,
    cursor: int | None = None,
) -> bool:
    """Fetch one page (page 1, or ``cursor``) of one endpoint for one season. False means stop the run."""
    path = f"/v1/{endpoint}"
    query = [("seasons[]", season)]
    if season_type:
        query.append(("season_type", season_type))
    query.append(("per_page", "100"))
    if cursor is not None:
        query.append(("cursor", str(cursor)))
    shown_type = f" season_type={season_type}" if season_type else ""
    shown_type += f" cursor={cursor}" if cursor is not None else ""
    return _fetch(
        path, query, f"{path} season={season} ({_season_label(season)}){shown_type}", endpoint, api_key, save,
        lambda status, rows: _fixture_name(endpoint, season, season_type, cursor, status, rows),
    )


def _probe_game(game_id: int, endpoint: str, api_key: str, save: bool) -> bool:
    """Fetch one game's record, or every stats line of it. False means stop the run."""
    if endpoint == "games":
        path, query = f"/v1/games/{game_id}", []
    else:
        path, query = "/v1/stats", [("game_ids[]", str(game_id)), ("per_page", "100")]
    return _fetch(
        path, query, f"{path} game_id={game_id}", endpoint, api_key, save,
        lambda status, rows: _game_fixture_name(endpoint, game_id, status, rows),
    )


def _fetch(
    path: str,
    query: list[tuple[str, str]],
    heading: str,
    endpoint: str,
    api_key: str,
    save: bool,
    fixture_name: Callable[[int, list[Any]], str],
) -> bool:
    """Send one request, print what came back, and save it if asked. False means stop the run."""
    url = f"{BASE_URL}{path}" + (f"?{urlencode(query)}" if query else "")
    print(f"\n--- {heading} ---")

    started = time.monotonic()
    try:
        status, headers, body = _http_get(path, query, api_key)
    except URLError:
        print("  request failed before a response", file=sys.stderr)
        return False
    elapsed_s = time.monotonic() - started
    text = _redact(body.decode("utf-8", errors="replace"), api_key)
    rate = _rate(headers)
    print(
        f"  HTTP {status}  {elapsed_s:.2f}s  "
        f"limit={rate['x-ratelimit-limit']} remaining={rate['x-ratelimit-remaining']}"
    )

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    response = payload if isinstance(payload, dict) else {"_raw": text}
    data = response.get("data")
    rows = [data] if isinstance(data, dict) else data or []

    if status != 200:
        print(f"  body[:500]: {text[:500]!r}")
    elif payload is None:
        print("  body was not JSON", file=sys.stderr)
        return False
    else:
        print(f"  rows: {len(rows)}  meta: {response.get('meta')}")
        if rows:
            _print_profile(rows)
            if endpoint == "stats":
                _print_stats_shape(rows)
            else:
                _print_games_shape(rows)

    if save:
        saved = _save_fixture(fixture_name(status, rows), url, status, elapsed_s, headers, response)
        print(f"  saved {saved.relative_to(_REPO_ROOT)}")

    if status != 200:
        return False
    if rate["x-ratelimit-remaining"] == "0":
        print("  remaining is 0. Not sending another call in this window.")
        return False
    return True


def main(argv: list[str]) -> int:
    """Probe games and stats page 1 for each season, or each game, on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("seasons", nargs="*", help="start years; 2000 when no season or game is given")
    parser.add_argument("--endpoints", nargs="+", choices=_ENDPOINTS, default=list(_ENDPOINTS))
    parser.add_argument("--save-fixtures", action="store_true")
    parser.add_argument("--season-type", help="games only: BALLDONTLIE season_type filter")
    parser.add_argument("--cursor", type=int, help="fetch the page at this cursor instead of page 1")
    parser.add_argument(
        "--game-id", type=int, action="append", default=[], metavar="ID",
        help="fetch /v1/games/<id> and /v1/stats?game_ids[]=<id> instead of season pages (repeatable)",
    )
    args = parser.parse_args(argv[1:])
    if args.game_id and (args.seasons or args.season_type or args.cursor is not None):
        parser.error("--game-id replaces seasons, --season-type, and --cursor")
    seasons = args.seasons or ([] if args.game_id else ["2000"])
    if args.season_type and args.endpoints != ["games"]:
        parser.error("--season-type applies to --endpoints games only")
    if args.cursor is not None and (len(seasons) != 1 or len(args.endpoints) != 1):
        parser.error("--cursor names a page of one endpoint for one season")

    api_key = os.environ.get("BALLDONTLIE_API_KEY", "")
    if not api_key:
        print("ERROR: BALLDONTLIE_API_KEY is missing.", file=sys.stderr)
        return 2

    for game_id in args.game_id:
        for endpoint in args.endpoints:
            if not _probe_game(game_id, endpoint, api_key, args.save_fixtures):
                return 1
    for season in seasons:
        for endpoint in args.endpoints:
            if not _probe(season, endpoint, api_key, args.save_fixtures, args.season_type, args.cursor):
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
