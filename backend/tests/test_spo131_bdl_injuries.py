"""SPO-131 — NBA injuries from the recorded BALLDONTLIE fixtures.

No test in this module calls BALLDONTLIE, ESPN, or CBS. The injury page
and the standings file are the recorded responses copied under
``tests/fixtures/bdl/``. A terminal page used to stop pagination has no
player rows; it only carries the ``next_cursor`` shape the client
returns when a page is the last one.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import socket
import sys
from datetime import datetime, timedelta, timezone

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_BACKEND)
sys.path.insert(0, _BACKEND)
sys.path.insert(0, os.path.join(_REPO, "scripts", "agents"))
sys.path.insert(0, os.path.join(_REPO, "nba_lineup_rag"))

from app.services.cache import CacheService  # noqa: E402
from app.services.lineup_source_support import TEAM_ALIASES  # noqa: E402
from app.services import nba_injuries  # noqa: E402
from app.services.nba_injuries import (  # noqa: E402
    NBA_INJURIES_CACHE_KEY,
    NBA_INJURIES_CACHE_TTL_SECONDS,
    get_cached_nba_injuries,
    normalize_bdl_injuries,
    refresh_nba_injuries,
    team_id_to_code_from_standings,
)
from app.settings import Settings, settings  # noqa: E402
from src.config import NBA_TEAMS  # noqa: E402

_FIXTURE_DIR = os.path.join(_BACKEND, "tests", "fixtures", "bdl")
_INJURY_PATH = os.path.join(_FIXTURE_DIR, "player_injuries__page1.json")
_STANDINGS_PATH = os.path.join(_FIXTURE_DIR, "standings_2026.json")

_SCORING_STATUSES = {"Out", "Questionable", "Day-To-Day", "Probable", "Healthy"}
_ENTRY_KEYS = {
    "player",
    "bdl_player_id",
    "team",
    "position",
    "status",
    "raw_status",
    "injury",
    "return_date",
    "source",
    "fetched_at",
}
_FETCHED_AT = "2026-11-11T04:00:00+00:00"
_DUMMY_KEY = "dummy"


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


INJURY_PAGE = _load(_INJURY_PATH)
STANDINGS = _load(_STANDINGS_PATH)


class FakeRedis:
    """Async Redis stand-in. Same surface as the cache unit-test fake."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[dict] = []

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        self.set_calls.append({"key": key, "value": value, "ex": ex, "nx": nx})
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def close(self) -> None:
        return None


class PageClient:
    """Serves a fixed list of page bodies. ``fail_at`` raises instead."""

    def __init__(self, pages: list[dict], fail_at: int | None = None) -> None:
        self.pages = pages
        self.fail_at = fail_at
        self.calls: list[dict] = []

    async def list_player_injuries(self, *, cursor: int | None = None, per_page: int = 100) -> dict:
        index = len(self.calls)
        self.calls.append({"cursor": cursor, "per_page": per_page})
        if self.fail_at is not None and index == self.fail_at:
            raise RuntimeError("player_injuries page failed")
        return self.pages[index]


class _ScrapedInjury:
    def __init__(self, team: str, player_name: str, position: str, status: str, injury: str) -> None:
        self.team = team
        self.player_name = player_name
        self.position = position
        self.status = status
        self.injury = injury


class _ScrapingFetcher:
    calls = 0

    def fetch_all(self) -> dict:
        _ScrapingFetcher.calls += 1
        return {
            "espn": [
                _ScrapedInjury("PHI", "Joel Embiid", "C", "Out", "knee"),
                _ScrapedInjury("NYL", "Breanna Stewart", "F", "Out", "foot"),
            ]
        }


def _cache() -> tuple[CacheService, FakeRedis]:
    fake = FakeRedis()
    service = CacheService()
    service._client = fake
    return service, fake


def _terminal(meta: dict) -> dict:
    """Last page. No player rows; only the cursor shape under test."""
    return {"data": [], "meta": meta}


