"""SPO-135h: NBA Doubtful keeps the Questionable blend.

The recorded BALLDONTLIE page stores Doubtful as status Questionable
and keeps raw_status Doubtful. That row is the same pick as a plain
Questionable row: a number on daily picks and on
GET /api/nba/events/{id}/reads, and the filtered board keeps it only
when that number clears the floor. Out still nulls the blend and still
stays on the board.

Odds shells are the recorded player_points capture. Only description
changes, and only so a recorded injury name is the posted player.
WNBA does not read this snapshot. A literal Doubtful word, the status
on the recorded page, stays on the WNBA path exactly as this head
already treats it.
"""

from __future__ import annotations

import asyncio

from app.api.wnba import router as wnba_router
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
    """A cache Doubtful row is Questionable and keeps that blend.

    Both names are on the recorded injury page. The odds capture's
    descriptions are replaced with those names. Prices, books, and the
    market key stay recorded.
    """
    questionable = _entry("Questionable")
    doubtful = _entry("Questionable", raw="Doubtful")
    picks = _picks_for(
        [questionable["player"], doubtful["player"]],
        [questionable, doubtful],
    )
    plain = _points(picks, questionable["player"])
    raw = _points(picks, doubtful["player"])
    assert raw.injury_status == "Questionable"
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
    doubtful = _entry("Questionable", raw="Doubtful")
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
    Doubtful name, and another to the recorded Questionable name.
    """
    questionable = _entry("Questionable")
    doubtful = _entry("Questionable", raw="Doubtful")
    event_id, rows = _points_rows()
    posted = sorted({row["player_name"] for row in rows})
    sources = [name for name in posted if name != "Dyson Daniels"]
    assert len(sources) >= 2
    rows = _relabel(rows, sources[0], questionable["player"])
    rows = _relabel(rows, sources[1], doubtful["player"])
    _install(
        monkeypatch,
        rows,
        injury_body=_fresh([questionable, doubtful]),
    )

    from app.services.event_reads import get_event_reads

    payload = asyncio.run(
        get_event_reads(event_id, market="player_points", csv_service=_Csv())
    )
    q_rows = _by_player(payload, questionable["player"])
    d_rows = _by_player(payload, doubtful["player"])
    assert all(item.combined_probability is not None for item in q_rows)
    assert all(0.0 < item.combined_probability < 1.0 for item in q_rows)
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


def test_wnba_literal_doubtful_keeps_todays_blend_board_and_reads() -> None:
    """WNBA still ignores a Doubtful word. These are the current values.

    The odds capture is the recorded player_points body. Only the
    description changes, to the recorded Doubtful player's name. The
    word itself is that page's status. WNBA analysis does not copy it
    onto the pick. The board still uses the historical rate. There is
    still no WNBA reads route.
    """
    word = _recorded_doubtful_word()
    doubtful = _entry("Questionable", raw="Doubtful")
    assert doubtful["raw_status"] == word

    from app.services.daily_analysis import DailyAnalysisService
    import app.services.daily_analysis as daily_analysis
    from tests.test_spo135c_bdl_injury_status import _async_return

    service = DailyAnalysisService()
    service._get_props_for_market = _async_return(_board_for(doubtful["player"]))

    class _WnbaCsv:
        def get_player_stats(self, **_kwargs):
            return {
                "p_over": 0.7,
                "p_under": 0.2,
                "n_games": 20,
                "game_logs": [{"team": "Liberty", "value": 18}],
            }

    original = daily_analysis._resolve_csv_service
    daily_analysis._resolve_csv_service = lambda league: _WnbaCsv()
    try:
        picks, _players, _props = asyncio.run(
            service._analyze_single_event(
                event_id="evt-w",
                home_team="New York Liberty",
                away_team="Connecticut Sun",
                commence_time="2026-06-01T23:00:00Z",
                league="wnba",
                injury_entries=[
                    {
                        "player": doubtful["player"],
                        "status": word,
                        "position": doubtful.get("position") or "",
                        "injury": doubtful.get("injury") or "",
                        "source": "espn",
                    }
                ],
            )
        )
    finally:
        daily_analysis._resolve_csv_service = original

    assert picks
    points = _points(picks, doubtful["player"])
    assert points.injury_status is None
    assert points.combined_probability is None
    assert points.signals is None
    assert points.lineup_confirmed is None
    assert points.probability == 0.7
    assert select_daily_picks([points], league="wnba") == [points]

    labeled = points.model_copy(update={"injury_status": word})
    returned = _with_nba_signal_verdicts(
        labeled,
        league="wnba",
        bookmakers_data=_board_for(doubtful["player"]),
        game_logs=[{"team": "Liberty", "value": 18}],
    )
    assert returned.injury_status == word
    assert returned.combined_probability is None
    assert returned.signals is None
    assert select_daily_picks([returned], league="wnba") == [returned]
    low = returned.model_copy(update={"probability": 0.64})
    assert select_daily_picks([low], league="wnba") == []

    paths = [getattr(route, "path", "") for route in wnba_router.routes]
    assert paths
    assert not any(path.endswith("/reads") for path in paths)
