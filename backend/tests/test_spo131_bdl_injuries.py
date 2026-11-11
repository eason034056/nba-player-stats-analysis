"""SPO-131 — NBA injuries from the recorded BALLDONTLIE fixtures.

No test in this module calls BALLDONTLIE, ESPN, or CBS. The injury page
and the standings file are the recorded responses copied under
``tests/fixtures/bdl/``. A terminal page is a deepcopy of that recorded
page with ``meta.next_cursor`` cleared or removed. Tests do not type a
new BDL response.
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
    NBA_INJURIES_MAX_PAGES,
    NBA_INJURIES_STALE_AFTER_SECONDS,
    NBA_INJURY_CACHE_SOCKET_TIMEOUT_SECONDS,
    get_cached_nba_injuries,
    normalize_bdl_injuries,
    refresh_nba_injuries,
    team_id_to_code_from_standings,
)
from app.settings import Settings, settings  # noqa: E402
from pydantic import SecretStr  # noqa: E402
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


def _recorded_page(*, next_cursor: object = None, drop_next_cursor: bool = False) -> dict:
    """Deepcopy of the recorded page. Only ``meta.next_cursor`` changes.

    ``drop_next_cursor`` deletes the field. Otherwise the copied page
    keeps every recorded row and sets ``next_cursor`` to the argument
    (``None`` is a last page).
    """
    page = copy.deepcopy(INJURY_PAGE)
    meta = page.setdefault("meta", {})
    if drop_next_cursor:
        meta.pop("next_cursor", None)
    else:
        meta["next_cursor"] = next_cursor
    return page


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
    monkeypatch.setattr(settings, "balldontlie_api_key", SecretStr(_DUMMY_KEY))


def _clear_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BALLDONTLIE_API_KEY", raising=False)
    monkeypatch.setattr(settings, "balldontlie_api_key", SecretStr(""))


def _set_injury_source(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Set the retired env var. NBA and WNBA both ignore it."""
    monkeypatch.setenv("NBA_INJURY_SOURCE", value)


def _use_default_injury_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NBA_INJURY_SOURCE", raising=False)


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
@pytest.mark.parametrize("drop_next_cursor", [False, True])
async def test_refresh_reads_fixture_then_stops(drop_next_cursor: bool) -> None:
    service, fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    last = _recorded_page(drop_next_cursor=drop_next_cursor) if drop_next_cursor else _recorded_page(next_cursor=None)
    client = PageClient([INJURY_PAGE, last])

    payload = await refresh_nba_injuries(client, service, mapping)

    assert [call["cursor"] for call in client.calls] == [None, INJURY_PAGE["meta"]["next_cursor"]]
    assert [call["per_page"] for call in client.calls] == [100, 100]
    assert payload is not None
    assert payload["entries"] == normalize_bdl_injuries(
        INJURY_PAGE["data"] + last["data"],
        mapping,
        fetched_at=payload["fetched_at"],
    )
    assert all(entry["fetched_at"] == payload["fetched_at"] for entry in payload["entries"])
    stored = await service.get(NBA_INJURIES_CACHE_KEY)
    assert stored == payload
    refresh_writes = [call for call in fake.set_calls if call["key"] == NBA_INJURIES_CACHE_KEY]
    assert refresh_writes[-1]["ex"] == NBA_INJURIES_CACHE_TTL_SECONDS == 24 * 60 * 60
    assert NBA_INJURIES_STALE_AFTER_SECONDS == 6 * 60 * 60
    assert NBA_INJURIES_CACHE_TTL_SECONDS > NBA_INJURIES_STALE_AFTER_SECONDS


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", [0, 1])
async def test_page_failure_keeps_the_previous_cache(fail_at: int) -> None:
    service, fake = _cache()
    previous = _old_snapshot()
    await service.set(NBA_INJURIES_CACHE_KEY, previous, ttl=100)
    writes_after_seed = len(fake.set_calls)
    client = PageClient([INJURY_PAGE, _recorded_page(next_cursor=None)], fail_at=fail_at)

    result = await refresh_nba_injuries(client, service, team_id_to_code_from_standings(STANDINGS))

    assert result is None
    assert await service.get(NBA_INJURIES_CACHE_KEY) == previous
    assert len(fake.set_calls) == writes_after_seed
    stored = await service.get(NBA_INJURIES_CACHE_KEY)
    assert stored["entries"][0]["player"] == "Keep Me"
    assert stored["entries"] != []


