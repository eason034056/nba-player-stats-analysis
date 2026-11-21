"""
backfill_support.py - a BdlClient answered from recorded BALLDONTLIE pages.

Shared by the backfill walker and CLI tests. Each request is answered with a
recorded capture chosen by path, season type, and cursor; a request with no
recorded answer fails the test.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import fakeredis.aioredis
import httpx

from app.services.bdl_client import BdlClient

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
Route = tuple[str, str | None, str | None]


def capture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text())


def next_cursor(recorded: dict[str, Any]) -> str:
    return str(recorded["response"]["meta"]["next_cursor"])


def with_bad_season(recorded: dict[str, Any]) -> dict[str, Any]:
    """The capture with its first game moved to the season before, which the writer refuses."""
    bad = copy.deepcopy(recorded)
    game = bad["response"]["data"][0]
    game["season"] -= 1
    return bad


def season_2025_routes() -> dict[Route, dict[str, Any]]:
    """Every 2025-26 page a walk asks for. The page after a full page is the recorded empty page."""
    regular = capture("games__season2025_regular_page1.json")
    stats = capture("stats__season2025_page1.json")
    return {
        ("/v1/games", "regular", None): regular,
        ("/v1/games", "regular", next_cursor(regular)): capture("games__season1900_empty.json"),
        ("/v1/games", "playoffs", None): capture("games__season2025_playoffs_page1.json"),
        ("/v1/games", "playin", None): capture("games__season2025_playin_page1.json"),
        ("/v1/games", "ist", None): capture("games__season2025_ist_page1.json"),
        ("/v1/stats", None, None): stats,
        ("/v1/stats", None, next_cursor(stats)): capture("stats__season1900_empty.json"),
    }


def season_2000_routes() -> dict[Route, dict[str, Any]]:
    """A 2000-01 walk from the first recorded games and stats pages.

    The 2000 games page was recorded without ``season_type``; its 100 games
    are October and November regular-season games. The other types answer
    with the recorded empty page, so the season is one page of each.
    """
    regular = capture("games__season2000_page1.json")
    stats = capture("stats__season2000_page1.json")
    empty_games = capture("games__season1900_empty.json")
    return {
        ("/v1/games", "regular", None): regular,
        ("/v1/games", "regular", next_cursor(regular)): empty_games,
        ("/v1/games", "playoffs", None): empty_games,
        ("/v1/games", "playin", None): empty_games,
        ("/v1/games", "ist", None): empty_games,
        ("/v1/stats", None, None): stats,
        ("/v1/stats", None, next_cursor(stats)): capture("stats__season1900_empty.json"),
    }


class RecordedBdl:
    """Answers with the capture routed to ``(path, season_type, cursor)`` and records every request."""

    def __init__(self, routes: dict[Route, dict[str, Any]]) -> None:
        self.routes = routes
        self.seen: list[Route] = []
        self.seasons: set[tuple[str, ...]] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        route = (request.url.path, params.get("season_type"), params.get("cursor"))
        self.seen.append(route)
        self.seasons.add(tuple(params.get_list("seasons[]")))
        if route not in self.routes:
            raise AssertionError(f"no recorded answer for {route}")
        recorded = self.routes[route]
        return httpx.Response(recorded["status"], json=recorded["response"], headers=recorded["rate_headers"])


class RecordedSeasons:
    """One ``RecordedBdl`` per season, chosen by the request's ``seasons[]``."""

    def __init__(self, routes_by_season: dict[int, dict[Route, dict[str, Any]]]) -> None:
        self.by_season = {season: RecordedBdl(routes) for season, routes in routes_by_season.items()}
        self.seen: list[tuple[int, Route]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        season = int(request.url.params["seasons[]"])
        bdl = self.by_season[season]
        response = bdl(request)
        self.seen.append((season, bdl.seen[-1]))
        return response


class InstantClock:
    """A clock whose sleep moves time forward instead of waiting."""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def recorded_client(handler: RecordedBdl | RecordedSeasons) -> BdlClient:
    clock = InstantClock()
    return BdlClient(
        api_key="unit-test-backfill-key",
        redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
        rate_limit_per_min=600,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
    )
