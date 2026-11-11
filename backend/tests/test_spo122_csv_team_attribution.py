"""SPO-122: do not label an event with a CSV club that is not playing.

The excerpt is copied, line for line, from ``data/nba_player_game_logs.csv``.
Anfernee Simons' last row in that file is 2026-02-21, Bulls. The recorded
Celtics at 76ers event is 2026-11-11. Bulls is not in that game, and the
older Celtics stint is not substituted for it.
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
from app.services.daily_analysis import canonical_team_code
from tests.fixtures.odds_api import NBA_EXPANDED_MARKETS, load_odds_fixture

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
_EXCERPT = _BACKEND / "tests" / "fixtures" / "csv" / "spo122_anfernee_simons_excerpt.csv"
_SHIPPED = _REPO / "data" / "nba_player_game_logs.csv"


@pytest.fixture
def excerpt_service(monkeypatch: pytest.MonkeyPatch) -> CSVPlayerHistoryService:
    monkeypatch.setattr(
        "app.services.csv_player_history.CSV_PATH",
        str(_EXCERPT),
    )
    service = CSVPlayerHistoryService("nba")
    service.load_csv()
    return service


def _bos_phi() -> dict:
    event = load_odds_fixture(NBA_EXPANDED_MARKETS)
    assert event["away_team"] == "Boston Celtics"
    assert event["home_team"] == "Philadelphia 76ers"
    return event


def test_excerpt_lines_are_copied_from_the_shipped_csv() -> None:
    shipped = _SHIPPED.read_text(encoding="utf-8-sig")
    excerpt_lines = _EXCERPT.read_text(encoding="utf-8").splitlines()
    assert excerpt_lines[0].startswith("Player,Season,GameType,Date,Team,")
    body = [line for line in excerpt_lines[1:] if line.strip()]
    assert body
    assert any(line.startswith("Anfernee Simons,") for line in body)
    assert any(line.startswith("Josh Giddey,") for line in body)
    for line in body:
        assert line in shipped


def test_simons_latest_row_is_bulls_and_that_code_is_chicago(
    excerpt_service: CSVPlayerHistoryService,
) -> None:
    """The file and the abbreviation map are not the bug by themselves.

    The latest row is used, and Bulls maps to CHI. That club is still
    the wrong label for the recorded event.
    """
    event = _bos_phi()
    logs = excerpt_service._cache["Anfernee Simons"]
    assert logs[0]["team"] == "Bulls"
    assert team_from_game_logs(logs, event["commence_time"]) == "Bulls"
    assert canonical_team_code("Bulls") == "CHI"
    assert team_on_event(
        logs,
        event["commence_time"],
        event["home_team"],
        event["away_team"],
    ) == ""
    assert team_on_event(
        logs,
        event["commence_time"],
        event["home_team"],
        event["away_team"],
        candidate="CHI",
    ) == ""
    # A projection that names a club in the game is kept. The older
    # Celtics stint is not used in its place.
    assert team_on_event(
        logs,
        event["commence_time"],
        event["home_team"],
        event["away_team"],
        candidate="Sixers",
    ) == "Sixers"


def test_event_teammates_omit_the_bulls_and_the_old_celtics_stint(
    excerpt_service: CSVPlayerHistoryService,
) -> None:
    event = _bos_phi()
    open_list = excerpt_service.get_teammates("Anfernee Simons")
    assert "Josh Giddey" in open_list
    assert "Derrick White" in open_list

    scoped = excerpt_service.get_player_stats(
        "Anfernee Simons",
        "points",
        9.5,
        home_team=event["home_team"],
        away_team=event["away_team"],
        as_of=event["commence_time"],
    )
    assert scoped["n_games"] > 0
    assert scoped["teammates"] == []
    assert "Josh Giddey" not in scoped["teammates"]
    assert "Derrick White" not in scoped["teammates"]


def test_a_club_that_is_in_the_game_is_kept(
    excerpt_service: CSVPlayerHistoryService,
) -> None:
    event = _bos_phi()
    logs = excerpt_service._cache["Derrick White"]
    assert team_from_game_logs(logs, event["commence_time"]) == "Celtics"
    assert team_on_event(
        logs,
        event["commence_time"],
        event["home_team"],
        event["away_team"],
    ) == "Celtics"
    mates = excerpt_service.get_player_stats(
        "Derrick White",
        "points",
        15.5,
        home_team=event["home_team"],
        away_team=event["away_team"],
        as_of=event["commence_time"],
    )["teammates"]
    assert "Anfernee Simons" in mates
    assert "Josh Giddey" not in mates
