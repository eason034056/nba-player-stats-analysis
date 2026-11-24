"""
test_bdl_client.py - BALLDONTLIE client against recorded captures.

No test in this module calls the network. Bodies and rate-limit headers
come from backend/tests/fixtures/bdl/, copied unchanged from the SPO-130a
captures. The live test is skipped unless RUN_INTEGRATION=1 and
BALLDONTLIE_API_KEY are both set.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import SecretStr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fakeredis.aioredis

from app.settings import Settings, settings
from app.services.bdl_client import (
    BdlApiError,
    BdlClient,
    BdlError,
    BdlRateLimitError,
    iter_pages,
)
from app.services.bdl_stats import normalize_stat_row

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
REPO_ROOT = Path(__file__).resolve().parents[2]
EXPLORE_SCRIPT = REPO_ROOT / "scripts" / "explore_balldontlie_api.py"
# One game per kind of gap in BALLDONTLIE's own data, captured by
# ``explore_bdl_backfill.py --game-id``; read by test_backfill_verify.py.
UPSTREAM_GAP_GAMES = (19865, 19052, 48851, 434, 1038278, 1038319, 1038379)

# Every capture in the tarball says 5. 1_800_000_000 is a later minute
# boundary, so a recorded reset (about 1_794_369_576) is already past and
# does not make the budget tests wait on the server window.
_MINUTE = 1_800_000_000.0


def _load(name: str) -> dict:
    """Load one capture. The file is ``{request, status, elapsed_s, rate_headers, response}``."""
    return json.loads((FIXTURE_DIR / name).read_text())


def _request_parts(capture: dict) -> tuple[str, dict[str, list[str]]]:
    """Path and decoded query of the URL that was actually sent."""
    parsed = urlparse(capture["request"])
    return parsed.path, parse_qs(parsed.query)


class ManualClock:
    """Clock whose sleep moves time forward instead of waiting.

    ``sleeps`` records every delay the client asked for. Tests assert on
    that list, so a 60 second backoff does not take 60 seconds.
    """

    def __init__(self, start: float) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _client(
    handler,
    clock: ManualClock,
    *,
    api_key: str = "unit-test-bdl-key-spo130a",
    rate_limit_per_min: int | None = 5,
    redis=None,
) -> BdlClient:
    """Client pointed at ``handler`` and an in-memory Redis."""
    if redis is None:
        redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return BdlClient(
        api_key=api_key,
        redis=redis,
        rate_limit_per_min=rate_limit_per_min,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
    )


def _json_response(capture: dict, headers: dict[str, str] | None = None, status: int | None = None):
    """Build a response whose JSON body is the recorded ``response`` object."""
    rate = dict(capture["rate_headers"])
    if headers:
        rate.update(headers)
    return httpx.Response(
        capture["status"] if status is None else status,
        json=capture["response"],
        headers=rate,
    )


def _recorded_429() -> httpx.Response:
    """429 whose body is the recorded text and whose headers are the recorded ones.

    The capture stores that text under ``response._raw`` because it is not
    a JSON object. The header ``x-ratelimit-reset`` is 1794370905.
    """
    capture = _load("lineups_18447393_2026-01-15_agents_429.json")
    raw = capture["response"]["_raw"]
    return httpx.Response(429, content=raw.encode(), headers=dict(capture["rate_headers"]))


# ---------------------------------------------------------------------------
# Fixtures and settings
# ---------------------------------------------------------------------------


def test_fixtures_match_recorded_paths_and_contain_no_key():
    """Each capture keeps its recorded URL, and no file holds the key."""
    expected = {
        "games_2026-11-10.json": "/v1/games",
        "games_2026-11-11.json": "/v1/games",
        "backend_players_batch45.json": "/v1/players",
        "injuries.json": "/v1/player_injuries",
        "props_live_21718080_OKC@POR_pregame.json": "/v2/odds/player_props",
        "props_live_21718081_WAS@IND_upcoming.json": "/v2/odds/player_props",
        "odds_2026-11-11.json": "/v2/odds",
        "projected_lineups_21718080.json": "/nba/v1/projected_lineups",
        "lineups_18447393_2026-01-15_agents_429.json": "/nba/v1/lineups",
        "games__season2000_page1.json": "/v1/games",
        "games__season1900_empty.json": "/v1/games",
        "stats__season2000_page1.json": "/v1/stats",
        "stats__season2025_page1.json": "/v1/stats",
        "stats__season1900_empty.json": "/v1/stats",
        "stats__seasonabc_http400.json": "/v1/stats",
        "games__season2025_regular_page1.json": "/v1/games",
        "games__season2025_playoffs_page1.json": "/v1/games",
        "games__season2025_bogus_http400.json": "/v1/games",
        "games__season2025_playin_page1.json": "/v1/games",
        "games__season2025_ist_page1.json": "/v1/games",
        "games__season2019_playin_page1.json": "/v1/games",
        "stats__season2000_cursor272160_page.json": "/v1/stats",
        "stats__season2025_cursor43451886_page.json": "/v1/stats",
        "stats__season2020_cursor6587519_page.json": "/v1/stats",
        "stats__season2020_cursor6603185_page.json": "/v1/stats",
        "stats__season2025_cursor24626559_page.json": "/v1/stats",
        "stats__season2026_page1.json": "/v1/stats",
        **{f"games__game{game}_record.json": f"/v1/games/{game}" for game in UPSTREAM_GAP_GAMES},
        **{f"stats__game{game}_page1.json": "/v1/stats" for game in UPSTREAM_GAP_GAMES},
    }
    found = {path.name for path in FIXTURE_DIR.glob("*.json")}
    # Other tickets may add captures in this directory. This set only has
    # to contain the SPO-130a and SPO-138a files.
    assert set(expected) <= found
    api_key = os.environ.get("BALLDONTLIE_API_KEY", "")
    for path in FIXTURE_DIR.glob("*.json"):
        text = path.read_text()
        if "Authorization" in text or "Bearer " in text:
            raise AssertionError(f"{path.name} contains an auth header")
        if api_key and api_key in text:
            raise AssertionError(f"{path.name} contains BALLDONTLIE_API_KEY")
    for name, path in expected.items():
        capture = json.loads((FIXTURE_DIR / name).read_text())
        assert set(capture) == {"request", "status", "elapsed_s", "rate_headers", "response"}
        assert urlparse(capture["request"]).path == path
        for header in ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"):
            assert header in capture["rate_headers"]


def test_settings_reads_balldontlie_env(monkeypatch):
    """The key and the per-minute limit are read from the environment."""
    assert Settings.model_fields["balldontlie_api_key"].default.get_secret_value() == ""
    assert Settings.model_fields["bdl_rate_limit_per_min"].default == 5
    monkeypatch.setenv("BALLDONTLIE_API_KEY", "from-env")
    monkeypatch.setenv("BDL_RATE_LIMIT_PER_MIN", "600")
    fresh = Settings()
    assert fresh.balldontlie_api_key.get_secret_value() == "from-env"
    assert "from-env" not in repr(fresh)
    assert fresh.bdl_rate_limit_per_min == 600


def test_explore_script_does_not_print_the_key():
    """The probe prints status and rate-limit numbers, not the key variable."""
    source = EXPLORE_SCRIPT.read_text()
    tree = ast.parse(source)
    printed: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            printed.extend(node.args)
    assert printed, "explore script should print probe results"
    for arg in printed:
        names = [child.id for child in ast.walk(arg) if isinstance(child, ast.Name)]
        assert "api_key" not in names


# ---------------------------------------------------------------------------
# URL and params
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_games_repeats_dates_and_returns_the_recorded_body():
    """``dates[]`` is repeated. The body is the recorded JSON, not a rewritten one."""
    capture = _load("games_2026-11-11.json")
    other = _load("games_2026-11-10.json")
    path, query = _request_parts(capture)
    assert path == "/v1/games"
    dates = [query["dates[]"][0], _request_parts(other)[1]["dates[]"][0]]
    seen: list[httpx.Request] = []
    clock = ManualClock(_MINUTE)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(capture)

    client = _client(handler, clock)
    try:
        body = await client.list_games(dates=dates)
    finally:
        await client.aclose()

    assert body == capture["response"]
    assert "next_cursor" not in body["meta"]
    request = seen[0]
    assert request.url.path == "/v1/games"
    assert request.url.params.get_list("dates[]") == dates
    assert request.url.params.get_list("per_page") == ["100"]
    assert request.url.params.get_list("cursor") == []
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_list_games_sends_cursor_when_asked():
    """A caller-supplied cursor is the ``cursor`` query parameter."""
    capture = _load("games_2026-11-11.json")
    injuries = _load("injuries.json")
    cursor = injuries["response"]["meta"]["next_cursor"]
    assert cursor == 15504814
    seen: list[httpx.Request] = []
    clock = ManualClock(_MINUTE)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(capture)

    client = _client(handler, clock)
    try:
        await client.list_games(dates=["2026-11-11"], cursor=cursor)
    finally:
        await client.aclose()

    assert seen[0].url.params.get_list("cursor") == [str(cursor)]


@pytest.mark.asyncio
async def test_list_players_repeats_player_ids_not_ids():
    """The recorded batch uses ``player_ids[]`` for every id, in that order."""
    capture = _load("backend_players_batch45.json")
    path, query = _request_parts(capture)
    assert path == "/v1/players"
    player_ids = [int(value) for value in query["player_ids[]"]]
    assert len(player_ids) == 45
    seen: list[httpx.Request] = []
    clock = ManualClock(_MINUTE)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(capture)

    client = _client(handler, clock)
    try:
        body = await client.list_players(player_ids=player_ids)
    finally:
        await client.aclose()

    assert body == capture["response"]
    assert len(body["data"]) == 45
    request = seen[0]
    assert request.url.path == "/v1/players"
    assert request.url.params.get_list("player_ids[]") == [str(value) for value in player_ids]
    assert request.url.params.get_list("ids[]") == []
    assert request.url.params.get_list("per_page") == ["100"]


@pytest.mark.asyncio
async def test_list_players_rejects_more_than_100_ids():
    """101 ids are a caller bug. No HTTP call is made and no budget slot is taken."""
    seen: list[httpx.Request] = []
    clock = ManualClock(_MINUTE)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise AssertionError("list_players must not call the API with more than 100 ids")

    client = _client(handler, clock)
    try:
        with pytest.raises(BdlError, match="100"):
            await client.list_players(player_ids=list(range(101)))
    finally:
        await client.aclose()
    assert seen == []


@pytest.mark.asyncio
async def test_list_player_injuries_uses_the_recorded_path():
    """``GET /v1/player_injuries`` returns the recorded page, including its cursor."""
    capture = _load("injuries.json")
    path, query = _request_parts(capture)
    assert path == "/v1/player_injuries"
    seen: list[httpx.Request] = []
    clock = ManualClock(_MINUTE)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(capture)

    client = _client(handler, clock)
    try:
        body = await client.list_player_injuries()
    finally:
        await client.aclose()

    assert body == capture["response"]
    assert body["meta"]["next_cursor"] == 15504814
    assert seen[0].url.path == path
    assert seen[0].url.params.get_list("per_page") == query["per_page"]
    assert seen[0].url.params.get_list("cursor") == []


@pytest.mark.asyncio
async def test_get_player_props_is_the_recorded_unpaginated_call():
    """Props are one response. The path and ``game_id`` come from the capture."""
    capture = _load("props_live_21718081_WAS@IND_upcoming.json")
    large = _load("props_live_21718080_OKC@POR_pregame.json")
    path, query = _request_parts(capture)
    large_path, large_query = _request_parts(large)
    assert path == large_path == "/v2/odds/player_props"
    assert "per_page" not in query
    assert "cursor" not in query
    game_id = int(query["game_id"][0])
    seen: list[httpx.Request] = []
    clock = ManualClock(_MINUTE)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(capture)

    client = _client(handler, clock)
    try:
        body = await client.get_player_props(game_id=game_id)
    finally:
        await client.aclose()

    assert body == capture["response"]
    assert body["meta"]["per_page"] == len(body["data"])
    assert "next_cursor" not in body["meta"]
    assert large["response"]["meta"]["per_page"] == len(large["response"]["data"])
    request = seen[0]
    assert request.url.path == "/v2/odds/player_props"
    assert request.url.params.get_list("game_id") == [str(game_id)]
    assert request.url.params.get_list("per_page") == []
    assert request.url.params.get_list("cursor") == []
    assert large_query["game_id"] == ["21718080"]


@pytest.mark.asyncio
async def test_get_game_returns_the_recorded_object_with_no_query():
    """``GET /v1/games/1038278`` matches games__game1038278_record.json."""
    capture = _load("games__game1038278_record.json")
    path, query = _request_parts(capture)
    assert path == "/v1/games/1038278"
    assert query == {}
    seen: list[httpx.Request] = []
    clock = ManualClock(_MINUTE)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(capture)

    client = _client(handler, clock)
    try:
        body = await client.get_game(game_id=1038278)
    finally:
        await client.aclose()

    assert body == capture["response"]
    assert isinstance(body["data"], dict)
    assert body["data"]["id"] == 1038278
    request = seen[0]
    assert request.url.path == "/v1/games/1038278"
    assert request.url.query == b""
    assert list(request.url.params.keys()) == []
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_get_game_rejects_a_bad_id_before_http():
    """Zero, a negative, a boolean, and a non-digit never reach the transport."""
    clock = ManualClock(_MINUTE)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise AssertionError("get_game sent HTTP")

    client = _client(handler, clock)
    try:
        for game_id in (0, -1, True, "abc", "0", ""):
            with pytest.raises(BdlError, match="positive game id"):
                await client.get_game(game_id=game_id)  # type: ignore[arg-type]
    finally:
        await client.aclose()

    assert seen == []
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_list_odds_uses_the_recorded_v2_path():
    """Game lines are ``GET /v2/odds``, the path in odds_2026-11-11.json."""
    capture = _load("odds_2026-11-11.json")
    path, query = _request_parts(capture)
    assert path == "/v2/odds"
    seen: list[httpx.Request] = []
    clock = ManualClock(_MINUTE)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(capture)

    client = _client(handler, clock)
    try:
        body = await client.list_odds(dates=query["dates[]"])
    finally:
        await client.aclose()

    assert body == capture["response"]
    assert seen[0].url.path == "/v2/odds"
    assert seen[0].url.params.get_list("dates[]") == query["dates[]"]
    assert seen[0].url.params.get_list("per_page") == query["per_page"]


@pytest.mark.asyncio
async def test_list_projected_lineups_uses_the_recorded_path():
    """Projected lineups are ``GET /nba/v1/projected_lineups`` with ``game_ids[]``."""
    capture = _load("projected_lineups_21718080.json")
    path, query = _request_parts(capture)
    assert path == "/nba/v1/projected_lineups"
    assert "per_page" not in query
    game_ids = [int(value) for value in query["game_ids[]"]]
    seen: list[httpx.Request] = []
    clock = ManualClock(_MINUTE)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(capture)

    client = _client(handler, clock)
    try:
        body = await client.list_projected_lineups(game_ids=game_ids)
    finally:
        await client.aclose()

    assert body == capture["response"]
    assert seen[0].url.path == path
    assert seen[0].url.params.get_list("game_ids[]") == query["game_ids[]"]
    assert seen[0].url.params.get_list("per_page") == []


@pytest.mark.asyncio
async def test_auth_header_comes_from_settings_and_is_not_logged(monkeypatch, caplog):
    """A default client unwraps the SecretStr into Authorization and does not log or repr it."""
    monkeypatch.setattr(
        settings, "balldontlie_api_key", SecretStr("from-settings-not-for-logs")
    )
    monkeypatch.setattr(settings, "bdl_rate_limit_per_min", 5)
    capture = _load("games_2026-11-11.json")
    seen: list[httpx.Request] = []
    clock = ManualClock(_MINUTE)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(capture)

    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = BdlClient(
        redis=redis,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
    )
    try:
        with caplog.at_level(logging.DEBUG):
            await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()

    assert seen[0].headers["authorization"] == "from-settings-not-for-logs"
    assert "from-settings-not-for-logs" not in caplog.text
    assert "from-settings-not-for-logs" not in repr(client)
    assert "authorization" not in caplog.text.lower()


@pytest.mark.asyncio
async def test_rate_status_reports_the_recorded_headers():
    """``rate_status`` is the last limit, remaining, and reset, as integers."""
    capture = _load("games_2026-11-11.json")
    clock = ManualClock(_MINUTE)
    client = _client(lambda request: _json_response(capture), clock)
    try:
        assert client.rate_status() == {"limit": None, "remaining": None, "reset": None}
        await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert client.rate_status() == {
        "limit": int(capture["rate_headers"]["x-ratelimit-limit"]),
        "remaining": int(capture["rate_headers"]["x-ratelimit-remaining"]),
        "reset": int(capture["rate_headers"]["x-ratelimit-reset"]),
    }


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_iter_pages_follows_the_recorded_injuries_cursor_then_stops():
    """Page 2 is requested with the recorded next_cursor.

    No second injuries page was captured. The follow-up response is the
    recorded games body, whose ``meta`` has ``per_page`` and no
    ``next_cursor``, so the iterator stops. That is a recorded last-page
    shape, not a typed injuries page.
    """
    injuries = _load("injuries.json")
    games = _load("games_2026-11-11.json")
    cursor = injuries["response"]["meta"]["next_cursor"]
    assert cursor == 15504814
    seen: list[httpx.Request] = []
    clock = ManualClock(_MINUTE)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.params.get("cursor") is None:
            return _json_response(injuries)
        return _json_response(games)

    client = _client(handler, clock)
    try:
        pages = [page async for page in iter_pages(client.list_player_injuries)]
    finally:
        await client.aclose()

    assert [page["meta"] for page in pages] == [
        injuries["response"]["meta"],
        games["response"]["meta"],
    ]
    assert len(seen) == 2
    assert seen[0].url.params.get_list("cursor") == []
    assert seen[1].url.params.get_list("cursor") == [str(cursor)]
    assert seen[1].url.path == "/v1/player_injuries"


@pytest.mark.asyncio
async def test_iter_pages_stops_when_the_recorded_page_has_no_next_cursor():
    """Games, players, and odds captures have no next_cursor, so they are one page."""
    capture = _load("odds_2026-11-11.json")
    assert "next_cursor" not in capture["response"]["meta"]
    clock = ManualClock(_MINUTE)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _json_response(capture)

    client = _client(handler, clock)
    try:
        pages = [page async for page in iter_pages(client.list_odds, dates=["2026-11-11"])]
    finally:
        await client.aclose()
    assert pages == [capture["response"]]
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_429_sleeps_until_the_recorded_reset_then_succeeds():
    """One 429 waits until the recorded reset, then the retry returns the games body."""
    denied = _load("lineups_18447393_2026-01-15_agents_429.json")
    reset = int(denied["rate_headers"]["x-ratelimit-reset"])
    assert reset == 1794370905
    games = _load("games_2026-11-11.json")
    clock = ManualClock(float(reset - 30))
    seen: list[tuple[float, int]] = []
    responses = [_recorded_429(), _json_response(games)]

    def handler(request: httpx.Request) -> httpx.Response:
        response = responses[len(seen)]
        seen.append((clock.now, response.status_code))
        return response

    client = _client(handler, clock)
    try:
        body = await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()

    assert body == games["response"]
    assert clock.sleeps == [30.0]
    assert seen == [(float(reset - 30), 429), (float(reset), 200)]


@pytest.mark.asyncio
async def test_three_429s_raise_bdl_rate_limit_error():
    """Three recorded 429s raise. There is no fourth call and no zero-length sleep."""
    denied = _load("lineups_18447393_2026-01-15_agents_429.json")
    reset = int(denied["rate_headers"]["x-ratelimit-reset"])
    clock = ManualClock(float(reset - 30))
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(429)
        return _recorded_429()

    client = _client(handler, clock)
    try:
        with pytest.raises(BdlRateLimitError) as raised:
            await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()

    assert len(seen) == 3
    assert raised.value.status_code == 429
    assert raised.value.reset == reset
    assert isinstance(raised.value, BdlError)
    assert not isinstance(raised.value, BdlApiError)
    assert clock.sleeps[0] == 30.0
    assert clock.sleeps == [30.0, 60.0]
    assert all(delay > 0 for delay in clock.sleeps)


@pytest.mark.asyncio
async def test_5xx_is_retried_with_bounded_backoff():
    """A 5xx waits 60 seconds when no reset header was recorded, then succeeds.

    No 5xx body was captured. The first response is an empty 503. The
    success body is the recorded games object.
    """
    games = _load("games_2026-11-11.json")
    clock = ManualClock(_MINUTE)
    seen: list[float] = []
    queue = [
        httpx.Response(503, content=b""),
        _json_response(games),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(clock.now)
        return queue[len(seen) - 1]

    client = _client(handler, clock)
    try:
        body = await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()

    assert body == games["response"]
    assert clock.sleeps == [60.0]
    assert seen == [_MINUTE, _MINUTE + 60.0]


@pytest.mark.asyncio
async def test_three_5xx_raise_bdl_api_error():
    """Three 503s raise BdlApiError with that status. The backoff stays at 60 seconds."""
    clock = ManualClock(_MINUTE)
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(503)
        return httpx.Response(503, content=b"")

    client = _client(handler, clock)
    try:
        with pytest.raises(BdlApiError) as raised:
            await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()

    assert len(seen) == 3
    assert raised.value.status_code == 503
    assert clock.sleeps == [60.0, 60.0]


# ---------------------------------------------------------------------------
# Shared per-minute budget
# ---------------------------------------------------------------------------


def _budget_handler(capture: dict, clock: ManualClock, headers: dict[str, str], seen: list[float]):
    """200 with a recorded body and whatever rate-limit headers the case needs."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(clock.now)
        return _json_response(capture, headers=headers)

    return handler


