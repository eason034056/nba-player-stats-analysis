"""SPO-131 QA — cache edge cases on the recorded BALLDONTLIE fixtures.

Every BDL body here is the recorded page or a copy of it. No test types
a new BDL response.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests import test_spo131_bdl_injuries as base
from tests.test_spo131_bdl_injuries import (
    INJURY_PAGE,
    STANDINGS,
    NBA_INJURIES_CACHE_KEY,
    NBA_INJURIES_CACHE_TTL_SECONDS,
    get_cached_nba_injuries,
    nba_injuries,
    normalize_bdl_injuries,
    refresh_nba_injuries,
    team_id_to_code_from_standings,
)

_MAPPING = team_id_to_code_from_standings(STANDINGS)
_REPO = Path(base._REPO)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fresh_entries() -> list[dict]:
    return normalize_bdl_injuries(INJURY_PAGE["data"], _MAPPING, fetched_at=_now_iso())


def _seed(body) -> base.CacheService:
    service, _fake = base._cache()
    asyncio.run(service.set(NBA_INJURIES_CACHE_KEY, body, ttl=NBA_INJURIES_CACHE_TTL_SECONDS))
    return service


def _agent_path(monkeypatch: pytest.MonkeyPatch, service) -> object:
    historical = base._historical()
    base._set_dummy_key(monkeypatch)
    # The cache is selected by NBA_INJURY_SOURCE, not by the API key.
    base._set_injury_source(monkeypatch, "bdl")
    base._use_cache(monkeypatch, service)
    base._forbid_scraper(monkeypatch)
    base._forbid_refresh(monkeypatch)
    base._guard_network(monkeypatch)
    return historical


def _single_page() -> dict:
    """The recorded page as the only page: a copy with ``next_cursor`` cleared."""
    page = copy.deepcopy(INJURY_PAGE)
    page["meta"]["next_cursor"] = None
    return page


def _row(last_name: str) -> dict:
    return copy.deepcopy(next(r for r in INJURY_PAGE["data"] if r["player"]["last_name"] == last_name))


# ---------------------------------------------------------------------------
# Fresh, empty, malformed
# ---------------------------------------------------------------------------


def test_fresh_snapshot_with_an_empty_list_means_no_injuries(monkeypatch):
    service = _seed({"fetched_at": _now_iso(), "entries": []})
    historical = _agent_path(monkeypatch, service)
    report = asyncio.run(historical.get_official_injury_report("UTA", league="nba"))
    assert report["signal"] == "neutral"
    assert report["details"]["injuries"] == []
    assert "reason" not in report["details"]


@pytest.mark.parametrize("entries", ["missing", None, "oops", {"UTA": []}])
def test_fresh_body_without_an_entries_list_is_unavailable(monkeypatch, entries):
    body = {"fetched_at": _now_iso()}
    if entries != "missing":
        body["entries"] = entries
    service = _seed(body)
    historical = _agent_path(monkeypatch, service)
    report = asyncio.run(historical.get_official_injury_report("UTA", league="nba"))
    assert report["signal"] == "caution"
    assert report["details"]["reason"] == "injury data unavailable"


@pytest.mark.parametrize("fetched_at", [None, "", "yesterday", 1731300000])
def test_unreadable_fetched_at_is_unavailable(monkeypatch, fetched_at):
    service = _seed({"fetched_at": fetched_at, "entries": _fresh_entries()})
    historical = _agent_path(monkeypatch, service)
    report = asyncio.run(historical.get_official_injury_report("UTA", league="nba"))
    assert report["signal"] == "caution"
    assert report["details"]["reason"] == "injury data unavailable"
    assert report["details"]["injuries"] == []


def test_non_object_body_is_unavailable(monkeypatch):
    service = _seed(_fresh_entries())  # a bare list, not {fetched_at, entries}
    historical = _agent_path(monkeypatch, service)
    report = asyncio.run(historical.get_official_injury_report("UTA", league="nba"))
    assert report["signal"] == "caution"
    assert report["details"]["reason"] == "injury data unavailable"


def test_redis_error_is_unavailable_not_healthy(monkeypatch):
    service, fake = base._cache()

    async def _boom(_key):
        raise ConnectionError("redis down")

    fake.get = _boom
    historical = _agent_path(monkeypatch, service)
    report = asyncio.run(historical.get_official_injury_report("UTA", league="nba"))
    assert report["signal"] == "caution"
    assert report["details"]["reason"] == "injury data unavailable"
    impact = historical.auto_teammate_impact("Jaren Jackson Jr", "points", 12.5, league="nba")
    assert impact["signal"] == "caution"
    assert impact["details"]["teammate_chemistry"] == []


# ---------------------------------------------------------------------------
# Clock handling
# ---------------------------------------------------------------------------


def test_z_suffix_and_naive_times_are_read_as_utc():
    now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    five_h = now - timedelta(hours=5)
    seven_h = now - timedelta(hours=7)
    assert nba_injuries._is_stale(five_h.strftime("%Y-%m-%dT%H:%M:%SZ"), now=now) is False
    assert nba_injuries._is_stale(seven_h.strftime("%Y-%m-%dT%H:%M:%SZ"), now=now) is True
    assert nba_injuries._is_stale(five_h.replace(tzinfo=None).isoformat(), now=now) is False
    assert nba_injuries._is_stale(seven_h.replace(tzinfo=None).isoformat(), now=now) is True


def test_offset_times_are_compared_in_utc():
    now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    chicago = timezone(timedelta(hours=-6))
    # 01:00 CST is 07:00 UTC, five hours before ``now``.
    assert nba_injuries._is_stale(datetime(2026, 11, 11, 1, 0, tzinfo=chicago).isoformat(), now=now) is False
    # 23:00 CST the day before is 05:00 UTC, seven hours before ``now``.
    assert nba_injuries._is_stale(datetime(2026, 11, 10, 23, 0, tzinfo=chicago).isoformat(), now=now) is True


def test_refresh_stamps_fetched_at_in_utc():
    service, _fake = base._cache()
    client = base.PageClient([_single_page()])
    payload = asyncio.run(refresh_nba_injuries(client, service, _MAPPING))
    parsed = datetime.fromisoformat(payload["fetched_at"])
    assert parsed.utcoffset() == timedelta(0)
    assert nba_injuries._is_stale(payload["fetched_at"]) is False


# ---------------------------------------------------------------------------
# Refresh must not publish an empty list over a good one
# ---------------------------------------------------------------------------


def test_refresh_with_no_team_map_keeps_the_previous_snapshot():
    service, _fake = base._cache()
    previous = {"fetched_at": _now_iso(), "entries": _fresh_entries()}
    asyncio.run(service.set(NBA_INJURIES_CACHE_KEY, previous, ttl=NBA_INJURIES_CACHE_TTL_SECONDS))
    client = base.PageClient([_single_page()])

    result = asyncio.run(refresh_nba_injuries(client, service, {}))

    assert result is None
    assert asyncio.run(service.get(NBA_INJURIES_CACHE_KEY)) == previous


def test_refresh_failure_log_does_not_echo_the_exception_text(caplog):
    service, _fake = base._cache()

    class _Leaky:
        async def list_player_injuries(self, *, cursor=None, per_page=100):
            raise RuntimeError("GET /v1/player_injuries Authorization: SECRET-TOKEN-123")

    with caplog.at_level(logging.DEBUG):
        assert asyncio.run(refresh_nba_injuries(_Leaky(), service, _MAPPING)) is None
    assert "SECRET-TOKEN-123" not in caplog.text
    assert "RuntimeError" in caplog.text


# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------


def test_recorded_statuses_are_all_handled():
    raw = {row["status"] for row in INJURY_PAGE["data"]}
    assert raw == {"Out", "Questionable", "Available", "Day-To-Day", "Probable", "Doubtful"}
    entries = normalize_bdl_injuries(INJURY_PAGE["data"], _MAPPING, fetched_at=_now_iso())
    assert {e["raw_status"] for e in entries} == raw - {"Available"}
    for entry in entries:
        expected = "Questionable" if entry["raw_status"] == "Doubtful" else entry["raw_status"]
        assert entry["status"] == expected


def test_doubtful_player_reads_as_caution_with_the_source_word(monkeypatch):
    entries = _fresh_entries()
    doubtful = next(e for e in entries if e["raw_status"] == "Doubtful")
    service = _seed({"fetched_at": _now_iso(), "entries": entries})
    historical = _agent_path(monkeypatch, service)
    report = asyncio.run(historical.get_official_injury_report(doubtful["team"], league="nba"))
    row = next(e for e in report["details"]["injuries"] if e["bdl_player_id"] == doubtful["bdl_player_id"])
    assert row["status"] == "Questionable"
    assert row["raw_status"] == "Doubtful"


def test_unrecognized_status_is_not_read_as_healthy(monkeypatch):
    row = _row("Jackson Jr.")
    row["status"] = "Out For Season"
    entries = normalize_bdl_injuries([row], _MAPPING, fetched_at=_now_iso())
    service = _seed({"fetched_at": _now_iso(), "entries": entries})
    historical = _agent_path(monkeypatch, service)
    availability = historical.get_availability_context("Jaren Jackson Jr", league="nba")
    assert availability["signal"] == "caution"


def test_unrecognized_status_is_kept_and_logged(caplog):
    row = _row("Jackson Jr.")
    row["status"] = "Out For Season"
    with caplog.at_level(logging.WARNING):
        entries = normalize_bdl_injuries([row], _MAPPING, fetched_at=_now_iso())
    assert [e["raw_status"] for e in entries] == ["Out For Season"]
    assert "unrecognized BDL injury status" in caplog.text


# ---------------------------------------------------------------------------
# Player matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["Jaren Jackson Jr", "Jaren Jackson Jr.", "jaren jackson"])
def test_suffix_spellings_match_the_bdl_row(monkeypatch, query):
    service = _seed({"fetched_at": _now_iso(), "entries": _fresh_entries()})
    historical = _agent_path(monkeypatch, service)
    availability = historical.get_availability_context(query, league="nba")
    assert availability["signal"] == "caution"
    assert availability["details"]["status"] == "Out"


def test_accented_bdl_name_matches_the_ascii_query(monkeypatch):
    row = _row("Jackson Jr.")
    row["player"]["first_name"] = "Járén"
    entries = normalize_bdl_injuries([row], _MAPPING, fetched_at=_now_iso())
    service = _seed({"fetched_at": _now_iso(), "entries": entries})
    historical = _agent_path(monkeypatch, service)
    availability = historical.get_availability_context("Jaren Jackson Jr", league="nba")
    assert availability["details"]["status"] == "Out"


def test_player_is_looked_up_on_the_bdl_team_for_that_team_id(monkeypatch):
    # The recorded row puts Jaren Jackson Jr. on team_id 29 (UTA).
    row = _row("Jackson Jr.")
    assert _MAPPING[row["player"]["team_id"]] == "UTA"
    entries = normalize_bdl_injuries([row], _MAPPING, fetched_at=_now_iso())
    service = _seed({"fetched_at": _now_iso(), "entries": entries})
    historical = _agent_path(monkeypatch, service)
    uta = asyncio.run(historical.get_official_injury_report("UTA", league="nba"))
    mem = asyncio.run(historical.get_official_injury_report("MEM", league="nba"))
    assert [e["bdl_player_id"] for e in uta["details"]["injuries"]] == [row["player"]["id"]]
    assert mem["details"]["injuries"] == []


# ---------------------------------------------------------------------------
# No BALLDONTLIE call on the agent path
# ---------------------------------------------------------------------------


def test_agent_tools_do_not_import_a_bdl_client_or_http_library():
    text = (_REPO / "scripts" / "agents" / "tools" / "historical.py").read_text(encoding="utf-8")
    for needle in ("bdl_client", "balldontlie.io", "api.balldontlie", "refresh_nba_injuries", "httpx", "aiohttp"):
        assert needle not in text


def test_cache_read_module_has_no_http_client():
    text = (_REPO / "backend" / "app" / "services" / "nba_injuries.py").read_text(encoding="utf-8")
    for needle in ("import httpx", "import aiohttp", "import requests", "balldontlie.io"):
        assert needle not in text


def test_fixtures_carry_no_credentials():
    for path in (_REPO / "backend" / "tests" / "fixtures" / "bdl").glob("*.json"):
        text = path.read_text(encoding="utf-8").lower()
        for needle in ("authorization", "apikey", "api_key", "bearer"):
            assert needle not in text, path.name


# ---------------------------------------------------------------------------
# WNBA regression
# ---------------------------------------------------------------------------


def test_wnba_availability_and_teammate_paths_stay_on_the_scraper(monkeypatch):
    historical = base._historical()
    base._set_dummy_key(monkeypatch)
    base._patch_scraper(monkeypatch)

    def _no_cache():
        raise AssertionError("NBA injury cache opened for WNBA")

    monkeypatch.setattr(nba_injuries, "open_injury_cache", _no_cache)
    base._guard_network(monkeypatch)
    rows = historical._fetch_injury_report_for_team("NYL", league="WNBA")
    assert [r["player"] for r in rows] == ["Breanna Stewart"]
    assert base._ScrapingFetcher.calls == 1
