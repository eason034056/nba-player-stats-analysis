"""Gap tests for SPO-98 team attribution and exact name matching.

Rows come from the shipped CSVs via ``CSVPlayerHistoryService``. No test
in this module builds an odds, injury, or lineup HTTP body.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_BACKEND)
sys.path.insert(0, _BACKEND)
sys.path.insert(0, os.path.join(_REPO, "scripts", "agents"))

from app.services.csv_player_history import (  # noqa: E402
    CSVPlayerHistoryService,
    team_from_game_logs,
)
from app.services.normalize import match_player_name, player_name_key  # noqa: E402

_UNKNOWN = "No Such Player"


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


def _sample_contexts():
    path = os.path.join(_REPO, "scripts", "dataset", "01_sample_contexts.py")
    spec = importlib.util.spec_from_file_location("sample_contexts_spo98", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _historical():
    import tools.historical as historical

    return historical


class TestNameKeyEdges:
    """Folding rules that the SPO-98 file only samples once, plus both leagues."""

    def test_diacritics_precomposed_and_combining(self):
        # č is U+010D. The combining form is c + caron (U+030C).
        combining = "Luka Donc\u030cic"
        assert player_name_key("Luka Dončić") == player_name_key("Luka Doncic")
        assert player_name_key(combining) == player_name_key("Luka Doncic")
        assert player_name_key("Nikola Jokić") == player_name_key("nikola jokic")
        assert player_name_key("Nikola Jokić") != player_name_key("Nikola Jovic")
        assert player_name_key("Kristaps Porziņģis") == player_name_key("Kristaps Porzingis")
        assert player_name_key("Alperen Şengün") == player_name_key("Alperen Sengun")

    def test_suffix_punctuation_hyphen_apostrophe_case_and_space(self):
        assert player_name_key("Gary Trent, Jr.") == player_name_key("gary trent jr")
        assert player_name_key("Xavier Tillman, Sr.") == player_name_key("Xavier Tillman Sr")
        assert player_name_key("Jimmy Butler III") == player_name_key("jimmy butler")
        assert player_name_key("DaRon Holmes II") == player_name_key("daron holmes")
        assert player_name_key("Gary Payton II") == player_name_key("Gary Payton")
        assert player_name_key("Tim Hardaway Jr.") == player_name_key("tim hardaway jr")
        assert player_name_key("Karl-Anthony Towns") == player_name_key("karl anthony towns")
        assert player_name_key("Shai Gilgeous-Alexander") == player_name_key(
            "Shai Gilgeous Alexander"
        )
        assert player_name_key("Te-Hina Paopao") == player_name_key("Te Hina Paopao")
        assert player_name_key("A'ja Wilson") == player_name_key("Aja Wilson")
        assert player_name_key("A’ja Wilson") == player_name_key("A'ja Wilson")
        assert player_name_key("De'Aaron Fox") == player_name_key("DeAaron Fox")
        assert player_name_key("D'Angelo Russell") == player_name_key("Dangelo Russell")
        assert player_name_key("Royce O'Neale") == player_name_key("Royce ONeale")
        assert player_name_key("Kel’el Ware") == player_name_key("Kel'el Ware")
        assert player_name_key("  P. J.   Washington ") == player_name_key("PJ Washington")
        # Apostrophe is deleted, not turned into a space, so a split token differs.
        assert player_name_key("De'Aaron Fox") != player_name_key("De Aaron Fox")
        assert player_name_key("D'Angelo Russell") != player_name_key("D Angelo Russell")
        # A first-name token that merely starts like a suffix stays put.
        assert player_name_key("Jrue Holiday") == "jrue holiday"
        assert player_name_key("Jr.") == ""
        assert player_name_key(None) == ""
        assert player_name_key("   ") == ""

    def test_stored_spellings_round_trip(self, nba_service, wnba_service):
        cases = {
            nba_service: [
                ("Luka Dončić", "Luka Doncic"),
                ("Luka Donc\u030cic", "Luka Doncic"),
                ("Nikola Jokić", "Nikola Jokic"),
                ("Nikola Jovic", "Nikola Jovic"),
                ("Michael Porter Jr.", "Michael Porter, Jr."),
                ("Xavier Tillman Sr", "Xavier Tillman, Sr."),
                ("Tim Hardaway Jr", "Tim Hardaway Jr."),
                ("Gary Payton", "Gary Payton II"),
                ("Kelly Oubre", "Kelly Oubre, Jr."),
                ("Trey Murphy", "Trey Murphy III"),
                ("Jaren Jackson Jr", "Jaren Jackson, Jr."),
                ("Shai Gilgeous Alexander", "Shai Gilgeous-Alexander"),
                ("Karl Anthony Towns", "Karl-Anthony Towns"),
                ("DeAaron Fox", "De'Aaron Fox"),
                ("Dangelo Russell", "D'Angelo Russell"),
                ("Royce ONeale", "Royce O'Neale"),
                ("Kel’el Ware", "Kel'el Ware"),
                ("AJ Green", "A.J. Green"),
                ("  PJ   WASHINGTON ", "P.J. Washington"),
                ("Jrue Holiday", "Jrue Holiday"),
            ],
            wnba_service: [
                ("  a'JA   wilson ", "A'ja Wilson"),
                ("A’ja Wilson", "A'ja Wilson"),
                ("Te Hina Paopao", "Te-Hina Paopao"),
                ("TaNiya Latson", "Ta'Niya Latson"),
                ("Flau’jae Johnson", "Flau'jae Johnson"),
                ("Betnijah Laney Hamilton", "Betnijah Laney-Hamilton"),
            ],
        }
        for service, pairs in cases.items():
            for query, stored in pairs:
                assert stored in service._all_players
                assert service.resolve_player_name(query) == stored

    def test_split_apostrophe_does_not_match_stored_name(self, nba_service):
        assert nba_service.resolve_player_name("De Aaron Fox") is None
        assert nba_service.resolve_player_name("D Angelo Russell") is None

    def test_empty_query_matches_nobody(self, nba_service, wnba_service):
        for service in (nba_service, wnba_service):
            assert service.resolve_player_name("") is None
            assert service.resolve_player_name("   ") is None
            assert match_player_name(None, service._all_players) is None
            assert match_player_name("Jr.", service._all_players) is None
            assert match_player_name("III", service._all_players) is None

    def test_every_stored_name_survives_case_and_whitespace(self, nba_service, wnba_service):
        for service in (nba_service, wnba_service):
            for name in service._all_players:
                assert service.resolve_player_name(name) == name
                assert service.resolve_player_name(f"  {name.upper()}  ") == name

    def test_csv_keys_do_not_collide_across_different_players(self, nba_service, wnba_service):
        """Two different stored players must not fold to one key.

        A shared key would make ``match_player_name`` return None for every
        non-exact query, which is a silent miss. Neither CSV has such a pair.
        """
        for league, service in (("nba", nba_service), ("wnba", wnba_service)):
            groups: dict[str, list[str]] = defaultdict(list)
            for name in service._all_players:
                groups[player_name_key(name)].append(name)
            collisions = {
                key: names for key, names in groups.items() if len(set(names)) > 1
            }
            assert collisions == {}, f"{league} player_name_key collisions: {collisions}"

    def test_synthetic_shared_key_does_not_guess_a_real_player(self, nba_service):
        real = "Gary Trent, Jr."
        assert real in nba_service._all_players
        # "Gary Trent" is not a second CSV player. Pairing him with the real
        # row is the collision the matcher must refuse to break.
        candidates = [real, "Gary Trent"]
        assert match_player_name("Gary Trent Jr.", candidates) is None
        assert match_player_name(real, candidates) == real
        assert match_player_name("Gary Trent", candidates) == "Gary Trent"


class TestUnmatchedNameCallSites:
    """Each identity lookup returns an empty result when nothing matches."""

    @pytest.mark.parametrize("league", ["nba", "wnba"])
    def test_csv_methods_reject_unknown_and_substring(self, league, nba_service, wnba_service):
        service = nba_service if league == "nba" else wnba_service
        substring = "Smith" if league == "nba" else "Wilson"
        for query in (_UNKNOWN, substring):
            stats = service.get_player_stats(query, "points", 10.5)
            assert stats["player"] == query
            assert stats["n_games"] == 0
            assert stats["p_over"] is None
            assert stats["p_under"] is None
            assert stats["game_logs"] == []
            assert "not found" in stats["message"]

            dd = service.player_dd_history(query)
            assert dd["player"] == query
            assert dd["games"] == 0
            assert dd["dd_games"] == 0
            assert dd["prob_dd"] is None
            assert dd["n_games"] == 0
            assert "not found" in dd["message"]

            assert service.get_player_opponents(query) == []
            assert service.get_teammates(query) == []
            assert service.resolve_player_name(query) is None

    def test_accented_query_does_not_return_the_near_name(self, nba_service, wnba_service):
        jokic = nba_service.get_player_stats("Nikola Jokić", "points", 20.5)
        jovic = nba_service.get_player_stats("Nikola Jovic", "points", 20.5)
        assert jokic["player"] == "Nikola Jokic"
        assert jovic["player"] == "Nikola Jovic"
        assert jokic["n_games"] > 0 and jovic["n_games"] > 0
        assert jokic["game_logs"] != jovic["game_logs"]
        assert "Nikola Jokic" not in nba_service.get_teammates("Nikola Jokić")
        assert nba_service.get_player_opponents("Nikola Jokić")

        mates = wnba_service.get_teammates("Aja Wilson")
        assert mates
        assert "A'ja Wilson" not in mates
        assert wnba_service.get_player_opponents("Aja Wilson")

    def test_historical_tools_when_nothing_matches(self):
        historical = _historical()
        for league in ("nba", "wnba"):
            assert historical._games_for(_UNKNOWN, league=league) == []
            assert historical._team_for(_UNKNOWN, "2026-02-09", league=league) == ""
            opponent = asyncio.run(
                historical._infer_opponent_from_schedule(
                    _UNKNOWN, "2026-02-09", league=league
                )
            )
            assert opponent == "unknown"

            availability = historical.get_availability_context(
                _UNKNOWN, "2026-02-09", league=league
            )
            assert availability["signal"] == "unavailable"
            assert availability["details"]["error"] == "no games"

            impact = historical.auto_teammate_impact(
                _UNKNOWN, "points", 10.5, league=league
            )
            assert impact["signal"] == "unavailable"
            assert impact["details"]["error"] == "no data"

            lineup = historical.get_lineup_context(
                _UNKNOWN, "2026-02-09", league=league
            )
            assert lineup["signal"] == "unavailable"
            assert lineup["details"]["error"] == "no data"

            rotation = historical.get_rotation_absorption_map(
                _UNKNOWN, "points", "2026-02-09", league=league
            )
            assert rotation["signal"] == "unavailable"
            assert rotation["details"]["error"] == "no data"

        assert historical._games_for("Smith", league="nba") == []
        assert historical._games_for("Curry", league="nba") == []
        assert historical._team_for("Smith", league="nba") == ""
        assert historical._games_for("Wilson", league="wnba") == []
        assert historical._team_for("Wilson", league="wnba") == ""

    def test_player_lineup_context_passes_empty_team_when_unmatched(self, monkeypatch):
        historical = _historical()
        calls: list[tuple[str, str]] = []

        async def _no_network(team, date="", league="nba"):
            calls.append((team, league))
            return historical._signal_payload(
                "unavailable", 0, 0, 0.0, "today", "lineup_consensus", {}
            )

        monkeypatch.setattr(historical, "get_projected_lineup_consensus", _no_network)
        for league in ("nba", "wnba"):
            calls.clear()
            payload = asyncio.run(
                historical.get_player_lineup_context(_UNKNOWN, league=league)
            )
            assert calls == [("", league)]
            assert payload["signal"] == "unavailable"
            assert payload["details"]["player"] == _UNKNOWN
            assert payload["details"]["canonical_player_name"] in (None, _UNKNOWN)


class TestTradeDayTeams:
    """Event-day team, the prior club when that day has no game, and no logs."""

    def test_no_logs_return_empty_string(self):
        assert team_from_game_logs(None) == ""
        assert team_from_game_logs([]) == ""
        assert team_from_game_logs([{"team": ""}, "not-a-row"]) == ""

    def test_buddy_hield_trade_day_gap_and_chart_shape(self, nba_service):
        logs = nba_service._cache["Buddy Hield"]
        # Last Warriors game is 2026-02-03. First Hawks game is 2026-02-09.
        assert team_from_game_logs(logs, "2026-02-03") == "Warriors"
        assert team_from_game_logs(logs, date(2026, 2, 6)) == "Warriors"
        assert team_from_game_logs(logs, datetime(2026, 2, 9)) == "Hawks"
        assert team_from_game_logs(logs, "02/09/2026") == "Hawks"
        assert team_from_game_logs(logs, "2026-02-09T23:00:00Z") == "Hawks"
        assert team_from_game_logs(logs) == "Hawks"

        chart = nba_service.get_player_stats("Buddy Hield", "points", 15.5)["game_logs"]
        assert chart[0]["team"] == "Warriors"
        assert chart[0]["date_full"] < chart[-1]["date_full"]
        assert team_from_game_logs(chart, "2026-02-09") == "Hawks"
        assert team_from_game_logs(chart, "2026-02-06") == "Warriors"
        # Chart rows also carry a year-less "date" label. That label is not a day.
        assert "/" in chart[-1]["date"] and chart[-1]["date"].count("/") == 1
        assert team_from_game_logs(chart, chart[-1]["date"]) == "Hawks"

    def test_mo_bamba_middle_stint_game_days(self, nba_service):
        logs = nba_service._cache["Mo Bamba"]
        assert team_from_game_logs(logs, "2025-12-29") == "Raptors"
        assert team_from_game_logs(logs, "2026-01-02") == "Raptors"
        assert team_from_game_logs(logs, "2026-03-04") == "Jazz"
        assert team_from_game_logs(logs) == "Jazz"
        assert team_from_game_logs(logs, "2025-10-16") == "Jazz"

    def test_wnba_carrington_trade_day_and_gap(self, wnba_service):
        logs = wnba_service._cache["DiJonai Carrington"]
        assert team_from_game_logs(logs, "2025-08-01") == "Wings"
        assert team_from_game_logs(logs, "2025-08-03") == "Wings"
        assert team_from_game_logs(logs, "2025-08-05") == "Lynx"
        chart = wnba_service.get_player_stats("DiJonai Carrington", "points", 10.5)
        assert chart["player"] == "DiJonai Carrington"
        assert team_from_game_logs(chart["game_logs"], "2025-08-03") == "Wings"
        assert team_from_game_logs(chart["game_logs"], "2025-08-05") == "Lynx"
        assert team_from_game_logs(chart["game_logs"]) == "Lynx"

    def test_post_midnight_utc_same_calendar_day_stays_put(self, nba_service):
        # 23:00Z is still 2026-03-15 in UTC (7pm ET). The Remix log is that day.
        logs = nba_service._cache["Jayson Kent"]
        assert team_from_game_logs(logs, "2026-03-15") == "Remix"
        assert team_from_game_logs(logs, "2026-03-15T23:00:00Z") == "Remix"
        assert team_from_game_logs(logs, "2026-03-16") == "Trail Blazers"

    def test_post_midnight_utc_commence_stays_on_us_game_date(self, nba_service):
        logs = nba_service._cache["Jayson Kent"]
        chart = nba_service.get_player_stats("Jayson Kent", "points", 8.5)["game_logs"]
        commence = "2026-03-16T00:30:00Z"
        assert team_from_game_logs(logs, commence) == "Remix"
        assert team_from_game_logs(chart, commence) == "Remix"


class TestHistoricalTeamCallSites:
    def test_lineup_and_rotation_use_event_day_team(self):
        historical = _historical()
        early = historical.get_lineup_context("Buddy Hield", "2026-02-06", league="nba")
        trade_day = historical.get_lineup_context(
            "Buddy Hield", "2026-02-09", league="nba"
        )
        assert early["details"]["team"] == "Warriors"
        assert trade_day["details"]["team"] == "Hawks"
        assert "Buddy Hield" not in {
            name for name, _count in trade_day["details"]["frequent_teammates"]
        }

        early_rot = historical.get_rotation_absorption_map(
            "Buddy Hield", "points", "2025-11-01", league="nba"
        )
        late_rot = historical.get_rotation_absorption_map(
            "Buddy Hield", "points", "2026-04-30", league="nba"
        )
        assert early_rot["details"]["team"] == "Warriors"
        assert late_rot["details"]["team"] == "Hawks"

        wings = historical.get_lineup_context(
            "DiJonai Carrington", "2025-08-03", league="wnba"
        )
        lynx = historical.get_lineup_context(
            "DiJonai Carrington", "2025-08-05", league="wnba"
        )
        assert wings["details"]["team"] == "Wings"
        assert lynx["details"]["team"] == "Lynx"
        mates = {name for name, _count in lynx["details"]["frequent_teammates"]}
        assert "DiJonai Carrington" not in mates
        wilson = historical.get_lineup_context("Aja Wilson", league="wnba")
        wilson_mates = {name for name, _count in wilson["details"]["frequent_teammates"]}
        assert "A'ja Wilson" not in wilson_mates
        assert "Aja Wilson" not in wilson_mates

    def test_auto_teammate_latest_team_without_a_date(self, monkeypatch):
        historical = _historical()
        monkeypatch.setattr(historical, "_fetch_injury_report_for_team", lambda _code: [])
        result = historical.auto_teammate_impact(
            "Buddy Hield", "points", 15.5, league="nba"
        )
        assert result["details"]["team"] == "Hawks"

    def test_lineup_sample_follows_the_event_day(self):
        historical = _historical()
        early = historical.get_lineup_context("Buddy Hield", "2025-11-01", league="nba")
        latest = historical.get_lineup_context("Buddy Hield", league="nba")
        assert early["details"]["team"] == "Warriors"
        assert latest["details"]["team"] == "Hawks"
        assert early["details"]["frequent_teammates"] != latest["details"]["frequent_teammates"]

    def test_resolved_player_is_not_his_own_star(self, monkeypatch):
        historical = _historical()
        monkeypatch.setattr(historical, "_fetch_injury_report_for_team", lambda _code: [])
        impact = historical.auto_teammate_impact(
            "Jaren Jackson Jr", "points", 12.5, league="nba"
        )
        rotation = historical.get_rotation_absorption_map(
            "Jaren Jackson Jr", "points", league="nba"
        )
        impact_stars = [row["star"] for row in impact["details"]["teammate_chemistry"]]
        rotation_stars = [row["absent_star"] for row in rotation["details"]["absorptions"]]
        assert "Jaren Jackson, Jr." not in impact_stars
        assert "Jaren Jackson, Jr." not in rotation_stars


class TestRosterAndSampleContexts:
    def test_nba_roster_cache_uses_latest_team(self):
        from app.services.lineup_source_support import _build_team_roster_cache

        cache = _build_team_roster_cache()
        assert "Buddy Hield" in cache["ATL"]
        assert "Buddy Hield" not in cache["GSW"]
        assert "Mo Bamba" in cache["UTA"]
        assert "Mo Bamba" not in cache["TOR"]

    def test_wnba_player_is_on_her_own_roster(self):
        from app.services.lineup_source_support import (
            _build_team_roster_cache,
            detect_team_code,
        )

        cache = _build_team_roster_cache()
        lynx = detect_team_code("Lynx", league="wnba")
        assert lynx == "MIN"
        assert "DiJonai Carrington" in cache.get(lynx, [])

    def test_sample_context_team_is_latest_in_the_window(self, nba_service):
        contexts = _sample_contexts()
        stats = nba_service.get_player_stats("Buddy Hield", "points", 15.5)
        assert stats["game_logs"][0]["team"] == "Warriors"
        assert (
            contexts._get_team_for_context((0, None, None, None, None), stats, {})
            == "Hawks"
        )

        last_ten = nba_service.get_player_stats("Buddy Hield", "points", 15.5, n=10)
        assert last_ten["game_logs"][0]["team"] == "Warriors"
        assert last_ten["game_logs"][-1]["team"] == "Hawks"
        assert (
            contexts._get_team_for_context((10, None, None, None, None), last_ten, {})
            == "Hawks"
        )

        missing = nba_service.get_player_stats(_UNKNOWN, "points", 15.5)
        assert missing["game_logs"] == []
        assert (
            contexts._get_team_for_context((0, None, None, None, None), missing, {})
            == ""
        )
        assert (
            contexts._get_team_for_context(
                (0, None, None, ["Not A Star"], True),
                stats,
                {"Hawks": ["Jalen Johnson"]},
            )
            == ""
        )

        star_path = os.path.join(_REPO, "data", "star_players.json")
        with open(star_path, encoding="utf-8") as handle:
            stars = json.load(handle)
        assert (
            contexts._get_team_for_context(
                (0, None, None, ["Stephen Curry"], True),
                stats,
                stars,
            )
            == "Warriors"
        )


class TestReReviewEdges:
    """Clocks and shared team codes the 096ad42 fixes did not cover."""

    def test_naive_datetime_and_date_only_string_are_not_shifted(self, nba_service):
        logs = nba_service._cache["Jayson Kent"]
        # A naive clock is already the CSV game date. 00:30 with no zone
        # stays on the 16th even though the same clock in UTC is the 15th
        # in New York.
        assert team_from_game_logs(logs, datetime(2026, 3, 16, 0, 30)) == "Trail Blazers"
        assert team_from_game_logs(logs, date(2026, 3, 16)) == "Trail Blazers"
        assert team_from_game_logs(logs, "2026-03-16") == "Trail Blazers"
        assert team_from_game_logs(logs, "03/16/2026") == "Trail Blazers"
        assert team_from_game_logs(logs, "2026-03-16T00:30:00") == "Trail Blazers"
        aware = datetime(2026, 3, 16, 0, 30, tzinfo=timezone.utc)
        assert team_from_game_logs(logs, aware) == "Remix"
        assert team_from_game_logs(logs, "2026-03-16T00:30:00Z") == "Remix"

    def test_eastern_evening_lineup_uses_the_converted_day(self):
        historical = _historical()
        evening = historical.get_lineup_context(
            "Jayson Kent", "2026-03-16T00:30:00Z", league="nba"
        )
        next_day = historical.get_lineup_context(
            "Jayson Kent", "2026-03-16", league="nba"
        )
        assert evening["details"]["team"] == "Remix"
        assert next_day["details"]["team"] == "Trail Blazers"

    def test_date_before_every_wnba_log_is_the_earliest_club(self, wnba_service):
        logs = wnba_service._cache["DiJonai Carrington"]
        assert team_from_game_logs(logs, "2020-01-01") == "Wings"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "America/New_York moves a late Pacific tip onto the next morning. "
            "2026-03-16T06:30:00Z is 10:30pm PST on 2026-03-15, and "
            "2026-03-15 22:30 America/Los_Angeles is 10:30pm local that night "
            "(05:30Z, because March 15 2026 is PDT). Kent's CSV row for that "
            "night is Remix vs Lakers. Both clocks return Trail Blazers, and "
            "get_lineup_context labels the same tip Trail Blazers."
        ),
    )
    def test_pacific_late_tip_stays_on_the_us_game_date(self, nba_service):
        logs = nba_service._cache["Jayson Kent"]
        assert team_from_game_logs(logs, "2026-03-16T06:30:00Z") == "Remix"
        pacific = datetime(2026, 3, 15, 22, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
        assert team_from_game_logs(logs, pacific) == "Remix"
        historical = _historical()
        late = historical.get_lineup_context(
            "Jayson Kent", "2026-03-16T06:30:00Z", league="nba"
        )
        assert late["details"]["team"] == "Remix"

    def test_star_list_matches_suffix_and_comma_variants(self, monkeypatch):
        historical = _historical()
        monkeypatch.setattr(historical, "_fetch_injury_report_for_team", lambda _code: [])
        queries = (
            "Jaren Jackson Jr",
            "Jaren Jackson Jr.",
            "Jaren Jackson, Jr.",
            "Jaren Jackson, Jr",
            "JAREN JACKSON JR",
        )
        for query in queries:
            impact = historical.auto_teammate_impact(
                query, "points", 12.5, league="nba"
            )
            rotation = historical.get_rotation_absorption_map(
                query, "points", league="nba"
            )
            impact_stars = [row["star"] for row in impact["details"]["teammate_chemistry"]]
            rotation_stars = [row["absent_star"] for row in rotation["details"]["absorptions"]]
            assert impact_stars == ["Lauri Markkanen"], query
            assert rotation_stars == ["Lauri Markkanen"], query
            assert "Jaren Jackson, Jr." not in impact_stars
            assert "Jaren Jackson, Jr." not in rotation_stars

    def test_injury_row_matches_suffix_and_comma_spelling(self, monkeypatch):
        historical = _historical()

        def _injuries(_code):
            return [
                {
                    "player": "Jaren Jackson, Jr.",
                    "position": "PF",
                    "status": "Out",
                    "injury": "ankle",
                    "source": "test",
                }
            ]

        monkeypatch.setattr(historical, "_fetch_injury_report_for_team", _injuries)
        availability = historical.get_availability_context(
            "Jaren Jackson Jr", "2026-03-01", league="nba"
        )
        assert availability["details"]["status"] == "Out"
        # The odds-board scan uses this same helper on outcome descriptions.
        assert historical._is_same_player("Nikola Jokić", "Nikola Jokic")
        assert historical._is_same_player("Gary Trent, Jr.", "gary trent jr")
        assert not historical._is_same_player("Nikola Jokić", "Nikola Jovic")

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Shared codes are one list. TOR holds Tyreke Key (Raptors) and "
            "Teonni Key (Tempo). resolve_canonical_player_name('T. Key', 'TOR') "
            "returns ambiguous_team_match. Each league has only one T. Key."
        ),
    )
    def test_shared_team_code_initials_do_not_cross_leagues(self):
        from app.services.lineup_source_support import (
            _build_team_roster_cache,
            resolve_canonical_player_name,
        )

        cache = _build_team_roster_cache()
        assert "Tyreke Key" in cache["TOR"]
        resolved = resolve_canonical_player_name("T. Key", "TOR")
        assert resolved["resolution_status"] == "team_resolved"
        assert resolved["canonical_name"] == "Tyreke Key"
        assert "Teonni Key" not in cache["TOR"]

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "canonical_team_code and historical._team_code_from_name only "
            "know NBA aliases. WNBA daily picks and the injury/odds paths "
            "send nicknames through them, so Lynx stays 'LYNX' / 'Lynx' "
            "instead of MIN and Wings stays 'WINGS'."
        ),
    )
    def test_wnba_nickname_uses_the_wnba_team_code(self):
        from app.services.daily_analysis import canonical_team_code

        historical = _historical()
        assert canonical_team_code("Lynx") == "MIN"
        assert canonical_team_code("Wings") == "DAL"
        assert historical._team_code_from_name("Lynx") == "MIN"
        assert historical._team_code_from_name("Wings") == "DAL"
