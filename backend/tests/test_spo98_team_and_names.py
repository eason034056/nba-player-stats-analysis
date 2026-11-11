"""SPO-98: event-day team attribution and normalized exact player names.

Real rows come from ``data/nba_player_game_logs.csv`` and
``data/wnba_player_game_logs.csv``. The shipped NBA file is a single
2025-2026 season; 126 players appear for more than one club, and 124 of
those have a different team on their first game than on their last, so
``game_logs[0]`` after the oldest-first chart reversal labels them with
the old club.
"""

import asyncio
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "..",
            "scripts",
            "agents",
        )
    ),
)

from app.services.csv_player_history import (
    CSVPlayerHistoryService,
    team_from_game_logs,
)
from app.services.daily_analysis import DailyAnalysisService
from app.services.normalize import match_player_name, player_name_key
from tests.fixtures.odds_api import (
    RECORDED_NBA_EVENTS,
    RECORDED_PLAYER_POINTS,
    load_odds_fixture,
)


@pytest.fixture(scope="module")
def nba_service():
    service = CSVPlayerHistoryService(league="nba")
    service.load_csv()
    return service


@pytest.fixture(scope="module")
def wnba_service():
    service = CSVPlayerHistoryService(league="wnba")
    service.load_csv()
    return service


def _first_and_last_team(logs):
    dated = []
    for log in logs:
        day = log.get("game_date")
        team = (log.get("team") or "").strip()
        if isinstance(day, datetime) and team:
            dated.append((day, team))
    dated.sort()
    teams = {team for _, team in dated}
    return dated[0][1], dated[-1][1], len(teams)


class TestPlayerNameKey:
    """The shared key folds spelling, not nicknames and not substrings."""

    def test_accents_suffixes_and_punctuation_share_a_key(self):
        assert player_name_key("Nikola Jokić") == player_name_key("Nikola Jokic")
        assert player_name_key("Luka Dončić") == player_name_key("  luka   doncic ")
        assert player_name_key("Jimmy Butler III") == player_name_key("Jimmy Butler")
        assert player_name_key("Gary Trent, Jr.") == player_name_key("Gary Trent Jr")
        assert player_name_key("P. J. Washington") == player_name_key("P.J. Washington")
        assert player_name_key("P.J. Washington") == player_name_key("PJ Washington")
        assert player_name_key("Karl-Anthony Towns") == player_name_key("Karl Anthony Towns")
        assert player_name_key("A'ja Wilson") == player_name_key("Aja Wilson")

    def test_nickname_alias_stays_explicit(self):
        # Steph/Stephen is an alias in canonical_name, not in this key.
        assert player_name_key("Steph Curry") != player_name_key("Stephen Curry")

    def test_substring_is_not_equality(self):
        assert match_player_name(
            "Smith",
            ["Aaron Nesmith", "Jalen Smith"],
        ) is None
        assert match_player_name(
            "Jalen Smith",
            ["Aaron Nesmith", "Jalen Smith"],
        ) == "Jalen Smith"
        # "smith" is contained in "nesmith"; that still must not match.
        assert match_player_name("Smith", ["Aaron Nesmith"]) is None

    def test_ambiguous_suffix_does_not_guess(self):
        candidates = ["Gary Trent", "Gary Trent, Jr."]
        assert match_player_name("Gary Trent", candidates) == "Gary Trent"
        assert match_player_name("Gary Trent Jr", candidates) is None


