"""SPO-97 gaps: real ESPN fixture edges, opt-in flags, and silent drops.

Rows are built from ``tests/fixtures/espn/schedule_events.json`` or copied
out of the shipped CSVs. Nothing here hand-types an ESPN payload.
"""

from __future__ import annotations

import asyncio
import csv
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.csv_downloader import CSVDownloaderService
from app.services.csv_player_history import CSVPlayerHistoryService
from app.services.daily_analysis import DailyAnalysisService
from app.services.game_log_hygiene import (
    GAME_TYPE_GLEAGUE,
    GAME_TYPE_NBA_CUP,
    GAME_TYPE_PLAY_IN,
    GAME_TYPE_PLAYOFFS,
    GAME_TYPE_PRESEASON,
    GAME_TYPE_REGULAR,
    GAME_TYPE_SUMMER,
    GAME_TYPE_UNCLASSIFIED,
    _local_dates,
    _parse_event_instant,
    hygiene_rows,
    load_schedule_events,
)

_REPO = Path(__file__).resolve().parents[2]
_EASTERN = ZoneInfo("America/New_York")
_RAW_COLUMNS = [
    "Player", "Season", "Date", "Team", "Opponent", "W/L", "Status", "Pos",
    "MIN", "PTS", "FGM", "FGA", "FG%", "3PM", "3PA", "3P%", "FTM", "FTA",
    "FT%", "ORB", "DRB", "REB", "AST", "STL", "BLK", "TOV", "PF", "FIC",
]

# Recorded event ids. Each one is loaded from schedule_events.json.
_PRESEASON_2025_10_17 = "401812731"  # Nets at Raptors, seasonType pre
_REGULAR_OPENER_2025_10_21 = "401809243"  # Rockets at Thunder, seasonType reg
_REGULAR_FINALE_2026_04_12 = "401811041"  # Magic at Celtics, seasonType reg
_PLAY_IN_2026_04_14 = "401866755"  # Heat at Hornets, seasonType playin
_PLAYOFFS_2026_04_18 = "401869187"  # Raptors at Cavaliers, seasonType post
_CUP_GROUP_2024_11_12 = "401703370"  # Hawks at Celtics, group play, counts as reg
_CUP_QUARTERFINAL_2024_12_10 = "401734902"  # Magic at Bucks, counts as reg
_CUP_SEMIFINAL_2024_12_14 = "401734906"  # Hawks at Bucks, counts as reg
_CUP_FINAL_2024_12_17 = "401734908"  # Bucks at Thunder, does not count as reg
_CUP_FINAL_2025_12_16 = "401809839"  # Spurs at Knicks, does not count as reg
_WNBA_PRESEASON_2026_04_25 = "401866150"  # Fever at Liberty, seasonType pre
_WNBA_REGULAR_2026_05_08 = "401856891"  # Mystics at Tempo, seasonType reg
_WNBA_PLAYOFFS_2025_09_14 = "401820272"  # Valkyries at Lynx, seasonType post


def _schedule() -> list[dict]:
    """The committed ESPN schedule, not a constructed payload."""
    return load_schedule_events()


def _event(event_id: str) -> dict:
    """One recorded event. Fails if the fixture no longer contains that id."""
    found = next(
        (event for event in _schedule() if str(event.get("id")) == event_id),
        None,
    )
    assert found is not None, event_id
    return found


def _csv_date(event: dict) -> str:
    """Arena-side date cell. Eastern and Pacific are both indexed.

    This fixture has no NBA tip where those two calendar dates differ, so
    the Eastern date is the one RealGM prints for these games.
    """
    instant = _parse_event_instant(str(event.get("date") or ""))
    assert instant is not None
    local = instant.astimezone(_EASTERN).date()
    assert local.isoformat() in _local_dates(instant)
    return f"{local.month}/{local.day}/{local.year}"


def _sides(event: dict) -> tuple[str, str]:
    """``(away shortDisplayName, home shortDisplayName)`` from the fixture."""
    named: dict[str, str] = {}
    for competitor in event.get("competitors") or []:
        team = competitor.get("team") or {}
        named[str(competitor.get("homeAway") or "")] = str(team.get("shortDisplayName") or "")
    assert named.get("away") and named.get("home")
    return named["away"], named["home"]


