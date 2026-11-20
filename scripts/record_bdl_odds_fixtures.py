#!/usr/bin/env python3
"""Record the BALLDONTLIE odds fixtures that are not in the tree yet.

The script calls the live APIs and writes the responses. It does not
invent a body. A 429 is saved only when a response is actually 429.
An empty ``/v1/players`` or an empty ``player_props`` body is saved
only when the response ``data`` array is empty.

The same-slate pair is one pregame game, captured within about two
minutes:

    GET /v4/sports/basketball_nba/events
    GET /v4/sports/basketball_nba/events/{id}/odds?markets=<SNAPSHOT_MARKETS>
    GET /v1/games?dates[]=
    GET /v2/odds/player_props?game_id=
    GET /v1/players?player_ids[]=

Games are paired by the Eastern date and the team codes, not by
commence time. The meta file stores the capture time and both
commence times.

Saved URLs have ``apiKey`` removed. Saved headers omit ``Authorization``.
The keys are read from the environment and are never printed.

Usage:
    PYTHONPATH=backend python3 scripts/record_bdl_odds_fixtures.py
    PYTHONPATH=backend python3 scripts/record_bdl_odds_fixtures.py --bdl-only

Without ``--bdl-only`` both ``BALLDONTLIE_API_KEY`` and ``ODDS_API_KEY``
are required, because the same-slate pair calls both providers.
``--bdl-only`` records only the BALLDONTLIE fixtures (an empty players
page, an empty props page, and a 429 only when one actually happens)
and reads ``BALLDONTLIE_API_KEY`` alone.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

# Identical to odds_snapshot_service.SNAPSHOT_MARKETS. The test compares them.
SNAPSHOT_MARKETS = (
    "player_points,"
    "player_rebounds,"
    "player_assists,"
    "player_threes,"
    "player_steals,"
    "player_frees_made,"
    "player_field_goals,"
    "player_points_rebounds_assists,"
    "player_rebounds_assists,"
    "player_points_rebounds,"
    "player_points_assists,"
    "player_double_double"
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BDL_DIR = _REPO_ROOT / "backend" / "tests" / "fixtures" / "bdl"
_SAME_SLATE_DIR = _REPO_ROOT / "backend" / "tests" / "fixtures" / "same_slate"
_ODDS_BASE = "https://api.the-odds-api.com"
_BDL_BASE = "https://api.balldontlie.io"
_PAIR_BUDGET_SECONDS = 150.0
_RATE_HEADER_PREFIXES = ("x-ratelimit-", "x-requests-")


def public_url(url: str) -> str:
    """Drop ``apiKey`` from a URL before it is written to disk."""
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() != "apikey"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def public_headers(headers: dict[str, str]) -> dict[str, str]:
    """Rate-limit headers only. ``Authorization`` is not a saved header."""
    saved: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in {"authorization", "cookie", "set-cookie"}:
            continue
        if lowered.startswith(_RATE_HEADER_PREFIXES):
            saved[lowered] = value
    return saved


def _redact(text: str, secrets: list[str]) -> str:
    """Replace any copy of a key with a fixed marker."""
    cleaned = text
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines without overriding the real environment."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


class _Http429(Exception):
    """A real 429. ``capture`` is the body that may be saved."""

    def __init__(self, capture: dict) -> None:
        super().__init__("429")
        self.capture = capture


def _request(
    url: str,
    *,
    headers: dict[str, str] | None,
    secrets: list[str],
) -> dict:
    """GET ``url`` and return a capture dict. The key is not in the dict."""
    started = time.monotonic()
    request = Request(url, headers=headers or {}, method="GET")
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read()
            status = response.status
            header_map = {key: value for key, value in response.headers.items()}
    except HTTPError as exc:
        raw = exc.read()
        status = exc.code
        header_map = {key: value for key, value in exc.headers.items()}
    except URLError as exc:
        reason = _redact(str(exc.reason), secrets)
        raise SystemExit(f"request failed: {reason}") from None

    elapsed = round(time.monotonic() - started, 2)
    text = raw.decode("utf-8", errors="replace")
    text = _redact(text, secrets)
    try:
        body: object = json.loads(text)
    except json.JSONDecodeError:
        body = {"_raw": text}
    capture = {
        "request": public_url(url),
        "status": status,
        "elapsed_s": elapsed,
        "rate_headers": public_headers(header_map),
        "response": body,
    }
    serialized = json.dumps(capture)
    for secret in secrets:
        if secret and secret in serialized:
            raise SystemExit("refusing to write a capture that still contains a key")
    if status == 429:
        raise _Http429(capture)
    if status != 200:
        raise SystemExit(f"unexpected status {status} for {urlsplit(url).path}")
    return capture


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {path.relative_to(_REPO_ROOT)} status={payload.get('status')}")


def _odds_url(path: str, query: list[tuple[str, str]], api_key: str) -> str:
    pairs = [("apiKey", api_key), *query]
    return f"{_ODDS_BASE}{path}?{urlencode(pairs)}"


def _bdl_url(path: str, query: list[tuple[str, str]]) -> str:
    if not query:
        return f"{_BDL_BASE}{path}"
    return f"{_BDL_BASE}{path}?{urlencode(query)}"


def _save_429(capture: dict) -> None:
    """Persist the 429 that just happened. No other 429 file is written."""
    path = _BDL_DIR / "player_props_429.json"
    if "player_props" not in str(capture.get("request")):
        path = _BDL_DIR / "bdl_http_429.json"
    _write(path, capture)


def _pair_prefix(slate_date: str, away_code: str, home_code: str) -> str:
    return f"{slate_date}_{away_code}@{home_code}"


def _record_same_slate(bdl_key: str, odds_key: str) -> None:
    """One pregame game from both providers, back to back."""
    sys.path.insert(0, str(_REPO_ROOT / "backend"))
    from app.services.bdl_odds_provider import games_match, slate_date_et, team_code

    secrets = [bdl_key, odds_key]
    started = time.monotonic()
    events_capture = _request(
        _odds_url("/v4/sports/basketball_nba/events", [], odds_key),
        headers=None,
        secrets=secrets,
    )
    events = events_capture["response"]
    if not isinstance(events, list):
        raise SystemExit("odds events response was not a list")
    now = datetime.now(timezone.utc)
    future = []
    for event in events:
        if not isinstance(event, dict):
            continue
        commence = event.get("commence_time")
        if not isinstance(commence, str):
            continue
        moment = datetime.fromisoformat(commence.replace("Z", "+00:00"))
        if moment > now:
            future.append(event)
    future.sort(key=lambda event: str(event.get("commence_time")))
    if not future:
        raise SystemExit("no future Odds API event to pair")
    dates: list[str] = []
    for event in future:
        slate = slate_date_et(str(event.get("commence_time")))
        if slate and slate not in dates:
            dates.append(slate)
        if len(dates) == 2:
            break
    games_capture = _request(
        _bdl_url("/v1/games", [("dates[]", date) for date in dates] + [("per_page", "100")]),
        headers={"Authorization": bdl_key},
        secrets=secrets,
    )
    games = games_capture["response"].get("data") if isinstance(games_capture["response"], dict) else None
    if not isinstance(games, list):
        raise SystemExit("games response had no data list")

    matched_event = None
    matched_game = None
    for event in future:
        for game in games:
            if not isinstance(game, dict):
                continue
            if game.get("status_state") != "scheduled":
                continue
            if games_match(
                odds_home=str(event.get("home_team") or ""),
                odds_away=str(event.get("away_team") or ""),
                odds_commence=str(event.get("commence_time") or ""),
                bdl_game=game,
            ):
                matched_event = event
                matched_game = game
                break
        if matched_event is not None:
            break
    if matched_event is None or matched_game is None:
        raise SystemExit("no pregame game matched on ET date and team codes")

    event_id = str(matched_event["id"])
    odds_capture = _request(
        _odds_url(
            f"/v4/sports/basketball_nba/events/{event_id}/odds",
            [
                ("regions", "us"),
                ("markets", SNAPSHOT_MARKETS),
                ("oddsFormat", "american"),
            ],
            odds_key,
        ),
        headers=None,
        secrets=secrets,
    )
    props_capture = _request(
        _bdl_url("/v2/odds/player_props", [("game_id", str(matched_game["id"]))]),
        headers={"Authorization": bdl_key},
        secrets=secrets,
    )
    props_rows = []
    if isinstance(props_capture["response"], dict):
        data = props_capture["response"].get("data")
        if isinstance(data, list):
            props_rows = data
    player_ids = []
    seen: set[int] = set()
    for row in props_rows:
        if isinstance(row, dict) and isinstance(row.get("player_id"), int) and row["player_id"] not in seen:
            seen.add(row["player_id"])
            player_ids.append(row["player_id"])
    player_captures: list[dict] = []
    for start in range(0, len(player_ids), 100):
        batch = player_ids[start : start + 100]
        query = [("player_ids[]", str(player_id)) for player_id in batch]
        query.append(("per_page", "100"))
        player_captures.append(
            _request(
                _bdl_url("/v1/players", query),
                headers={"Authorization": bdl_key},
                secrets=secrets,
            )
        )
    elapsed = time.monotonic() - started
    if elapsed > _PAIR_BUDGET_SECONDS:
        raise SystemExit(
            f"same-slate capture took {elapsed:.0f}s, which is past {_PAIR_BUDGET_SECONDS:.0f}s; not saved"
        )

    home = matched_game.get("home_team") if isinstance(matched_game.get("home_team"), dict) else {}
    away = matched_game.get("visitor_team") if isinstance(matched_game.get("visitor_team"), dict) else {}
    away_code = team_code(str(away.get("full_name") or ""), str(away.get("abbreviation") or ""))
    home_code = team_code(str(home.get("full_name") or ""), str(home.get("abbreviation") or ""))
    slate = str(matched_game.get("date") or slate_date_et(str(matched_event.get("commence_time"))))
    prefix = _pair_prefix(slate, away_code, home_code)
    _SAME_SLATE_DIR.mkdir(parents=True, exist_ok=True)
    _write(_SAME_SLATE_DIR / f"{prefix}__odds_api_events.json", events_capture)
    _write(_SAME_SLATE_DIR / f"{prefix}__odds_api_odds.json", odds_capture)
    _write(_SAME_SLATE_DIR / f"{prefix}__bdl_games.json", games_capture)
    _write(_SAME_SLATE_DIR / f"{prefix}__bdl_props.json", props_capture)
    for index, capture in enumerate(player_captures, start=1):
        suffix = "__bdl_players.json" if len(player_captures) == 1 else f"__bdl_players_{index}.json"
        _write(_SAME_SLATE_DIR / f"{prefix}{suffix}", capture)
    meta = {
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "odds_api_commence_time": matched_event.get("commence_time"),
        "bdl_commence_time": matched_game.get("datetime"),
        "slate_date": slate,
        "away_code": away_code,
        "home_code": home_code,
        "elapsed_seconds": round(elapsed, 2),
    }
    meta_path = _SAME_SLATE_DIR / f"{prefix}__meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {meta_path.relative_to(_REPO_ROOT)} elapsed={elapsed:.1f}s")


def _record_empty_players(bdl_key: str) -> None:
    """Save ``/v1/players`` only when the live ``data`` array is empty."""
    capture = _request(
        _bdl_url("/v1/players", [("player_ids[]", "0"), ("per_page", "100")]),
        headers={"Authorization": bdl_key},
        secrets=[bdl_key],
    )
    data = capture["response"].get("data") if isinstance(capture["response"], dict) else None
    if data == []:
        _write(_BDL_DIR / "players_empty.json", capture)
        return
    print("empty /v1/players was not returned; not writing players_empty.json")


def _record_empty_props(bdl_key: str) -> None:
    """Save ``player_props`` only when some future game has an empty ``data`` list."""
    day = (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat()
    games = _request(
        _bdl_url("/v1/games", [("dates[]", day), ("per_page", "100")]),
        headers={"Authorization": bdl_key},
        secrets=[bdl_key],
    )
    data = games["response"].get("data") if isinstance(games["response"], dict) else None
    if not isinstance(data, list) or not data:
        print(f"no games on {day}; not writing props_empty.json")
        return
    for game in data[:3]:
        if not isinstance(game, dict) or not isinstance(game.get("id"), int):
            continue
        capture = _request(
            _bdl_url("/v2/odds/player_props", [("game_id", str(game["id"]))]),
            headers={"Authorization": bdl_key},
            secrets=[bdl_key],
        )
        rows = capture["response"].get("data") if isinstance(capture["response"], dict) else None
        if rows == []:
            _write(_BDL_DIR / "props_empty.json", capture)
            return
    print("no empty player_props body was returned; not writing props_empty.json")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """``--bdl-only`` skips The Odds API and the same-slate pair."""
    parser = argparse.ArgumentParser(description="Record BALLDONTLIE odds fixtures from live responses.")
    parser.add_argument(
        "--bdl-only",
        action="store_true",
        help="Record only BALLDONTLIE fixtures. Requires BALLDONTLIE_API_KEY.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Record what the live APIs actually return. Exit before writing a guessed body."""
    args = _parse_args(argv)
    _load_env_file(_REPO_ROOT / ".env")
    _load_env_file(_REPO_ROOT / "backend" / ".env")
    bdl_key = os.environ.get("BALLDONTLIE_API_KEY", "").strip()
    odds_key = os.environ.get("ODDS_API_KEY", "").strip()
    if args.bdl_only:
        if not bdl_key:
            raise SystemExit("BALLDONTLIE_API_KEY must be set")
    elif not bdl_key or not odds_key:
        raise SystemExit("BALLDONTLIE_API_KEY and ODDS_API_KEY must both be set")
    try:
        if not args.bdl_only:
            _record_same_slate(bdl_key, odds_key)
        _record_empty_players(bdl_key)
        _record_empty_props(bdl_key)
    except _Http429 as exc:
        _save_429(exc.capture)
        raise SystemExit("recorded a 429 and stopped") from None


if __name__ == "__main__":
    main()