@pytest.mark.asyncio
async def test_shared_budget_blocks_the_sixth_call_at_limit_5():
    """Two clients on one Redis fill a 5/min window. The sixth call waits for the next minute."""
    capture = _load("games_2026-11-11.json")
    # Keep the recorded limit of 5. Remaining stays above 0 so the block is
    # the shared counter, not the "remaining is 0" pause.
    headers = dict(capture["rate_headers"])
    assert headers["x-ratelimit-limit"] == "5"
    headers["x-ratelimit-remaining"] = "4"
    clock = ManualClock(_MINUTE)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    seen: list[float] = []
    handler = _budget_handler(capture, clock, headers, seen)
    first = _client(handler, clock, rate_limit_per_min=5, redis=redis)
    second = _client(handler, clock, rate_limit_per_min=5, redis=redis)
    try:
        for _ in range(3):
            await first.list_games(dates=["2026-11-11"])
        for _ in range(2):
            await second.list_games(dates=["2026-11-11"])
        assert clock.sleeps == []
        assert seen == [_MINUTE] * 5
        await second.list_games(dates=["2026-11-11"])
    finally:
        await first.aclose()
        await second.aclose()

    assert clock.sleeps == [60.0]
    assert seen == [_MINUTE] * 5 + [_MINUTE + 60.0]


