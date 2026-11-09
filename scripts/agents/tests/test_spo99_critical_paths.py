"""Critical-path checks for the SPO-99 walk-forward harness.

These tests do not change production code. They pin:

* leakage: a target is scored only from games dated strictly before it
* MED20 / L10 / L5 / ALL proxy lines, including ties and the x.5 step
* Wilson intervals, Brier, calibration gap, and ROI at -110
* calibration-guard thresholds, including the equality boundary
* the odds-history hook, inactive without a file and CLV from a real capture
* Daily Picks and scorecard decisions against the predicates that were
  inlined on origin/dev, including the sample floor and the 0.55 / 0.45 edges
* one shared replay for NBA and WNBA
"""

from __future__ import annotations

import math
import random
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from evaluation.calibration_guard import Thresholds, evaluate_guard
from evaluation.metrics import Summary, roi_from_hit_rate, summarize, wilson
from evaluation.odds_history import (
    ASSUMED_AMERICAN_ODDS,
    closing_line_value,
    load_odds_history,
    open_close_from_snapshots,
    unit_profit,
)
from evaluation.paths import bootstrap
from evaluation.proxy_lines import proxy_line
from evaluation.walk_forward import EVAL_START, replay_league

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "odds_api_wnba_player_points_head500.json"
)

# The predicate that lived inline in daily_analysis before choose_daily_pick_side.
# OVER is checked first, so a player who clears both sides is an over.
def _dev_daily_side(p_over, p_under, threshold=0.65):
    if p_over is not None and p_over >= threshold:
        return "over", round(p_over, 4)
    if p_under is not None and p_under >= threshold:
        return "under", round(p_under, 4)
    return None, None


# The predicate that lived inline in scoring.compute_scorecard before
# decision_from_over_probability. The comparison is on the unrounded P(over).
def _dev_scorecard_side(p_over: float) -> str:
    if p_over >= 0.55:
        return "over"
    if p_over <= 0.45:
        return "under"
    return "avoid"


class _Service:
    """Cache stand-in. replay_league only reads _cache on the daily path."""

    def __init__(self, cache: dict):
        self._cache = cache
        self.league = "nba"
        self._loaded = True


class _Row:
    """One prop, shaped the way Accumulator.add reads it."""

    def __init__(self, prob: float, hit: int, *, price=None, p_over=None, over_hit=None):
        self.over_hit = hit if over_hit is None else over_hit
        self.actual = 11.0 if self.over_hit else 0.0
        self.line = 10.5
        self.p_over = prob if p_over is None else p_over
        self.pick = "over"
        self.hit = hit
        self.prob = prob
        self.price = price
        self.clv_prob = None
        self.clv_line = None


def _game(
    when: datetime,
    points: float,
    *,
    player: str = "Test Player",
    team: str = "AAA",
    minutes: float = 30.0,
) -> dict:
    return {
        "player_name": player,
        "game_date": when,
        "minutes": minutes,
        "points": points,
        "rebounds": 5.0,
        "assists": 4.0,
        "pra": points + 9.0,
        "team": team,
        "season": "2025-2026",
    }


def _replay(cache: dict, league: str = "nba", **kwargs):
    proxies = kwargs.pop("proxies", ["L10", "L5", "ALL", "MED20"])
    return replay_league(
        _Service(cache),
        league,
        proxies,
        eval_start=kwargs.pop("eval_start", datetime(2025, 11, 1)),
        markets=kwargs.pop("markets", [("player_points", "points")]),
        threshold=kwargs.pop("threshold", 0.65),
        min_games=kwargs.pop("min_games", 10),
        do_agent=False,
        validate=0,
        **kwargs,
    )


def _by_date(replay, proxy: str = "L10") -> dict[str, object]:
    found = {}
    for row in replay.daily:
        if row.proxy == proxy:
            found[row.date] = row
    return found


# ---------------------------------------------------------------------------
# Leakage
# ---------------------------------------------------------------------------


