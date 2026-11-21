"""SPO-135h: NBA Doubtful keeps the Questionable blend.

The recorded BALLDONTLIE page stores Doubtful as status Doubtful
(SPO-135i) and keeps raw_status Doubtful. That row is the same pick as a plain
Questionable row: a number on daily picks and on
GET /api/nba/events/{id}/reads, and the filtered board keeps it only
when that number clears the floor. Out still nulls the blend and still
stays on the board.

Odds shells are the recorded player_points capture. Only description
changes, and only so a recorded injury name is the posted player.
"""

from __future__ import annotations

import asyncio

from app.services.daily_analysis import (
    _with_nba_signal_verdicts,
    select_daily_picks,
)
from app.services.pick_signals import build_nba_signals
from tests.test_spo131_bdl_injuries import INJURY_PAGE
from tests.test_spo135c_bdl_injury_status import (
    _board_for,
    _entry,
    _named,
    _picks_for,
)
from tests.test_spo135e_event_reads_injuries import (
    _Csv,
    _by_player,
    _fresh,
    _install,
    _relabel,
)
from tests.test_spo121_bulk_reads import _points_rows


def _recorded_doubtful_word() -> str:
    """The status word on a recorded Doubtful row. Not a typed label."""
    words = {
        row["status"]
        for row in INJURY_PAGE["data"]
        if isinstance(row, dict) and row.get("status") == "Doubtful"
    }
    assert words == {"Doubtful"}
    return next(iter(words))


def _points(picks, name: str):
    rows = [pick for pick in _named(picks, name) if pick.metric == "points"]
    assert len(rows) == 1
    return rows[0]


def test_raw_doubtful_pick_matches_plain_questionable() -> None:
    """A cache Doubtful row keeps the Questionable blend.

    Both names are on the recorded injury page. The odds capture's
    descriptions are replaced with those names. Prices, books, and the
    market key stay recorded.
    """
    questionable = _entry("Questionable")
    doubtful = _entry("Doubtful")
    picks = _picks_for(
        [questionable["player"], doubtful["player"]],
        [questionable, doubtful],
    )
    plain = _points(picks, questionable["player"])
    raw = _points(picks, doubtful["player"])
    assert raw.injury_status == "Doubtful"
    assert plain.injury_status == "Questionable"
    assert raw.combined_probability is not None
    assert raw.combined_probability == plain.combined_probability
    assert raw.lineup_confirmed is None


def test_filtered_board_keeps_raw_doubtful_only_above_the_floor() -> None:
    """The board uses the blend, the same way it uses a Questionable blend.

    The pick stays when min_probability is that number. It leaves when
    the floor is higher. Questionable does the same.
    """
    questionable = _entry("Questionable")
    doubtful = _entry("Doubtful")
    picks = _picks_for(
        [questionable["player"], doubtful["player"]],
        [questionable, doubtful],
    )
    plain = _points(picks, questionable["player"])
    raw = _points(picks, doubtful["player"])
    blend = raw.combined_probability
    assert blend is not None
    assert plain.combined_probability == blend
    assert raw.n_games >= 10
    kept = select_daily_picks([raw, plain], min_probability=blend, min_games=10)
    assert {pick.player_name for pick in kept} == {
        raw.player_name,
        plain.player_name,
    }
    dropped = select_daily_picks(
        [raw, plain], min_probability=blend + 0.0001, min_games=10
    )
    assert dropped == []


def test_reads_give_raw_doubtful_a_number(monkeypatch) -> None:
    """GET /api/nba/events/{id}/reads returns a number for a cache Doubtful.

    One recorded player_points description is relabeled to the recorded
    Doubtful name. A second call uses that same recorded row with
    ``raw_status`` set to the stored status, so the prices stay put and
    only the source word changes. The two numbers match.
    """
    doubtful = _entry("Doubtful")
    event_id, rows = _points_rows()
    posted = sorted({row["player_name"] for row in rows})
    source = next(name for name in posted if name != "Dyson Daniels")
    rows = _relabel(rows, source, doubtful["player"])
    _install(monkeypatch, rows, injury_body=_fresh([doubtful]))

    from app.services.event_reads import get_event_reads

    payload = asyncio.run(
        get_event_reads(event_id, market="player_points", csv_service=_Csv())
    )
    d_rows = _by_player(payload, doubtful["player"])
    assert all(item.combined_probability is not None for item in d_rows)
    assert all(0.0 < item.combined_probability < 1.0 for item in d_rows)

    plain = dict(doubtful)
    plain["raw_status"] = plain["status"]
    _install(monkeypatch, rows, injury_body=_fresh([plain]))
    again = asyncio.run(
        get_event_reads(event_id, market="player_points", csv_service=_Csv())
    )
    q_rows = _by_player(again, doubtful["player"])
    assert [item.combined_probability for item in d_rows] == [
        item.combined_probability for item in q_rows
    ]


def test_literal_doubtful_word_matches_questionable_on_the_nba_blend() -> None:
    """A status word of Doubtful does not null an NBA blend.

    The word is the one stored on the recorded page. The market
    probability is the helper's explicit input, the same way the
    signal tests pass one.
    """
    word = _recorded_doubtful_word()
    shared = dict(
        side="over",
        line=24.5,
        player_name="Test Player",
        market_probability=0.58,
        history_rate=0.62,
    )
    _signals, doubtful, _total = build_nba_signals(injury_status=word, **shared)
    _signals, plain, _total = build_nba_signals(
        injury_status="Questionable", **shared
    )
    assert doubtful is not None
    assert doubtful == plain


def test_out_still_nulls_the_blend_and_stays_on_the_board() -> None:
    """Out still has a null blend and still remains on the filtered board."""
    out = _entry("Out")
    picks = _picks_for([out["player"]], [out])
    row = _points(picks, out["player"])
    assert row.injury_status == "Out"
    assert row.combined_probability is None
    assert row.lineup_confirmed is None
    assert select_daily_picks([row]) == [row]


def test_reads_still_null_an_out_player(monkeypatch) -> None:
    """GET /api/nba/events/{id}/reads still returns null for Out.

    One recorded description is relabeled to the recorded Out name.
    """
    out = _entry("Out")
    event_id, rows = _points_rows()
    posted = sorted({row["player_name"] for row in rows})
    source = next(name for name in posted if name != "Dyson Daniels")
    rows = _relabel(rows, source, out["player"])
    _install(monkeypatch, rows, injury_body=_fresh([out]))

    from app.services.event_reads import get_event_reads

    payload = asyncio.run(
        get_event_reads(event_id, market="player_points", csv_service=_Csv())
    )
    blocked = _by_player(payload, out["player"])
    assert {item.combined_probability for item in blocked} == {None}
    assert all(item.signals is not None for item in blocked)