class TestRealCsvNames:
    def test_nba_substring_collision_does_not_match(self, nba_service):
        # Old bidirectional substring returned Seth Curry for "Curry"
        # (Seth sorts before Stephen) and Aaron Nesmith for "Smith"
        # because "smith" sits inside "nesmith".
        assert nba_service.resolve_player_name("Curry") is None
        assert nba_service.resolve_player_name("Smith") is None
        assert nba_service.resolve_player_name("Williams") is None
        assert nba_service.resolve_player_name("Porter") is None
        assert nba_service.resolve_player_name("Seth Curry") == "Seth Curry"
        assert nba_service.resolve_player_name("Stephen Curry") == "Stephen Curry"
        assert nba_service.resolve_player_name("Aaron Nesmith") == "Aaron Nesmith"
        assert nba_service.resolve_player_name("Lucas Williamson") == "Lucas Williamson"

    def test_nba_accent_suffix_and_punctuation_hit_stored_spelling(self, nba_service):
        assert nba_service.resolve_player_name("Nikola Jokić") == "Nikola Jokic"
        assert nba_service.resolve_player_name("Luka Dončić") == "Luka Doncic"
        assert nba_service.resolve_player_name("Kristaps Porziņģis") == "Kristaps Porzingis"
        assert nba_service.resolve_player_name("Alperen Şengün") == "Alperen Sengun"
        assert nba_service.resolve_player_name("Nikola Jovic") == "Nikola Jovic"
        assert nba_service.resolve_player_name("Michael Porter Jr.") == "Michael Porter, Jr."
        assert nba_service.resolve_player_name("Gary Trent Jr.") == "Gary Trent, Jr."
        assert nba_service.resolve_player_name("Jimmy Butler") == "Jimmy Butler III"
        assert nba_service.resolve_player_name("DaRon Holmes") == "DaRon Holmes II"
        assert nba_service.resolve_player_name("CJ McCollum") == "C.J. McCollum"
        assert nba_service.resolve_player_name("Karl Anthony Towns") == "Karl-Anthony Towns"
        assert nba_service.resolve_player_name("Trayce Jackson Davis") == "Trayce Jackson-Davis"
        assert nba_service.resolve_player_name("  nikola   JOKIC ") == "Nikola Jokic"

        stats = nba_service.get_player_stats("Nikola Jokić", "points", 20.5)
        assert stats["player"] == "Nikola Jokic"
        assert stats["n_games"] > 0
        # Jokić must not be handed Jovic's log.
        jovic = nba_service.get_player_stats("Nikola Jovic", "points", 10.5)
        assert jovic["player"] == "Nikola Jovic"
        assert jovic["n_games"] != stats["n_games"] or jovic["mean"] != stats["mean"]

    def test_steph_is_not_an_implicit_alias_for_stephen(self, nba_service):
        assert nba_service.resolve_player_name("Steph Curry") is None

    def test_wnba_apostrophe_and_substring(self, wnba_service):
        assert wnba_service.resolve_player_name("Aja Wilson") == "A'ja Wilson"
        assert wnba_service.resolve_player_name("Wilson") is None
        stats = wnba_service.get_player_stats("Aja Wilson", "points", 15.5)
        assert stats["player"] == "A'ja Wilson"
        assert stats["n_games"] > 0
        dd = wnba_service.player_dd_history("Aja Wilson")
        assert dd["player"] == "A'ja Wilson"
        assert dd["games"] > 0


