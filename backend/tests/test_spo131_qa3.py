"""SPO-131 QA round 3 — mixed scrape and cache rows, and WNBA parity.

BDL rows are normalized from the recorded page. Scrape rows use the same
in-process ``InjuriesPageFetcher`` stand-in as the SPO-131 tests.
"""

from __future__ import annotations

import copy

from tests import test_spo131_bdl_injuries as base
from tests.test_spo131_bdl_injuries import (
    INJURY_PAGE,
    STANDINGS,
    nba_injuries,
    normalize_bdl_injuries,
    team_id_to_code_from_standings,
)

_MAPPING = team_id_to_code_from_standings(STANDINGS)


def _bdl_row(index: int = 0) -> dict:
    return normalize_bdl_injuries([copy.deepcopy(INJURY_PAGE["data"][index])], _MAPPING, fetched_at="x")[0]


def _scrape_like(row: dict, status: str) -> dict:
    return {"player": row["player"], "position": row["position"], "status": status, "injury": "", "source": "cbs"}


def test_scrape_row_and_cache_row_for_one_player_pick_the_cache_row():
    historical = base._historical()
    cached = _bdl_row()
    scraped = _scrape_like(cached, "Questionable")
    assert historical._match_injury_entry([scraped, cached], cached["player"]) is cached
    assert historical._match_injury_entry([cached, scraped], cached["player"]) is cached


def test_cache_row_without_id_next_to_a_scrape_row_is_still_used():
    historical = base._historical()
    cached = dict(_bdl_row(), bdl_player_id=None)
    scraped = _scrape_like(cached, "Questionable")
    assert historical._match_injury_entry([scraped, cached], cached["player"]) is cached


def test_caller_id_wins_over_a_scrape_row():
    historical = base._historical()
    cached = _bdl_row()
    scraped = _scrape_like(cached, "Questionable")
    found = historical._match_injury_entry([scraped, cached], "someone else", cached["bdl_player_id"])
    assert found is cached


def test_scrape_rows_only_take_the_first_name_match_like_dev():
    historical = base._historical()
    cached = _bdl_row()
    first = _scrape_like(cached, "Out")
    second = dict(_scrape_like(cached, "Questionable"), source="espn")
    assert historical._match_injury_entry([first, second], cached["player"]) is first
    assert historical._match_injury_entry([second, first], cached["player"]) is second


class _WnbaBothSources:
    def fetch_all(self) -> dict:
        return {
            "espn": [base._ScrapedInjury("NYL", "Breanna Stewart", "F", "Out", "foot")],
            "cbs": [base._ScrapedInjury("NYL", "Breanna Stewart", "F", "Questionable", "foot")],
        }


def test_wnba_availability_takes_the_first_scrape_row_for_every_flag(monkeypatch):
    historical = base._historical()
    base._set_dummy_key(monkeypatch)
    base._install_injuries_module(monkeypatch, _WnbaBothSources)

    def _no_cache():
        raise AssertionError("NBA injury cache opened for WNBA")

    monkeypatch.setattr(nba_injuries, "open_injury_cache", _no_cache)
    base._guard_network(monkeypatch)
    rows = historical._fetch_injury_report_for_team("NYL", league="wnba")
    for flag in ("espn_cbs", "bdl", "foo"):
        base._set_injury_source(monkeypatch, flag)
        assert historical._fetch_injury_report_for_team("NYL", league="wnba") == rows
        assert historical._match_injury_entry(rows, "Breanna Stewart")["status"] == "Out"
