"""QA edges for SPO-113 field enrichment.

External API bodies are not rebuilt here. Season boundaries are read from
the recorded ESPN season documents. Rank cases use in-memory game-log
rows or the shipped CSV.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.models.schemas import NBAEvent
from app.services.csv_player_history import (
    CSVPlayerHistoryService,
    csv_player_service,
)
from app.services.daily_analysis import canonical_team_code
from app.services.defense_ranks import (
    build_defense_rank_table,
    fill_null_defense_ranks,
    nba_defense_table,
)
from app.services.event_fields import enrich_nba_event
from app.services.lineup_service import confirmation_status
from app.services.nba_season import recorded_nba_season_label

_SEASONS = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "espn" / "seasons"
)
_CHICAGO = ZoneInfo("America/Chicago")
_NBA_CODES = {
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}
_CSV_RANK_NOTE = "Computed from real points allowed, not fantasy points."
_HEADER = [
    "Player",
    "Season",
    "GameType",
    "Date",
    "Team",
    "Opponent",
    "Status",
    "Pos",
    "MIN",
    "PTS",
    "REB",
    "AST",
]


def _utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _window(filename: str) -> tuple[str, str, str]:
    """Date prefix and CSV label from one recorded ESPN season file."""
    document = json.loads((_SEASONS / filename).read_text(encoding="utf-8"))
    start = str(document["startDate"])[:10]
    end = str(document["endDate"])[:10]
    label = recorded_nba_season_label(_utc(*map(int, start.split("-"))))
    return start, end, label


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_HEADER)
        writer.writeheader()
        for row in rows:
            full = {column: "" for column in _HEADER}
            full.update(row)
            writer.writerow(full)


def _log(
    player: str,
    when: str,
    team: str,
    opponent: str,
    points: str,
    *,
    season: str = "2025-2026",
    game_type: str = "regular_season",
    minutes: str = "30:00",
    pos: str = "PG",
    rebounds: str = "5",
) -> dict[str, str]:
    return {
        "Player": player,
        "Season": season,
        "GameType": game_type,
        "Date": when,
        "Team": team,
        "Opponent": opponent,
        "Status": "Starter",
        "Pos": pos,
        "MIN": minutes,
        "PTS": points,
        "REB": rebounds,
        "AST": "1",
    }


def _service(path: Path) -> CSVPlayerHistoryService:
    import app.services.csv_player_history as history

    service = CSVPlayerHistoryService(league="nba")
    previous = history.CSV_PATH
    history.CSV_PATH = str(path)
    try:
        service.load_csv()
    finally:
        history.CSV_PATH = previous
    return service


def _game(
    team: str,
    opponent: str,
    points: float,
    *,
    pos: str = "PG",
    when: datetime | None = None,
    game_type: str = "regular_season",
    season: str = "2025-2026",
    minutes: float = 30,
) -> dict:
    return {
        "team": team,
        "opponent": opponent,
        "points": points,
        "pos": pos,
        "game_date": when or datetime(2025, 11, 1),
        "season": season,
        "game_type": game_type,
        "minutes": minutes,
    }


def _confirmed(starters: list[str] | None = None) -> dict:
    return {
        "starters": starters or ["A", "B", "C", "D", "E"],
        "updated_at": "2020-01-01T00:00:00+00:00",
        "source_snapshots": {
            "rotowire": {
                "status": "confirmed",
                "updated_at": "2020-01-01T00:00:00+00:00",
            },
            "rotogrinders": {
                "status": "projected",
                "updated_at": "2026-11-10T18:00:00+00:00",
            },
        },
    }


class TestDefenseRankScale:
    def test_rank_one_is_the_most_points_allowed(self):
        # Celtics allowed 50 points. Lakers allowed 10. Rebounds run the
        # other way and are not an input to the rank.
        table = build_defense_rank_table(
            [
                _game("Lakers", "Celtics", 50),
                _game("Celtics", "Lakers", 10),
            ]
        )
        assert table.overall["BOS"] == 1
        assert table.overall["LAL"] == 2
        assert table.by_position[("BOS", "PG")] < table.by_position[("LAL", "PG")]

    def test_ties_break_by_team_code_and_stay_unique(self):
        table = build_defense_rank_table(
            [
                _game("Lakers", "Celtics", 20),
                _game("Celtics", "Lakers", 20),
            ]
        )
        assert table.overall["BOS"] == 1
        assert table.overall["LAL"] == 2
        assert len(set(table.overall.values())) == len(table.overall)

    def test_position_rank_is_within_that_position(self):
        # Lakers allowed 100 to centers. Celtics allowed 40 to point guards.
        # Each of those is the most allowed at its own position, so both
        # ranks are 1. A single list of every team-position pair gives
        # the center total rank 1 and the guard total rank 2.
        table = build_defense_rank_table(
            [
                _game("Celtics", "Lakers", 100, pos="C"),
                _game("Lakers", "Celtics", 40, pos="PG"),
            ]
        )
        assert table.by_position[("LAL", "C")] == 1
        assert table.by_position[("BOS", "PG")] == 1
        assert max(table.by_position.values()) <= 30
        for position in ("PG", "SG", "SF", "PF", "C"):
            ranks = [
                rank
                for (team, spot), rank in table.by_position.items()
                if spot == position
            ]
            assert ranks
            assert sorted(ranks) == list(range(1, len(ranks) + 1))

    def test_fallback_never_emits_a_rank_outside_1_to_30(self):
        games = [
            _game(f"Club{index:02d}", f"Opp{index:02d}", float(index + 1))
            for index in range(31)
        ]
        table = build_defense_rank_table(games)
        assert table.overall
        assert min(table.overall.values()) >= 1
        assert max(table.overall.values()) <= 30
        assert max(table.by_position.values()) <= 30

    def test_shipped_overall_ranks_are_unique_and_inside_1_to_30(self):
        table = nba_defense_table()
        ranks = list(table.overall.values())
        assert ranks
        assert min(ranks) == 1
        assert max(ranks) == len(ranks)
        assert max(ranks) <= 30
        assert table.season == "2025-2026"
        assert recorded_nba_season_label(_utc(2026, 11, 10)) == "2026-2027"

    def test_shipped_position_ranks_stay_inside_1_to_30(self):
        table = nba_defense_table()
        assert table.by_position
        offenders = {
            key: rank
            for key, rank in table.by_position.items()
            if rank < 1 or rank > 30
        }
        assert offenders == {}
        for position in ("PG", "SG", "SF", "PF", "C"):
            ranks = [
                rank
                for (team, spot), rank in table.by_position.items()
                if spot == position
            ]
            assert len(ranks) == len(set(ranks))
            assert min(ranks) == 1
            assert max(ranks) <= 30

    def test_philadelphia_resolves_through_the_sixers_spelling(self):
        table = nba_defense_table()
        assert "PHI" in table.overall
        assert "SIXERS" not in table.overall
        for opponent in ("PHI", "Philadelphia 76ers", "76ers", "Sixers"):
            filled = fill_null_defense_ranks(
                {
                    "opponent": opponent,
                    "position": "PG",
                    "opponent_rank": None,
                    "opponent_position_rank": None,
                },
                table,
            )
            assert filled["opponent_rank"] is not None
            assert 1 <= filled["opponent_rank"] <= 30
            assert filled["opponent_position_rank"] is not None
            assert 1 <= filled["opponent_position_rank"] <= 30

    def test_an_out_of_range_input_is_replaced_from_the_csv(self):
        table = build_defense_rank_table([_game("Lakers", "Celtics", 20)])
        kept = fill_null_defense_ranks(
            {
                "opponent": "BOS",
                "position": "PG",
                "opponent_rank": 0,
                "opponent_position_rank": 31,
            },
            table,
        )
        assert kept["opponent_rank"] == table.overall["BOS"]
        assert kept["opponent_position_rank"] == table.by_position[("BOS", "PG")]
        assert kept["opponent_rank_source"] == "csv"

    def test_preseason_and_zero_point_rows_do_not_invent_a_defense(self):
        table = build_defense_rank_table(
            [
                _game("Lakers", "Celtics", 40, game_type="preseason"),
                _game("Lakers", "Celtics", 0, game_type="playoffs"),
            ]
        )
        assert table.overall == {}


class TestLineupConfirmationEdges:
    def test_stale_confirmed_snapshot_still_beats_a_fresh_projection(self):
        # The consensus rule does not read updated_at. A 2020 RotoWire
        # confirmation beats a same-day RotoGrinders projection.
        assert confirmation_status(_confirmed()) == "confirmed"

    def test_partial_completeness_can_still_be_confirmed(self):
        lineup = _confirmed(starters=["A", "B"])
        lineup["status"] = "partial"
        assert lineup["status"] == "partial"
        assert confirmation_status(lineup) == "confirmed"

    def test_one_club_confirmed_does_not_confirm_the_other(self):
        event = NBAEvent(
            event_id="evt-1",
            sport_key="basketball_nba",
            home_team="Los Angeles Lakers",
            away_team="Boston Celtics",
            commence_time="2026-01-15T01:00:00Z",
        )
        only_home = enrich_nba_event(event, {"LAL": _confirmed()})
        assert only_home.lineup_status is not None
        assert only_home.lineup_status.home == "confirmed"
        assert only_home.lineup_status.away is None

        both = enrich_nba_event(
            event,
            {"LAL": _confirmed(), "BOS": _confirmed()},
        )
        assert both.lineup_status is not None
        assert both.lineup_status.home == "confirmed"
        assert both.lineup_status.away == "confirmed"

        projected = {
            "starters": ["A"],
            "source_snapshots": {
                "rotowire": {"status": "expected"},
                "rotogrinders": {"status": "projected"},
            },
        }
        split = enrich_nba_event(event, {"LAL": _confirmed(), "BOS": projected})
        assert split.lineup_status is not None
        assert split.lineup_status.home == "confirmed"
        assert split.lineup_status.away == "projected"


class TestSeasonWindow:
    def test_recorded_window_edges_are_inclusive_on_the_utc_date(self):
        expectations = {
            "nba_2025.json": "2024-2025",
            "nba_2026.json": "2025-2026",
            "nba_2027.json": "2026-2027",
        }
        for filename, label in expectations.items():
            start, end, resolved = _window(filename)
            assert resolved == label
            assert recorded_nba_season_label(_utc(*map(int, start.split("-")), 0)) == label
            assert recorded_nba_season_label(_utc(*map(int, end.split("-")), 23)) == label

    def test_october_april_and_june_dates(self):
        # 2025-10-01 is the recorded start of 2025-26, including preseason.
        assert recorded_nba_season_label(_utc(2025, 10, 1, 0)) == "2025-2026"
        # The day before that start is the offseason gap after 2024-25.
        assert recorded_nba_season_label(_utc(2025, 9, 30, 23)) == "2024-2025"
        # April is still inside the season window. The regular-season
        # type ends earlier; the label does not switch there.
        assert recorded_nba_season_label(_utc(2026, 4, 13)) == "2025-2026"
        assert recorded_nba_season_label(_utc(2027, 4, 12)) == "2026-2027"
        # June 27 2026 is the last day of 2025-26. June 28 is the gap
        # and still resolves to the season that started most recently.
        assert recorded_nba_season_label(_utc(2026, 6, 27, 23)) == "2025-2026"
        assert recorded_nba_season_label(_utc(2026, 6, 28, 0)) == "2025-2026"
        assert recorded_nba_season_label(_utc(2025, 6, 27, 23)) == "2024-2025"
        assert recorded_nba_season_label(_utc(2025, 6, 28, 0)) == "2024-2025"
        assert recorded_nba_season_label(_utc(2027, 6, 26, 23)) == "2026-2027"
        assert recorded_nba_season_label(_utc(2027, 6, 27, 0)) == "2026-2027"

    def test_preseason_is_inside_the_window_and_july_is_the_gap(self):
        # 2026-27 starts 2026-09-30. October 2 is preseason, not a new label.
        assert recorded_nba_season_label(_utc(2026, 10, 2)) == "2026-2027"
        assert recorded_nba_season_label(_utc(2026, 7, 4)) == "2025-2026"

    def test_chicago_evening_uses_the_utc_date(self):
        # 2026-09-29 20:00 in Chicago is 2026-09-30 01:00 UTC, the first
        # date of the 2026-27 window. The same clock time read as UTC is
        # still the gap and stays on 2025-26.
        chicago = datetime(2026, 9, 29, 20, 0, tzinfo=_CHICAGO)
        assert recorded_nba_season_label(chicago) == "2026-2027"
        assert recorded_nba_season_label(datetime(2026, 9, 29, 20, 0)) == "2025-2026"
        assert recorded_nba_season_label(
            datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)
        ) == "2025-2026"

    def test_overlapping_windows_keep_the_one_that_started_later(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.nba_season._nba_season_windows",
            lambda: (
                ("2025-10-01", "2026-06-27", "2025-2026"),
                ("2026-06-01", "2027-06-26", "2026-2027"),
            ),
        )
        assert recorded_nba_season_label(_utc(2026, 6, 15)) == "2026-2027"
        assert recorded_nba_season_label(_utc(2026, 5, 1)) == "2025-2026"


class TestHistorySample:
    def _path(self, tmp_path: Path) -> Path:
        path = tmp_path / "history.csv"
        _write_csv(
            path,
            [
                _log("Sample Player", "3/1/2026", "Knicks", "Celtics", "30"),
                _log("Bench Mate", "3/1/2026", "Knicks", "Celtics", "8"),
                _log("Sample Player", "2/1/2026", "Knicks", "Heat", "10"),
                _log("Sample Player", "1/1/2026", "Knicks", "Heat", "20"),
                _log(
                    "Sample Player",
                    "1/15/2026",
                    "Knicks",
                    "Heat",
                    "99",
                    minutes="0:00",
                ),
                _log(
                    "Sample Player",
                    "4/20/2026",
                    "Knicks",
                    "Heat",
                    "99",
                    game_type="playoffs",
                ),
                _log(
                    "Sample Player",
                    "10/5/2025",
                    "Knicks",
                    "Heat",
                    "99",
                    game_type="preseason",
                ),
                _log(
                    "Sample Player",
                    "12/1/2025",
                    "Knicks",
                    "Bucks",
                    "18",
                    game_type="",
                ),
            ],
        )
        return path

    def test_season_fields_ignore_n_and_stay_beside_the_sample(self, tmp_path):
        service = _service(self._path(tmp_path))
        stats = service.get_player_stats("Sample Player", "points", 15.0, n=1)
        assert stats["n_games"] == 1
        assert stats["season"] == "2026-2027"
        assert stats["season_n_games"] == 0
        assert stats["season_p_over"] is None
        assert stats["season_p_under"] is None
        assert stats["season_mean"] is None

        older = service.get_player_stats(
            "Sample Player", "points", 15.0, n=1, season="2025-26"
        )
        # Played regular-season rows: 30, 10, 20, and the blank-type 18.
        # The 0-minute 99, the playoff 99, and the preseason 99 are out.
        assert older["n_games"] == 1
        assert older["season"] == "2025-2026"
        assert older["season_n_games"] == 4
        assert older["season_p_over"] == 0.75
        assert older["season_p_under"] == 0.25
        assert older["season_mean"] == 19.5
        assert all(log["value"] != 99 for log in older["game_logs"])

    def test_teammate_context_uses_the_sample_after_n(self, tmp_path):
        service = _service(self._path(tmp_path))
        last_one = service.get_player_stats(
            "Sample Player", "points", 15.0, n=1, season="2025-2026"
        )
        mate = next(
            item for item in last_one["teammate_context"] if item["name"] == "Bench Mate"
        )
        assert last_one["n_games"] == 1
        assert mate["games_missed"] == 0
        assert mate["with_n"] == 1
        assert mate["without_n"] == 0
        assert mate["with_mean"] == 30.0
        assert mate["without_mean"] is None
        assert mate["games_missed"] == mate["without_n"]

        last_two = service.get_player_stats(
            "Sample Player", "points", 15.0, n=2, season="2025-2026"
        )
        mate = next(
            item for item in last_two["teammate_context"] if item["name"] == "Bench Mate"
        )
        assert last_two["n_games"] == 2
        assert mate["games_missed"] == 1
        assert mate["without_n"] == 1
        assert mate["with_n"] == 1
        assert mate["without_mean"] == 10.0
        assert [game["date"] for game in mate["missed_games"]] == ["2026-02-01"]
        assert last_two["season_n_games"] == 4

    def test_empty_sample_returns_zero_context(self, tmp_path):
        service = _service(self._path(tmp_path))
        stats = service.get_player_stats(
            "Sample Player",
            "points",
            15.0,
            n=3,
            opponent="Nets",
            season="2025-2026",
        )
        assert stats["n_games"] == 0
        assert stats["game_logs"] == []
        assert stats["teammate_context"]
        for item in stats["teammate_context"]:
            assert item["games_missed"] == 0
            assert item["missed_games"] == []
            assert item["with_n"] == 0
            assert item["without_n"] == 0
            assert item["with_mean"] is None
            assert item["without_mean"] is None


class TestRankBoundsAndLabels:
    def test_fewer_than_thirty_teams_are_numbered_from_one(self):
        table = build_defense_rank_table(
            [
                _game("Lakers", "Celtics", 20),
                _game("Celtics", "Lakers", 10),
            ]
        )
        assert sorted(table.overall.values()) == [1, 2]
        assert 30 not in table.overall.values()

    def test_a_tie_at_the_cutoff_keeps_the_earlier_code(self):
        games = [
            _game(f"Home{index:02d}", f"Opp{index:02d}", float(100 - index))
            for index in range(29)
        ]
        games.append(_game("Home29", "Aaa", 10))
        games.append(_game("Home30", "Zzz", 10))
        table = build_defense_rank_table(games)
        assert len(table.overall) == 30
        assert table.overall["AAA"] == 30
        assert "ZZZ" not in table.overall
        assert min(table.overall.values()) == 1
        assert max(table.overall.values()) == 30

    def test_zero_minute_points_stay_out_of_the_sum(self):
        table = build_defense_rank_table(
            [
                _game("Lakers", "Celtics", 80, minutes=0),
                _game(
                    "Lakers",
                    "Celtics",
                    10,
                    minutes=30,
                    when=datetime(2025, 11, 2),
                ),
                _game(
                    "Celtics",
                    "Lakers",
                    40,
                    minutes=30,
                    when=datetime(2025, 11, 2),
                ),
                _game(
                    "Heat",
                    "Knicks",
                    70,
                    minutes="0:00",
                    when=datetime(2025, 11, 3),
                ),
            ]
        )
        assert table.overall["LAL"] == 1
        assert table.overall["BOS"] == 2
        assert "NYK" not in table.overall

    def test_every_csv_club_resolves_to_one_of_the_thirty_codes(self):
        csv_player_service.load_csv()
        seen: set[str] = set()
        for rows in csv_player_service._cache.values():
            for game in rows:
                for key in ("team", "opponent"):
                    code = canonical_team_code(str(game.get(key) or ""), league="nba")
                    assert code in _NBA_CODES
                    seen.add(code)
        assert seen == _NBA_CODES
        assert set(nba_defense_table().overall) == _NBA_CODES

    def test_csv_fill_records_source_season_and_note(self):
        filled = fill_null_defense_ranks(
            {
                "opponent": "LAL",
                "position": "PG",
                "opponent_rank": None,
                "opponent_position_rank": None,
            }
        )
        assert filled["opponent_rank_source"] == "csv"
        assert filled["opponent_rank_season"] == "2025-2026"
        assert filled["opponent_rank_note"] == _CSV_RANK_NOTE
        assert 1 <= filled["opponent_rank"] <= 30
        assert 1 <= filled["opponent_position_rank"] <= 30

    def test_an_in_range_input_is_replaced_by_the_csv(self):
        kept = fill_null_defense_ranks(
            {
                "opponent": "LAL",
                "position": "PG",
                "opponent_rank": 12,
                "opponent_position_rank": 8,
            }
        )
        assert kept["opponent_rank_source"] == "csv"
        assert kept["opponent_position_rank_source"] == "csv"
        assert kept["opponent_rank_note"] == _CSV_RANK_NOTE
        assert 1 <= kept["opponent_rank"] <= 30
        assert 1 <= kept["opponent_position_rank"] <= 30