@pytest.mark.asyncio
async def test_budget_allows_600_calls_at_limit_600():
    """A 600/min limit lets 600 calls through in one minute and holds the 601st.

    No capture has ``x-ratelimit-limit: 600``; the trial key recorded 5.
    The body is still the recorded projected-lineups object. The header
    value is the paid tier the client has to honor.
    """
    capture = _load("projected_lineups_21718080.json")
    headers = {
        "x-ratelimit-limit": "600",
        "x-ratelimit-remaining": "599",
        "x-ratelimit-reset": str(int(_MINUTE) + 60),
    }
    clock = ManualClock(_MINUTE)
    seen: list[float] = []
    client = _client(
        _budget_handler(capture, clock, headers, seen),
        clock,
        rate_limit_per_min=600,
    )
    try:
        for _ in range(600):
            await client.list_projected_lineups(game_ids=[21718080])
        assert clock.sleeps == []
        assert seen == [_MINUTE] * 600
        await client.list_projected_lineups(game_ids=[21718080])
    finally:
        await client.aclose()

    assert clock.sleeps == [60.0]
    assert seen[-1] == _MINUTE + 60.0
    assert client.rate_status()["limit"] == 600


@pytest.mark.asyncio
async def test_observed_limit_header_raises_the_shared_budget():
    """A response that says 600 replaces the configured 5 for every client on this Redis."""
    capture = _load("projected_lineups_21718080.json")
    headers = {
        "x-ratelimit-limit": "600",
        "x-ratelimit-remaining": "599",
        "x-ratelimit-reset": str(int(_MINUTE) + 60),
    }
    clock = ManualClock(_MINUTE)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    seen: list[float] = []
    handler = _budget_handler(capture, clock, headers, seen)
    first = _client(handler, clock, rate_limit_per_min=5, redis=redis)
    second = _client(handler, clock, rate_limit_per_min=5, redis=redis)
    try:
        for _ in range(6):
            await first.list_projected_lineups(game_ids=[21718080])
        await second.list_projected_lineups(game_ids=[21718080])
    finally:
        await first.aclose()
        await second.aclose()

    assert clock.sleeps == []
    assert len(seen) == 7
    assert await redis.get("bdl:ratelimit:v1:observed_limit") == "600"