@pytest.mark.asyncio
async def test_cache_write_failure_keeps_the_previous_body() -> None:
    class _Refuse:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def set(self, key: str, value: dict, ttl: int) -> bool:
            self.calls.append({"key": key, "value": value, "ttl": ttl})
            return False

    cache = _Refuse()
    client = PageClient([INJURY_PAGE, _recorded_page(next_cursor=None)])
    result = await refresh_nba_injuries(client, cache, team_id_to_code_from_standings(STANDINGS))
    assert result is None
    assert len(cache.calls) == 1
    assert cache.calls[0]["key"] == NBA_INJURIES_CACHE_KEY
    assert cache.calls[0]["ttl"] == NBA_INJURIES_CACHE_TTL_SECONDS
    assert cache.calls[0]["value"]["entries"]


def test_stale_boundary_is_older_than_six_hours() -> None:
    now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    exactly = (now - timedelta(seconds=NBA_INJURIES_STALE_AFTER_SECONDS)).isoformat()
    older = (now - timedelta(seconds=NBA_INJURIES_STALE_AFTER_SECONDS, microseconds=1)).isoformat()
    assert nba_injuries._is_stale(exactly, now=now) is False
    assert nba_injuries._is_stale(older, now=now) is True
    assert nba_injuries._is_stale(None, now=now) is True


class _RepeatingCursorClient:
    """Every page is the recorded body with the same next_cursor."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def list_player_injuries(self, *, cursor: int | None = None, per_page: int = 100) -> dict:
        self.calls.append({"cursor": cursor, "per_page": per_page})
        return _recorded_page(next_cursor=7)


class _EndlessCursorClient:
    """Each page is the recorded body with a new next_cursor."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def list_player_injuries(self, *, cursor: int | None = None, per_page: int = 100) -> dict:
        self.calls.append({"cursor": cursor, "per_page": per_page})
        nxt = 0 if cursor is None else int(cursor) + 1
        return _recorded_page(next_cursor=nxt)


@pytest.mark.asyncio
async def test_repeated_next_cursor_stops_without_looping() -> None:
    service, _fake = _cache()
    client = _RepeatingCursorClient()
    payload = await refresh_nba_injuries(client, service, team_id_to_code_from_standings(STANDINGS))
    assert payload is not None
    assert len(client.calls) == 2
    assert len(client.calls) < NBA_INJURIES_MAX_PAGES
    assert client.calls[1]["cursor"] == 7


@pytest.mark.asyncio
async def test_refresh_stops_at_the_page_cap(caplog: pytest.LogCaptureFixture) -> None:
    service, _fake = _cache()
    previous = _old_snapshot()
    await service.set(NBA_INJURIES_CACHE_KEY, previous, ttl=NBA_INJURIES_CACHE_TTL_SECONDS)
    client = _EndlessCursorClient()
    with caplog.at_level(logging.WARNING):
        payload = await refresh_nba_injuries(
            client, service, team_id_to_code_from_standings(STANDINGS)
        )
    assert payload is None
    assert await service.get(NBA_INJURIES_CACHE_KEY) == previous
    assert len(client.calls) == NBA_INJURIES_MAX_PAGES == 20
    assert "page cap" in caplog.text


@pytest.mark.asyncio
async def test_page_cap_does_not_replace_the_previous_snapshot() -> None:
    service, _fake = _cache()
    previous = _old_snapshot()
    await service.set(NBA_INJURIES_CACHE_KEY, previous, ttl=NBA_INJURIES_CACHE_TTL_SECONDS)
    result = await refresh_nba_injuries(
        _EndlessCursorClient(),
        service,
        team_id_to_code_from_standings(STANDINGS),
    )
    assert result is None
    assert await service.get(NBA_INJURIES_CACHE_KEY) == previous


