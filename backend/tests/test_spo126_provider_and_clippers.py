"""SPO-126: OddsProvider abstract method and LA Clippers team code.

``get_event_odds`` is part of the provider interface. ``QuotaUsage`` only
stores the quota counters. ESPN records the Clippers as ``LA Clippers``
(event 401910304). That spelling has to share the LAC code with the CSV
nickname ``Clippers``, which is what ``team_on_event`` compares.
"""

from __future__ import annotations

import inspect
import os
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.csv_player_history import (
    CSVPlayerHistoryService,
    team_from_game_logs,
    team_on_event,
)
from app.services.daily_analysis import canonical_team_code
from app.services.game_log_hygiene import load_schedule_events
from app.services.odds_provider import OddsProvider, QuotaUsage
from dataclasses import fields, is_dataclass

# Boston Celtics at LA Clippers, recorded in
# tests/fixtures/espn/nba_team_2_schedule_2027_type_2.json.
_CELTICS_AT_CLIPPERS = "401910304"


@pytest.fixture(scope="module")
def nba_history() -> CSVPlayerHistoryService:
    service = CSVPlayerHistoryService("nba")
    service.load_csv()
    return service


def _clippers_event() -> dict[str, Any]:
    found = next(
        (
            event
            for event in load_schedule_events(league="nba")
            if str(event.get("id")) == _CELTICS_AT_CLIPPERS
        ),
        None,
    )
    assert found is not None, _CELTICS_AT_CLIPPERS
    return found


def _display_name(event: dict[str, Any], side: str) -> str:
    for competitor in event.get("competitors") or []:
        if competitor.get("homeAway") != side:
            continue
        team = competitor.get("team") or {}
        return str(team.get("displayName") or "")
    raise AssertionError(f"{side} competitor missing on {event.get('id')}")


def _app_provider_subclasses() -> list[type]:
    """Concrete and abstract OddsProvider subclasses defined in the app."""
    import app.services.odds_theoddsapi  # noqa: F401  registers TheOddsAPIProvider

    found: list[type] = []
    pending = list(OddsProvider.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if cls.__module__.startswith("app."):
            found.append(cls)
    return found


class TestOddsProviderContract:
    def test_odds_provider_is_abstract_and_requires_get_event_odds(self):
        assert inspect.isabstract(OddsProvider)
        assert OddsProvider.__abstractmethods__ == frozenset(
            {"get_events", "get_event_odds"}
        )
        with pytest.raises(TypeError):
            OddsProvider()  # type: ignore[abstract]

        class _EventsOnly(OddsProvider):
            async def get_events(self, sport, regions, date_from=None, date_to=None):
                return []

        with pytest.raises(TypeError, match="get_event_odds"):
            _EventsOnly()

    def test_quota_usage_has_no_abstract_members(self):
        assert is_dataclass(QuotaUsage)
        assert not inspect.isabstract(QuotaUsage)
        assert QuotaUsage.__dataclass_params__.frozen is True
        assert [field.name for field in fields(QuotaUsage)] == [
            "remaining",
            "used",
            "last",
        ]
        abstract = {
            name
            for name, member in inspect.getmembers(QuotaUsage)
            if getattr(member, "__isabstractmethod__", False)
        }
        assert abstract == set()
        assert not hasattr(QuotaUsage, "get_event_odds")
        usage = QuotaUsage(remaining=4, used=1, last=1)
        assert usage.total == 5
        assert usage.remaining_ratio == 0.8

    def test_concrete_providers_implement_get_event_odds(self):
        subclasses = _app_provider_subclasses()
        missing = sorted(
            cls.__qualname__
            for cls in subclasses
            if "get_event_odds" in getattr(cls, "__abstractmethods__", frozenset())
        )
        assert missing == [], (
            "OddsProvider subclass does not implement get_event_odds: "
            + ", ".join(missing)
        )
        concrete = [
            cls.__qualname__
            for cls in subclasses
            if not inspect.isabstract(cls)
        ]
        assert "TheOddsAPIProvider" in concrete


class TestLaTeamCodes:
    @pytest.mark.parametrize(
        "spelling",
        [
            "LAC",
            "Clippers",
            "Los Angeles Clippers",
            "LA Clippers",
            "L.A. Clippers",
            "la clippers",
        ],
    )
    def test_clippers_spellings_map_to_lac(self, spelling: str):
        assert canonical_team_code(spelling) == "LAC"

    @pytest.mark.parametrize(
        "spelling",
        [
            "LAL",
            "Lakers",
            "Los Angeles Lakers",
            "LA Lakers",
            "L.A. Lakers",
            "la lakers",
        ],
    )
    def test_lakers_spellings_map_to_lal(self, spelling: str):
        assert canonical_team_code(spelling) == "LAL"

    def test_wnba_codes_stay_on_the_wnba_table(self):
        assert canonical_team_code("Lynx", league="wnba") == "MIN"
        assert canonical_team_code("Wings", league="wnba") == "DAL"
        assert canonical_team_code("LA Sparks", league="wnba") == "LAS"
        assert canonical_team_code("Los Angeles Sparks", league="wnba") == "LAS"
        assert canonical_team_code("Lynx") != "MIN"
        assert canonical_team_code("LA Sparks") == "LASPARKS"
        assert canonical_team_code("Sparks") == "SPARKS"
        assert canonical_team_code("LA") == "LA"


class TestTeamOnEventClippers:
    def test_recorded_clippers_game_keeps_the_csv_club(
        self, nba_history: CSVPlayerHistoryService
    ):
        event = _clippers_event()
        home = _display_name(event, "home")
        away = _display_name(event, "away")
        assert home == "LA Clippers"
        assert away == "Boston Celtics"
        assert canonical_team_code(home) == "LAC"
        assert canonical_team_code(away) == "BOS"

        logs = nba_history._cache["Kawhi Leonard"]
        assert team_from_game_logs(logs, event["date"]) == "Clippers"
        assert team_on_event(logs, event["date"], home, away) == "Clippers"
        assert (
            team_on_event(logs, event["date"], "Los Angeles Clippers", away)
            == "Clippers"
        )
        assert team_on_event(logs, event["date"], home, away, candidate="LAC") == "LAC"

        other = nba_history._cache["Anfernee Simons"]
        assert team_on_event(other, event["date"], home, away) == ""

    def test_la_lakers_spelling_keeps_the_csv_club(
        self, nba_history: CSVPlayerHistoryService
    ):
        logs = nba_history._cache["LeBron James"]
        assert team_from_game_logs(logs) == "Lakers"
        assert team_on_event(logs, None, "LA Lakers", "Boston Celtics") == "Lakers"
        assert (
            team_on_event(logs, None, "Los Angeles Lakers", "Boston Celtics")
            == "Lakers"
        )
        assert team_on_event(logs, None, "LA Clippers", "Boston Celtics") == ""