@pytest.mark.asyncio
async def test_observed_limit_header_overrides_a_higher_config():
    """A recorded limit of 5 wins over BDL_RATE_LIMIT_PER_MIN=600 after the first response."""
    capture = _load("games_2026-11-11.json")
    headers = dict(capture["rate_headers"])
    headers["x-ratelimit-remaining"] = "4"
    clock = ManualClock(_MINUTE)
    seen: list[float] = []
    client = _client(
        _budget_handler(capture, clock, headers, seen),
        clock,
        rate_limit_per_min=600,
    )
    try:
        for _ in range(5):
            await client.list_games(dates=["2026-11-11"])
        assert clock.sleeps == []
        await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()

    assert seen[:5] == [_MINUTE] * 5
    assert seen[5] == _MINUTE + 60.0
    assert clock.sleeps == [60.0]


@pytest.mark.asyncio
async def test_ceiling_holds_the_budget_below_the_recorded_600():
    """The backfill caps itself at 500/min so the GOAT key keeps 100/min for live jobs.

    The 2025-26 games capture recorded ``x-ratelimit-limit: 600``. That
    observed value raises the budget for everyone else; it must not raise
    a client that set a ceiling.
    """
    capture = _load("games__season2025_regular_page1.json")
    headers = dict(capture["rate_headers"])
    assert headers["x-ratelimit-limit"] == "600"
    clock = ManualClock(_MINUTE)
    seen: list[float] = []
    client = BdlClient(
        api_key="unit-test-bdl-key-spo130a",
        redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
        rate_limit_per_min=5,
        rate_limit_ceiling=500,
        transport=httpx.MockTransport(_budget_handler(capture, clock, headers, seen)),
        sleep=clock.sleep,
        clock=clock.time,
    )
    try:
        for _ in range(500):
            await client.list_games(seasons=[2025], season_type="regular")
        assert clock.sleeps == []
        await client.list_games(seasons=[2025], season_type="regular")
    finally:
        await client.aclose()

    assert clock.sleeps == [60.0]
    assert seen[499] == _MINUTE
    assert seen[500] == _MINUTE + 60.0