@pytest.mark.asyncio
async def test_malformed_page_logs_a_warning_and_keeps_the_cache(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, _fake = _cache()
    previous = _old_snapshot()
    await service.set(NBA_INJURIES_CACHE_KEY, previous, ttl=NBA_INJURIES_CACHE_TTL_SECONDS)

    class _BadPage:
        async def list_player_injuries(self, *, cursor: int | None = None, per_page: int = 100) -> dict:
            page = _recorded_page(next_cursor=None)
            del page["data"]
            return page

    with caplog.at_level(logging.WARNING):
        result = await refresh_nba_injuries(
            _BadPage(),
            service,
            team_id_to_code_from_standings(STANDINGS),
        )
    assert result is None
    assert await service.get(NBA_INJURIES_CACHE_KEY) == previous
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert warnings
    assert any("rejected a page" in record.message for record in warnings)
    assert "empty team map" not in caplog.text
    assert all(record.exc_info in (None, (None, None, None)) for record in warnings)


@pytest.mark.asyncio
async def test_unexpected_error_logs_only_the_exception_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, _fake = _cache()
    previous = _old_snapshot()
    await service.set(NBA_INJURIES_CACHE_KEY, previous, ttl=NBA_INJURIES_CACHE_TTL_SECONDS)
    client = PageClient([INJURY_PAGE], fail_at=0)
    with caplog.at_level(logging.WARNING):
        result = await refresh_nba_injuries(client, service, {})
    assert result is None
    assert await service.get(NBA_INJURIES_CACHE_KEY) == previous
    assert "RuntimeError" in caplog.text
    assert "player_injuries page failed" not in caplog.text
    assert all(record.exc_info in (None, (None, None, None)) for record in caplog.records)


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
    default_key = Settings.model_fields["balldontlie_api_key"].default
    assert isinstance(default_key, SecretStr)
    assert default_key.get_secret_value() == ""
    assert Settings.model_fields["nba_injuries_refresh_minutes"].default == 30
    assert "nba_injury_source" not in Settings.model_fields


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
    client = PageClient([INJURY_PAGE, _recorded_page(next_cursor=None)])
    payload = asyncio.run(refresh_nba_injuries(client, service, mapping))
    assert payload is not None

    _set_dummy_key(monkeypatch)
    _set_injury_source(monkeypatch, "bdl")
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
            PageClient([INJURY_PAGE, _recorded_page(drop_next_cursor=True)]),
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
    _set_injury_source(monkeypatch, "bdl")
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
    _set_injury_source(monkeypatch, "bdl")
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
    _set_injury_source(monkeypatch, "bdl")
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)

    report = asyncio.run(historical.get_official_injury_report("PHI", league="nba"))
    assert report["signal"] == "caution"
    assert report["details"]["reason"] == "injury data unavailable"
    assert report["details"]["injuries"] == []
    assert report["details"]["fetched_at"] == "2026-11-01T00:00:00+00:00"


def test_body_inside_ttl_and_past_six_hours_is_stale_not_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seven hours is inside the 24h Redis TTL and past the 6h stale window."""
    historical = _historical()
    service, _fake = _cache()
    fetched_at = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    assert timedelta(hours=7).total_seconds() > NBA_INJURIES_STALE_AFTER_SECONDS
    assert timedelta(hours=7).total_seconds() < NBA_INJURIES_CACHE_TTL_SECONDS
    entries = [{"player": "Still Stored", "team": "PHI", "status": "Out", "source": "balldontlie"}]
    asyncio.run(
        service.set(
            NBA_INJURIES_CACHE_KEY,
            {"fetched_at": fetched_at, "entries": entries},
            ttl=NBA_INJURIES_CACHE_TTL_SECONDS,
        )
    )
    snapshot = asyncio.run(get_cached_nba_injuries("PHI", cache=service))
    assert snapshot["stale"] is True
    assert snapshot["fetched_at"] == fetched_at
    assert snapshot["entries"] == entries

    _set_dummy_key(monkeypatch)
    _set_injury_source(monkeypatch, "bdl")
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)
    report = asyncio.run(historical.get_official_injury_report("PHI", league="nba"))
    assert report["signal"] == "caution"
    assert report["details"]["reason"] == "injury data unavailable"
    assert report["details"]["injuries"] == []
    assert report["details"]["fetched_at"] == fetched_at


def _expect_espn_cbs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scraper is allowed. Opening the BDL cache fails the test."""
    _patch_scraper(monkeypatch)

    def _no_cache():
        raise AssertionError("NBA injury cache opened on the ESPN/CBS path")

    monkeypatch.setattr(nba_injuries, "open_injury_cache", _no_cache)
    _guard_network(monkeypatch)


