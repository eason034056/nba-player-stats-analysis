"""SPO-131 QA round 2 — matching on the scrape path and the page cap.

BDL bodies are the recorded page or a copy of it. The scrape stub is the
same in-process ``InjuriesPageFetcher`` stand-in the SPO-131 tests use;
it returns parsed rows, not an HTTP body.
"""

from __future__ import annotations

import asyncio
import copy

import pytest

from tests import test_spo131_bdl_injuries as base
from tests.test_spo131_bdl_injuries import (
    INJURY_PAGE,
    NBA_INJURIES_CACHE_KEY,
    NBA_INJURIES_CACHE_TTL_SECONDS,
    STANDINGS,
    nba_injuries,
    normalize_bdl_injuries,
    refresh_nba_injuries,
    team_id_to_code_from_standings,
)

_MAPPING = team_id_to_code_from_standings(STANDINGS)


class _BothSourcesFetcher:
    """ESPN and CBS both list the same player, as the live pages do."""

    def fetch_all(self) -> dict:
        return {
            "espn": [base._ScrapedInjury("PHI", "Joel Embiid", "C", "Out", "knee")],
            "cbs": [base._ScrapedInjury("PHI", "Joel Embiid", "C", "Out", "Knee")],
        }


def _scrape_path(monkeypatch, league_source: str | None = None):
    historical = base._historical()
    if league_source is None:
        base._use_default_injury_source(monkeypatch)
    else:
        base._set_injury_source(monkeypatch, league_source)
    base._install_injuries_module(monkeypatch, _BothSourcesFetcher)

    def _no_cache():
        raise AssertionError("cache opened on the scrape path")

    monkeypatch.setattr(nba_injuries, "open_injury_cache", _no_cache)
    base._guard_network(monkeypatch)
    return historical


def test_scrape_rows_reach_the_tool_unchanged(monkeypatch):
    historical = _scrape_path(monkeypatch)
    rows = historical._fetch_injury_report_for_team("PHI", league="nba")
    assert [(r["player"], r["source"]) for r in rows] == [("Joel Embiid", "espn"), ("Joel Embiid", "cbs")]


def test_player_on_both_scrape_sources_is_still_out_on_the_default_path(monkeypatch):
    historical = _scrape_path(monkeypatch)
    availability = historical.get_availability_context("Joel Embiid", league="nba")
    assert availability["details"]["status"] == "Out"
    assert availability["signal"] == "caution"


def test_player_on_both_scrape_sources_with_unknown_flag(monkeypatch):
    historical = _scrape_path(monkeypatch, "foo")
    availability = historical.get_availability_context("Joel Embiid", league="nba")
    assert availability["details"]["status"] == "Out"


def test_same_player_twice_in_the_cache_without_ids_is_not_guessed():
    historical = base._historical()
    row = normalize_bdl_injuries([copy.deepcopy(INJURY_PAGE["data"][0])], _MAPPING, fetched_at="x")[0]
    other = dict(row, team="BOS", bdl_player_id=None)
    first = dict(row, bdl_player_id=None)
    assert historical._match_injury_entry([first, other], row["player"]) is None


def test_bdl_id_wins_over_a_duplicate_name():
    historical = base._historical()
    row = normalize_bdl_injuries([copy.deepcopy(INJURY_PAGE["data"][0])], _MAPPING, fetched_at="x")[0]
    other = dict(row, team="BOS", bdl_player_id=1)
    assert historical._match_injury_entry([other, row], row["player"], row["bdl_player_id"]) is row


# ---------------------------------------------------------------------------
# Page cap
# ---------------------------------------------------------------------------


class _EndlessRecordedPages:
    """Every call returns the recorded page with a fresh next_cursor."""

    def __init__(self) -> None:
        self.calls = 0

    async def list_player_injuries(self, *, cursor=None, per_page=100) -> dict:
        self.calls += 1
        page = copy.deepcopy(INJURY_PAGE)
        page["meta"]["next_cursor"] = INJURY_PAGE["meta"]["next_cursor"] + self.calls
        return page


def test_page_cap_does_not_replace_the_previous_snapshot():
    service, _fake = base._cache()
    previous = base._old_snapshot()
    asyncio.run(service.set(NBA_INJURIES_CACHE_KEY, previous, ttl=NBA_INJURIES_CACHE_TTL_SECONDS))
    client = _EndlessRecordedPages()

    result = asyncio.run(refresh_nba_injuries(client, service, _MAPPING))

    assert client.calls == nba_injuries.NBA_INJURIES_MAX_PAGES
    assert result is None
    assert asyncio.run(service.get(NBA_INJURIES_CACHE_KEY)) == previous


# ---------------------------------------------------------------------------
# TTL 24h / stale 6h
# ---------------------------------------------------------------------------


def test_redis_ttl_is_a_day_and_staleness_is_six_hours():
    assert nba_injuries.NBA_INJURIES_CACHE_TTL_SECONDS == 24 * 60 * 60
    assert nba_injuries.NBA_INJURIES_STALE_AFTER_SECONDS == 6 * 60 * 60


def test_refresh_writes_with_the_24h_ttl():
    service, fake = base._cache()
    page = copy.deepcopy(INJURY_PAGE)
    page["meta"]["next_cursor"] = None
    asyncio.run(refresh_nba_injuries(base.PageClient([page]), service, _MAPPING))
    writes = [c for c in fake.set_calls if c["key"] == NBA_INJURIES_CACHE_KEY]
    assert writes[-1]["ex"] == 24 * 60 * 60


@pytest.mark.parametrize("hours, stale", [(5.99, False), (6.01, True), (23, True)])
def test_body_still_in_redis_is_judged_by_fetched_at(monkeypatch, hours, stale):
    from datetime import datetime, timedelta, timezone

    at = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    entries = normalize_bdl_injuries(INJURY_PAGE["data"], _MAPPING, fetched_at=at)
    service, _fake = base._cache()
    asyncio.run(service.set(NBA_INJURIES_CACHE_KEY, {"fetched_at": at, "entries": entries}, ttl=NBA_INJURIES_CACHE_TTL_SECONDS))
    historical = base._historical()
    base._set_injury_source(monkeypatch, "bdl")
    base._use_cache(monkeypatch, service)
    base._forbid_scraper(monkeypatch)
    base._guard_network(monkeypatch)
    report = asyncio.run(historical.get_official_injury_report("UTA", league="nba"))
    if stale:
        assert report["signal"] == "caution"
        assert report["details"]["reason"] == "injury data unavailable"
        assert report["details"]["injuries"] == []
    else:
        assert report["details"]["injuries"]
        assert "reason" not in report["details"]
