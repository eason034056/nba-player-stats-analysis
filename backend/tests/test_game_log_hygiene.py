"""Season labels and game-type hygiene for the player game-log CSVs.

The cases here use the same JSON shape ``scripts/explore_espn_schedule_api.py``
records (season.displayName, seasonType.abbreviation, competitor
shortDisplayName). One test also reads the committed fixture and the
shipped CSVs, so a regression that puts Summer League back into the
canonical file fails without a network call.
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.csv_player_history import CSVPlayerHistoryService
from app.services.game_log_hygiene import (
    GAME_TYPE_PLAY_IN,
    GAME_TYPE_PLAYOFFS,
    GAME_TYPE_PRESEASON,
    GAME_TYPE_REGULAR,
    GAME_TYPE_SUMMER,
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


def _event(
    event_id: str,
    *,
    league: str,
    when: str,
    display: str,
    year: int,
    abbrev: str,
    home: str,
    away: str,
) -> dict:
    """One recorded-shape schedule event."""
    return {
        "id": event_id,
        "league": league,
        "date": when,
        "name": f"{away} at {home}",
        "shortName": "",
        "season": {"year": year, "displayName": display},
        "seasonType": {
            "id": abbrev,
            "type": 2,
            "name": abbrev,
            "abbreviation": abbrev,
        },
        "competitors": [
            {
                "homeAway": "home",
                "team": {
                    "abbreviation": home[:3].upper(),
                    "shortDisplayName": home,
                    "displayName": home,
                    "name": home,
                    "location": "",
                },
            },
            {
                "homeAway": "away",
                "team": {
                    "abbreviation": away[:3].upper(),
                    "shortDisplayName": away,
                    "displayName": away,
                    "name": away,
                    "location": "",
                },
            },
        ],
    }


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


def _schedule() -> list[dict]:
    """Tiny schedule covering every game type the hygiene pass branches on."""
    return [
        _event("reg", league="nba", when="2025-10-22T02:00Z", display="2025-26", year=2026, abbrev="reg", home="Lakers", away="Warriors"),
        _event("pre", league="nba", when="2025-10-04T23:00Z", display="2025-26", year=2026, abbrev="pre", home="Lakers", away="Warriors"),
        _event("sum", league="nba-summer-las-vegas", when="2025-07-11T02:00Z", display="2025", year=2025, abbrev="reg", home="Lakers", away="Kings"),
        _event("post", league="nba", when="2026-04-20T00:00Z", display="2025-26", year=2026, abbrev="post", home="Lakers", away="Rockets"),
        _event("pin", league="nba", when="2026-04-15T00:00Z", display="2025-26", year=2026, abbrev="playin", home="Hawks", away="Magic"),
        _event("glg", league="nba-development", when="2026-01-05T00:00Z", display="2025-26", year=2026, abbrev="reg", home="Remix", away="Stars"),
        _event("phi", league="nba", when="2026-01-10T00:00Z", display="2025-26", year=2026, abbrev="reg", home="76ers", away="Celtics"),
        _event("wreg", league="wnba", when="2026-05-08T23:00Z", display="2026", year=2026, abbrev="reg", home="Mystics", away="Tempo"),
        # Same nicknames on the same night in the G League and the NBA.
        _event("nba-dup", league="nba", when="2026-02-26T03:00Z", display="2025-26", year=2026, abbrev="reg", home="Lakers", away="Suns"),
        _event("g-dup", league="nba-development", when="2026-02-26T03:00Z", display="2025-26", year=2026, abbrev="reg", home="Lakers", away="Suns"),
    ]


def _local(when: str) -> str:
    """One arena-local date for a UTC kickoff, formatted M/D/YYYY."""
    instant = _parse_event_instant(when)
    assert instant is not None
    iso = sorted(_local_dates(instant))[0]
    parsed = datetime.strptime(iso, "%Y-%m-%d")
    return f"{parsed.month}/{parsed.day}/{parsed.year}"


class TestHygieneRules:
    """Schedule join, drop rules, and the cross-season duplicate."""

    def test_regular_season_label_expands_display_name(self):
        # ESPN records "2025-26". The CSV column keeps the scraper's
        # four-digit form "2025-2026", derived from that displayName.
        rows = [_row("Player A", "2025-2026", _local("2025-10-22T02:00Z"), "Lakers", "Warriors")]
        report = hygiene_rows(rows, _schedule(), league="nba")
        assert report.output_rows == 1
        assert report.rows[0]["Season"] == "2025-2026"
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR

    def test_summer_league_and_preseason_are_dropped(self):
        rows = [
            _row("Player A", "2025-2026", _local("2025-07-11T02:00Z"), "Lakers", "Kings"),
            _row("Player A", "2025-2026", _local("2025-10-04T23:00Z"), "Lakers", "Warriors"),
            _row("Player A", "2025-2026", _local("2025-10-22T02:00Z"), "Lakers", "Warriors"),
        ]
        report = hygiene_rows(rows, _schedule(), league="nba")
        assert report.output_rows == 1
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR
        assert report.dropped[GAME_TYPE_SUMMER] == 1
        assert report.dropped[GAME_TYPE_PRESEASON] == 1

    def test_playoffs_and_play_in_stay_and_are_labeled(self):
        rows = [
            _row("Player A", "2025-2026", _local("2026-04-20T00:00Z"), "Lakers", "Rockets"),
            _row("Player B", "2025-2026", _local("2026-04-15T00:00Z"), "Hawks", "Magic"),
        ]
        report = hygiene_rows(rows, _schedule(), league="nba")
        by_type = {row["GameType"]: row for row in report.rows}
        assert set(by_type) == {GAME_TYPE_PLAYOFFS, GAME_TYPE_PLAY_IN}
        assert by_type[GAME_TYPE_PLAYOFFS]["Season"] == "2025-2026"
        assert by_type[GAME_TYPE_PLAY_IN]["Season"] == "2025-2026"

    def test_g_league_and_unmatched_college_rows_are_dropped(self):
        rows = [
            _row("Player G", "2025-2026", _local("2026-01-05T00:00Z"), "Remix", "Stars"),
            _row("Player C", "2025-2026", "2/15/2025", "Georgetown", "Butler"),
        ]
        report = hygiene_rows(rows, _schedule(), league="nba")
        assert report.output_rows == 0

    def test_sixers_alias_joins_recorded_76ers_name(self):
        # team_directory.json records shortDisplayName "76ers". The scraper
        # writes "Sixers". The row still has to find the event.
        rows = [_row("Player S", "2025-2026", _local("2026-01-10T00:00Z"), "Sixers", "Celtics")]
        report = hygiene_rows(rows, _schedule(), league="nba")
        assert report.output_rows == 1
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR
        assert report.rows[0]["Team"] == "Sixers"

    def test_parent_league_wins_when_g_league_shares_nicknames(self):
        rows = [_row("Austin Reaves", "2025-2026", _local("2026-02-26T03:00Z"), "Lakers", "Suns", pts="20")]
        report = hygiene_rows(rows, _schedule(), league="nba")
        assert report.output_rows == 1
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR
        assert report.ambiguous == 0

    def test_cross_season_duplicate_keeps_the_schedule_season(self):
        # Same box score stored once under the wrong season and once under
        # the season the schedule assigns. Keep the matching copy.
        date = _local("2026-05-08T23:00Z")
        rows = [
            _row("Maria Conde", "2025", date, "Tempo", "Mystics", pts="2"),
            _row("Maria Conde", "2026", date, "Tempo", "Mystics", pts="2"),
        ]
        report = hygiene_rows(rows, _schedule(), league="wnba")
        assert report.output_rows == 1
        assert report.duplicates_removed == 1
        assert report.rows[0]["Season"] == "2026"
        assert report.rows[0]["GameType"] == GAME_TYPE_REGULAR
        assert report.rows[0]["Player"] == "Maria Conde"


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