def test_unsorted_future_game_does_not_change_an_earlier_line():
    """A 100-point game dated after the target stays out of the prior.

    The cache lists that future game first, and the real history is newest
    first, so a replay that forgot to sort would treat 100 as the recent
    window.
    """
    start = datetime(2025, 11, 1)
    history = [_game(start + timedelta(days=offset), 10.0) for offset in range(13)]
    future = _game(start + timedelta(days=30), 100.0)
    cache = {"Test Player": [future, *reversed(history)]}
    replay = _replay(cache, proxies=["L10", "MED20"])
    target = (start + timedelta(days=12)).strftime("%Y-%m-%d")
    row = _by_date(replay, "L10")[target]
    assert row.line == 10.5
    assert row.p_over == 0.0
    assert row.p_under == 1.0
    assert row.n_games == 12
    assert row.actual == 10.0
    med = _by_date(replay, "MED20")[target]
    assert med.line == 9.5
    assert med.pick == "over"
    assert all(other.date < future["game_date"].strftime("%Y-%m-%d") or other.date == future["game_date"].strftime("%Y-%m-%d") for other in replay.daily)
    future_rows = [other for other in replay.daily if other.date == "2025-12-01"]
    assert future_rows
    assert all(other.line != 100.5 for other in future_rows)


def test_same_day_doubleheader_is_not_prior_for_that_date():
    """Two games on one date. The scored row's prior stops at the day before.

    Input order is shuffled. The same-day sibling has a different team and
    a different total, which is the trade-day / doubleheader shape. Whichever
    copy the stable date sort scores, the other copy is not in that prior.
    """
    start = datetime(2025, 11, 1)
    earlier = [_game(start + timedelta(days=offset), 10.0, team="OLD") for offset in range(12)]
    day = start + timedelta(days=12)
    first = _game(day, 10.0, team="OLD")
    second = _game(day, 50.0, team="NEW")
    later = _game(start + timedelta(days=13), 12.0, team="NEW")
    logs = [later, second, *earlier, first]
    random.Random(99).shuffle(logs)
    replay = _replay({"Test Player": logs}, proxies=["L10", "ALL"])
    scored = _by_date(replay, "L10")[day.strftime("%Y-%m-%d")]
    assert scored.n_games == 12
    assert scored.line == 10.5
    assert scored.p_over == 0.0
    assert scored.actual in (10.0, 50.0)
    # The sibling is a different team. It still does not enter this prior.
    assert scored.p_under == 1.0
    nxt = _by_date(replay, "ALL")[(start + timedelta(days=13)).strftime("%Y-%m-%d")]
    # Both same-day rows are strictly before the next day, so both are in
    # that later sample. 12 tens, plus 10, plus 50.
    assert nxt.n_games == 14
    assert nxt.actual == 12.0


def test_dnp_and_same_day_zero_minutes_stay_out_of_the_window():
    start = datetime(2025, 11, 1)
    played = [_game(start + timedelta(days=offset), 8.0) for offset in range(11)]
    dnp = _game(start + timedelta(days=5), 40.0, minutes=0.0)
    same_day_dnp = _game(played[-1]["game_date"], 80.0, minutes=0.0, team="NEW")
    replay = _replay({"Test Player": [same_day_dnp, dnp, *played]}, proxies=["L10"])
    row = _by_date(replay)[played[-1]["game_date"].strftime("%Y-%m-%d")]
    assert row.actual == 8.0
    assert row.n_games == 10
    assert row.line == 8.5


def test_fewer_than_min_sample_games_is_not_a_target():
    from app.services.daily_analysis import MIN_SAMPLE_GAMES

    start = datetime(2025, 11, 1)
    short = [_game(start + timedelta(days=offset), 20.0) for offset in range(MIN_SAMPLE_GAMES)]
    long = [_game(start + timedelta(days=offset), 20.0) for offset in range(MIN_SAMPLE_GAMES + 1)]
    assert _replay({"Test Player": short}).daily == []
    rows = _replay({"Test Player": long}, proxies=["L10"]).daily
    assert len(rows) == 1
    assert rows[0].n_games == MIN_SAMPLE_GAMES