def test_without_key_nba_reads_the_cache_and_does_not_scrape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The API key is not the feed switch. NBA never scrapes."""
    historical = _historical()
    service, _fake = _cache()
    _clear_key(monkeypatch)
    _use_default_injury_source(monkeypatch)
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)

    result = asyncio.run(historical.get_official_injury_report("PHI", league="nba"))
    assert result["signal"] == "caution"
    assert result["details"]["reason"] == "injury data unavailable"
    assert result["details"]["injuries"] == []


def test_nba_reads_the_cache_when_the_old_flag_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical = _historical()
    service, _fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    payload = asyncio.run(
        refresh_nba_injuries(
            PageClient([INJURY_PAGE, _recorded_page(next_cursor=None)]),
            service,
            mapping,
        )
    )
    assert payload is not None
    _set_dummy_key(monkeypatch)
    _use_default_injury_source(monkeypatch)
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)

    team_code = payload["entries"][0]["team"]
    result = asyncio.run(historical.get_official_injury_report(team_code, league="nba"))
    assert result["details"]["injuries"][0]["source"] == "balldontlie"
    assert "reason" not in result["details"]


def test_nba_ignores_espn_cbs_env_and_reads_the_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical = _historical()
    service, _fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    payload = asyncio.run(
        refresh_nba_injuries(
            PageClient([INJURY_PAGE, _recorded_page(next_cursor=None)]),
            service,
            mapping,
        )
    )
    assert payload is not None
    _set_dummy_key(monkeypatch)
    _set_injury_source(monkeypatch, "espn_cbs")
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)

    team_code = payload["entries"][0]["team"]
    result = asyncio.run(historical.get_official_injury_report(team_code, league="nba"))
    assert result["details"]["injuries"][0]["source"] == "balldontlie"


def test_nba_ignores_an_unknown_injury_source_env(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    historical = _historical()
    service, _fake = _cache()
    _set_dummy_key(monkeypatch)
    _set_injury_source(monkeypatch, "rotowire")
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(historical.get_official_injury_report("PHI", league="nba"))
    assert result["details"]["reason"] == "injury data unavailable"
    assert "rotowire" not in caplog.text
    assert "espn_cbs" not in caplog.text


@pytest.mark.parametrize("source", [None, "espn_cbs", "bdl", "rotowire"])
def test_wnba_stays_on_the_scraper_for_every_flag(
    monkeypatch: pytest.MonkeyPatch,
    source: str | None,
) -> None:
    historical = _historical()
    _set_dummy_key(monkeypatch)
    if source is None:
        _use_default_injury_source(monkeypatch)
    else:
        _set_injury_source(monkeypatch, source)
    _expect_espn_cbs(monkeypatch)
    _forbid_refresh(monkeypatch)

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


def test_empty_data_page_with_a_team_map_stores_an_empty_list() -> None:
    """``data: []`` plus a usable map is a real empty league, not a failure."""
    page = _recorded_page(next_cursor=None)
    page["data"] = []
    service, _fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    payload = asyncio.run(refresh_nba_injuries(PageClient([page]), service, mapping))
    assert payload is not None
    assert payload["entries"] == []
    stored = asyncio.run(service.get(NBA_INJURIES_CACHE_KEY))
    assert stored["entries"] == []


@pytest.mark.asyncio
async def test_rows_that_all_drop_keep_the_previous_snapshot() -> None:
    service, _fake = _cache()
    previous = _old_snapshot()
    await service.set(NBA_INJURIES_CACHE_KEY, previous, ttl=NBA_INJURIES_CACHE_TTL_SECONDS)
    page = _recorded_page(next_cursor=None)
    result = await refresh_nba_injuries(PageClient([page]), service, {999999: "ZZZ"})
    assert result is None
    assert await service.get(NBA_INJURIES_CACHE_KEY) == previous


def test_injury_cache_client_sets_socket_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def _from_url(url: str, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeRedis()

    monkeypatch.setattr("app.services.cache.redis.from_url", _from_url)
    service = nba_injuries.open_injury_cache()
    asyncio.run(service.get_client())
    assert captured["kwargs"]["decode_responses"] is True
    assert captured["kwargs"]["socket_timeout"] == NBA_INJURY_CACHE_SOCKET_TIMEOUT_SECONDS == 2.0
    assert captured["kwargs"]["socket_connect_timeout"] == NBA_INJURY_CACHE_SOCKET_TIMEOUT_SECONDS


def _seed_fresh(service: CacheService, entries: list[dict]) -> str:
    fetched_at = datetime.now(timezone.utc).isoformat()
    asyncio.run(
        service.set(
            NBA_INJURIES_CACHE_KEY,
            {"fetched_at": fetched_at, "entries": entries},
            ttl=NBA_INJURIES_CACHE_TTL_SECONDS,
        )
    )
    return fetched_at


def test_uppercase_bdl_is_the_cache_source(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """``BDL`` is folded to ``bdl``. It is not an unknown value."""
    historical = _historical()
    service, _fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    entries = normalize_bdl_injuries(INJURY_PAGE["data"], mapping, fetched_at="2026-11-11T12:00:00+00:00")
    fetched_at = _seed_fresh(service, entries)
    _set_dummy_key(monkeypatch)
    _set_injury_source(monkeypatch, "BDL")
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)
    with caplog.at_level(logging.WARNING):
        report = asyncio.run(historical.get_official_injury_report(entries[0]["team"], league="nba"))
    assert "unknown" not in caplog.text.lower()
    assert report["details"]["injuries"]
    assert report["details"]["injuries"][0]["fetched_at"]
    assert fetched_at


@pytest.mark.parametrize("value", ["foo", ""])
def test_invalid_injury_source_env_still_reads_the_cache(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    value: str,
) -> None:
    historical = _historical()
    service, _fake = _cache()
    _set_dummy_key(monkeypatch)
    _set_injury_source(monkeypatch, value)
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(historical.get_official_injury_report("PHI", league="nba"))
    assert result["details"]["reason"] == "injury data unavailable"
    if value:
        assert value not in caplog.text
    assert "espn_cbs" not in caplog.text


def test_nba_cache_read_does_not_consult_a_source_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A settings object with no injury-source field still reads the cache."""
    historical = _historical()
    service, _fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    payload = asyncio.run(
        refresh_nba_injuries(
            PageClient([INJURY_PAGE, _recorded_page(next_cursor=None)]),
            service,
            mapping,
        )
    )
    assert payload is not None
    _use_default_injury_source(monkeypatch)
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)
    team_code = payload["entries"][0]["team"]
    result = asyncio.run(historical.get_official_injury_report(team_code, league="nba"))
    assert result["details"]["injuries"][0]["source"] == "balldontlie"


