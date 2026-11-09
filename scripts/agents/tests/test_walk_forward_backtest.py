"""Walk-forward harness: proxy lines, no lookahead, odds hook, production rates."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from evaluation.assumptions import ASSUMPTION_A, ASSUMPTION_B, ASSUMPTION_C
from evaluation.metrics import roi_from_hit_rate, summarize, wilson
from evaluation.odds_history import (
    ASSUMED_AMERICAN_ODDS,
    PropOddsQuote,
    closing_line_value,
    load_odds_history,
    open_close_from_snapshots,
    unit_profit,
)
from evaluation.proxy_lines import proxy_line
from evaluation.walk_forward import replay_league


class _Service:
    """Enough of a CSV service for a daily-only replay. Not the agent singleton."""

    def __init__(self, cache: dict):
        self._cache = cache
        self.league = "nba"
        self._loaded = True


def _game(
    day: int, points: float, *, player: str = "Test Player", team: str = "AAA"
) -> dict:
    return {
        "player_name": player,
        "game_date": datetime(2025, 11, 1) + timedelta(days=day),
        "minutes": 30.0,
        "points": points,
        "rebounds": 5.0,
        "assists": 4.0,
        "pra": points + 9.0,
        "team": team,
        "season": "2025-2026",
    }


def _replay(points: list[float], **kwargs):
    cache = {"Test Player": [_game(day, value) for day, value in enumerate(points)]}
    return replay_league(
        _Service(cache),
        "nba",
        kwargs.pop("proxies", ["L10"]),
        eval_start=datetime(2025, 11, 1),
        markets=[("player_points", "points")],
        threshold=0.65,
        min_games=10,
        do_agent=False,
        validate=0,
        **kwargs,
    )


def test_med20_tie_goes_to_the_lower_line():
    # Both 1.5 and 2.5 split [1, 1, 3, 3] at 50/50. The lower line wins.
    assert proxy_line([1, 1, 3, 3], "MED20") == 1.5


def test_l10_is_floor_of_the_mean_plus_half():
    values = [12, 10, 10, 10, 10, 10, 10, 10, 10, 10]
    assert proxy_line(values, "L10") == 10.5


def test_proxy_line_empty_window_is_none():
    assert proxy_line([], "L10") is None
    assert proxy_line([], "MED20") is None


def test_unknown_proxy_raises():
    with pytest.raises(ValueError):
        proxy_line([1.0], "NOPE")


def test_walk_forward_does_not_see_the_future_or_the_target():
    # Twelve 10-point games, then a 10, then a 100. The 100 must not move
    # the line or the probability of any earlier game, and it must not
    # enter its own history either.
    points = [10.0] * 12 + [10.0, 100.0]
    replay = _replay(points)
    by_date = {}
    for row in replay.daily:
        by_date.setdefault(row.date, row)
    earlier = by_date[(datetime(2025, 11, 1) + timedelta(days=12)).strftime("%Y-%m-%d")]
    spike = by_date[(datetime(2025, 11, 1) + timedelta(days=13)).strftime("%Y-%m-%d")]
    assert earlier.line == 10.5
    assert earlier.p_over == 0.0
    assert earlier.p_under == 1.0
    assert earlier.pick == "under"
    assert earlier.hit == 1
    assert spike.p_over == 0.0
    assert spike.over_hit == 1
    assert spike.line_source == "proxy"
    assert spike.price is None


def test_duplicate_player_date_is_not_scored_twice():
    games = [_game(day, 10.0) for day in range(12)]
    extra = _game(11, 80.0)
    # Same calendar day as the last real game, different stat. It is not a
    # second target, and it is not prior for that date.
    cache = {"Test Player": games + [extra]}
    replay = replay_league(
        _Service(cache),
        "nba",
        ["L10"],
        eval_start=datetime(2025, 11, 1),
        markets=[("player_points", "points")],
        threshold=0.65,
        min_games=10,
        do_agent=False,
        validate=0,
    )
    last_date = games[-1]["game_date"].strftime("%Y-%m-%d")
    rows = [row for row in replay.daily if row.date == last_date]
    assert len(rows) == 1
    assert rows[0].actual == 10.0


def test_opening_line_replaces_the_proxy_and_prices_the_bet():
    points = [10.0] * 14
    target = (datetime(2025, 11, 1) + timedelta(days=12)).strftime("%Y-%m-%d")
    quote = PropOddsQuote(
        league="nba",
        player="Test Player",
        game_date=target,
        market="points",
        open_line=2.5,
        open_over_price=-150,
        open_under_price=130,
        close_line=4.5,
        close_over_price=-180,
        close_under_price=150,
        book="draftkings",
    )
    from evaluation.odds_history import OddsHistory, player_key

    history = OddsHistory(
        quotes={
            (
                quote.league,
                player_key(quote.player),
                quote.game_date,
                quote.market,
            ): quote
        },
        source="test",
    )
    replay = _replay(points, odds=history)
    matched = [row for row in replay.daily if row.date == target]
    other = [row for row in replay.daily if row.date != target]
    assert len(matched) == 1
    assert matched[0].line == 2.5
    assert matched[0].line_source == "open"
    assert matched[0].pick == "over"
    assert matched[0].price == -150
    assert matched[0].clv_prob is not None
    assert matched[0].clv_line == pytest.approx(2.0)
    assert other
    assert all(row.line_source == "proxy" and row.price is None for row in other)


def test_wilson_interval_contains_the_rate_and_matches_a_known_case():
    low, high = wilson(81, 100)
    assert low < 0.81 < high
    assert low == pytest.approx(0.7222, abs=1e-3)
    assert high == pytest.approx(0.8748, abs=1e-3)
    assert all(math.isnan(value) for value in wilson(0, 0))


def test_roi_at_minus_110_matches_unit_profit():
    assert unit_profit(ASSUMED_AMERICAN_ODDS, True) == pytest.approx(100 / 110)
    assert unit_profit(ASSUMED_AMERICAN_ODDS, False) == -1
    assert unit_profit(-150, True) == pytest.approx(100 / 150)
    assert unit_profit(130, True) == pytest.approx(1.30)
    # 60 wins and 40 losses.
    hit_rate = 0.6
    roi = roi_from_hit_rate(hit_rate)
    manual = (60 * (100 / 110) - 40) / 100
    assert roi == pytest.approx(manual)


def test_summary_uses_real_price_when_a_row_carries_one():
    class Row:
        def __init__(self, hit, price):
            self.over_hit = 1
            self.actual = 11
            self.line = 10.5
            self.p_over = 0.7
            self.pick = "over"
            self.hit = hit
            self.prob = 0.7
            self.price = price
            self.clv_prob = 0.02 if price else None
            self.clv_line = 1.0 if price else None

    summary = summarize([Row(1, -150), Row(0, -150)])
    assert summary.priced_picks == 2
    assert summary.roi == pytest.approx((100 / 150 - 1) / 2)
    assert summary.clv_n == 2
    assert summary.roi_method == "normal"


def test_inactive_odds_hook_and_missing_file(tmp_path):
    assert load_odds_history(None).active is False
    empty = tmp_path / "empty.csv"
    empty.write_text(
        "league,player,game_date,market,open_line,open_over_price,open_under_price,close_line,close_over_price,close_under_price\n",
        encoding="utf-8",
    )
    assert load_odds_history(str(empty)).active is False
    with pytest.raises(FileNotFoundError):
        load_odds_history(str(tmp_path / "missing.csv"))


def test_csv_loader_and_snapshot_reducer_and_clv(tmp_path):
    path = tmp_path / "odds.csv"
    path.write_text(
        "league,player,game_date,market,open_line,open_over_price,open_under_price,"
        "close_line,close_over_price,close_under_price,book\n"
        "nba,Stephen Curry,2026-01-15,player_points,24.5,-110,-110,26.5,-150,130,draftkings\n"
        "nba,Stephen Curry,2026-01-15,player_points,99.5,-110,-110,99.5,-110,-110,draftkings\n"
        "nba,Bad Row,2026-01-15,points,10.5,0,-110,10.5,0,-110,\n",
        encoding="utf-8",
    )
    history = load_odds_history(str(path))
    assert history.active
    assert history.skipped_rows == 1
    assert history.duplicate_keys == 1
    quote = history.lookup("NBA", "stephen curry", "2026-01-15", "points")
    assert quote is not None
    assert quote.open_line == 99.5  # last valid row wins
    assert quote.market == "points"

    fresh = PropOddsQuote(
        league="nba",
        player="Stephen Curry",
        game_date="2026-01-15",
        market="points",
        open_line=24.5,
        open_over_price=-110,
        open_under_price=-110,
        close_line=26.5,
        close_over_price=-150,
        close_under_price=130,
    )
    clv_prob, clv_line = closing_line_value(fresh, "over")
    # Open is a symmetric -110/-110, so the vig-free probability is 0.5.
    # Close -150 / +130 is not symmetric.
    from app.services.prob import american_to_prob, devig

    fair_over, _fair_under = devig(american_to_prob(-150), american_to_prob(130))
    assert clv_prob == pytest.approx(fair_over - 0.5)
    assert clv_line == pytest.approx(2.0)
    under_prob, under_line = closing_line_value(fresh, "under")
    assert under_line == pytest.approx(-2.0)
    assert under_prob == pytest.approx(-clv_prob)

    snapshots = open_close_from_snapshots(
        [
            {
                "player_name": "Stephen Curry",
                "date": "2026-01-15",
                "market": "player_points",
                "line": 24.5,
                "over_odds": -110,
                "under_odds": -110,
                "snapshot_at": "2026-01-15T12:00:00Z",
                "bookmaker": "fanduel",
            },
            {
                "player_name": "Stephen Curry",
                "date": "2026-01-15",
                "market": "player_points",
                "line": 26.5,
                "over_odds": -150,
                "under_odds": 130,
                "snapshot_at": "2026-01-15T23:00:00Z",
                "bookmaker": "fanduel",
            },
            {
                "player_name": "Stephen Curry",
                "date": "2026-01-15",
                "market": "player_points",
                "line": 1.5,
                "over_odds": -110,
                "under_odds": -110,
                "snapshot_at": "2026-01-15T10:00:00Z",
                "bookmaker": "caesars",
            },
        ]
    )
    # Alphabetical bookmaker wins: caesars before fanduel, so the only
    # caesars snapshot is both the open and the close.
    reduced = snapshots.lookup("nba", "Stephen Curry", "2026-01-15", "points")
    assert reduced is not None
    assert reduced.book == "caesars"
    assert reduced.open_line == 1.5
    assert reduced.close_line == 1.5


def test_report_states_the_three_assumptions_when_no_odds_are_loaded():
    from evaluation.odds_history import inactive_history
    from evaluation.report import render_report
    from evaluation.walk_forward import LeagueReplay

    empty = {
        "rows": 0,
        "players": 0,
        "date_start": None,
        "date_end": None,
        "seasons": {},
        "duplicates": [],
        "multi_team_players": 0,
        "rows_before_nba_cutoff": 0,
        "before_cutoff_by_month": {},
    }
    text = render_report(
        {
            "nba": LeagueReplay(league="nba", exposure={}),
            "wnba": LeagueReplay(league="wnba", exposure={}),
        },
        {"nba": empty, "wnba": empty},
        inactive_history(),
        command="python scripts/agents/evaluation/backtest.py --report backtest_report.md",
        oracle_note="not run",
        guard_note="not run",
        elapsed_s=0,
    )
    assert ASSUMPTION_A in text
    assert ASSUMPTION_B in text
    assert ASSUMPTION_C in text
    assert "CLV hook is inactive" in text
    assert "SPO-97" in text and "SPO-98" in text


def test_production_decision_thresholds_match_the_shared_functions():
    from app.services.daily_analysis import (
        HIGH_PROBABILITY_THRESHOLD,
        choose_daily_pick_side,
    )
    from scoring import (
        OVER_DECISION_THRESHOLD,
        UNDER_DECISION_THRESHOLD,
        decision_from_over_probability,
    )

    assert HIGH_PROBABILITY_THRESHOLD == 0.65
    assert choose_daily_pick_side(0.65, 0.70) == ("over", 0.65)
    assert choose_daily_pick_side(0.64, 0.80) == ("under", 0.80)
    assert choose_daily_pick_side(0.64, 0.64) == (None, None)
    assert OVER_DECISION_THRESHOLD == 0.55
    assert UNDER_DECISION_THRESHOLD == 0.45
    assert decision_from_over_probability(0.55) == "over"
    assert decision_from_over_probability(0.45) == "under"
    assert decision_from_over_probability(0.50) == "avoid"


def test_real_get_player_stats_agrees_and_agent_gate_is_avoid():
    """A few real players: daily rates match get_player_stats, agent rows are gated."""
    from evaluation.walk_forward import load_historical, select_players

    historical = load_historical()
    service = historical._csv_for("nba")
    chosen = select_players(list(service._cache), 4, seed=7)
    replay = replay_league(
        service,
        "nba",
        ["MED20", "L10"],
        players=chosen,
        do_agent=True,
        validate=40,
        seed=7,
    )
    assert replay.validation["checked"] > 0
    assert replay.validation["mismatches"] == 0
    assert replay.agent
    assert all(row.prod_decision == "avoid" for row in replay.agent)
    assert all(row.pass_reason == "no market price available" for row in replay.agent)
    assert all(row.eligible is False for row in replay.agent)
    assert any(row.pick in ("over", "under") for row in replay.agent)