def _guard_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if the process opens a TCP connection."""

    class _GuardedSocket(socket.socket):
        def connect(self, address):  # type: ignore[override]
            raise AssertionError(f"network connect {address!r}")

        def connect_ex(self, address):  # type: ignore[override]
            raise AssertionError(f"network connect_ex {address!r}")

    monkeypatch.setattr(socket, "socket", _GuardedSocket)

    def _blocked_create_connection(*_args, **_kwargs):
        raise AssertionError("network create_connection")

    monkeypatch.setattr(socket, "create_connection", _blocked_create_connection)


def _use_cache(monkeypatch: pytest.MonkeyPatch, service: CacheService) -> None:
    def _open() -> CacheService:
        opened = CacheService()
        opened._client = service._client
        return opened

    monkeypatch.setattr(nba_injuries, "open_injury_cache", _open)


def _set_dummy_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BALLDONTLIE_API_KEY", _DUMMY_KEY)
    monkeypatch.setattr(settings, "balldontlie_api_key", _DUMMY_KEY)


def _clear_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BALLDONTLIE_API_KEY", raising=False)
    monkeypatch.setattr(settings, "balldontlie_api_key", "")


def _install_injuries_module(monkeypatch: pytest.MonkeyPatch, fetcher_cls: type) -> None:
    """Register a fetcher without importing the RAG package.

    ``src.sources`` imports feedparser. The product-agent tests must not
    need that dependency, and they must not hit ESPN or CBS.
    """
    import types

    sources = types.ModuleType("src.sources")
    sources.__path__ = []
    injuries = types.ModuleType("src.sources.injuries_pages")
    injuries.InjuriesPageFetcher = fetcher_cls
    sources.injuries_pages = injuries
    monkeypatch.setitem(sys.modules, "src.sources", sources)
    monkeypatch.setitem(sys.modules, "src.sources.injuries_pages", injuries)


def _patch_scraper(monkeypatch: pytest.MonkeyPatch) -> None:
    _ScrapingFetcher.calls = 0
    _install_injuries_module(monkeypatch, _ScrapingFetcher)


def _forbid_scraper(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Forbidden:
        def fetch_all(self):
            raise AssertionError("ESPN/CBS scraper called on the NBA cache path")

    _install_injuries_module(monkeypatch, _Forbidden)


def _forbid_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _refresh(*_args, **_kwargs):
        raise AssertionError("refresh_nba_injuries called from the request path")

    monkeypatch.setattr(nba_injuries, "refresh_nba_injuries", _refresh)


# ---------------------------------------------------------------------------
# Normalizer and the standings map
# ---------------------------------------------------------------------------


def test_standings_codes_match_nba_tables() -> None:
    """The recorded standings abbreviations are our NBA codes.

    The map is built from the fixture. It is not a hand-typed table.
    """
    mapping = team_id_to_code_from_standings(STANDINGS)
    codes = set(mapping.values())
    assert len(mapping) == 30
    assert len(codes) == 30
    assert codes == set(NBA_TEAMS)
    assert codes == set(TEAM_ALIASES)


def test_normalize_drops_available_and_maps_doubtful() -> None:
    rows = INJURY_PAGE["data"]
    mapping = team_id_to_code_from_standings(STANDINGS)
    entries = normalize_bdl_injuries(rows, mapping, fetched_at=_FETCHED_AT)

    available = [row for row in rows if row["status"] == "Available"]
    assert len(available) == 5
    assert len(entries) == len(rows) - 5
    assert not any(entry["status"] == "Available" or entry["raw_status"] == "Available" for entry in entries)

    doubtful_rows = [row for row in rows if row["status"] == "Doubtful"]
    doubtful = [entry for entry in entries if entry["raw_status"] == "Doubtful"]
    assert len(doubtful_rows) == 2
    assert len(doubtful) == 2
    assert {entry["status"] for entry in doubtful} == {"Questionable"}

    statuses = {entry["status"] for entry in entries}
    assert statuses <= _SCORING_STATUSES
    assert "Doubtful" not in statuses
    assert statuses == {"Out", "Questionable", "Day-To-Day", "Probable"}

    sample = next(row for row in rows if row["status"] == "Out")
    normalized = next(entry for entry in entries if entry["bdl_player_id"] == sample["player"]["id"])
    player = sample["player"]
    assert set(normalized) == _ENTRY_KEYS
    assert normalized["player"] == f"{player['first_name']} {player['last_name']}".strip()
    assert normalized["team"] == mapping[player["team_id"]]
    assert normalized["team"] in NBA_TEAMS
    assert normalized["position"] == player["position"]
    assert normalized["status"] == sample["status"]
    assert normalized["raw_status"] == sample["status"]
    assert normalized["injury"] == sample["description"]
    assert normalized["return_date"] == sample["return_date"]
    assert normalized["source"] == "balldontlie"
    assert normalized["fetched_at"] == _FETCHED_AT


def test_unknown_team_id_is_logged_and_dropped(caplog: pytest.LogCaptureFixture) -> None:
    rows = INJURY_PAGE["data"]
    with caplog.at_level(logging.WARNING):
        entries = normalize_bdl_injuries(rows, {})
    assert entries == []
    assert "unknown team_id" in caplog.text


# ---------------------------------------------------------------------------
# Refresh, failure, stale, missing
# ---------------------------------------------------------------------------


def _old_snapshot() -> dict:
    return {
        "fetched_at": "2026-11-10T00:00:00+00:00",
        "entries": [{"player": "Keep Me", "status": "Out", "source": "balldontlie"}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal_meta",
    [
        {"next_cursor": None, "per_page": 100},
        {"per_page": 100},
    ],
)
async def test_refresh_reads_fixture_then_stops(terminal_meta: dict) -> None:
    service, fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    client = PageClient([INJURY_PAGE, _terminal(terminal_meta)])

    payload = await refresh_nba_injuries(client, service, mapping)

    assert [call["cursor"] for call in client.calls] == [None, INJURY_PAGE["meta"]["next_cursor"]]
    assert [call["per_page"] for call in client.calls] == [100, 100]
    assert payload is not None
    assert payload["entries"] == normalize_bdl_injuries(
        INJURY_PAGE["data"],
        mapping,
        fetched_at=payload["fetched_at"],
    )
    assert all(entry["fetched_at"] == payload["fetched_at"] for entry in payload["entries"])
    stored = await service.get(NBA_INJURIES_CACHE_KEY)
    assert stored == payload
    refresh_writes = [call for call in fake.set_calls if call["key"] == NBA_INJURIES_CACHE_KEY]
    assert refresh_writes[-1]["ex"] == NBA_INJURIES_CACHE_TTL_SECONDS == 6 * 60 * 60


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", [0, 1])
async def test_page_failure_keeps_the_previous_cache(fail_at: int) -> None:
    service, fake = _cache()
    previous = _old_snapshot()
    await service.set(NBA_INJURIES_CACHE_KEY, previous, ttl=100)
    writes_after_seed = len(fake.set_calls)
    client = PageClient([INJURY_PAGE, _terminal({"next_cursor": None, "per_page": 100})], fail_at=fail_at)

    result = await refresh_nba_injuries(client, service, team_id_to_code_from_standings(STANDINGS))

    assert result is None
    assert await service.get(NBA_INJURIES_CACHE_KEY) == previous
    assert len(fake.set_calls) == writes_after_seed
    stored = await service.get(NBA_INJURIES_CACHE_KEY)
    assert stored["entries"][0]["player"] == "Keep Me"
    assert stored["entries"] != []


@pytest.mark.asyncio
async def test_cache_write_failure_keeps_the_previous_body() -> None:
    previous = _old_snapshot()

    class _Refuse:
        def __init__(self) -> None:
            self.body = copy.deepcopy(previous)

        async def set(self, key: str, value: dict, ttl: int) -> bool:
            return False

    cache = _Refuse()
    client = PageClient([INJURY_PAGE, _terminal({"next_cursor": None})])
    result = await refresh_nba_injuries(client, cache, team_id_to_code_from_standings(STANDINGS))
    assert result is None
    assert cache.body == previous


def test_stale_boundary_is_older_than_six_hours() -> None:
    now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    exactly = (now - timedelta(seconds=NBA_INJURIES_CACHE_TTL_SECONDS)).isoformat()
    older = (now - timedelta(seconds=NBA_INJURIES_CACHE_TTL_SECONDS, microseconds=1)).isoformat()
    assert nba_injuries._is_stale(exactly, now=now) is False
    assert nba_injuries._is_stale(older, now=now) is True
    assert nba_injuries._is_stale(None, now=now) is True


@pytest.mark.asyncio
async def test_get_cached_missing_and_stale_and_team_filter() -> None:
    service, _fake = _cache()
    missing = await get_cached_nba_injuries(cache=service)
    assert missing == {"entries": [], "fetched_at": None, "stale": True}

    mapping = team_id_to_code_from_standings(STANDINGS)
    fresh_at = datetime.now(timezone.utc).isoformat()
    entries = normalize_bdl_injuries(INJURY_PAGE["data"], mapping, fetched_at=fresh_at)
    await service.set(
        NBA_INJURIES_CACHE_KEY,
        {"fetched_at": fresh_at, "entries": entries},
        ttl=NBA_INJURIES_CACHE_TTL_SECONDS,
    )
    present_ids = {row["player"]["team_id"] for row in INJURY_PAGE["data"]}
    absent_code = next(
        team["team"]["abbreviation"]
        for team in STANDINGS["data"]
        if team["team"]["id"] not in present_ids
    )
    present_code = entries[0]["team"]
    fresh = await get_cached_nba_injuries(present_code, cache=service)
    assert fresh["stale"] is False
    assert fresh["fetched_at"] == fresh_at
    assert fresh["entries"]
    assert {row["team"] for row in fresh["entries"]} == {present_code}

    empty_team = await get_cached_nba_injuries(absent_code, cache=service)
    assert empty_team["stale"] is False
    assert empty_team["entries"] == []

    stale_at = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    await service.set(
        NBA_INJURIES_CACHE_KEY,
        {"fetched_at": stale_at, "entries": entries},
        ttl=NBA_INJURIES_CACHE_TTL_SECONDS,
    )
    stale = await get_cached_nba_injuries(cache=service)
    assert stale["stale"] is True
    assert stale["fetched_at"] == stale_at
    assert stale["entries"]


def test_settings_expose_the_refresh_interval_and_key() -> None:
    assert Settings.model_fields["balldontlie_api_key"].default == ""
    assert Settings.model_fields["nba_injuries_refresh_minutes"].default == 15


# ---------------------------------------------------------------------------
# Product-agent read path
# ---------------------------------------------------------------------------


def _historical():
    import tools.historical as historical

    return historical


def test_official_report_for_one_team_reads_the_cache_only(monkeypatch: pytest.MonkeyPatch) -> None:
    historical = _historical()
    service, _fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    client = PageClient([INJURY_PAGE, _terminal({"next_cursor": None, "per_page": 100})])
    payload = asyncio.run(refresh_nba_injuries(client, service, mapping))
    assert payload is not None

    _set_dummy_key(monkeypatch)
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _forbid_refresh(monkeypatch)
    _guard_network(monkeypatch)

    team_code = payload["entries"][0]["team"]
    expected = [row for row in payload["entries"] if row["team"] == team_code]
    result = asyncio.run(historical.get_official_injury_report(team_code, league="nba"))

    assert result["signal"] == "caution"
    assert result["details"]["team_code"] == team_code
    assert result["details"]["injuries"] == expected
    assert result["details"]["injuries"][0]["source"] == "balldontlie"
    assert "bdl_player_id" in result["details"]["injuries"][0]
    assert "raw_status" in result["details"]["injuries"][0]
    assert "reason" not in result["details"]


def test_fresh_team_with_no_rows_is_not_reported_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    historical = _historical()
    service, _fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    payload = asyncio.run(
        refresh_nba_injuries(
            PageClient([INJURY_PAGE, _terminal({"per_page": 100})]),
            service,
            mapping,
        )
    )
    assert payload is not None
    present_ids = {row["player"]["team_id"] for row in INJURY_PAGE["data"]}
    absent_code = next(
        team["team"]["abbreviation"]
        for team in STANDINGS["data"]
        if team["team"]["id"] not in present_ids
    )
    _set_dummy_key(monkeypatch)
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)

    result = asyncio.run(historical.get_official_injury_report(absent_code, league="nba"))
    assert result["signal"] == "neutral"
    assert result["details"]["injuries"] == []
    assert "reason" not in result["details"]


def test_missing_cache_is_caution_not_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    historical = _historical()
    service, _fake = _cache()
    _set_dummy_key(monkeypatch)
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)

    report = asyncio.run(historical.get_official_injury_report("PHI", league="nba"))
    assert report["signal"] == "caution"
    assert report["details"]["reason"] == "injury data unavailable"
    assert report["details"]["injuries"] == []
    assert report["details"]["stale"] is True

    availability = historical.get_availability_context("Jaren Jackson Jr", league="nba")
    assert availability["signal"] == "caution"
    assert availability["details"]["reason"] == "injury data unavailable"
    assert availability["details"]["status"] is None

    impact = historical.auto_teammate_impact("Jaren Jackson Jr", "points", 12.5, league="nba")
    assert impact["signal"] == "caution"
    assert impact["details"]["reason"] == "injury data unavailable"
    assert impact["details"]["teammate_chemistry"] == []
    assert "Healthy" not in json.dumps(impact["details"])


def test_stale_cache_is_caution_not_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    historical = _historical()
    service, _fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    entries = normalize_bdl_injuries(INJURY_PAGE["data"], mapping, fetched_at="2026-11-01T00:00:00+00:00")
    asyncio.run(
        service.set(
            NBA_INJURIES_CACHE_KEY,
            {"fetched_at": "2026-11-01T00:00:00+00:00", "entries": entries},
            ttl=NBA_INJURIES_CACHE_TTL_SECONDS,
        )
    )
    _set_dummy_key(monkeypatch)
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)

    report = asyncio.run(historical.get_official_injury_report("PHI", league="nba"))
    assert report["signal"] == "caution"
    assert report["details"]["reason"] == "injury data unavailable"
    assert report["details"]["injuries"] == []
    assert report["details"]["fetched_at"] == "2026-11-01T00:00:00+00:00"


def test_without_key_nba_keeps_the_espn_cbs_scraper(monkeypatch: pytest.MonkeyPatch) -> None:
    historical = _historical()
    _clear_key(monkeypatch)
    _patch_scraper(monkeypatch)

    def _no_cache():
        raise AssertionError("NBA cache opened while the API key is unset")

    monkeypatch.setattr(nba_injuries, "open_injury_cache", _no_cache)
    _guard_network(monkeypatch)

    result = asyncio.run(historical.get_official_injury_report("76ers", league="nba"))
    assert _ScrapingFetcher.calls == 1
    assert result["signal"] == "caution"
    assert result["details"]["injuries"] == [
        {
            "player": "Joel Embiid",
            "position": "C",
            "status": "Out",
            "injury": "knee",
            "source": "espn",
        }
    ]
    assert "reason" not in result["details"]


def test_wnba_stays_on_the_scraper_when_the_key_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    historical = _historical()
    _set_dummy_key(monkeypatch)
    _patch_scraper(monkeypatch)

    def _no_cache():
        raise AssertionError("NBA injury cache opened for WNBA")

    monkeypatch.setattr(nba_injuries, "open_injury_cache", _no_cache)
    _forbid_refresh(monkeypatch)
    _guard_network(monkeypatch)

    result = asyncio.run(historical.get_official_injury_report("Liberty", league="wnba"))
    assert _ScrapingFetcher.calls == 1
    assert result["signal"] == "caution"
    assert result["details"]["injuries"] == [
        {
            "player": "Breanna Stewart",
            "position": "F",
            "status": "Out",
            "injury": "foot",
            "source": "espn",
        }
    ]
    rows = historical._fetch_injury_report_for_team("NYL", league="wnba")
    assert rows[0]["player"] == "Breanna Stewart"
    assert "bdl_player_id" not in rows[0]


def test_data_logger_names_the_balldontlie_cache() -> None:
    import data_logger

    injury = data_logger.TOOL_EXPLANATIONS["get_official_injury_report"]["source"]
    teammate = data_logger.TOOL_EXPLANATIONS["auto_teammate_impact"]["source"]
    assert "BALLDONTLIE" in injury
    assert "ESPN/CBS" in injury
    assert "BALLDONTLIE" in teammate
    assert "ESPN/CBS" in teammate
