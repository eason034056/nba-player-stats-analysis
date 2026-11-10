"""Walk-forward harness: proxy lines, no lookahead, odds hook, production rates."""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from evaluation.assumptions import ASSUMPTION_A, ASSUMPTION_B, ASSUMPTION_C
from evaluation.metrics import roi_from_hit_rate, summarize, wilson
from evaluation.odds_history import (
    ASSUMED_AMERICAN_ODDS,
    closing_line_value,
    load_odds_history,
    open_close_from_snapshots,
    unit_profit,
)
from evaluation.proxy_lines import proxy_line
from evaluation.walk_forward import replay_league

# Recorded Odds API bodies. The first 500 bytes of each response, copied from
# the research notes. Tests parse these files. They do not type prices.
WNBA_POINTS_CAPTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "odds_api_wnba_player_points_head500.json"
)
NBA_THREES_CAPTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "odds_api_nba_player_threes_head500.json"
)


def _recorded_pair(path: Path) -> dict[str, object]:
    """First complete Over/Under pair in a truncated Odds API body."""
    text = path.read_text(encoding="utf-8")
    assert len(text.encode()) == 500
    sport = re.search(r'"sport_key":"([^"]+)"', text)
    commence = re.search(r'"commence_time":"([^"]+)"', text)
    pair = re.search(
        r'"key":"(?P<book>[^"]+)","title":"[^"]+","markets":\[\{"key":"(?P<market>[^"]+)",'
        r'"last_update":"(?P<updated>[^"]+)","outcomes":\['
        r'\{"name":"Over","description":"(?P<player>[^"]+)","price":(?P<over>-?\d+),"point":(?P<line>\d+(?:\.\d+)?)\}'
        r',\{"name":"Under","description":"(?P<player_under>[^"]+)","price":(?P<under>-?\d+),"point":(?P<line_under>\d+(?:\.\d+)?)\}',
        text,
    )
    assert sport and commence and pair
    assert pair.group("player") == pair.group("player_under")
    assert pair.group("line") == pair.group("line_under")
    league = "wnba" if sport.group(1).endswith("wnba") else "nba"
    return {
        "league": league,
        "player": pair.group("player"),
        "game_date": commence.group(1)[:10],
        "market": pair.group("market"),
        "line": float(pair.group("line")),
        "over": int(pair.group("over")),
        "under": int(pair.group("under")),
        "book": pair.group("book"),
        "snapshot_at": pair.group("updated"),
    }


def _quote_csv_row(captured: dict[str, object], *, over: int | None = None) -> str:
    """One open/close row. Open and close are the same captured quote."""
    over_price = captured["over"] if over is None else over
    return (
        f"{captured['league']},{captured['player']},{captured['game_date']},{captured['market']},"
        f"{captured['line']},{over_price},{captured['under']},"
        f"{captured['line']},{over_price},{captured['under']},{captured['book']}"
    )


def _snapshot(captured: dict[str, object]) -> dict[str, object]:
    return {
        "player_name": captured["player"],
        "date": captured["game_date"],
        "market": captured["market"],
        "line": captured["line"],
        "over_odds": captured["over"],
        "under_odds": captured["under"],
        "snapshot_at": captured["snapshot_at"],
        "bookmaker": captured["book"],
        "league": captured["league"],
    }


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


def test_identical_same_day_row_is_kept_once_in_a_later_prior():
    games = [_game(day, 10.0) for day in range(12)]
    duplicate = _game(11, 10.0)
    later = _game(12, 12.0)
    replay = replay_league(
        _Service({"Test Player": games + [duplicate, later]}),
        "nba",
        ["L10"],
        eval_start=datetime(2025, 11, 1),
        markets=[("player_points", "points")],
        threshold=0.65,
        min_games=10,
        do_agent=False,
        validate=0,
    )
    later_date = later["game_date"].strftime("%Y-%m-%d")
    row = next(item for item in replay.daily if item.date == later_date)
    # 12 distinct games. The second copy of day 11 is the same box score.
    assert row.n_games == 12
    assert row.actual == 12.0