def test_bdl_without_a_key_and_no_cache_is_caution(monkeypatch: pytest.MonkeyPatch) -> None:
    historical = _historical()
    historical._logged_bdl_without_key = False
    service, _fake = _cache()
    _clear_key(monkeypatch)
    _set_injury_source(monkeypatch, "bdl")
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)

    report = asyncio.run(historical.get_official_injury_report("PHI", league="nba"))
    assert report["signal"] == "caution"
    assert report["details"]["reason"] == "injury data unavailable"
    availability = historical.get_availability_context("Jaren Jackson Jr", league="nba")
    assert availability["signal"] == "caution"
    assert availability["details"]["fetched_at"] is None
    assert availability["details"]["status"] is None
    impact = historical.auto_teammate_impact("Jaren Jackson Jr", "points", 12.5, league="nba")
    assert impact["signal"] == "caution"
    assert impact["details"]["fetched_at"] is None
    assert "Healthy" not in json.dumps(impact["details"])


def test_bdl_without_a_key_and_a_stale_cache_is_caution(monkeypatch: pytest.MonkeyPatch) -> None:
    historical = _historical()
    service, _fake = _cache()
    fetched_at = "2026-11-01T00:00:00+00:00"
    mapping = team_id_to_code_from_standings(STANDINGS)
    entries = normalize_bdl_injuries(INJURY_PAGE["data"], mapping, fetched_at=fetched_at)
    asyncio.run(
        service.set(
            NBA_INJURIES_CACHE_KEY,
            {"fetched_at": fetched_at, "entries": entries},
            ttl=NBA_INJURIES_CACHE_TTL_SECONDS,
        )
    )
    _clear_key(monkeypatch)
    _set_injury_source(monkeypatch, "bdl")
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)
    report = asyncio.run(historical.get_official_injury_report("PHI", league="nba"))
    assert report["signal"] == "caution"
    assert report["details"]["reason"] == "injury data unavailable"
    assert report["details"]["fetched_at"] == fetched_at
    availability = historical.get_availability_context("Jaren Jackson Jr", league="nba")
    assert availability["signal"] == "caution"
    assert availability["details"]["fetched_at"] == fetched_at
    assert availability["details"]["status"] is None