class TestTeamAttribution:
    def test_nba_traded_player_counts(self, nba_service):
        multi = 0
        label_changes = 0
        for logs in nba_service._cache.values():
            first, last, n_teams = _first_and_last_team(logs)
            if n_teams > 1:
                multi += 1
                if first != last:
                    label_changes += 1
        # Preseason, summer, and G League rows are out of the canonical
        # file, so only regular-season and playoff clubs remain. 74 players
        # still have two or more clubs, and each one's earliest club
        # differs from the latest.
        assert multi == 74
        assert label_changes == 74

    def test_buddy_hield_event_day_and_latest_team(self, nba_service):
        logs = nba_service._cache["Buddy Hield"]
        # Oldest-first chart shape is what daily_analysis used to read.
        chart = list(reversed(logs))
        assert chart[0]["team"] == "Warriors"
        assert team_from_game_logs(chart, "2025-11-01") == "Warriors"
        assert team_from_game_logs(chart, "2026-02-09") == "Hawks"
        assert team_from_game_logs(chart, "2026-04-30T23:00:00Z") == "Hawks"
        assert team_from_game_logs(chart) == "Hawks"
        # Raw cache is newest-first; the helper must not depend on that.
        assert team_from_game_logs(logs, "2025-11-01") == "Warriors"
        # A date before every log is the earliest known club, not the latest.
        assert team_from_game_logs(logs, "2020-01-01") == "Warriors"
        assert team_from_game_logs(logs) == "Hawks"

    def test_round_trip_player_uses_team_on_that_day(self, nba_service):
        # Mo Bamba: Jazz -> Raptors -> Jazz. Earliest and latest are both
        # Jazz, so "most recent" hides the middle stint. The event day does not.
        logs = nba_service._cache["Mo Bamba"]
        assert team_from_game_logs(logs) == "Jazz"
        # Games before 2025-12-29 were not regular season, so the earliest
        # club left in the file is the Raptors.
        assert team_from_game_logs(logs, "2025-10-16") == "Raptors"
        assert team_from_game_logs(logs, "2026-01-03") == "Raptors"
        assert team_from_game_logs(logs, "2026-01-15") == "Raptors"
        assert team_from_game_logs(logs, "2026-03-05") == "Jazz"

    def test_wnba_traded_player_event_day(self, wnba_service):
        label_changes = 0
        for logs in wnba_service._cache.values():
            first, last, n_teams = _first_and_last_team(logs)
            if n_teams > 1 and first != last:
                label_changes += 1
        # Preseason rows are out of the canonical file. 24 players still
        # change club between their earliest and latest remaining game.
        assert label_changes == 24

        logs = wnba_service._cache["DiJonai Carrington"]
        chart = list(reversed(logs))
        assert chart[0]["team"] == "Wings"
        assert team_from_game_logs(chart, "2025-05-02") == "Wings"
        assert team_from_game_logs(chart, "2025-06-01") == "Wings"
        assert team_from_game_logs(chart, "2025-08-05") == "Lynx"
        assert team_from_game_logs(chart) == "Lynx"

    def test_undated_single_log_keeps_that_team(self):
        # daily_analysis fixtures pass one team and no date.
        assert team_from_game_logs([{"team": "Heat"}]) == "Heat"
        assert team_from_game_logs([]) == ""


# Recorded The Odds API bodies. See tests/fixtures/README.md.
# Only player_points was captured. Other markets are left empty.


def _load_recorded_event() -> dict:
    """The Lakers @ Hawks player_points response, unchanged."""
    return load_odds_fixture(RECORDED_PLAYER_POINTS)


def _outcome_names(event: dict) -> set[str]:
    names: set[str] = set()
    for book in event["bookmakers"]:
        for market in book["markets"]:
            for outcome in market["outcomes"]:
                description = outcome.get("description") or ""
                if description:
                    names.add(description)
    return names


