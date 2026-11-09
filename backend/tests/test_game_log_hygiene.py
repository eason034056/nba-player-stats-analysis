"""Season labels and game-type hygiene for the player game-log CSVs.

Schedule rows come from ``tests/fixtures/espn/``: the compact index plus
the raw team-schedule responses recorded with curl. One test also reads
the shipped CSVs, so a regression that puts Summer League back into the
canonical file fails without a network call.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.csv_player_history import CSVPlayerHistoryService
from app.services.espn_schedule import compact_event
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
    parse_csv_date,
)

_REPO = Path(__file__).resolve().parents[2]
_COLUMNS = [
    "Player", "Season", "Date", "Team", "Opponent", "W/L", "Status", "Pos",
    "MIN", "PTS", "FGM", "FGA", "FG%", "3PM", "3PA", "3P%", "FTM", "FTA",
    "FT%", "ORB", "DRB", "REB", "AST", "STL", "BLK", "TOV", "PF", "FIC",
]


# Recorded event ids in tests/fixtures/espn/schedule_events.json, except
# the 2026-27 Celtics games, which are folded in from the raw curl file.
_REGULAR_OPENER = "401809243"  # Rockets at Thunder
_PRESEASON = "401812731"  # Nets at Raptors
_SUMMER = "401352125"  # Grizzlies at Jazz Blue
_PLAYOFFS = "401869187"  # Raptors at Cavaliers
_PLAY_IN = "401866755"  # Heat at Hornets
_GLEAGUE = "401693177"  # MEGA MIS at G League United
_SIXERS = "401704632"  # Bucks at Philadelphia 76ers
_NBA_SAME_NIGHT = "401810710"  # Lakers / Suns, NBA
_GLEAGUE_SAME_NIGHT = "401819340"  # Lakers / Suns, G League
_WNBA_REGULAR = "401856891"  # Mystics at Tempo
_CELTICS_2027_RAW = "nba_team_2_schedule_2027_type_2.json"


def _recorded(event_id: str) -> dict:
    """One event from the fixture. Fails if that id was dropped."""
    found = next(
        (event for event in load_schedule_events() if str(event.get("id")) == event_id),
        None,
    )
    assert found is not None, event_id
    return found


def _csv_date(event: dict) -> str:
    """One arena-local date for a recorded kickoff, formatted M/D/YYYY."""
    instant = _parse_event_instant(str(event.get("date") or ""))
    assert instant is not None
    iso = sorted(_local_dates(instant))[0]
    parsed = datetime.strptime(iso, "%Y-%m-%d")
    return f"{parsed.month}/{parsed.day}/{parsed.year}"


def _sides(event: dict) -> tuple[str, str]:
    """``(home shortDisplayName, away shortDisplayName)`` from the recording."""
    home = away = ""
    for competitor in event.get("competitors") or []:
        name = str((competitor.get("team") or {}).get("shortDisplayName") or "")
        if competitor.get("homeAway") == "home":
            home = name
        else:
            away = name
    assert home and away, event.get("id")
    return home, away


def _row_for(event: dict, player: str, *, season: str = "1999-2000", pts: str = "10") -> dict:
    """A CSV row whose clubs and date are copied off ``event``."""
    home, away = _sides(event)
    return _row(player, season, _csv_date(event), home, away, pts=pts)


def _row(player: str, season: str, date: str, team: str, opponent: str, pts: str = "10") -> dict:
    """One game-log row. Box score is constant except points, for dedupe tests."""
    row = {column: "" for column in _COLUMNS}
    row.update(
        {
            "Player": player,
            "Season": season,
            "Date": date,
            "Team": team,
            "Opponent": opponent,
            "MIN": "20:00",
            "PTS": pts,
        }
    )
    return row


class TestHygieneRules:
    """Schedule join, drop rules, and the cross-season duplicate.

    Every event is loaded from the recorded fixture. The CSV row copies
    that event's clubs and local date.
    """

    def test_regular_season_label_expands_display_name(self):
        # ESPN records "2025-26". The CSV column keeps the scraper's
        # four-digit form "2025-2026", derived from that displayName.
        event = _recorded(_REGULAR_OPENER)
        assert event["season"]["displayName"] == "2025-26"
        report = hygiene_rows([_row_for(event, "Player A")], [event], league="nba")
        assert report.output_rows == 1
        assert report.rows[0]["Season"] == "2025-2026"
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR

    def test_summer_league_and_preseason_are_dropped(self):
        summer = _recorded(_SUMMER)
        preseason = _recorded(_PRESEASON)
        regular = _recorded(_REGULAR_OPENER)
        rows = [
            _row_for(summer, "Player A"),
            _row_for(preseason, "Player A", pts="11"),
            _row_for(regular, "Player A", pts="12"),
        ]
        report = hygiene_rows(rows, [summer, preseason, regular], league="nba")
        assert report.output_rows == 1
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR
        assert report.dropped[GAME_TYPE_SUMMER] == 1
        assert report.dropped[GAME_TYPE_PRESEASON] == 1

    def test_playoffs_and_play_in_stay_and_are_labeled(self):
        playoffs = _recorded(_PLAYOFFS)
        play_in = _recorded(_PLAY_IN)
        report = hygiene_rows(
            [
                _row_for(playoffs, "Player A"),
                _row_for(play_in, "Player B", pts="11"),
            ],
            [playoffs, play_in],
            league="nba",
        )
        by_type = {row["GameType"]: row for row in report.rows}
        assert set(by_type) == {GAME_TYPE_PLAYOFFS, GAME_TYPE_PLAY_IN}
        assert by_type[GAME_TYPE_PLAYOFFS]["Season"] == "2025-2026"
        assert by_type[GAME_TYPE_PLAY_IN]["Season"] == "2025-2026"

    def test_g_league_drops_and_unmatched_rows_are_kept(self, caplog: pytest.LogCaptureFixture):
        # A classified G League game leaves the file. A row that joins
        # nothing stays, labeled unclassified, and the count is logged.
        # Deleting that row is how a short fixture erased a new season.
        g_league = _recorded(_GLEAGUE)
        assert g_league["league"] == "nba-development"
        opener = _recorded(_REGULAR_OPENER)
        college = _row(
            "Player C",
            "2025-2026",
            _csv_date(opener),
            "Georgetown",
            "Butler",
        )
        with caplog.at_level(logging.WARNING):
            report = hygiene_rows(
                [_row_for(g_league, "Player G"), college],
                [g_league, opener],
                league="nba",
            )
        assert report.output_rows == 1
        assert report.rows[0]["Player"] == "Player C"
        assert report.rows[0]["GameType"] == GAME_TYPE_UNCLASSIFIED
        assert report.dropped[GAME_TYPE_GLEAGUE] == 1
        assert report.unclassified == 1
        assert any(
            "1 row(s) unclassified" in record.message for record in caplog.records
        )

    def test_sixers_alias_joins_recorded_76ers_name(self):
        # team_directory.json records shortDisplayName "76ers". The scraper
        # writes "Sixers". The row still has to find the event.
        event = _recorded(_SIXERS)
        home, away = _sides(event)
        assert home == "76ers"
        row = _row("Player S", "2025-2026", _csv_date(event), "Sixers", away)
        report = hygiene_rows([row], [event], league="nba")
        assert report.output_rows == 1
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR
        assert report.rows[0]["Team"] == "Sixers"

    def test_parent_league_wins_when_g_league_shares_nicknames(self):
        nba = _recorded(_NBA_SAME_NIGHT)
        g_league = _recorded(_GLEAGUE_SAME_NIGHT)
        assert nba["league"] == "nba"
        assert g_league["league"] == "nba-development"
        report = hygiene_rows(
            [_row_for(nba, "Austin Reaves", pts="20")],
            [nba, g_league],
            league="nba",
        )
        assert report.output_rows == 1
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR
        assert report.ambiguous == 0

    def test_cross_season_duplicate_keeps_the_schedule_season(self):
        # Same box score stored once under the wrong season and once under
        # the season the schedule assigns. Keep the matching copy.
        event = _recorded(_WNBA_REGULAR)
        home, away = _sides(event)
        date = _csv_date(event)
        rows = [
            _row("Maria Conde", "2025", date, home, away, pts="2"),
            _row("Maria Conde", "2026", date, home, away, pts="2"),
        ]
        report = hygiene_rows(rows, [event], league="wnba")
        assert report.output_rows == 1
        assert report.duplicates_removed == 1
        assert report.rows[0]["Season"] == "2026"
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR
        assert report.rows[0]["Player"] == "Maria Conde"

    def test_recorded_2027_schedule_labels_the_current_regular_season(self):
        # The Celtics 2026-27 regular season is a curl of the site API,
        # not a row typed into schedule_events.json.
        raw_path = _REPO / "tests" / "fixtures" / "espn" / _CELTICS_2027_RAW
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        assert payload["requestedSeason"]["displayName"] == "2026-27"
        assert payload["requestedSeason"]["name"] == "Regular Season"
        compact = compact_event("nba", payload["events"][0])
        report = hygiene_rows([_row_for(compact, "Celtics Player")], [compact], league="nba")
        assert report.output_rows == 1
        assert report.rows[0]["Season"] == "2026-2027"
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR


class TestLoaderExcludesNonRegular:
    """The stats path reads GameType and defaults to the regular season."""

    def _service(self, tmp_path: Path, rows: list[dict]) -> CSVPlayerHistoryService:
        path = tmp_path / "nba_player_game_logs.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_COLUMNS + ["GameType"])
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        service = CSVPlayerHistoryService(league="nba")
        # load_csv reads the module-level CSV_PATH for the NBA league.
        return service, path

    def test_default_stats_skip_playoffs_and_summer(self, tmp_path, monkeypatch):
        regular = _row("Pat Player", "2025-2026", "10/22/2025", "Lakers", "Warriors", pts="30")
        regular["GameType"] = GAME_TYPE_REGULAR
        playoff = _row("Pat Player", "2025-2026", "4/20/2026", "Lakers", "Rockets", pts="5")
        playoff["GameType"] = GAME_TYPE_PLAYOFFS
        summer = _row("Pat Player", "2025-2026", "7/10/2025", "Lakers", "Kings", pts="40")
        summer["GameType"] = GAME_TYPE_SUMMER
        service, path = self._service(tmp_path, [regular, playoff, summer])
        monkeypatch.setattr("app.services.csv_player_history.CSV_PATH", str(path))
        stats = service.get_player_stats("Pat Player", "points", 10.5)
        assert stats["n_games"] == 1
        assert stats["mean"] == 30
        assert stats["game_logs"][0]["game_type"] == GAME_TYPE_REGULAR

        with_playoffs = service.get_player_stats(
            "Pat Player", "points", 10.5, include_playoffs=True
        )
        assert with_playoffs["n_games"] == 2
        kinds = {log["game_type"] for log in with_playoffs["game_logs"]}
        assert kinds == {GAME_TYPE_REGULAR, GAME_TYPE_PLAYOFFS}

    def test_play_in_is_opt_in(self, tmp_path, monkeypatch):
        regular = _row("Pat Player", "2025-2026", "10/22/2025", "Lakers", "Warriors", pts="10")
        regular["GameType"] = GAME_TYPE_REGULAR
        play_in = _row("Pat Player", "2025-2026", "4/15/2026", "Hawks", "Magic", pts="12")
        play_in["GameType"] = GAME_TYPE_PLAY_IN
        service, path = self._service(tmp_path, [regular, play_in])
        monkeypatch.setattr("app.services.csv_player_history.CSV_PATH", str(path))
        default = service.player_dd_history("Pat Player")
        opted = service.player_dd_history("Pat Player", include_play_in=True)
        assert default["n_games"] == 1
        assert opted["n_games"] == 2

    def test_nba_cup_championship_stays_out_of_the_default_sample(self, tmp_path, monkeypatch):
        regular = _row("Pat Player", "2025-2026", "10/22/2025", "Lakers", "Warriors", pts="10")
        regular["GameType"] = GAME_TYPE_REGULAR
        cup = _row("Pat Player", "2024-2025", "12/17/2024", "Thunder", "Bucks", pts="40")
        cup["GameType"] = GAME_TYPE_NBA_CUP
        service, path = self._service(tmp_path, [regular, cup])
        monkeypatch.setattr("app.services.csv_player_history.CSV_PATH", str(path))
        stats = service.get_player_stats("Pat Player", "points", 10.5)
        assert stats["n_games"] == 1
        assert stats["mean"] == 10
        with_playoffs = service.get_player_stats(
            "Pat Player", "points", 10.5, include_playoffs=True
        )
        assert with_playoffs["n_games"] == 1


class TestShippedCsv:
    """The files under data/ after the hygiene pass."""

    def _rows(self, name: str) -> list[dict[str, str]]:
        path = _REPO / "data" / name
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))

    def test_nba_file_has_no_summer_or_preseason_and_splits_playoffs(self):
        rows = self._rows("nba_player_game_logs.csv")
        types = {row["GameType"] for row in rows}
        assert GAME_TYPE_SUMMER not in types
        assert GAME_TYPE_PRESEASON not in types
        assert GAME_TYPE_REGULAR in types
        assert GAME_TYPE_PLAYOFFS in types
        assert GAME_TYPE_PLAY_IN in types
        seasons = {row["Season"] for row in rows}
        # The bug was every row carrying 2025-2026. More than one season
        # has to survive once older regular-season games are relabeled.
        assert seasons != {"2025-2026"}
        assert "2025-2026" in seasons
        july = [
            row for row in rows
            if (parse_csv_date(row["Date"]) or "").startswith("2025-07")
        ]
        assert july == []
        early_regular = [
            row for row in rows
            if row["Season"] == "2025-2026"
            and row["GameType"] == GAME_TYPE_REGULAR
            and (parse_csv_date(row["Date"]) or "") < "2025-10-21"
        ]
        assert early_regular == []

    def test_wnba_maria_conde_is_deduped_onto_2026(self):
        rows = self._rows("wnba_player_game_logs.csv")
        conde = [
            row for row in rows
            if row["Player"] == "Maria Conde" and parse_csv_date(row["Date"]) == "2026-05-08"
        ]
        assert len(conde) == 1
        assert conde[0]["Season"] == "2026"
        assert conde[0]["GameType"] == GAME_TYPE_REGULAR
        # No other player-game is stored under two seasons.
        seen: dict[tuple[str, str, str, str], set[str]] = {}
        for row in rows:
            key = (
                row["Player"].strip().lower(),
                parse_csv_date(row["Date"]) or row["Date"],
                row["Team"].strip().lower(),
                row["Opponent"].strip().lower(),
            )
            seen.setdefault(key, set()).add(row["Season"])
        cross = [key for key, seasons in seen.items() if len(seasons) > 1]
        assert cross == []

    def test_recorded_fixture_labels_opening_night(self):
        # Ground the parser on the committed payload, not a hand-built event.
        events = load_schedule_events()
        opener = next(
            event for event in events
            if event.get("id") == "401809243"
        )
        assert opener["season"]["displayName"] == "2025-26"
        assert opener["seasonType"]["abbreviation"] == "reg"
        rows = [_row("Test Player", "1999-2000", "10/21/2025", "Thunder", "Rockets")]
        report = hygiene_rows(rows, events, league="nba")
        assert report.output_rows == 1
        assert report.rows[0]["Season"] == "2025-2026"
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR


@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="Live ESPN schedule fetch — set RUN_INTEGRATION=1 to enable.",
)
def test_live_scoreboard_has_the_fields_the_parser_reads():
    """The fixture was recorded from this endpoint. Re-check the shape."""
    import json
    import urllib.request

    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20251021"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    event = payload["events"][0]
    assert "date" in event
    assert "type" in event["season"] or "slug" in event["season"]
    team = event["competitions"][0]["competitors"][0]["team"]
    assert team.get("shortDisplayName")


@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="Live ESPN schedule fetch — set RUN_INTEGRATION=1 to enable.",
)
def test_live_2027_celtics_schedule_matches_the_recorded_file():
    """The 2026-27 fixture was recorded from this team-schedule URL."""
    import json
    import urllib.request

    url = (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/2/"
        "schedule?season=2027&seasontype=2"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert payload["requestedSeason"]["displayName"] == "2026-27"
    assert payload["events"]
    competition = payload["events"][0]["competitions"][0]
    assert "notes" in competition
    assert "type" in competition
