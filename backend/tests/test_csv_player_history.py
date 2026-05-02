"""
Tests for CSVPlayerHistoryService

Covers:
- CSV loading and caching
- get_player_stats probability calculations
- DNP filtering
- Insufficient data / empty CSV / player not found
- get_all_players with and without search
- Different metrics (points, rebounds, assists, pra)
- Histogram calculation
- Opponent and starter filters
- Teammate filter logic
- Fuzzy player name matching
- _parse_minutes and _parse_float helpers
"""

import os
import sys
import csv
import tempfile
from datetime import datetime
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.csv_player_history import CSVPlayerHistoryService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv(rows, tmp_dir=None):
    """Write a temporary CSV file from a list of dicts and return the path."""
    fieldnames = [
        "Player", "Team", "Opponent", "Date", "Season", "W/L", "Pos",
        "Status", "MIN", "PTS", "AST", "REB", "ORB", "DRB",
        "FGM", "FGA", "FG%", "3PM", "3PA", "3P%",
        "FTM", "FTA", "FT%", "STL", "BLK", "TOV", "PF", "FIC",
    ]
    fd, path = tempfile.mkstemp(suffix=".csv", dir=tmp_dir)
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


SAMPLE_ROWS = [
    # Stephen Curry - 5 games with varied stats
    {
        "Player": "Stephen Curry", "Team": "Warriors", "Opponent": "Lakers",
        "Date": "01/10/2025", "Season": "2024-25", "W/L": "W", "Pos": "PG",
        "Status": "Starter", "MIN": "34:20",
        "PTS": "30", "AST": "8", "REB": "5", "ORB": "1", "DRB": "4",
        "FGM": "10", "FGA": "20", "FG%": "0.500",
        "3PM": "5", "3PA": "10", "3P%": "0.500",
        "FTM": "5", "FTA": "5", "FT%": "1.000",
        "STL": "2", "BLK": "0", "TOV": "3", "PF": "2", "FIC": "20",
    },
    {
        "Player": "Stephen Curry", "Team": "Warriors", "Opponent": "Celtics",
        "Date": "01/08/2025", "Season": "2024-25", "W/L": "L", "Pos": "PG",
        "Status": "Starter", "MIN": "36:00",
        "PTS": "25", "AST": "6", "REB": "4", "ORB": "0", "DRB": "4",
        "FGM": "9", "FGA": "22", "FG%": "0.409",
        "3PM": "4", "3PA": "12", "3P%": "0.333",
        "FTM": "3", "FTA": "3", "FT%": "1.000",
        "STL": "1", "BLK": "0", "TOV": "2", "PF": "1", "FIC": "16",
    },
    {
        "Player": "Stephen Curry", "Team": "Warriors", "Opponent": "Suns",
        "Date": "01/06/2025", "Season": "2024-25", "W/L": "W", "Pos": "PG",
        "Status": "Starter", "MIN": "32:10",
        "PTS": "22", "AST": "10", "REB": "6", "ORB": "1", "DRB": "5",
        "FGM": "8", "FGA": "18", "FG%": "0.444",
        "3PM": "3", "3PA": "9", "3P%": "0.333",
        "FTM": "3", "FTA": "4", "FT%": "0.750",
        "STL": "0", "BLK": "1", "TOV": "4", "PF": "3", "FIC": "18",
    },
    {
        "Player": "Stephen Curry", "Team": "Warriors", "Opponent": "Lakers",
        "Date": "01/04/2025", "Season": "2024-25", "W/L": "W", "Pos": "PG",
        "Status": "Starter", "MIN": "30:45",
        "PTS": "35", "AST": "5", "REB": "3", "ORB": "0", "DRB": "3",
        "FGM": "12", "FGA": "21", "FG%": "0.571",
        "3PM": "6", "3PA": "11", "3P%": "0.545",
        "FTM": "5", "FTA": "6", "FT%": "0.833",
        "STL": "3", "BLK": "0", "TOV": "1", "PF": "2", "FIC": "25",
    },
    # A DNP game (0 minutes)
    {
        "Player": "Stephen Curry", "Team": "Warriors", "Opponent": "Nets",
        "Date": "01/02/2025", "Season": "2024-25", "W/L": "W", "Pos": "PG",
        "Status": "", "MIN": "0:00",
        "PTS": "0", "AST": "0", "REB": "0", "ORB": "0", "DRB": "0",
        "FGM": "0", "FGA": "0", "FG%": "", "3PM": "0", "3PA": "0",
        "3P%": "", "FTM": "0", "FTA": "0", "FT%": "",
        "STL": "0", "BLK": "0", "TOV": "0", "PF": "0", "FIC": "0",
    },
    # Another player - bench
    {
        "Player": "Klay Thompson", "Team": "Warriors", "Opponent": "Lakers",
        "Date": "01/10/2025", "Season": "2024-25", "W/L": "W", "Pos": "SG",
        "Status": "Bench", "MIN": "28:00",
        "PTS": "18", "AST": "2", "REB": "3", "ORB": "0", "DRB": "3",
        "FGM": "7", "FGA": "15", "FG%": "0.467",
        "3PM": "4", "3PA": "9", "3P%": "0.444",
        "FTM": "0", "FTA": "0", "FT%": "",
        "STL": "1", "BLK": "0", "TOV": "1", "PF": "2", "FIC": "12",
    },
    {
        "Player": "Klay Thompson", "Team": "Warriors", "Opponent": "Celtics",
        "Date": "01/08/2025", "Season": "2024-25", "W/L": "L", "Pos": "SG",
        "Status": "Starter", "MIN": "30:00",
        "PTS": "22", "AST": "3", "REB": "5", "ORB": "1", "DRB": "4",
        "FGM": "8", "FGA": "18", "FG%": "0.444",
        "3PM": "5", "3PA": "10", "3P%": "0.500",
        "FTM": "1", "FTA": "2", "FT%": "0.500",
        "STL": "0", "BLK": "1", "TOV": "2", "PF": "3", "FIC": "15",
    },
]