def test_bdl_without_a_key_reads_a_fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    historical = _historical()
    service, _fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    entries = normalize_bdl_injuries(
        INJURY_PAGE["data"],
        mapping,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    _seed_fresh(service, entries)
    _clear_key(monkeypatch)
    monkeypatch.setattr(settings, "balldontlie_api_key", SecretStr(""))
    _set_injury_source(monkeypatch, "bdl")
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)
    team = entries[0]["team"]
    report = asyncio.run(historical.get_official_injury_report(team, league="nba"))
    assert report["signal"] == "caution"
    assert report["details"]["injuries"]
    assert "reason" not in report["details"]


def test_empty_secret_is_not_a_configured_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    historical = _historical()
    historical._logged_bdl_without_key = False
    service, _fake = _cache()
    monkeypatch.delenv("BALLDONTLIE_API_KEY", raising=False)
    monkeypatch.setattr(settings, "balldontlie_api_key", SecretStr(""))
    _set_injury_source(monkeypatch, "bdl")
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    with caplog.at_level(logging.WARNING):
        report = asyncio.run(historical.get_official_injury_report("PHI", league="nba"))
    assert report["signal"] == "caution"
    assert report["details"]["reason"] == "injury data unavailable"
    assert "unset" not in caplog.text
    assert "SecretStr" not in caplog.text


def test_traded_player_matches_by_name_off_the_csv_team(monkeypatch: pytest.MonkeyPatch) -> None:
    historical = _historical()
    service, _fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    entries = normalize_bdl_injuries(
        INJURY_PAGE["data"],
        mapping,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    row = copy.deepcopy(next(entry for entry in entries if entry["player"] == "Jaren Jackson Jr."))
    row["team"] = "MEM"
    _seed_fresh(service, [row])
    _set_dummy_key(monkeypatch)
    _set_injury_source(monkeypatch, "bdl")
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)
    availability = historical.get_availability_context("Jaren Jackson Jr", league="nba")
    assert availability["signal"] == "caution"
    assert availability["details"]["status"] == "Out"
    assert availability["details"]["detail"]["team"] == "MEM"


def test_bdl_player_id_wins_when_names_collide(monkeypatch: pytest.MonkeyPatch) -> None:
    historical = _historical()
    service, _fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    entries = normalize_bdl_injuries(
        INJURY_PAGE["data"],
        mapping,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    original = next(entry for entry in entries if entry["player"] == "Jaren Jackson Jr.")
    other = copy.deepcopy(original)
    other["bdl_player_id"] = original["bdl_player_id"] + 1
    other["status"] = "Questionable"
    _seed_fresh(service, [original, other])
    _set_dummy_key(monkeypatch)
    _set_injury_source(monkeypatch, "bdl")
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)
    availability = historical.get_availability_context(
        "Jaren Jackson Jr",
        league="nba",
        bdl_player_id=original["bdl_player_id"],
    )
    assert availability["details"]["status"] == "Out"
    assert availability["details"]["detail"]["bdl_player_id"] == original["bdl_player_id"]


