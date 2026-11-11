"""SPO-122 review checks for event team labels and scoped teammates.

NBA rows come from the shipped excerpt
``tests/fixtures/csv/spo122_anfernee_simons_excerpt.csv`` and the event
identity from the recorded Odds API body. WNBA rows come from the shipped
``data/wnba_player_game_logs.csv``. Nothing here is typed by hand from an
external API.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.csv_player_history import (
    CSVPlayerHistoryService,
    team_from_game_logs,
    team_on_event,
)
from tests.fixtures.odds_api import NBA_EXPANDED_MARKETS, load_odds_fixture

_BACKEND = Path(__file__).resolve().parents[1]
_EXCERPT = _BACKEND / "tests" / "fixtures" / "csv" / "spo122_anfernee_simons_excerpt.csv"


@pytest.fixture
def excerpt_service(monkeypatch: pytest.MonkeyPatch) -> CSVPlayerHistoryService:
    monkeypatch.setattr("app.services.csv_player_history.CSV_PATH", str(_EXCERPT))
    service = CSVPlayerHistoryService("nba")
    service.load_csv()
    return service


@pytest.fixture(scope="module")
def wnba_service() -> CSVPlayerHistoryService:
    service = CSVPlayerHistoryService("wnba")
    service.load_csv()
    return service


@pytest.fixture(scope="module")
def bos_phi() -> dict:
    event = load_odds_fixture(NBA_EXPANDED_MARKETS)
    assert event["away_team"] == "Boston Celtics"
    assert event["home_team"] == "Philadelphia 76ers"
    return event


class TestTeamOnEvent:
    def test_projection_club_not_in_game_falls_through_to_log_club(
        self, excerpt_service, bos_phi
    ):
        logs = excerpt_service._cache["Derrick White"]
        got = team_on_event(
            logs,
            bos_phi["commence_time"],
            bos_phi["home_team"],
            bos_phi["away_team"],
            candidate="GSW",
        )
        assert got == "Celtics"

    def test_projection_club_not_in_game_and_log_club_not_in_game_is_blank(
        self, excerpt_service, bos_phi
    ):
        logs = excerpt_service._cache["Anfernee Simons"]
        got = team_on_event(
            logs,
            bos_phi["commence_time"],
            bos_phi["home_team"],
            bos_phi["away_team"],
            candidate="GSW",
        )
        assert got == ""

    @pytest.mark.parametrize("candidate", ["BOS", "bos", "Celtics", "Boston Celtics", " PHI ", "Sixers", "76ers"])
    def test_projection_spellings_for_a_club_in_the_game_are_kept(
        self, excerpt_service, bos_phi, candidate
    ):
        logs = excerpt_service._cache["Anfernee Simons"]
        got = team_on_event(
            logs,
            bos_phi["commence_time"],
            bos_phi["home_team"],
            bos_phi["away_team"],
            candidate=candidate,
        )
        assert got == candidate.strip()

    @pytest.mark.parametrize(
        "home, away",
        [("Philadelphia 76ers", ""), ("", "Boston Celtics"), ("", ""), ("  ", "Boston Celtics")],
    )
    def test_one_missing_club_keeps_the_old_rule(self, excerpt_service, bos_phi, home, away):
        logs = excerpt_service._cache["Anfernee Simons"]
        assert team_on_event(logs, bos_phi["commence_time"], home, away) == "Bulls"
        assert team_on_event(logs, bos_phi["commence_time"], home, away, candidate="GSW") == "GSW"

    def test_abbreviation_event_clubs_match_csv_nicknames(self, excerpt_service, bos_phi):
        logs = excerpt_service._cache["Derrick White"]
        assert team_on_event(logs, bos_phi["commence_time"], "PHI", "BOS") == "Celtics"

    def test_no_logs_and_no_candidate_is_blank(self, bos_phi):
        assert team_on_event([], bos_phi["commence_time"], bos_phi["home_team"], bos_phi["away_team"]) == ""
        assert team_on_event(None, None, bos_phi["home_team"], bos_phi["away_team"]) == ""

    def test_past_event_uses_the_club_on_that_day(self, excerpt_service):
        logs = excerpt_service._cache["Anfernee Simons"]
        first_day = min(log["game_date"] for log in logs if log["team"] == "Celtics")
        day = first_day.strftime("%Y-%m-%d")
        assert team_from_game_logs(logs, day) == "Celtics"
        assert team_on_event(logs, day, "Philadelphia 76ers", "Boston Celtics") == "Celtics"


class TestGetTeammatesOnlyTeam:
    def test_none_keeps_every_stint(self, excerpt_service):
        mates = excerpt_service.get_teammates("Anfernee Simons", only_team=None)
        assert mates == excerpt_service.get_teammates("Anfernee Simons")
        assert "Josh Giddey" in mates and "Derrick White" in mates

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_club_returns_no_one(self, excerpt_service, blank):
        assert excerpt_service.get_teammates("Anfernee Simons", only_team=blank) == []

    @pytest.mark.parametrize("club", ["Bulls", "CHI", "Chicago Bulls", "chi"])
    def test_one_club_keeps_only_that_stint(self, excerpt_service, club):
        mates = excerpt_service.get_teammates("Anfernee Simons", only_team=club)
        assert "Josh Giddey" in mates
        assert "Derrick White" not in mates
        assert "Anfernee Simons" not in mates

    def test_club_the_player_never_played_for_is_empty(self, excerpt_service):
        assert excerpt_service.get_teammates("Anfernee Simons", only_team="Lakers") == []

    def test_unknown_player_is_empty_for_every_scope(self, excerpt_service):
        for scope in (None, "", "Bulls"):
            assert excerpt_service.get_teammates("Nobody Here", only_team=scope) == []


class TestPlayerStatsScope:
    def test_one_event_club_does_not_scope_the_list(self, excerpt_service, bos_phi):
        full = excerpt_service.get_teammates("Anfernee Simons")
        stats = excerpt_service.get_player_stats(
            "Anfernee Simons",
            "points",
            9.5,
            home_team=bos_phi["home_team"],
            away_team=None,
            as_of=bos_phi["commence_time"],
        )
        assert stats["teammates"] == full

    def test_scoping_changes_teammates_only_not_the_sample(self, excerpt_service, bos_phi):
        open_stats = excerpt_service.get_player_stats("Anfernee Simons", "points", 9.5)
        scoped = excerpt_service.get_player_stats(
            "Anfernee Simons",
            "points",
            9.5,
            home_team=bos_phi["home_team"],
            away_team=bos_phi["away_team"],
            as_of=bos_phi["commence_time"],
        )
        assert scoped["teammates"] == []
        for key in ("n_games", "p_over", "p_under", "mean"):
            assert scoped.get(key) == open_stats.get(key)

    def test_bad_as_of_does_not_raise(self, excerpt_service, bos_phi):
        scoped = excerpt_service.get_player_stats(
            "Derrick White",
            "points",
            15.5,
            home_team=bos_phi["home_team"],
            away_team=bos_phi["away_team"],
            as_of="not-a-date",
        )
        assert "Anfernee Simons" in scoped["teammates"]


class TestWnbaUnchanged:
    def test_wnba_nickname_matches_wnba_event_names(self, wnba_service):
        logs = wnba_service._cache["Napheesa Collier"]
        latest = team_from_game_logs(logs)
        assert latest == "Lynx"
        assert team_on_event(logs, None, "Minnesota Lynx", "Chicago Sky", league="wnba") == "Lynx"
        assert team_on_event(logs, None, "Las Vegas Aces", "Seattle Storm", league="wnba") == ""

    def test_lynx_is_not_the_timberwolves(self, wnba_service):
        logs = wnba_service._cache["Napheesa Collier"]
        assert team_on_event(
            logs, None, "Minnesota Timberwolves", "Chicago Bulls", league="nba"
        ) == ""

    def test_wnba_unscoped_teammates_match_the_previous_list(self, wnba_service):
        stats = wnba_service.get_player_stats("Napheesa Collier", "points", 20.5)
        assert stats["teammates"] == wnba_service.get_teammates("Napheesa Collier")
        assert stats["teammates"]

    def test_wnba_scoped_teammates_keep_the_in_game_club(self, wnba_service):
        scoped = wnba_service.get_player_stats(
            "Napheesa Collier",
            "points",
            20.5,
            home_team="Minnesota Lynx",
            away_team="Chicago Sky",
        )
        assert scoped["teammates"] == wnba_service.get_teammates("Napheesa Collier", only_team="Lynx")
        assert scoped["teammates"]
        off = wnba_service.get_player_stats(
            "Napheesa Collier",
            "points",
            20.5,
            home_team="Las Vegas Aces",
            away_team="Seattle Storm",
        )
        assert off["teammates"] == []
