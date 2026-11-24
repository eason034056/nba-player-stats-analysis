#!/usr/bin/env python3
"""Record BALLDONTLIE odds fixtures that are not in the tree yet.

The script calls BALLDONTLIE and writes the responses. It does not
invent a body. A 429 is saved only when a response is actually 429.
An empty ``/v1/players`` or an empty ``player_props`` body is saved
only when the response ``data`` array is empty.

Saved URLs have ``apiKey`` removed. Saved headers omit ``Authorization``.
``BALLDONTLIE_API_KEY`` is read from the environment and is never printed.

Usage:
    PYTHONPATH=backend python3 scripts/record_bdl_odds_fixtures.py
    PYTHONPATH=backend python3 scripts/record_bdl_odds_fixtures.py --from-fixtures

``--from-fixtures`` prints agreement stats from an already recorded
same-slate pair and does not need a key. It exits non-zero when the
shared props agree below 90 percent, or when no prop is shared.
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
_BDL_BASE = "https://api.balldontlie.io"
_PAIR_BUDGET_SECONDS = 150.0
_RATE_HEADER_PREFIXES = ("x-ratelimit-", "x-requests-")
_AGREEMENT_MIN = 0.90
_DEFAULT_SAME_SLATE = "backend/tests/fixtures/same_slate"


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


def _ensure_backend_path() -> None:
    """Let this script import the backend services."""
    backend = str(_REPO_ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)


def _unwrap(payload: object) -> dict:
    """Recorded wrapper or a raw JSON object. The body is not printed."""
    if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
        return payload["response"]
    if isinstance(payload, dict):
        return payload
    raise SystemExit("same-slate file is not an object")


def _names_from_pages(pages: list[dict]) -> dict[int, str]:
    """Player id to display name. The names are not printed."""
    _ensure_backend_path()
    from app.services.bdl_player_directory import bdl_player_name

    names: dict[int, str] = {}
    for page in pages:
        for player in page.get("data") or []:
            if isinstance(player, dict) and isinstance(player.get("id"), int):
                names[player["id"]] = bdl_player_name(player)
    return names


def _print_agreement(
    *,
    captured_at: str,
    bdl_lines: dict[tuple[str, str], float],
    odds_lines: dict[tuple[str, str], float],
) -> int:
    """Print agreement stats only. Return 0 at or above 90 percent.

    A player name is the first half of each consensus key and is not printed.
    No shared prop is a failure, the same as a rate below 90 percent.
    """
    shared = [key for key in bdl_lines if key in odds_lines]

    def measure(keys: list[tuple[str, str]]) -> tuple[int, int, float]:
        total = len(keys)
        if total == 0:
            return 0, 0, 0.0
        within = sum(
            1
            for player, market in keys
            if abs(bdl_lines[(player, market)] - odds_lines[(player, market)]) <= 0.5 + 1e-9
        )
        return total, within, within / total

    total, within, rate = measure(shared)
    passed = bool(shared) and rate >= _AGREEMENT_MIN
    lines = [
        f"capture={captured_at}",
        f"shared={total}",
        f"within_0.5={within}",
        f"percent={rate:.1%}",
        f"result={'pass' if passed else 'fail'}",
    ]
    markets = sorted({market for _player, market in shared})
    for market in markets:
        market_keys = [key for key in shared if key[1] == market]
        market_total, market_within, market_rate = measure(market_keys)
        lines.append(
            f"market={market} shared={market_total} within_0.5={market_within} percent={market_rate:.1%}"
        )
    print("\n".join(lines))
    return 0 if passed else 1


def _stats_from_bodies(
    *,
    captured_at: str,
    odds_body: dict,
    props_body: dict,
    games_body: dict,
    names: dict[int, str],
    meta: dict | None = None,
) -> int:
    """Adapt the props with the shipping rule and print the agreement."""
    _ensure_backend_path()
    from app.services.bdl_odds_provider import games_match
    from app.services.bdl_props_adapter import BdlPropsAdapter, consensus_lines

    meta = meta or {}
    commence = str(odds_body.get("commence_time") or meta.get("odds_api_commence_time") or "")
    game = next(
        (
            item
            for item in games_body.get("data") or []
            if isinstance(item, dict)
            and games_match(
                odds_home=str(odds_body.get("home_team") or ""),
                odds_away=str(odds_body.get("away_team") or ""),
                odds_commence=commence,
                bdl_game=item,
            )
        ),
        None,
    )
    if not isinstance(game, dict):
        return _print_agreement(captured_at=captured_at, bdl_lines={}, odds_lines={})
    tip_text = game.get("datetime") if isinstance(game.get("datetime"), str) else ""
    tip = datetime.fromisoformat(tip_text.replace("Z", "+00:00")) if tip_text else None
    props_rows = props_body.get("data") if isinstance(props_body.get("data"), list) else []
    books = BdlPropsAdapter().to_bookmakers(
        [row for row in props_rows if isinstance(row, dict)],
        names,
        game_datetime=tip,
    )
    odds_books = odds_body.get("bookmakers") if isinstance(odds_body.get("bookmakers"), list) else []
    return _print_agreement(
        captured_at=captured_at,
        bdl_lines=consensus_lines(books),
        odds_lines=consensus_lines([book for book in odds_books if isinstance(book, dict)]),
    )


def _read_json(path: Path) -> object:
    """Load one recorded file. A bad file exits without printing its text."""
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        raise SystemExit(f"same-slate file is unreadable: {path.name}") from None


def _stats_from_fixtures(directory: Path) -> int:
    """Print agreement for the first recorded pair in ``directory``."""
    if not directory.is_dir():
        raise SystemExit("same-slate directory is missing")
    metas = sorted(directory.glob("*__meta.json"))
    if not metas:
        raise SystemExit("same-slate directory has no recorded pair")
    meta_path = metas[0]
    meta = _read_json(meta_path)
    if not isinstance(meta, dict):
        raise SystemExit("same-slate meta file is not an object")
    prefix = meta_path.name[: -len("__meta.json")]
    odds_path = directory / f"{prefix}__odds_api_odds.json"
    props_path = directory / f"{prefix}__bdl_props.json"
    games_path = directory / f"{prefix}__bdl_games.json"
    players_paths = sorted(directory.glob(f"{prefix}__bdl_players*.json"))
    for path in (odds_path, props_path, games_path):
        if not path.exists():
            raise SystemExit(f"same-slate file missing: {path.name}")
    if not players_paths:
        raise SystemExit(f"same-slate players file missing for {prefix}")
    pages = []
    for path in players_paths:
        page = _read_json(path)
        pages.append(_unwrap(page))
    odds_body = _unwrap(_read_json(odds_path))
    props_body = _unwrap(_read_json(props_path))
    games_body = _unwrap(_read_json(games_path))
    captured_at = meta.get("captured_at") if isinstance(meta.get("captured_at"), str) else ""
    return _stats_from_bodies(
        captured_at=captured_at,
        odds_body=odds_body,
        props_body=props_body,
        games_body=games_body,
        names=_names_from_pages(pages),
        meta=meta,
    )


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
    """``--from-fixtures`` reads a recorded pair instead of calling the API.

    ``--bdl-only`` is accepted and records the same BALLDONTLIE fixtures
    as a bare run. ``--stats-only`` scores the recorded pair and writes nothing.
    """
    parser = argparse.ArgumentParser(description="Record BALLDONTLIE odds fixtures from live responses.")
    parser.add_argument(
        "--bdl-only",
        action="store_true",
        help="Record BALLDONTLIE fixtures. Requires BALLDONTLIE_API_KEY.",
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Print agreement stats from the recorded pair. Writes nothing.",
    )
    parser.add_argument(
        "--from-fixtures",
        nargs="?",
        const=_DEFAULT_SAME_SLATE,
        default=None,
        help=(
            "Print agreement stats from a recorded same-slate directory. "
            f"Default directory is {_DEFAULT_SAME_SLATE}. No key is required."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Record what BALLDONTLIE actually returns. Exit before writing a guessed body."""
    args = _parse_args(argv)
    if args.from_fixtures is not None or args.stats_only:
        raw = args.from_fixtures if args.from_fixtures is not None else _DEFAULT_SAME_SLATE
        directory = Path(raw)
        if not directory.is_absolute():
            directory = Path.cwd() / directory
        raise SystemExit(_stats_from_fixtures(directory))
    _load_env_file(_REPO_ROOT / ".env")
    _load_env_file(_REPO_ROOT / "backend" / ".env")
    bdl_key = os.environ.get("BALLDONTLIE_API_KEY", "").strip()
    if not bdl_key:
        raise SystemExit("BALLDONTLIE_API_KEY must be set")
    try:
        _record_empty_players(bdl_key)
        _record_empty_props(bdl_key)
    except _Http429 as exc:
        _save_429(exc.capture)
        raise SystemExit("recorded a 429 and stopped") from None


if __name__ == "__main__":
    main()