def _raw_row(
    event: dict,
    player: str,
    *,
    pts: str = "10",
    scraped_season: str = "2025-2026",
) -> dict[str, str]:
    """One scraper-shaped row joined to ``event`` on date plus both clubs."""
    away, home = _sides(event)
    row = {column: "" for column in _RAW_COLUMNS}
    row.update(
        {
            "Player": player,
            "Season": scraped_season,
            "Date": _csv_date(event),
            "Team": away,
            "Opponent": home,
            "MIN": "20:00",
            "PTS": pts,
            "REB": pts,
            "AST": pts,
        }
    )
    return row


def _write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    """Write ``rows`` with the exact header ``load_csv`` / hygiene expect."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _shipped(name: str) -> list[dict[str, str]]:
    """Rows from a canonical CSV under ``data/``."""
    with (_REPO / "data" / name).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


class TestFixtureSeasonEdges:
    """October and April boundaries taken from recorded events."""

    def test_october_preseason_drops_and_opening_night_is_regular(self):
        # 2025-10-17 is still preseason. 2025-10-21 is the regular-season
        # opener. The scraped season string is deliberately wrong.
        events = _schedule()
        pre = _raw_row(_event(_PRESEASON_2025_10_17), "October Player", scraped_season="1999-2000")
        opener = _raw_row(
            _event(_REGULAR_OPENER_2025_10_21),
            "October Player",
            pts="22",
            scraped_season="1999-2000",
        )
        report = hygiene_rows([pre, opener], events, league="nba")
        assert report.output_rows == 1
        assert report.dropped[GAME_TYPE_PRESEASON] == 1
        assert report.rows[0]["Player"] == "October Player"
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR
        assert report.rows[0]["Season"] == "2025-2026"
        assert report.rows[0]["PTS"] == "22"

    def test_april_splits_regular_play_in_and_playoffs(self):
        # 2026-04-12 regular season, 2026-04-14 play-in, 2026-04-18 playoffs.
        # Play-in must not be swallowed by the playoff bucket or the reverse.
        events = _schedule()
        rows = [
            _raw_row(_event(_REGULAR_FINALE_2026_04_12), "April Player", pts="11"),
            _raw_row(_event(_PLAY_IN_2026_04_14), "April Player", pts="12"),
            _raw_row(_event(_PLAYOFFS_2026_04_18), "April Player", pts="13"),
        ]
        report = hygiene_rows(rows, events, league="nba")
        by_type = {row["GameType"]: row for row in report.rows}
        assert set(by_type) == {GAME_TYPE_REGULAR, GAME_TYPE_PLAY_IN, GAME_TYPE_PLAYOFFS}
        assert by_type[GAME_TYPE_REGULAR]["PTS"] == "11"
        assert by_type[GAME_TYPE_PLAY_IN]["PTS"] == "12"
        assert by_type[GAME_TYPE_PLAYOFFS]["PTS"] == "13"
        assert {row["Season"] for row in report.rows} == {"2025-2026"}

    def test_prior_season_group_game_is_relabelled_2024_2025(self):
        # Hawks at Celtics on 2024-11-12 is an NBA Cup group game. Group
        # games count as the regular season. The scraper had stamped
        # 2025-2026 on every row; the fixture displayName is 2024-25.
        events = _schedule()
        row = _raw_row(
            _event(_CUP_GROUP_2024_11_12),
            "Group Player",
            scraped_season="2025-2026",
        )
        report = hygiene_rows([row], events, league="nba")
        assert report.output_rows == 1
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR
        assert report.rows[0]["Season"] == "2024-2025"

    def test_cup_knockout_through_semifinals_stays_regular_season(self):
        # Quarterfinals and semifinals count toward the 82-game season.
        events = _schedule()
        rows = [
            _raw_row(_event(_CUP_QUARTERFINAL_2024_12_10), "Knockout Player", pts="14"),
            _raw_row(_event(_CUP_SEMIFINAL_2024_12_14), "Knockout Player", pts="15"),
        ]
        report = hygiene_rows(rows, events, league="nba")
        assert report.output_rows == 2
        assert {row["GameType"] for row in report.rows} == {GAME_TYPE_REGULAR}
        assert {row["Season"] for row in report.rows} == {"2024-2025"}

    def test_every_2024_cup_group_event_stays_regular_season(self):
        # The 60 group-play events share the 401703 id prefix and November
        # / December 3 dates. All of them are seasonType reg in the fixture.
        events = _schedule()
        group = [event for event in events if str(event.get("id", "")).startswith("401703")]
        assert len(group) == 60
        rows = [
            _raw_row(event, f"Group {event['id']}", scraped_season="2025-2026")
            for event in group
        ]
        report = hygiene_rows(rows, events, league="nba")
        assert report.output_rows == 60
        assert set(report.kept) == {GAME_TYPE_REGULAR}
        assert report.seasons_kept == {"2024-2025": 60}


@pytest.mark.parametrize("event_id", [_CUP_FINAL_2024_12_17, _CUP_FINAL_2025_12_16])
def test_nba_cup_championship_is_not_regular_season(event_id: str):
    """The championship must not enter the default regular-season sample."""
    report = hygiene_rows([_raw_row(_event(event_id), "Final Player")], _schedule(), league="nba")
    kept_regular = [row for row in report.rows if row["GameType"] == GAME_TYPE_REGULAR]
    assert kept_regular == []
    assert [row["GameType"] for row in report.rows] == [GAME_TYPE_NBA_CUP]


def test_downloader_keeps_games_the_fixture_does_not_list(tmp_path: Path):
    """Current-season games missing from the fixture must survive a download rewrite."""
    future = {column: "" for column in _RAW_COLUMNS}
    future.update(
        {
            "Player": "Future Player",
            "Season": "2026-2027",
            "Date": "10/21/2026",
            "Team": "Celtics",
            "Opponent": "Knicks",
            "MIN": "30:00",
            "PTS": "28",
        }
    )
    path = tmp_path / "nba_player_game_logs.csv"
    _write_csv(path, [future], _RAW_COLUMNS)
    CSVDownloaderService(save_path=path)._hygiene_game_log()
    written = path.read_text(encoding="utf-8")
    assert "Future Player" in written


class TestWnbaFixtureParity:
    """The same join, on recorded WNBA events."""

    def test_preseason_drops_regular_and_playoffs_stay(self):
        events = _schedule()
        rows = [
            _raw_row(_event(_WNBA_PRESEASON_2026_04_25), "Wnba Player", scraped_season="2025"),
            _raw_row(
                _event(_WNBA_REGULAR_2026_05_08),
                "Wnba Player",
                pts="8",
                scraped_season="2025",
            ),
            _raw_row(
                _event(_WNBA_PLAYOFFS_2025_09_14),
                "Wnba Player",
                pts="9",
                scraped_season="2026",
            ),
        ]
        report = hygiene_rows(rows, events, league="wnba")
        assert report.dropped[GAME_TYPE_PRESEASON] == 1
        by_type = {row["GameType"]: row for row in report.rows}
        assert set(by_type) == {GAME_TYPE_REGULAR, GAME_TYPE_PLAYOFFS}
        assert by_type[GAME_TYPE_REGULAR]["Season"] == "2026"
        assert by_type[GAME_TYPE_REGULAR]["Team"] == "Mystics"
        assert by_type[GAME_TYPE_PLAYOFFS]["Season"] == "2025"
        assert by_type[GAME_TYPE_PLAYOFFS]["GameType"] == GAME_TYPE_PLAYOFFS


class TestOptInFlags:
    """Stats and daily picks default to the regular season. Each flag is separate."""

    def _player_file(self, tmp_path: Path, league: str) -> tuple[Path, str]:
        """One real regular row, one real playoff row, one real or copied play-in row."""
        shipped_name = "wnba_player_game_logs.csv" if league == "wnba" else "nba_player_game_logs.csv"
        shipped = _shipped(shipped_name)
        by_player: dict[str, dict[str, dict[str, str]]] = {}
        for row in shipped:
            by_player.setdefault(row["Player"], {})[row["GameType"]] = row
        player = next(
            name
            for name, kinds in by_player.items()
            if GAME_TYPE_REGULAR in kinds and GAME_TYPE_PLAYOFFS in kinds
        )
        regular = dict(by_player[player][GAME_TYPE_REGULAR])
        playoff = dict(by_player[player][GAME_TYPE_PLAYOFFS])
        if GAME_TYPE_PLAY_IN in by_player[player]:
            play_in = dict(by_player[player][GAME_TYPE_PLAY_IN])
        else:
            # WNBA has no play-in games. A copied row with that token checks
            # the flag without inventing an ESPN event.
            play_in = dict(regular)
            play_in["GameType"] = GAME_TYPE_PLAY_IN
            play_in["Date"] = "9/20/2025"
        regular["PTS"] = "10"
        playoff["PTS"] = "30"
        play_in["PTS"] = "20"
        for row in (regular, playoff, play_in):
            row["MIN"] = "20:00"
        columns = list(regular.keys())
        path = tmp_path / shipped_name
        _write_csv(path, [regular, playoff, play_in], columns)
        return path, player

    def test_stats_flags_are_independent(self, tmp_path, monkeypatch):
        path, player = self._player_file(tmp_path, "nba")
        monkeypatch.setattr("app.services.csv_player_history.CSV_PATH", str(path))
        service = CSVPlayerHistoryService(league="nba")
        default = service.get_player_stats(player, "points", 15)
        playoffs_only = service.get_player_stats(player, "points", 15, include_playoffs=True)
        play_in_only = service.get_player_stats(player, "points", 15, include_play_in=True)
        both = service.get_player_stats(
            player, "points", 15, include_playoffs=True, include_play_in=True
        )
        assert default["n_games"] == 1
        assert default["mean"] == 10
        assert {log["game_type"] for log in playoffs_only["game_logs"]} == {
            GAME_TYPE_REGULAR,
            GAME_TYPE_PLAYOFFS,
        }
        assert {log["game_type"] for log in play_in_only["game_logs"]} == {
            GAME_TYPE_REGULAR,
            GAME_TYPE_PLAY_IN,
        }
        assert both["n_games"] == 3

    def test_wnba_stats_flags_match_nba(self, tmp_path, monkeypatch):
        path, player = self._player_file(tmp_path, "wnba")
        monkeypatch.setenv("WNBA_CSV_DATA_PATH", str(path))
        service = CSVPlayerHistoryService(league="wnba")
        default = service.get_player_stats(player, "points", 15)
        opted = service.get_player_stats(player, "points", 15, include_playoffs=True)
        assert default["n_games"] == 1
        assert default["game_logs"][0]["game_type"] == GAME_TYPE_REGULAR
        assert opted["n_games"] == 2
        assert {log["game_type"] for log in opted["game_logs"]} == {
            GAME_TYPE_REGULAR,
            GAME_TYPE_PLAYOFFS,
        }

    def test_daily_picks_ignore_playoff_points(self, tmp_path, monkeypatch):
        # Nine regular-season games sit under the line. Twenty playoff games
        # sit over it. n_games < 10 suppresses a pick. Folding the playoffs
        # in would clear the 0.65 bar (20/29). The picks call does not pass
        # include_playoffs.
        path = tmp_path / "nba_player_game_logs.csv"
        shipped = _shipped("nba_player_game_logs.csv")
        template = next(row for row in shipped if row["GameType"] == GAME_TYPE_REGULAR)
        columns = list(template.keys())
        rows: list[dict[str, str]] = []
        for index in range(9):
            regular = dict(template)
            regular["Player"] = "Pick Player"
            regular["GameType"] = GAME_TYPE_REGULAR
            regular["Date"] = f"1/{index + 1}/2026"
            regular["PTS"] = "0"
            regular["REB"] = "0"
            regular["AST"] = "0"
            regular["MIN"] = "20:00"
            rows.append(regular)
        for index in range(20):
            playoff = dict(template)
            playoff["Player"] = "Pick Player"
            playoff["GameType"] = GAME_TYPE_PLAYOFFS
            playoff["Date"] = f"4/{index + 1}/2026"
            playoff["PTS"] = "40"
            playoff["REB"] = "40"
            playoff["AST"] = "40"
            playoff["MIN"] = "32:00"
            rows.append(playoff)
        _write_csv(path, rows, columns)
        monkeypatch.setattr("app.services.csv_player_history.CSV_PATH", str(path))
        history = CSVPlayerHistoryService(league="nba")
        opted = history.get_player_stats("Pick Player", "points", 10.5, include_playoffs=True)
        assert opted["n_games"] == 29
        assert opted["p_over"] >= 0.65

        seen: list[dict] = []
        real = history.get_player_stats

        def _record(*args, **kwargs):
            seen.append(kwargs)
            return real(*args, **kwargs)

        history.get_player_stats = _record  # type: ignore[method-assign]
        service = DailyAnalysisService(probability_threshold=0.65)
        service.csv_service = history
        service._get_props_for_market = AsyncMock(
            return_value=[
                {
                    "key": "testbook",
                    "markets": [
                        {
                            "outcomes": [
                                {"description": "Pick Player", "point": 10.5},
                                {"description": "Pick Player", "point": 10.5},
                            ]
                        }
                    ],
                }
            ]
        )
        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-spo97",
                home_team="Boston Celtics",
                away_team="New York Knicks",
                commence_time="2026-04-18T23:30:00Z",
                projections={},
            )
        )
        assert picks == []
        assert seen
        assert all(not call.get("include_playoffs") for call in seen)
        assert all(not call.get("include_play_in") for call in seen)


class TestLoadCsvSkipsDroppedTypes:
    """``load_csv`` is the second gate for a file that still contains dropped types."""

    def _rows_for(self, league: str) -> tuple[list[dict[str, str]], list[str], str]:
        shipped_name = "wnba_player_game_logs.csv" if league == "wnba" else "nba_player_game_logs.csv"
        template = next(row for row in _shipped(shipped_name) if row["GameType"] == GAME_TYPE_REGULAR)
        columns = list(template.keys())
        player = "Filter Player"
        kept = dict(template)
        kept["Player"] = player
        kept["GameType"] = GAME_TYPE_REGULAR
        kept["PTS"] = "12"
        kept["MIN"] = "18:00"
        dropped_rows = []
        for index, game_type in enumerate(
            (GAME_TYPE_SUMMER, GAME_TYPE_PRESEASON, GAME_TYPE_GLEAGUE, GAME_TYPE_UNCLASSIFIED)
        ):
            row = dict(template)
            row["Player"] = player
            row["GameType"] = game_type
            row["Date"] = f"7/{index + 1}/2025"
            row["PTS"] = "80"
            row["MIN"] = "40:00"
            dropped_rows.append(row)
        return [kept, *dropped_rows], columns, player

    def test_nba_loader_skips_summer_preseason_g_league_and_unclassified(self, tmp_path, monkeypatch):
        rows, columns, player = self._rows_for("nba")
        path = tmp_path / "nba_player_game_logs.csv"
        _write_csv(path, rows, columns)
        monkeypatch.setattr("app.services.csv_player_history.CSV_PATH", str(path))
        service = CSVPlayerHistoryService(league="nba")
        stats = service.get_player_stats(player, "points", 20)
        assert stats["n_games"] == 1
        assert stats["mean"] == 12
        assert stats["game_logs"][0]["game_type"] == GAME_TYPE_REGULAR

    def test_wnba_loader_skips_the_same_tokens(self, tmp_path, monkeypatch):
        rows, columns, player = self._rows_for("wnba")
        path = tmp_path / "wnba_player_game_logs.csv"
        _write_csv(path, rows, columns)
        monkeypatch.setenv("WNBA_CSV_DATA_PATH", str(path))
        service = CSVPlayerHistoryService(league="wnba")
        stats = service.get_player_stats(player, "points", 20)
        assert stats["n_games"] == 1
        assert stats["mean"] == 12
        assert service._cache[player][0]["game_type"] == GAME_TYPE_REGULAR
