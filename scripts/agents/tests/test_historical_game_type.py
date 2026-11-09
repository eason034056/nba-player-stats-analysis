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
    GAME_TYPE_PLAY_IN,
    GAME_TYPE_PLAYOFFS,
    GAME_TYPE_REGULAR,
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
