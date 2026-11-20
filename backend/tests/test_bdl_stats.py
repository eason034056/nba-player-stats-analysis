"""
test_bdl_stats.py - normalizing BALLDONTLIE /v1/stats rows.

Rows come from the SPO-138a captures in backend/tests/fixtures/bdl/:
``stats__season2000_page1.json`` (2000-01) and
``stats__season2025_page1.json`` (2025-26). The two seasons spell a
did-not-play row differently, which is what these tests pin down.
Later pages hold the spellings the full walks found:
``stats__season2000_cursor272160_page.json`` (a ``28:60`` row),
``stats__season2025_cursor43451886_page.json`` (rows with no minutes and
``plus_minus: 0``), ``stats__season2020_cursor6587519_page.json`` and
``stats__season2020_cursor6603185_page.json`` (play-in percentages on a
0-100 scale), ``stats__season2025_cursor24626559_page.json`` (the page
where did-not-play rows switch from ``plus_minus: null`` to ``0``), and
``stats__season2026_page1.json`` (2026-27 did-not-play rows as ``min: "0"``).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.bdl_stats import BdlStatLine, BdlStatRowError, normalize_stat_row, parse_minutes

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"

# Written out here, not imported, so a stat the module forgets fails a test.
BOX_STATS = (
    "pts", "reb", "ast", "stl", "blk", "turnover", "pf",
    "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb",
)
SHOOTING_PCTS = ("fg_pct", "fg3_pct", "ft_pct")


def _rows(season: int) -> list[dict[str, Any]]:
    """The 100 recorded rows for one season's first page."""
    capture = json.loads((FIXTURE_DIR / f"stats__season{season}_page1.json").read_text())
    return capture["response"]["data"]


SIXTY_SECONDS_PAGE = "stats__season2000_cursor272160_page.json"
NO_MINUTES_PAGE = "stats__season2025_cursor43451886_page.json"
PLAY_IN_PAGE = "stats__season2020_cursor6587519_page.json"
PLAY_IN_NEXT_PAGE = "stats__season2020_cursor6603185_page.json"
PLUS_MINUS_ZERO_PAGE = "stats__season2025_cursor24626559_page.json"
SEASON_2026_PAGE = "stats__season2026_page1.json"
SHOOTING = (("fg_pct", "fgm", "fga"), ("fg3_pct", "fg3m", "fg3a"), ("ft_pct", "ftm", "fta"))


def _page(name: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURE_DIR / name).read_text())["response"]["data"]


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [("16", 960), ("49", 2940), ("13:44", 824), ("40:42", 2442), ("0", 0), ("00", 0)],
)
def test_parse_minutes_returns_seconds(raw: str, seconds: int) -> None:
    """Both spellings in the captures: whole minutes and minutes:seconds."""
    assert parse_minutes(raw) == seconds


@pytest.mark.parametrize("raw", [None, ""])
def test_parse_minutes_returns_none_when_absent(raw: str | None) -> None:
    """The 2000-01 did-not-play rows send ``min: null``."""
    assert parse_minutes(raw) is None


@pytest.mark.parametrize("raw", ["12.5", "abc", "1:2:3", "13:61", "13:99", " 16", 16])
def test_parse_minutes_rejects_unknown_spellings(raw: Any) -> None:
    """A spelling no capture shows is an error, not a guess."""
    with pytest.raises(BdlStatRowError):
        parse_minutes(raw)


def _stats_of(line: BdlStatLine) -> dict[str, Any]:
    """Box stats, percentages, plus_minus and seconds: the fields a DNP row must clear."""
    names = (*BOX_STATS, *SHOOTING_PCTS, "plus_minus", "seconds_played")
    return {name: getattr(line, name) for name in names}


def test_2000_dnp_rows_have_no_stat_line() -> None:
    """2000-01 spells DNP as ``min: null`` with every stat null."""
    dnp_rows = [row for row in _rows(2000) if row["min"] is None]
    assert len(dnp_rows) == 4
    for row in dnp_rows:
        line = normalize_stat_row(row)
        assert line.dnp is True
        assert set(_stats_of(line).values()) == {None}


def test_2025_zero_minute_rows_without_plus_minus_are_dnp() -> None:
    """2025-26 spells DNP as ``min: "00"`` with zeros, percentages included; the zeros become null."""
    dnp_rows = [row for row in _rows(2025) if row["min"] == "00"]
    assert len(dnp_rows) == 37
    for row in dnp_rows:
        assert row["pts"] == 0
        assert row["fg_pct"] == 0
        line = normalize_stat_row(row)
        assert line.dnp is True
        assert set(_stats_of(line).values()) == {None}


def test_zero_minute_row_with_zero_plus_minus_and_no_stats_is_dnp() -> None:
    """BALLDONTLIE sends ``plus_minus: 0`` on did-not-play rows too, so a 0 shows no court time."""
    (row,) = [row for row in _rows(2025) if row["min"] == "0"]
    assert row["plus_minus"] == 0
    line = normalize_stat_row(row)
    assert line.dnp is True
    assert set(_stats_of(line).values()) == {None}


