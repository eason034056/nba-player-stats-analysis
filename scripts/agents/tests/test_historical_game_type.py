"""SPO-97 — the historical agent stays on regular-season games.

``_games_for`` is the props path. Playoff and play-in rows stay in the CSV
so ``CSVPlayerHistoryService`` can opt in, but this tool has no opt-in flag.
The rows below are copied from the shipped CSVs and retagged.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

_AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.abspath(os.path.join(_AGENTS_DIR, "..", ".."))
_BACKEND = os.path.join(_REPO, "backend")
for _path in (_BACKEND, _AGENTS_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.services.csv_player_history import CSVPlayerHistoryService
from app.services.game_log_hygiene import (
    GAME_TYPE_AMBIGUOUS,
    GAME_TYPE_NBA_CUP,
    GAME_TYPE_PLAY_IN,
    GAME_TYPE_PLAYOFFS,
    GAME_TYPE_REGULAR,
    GAME_TYPE_UNCLASSIFIED,
    _local_dates,
    _parse_event_instant,
    load_schedule_events,
)
from tools import historical


def _shipped(name: str) -> list[dict[str, str]]:
    """Rows from a canonical CSV under ``data/``."""
    path = Path(_REPO) / "data" / name
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    """Write ``rows`` with the header of the first row."""
    columns = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _retagged(template: dict[str, str], player: str, game_type: str, date: str, pts: str) -> dict[str, str]:
    """Copy a real game log and stamp the game type under test."""
    row = dict(template)
    row["Player"] = player
    row["GameType"] = game_type
    row["Date"] = date
    row["PTS"] = pts
    row["MIN"] = "24:00"
    return row


def test_games_for_keeps_regular_season_only(tmp_path, monkeypatch):
    """Playoff and play-in minutes must not enter a season hit rate."""
    template = next(row for row in _shipped("nba_player_game_logs.csv") if row["GameType"] == GAME_TYPE_REGULAR)
    player = "Agent Player"
    rows = [
        _retagged(template, player, GAME_TYPE_REGULAR, "1/5/2026", "11"),
        _retagged(template, player, GAME_TYPE_PLAYOFFS, "4/20/2026", "40"),
        _retagged(template, player, GAME_TYPE_PLAY_IN, "4/15/2026", "33"),
    ]
    path = tmp_path / "nba_player_game_logs.csv"
    _write(path, rows)
    monkeypatch.setattr("app.services.csv_player_history.CSV_PATH", str(path))
    fresh = CSVPlayerHistoryService(league="nba")
    monkeypatch.setitem(historical._CSV_SVCS, "nba", fresh)

    games = historical._games_for(player, league="nba")

    assert len(games) == 1
    assert games[0]["game_type"] == GAME_TYPE_REGULAR
    assert games[0]["points"] == 11


def test_wnba_games_for_keeps_regular_season_only(tmp_path, monkeypatch):
    """WNBA uses the same filter. There is no separate playoff switch on the tool."""
    template = next(row for row in _shipped("wnba_player_game_logs.csv") if row["GameType"] == GAME_TYPE_REGULAR)
    player = "Agent Player"
    rows = [
        _retagged(template, player, GAME_TYPE_REGULAR, "5/20/2025", "14"),
        _retagged(template, player, GAME_TYPE_PLAYOFFS, "9/20/2025", "30"),
    ]
    path = tmp_path / "wnba_player_game_logs.csv"
    _write(path, rows)
    monkeypatch.setenv("WNBA_CSV_DATA_PATH", str(path))
    fresh = CSVPlayerHistoryService(league="wnba")
    monkeypatch.setitem(historical._CSV_SVCS, "wnba", fresh)

    games = historical._games_for(player, league="wnba")

    assert len(games) == 1
    assert games[0]["game_type"] == GAME_TYPE_REGULAR
    assert games[0]["points"] == 14


def test_backtest_hit_rate_excludes_unclassified_and_cup_finals(tmp_path, monkeypatch):
    """``evaluation/backtest.py`` calls ``get_base_stats``, which calls ``_games_for``.

    Unclassified and ambiguous rows are not loaded. The Cup final is loaded
    and then dropped, because this tool keeps ``regular_season`` only.
    A 40-point row of either kind would have made the hit rate 0.5.
    """
    template = next(row for row in _shipped("nba_player_game_logs.csv") if row["GameType"] == GAME_TYPE_REGULAR)
    player = "Backtest Player"
    rows = [
        _retagged(template, player, GAME_TYPE_REGULAR, "1/5/2026", "11"),
        _retagged(template, player, GAME_TYPE_UNCLASSIFIED, "1/6/2026", "40"),
        _retagged(template, player, GAME_TYPE_AMBIGUOUS, "1/7/2026", "40"),
        _retagged(template, player, GAME_TYPE_NBA_CUP, "12/17/2024", "40"),
        _retagged(template, player, GAME_TYPE_PLAYOFFS, "4/20/2026", "40"),
    ]
    path = tmp_path / "nba_player_game_logs.csv"
    _write(path, rows)
    monkeypatch.setattr("app.services.csv_player_history.CSV_PATH", str(path))
    fresh = CSVPlayerHistoryService(league="nba")
    monkeypatch.setitem(historical._CSV_SVCS, "nba", fresh)

    games = historical._games_for(player, league="nba")
    signal = historical.get_base_stats(player, "points", 20, league="nba")

    assert [game["game_type"] for game in games] == [GAME_TYPE_REGULAR]
    assert signal["details"]["total"] == 1
    assert signal["details"]["hit_rate"] == 0
    assert signal["details"]["mean"] == 11
    loaded = {game["game_type"] for game in fresh._cache[player]}
    assert GAME_TYPE_UNCLASSIFIED not in loaded
    assert GAME_TYPE_AMBIGUOUS not in loaded
    assert GAME_TYPE_NBA_CUP in loaded


# Recorded ids in tests/fixtures/espn/schedule_events.json. Same recordings
# the hygiene tests use. This test copies their clubs and local dates and
# does not invent an odds or schedule payload.
_REGULAR_OPENER = "401809243"  # Rockets at Thunder
_PLAYOFFS = "401869187"  # Raptors at Cavaliers
_PLAY_IN = "401866755"  # Heat at Hornets
_CUP_FINAL = "401734908"  # NBA Cup Championship


def _recorded(event_id: str) -> dict:
    """One compact event from the recorded ESPN fixture."""
    found = next(
        (event for event in load_schedule_events() if str(event.get("id")) == event_id),
        None,
    )
    assert found is not None, event_id
    return found


def _fixture_date(event: dict) -> str:
    """Arena-local day of a recorded kickoff, as ``M/D/YYYY``."""
    instant = _parse_event_instant(str(event.get("date") or ""))
    assert instant is not None, event.get("id")
    iso = sorted(_local_dates(instant))[0]
    year, month, day = iso.split("-")
    return f"{int(month)}/{int(day)}/{year}"


def _fixture_clubs(event: dict) -> tuple[str, str]:
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


def _from_fixture(
    template: dict[str, str],
    event: dict,
    player: str,
    game_type: str,
    pts: str,
    minutes: str,
) -> dict[str, str]:
    """Copy a real game-log header and stamp one recorded event onto it."""
    row = _retagged(template, player, game_type, _fixture_date(event), pts)
    home, away = _fixture_clubs(event)
    row["Team"] = home
    row["Opponent"] = away
    row["MIN"] = minutes
    return row


def test_games_for_resolved_name_drops_playoff_dnp_and_cup(tmp_path, monkeypatch):
    """An accented query resolves, then the props filter still applies.

    ``Nikola Jokić`` is not the stored spelling. The old substring fallback
    does not fold the accent, so an empty result would mean resolution was
    dropped. A playoff or Cup row in the result would mean only the
    minutes check survived the merge. The DNP is a regular-season row with
    zero minutes, dated from the recorded play-in so it is a separate game.
    ``_team_for`` still reads that playoff row.
    """
    template = next(
        row for row in _shipped("nba_player_game_logs.csv") if row["GameType"] == GAME_TYPE_REGULAR
    )
    regular = _recorded(_REGULAR_OPENER)
    playoff = _recorded(_PLAYOFFS)
    dnp_event = _recorded(_PLAY_IN)
    cup = _recorded(_CUP_FINAL)
    stored = "Nikola Jokic"
    rows = [
        _from_fixture(template, regular, stored, GAME_TYPE_REGULAR, "11", "24:00"),
        _from_fixture(template, playoff, stored, GAME_TYPE_PLAYOFFS, "40", "36:00"),
        _from_fixture(template, dnp_event, stored, GAME_TYPE_REGULAR, "99", "0:00"),
        _from_fixture(template, cup, stored, GAME_TYPE_NBA_CUP, "40", "30:00"),
    ]
    assert len({row["Date"] for row in rows}) == 4
    path = tmp_path / "nba_player_game_logs.csv"
    _write(path, rows)
    monkeypatch.setattr("app.services.csv_player_history.CSV_PATH", str(path))
    fresh = CSVPlayerHistoryService(league="nba")
    monkeypatch.setitem(historical._CSV_SVCS, "nba", fresh)

    games = historical._games_for("Nikola Jokić", league="nba")

    assert "Nikola Jokić" not in fresh._cache
    assert len(fresh._cache[stored]) == 4
    assert [game["points"] for game in games] == [11]
    assert games[0]["game_type"] == GAME_TYPE_REGULAR
    assert games[0]["minutes"] > 0
    assert games[0]["team"] == _fixture_clubs(regular)[0]
    assert historical._games_for("Jokic", league="nba") == []
    playoff_team, _playoff_opponent = _fixture_clubs(playoff)
    assert historical._team_for("Nikola Jokić", _fixture_date(playoff), league="nba") == playoff_team
