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


def test_offline_index_labels_commissioners_cup_final():
    compact = json.loads(default_schedule_path().read_text(encoding="utf-8"))
    before = next(event for event in compact if str(event.get("id")) == _CUP_EVENT_ID)
    assert game_type_for_event(before) == GAME_TYPE_REGULAR

    events = load_schedule_events()
    event = next(event for event in events if str(event.get("id")) == _CUP_EVENT_ID)
    assert event["league"] == "wnba"
    assert game_type_for_event(event) == GAME_TYPE_CUP
    notes = (event.get("competition") or {}).get("notes") or []
    assert any(
        "Commissioner" in str((note or {}).get("headline") or "") for note in notes
    )


def test_explicit_league_is_not_read_from_the_filename(caplog):
    with caplog.at_level(logging.WARNING):
        events = load_schedule_events(league="wnba")
    assert not any("No league was passed" in record.message for record in caplog.records)
    event = next(event for event in events if str(event.get("id")) == _CUP_EVENT_ID)
    assert event["league"] == "wnba"
    assert game_type_for_event(event) == GAME_TYPE_CUP


def test_missing_league_falls_back_to_the_filename_with_a_warning(caplog):
    with caplog.at_level(logging.WARNING):
        events = load_schedule_events()
    assert any(
        "No league was passed" in record.message and "wnba" in record.message
        for record in caplog.records
    )
    event = next(event for event in events if str(event.get("id")) == _CUP_EVENT_ID)
    assert game_type_for_event(event) == GAME_TYPE_CUP


def test_filename_without_a_league_prefix_raises(tmp_path: Path):
    schedule = tmp_path / "schedule_events.json"
    schedule.write_text("[]", encoding="utf-8")
    bad = tmp_path / "_team_1_schedule_2025_type_2.json"
    bad.write_text('{"events": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="no league prefix"):
        _overlay_recorded_team_schedules(schedule, [])


def test_passed_league_overrides_a_filename_with_no_prefix(tmp_path: Path):
    schedule = tmp_path / "schedule_events.json"
    schedule.write_text("[]", encoding="utf-8")
    recorded = (
        Path(__file__).resolve().parents[2]
        / "tests"
        / "fixtures"
        / "espn"
        / "recorded"
        / "wnba_team_5_schedule_2025_type_2.json"
    )
    target = tmp_path / "_team_5_schedule_2025_type_2.json"
    target.write_bytes(recorded.read_bytes())
    merged = _overlay_recorded_team_schedules(schedule, [], league="wnba")
    event = next(item for item in merged if str(item.get("id")) == _CUP_EVENT_ID)
    assert event["league"] == "wnba"
    assert game_type_for_event(event) == GAME_TYPE_CUP


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