def test_real_csv_rows_use_only_strictly_earlier_games():
    """One real player per league. The ALL line is the mean of earlier games only."""
    from evaluation.walk_forward import load_historical

    historical = load_historical()
    for league in ("nba", "wnba"):
        service = historical._csv_for(league)
        chosen = None
        active = []
        for name in sorted(service._cache):
            games = [
                game
                for game in service._cache[name]
                if game.get("game_date") and (game.get("minutes") or 0) > 0
            ]
            if len(games) >= 15 and all(game.get("points") is not None for game in games):
                chosen = name
                active = games
                break
        assert chosen is not None
        replay = replay_league(
            service,
            league,
            ["ALL"],
            players={chosen},
            markets=[("player_points", "points")],
            do_agent=False,
            validate=0,
        )
        assert replay.daily
        assert {row.league for row in replay.daily} == {league}
        for row in replay.daily:
            target = datetime.strptime(row.date, "%Y-%m-%d")
            earlier = [
                float(game["points"])
                for game in active
                if game["game_date"] < target
            ]
            assert row.n_games == len(earlier)
            assert earlier
            assert row.line == math.floor(sum(earlier) / len(earlier)) + 0.5
            assert target >= EVAL_START[league]


# ---------------------------------------------------------------------------
# Proxy lines
# ---------------------------------------------------------------------------


def test_proxy_kinds_round_to_a_half_point_and_break_ties_low():
    # [1, 1, 3, 3] is 50/50 at both 1.5 and 2.5. The lower line wins.
    assert proxy_line([1, 1, 3, 3], "MED20") == 1.5
    # A constant integer has the same distance to the line below and the
    # line above. MED20 takes the lower line, so every prior game is an over.
    assert proxy_line([15, 15, 15, 15], "MED20") == 14.5
    assert proxy_line([], "MED20") is None
    assert proxy_line([0, 0, -3], "MED20") == 0.5

    newest_first = [20, 20, 20, 20, 20, 0, 0, 0, 0, 0]
    assert proxy_line(newest_first, "L5") == 20.5
    assert proxy_line(newest_first, "L10") == 10.5
    assert proxy_line(newest_first, "ALL") == 10.5
    # floor(mean) + 0.5. An exact integer mean still steps up to the next x.5,
    # and a mean just below the next integer stays on the lower x.5.
    assert proxy_line([10, 10, 10, 10, 10], "L5") == 10.5
    assert proxy_line([11, 11, 11, 11, 11], "L5") == 11.5
    assert proxy_line([10, 10, 10, 10, 14.995], "L5") == 10.5
    with pytest.raises(ValueError):
        proxy_line([1.0], "NOPE")


def test_constant_player_is_an_over_at_med20_and_an_under_at_l10():
    """The two proxies grade the same next game on opposite sides.

    MED20's tie goes to the lower x.5, so a player who always scores 10 is
    over 9.5. L10 is floor(10) + 0.5 = 10.5, so the same player is under.
    Both next games "hit". That hit is the proxy, not a market.
    """
    start = datetime(2025, 11, 1)
    logs = [_game(start + timedelta(days=offset), 10.0) for offset in range(21)]
    replay = _replay({"Test Player": logs}, proxies=["MED20", "L10"])
    last = (start + timedelta(days=20)).strftime("%Y-%m-%d")
    med = _by_date(replay, "MED20")[last]
    recent = _by_date(replay, "L10")[last]
    assert med.line == 9.5
    assert med.pick == "over"
    assert med.hit == 1
    assert recent.line == 10.5
    assert recent.pick == "under"
    assert recent.hit == 1


# ---------------------------------------------------------------------------
# Wilson, Brier, calibration gap, ROI at -110
# ---------------------------------------------------------------------------


def test_wilson_matches_the_textbook_interval():
    low, high = wilson(81, 100)
    assert low == pytest.approx(0.7222097592919214)
    assert high == pytest.approx(0.8748534600729574)
    assert wilson(0, 100) == pytest.approx((0.0, 0.03699480747600191))
    one_low, one_high = wilson(1, 1)
    assert one_low == pytest.approx(0.20654329147389294)
    assert one_high == 1.0
    assert all(math.isnan(value) for value in wilson(0, 0))


def test_minus_110_breakeven_is_52_38_percent_and_a_win_pays_100_over_110():
    assert ASSUMED_AMERICAN_ODDS == -110
    assert unit_profit(-110, True) == pytest.approx(100 / 110)
    assert unit_profit(-110, False) == -1.0
    breakeven = 110 / 210
    assert round(100 * breakeven, 2) == 52.38
    assert roi_from_hit_rate(breakeven) == pytest.approx(0.0)
    # 11 wins and 10 losses is exactly 110/210. Profit is 11 * (100/110) - 10 = 0.
    rows = [_Row(0.6, 1) for _ in range(11)] + [_Row(0.6, 0) for _ in range(10)]
    summary = summarize(rows)
    assert summary.roi == pytest.approx(0.0)
    assert summary.roi_method == "wilson"
    assert summary.priced_picks == 0
    manual = (11 * (100 / 110) - 10) / 21
    assert summary.roi == pytest.approx(manual)


