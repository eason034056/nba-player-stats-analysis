"""SPO-135h QA: status table, board filter, and top_read Out skip.

If the product rule is that only Out nulls the NBA blend, every other
word keeps the same number as a plain Questionable row. The filtered
board keeps Out with a null blend and applies the blend floor to the
rest. top_read still skips only Out. WNBA coverage stays in the
ticket's own test file.

Odds shells and injury names come from recorded fixtures. Tests only
change a description or the status word on an already-normalized row.
"""

from __future__ import annotations

import pytest

from app.models.schemas import DailyPick
from app.services.daily_analysis import best_top_reads, select_daily_picks
from app.services.pick_signals import build_nba_signals
from tests.test_spo135c_bdl_injury_status import _entry, _named, _picks_for
from tests.test_spo135g_top_read_out import (
    _EVENT_ID,
    _analyze,
    _books,
    _cache,
    _recorded_event,
    _sources,
)

# Words the blend should treat like Questionable, including case and
# surrounding whitespace, plus labels the normalizer never emits.
_KEEP = (
    None,
    "",
    "Questionable",
    " questionable ",
    "QUESTIONABLE",
    "Doubtful",
    " Doubtful ",
    "DOUBTFUL",
    "Probable",
    "probable",
    " PROBABLE ",
    "Day-To-Day",
    "day-to-day",
    "Day-to-day",
    "GTD",
    "Game Time Decision",
    "Available",
    "unknown",
)

_OUT = ("Out", "out", " OUT ", "\tOut")


def _points(picks, name: str):
    rows = [pick for pick in _named(picks, name) if pick.metric == "points"]
    assert len(rows) == 1
    return rows[0]


def _blend(injury_status: str | None) -> float | None:
    _signals, combined, _total = build_nba_signals(
        side="over",
        line=24.5,
        player_name="Test Player",
        market_probability=0.58,
        history_rate=0.62,
        injury_status=injury_status,
    )
    return combined


def _board_pick(
    *,
    injury_status: str | None,
    combined_probability: float | None,
    n_games: int = 20,
) -> DailyPick:
    return DailyPick(
        player_name="Test Player",
        event_id="evt-qa",
        home_team="Atlanta Hawks",
        away_team="Los Angeles Lakers",
        commence_time="2026-11-10T00:10:00Z",
        metric="points",
        threshold=24.5,
        direction="over",
        probability=0.72,
        n_games=n_games,
        bookmakers_count=3,
        injury_status=injury_status,
        combined_probability=combined_probability,
    )


@pytest.mark.parametrize("status", _KEEP)
def test_non_out_status_keeps_the_questionable_blend(status: str | None) -> None:
    """A non-Out word keeps the same number as Questionable."""
    kept = _blend(status)
    plain = _blend("Questionable")
    assert kept is not None
    assert kept == plain


@pytest.mark.parametrize("status", _OUT)
def test_out_status_nulls_the_blend(status: str) -> None:
    """Out, ignoring case and surrounding whitespace, still nulls the blend."""
    assert _blend(status) is None


@pytest.mark.parametrize("status", _KEEP)
def test_board_applies_the_blend_floor_to_a_non_out_status(
    status: str | None,
) -> None:
    """A non-Out row stays at the floor and leaves when the floor is higher.

    A cached Questionable row whose blend is still null (the previous
    rule) also leaves. Out is not in this table.
    """
    kept = _board_pick(injury_status=status, combined_probability=0.70)
    assert select_daily_picks([kept], min_probability=0.70) == [kept]
    assert select_daily_picks([kept], min_probability=0.7001) == []
    stale = _board_pick(injury_status=status, combined_probability=None)
    assert select_daily_picks([stale]) == []


@pytest.mark.parametrize("status", _OUT)
def test_board_keeps_out_with_a_null_blend(status: str) -> None:
    """Out stays on the board when the sample floor passes, even with no blend."""
    row = _board_pick(injury_status=status, combined_probability=None)
    assert select_daily_picks([row]) == [row]
    short = _board_pick(
        injury_status=status, combined_probability=None, n_games=9
    )
    assert select_daily_picks([short]) == []


def test_recorded_probable_and_day_to_day_match_questionable_on_picks() -> None:
    """Recorded Probable and Day-To-Day rows keep the Questionable blend.

    Each name comes from the recorded injury page. The odds capture
    only changes description so those names are the posted players.
    History is the same stub for every name.
    """
    questionable = _entry("Questionable")
    probable = _entry("Probable")
    day = _entry("Day-To-Day")
    picks = _picks_for(
        [questionable["player"], probable["player"], day["player"]],
        [questionable, probable, day],
    )
    plain = _points(picks, questionable["player"])
    for entry in (probable, day):
        row = _points(picks, entry["player"])
        assert row.injury_status == entry["status"]
        assert row.combined_probability is not None
        assert row.combined_probability == plain.combined_probability


def test_top_read_skips_out_and_keeps_the_raw_doubtful_next() -> None:
    """The best stored pick is Out, so a raw Doubtful next row is chosen.

    Both names are on the recorded injury page. Only descriptions on
    the recorded player_points books change.
    """
    out = _entry("Out")
    doubtful = _entry("Questionable", raw="Doubtful")
    assert out["player"] != doubtful["player"]
    best_source, nxt, _healthy = _sources(out["player"])
    picks = _analyze(
        _recorded_event(_EVENT_ID),
        _books({best_source: out["player"], nxt: doubtful["player"]}),
        {out["player"]: 0.91, doubtful["player"]: 0.72},
    )
    reads = best_top_reads(
        _cache(picks),
        injury_entries=[out, doubtful],
    )
    assert reads[_EVENT_ID].player == doubtful["player"]
    assert out["player"] not in {read.player for read in reads.values()}
