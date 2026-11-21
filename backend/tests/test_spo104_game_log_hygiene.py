"""SPO-104 follow-ups for the offline schedule index.

A team-schedule filename with no league prefix raises. A blank or
missing ``GameType`` is regular season.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.game_log_hygiene import (
    GAME_TYPE_REGULAR,
    _SCHEDULE_CACHE,
    _overlay_recorded_team_schedules,
    coalesce_game_type,
)


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