@pytest.fixture
def csv_path(tmp_path):
    """Create a temp CSV and return its path."""
    return _make_csv(SAMPLE_ROWS, tmp_dir=str(tmp_path))


@pytest.fixture
def service(csv_path):
    """Return a CSVPlayerHistoryService that reads from the temp CSV."""
    svc = CSVPlayerHistoryService()
    with patch("app.services.csv_player_history.CSV_PATH", csv_path):
        svc.load_csv()
    return svc


@pytest.fixture
def empty_service(tmp_path):
    """Return a service backed by an empty CSV (header only, no rows)."""
    path = _make_csv([], tmp_dir=str(tmp_path))
    svc = CSVPlayerHistoryService()
    with patch("app.services.csv_player_history.CSV_PATH", path):
        svc.load_csv()
    return svc


# ---------------------------------------------------------------------------
# CSV Loading
# ---------------------------------------------------------------------------


class TestLoadCSV:

    def test_load_csv_populates_cache(self, service):
        assert service._loaded is True
        assert len(service._cache) > 0

    def test_load_csv_sets_all_players_sorted(self, service):
        assert service._all_players == sorted(service._all_players)

    def test_load_csv_idempotent(self, csv_path):
        """Calling load_csv twice does not re-read the file."""
        svc = CSVPlayerHistoryService()
        with patch("app.services.csv_player_history.CSV_PATH", csv_path):
            svc.load_csv()
            first_cache_id = id(svc._cache)
            svc.load_csv()
            # Same dict object - not recreated
            assert id(svc._cache) == first_cache_id

    def test_load_csv_file_not_found(self, tmp_path):
        svc = CSVPlayerHistoryService()
        with patch(
            "app.services.csv_player_history.CSV_PATH",
            str(tmp_path / "does_not_exist.csv"),
        ):
            with pytest.raises(FileNotFoundError):
                svc.load_csv()

    def test_load_csv_game_logs_sorted_most_recent_first(self, service):
        logs = service._cache["Stephen Curry"]
        dates = [g["game_date"] for g in logs if g["game_date"]]
        for i in range(len(dates) - 1):
            assert dates[i] >= dates[i + 1]


# ---------------------------------------------------------------------------
# get_all_players
# ---------------------------------------------------------------------------


