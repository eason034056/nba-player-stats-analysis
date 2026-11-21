"""SPO-104 follow-ups for the offline schedule index.

The Commissioner's Cup final is the recorded ESPN team schedule
``tests/fixtures/espn/recorded/wnba_team_5_schedule_2025_type_2.json``,
event 401736430. The compact index lists that id as a regular-season
game with no competition notes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.services.game_log_hygiene import (
    GAME_TYPE_CUP,
    GAME_TYPE_REGULAR,
    _SCHEDULE_CACHE,
    _overlay_recorded_team_schedules,
    coalesce_game_type,
    default_schedule_path,
    game_type_for_event,
    load_schedule_events,
)

_CUP_EVENT_ID = "401736430"


@pytest.fixture(autouse=True)
def _clear_schedule_cache():
    _SCHEDULE_CACHE.clear()
    yield
    _SCHEDULE_CACHE.clear()








def test_filename_without_a_league_prefix_raises(tmp_path: Path):
    schedule = tmp_path / "schedule_events.json"
    schedule.write_text("[]", encoding="utf-8")
    bad = tmp_path / "_team_1_schedule_2025_type_2.json"
    bad.write_text('{"events": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="no league prefix"):
        _overlay_recorded_team_schedules(schedule, [])




@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, GAME_TYPE_REGULAR),
        ("", GAME_TYPE_REGULAR),
        ("   ", GAME_TYPE_REGULAR),
        ("playoffs", "playoffs"),
    ],
)
def test_blank_game_type_is_regular_season(value, expected):
    assert coalesce_game_type(value) == expected


def test_missing_game_type_cell_is_regular_season():
    row: dict[str, str] = {}
    assert coalesce_game_type(row.get("GameType")) == GAME_TYPE_REGULAR