def _dual_source_scrape(monkeypatch: pytest.MonkeyPatch):
    """ESPN and CBS both list the same WNBA Out player. The cache must not open."""
    historical = _historical()
    team = historical._team_for("Breanna Stewart", league="wnba")
    code = historical._team_code_from_name(team, league="wnba")

    class _BothSources:
        def fetch_all(self) -> dict:
            def _row() -> _ScrapedInjury:
                return _ScrapedInjury(code, "Breanna Stewart", "F", "Out", "foot")

            return {"espn": [_row()], "cbs": [_row()]}

    _install_injuries_module(monkeypatch, _BothSources)

    def _no_cache() -> None:
        raise AssertionError("NBA injury cache opened on the WNBA scrape path")

    monkeypatch.setattr(nba_injuries, "open_injury_cache", _no_cache)
    _guard_network(monkeypatch)
    return historical


def test_wnba_player_on_both_scrape_sources_is_still_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical = _dual_source_scrape(monkeypatch)
    _use_default_injury_source(monkeypatch)
    availability = historical.get_availability_context("Breanna Stewart", league="wnba")
    assert availability["signal"] == "caution"
    assert availability["details"]["status"] == "Out"


def test_wnba_player_on_both_scrape_sources_ignores_the_old_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical = _dual_source_scrape(monkeypatch)
    _set_injury_source(monkeypatch, "foo")
    availability = historical.get_availability_context("Breanna Stewart", league="wnba")
    assert availability["signal"] == "caution"
    assert availability["details"]["status"] == "Out"


def test_two_cache_rows_with_the_same_name_and_no_id_are_not_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical = _historical()
    service, _fake = _cache()
    mapping = team_id_to_code_from_standings(STANDINGS)
    entries = normalize_bdl_injuries(
        INJURY_PAGE["data"],
        mapping,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    original = copy.deepcopy(next(entry for entry in entries if entry["player"] == "Jaren Jackson Jr."))
    other = copy.deepcopy(original)
    original["bdl_player_id"] = None
    other["bdl_player_id"] = None
    other["status"] = "Questionable"
    _seed_fresh(service, [original, other])
    _set_dummy_key(monkeypatch)
    _set_injury_source(monkeypatch, "bdl")
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)
    availability = historical.get_availability_context("Jaren Jackson Jr", league="nba")
    assert availability["signal"] == "neutral"
    assert availability["details"]["status"] == "Healthy"


@pytest.mark.parametrize("hours,is_stale", [(5.99, False), (6.01, True), (23, True)])
def test_hours_inside_the_day_long_ttl_follow_the_six_hour_stale_window(
    monkeypatch: pytest.MonkeyPatch,
    hours: float,
    is_stale: bool,
) -> None:
    historical = _historical()
    service, _fake = _cache()
    fetched_at = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    mapping = team_id_to_code_from_standings(STANDINGS)
    entries = normalize_bdl_injuries(INJURY_PAGE["data"], mapping, fetched_at=fetched_at)
    asyncio.run(
        service.set(
            NBA_INJURIES_CACHE_KEY,
            {"fetched_at": fetched_at, "entries": entries},
            ttl=NBA_INJURIES_CACHE_TTL_SECONDS,
        )
    )
    assert timedelta(hours=hours).total_seconds() < NBA_INJURIES_CACHE_TTL_SECONDS
    _set_dummy_key(monkeypatch)
    _set_injury_source(monkeypatch, "bdl")
    _use_cache(monkeypatch, service)
    _forbid_scraper(monkeypatch)
    _guard_network(monkeypatch)
    report = asyncio.run(historical.get_official_injury_report(entries[0]["team"], league="nba"))
    if is_stale:
        assert report["signal"] == "caution"
        assert report["details"]["reason"] == "injury data unavailable"
        assert report["details"]["injuries"] == []
        assert report["details"]["fetched_at"] == fetched_at
    else:
        assert report["details"]["injuries"]
        assert "reason" not in report["details"]


def test_data_logger_names_the_balldontlie_cache() -> None:
    import data_logger

    injury = data_logger.TOOL_EXPLANATIONS["get_official_injury_report"]["source"]
    teammate = data_logger.TOOL_EXPLANATIONS["auto_teammate_impact"]["source"]
    assert "BALLDONTLIE" in injury
    assert "ESPN/CBS" in injury
    assert "BALLDONTLIE" in teammate
    assert "ESPN/CBS" in teammate