@pytest.mark.asyncio
async def test_ceiling_does_not_raise_a_lower_observed_limit():
    """A ceiling only lowers. A key that says 5/min still gets 5 calls a minute."""
    capture = _load("games_2026-11-11.json")
    headers = dict(capture["rate_headers"])
    assert headers["x-ratelimit-limit"] == "5"
    headers["x-ratelimit-remaining"] = "4"
    clock = ManualClock(_MINUTE)
    seen: list[float] = []
    client = BdlClient(
        api_key="unit-test-bdl-key-spo130a",
        redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
        rate_limit_per_min=5,
        rate_limit_ceiling=500,
        transport=httpx.MockTransport(_budget_handler(capture, clock, headers, seen)),
        sleep=clock.sleep,
        clock=clock.time,
    )
    try:
        for _ in range(6):
            await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()

    assert seen[:5] == [_MINUTE] * 5
    assert seen[5] == _MINUTE + 60.0


def test_ceiling_below_one_is_rejected():
    with pytest.raises(BdlError):
        BdlClient(
            api_key="unit-test-bdl-key-spo130a",
            redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
            rate_limit_ceiling=0,
        )


# ---------------------------------------------------------------------------
# Season walks (SPO-138a captures)
# ---------------------------------------------------------------------------


def _recording_client(capture: dict, seen: list[httpx.Request], clock: ManualClock) -> BdlClient:
    """Client that records each request and answers with ``capture``."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(capture)

    return _client(handler, clock)


@pytest.mark.asyncio
async def test_list_stats_sends_the_recorded_season_query():
    """``/v1/stats`` with ``seasons[]`` and ``per_page``, as in the 2000-01 capture."""
    capture = _load("stats__season2000_page1.json")
    path, query = _request_parts(capture)
    seen: list[httpx.Request] = []
    client = _recording_client(capture, seen, ManualClock(_MINUTE))
    try:
        body = await client.list_stats(seasons=[2000])
    finally:
        await client.aclose()

    assert body == capture["response"]
    request = seen[0]
    assert request.url.path == path == "/v1/stats"
    assert request.url.params.get_list("seasons[]") == query["seasons[]"] == ["2000"]
    assert request.url.params.get_list("per_page") == query["per_page"]
    assert request.url.params.get_list("cursor") == []


@pytest.mark.asyncio
async def test_list_stats_sends_cursor_when_asked():
    """The recorded ``meta.next_cursor`` goes back as ``cursor``."""
    capture = _load("stats__season2000_page1.json")
    cursor = capture["response"]["meta"]["next_cursor"]
    seen: list[httpx.Request] = []
    client = _recording_client(capture, seen, ManualClock(_MINUTE))
    try:
        await client.list_stats(seasons=[2000], cursor=cursor)
    finally:
        await client.aclose()

    assert seen[0].url.params.get_list("cursor") == [str(cursor)]


@pytest.mark.asyncio
async def test_list_stats_without_seasons_raises_before_a_request():
    """An empty list would send no filter at all."""
    seen: list[httpx.Request] = []
    client = _recording_client(_load("stats__season2000_page1.json"), seen, ManualClock(_MINUTE))
    try:
        with pytest.raises(BdlError):
            await client.list_stats(seasons=[])
    finally:
        await client.aclose()

    assert seen == []


@pytest.mark.asyncio
async def test_list_games_sends_the_recorded_season_query():
    """``list_games(seasons=...)`` sends ``seasons[]`` and no ``dates[]``."""
    capture = _load("games__season2000_page1.json")
    _, query = _request_parts(capture)
    seen: list[httpx.Request] = []
    client = _recording_client(capture, seen, ManualClock(_MINUTE))
    try:
        body = await client.list_games(seasons=[2000])
    finally:
        await client.aclose()

    assert body == capture["response"]
    assert seen[0].url.params.get_list("seasons[]") == query["seasons[]"] == ["2000"]
    assert seen[0].url.params.get_list("dates[]") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("season_type", ["regular", "playoffs", "playin", "ist"])
async def test_list_games_sends_the_recorded_season_type(season_type: str):
    """Q7: each season is walked once per type, and a game is stored with the type it was fetched under."""
    capture = _load(f"games__season2025_{season_type}_page1.json")
    _, query = _request_parts(capture)
    seen: list[httpx.Request] = []
    client = _recording_client(capture, seen, ManualClock(_MINUTE))
    try:
        body = await client.list_games(seasons=[2025], season_type=season_type)
    finally:
        await client.aclose()

    assert body == capture["response"]
    assert seen[0].url.params.get_list("season_type") == query["season_type"] == [season_type]
    assert seen[0].url.params.get_list("seasons[]") == query["seasons[]"] == ["2025"]


def test_recorded_season_types_split_on_postseason():
    """What the filter returned in 2025-26: Cup group games are regular, and only playoff games are postseason."""
    regular = _load("games__season2025_regular_page1.json")["response"]["data"]
    playoffs = _load("games__season2025_playoffs_page1.json")["response"]["data"]
    assert {game["postseason"] for game in regular} == {False}
    assert any(game["ist_stage"] for game in regular)
    assert {game["postseason"] for game in playoffs} == {True}
    assert min(game["date"] for game in playoffs) == "2026-04-18"


def test_recorded_postseason_flag_does_not_identify_play_in():
    """The 2019-20 bubble play-in is postseason and the 2025-26 play-in is not, so the flag cannot classify a game."""
    bubble = _load("games__season2019_playin_page1.json")["response"]["data"]
    recent = _load("games__season2025_playin_page1.json")["response"]["data"]
    assert {game["postseason"] for game in bubble} == {True}
    assert {game["postseason"] for game in recent} == {False}
    assert len(recent) == 6


def test_recorded_ist_is_only_the_cup_championship():
    """Cup group, quarterfinal, and semifinal games come back as regular. ``ist`` is the final alone."""
    games = _load("games__season2025_ist_page1.json")["response"]["data"]
    assert [game["ist_stage"] for game in games] == ["Championship"]


def test_recorded_unknown_season_type_is_a_400():
    """BALLDONTLIE checks the value instead of ignoring it, so a typo cannot pull every game type."""
    capture = _load("games__season2025_bogus_http400.json")
    assert capture["status"] == 400
    assert capture["response"] == {"errors": [{"param": "season_type", "error": "Invalid value"}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("season_type", ["preseason", "postseason", ""])
async def test_list_games_rejects_an_unrecorded_season_type_before_a_request(season_type: str):
    """Preseason is a BALLDONTLIE type that is never stored (Q7). Any other value costs no call and no budget slot."""
    seen: list[httpx.Request] = []
    client = _recording_client(_load("games__season2025_regular_page1.json"), seen, ManualClock(_MINUTE))
    try:
        with pytest.raises(BdlError):
            await client.list_games(seasons=[2025], season_type=season_type)
    finally:
        await client.aclose()

    assert seen == []


@pytest.mark.asyncio
async def test_list_games_without_dates_or_seasons_raises_before_a_request():
    """No filter at all is refused, as an empty ``dates`` list already was."""
    seen: list[httpx.Request] = []
    client = _recording_client(_load("games__season2000_page1.json"), seen, ManualClock(_MINUTE))
    try:
        with pytest.raises(BdlError):
            await client.list_games()
        with pytest.raises(BdlError):
            await client.list_games(dates=[], seasons=[])
    finally:
        await client.aclose()

    assert seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "method"),
    [("stats__season1900_empty.json", "list_stats"), ("games__season1900_empty.json", "list_games")],
)
async def test_empty_season_is_one_page_without_next_cursor(name: str, method: str):
    """A season with no rows is HTTP 200, ``data: []``, and no ``next_cursor`` key, so the walk stops."""
    capture = _load(name)
    assert capture["status"] == 200
    assert capture["response"] == {"data": [], "meta": {"per_page": 100}}
    seen: list[httpx.Request] = []
    client = _recording_client(capture, seen, ManualClock(_MINUTE))
    try:
        pages = [page async for page in iter_pages(getattr(client, method), seasons=[1900])]
    finally:
        await client.aclose()

    assert pages == [capture["response"]]
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_recorded_400_raises_api_error_without_retry():
    """The 400 body recorded for ``seasons[]=abc`` raises once, with no wait and no key."""
    capture = _load("stats__seasonabc_http400.json")
    assert capture["status"] == 400
    assert capture["response"]["errors"][0]["param"] == "seasons[0]"
    seen: list[httpx.Request] = []
    clock = ManualClock(_MINUTE)
    client = _recording_client(capture, seen, clock)
    try:
        with pytest.raises(BdlApiError) as raised:
            await client.list_stats(seasons=[2000])
    finally:
        await client.aclose()

    assert raised.value.status_code == 400
    assert "unit-test-bdl-key-spo130a" not in str(raised.value)
    assert len(seen) == 1
    assert clock.sleeps == []


# ---------------------------------------------------------------------------
# Live call. Not executed in the default suite.
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1" or not os.environ.get("BALLDONTLIE_API_KEY"),
    reason="Set RUN_INTEGRATION=1 and BALLDONTLIE_API_KEY to call BALLDONTLIE.",
)
async def test_live_list_games_smoke():
    """One live games call. Proves the host, the auth header, and a JSON object."""
    client = BdlClient()
    try:
        page = await client.list_games(dates=["2026-11-11"], per_page=25)
    finally:
        await client.aclose()
    assert isinstance(page.get("data"), list)
    assert isinstance(page.get("meta"), dict)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1" or not os.environ.get("BALLDONTLIE_API_KEY"),
    reason="Set RUN_INTEGRATION=1 and BALLDONTLIE_API_KEY to call BALLDONTLIE.",
)
async def test_live_list_stats_filters_by_season_and_normalizes():
    """One live 2000-01 stats page. The API applies ``seasons[]`` and every row normalizes.

    Redis is in memory: this checks the BALLDONTLIE contract, not a local Redis.
    """
    client = BdlClient(redis=fakeredis.aioredis.FakeRedis(decode_responses=True))
    try:
        page = await client.list_stats(seasons=[2000], per_page=25)
    finally:
        await client.aclose()

    rows = page["data"]
    assert len(rows) == 25
    assert isinstance(page["meta"].get("next_cursor"), int)
    assert {row["game"]["season"] for row in rows} == {2000}
    for row in rows:
        normalize_stat_row(row)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1" or not os.environ.get("BALLDONTLIE_API_KEY"),
    reason="Set RUN_INTEGRATION=1 and BALLDONTLIE_API_KEY to call BALLDONTLIE.",
)
async def test_live_list_games_filters_by_season_type():
    """One live 2025-26 playoffs page. The API applies ``season_type``: every game is postseason.

    Redis is in memory: this checks the BALLDONTLIE contract, not a local Redis.
    """
    client = BdlClient(redis=fakeredis.aioredis.FakeRedis(decode_responses=True))
    try:
        page = await client.list_games(seasons=[2025], season_type="playoffs", per_page=25)
    finally:
        await client.aclose()

    games = page["data"]
    assert len(games) == 25
    assert {game["season"] for game in games} == {2025}
    assert {game["postseason"] for game in games} == {True}


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1" or not os.environ.get("BALLDONTLIE_API_KEY"),
    reason="Set RUN_INTEGRATION=1 and BALLDONTLIE_API_KEY to call BALLDONTLIE.",
)
@pytest.mark.parametrize(("season_type", "stage_dates"), [
    ("playin", {"2026-04-14", "2026-04-15", "2026-04-17"}),
    ("ist", {"2025-12-16"}),
])
async def test_live_list_games_returns_the_play_in_and_the_cup_final(
    season_type: str, stage_dates: set[str]
):
    """The two types Q7 added. Each fits on one page: 6 play-in games, 1 Cup final."""
    client = BdlClient(redis=fakeredis.aioredis.FakeRedis(decode_responses=True))
    try:
        page = await client.list_games(seasons=[2025], season_type=season_type)
    finally:
        await client.aclose()

    assert {game["date"] for game in page["data"]} == stage_dates
    assert "next_cursor" not in page["meta"]