def test_opening_line_replaces_the_proxy_and_prices_the_bet(tmp_path):
    captured = _recorded_pair(WNBA_POINTS_CAPTURE)
    target = datetime.strptime(str(captured["game_date"]), "%Y-%m-%d")
    player = str(captured["player"])
    # Every prior total is below the captured line, so the priced side is under.
    logs = []
    for offset in range(14):
        game = _game(offset, 10.0, player=player)
        game["game_date"] = target - timedelta(days=13 - offset)
        logs.append(game)
    path = tmp_path / "open_close.csv"
    path.write_text(
        "league,player,game_date,market,open_line,open_over_price,open_under_price,"
        "close_line,close_over_price,close_under_price,book\n" + _quote_csv_row(captured) + "\n",
        encoding="utf-8",
    )
    history = load_odds_history(str(path))
    replay = replay_league(
        _Service({player: logs}),
        str(captured["league"]),
        ["L10"],
        eval_start=target - timedelta(days=30),
        markets=[("player_points", "points")],
        threshold=0.65,
        min_games=10,
        do_agent=False,
        validate=0,
        odds=history,
    )
    matched = [row for row in replay.daily if row.date == captured["game_date"]]
    other = [row for row in replay.daily if row.date != captured["game_date"]]
    assert len(matched) == 1
    assert matched[0].line == captured["line"]
    assert matched[0].line_source == "open"
    assert matched[0].pick == "under"
    assert matched[0].price == captured["under"]
    # The capture is one snapshot, so open and close are that quote. CLV is 0.
    assert matched[0].clv_prob == pytest.approx(0.0)
    assert matched[0].clv_line == pytest.approx(0.0)
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
    assert unit_profit(ASSUMED_AMERICAN_ODDS, None) == 0.0
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
    captured = _recorded_pair(WNBA_POINTS_CAPTURE)
    other = _recorded_pair(NBA_THREES_CAPTURE)
    path = tmp_path / "odds.csv"
    header = (
        "league,player,game_date,market,open_line,open_over_price,open_under_price,"
        "close_line,close_over_price,close_under_price,book\n"
    )
    # The captured row twice, then the same row with a zero price so the loader
    # skips it. The zero is not a quoted price.
    path.write_text(
        header
        + _quote_csv_row(captured)
        + "\n"
        + _quote_csv_row(captured)
        + "\n"
        + _quote_csv_row(captured, over=0)
        + "\n",
        encoding="utf-8",
    )
    history = load_odds_history(str(path))
    assert history.active
    assert history.skipped_rows == 1
    assert history.duplicate_keys == 1
    quote = history.lookup(
        str(captured["league"]),
        str(captured["player"]),
        str(captured["game_date"]),
        "points",
    )
    assert quote is not None
    assert quote.open_line == captured["line"]
    assert quote.open_over_price == captured["over"]
    assert quote.open_under_price == captured["under"]
    assert quote.market == "points"
    assert quote.book == captured["book"]

    # One captured snapshot is both the open and the close, so both CLVs are 0.
    # A line move at a constant price would still have line CLV, but this body
    # has no second timestamp to take that move from.
    clv_prob, clv_line = closing_line_value(quote, "over")
    assert clv_prob == pytest.approx(0.0)
    assert clv_line == pytest.approx(0.0)
    under_prob, under_line = closing_line_value(quote, "under")
    assert under_prob == pytest.approx(0.0)
    assert under_line == pytest.approx(0.0)

    reduced = open_close_from_snapshots([_snapshot(captured), _snapshot(other)])
    kept = reduced.lookup(
        str(captured["league"]),
        str(captured["player"]),
        str(captured["game_date"]),
        "points",
    )
    assert kept is not None
    assert kept.book == captured["book"]
    assert kept.open_line == captured["line"]
    assert kept.close_line == captured["line"]
    assert kept.open_over_price == captured["over"]
    threes = reduced.lookup(
        str(other["league"]),
        str(other["player"]),
        str(other["game_date"]),
        "threes_made",
    )
    assert threes is not None
    assert threes.book == other["book"]
    assert threes.open_line == other["line"]


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