class TestGetAllPlayers:

    def test_returns_all_players(self, service):
        players = service.get_all_players()
        assert "Stephen Curry" in players
        assert "Klay Thompson" in players
        assert len(players) == 2

    def test_search_filter_case_insensitive(self, service):
        result = service.get_all_players(search="curry")
        assert result == ["Stephen Curry"]

    def test_search_no_match(self, service):
        result = service.get_all_players(search="Nonexistent")
        assert result == []

    def test_empty_csv_returns_empty_list(self, empty_service):
        assert empty_service.get_all_players() == []


# ---------------------------------------------------------------------------
# get_player_stats - basic probability calculations
# ---------------------------------------------------------------------------


class TestGetPlayerStatsBasic:

    def test_returns_correct_keys(self, service):
        result = service.get_player_stats("Stephen Curry", "points", 24.5)
        expected_keys = {
            "player", "metric", "threshold", "n_games",
            "p_over", "p_under", "mean", "std",
            "histogram", "game_logs", "opponents", "teammates",
            "equal_count", "opponent_filter", "teammate_filter",
            "teammate_played", "message",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_over_under_probabilities(self, service):
        # Curry points: 30, 25, 22, 35 (DNP excluded by default)
        # threshold=24.5 -> over: 30, 25, 35 = 3/4; under: 22 = 1/4
        result = service.get_player_stats("Stephen Curry", "points", 24.5)
        assert result["n_games"] == 4
        assert result["p_over"] == 0.75
        assert result["p_under"] == 0.25

    def test_mean_and_std(self, service):
        result = service.get_player_stats("Stephen Curry", "points", 24.5)
        # mean of [30, 25, 22, 35] = 28.0
        assert result["mean"] == 28.0
        assert result["std"] is not None
        assert result["std"] > 0

    def test_all_over(self, service):
        # All Curry points > 10
        result = service.get_player_stats("Stephen Curry", "points", 10.0)
        assert result["p_over"] == 1.0
        assert result["p_under"] == 0.0

    def test_all_under(self, service):
        # All Curry points < 50
        result = service.get_player_stats("Stephen Curry", "points", 50.0)
        assert result["p_over"] == 0.0
        assert result["p_under"] == 1.0

    def test_equal_count(self, service):
        # threshold exactly on a value
        result = service.get_player_stats("Stephen Curry", "points", 25.0)
        assert result["equal_count"] == 1

    def test_message_is_none_on_success(self, service):
        result = service.get_player_stats("Stephen Curry", "points", 24.5)
        assert result["message"] is None


# ---------------------------------------------------------------------------
# Different metrics
# ---------------------------------------------------------------------------


class TestGetPlayerStatsMetrics:

    def test_assists(self, service):
        # Curry assists: 8, 6, 10, 5
        result = service.get_player_stats("Stephen Curry", "assists", 6.5)
        assert result["n_games"] == 4
        # over 6.5: 8, 10 => 2/4
        assert result["p_over"] == 0.5

    def test_rebounds(self, service):
        # Curry rebounds: 5, 4, 6, 3
        result = service.get_player_stats("Stephen Curry", "rebounds", 4.5)
        assert result["n_games"] == 4
        # over 4.5: 5, 6 => 2/4
        assert result["p_over"] == 0.5

    def test_pra(self, service):
        # PRA = pts + reb + ast
        # 30+5+8=43, 25+4+6=35, 22+6+10=38, 35+3+5=43
        result = service.get_player_stats("Stephen Curry", "pra", 40.0)
        assert result["n_games"] == 4
        # over 40: 43, 43 => 2/4
        assert result["p_over"] == 0.5


# ---------------------------------------------------------------------------
# DNP exclusion
# ---------------------------------------------------------------------------


class TestExcludeDNP:

    def test_exclude_dnp_true_skips_zero_minutes(self, service):
        result = service.get_player_stats(
            "Stephen Curry", "points", 24.5, exclude_dnp=True
        )
        assert result["n_games"] == 4  # DNP game excluded

    def test_exclude_dnp_false_includes_zero_minutes(self, service):
        result = service.get_player_stats(
            "Stephen Curry", "points", 24.5, exclude_dnp=False
        )
        assert result["n_games"] == 5  # DNP game included


# ---------------------------------------------------------------------------
# Last N games
# ---------------------------------------------------------------------------


class TestLastNGames:

    def test_n_limits_games(self, service):
        result = service.get_player_stats("Stephen Curry", "points", 24.5, n=2)
        assert result["n_games"] == 2

    def test_n_zero_means_all(self, service):
        result = service.get_player_stats("Stephen Curry", "points", 24.5, n=0)
        assert result["n_games"] == 4

    def test_n_larger_than_available(self, service):
        result = service.get_player_stats("Stephen Curry", "points", 24.5, n=100)
        assert result["n_games"] == 4


# ---------------------------------------------------------------------------
# Player not found / insufficient data
# ---------------------------------------------------------------------------


class TestPlayerNotFound:

    def test_nonexistent_player(self, service):
        result = service.get_player_stats("Nonexistent Player", "points", 20.0)
        assert result["n_games"] == 0
        assert result["p_over"] is None
        assert result["p_under"] is None
        assert result["mean"] is None
        assert result["message"] is not None
        assert "not found" in result["message"]

    def test_empty_csv_player_stats(self, empty_service):
        result = empty_service.get_player_stats("Anyone", "points", 10.0)
        assert result["n_games"] == 0
        assert result["p_over"] is None

    def test_fuzzy_match_partial_name(self, service):
        """Partial name triggers fuzzy matching."""
        result = service.get_player_stats("Curry", "points", 24.5)
        # Should match "Stephen Curry" via fuzzy logic
        assert result["n_games"] > 0
        assert result["player"] == "Stephen Curry"


# ---------------------------------------------------------------------------
# Opponent filter
# ---------------------------------------------------------------------------


class TestOpponentFilter:

    def test_filter_by_opponent(self, service):
        result = service.get_player_stats(
            "Stephen Curry", "points", 24.5, opponent="Lakers"
        )
        # Curry vs Lakers: 30, 35 => n_games=2
        assert result["n_games"] == 2
        for log in result["game_logs"]:
            assert log["opponent"] == "Lakers"

    def test_filter_opponent_no_games(self, service):
        result = service.get_player_stats(
            "Stephen Curry", "points", 24.5, opponent="NonexistentTeam"
        )
        assert result["n_games"] == 0
        assert result["p_over"] is None


# ---------------------------------------------------------------------------
# Starter filter
# ---------------------------------------------------------------------------


class TestStarterFilter:

    def test_starters_only(self, service):
        # All 4 non-DNP Curry games are "Starter"
        result = service.get_player_stats(
            "Stephen Curry", "points", 24.5, is_starter=True
        )
        assert result["n_games"] == 4

    def test_bench_only_klay(self, service):
        # Klay has 1 bench game and 1 starter game
        result = service.get_player_stats(
            "Klay Thompson", "points", 15.0, is_starter=False
        )
        assert result["n_games"] == 1
        for log in result["game_logs"]:
            assert log["is_starter"] is False


# ---------------------------------------------------------------------------
# game_logs ordering (oldest first for chart)
# ---------------------------------------------------------------------------


class TestGameLogsOrdering:

    def test_game_logs_oldest_first(self, service):
        result = service.get_player_stats("Stephen Curry", "points", 24.5)
        dates = [g["date_full"] for g in result["game_logs"]]
        for i in range(len(dates) - 1):
            assert dates[i] <= dates[i + 1]


# ---------------------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------------------


class TestHistogram:

    def test_histogram_returned(self, service):
        result = service.get_player_stats("Stephen Curry", "points", 24.5)
        assert isinstance(result["histogram"], list)
        assert len(result["histogram"]) > 0

    def test_histogram_bin_structure(self, service):
        result = service.get_player_stats("Stephen Curry", "points", 24.5, bins=5)
        for b in result["histogram"]:
            assert "binStart" in b
            assert "binEnd" in b
            assert "count" in b

    def test_histogram_total_count(self, service):
        result = service.get_player_stats("Stephen Curry", "points", 24.5, bins=5)
        total = sum(b["count"] for b in result["histogram"])
        assert total == result["n_games"]


# ---------------------------------------------------------------------------
# _calculate_histogram edge cases
# ---------------------------------------------------------------------------


class TestCalculateHistogram:

    def test_empty_values(self, service):
        assert service._calculate_histogram([], 10) == []

    def test_bins_zero(self, service):
        assert service._calculate_histogram([1, 2, 3], 0) == []

    def test_all_same_value(self, service):
        hist = service._calculate_histogram([5.0, 5.0, 5.0], 10)
        assert len(hist) == 1
        assert hist[0]["count"] == 3
        assert hist[0]["binStart"] == hist[0]["binEnd"]


# ---------------------------------------------------------------------------
# _parse_minutes
# ---------------------------------------------------------------------------


class TestParseMinutes:

    def setup_method(self):
        self.svc = CSVPlayerHistoryService()

    def test_mm_ss(self):
        assert self.svc._parse_minutes("32:15") == pytest.approx(32.25)

    def test_integer(self):
        assert self.svc._parse_minutes("32") == 32.0

    def test_float_string(self):
        assert self.svc._parse_minutes("32.5") == 32.5

    def test_empty_string(self):
        assert self.svc._parse_minutes("") == 0.0

    def test_none_value(self):
        assert self.svc._parse_minutes(None) == 0.0

    def test_whitespace_only(self):
        assert self.svc._parse_minutes("   ") == 0.0

    def test_invalid(self):
        assert self.svc._parse_minutes("abc") == 0.0

    def test_colon_with_invalid_parts(self):
        assert self.svc._parse_minutes("ab:cd") == 0.0

    def test_zero_minutes(self):
        assert self.svc._parse_minutes("0:00") == 0.0


# ---------------------------------------------------------------------------
# _parse_float
# ---------------------------------------------------------------------------


class TestParseFloat:

    def setup_method(self):
        self.svc = CSVPlayerHistoryService()

    def test_valid_float(self):
        assert self.svc._parse_float("3.14") == pytest.approx(3.14)

    def test_valid_integer_string(self):
        assert self.svc._parse_float("10") == 10.0

    def test_empty_string(self):
        assert self.svc._parse_float("") is None

    def test_none_value(self):
        assert self.svc._parse_float(None) is None

    def test_whitespace_only(self):
        assert self.svc._parse_float("   ") is None

    def test_invalid_string(self):
        assert self.svc._parse_float("abc") is None

    def test_whitespace_padding(self):
        assert self.svc._parse_float("  42  ") == 42.0


# ---------------------------------------------------------------------------
# get_player_opponents
# ---------------------------------------------------------------------------


class TestGetPlayerOpponents:

    def test_opponents_list(self, service):
        opps = service.get_player_opponents("Stephen Curry")
        assert "Lakers" in opps
        assert "Celtics" in opps
        assert "Suns" in opps
        assert "Nets" in opps  # DNP game still has opponent recorded
        assert opps == sorted(opps)

    def test_nonexistent_player(self, service):
        opps = service.get_player_opponents("Nobody")
        assert opps == []


# ---------------------------------------------------------------------------
# Teammates
# ---------------------------------------------------------------------------


class TestGetTeammates:

    def test_teammates_excludes_self(self, service):
        teammates = service.get_teammates("Stephen Curry")
        assert "Stephen Curry" not in teammates

    def test_teammates_includes_same_team(self, service):
        teammates = service.get_teammates("Stephen Curry")
        # Klay played on Warriors on same dates, should appear as teammate
        assert "Klay Thompson" in teammates

    def test_nonexistent_player_empty(self, service):
        assert service.get_teammates("Nobody") == []


# ---------------------------------------------------------------------------
# Teammate filter in get_player_stats
# ---------------------------------------------------------------------------


class TestTeammateFilter:

    def test_teammate_played_true(self, service):
        # Klay played on 01/10 and 01/08. Curry also played those dates.
        result = service.get_player_stats(
            "Stephen Curry", "points", 0.0,
            teammate_filter=["Klay Thompson"],
            teammate_played=True,
        )
        # Curry games on dates where Klay also played:
        # 01/10 (both played), 01/08 (both played)
        assert result["n_games"] == 2

    def test_teammate_played_false(self, service):
        result = service.get_player_stats(
            "Stephen Curry", "points", 0.0,
            teammate_filter=["Klay Thompson"],
            teammate_played=False,
        )
        # Curry games on dates Klay did NOT play:
        # 01/06 and 01/04
        assert result["n_games"] == 2

    def test_invalid_teammate_ignored(self, service):
        result = service.get_player_stats(
            "Stephen Curry", "points", 24.5,
            teammate_filter=["Not A Teammate"],
            teammate_played=True,
        )
        # Invalid teammate gets filtered out, no teammate filter applied
        assert result["n_games"] == 4


# ---------------------------------------------------------------------------
# Reload
# ---------------------------------------------------------------------------


class TestReload:

    def test_reload_clears_and_reloads(self, csv_path):
        svc = CSVPlayerHistoryService()
        with patch("app.services.csv_player_history.CSV_PATH", csv_path):
            svc.load_csv()
            assert svc._loaded is True
            svc.reload()
            assert svc._loaded is True
            assert len(svc._all_players) == 2


# ---------------------------------------------------------------------------
# REB fallback (ORB + DRB when REB column is empty)
# ---------------------------------------------------------------------------


class TestREBFallback:

    def test_reb_calculated_from_orb_drb(self, tmp_path):
        rows = [
            {
                "Player": "Test Player", "Team": "Test", "Opponent": "Opp",
                "Date": "01/01/2025", "Season": "2024-25", "W/L": "W",
                "Pos": "SF", "Status": "Starter", "MIN": "30:00",
                "PTS": "10", "AST": "5", "REB": "",  # empty REB
                "ORB": "3", "DRB": "7",
                "FGM": "", "FGA": "", "FG%": "", "3PM": "", "3PA": "",
                "3P%": "", "FTM": "", "FTA": "", "FT%": "",
                "STL": "", "BLK": "", "TOV": "", "PF": "", "FIC": "",
            },
        ]
        path = _make_csv(rows, tmp_dir=str(tmp_path))
        svc = CSVPlayerHistoryService()
        with patch("app.services.csv_player_history.CSV_PATH", path):
            svc.load_csv()
        result = svc.get_player_stats("Test Player", "rebounds", 5.0)
        assert result["n_games"] == 1
        # 3 + 7 = 10
        assert result["mean"] == 10.0


# ---------------------------------------------------------------------------
# Date parsing formats
# ---------------------------------------------------------------------------


class TestDateParsing:

    def test_alternative_date_format(self, tmp_path):
        rows = [
            {
                "Player": "Date Test", "Team": "T", "Opponent": "O",
                "Date": "2025-03-15",  # YYYY-MM-DD format
                "Season": "", "W/L": "", "Pos": "", "Status": "",
                "MIN": "25", "PTS": "20", "AST": "5", "REB": "5",
                "ORB": "", "DRB": "",
                "FGM": "", "FGA": "", "FG%": "", "3PM": "", "3PA": "",
                "3P%": "", "FTM": "", "FTA": "", "FT%": "",
                "STL": "", "BLK": "", "TOV": "", "PF": "", "FIC": "",
            },
        ]
        path = _make_csv(rows, tmp_dir=str(tmp_path))
        svc = CSVPlayerHistoryService()
        with patch("app.services.csv_player_history.CSV_PATH", path):
            svc.load_csv()
        logs = svc._cache["Date Test"]
        assert logs[0]["game_date"] == datetime(2025, 3, 15)

    def test_invalid_date_yields_none(self, tmp_path):
        rows = [
            {
                "Player": "Bad Date", "Team": "T", "Opponent": "O",
                "Date": "not-a-date",
                "Season": "", "W/L": "", "Pos": "", "Status": "",
                "MIN": "25", "PTS": "20", "AST": "5", "REB": "5",
                "ORB": "", "DRB": "",
                "FGM": "", "FGA": "", "FG%": "", "3PM": "", "3PA": "",
                "3P%": "", "FTM": "", "FTA": "", "FT%": "",
                "STL": "", "BLK": "", "TOV": "", "PF": "", "FIC": "",
            },
        ]
        path = _make_csv(rows, tmp_dir=str(tmp_path))
        svc = CSVPlayerHistoryService()
        with patch("app.services.csv_player_history.CSV_PATH", path):
            svc.load_csv()
        logs = svc._cache["Bad Date"]
        assert logs[0]["game_date"] is None


# ---------------------------------------------------------------------------
# get_players_in_game
# ---------------------------------------------------------------------------


class TestGetPlayersInGame:

    def test_returns_players_for_date(self, service):
        players = service.get_players_in_game("Warriors", datetime(2025, 1, 10))
        assert "Stephen Curry" in players
        assert "Klay Thompson" in players

    def test_no_players_for_unknown_date(self, service):
        players = service.get_players_in_game("Warriors", datetime(2099, 1, 1))
        assert len(players) == 0