def test_brier_and_calibration_gap_are_the_pick_mean_squared_error():
    rows = [_Row(0.8, 1), _Row(0.8, 0), _Row(0.8, 0)]
    summary = summarize(rows)
    assert summary.brier == pytest.approx((0.04 + 0.64 + 0.64) / 3)
    assert summary.avg_pred == pytest.approx(0.8)
    assert summary.hit_rate == pytest.approx(1 / 3)
    assert summary.calibration_gap == pytest.approx(abs(0.8 - 1 / 3))
    assert summary.p_over_brier == summary.brier


def test_push_at_the_line_is_graded_as_a_loss():
    """actual == line is neither an over nor an under, so the bet loses 1 unit.

    A real -110 book returns the stake on a push. unit_profit only sees the
    boolean the replay already decided, and that boolean is false on a tie.
    """
    start = datetime(2025, 11, 1)
    # Eleven 10s, then a target of 10.5 so it lands on the L10 line 10.5.
    logs = [_game(start + timedelta(days=offset), 10.0) for offset in range(11)]
    logs.append(_game(start + timedelta(days=11), 10.5))
    row = _replay({"Test Player": logs}, proxies=["L10"]).daily[-1]
    assert row.line == 10.5
    assert row.actual == 10.5
    assert row.pick == "under"
    assert row.hit == 0
    assert unit_profit(ASSUMED_AMERICAN_ODDS, bool(row.hit)) == -1.0


# ---------------------------------------------------------------------------
# Guard thresholds
# ---------------------------------------------------------------------------


def _summary(**overrides) -> Summary:
    fields = dict(
        props=100,
        picks=40,
        hits=20,
        hit_rate=0.5,
        hit_lo=0.3,
        hit_hi=0.7,
        roi=0.0,
        roi_lo=0.0,
        roi_hi=0.0,
        roi_method="wilson",
        avg_pred=0.5,
        naive=0.5,
        lift=0.0,
        brier=0.20,
        brier_lo=0.1,
        brier_hi=0.3,
        p_over_brier=0.20,
        actual_over_rate=0.5,
        mean_p_over=0.5,
        base_rate_brier=0.25,
        clv_prob=None,
        clv_line=None,
        clv_n=0,
        priced_picks=0,
    )
    fields.update(overrides)
    return Summary(**fields)


def test_guard_fails_only_when_a_stat_is_strictly_above_the_threshold():
    bounds = Thresholds(max_brier=0.30, max_calibration_gap=0.15)
    # The same literal on both sides compares equal, so Brier == 0.30 passes.
    brier_equal = _summary(brier=0.30, avg_pred=0.50, hit_rate=0.50)
    assert brier_equal.calibration_gap == 0.0
    assert evaluate_guard([("nba", brier_equal)], bounds).ok is True

    inside = _summary(brier=0.20, avg_pred=0.64, hit_rate=0.50)
    assert inside.calibration_gap == pytest.approx(0.14)
    assert evaluate_guard([("nba", inside)], bounds).ok is True

    brier_over = _summary(brier=0.30 + 1e-9, avg_pred=0.5, hit_rate=0.5)
    brier_result = evaluate_guard([("nba", brier_over)], bounds)
    assert brier_result.ok is False
    assert any("Brier" in item for item in brier_result.failures)
    assert not any("calibration gap" in item for item in brier_result.failures)

    gap_over = _summary(brier=0.20, avg_pred=0.66, hit_rate=0.50)
    gap_result = evaluate_guard([("wnba", gap_over)], bounds)
    assert gap_result.ok is False
    assert any("calibration gap" in item for item in gap_result.failures)
    assert not any("Brier" in item for item in gap_result.failures)


@pytest.mark.xfail(
    reason=(
        "evaluate_guard treats a gap as a failure only when it is strictly "
        "greater than the threshold (gap <= max). abs(0.65 - 0.50) is "
        "0.15000000000000002, which is greater than the literal 0.15, so a "
        "calibration gap of 0.15 fails and the message prints '0.150 > 0.150'."
    )
)
def test_calibration_gap_equal_to_the_threshold_passes():
    bounds = Thresholds(max_brier=0.30, max_calibration_gap=0.15)
    on_the_line = _summary(brier=0.20, avg_pred=0.65, hit_rate=0.50)
    assert on_the_line.calibration_gap == pytest.approx(0.15)
    result = evaluate_guard([("nba", on_the_line)], bounds)
    assert result.ok is True


