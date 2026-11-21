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
import sys
from datetime import datetime, timedelta, timezone

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_BACKEND)
sys.path.insert(0, _BACKEND)
sys.path.insert(0, os.path.join(_REPO, "nba_lineup_rag"))

from app.services.cache import CacheService  # noqa: E402
from app.services.injury_status import OUT, PROBABLE, UNRESOLVED_INJURY_STATUSES  # noqa: E402
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
from app.settings import Settings  # noqa: E402
from pydantic import SecretStr  # noqa: E402
from src.config import NBA_TEAMS  # noqa: E402

_FIXTURE_DIR = os.path.join(_BACKEND, "tests", "fixtures", "bdl")
_INJURY_PATH = os.path.join(_FIXTURE_DIR, "player_injuries__page1.json")
_STANDINGS_PATH = os.path.join(_FIXTURE_DIR, "standings_2026.json")

_SCORING_STATUSES = {OUT, PROBABLE, "Healthy"} | UNRESOLVED_INJURY_STATUSES
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
    assert {entry["status"] for entry in doubtful} == {"Doubtful"}

    statuses = {entry["status"] for entry in entries}
    assert statuses <= _SCORING_STATUSES
    assert statuses == {"Out", "Doubtful", "Questionable", "Day-To-Day", "Probable"}

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