@pytest.mark.parametrize(
    ("page", "minutes", "count"),
    [(PLUS_MINUS_ZERO_PAGE, "00", 9), (SEASON_2026_PAGE, "0", 19)],
    ids=["2025-26-from-december", "2026-27"],
)
def test_did_not_play_rows_spelled_with_zero_plus_minus(page: str, minutes: str, count: int) -> None:
    """From 2025-12-23 a 2025-26 DNP row is ``"00"`` with ``plus_minus: 0``; 2026-27 sends ``"0"``.

    Read as played, they made 30.5 players a game in 2025-26 against about
    21 in every other season, while players with a minute or more stayed at 21.7.
    """
    rows = [row for row in _page(page) if row["min"] == minutes and row["plus_minus"] == 0]
    assert len(rows) == count
    lines = [normalize_stat_row(row) for row in rows]
    assert all(line.dnp for line in lines)
    assert all(value is None for line in lines for value in _stats_of(line).values())


def test_page_where_the_dnp_spelling_changes_reads_both_as_dnp() -> None:
    """The same page has 25 DNP rows with ``plus_minus: null`` and 9 with 0."""
    rows = [row for row in _page(PLUS_MINUS_ZERO_PAGE) if row["min"] == "00"]
    assert sorted(str(row["plus_minus"]) for row in rows) == ["0"] * 9 + ["None"] * 25
    assert all(normalize_stat_row(row).dnp for row in rows)


def test_zero_minute_row_with_a_nonzero_plus_minus_is_played() -> None:
    """The score moved while he was on court, so ``"0"`` here is under a minute."""
    row = next(row for row in _page(PLAY_IN_NEXT_PAGE) if row["id"] == 6611147)
    assert (row["min"], row["plus_minus"], row["pts"]) == ("0", -2, 0)
    line = normalize_stat_row(row)
    assert (line.dnp, line.seconds_played, line.plus_minus) == (False, 0, -2)


@pytest.mark.parametrize(
    ("page", "stat_id", "seconds"),
    [(SEASON_2026_PAGE, 45163101, 74), ("stats__season2000_page1.json", 270110, 240)],
    ids=["2026-27-plus-minus-0", "2000-01-plus-minus-null"],
)
def test_minutes_with_no_stats_are_played(page: str, stat_id: int, seconds: int) -> None:
    """Seconds on the clock are court time even when nothing else was recorded."""
    row = next(row for row in _page(page) if row["id"] == stat_id)
    assert not any(row[name] for name in BOX_STATS)
    line = normalize_stat_row(row)
    assert (line.dnp, line.seconds_played) == (False, seconds)


def test_zero_minute_row_with_a_stat_is_played() -> None:
    """2005-06 has ``"0"`` minute rows with points (Pat Garrity, 3 on 2005-12-19)."""
    row = dict(next(row for row in _page(SEASON_2026_PAGE) if row["min"] == "0" and row["plus_minus"] == 0))
    row.update(pts=3, fgm=1, fga=2)
    line = normalize_stat_row(row)
    assert (line.dnp, line.seconds_played, line.pts) == (False, 0, 3)


def test_played_row_keeps_the_recorded_box_score() -> None:
    """A minutes:seconds row from 2000-01 keeps every stat as recorded."""
    row = next(row for row in _rows(2000) if row["min"] == "13:44")
    line = normalize_stat_row(row)
    assert line.dnp is False
    assert line.seconds_played == 824
    recorded = (*BOX_STATS, *SHOOTING_PCTS)
    assert {name: getattr(line, name) for name in recorded} == {name: row[name] for name in recorded}
    assert (line.stat_id, line.game_id, line.player_id) == (row["id"], row["game"]["id"], row["player"]["id"])


def test_played_row_without_attempts_keeps_a_null_percentage() -> None:
    """No shots means no percentage. BDL sends null there, and null is kept, not read as 0%."""
    row = next(row for row in _rows(2000) if row["min"] == "3")
    assert (row["fga"], row["fg_pct"], row["fta"], row["ft_pct"]) == (0, None, 2, 1)
    line = normalize_stat_row(row)
    assert line.dnp is False
    assert (line.fg_pct, line.fg3_pct, line.ft_pct) == (None, None, 1.0)


@pytest.mark.parametrize("bad_pct", [100.5, -0.1])
def test_percentage_outside_both_scales_raises_row_error(bad_pct: float) -> None:
    """A percentage is a 0-1 fraction or a 0-100 play-in value; anything else is refused."""
    row = dict(next(row for row in _rows(2000) if row["min"] == "13:44"))
    row["fg_pct"] = bad_pct
    with pytest.raises(BdlStatRowError):
        normalize_stat_row(row)


def test_team_id_is_the_team_in_that_game() -> None:
    """``player.team_id`` is the player's team today; the row's ``team`` is the team that night."""
    moved = [row for row in _rows(2000) if row["player"]["team_id"] != row["team"]["id"]]
    assert moved
    for row in moved:
        assert normalize_stat_row(row).team_id == row["team"]["id"]