def test_guard_with_fewer_than_30_picks_watches_every_prop_instead():
    bounds = Thresholds(max_brier=0.30, max_calibration_gap=0.15)
    # The pick rule is badly wrong, but there are only 29 picks and p_over
    # on the whole prop set is calibrated. The guard uses the prop fallback.
    hidden = _summary(picks=29, brier=0.90, avg_pred=0.95, hit_rate=0.10)
    assert evaluate_guard([("nba", hidden)], bounds).ok is True
    watched = _summary(picks=30, brier=0.90, avg_pred=0.95, hit_rate=0.10)
    assert evaluate_guard([("nba", watched)], bounds).ok is False

    empty = evaluate_guard([], bounds)
    assert empty.ok is False
    assert empty.failures == ["no leagues to check"]
    no_props = evaluate_guard([("wnba", _summary(props=0, picks=0))], bounds)
    assert no_props.ok is False
    assert any("no props" in item for item in no_props.failures)


def test_one_league_can_fail_while_the_other_passes():
    bounds = Thresholds(max_brier=0.30, max_calibration_gap=0.15)
    good = _summary()
    bad = _summary(brier=0.50, avg_pred=0.9, hit_rate=0.4)
    result = evaluate_guard([("nba", good), ("wnba", bad)], bounds)
    assert result.ok is False
    assert any(item.startswith("wnba") for item in result.failures)
    assert not any(item.startswith("nba") for item in result.failures)
    assert "ok nba" in result.message
    assert "FAIL wnba" in result.message


# ---------------------------------------------------------------------------
# Odds history hook
# ---------------------------------------------------------------------------


def _captured_quote() -> dict[str, object]:
    """Parse the one complete Over/Under pair in the committed 500-byte capture.

    The body is the first 500 bytes of The Odds API response recorded in
    docs/research/wnba-rollout/odds_api_wnba_markets.md section 3.2.1. It is
    cut off mid-string, so this reads the first finished pair and nothing past it.
    """
    text = FIXTURE.read_text(encoding="utf-8")
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
    league = "wnba" if sport.group(1).endswith("wnba") else sport.group(1).rsplit("_", 1)[-1]
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
        "sport_key": sport.group(1),
    }


def test_odds_hook_is_inactive_when_the_file_is_missing_or_empty(tmp_path):
    assert load_odds_history(None).active is False
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    assert load_odds_history(str(empty)).active is False
    blank = tmp_path / "blank.jsonl"
    blank.write_text("\n\n", encoding="utf-8")
    assert load_odds_history(str(blank)).active is False
    header = tmp_path / "header.csv"
    header.write_text(
        "league,player,game_date,market,open_line,open_over_price,open_under_price,"
        "close_line,close_over_price,close_under_price\n",
        encoding="utf-8",
    )
    assert load_odds_history(str(header)).active is False
    with pytest.raises(FileNotFoundError):
        load_odds_history(str(tmp_path / "no-such-file.csv"))