class TestDailyAnalysisWiring:
    def _picks(self, game_logs, commence_time, projections=None, home_team=None, away_team=None):
        event = _load_recorded_event()
        events = load_odds_fixture(RECORDED_NBA_EVENTS)
        assert any(row["id"] == event["id"] for row in events)
        assert len(event["bookmakers"]) == 6
        assert {m["key"] for b in event["bookmakers"] for m in b["markets"]} == {
            "player_points"
        }

        async def props_for_market(event_id, market, league="nba"):
            if event_id != event["id"] or market != "player_points":
                return []
            return event["bookmakers"]

        service = DailyAnalysisService(probability_threshold=0.65)
        service._get_props_for_market = props_for_market
        service.csv_service = MagicMock()
        service.csv_service.get_player_stats = MagicMock(
            return_value={
                "p_over": 0.80,
                "p_under": 0.15,
                "n_games": 40,
                "game_logs": game_logs,
            }
        )
        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id=event["id"],
                home_team=home_team or event["home_team"],
                away_team=away_team or event["away_team"],
                commence_time=commence_time,
                projections=projections or {},
            )
        )
        return picks, event

    def test_event_after_trade_uses_new_team_not_oldest_log(self):
        logs = [
            {"team": "Warriors", "date_full": "2025-10-05"},
            {"team": "Hawks", "date_full": "2026-02-09"},
        ]
        event = _load_recorded_event()
        # Recorded tip is 2026-11-10T00:10:00Z (2026-11-09 in New York),
        # after the synthetic Hawks log.
        picks, loaded = self._picks(logs, event["commence_time"])
        assert loaded["id"] == event["id"]
        assert picks
        assert {p.player_name for p in picks} <= _outcome_names(event)
        assert all(p.home_team == "Atlanta Hawks" for p in picks)
        assert all(p.away_team == "Los Angeles Lakers" for p in picks)
        assert all(p.player_team == "Hawks" for p in picks)
        assert all(p.player_team_code == "ATL" for p in picks)

    def test_event_before_trade_keeps_old_team(self):
        logs = [
            {"team": "Warriors", "date_full": "2025-10-05"},
            {"team": "Hawks", "date_full": "2026-02-09"},
        ]
        # The recorded tip is after this trade. The earlier commence is the
        # clock under test; the bookmaker body stays the recorded one.
        # The recorded body is still Lakers at Hawks. Warriors is not in
        # that game, so pass a slate that includes the pre-trade club.
        # The clock stays before the Hawks log.
        picks, event = self._picks(
            logs,
            "2025-11-01T02:00:00Z",
            home_team="Boston Celtics",
            away_team="Golden State Warriors",
        )
        assert picks
        assert {p.player_name for p in picks} <= _outcome_names(event)
        assert all(p.home_team == "Boston Celtics" for p in picks)
        assert all(p.away_team == "Golden State Warriors" for p in picks)
        assert all(p.player_team == "Warriors" for p in picks)
        assert all(p.player_team_code == "GSW" for p in picks)
        assert all(p.player_team != "Hawks" for p in picks)

    def test_projection_team_still_wins(self):
        logs = [
            {"team": "Warriors", "date_full": "2025-10-05"},
            {"team": "Hawks", "date_full": "2026-02-09"},
        ]
        event = _load_recorded_event()
        projected = "Jalen Johnson"
        assert projected in _outcome_names(event)
        picks, _ = self._picks(
            logs,
            event["commence_time"],
            projections={projected: {"team": "LAL"}},
        )
        projected_picks = [p for p in picks if p.player_name == projected]
        other_picks = [p for p in picks if p.player_name != projected]
        assert projected_picks
        assert other_picks
        # LAL is the away club on the recorded event, so the projection
        # is kept. A code for a club that is not playing is not kept.
        assert all(p.player_team == "LAL" for p in projected_picks)
        assert all(p.player_team_code == "LAL" for p in projected_picks)
        assert all(p.player_team == "Hawks" for p in other_picks)


class TestHistoricalGamesFor:
    def test_nba_and_wnba_exact_names_and_event_day_team(self):
        from tools.historical import _games_for, _team_for

        jokic = _games_for("Nikola Jokić", league="nba")
        assert jokic
        assert jokic[0]["player_name"] == "Nikola Jokic"
        assert _games_for("Smith", league="nba") == []
        assert _games_for("Curry", league="nba") == []

        assert _team_for("Buddy Hield", "2025-11-01", league="nba") == "Warriors"
        assert _team_for("Buddy Hield", "2026-04-30", league="nba") == "Hawks"
        assert _team_for("Buddy Hield", league="nba") == "Hawks"
        assert _team_for("Mo Bamba", "2026-01-15", league="nba") == "Raptors"

        wilson = _games_for("Aja Wilson", league="wnba")
        assert wilson
        assert wilson[0]["player_name"] == "A'ja Wilson"
        assert _games_for("Wilson", league="wnba") == []
        assert _team_for("DiJonai Carrington", "2025-06-01", league="wnba") == "Wings"
        assert _team_for("DiJonai Carrington", league="wnba") == "Lynx"