@pytest.mark.parametrize(("season", "dnp_count"), [(2000, 4), (2025, 38), (2026, 19)])
def test_every_recorded_row_normalizes(season: int, dnp_count: int) -> None:
    """No captured row raises, and the DNP count matches the analysis above."""
    lines = [normalize_stat_row(row) for row in _rows(season)]
    assert sum(line.dnp for line in lines) == dnp_count


@pytest.mark.parametrize("field", ["pts", "fg_pct"])
def test_row_missing_a_field_raises_row_error(field: str) -> None:
    """Schema drift is reported per row instead of a bare KeyError."""
    row = dict(_rows(2000)[0])
    del row[field]
    with pytest.raises(BdlStatRowError):
        normalize_stat_row(row)


def test_stats_without_minutes_raise_row_error() -> None:
    """A row with stats but ``min: null`` contradicts itself; it is not guessed as DNP or played."""
    row = dict(next(row for row in _rows(2000) if row["min"] == "13:44"))
    row["min"] = None
    with pytest.raises(BdlStatRowError):
        normalize_stat_row(row)


def test_sixty_seconds_rolls_into_the_next_minute() -> None:
    """``28:60`` is in 19 rows of the 2000-01 walk, every one a player who played. It is 29:00."""
    assert parse_minutes("28:60") == 29 * 60


def test_recorded_sixty_second_row_is_a_played_line() -> None:
    """Stephon Marbury's 41 points on 2000-11-11 were refused before 60 seconds was read."""
    row = next(row for row in _page(SIXTY_SECONDS_PAGE) if row["min"] == "28:60")
    line = normalize_stat_row(row)
    assert (line.dnp, line.seconds_played, line.pts) == (False, 29 * 60, row["pts"])


def test_rows_with_no_minutes_no_stats_and_zero_plus_minus_are_dnp() -> None:
    """BALLDONTLIE added these 21 rows to 2025-26 later, all on its last page.

    Every team they belong to already has its 240 minutes without them, so
    they are did-not-play rows spelled with ``plus_minus: 0`` instead of null.
    """
    rows = [row for row in _page(NO_MINUTES_PAGE) if row["min"] is None]
    assert len(rows) == 21
    lines = [normalize_stat_row(row) for row in rows]
    assert all(line.dnp for line in lines)
    assert all(value is None for line in lines for value in _stats_of(line).values())


@pytest.mark.parametrize(
    "court_time",
    [{"plus_minus": 3}, {"pts": 2, "fgm": 1, "fga": 1}],
    ids=["plus-minus", "points"],
)
def test_no_minutes_with_a_sign_of_court_time_still_raises(court_time: dict[str, int]) -> None:
    """Only a line of zeros reads as did-not-play. Any court time with no minutes contradicts itself."""
    row = dict(next(row for row in _page(NO_MINUTES_PAGE) if row["min"] is None))
    row.update(court_time)
    with pytest.raises(BdlStatRowError):
        normalize_stat_row(row)


def test_play_in_percentages_on_a_0_to_100_scale_become_fractions() -> None:
    """The 2019-20 to 2021-22 play-in games send 66.7 for 4 of 6, not 0.667.

    All 584 such values in the walk equal 100 * made / attempted rounded to
    a tenth, so each is read as a percentage. A single-game share under 1%
    is not possible, so a value over 1 cannot be a fraction. The rounding
    can be exactly half a step: 7 of 16 is 0.4375 and arrives as 43.8.
    """
    half_a_step = 0.0005 + 1e-9
    rows = [row for row in _page(PLAY_IN_PAGE) if any((row[pct] or 0) > 1 for pct in SHOOTING_PCTS)]
    assert len(rows) == 70
    for row in rows:
        line = normalize_stat_row(row)
        for pct, made, attempted in SHOOTING:
            if row[attempted]:
                value = getattr(line, pct)
                assert value == round(value, 3), "three decimals, like the 0-1 values BALLDONTLIE rounds"
                assert value == pytest.approx(row[made] / row[attempted], abs=half_a_step)


@pytest.mark.parametrize(("name", "sent_as_zero"), [(SEASON_2026_PAGE, 60), (PLAY_IN_PAGE, 64)])
def test_a_shot_type_never_taken_has_no_percentage(name: str, sent_as_zero: int) -> None:
    """Several seasons send 0 for a shot type the player never took (all of 2015-16 to 2017-18).

    0 of 0 is not 0%, so it is stored as null like the seasons that send null.
    No row in the walk has a percentage above 0 with no attempts.
    """
    zeros = 0
    for row in _page(name):
        line = normalize_stat_row(row)
        if line.dnp:
            continue
        for pct, _, attempted in SHOOTING:
            if row[attempted] == 0:
                zeros += row[pct] == 0
                assert getattr(line, pct) is None
            else:
                assert getattr(line, pct) is not None
    assert zeros == sent_as_zero


@pytest.mark.parametrize(
    "name",
    [SIXTY_SECONDS_PAGE, NO_MINUTES_PAGE, PLAY_IN_PAGE, PLAY_IN_NEXT_PAGE, PLUS_MINUS_ZERO_PAGE, SEASON_2026_PAGE],
)
def test_every_row_of_the_later_pages_normalizes(name: str) -> None:
    for row in _page(name):
        normalize_stat_row(row)