def test_real_capture_has_zero_clv_when_open_and_close_are_that_quote(tmp_path):
    """One captured snapshot is both the open and the close, so CLV is zero.

    The capture is a single FanDuel player_points quote. There is no second
    timestamp in the committed body, so a non-zero line move would be invented.
    """
    captured = _captured_quote()
    assert captured["sport_key"] == "basketball_wnba"
    assert captured["book"] == "fanduel"
    assert captured["market"] == "player_points"
    assert captured["player"] == "Flau'jae Johnson"

    path = tmp_path / "open_close.csv"
    path.write_text(
        "league,player,game_date,market,open_line,open_over_price,open_under_price,"
        "close_line,close_over_price,close_under_price,book\n"
        f"{captured['league']},{captured['player']},{captured['game_date']},{captured['market']},"
        f"{captured['line']},{captured['over']},{captured['under']},"
        f"{captured['line']},{captured['over']},{captured['under']},{captured['book']}\n",
        encoding="utf-8",
    )
    history = load_odds_history(str(path))
    assert history.active is True
    assert history.skipped_rows == 0
    quote = history.lookup(
        captured["league"],
        captured["player"],
        str(captured["game_date"]),
        "points",
    )
    assert quote is not None
    assert quote.open_line == captured["line"]
    assert quote.close_line == captured["line"]
    assert quote.open_over_price == captured["over"]
    assert quote.open_under_price == captured["under"]

    bootstrap()
    from app.services.prob import american_to_prob, devig

    fair_over, fair_under = devig(
        american_to_prob(captured["over"]),
        american_to_prob(captured["under"]),
    )
    assert fair_over + fair_under == pytest.approx(1.0)
    # -108 and -120 are not a symmetric pair, so the vig-free over is not 0.5.
    assert fair_over != pytest.approx(0.5)
    clv_prob, clv_line = closing_line_value(quote, "over")
    assert clv_prob == pytest.approx(0.0)
    assert clv_line == pytest.approx(0.0)
    under_prob, under_line = closing_line_value(quote, "under")
    assert under_prob == pytest.approx(0.0)
    assert under_line == pytest.approx(0.0)

    reduced = open_close_from_snapshots(
        [
            {
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
        ]
    )
    snapshot_quote = reduced.lookup(
        str(captured["league"]),
        str(captured["player"]),
        str(captured["game_date"]),
        "points",
    )
    assert snapshot_quote is not None
    assert snapshot_quote.book == captured["book"]
    snap_prob, snap_line = closing_line_value(snapshot_quote, "over")
    assert snap_prob == pytest.approx(0.0)
    assert snap_line == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Decision refactor vs the origin/dev predicates
# ---------------------------------------------------------------------------


def _scorecard_signals(hit_rate: float, sample_size: int = 20) -> dict:
    def stub(**details):
        return {
            "signal": "neutral",
            "effect_size": 0.0,
            "sample_size": sample_size,
            "reliability": 0.0,
            "window": "season",
            "source": "test",
            "details": details,
        }

    base = stub(hit_rate=hit_rate, mean=20.0)
    base["sample_size"] = sample_size
    return {
        "get_base_stats": base,
        "get_trend_analysis": stub(recent_vs_season_pct=0.0),
        "get_shooting_profile": stub(fg_diff=0.0),
        "get_variance_profile": stub(cv=0.1),
        "get_schedule_context": stub(is_back_to_back=False),
        "auto_teammate_impact": stub(teammate_chemistry=[]),
        "get_own_team_injury_report": stub(injuries=[]),
    }


def _market(implied: float) -> dict:
    return {
        "get_current_market": {"signal": "available", "details": {"n_books": 4}},
        "get_market_quote_for_line": {
            "signal": "available",
            "details": {
                "pricing_mode": "exact_line",
                "market_implied_for_query": implied,
                "queried_line": 19.5,
            },
        },
    }


def test_choose_daily_pick_side_matches_the_dev_predicate_including_edges():
    from app.services.daily_analysis import (
        HIGH_PROBABILITY_THRESHOLD,
        MIN_SAMPLE_GAMES,
        choose_daily_pick_side,
    )

    assert MIN_SAMPLE_GAMES == 10
    assert HIGH_PROBABILITY_THRESHOLD == 0.65
    grid = [None, 0.0, 0.6499, 0.65, 0.6501, 0.70, 0.80, 1.0, 0.65554]
    for p_over in grid:
        for p_under in grid:
            assert choose_daily_pick_side(p_over, p_under) == _dev_daily_side(
                p_over, p_under
            )
    # Both sides clear 0.65. Dev published the over.
    assert choose_daily_pick_side(0.65, 0.90) == ("over", 0.65)
    assert choose_daily_pick_side(0.6499, 0.65) == ("under", 0.65)
    assert choose_daily_pick_side(0.6499, 0.6499) == (None, None)


def test_scorecard_band_edges_match_the_dev_predicate():
    from scoring import (
        MIN_SAMPLE_FOR_BET,
        OVER_DECISION_THRESHOLD,
        UNDER_DECISION_THRESHOLD,
        compute_scorecard,
        decision_from_over_probability,
    )

    assert MIN_SAMPLE_FOR_BET == 10
    assert OVER_DECISION_THRESHOLD == 0.55
    assert UNDER_DECISION_THRESHOLD == 0.45
    for p_over in (0.0, 0.4499, 0.45, 0.4501, 0.50, 0.5499, 0.55, 0.5501, 1.0):
        assert decision_from_over_probability(p_over) == _dev_scorecard_side(p_over)

    # A market price is attached so the eligibility gate does not rewrite the side.
    # Implied 0.30 is far enough from these rates that EV is not "too thin".
    for rate, side in ((0.55, "over"), (0.45, "under"), (0.50, "avoid"), (0.5499, "avoid"), (0.4501, "avoid")):
        card = compute_scorecard(_scorecard_signals(rate), {}, _market(0.30))
        assert card["decision"] == side
        assert card["model_probability"] == pytest.approx(rate)

    small = compute_scorecard(_scorecard_signals(0.90, sample_size=9), {}, _market(0.30))
    assert small["decision"] == "avoid"
    assert small["eligible_for_bet"] is False
    assert "sample size too small" in small["pass_reason"]


@pytest.mark.xfail(
    reason=(
        "walk_forward._agent_rows applies decision_from_over_probability to "
        "card['model_probability'], which compute_scorecard has already rounded "
        "to 4 decimals (scoring.py returns round(model_prob, 4); walk_forward.py "
        "reads that value). The scorecard's own pre-gate comparison, on dev and "
        "on this branch, uses the unrounded model_prob. 0.54995 is avoid before "
        "rounding and over after round(..., 4), so an agent pick can cross the "
        "0.55 edge."
    )
)
def test_published_probability_stays_on_the_same_side_as_the_unrounded_candidate():
    from scoring import compute_scorecard, decision_from_over_probability

    raw = 0.54995
    assert _dev_scorecard_side(raw) == "avoid"
    card = compute_scorecard(_scorecard_signals(raw), {}, _market(0.30))
    assert card["model_probability"] == pytest.approx(0.55)
    # The replay's pre-gate side is this call. It has to agree with the
    # unrounded comparison the scorecard actually made.
    assert decision_from_over_probability(card["model_probability"]) == "avoid"


# ---------------------------------------------------------------------------
# League parameterization
# ---------------------------------------------------------------------------


def test_nba_and_wnba_replays_share_the_scoring_math():
    start = datetime(2025, 11, 1)
    logs = [_game(start + timedelta(days=offset), 10.0 + (offset % 3)) for offset in range(16)]
    cache = {"Test Player": logs}
    nba = _replay(cache, "nba")
    wnba = _replay(cache, "wnba")
    assert nba.daily and wnba.daily

    def signature(replay):
        return [
            (row.proxy, row.date, row.market, row.line, row.actual, row.p_over, row.p_under, row.pick, row.hit, row.n_games)
            for row in replay.daily
        ]

    assert signature(nba) == signature(wnba)
    assert {row.league for row in nba.daily} == {"nba"}
    assert {row.league for row in wnba.daily} == {"wnba"}


def test_default_window_is_per_league_and_the_loop_is_shared():
    """June games are WNBA targets. The same games are NBA history, not targets.

    EVAL_START is the only league-specific input on this path. The rows that
    both leagues do score, once the NBA window is opened, match the WNBA rows.
    """
    start = datetime(2025, 6, 1)
    logs = [_game(start + timedelta(days=offset), 12.0) for offset in range(20)]
    cache = {"Test Player": logs}
    wnba = replay_league(
        _Service(cache),
        "wnba",
        ["L10"],
        markets=[("player_points", "points")],
        do_agent=False,
        validate=0,
    )
    nba_default = replay_league(
        _Service(cache),
        "nba",
        ["L10"],
        markets=[("player_points", "points")],
        do_agent=False,
        validate=0,
    )
    assert EVAL_START["wnba"] == datetime(2025, 5, 1)
    assert EVAL_START["nba"] == datetime(2025, 10, 21)
    assert wnba.daily
    assert all(row.date < "2025-10-21" for row in wnba.daily)
    assert nba_default.daily == []
    nba_opened = replay_league(
        _Service(cache),
        "nba",
        ["L10"],
        eval_start=EVAL_START["wnba"],
        markets=[("player_points", "points")],
        do_agent=False,
        validate=0,
    )

    def signature(replay):
        return [(row.date, row.line, row.pick, row.hit, row.n_games) for row in replay.daily]

    assert signature(nba_opened) == signature(wnba)
