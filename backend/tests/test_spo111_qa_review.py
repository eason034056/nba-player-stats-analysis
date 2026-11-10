"""QA coverage for SPO-111 read tiers, historical rates, and top_read.

The published board is probability >= 0.65 and n_games >= 10. That
predicate is copied below as ``_prechange_board`` so the default query
is compared with the filter this PR replaced, not with the new helper.

``p_over`` and ``p_under`` are shares of prior games (strictly above and
strictly below the line). They are not bookmaker no-vig probabilities.
A push makes their sum less than 1. A missing side stays null.

Odds API bodies come from ``tests.fixtures.odds_api.load_odds_fixture``.
"""

import asyncio
import inspect
import math
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.schemas import AnalysisStats, DailyPick, DailyPicksResponse, NBAEvent
from app.services.cache import CacheService, cache_service
from app.services.daily_analysis import (
    HIGH_PROBABILITY_THRESHOLD,
    MIN_SAMPLE_GAMES,
    DailyAnalysisService,
    best_top_reads,
    daily_picks_cache_key,
    present_daily_picks,
    read_tier,
)
from app.services.prob import american_to_prob, devig, posted_american_odds
from tests.fixtures.odds_api import load_odds_fixture

# PR #39 frontend/lib/today-board.ts readTier. Cuts are inclusive.
# Labels there are "Strong play", "Playable", "Lean only", and "Pass".
# This API uses "Lean" and sends null below 0.56 (the pass bucket).
_READ_TIER_TABLE = (
    (0.70, "Strong play"),
    (0.65, "Playable"),
    (0.56, "Lean"),
)

_EVENTS = load_odds_fixture("odds_api_events__basketball_nba.json")
_PLAYER_POINTS = load_odds_fixture("odds_api_event_odds__player_points.json")
_PLAYER_NAMES = tuple(sorted({
    outcome["description"]
    for book in _PLAYER_POINTS["bookmakers"]
    for market in book["markets"]
    for outcome in market["outcomes"]
    if outcome.get("description")
}))


def _frontend_read_tier(probability):
    """Same comparisons as PR #39 ``readTier``, with this API's strings.

    Non-finite input and a probability below 0.56 return None. The
    frontend returns null for non-finite input and ``pass`` below 0.56.
    """
    if probability is None or not isinstance(probability, (int, float)):
        return None
    if not math.isfinite(probability):
        return None
    for cutoff, label in _READ_TIER_TABLE:
        if probability >= cutoff:
            return label
    return None


def _prechange_board(picks, min_probability=0.65, min_games=10):
    """The daily-picks filter before the floors moved onto the query.

    Inclusive on both sides. This is the predicate that used to live
    inline in ``get_daily_picks``. It is not a call to ``select_daily_picks``.
    """
    return [
        pick
        for pick in picks
        if pick.probability >= min_probability and pick.n_games >= min_games
    ]


def _identity(pick):
    return (
        pick.player_name,
        pick.metric,
        pick.direction,
        pick.probability,
        pick.n_games,
        pick.threshold,
        pick.tier,
        pick.p_over,
        pick.p_under,
    )


def _books(event, only=None, drop_under=False, null_under_price=False):
    """Copy recorded bookmakers, optionally keeping one player or one side.

    The outcomes still come from the fixture. Dropping the Under name or
    clearing its price is how a one-sided quote is built without typing
    a new Odds API body.
    """
    books = []
    for book in event["bookmakers"]:
        markets = []
        for market in book.get("markets", []):
            outcomes = []
            for outcome in market.get("outcomes", []):
                if only is not None and outcome.get("description") not in only:
                    continue
                if drop_under and outcome.get("name") == "Under":
                    continue
                row = dict(outcome)
                if null_under_price and row.get("name") == "Under":
                    row["price"] = None
                outcomes.append(row)
            if outcomes:
                markets.append({**market, "outcomes": outcomes})
        if markets:
            books.append({**book, "markets": markets})
    return books


def _fair_pair(books, player):
    """First two-sided no-vig pair posted for ``player``, at any line."""
    for book in books:
        for market in book.get("markets", []):
            over_price = None
            under_price = None
            point = None
            for outcome in market.get("outcomes", []):
                if outcome.get("description") != player:
                    continue
                price = posted_american_odds(outcome.get("price"))
                if price is None:
                    continue
                if outcome.get("name") == "Over" and over_price is None:
                    over_price = price
                    point = outcome.get("point")
                elif outcome.get("name") == "Under" and under_price is None:
                    under_price = price
            if over_price is not None and under_price is not None:
                return devig(
                    american_to_prob(over_price),
                    american_to_prob(under_price),
                ), point
    return None, None


def _rates_from_values(values, threshold):
    n_games = len(values)
    p_over = round(sum(value > threshold for value in values) / n_games, 4)
    p_under = round(sum(value < threshold for value in values) / n_games, 4)
    return p_over, p_under, n_games


def _analyze(stats_for, *, league="nba", only=None, drop_under=False, null_under_price=False):
    """Run one event through the service using the recorded player_points body."""
    event = _PLAYER_POINTS
    service = DailyAnalysisService()

    async def props(event_id, market_key, league="nba"):
        if event_id != event["id"] or market_key != "player_points":
            return []
        return _books(
            event,
            only=only,
            drop_under=drop_under,
            null_under_price=null_under_price,
        )

    service._get_props_for_market = props
    service.csv_service = type("Csv", (), {})()
    service.csv_service.latest_position = lambda player_name: None
    service.csv_service.get_player_stats = (
        lambda player_name, metric, threshold, n=0, exclude_dnp=True: stats_for(
            player_name, threshold
        )
    )
    return asyncio.run(
        service._analyze_single_event(
            event_id=event["id"],
            home_team=event["home_team"],
            away_team=event["away_team"],
            commence_time=event["commence_time"],
            projections={},
            league=league,
        )
    )[0]


def _case_stats(assignments):
    """Stats callback. ``"push"`` builds an 8 / 1 / 1 split around the line."""

    def stats_for(player_name, threshold):
        spec = assignments[player_name]
        if spec == "push":
            values = [threshold + 1] * 8 + [threshold - 1] + [threshold]
            p_over, p_under, n_games = _rates_from_values(values, threshold)
        elif spec == "all_over":
            values = [threshold + 1] * 10
            p_over, p_under, n_games = _rates_from_values(values, threshold)
        else:
            p_over, p_under, n_games = spec
        return {
            "p_over": p_over,
            "p_under": p_under,
            "n_games": n_games,
            "game_logs": [{"team": "Hawks"}],
        }

    return stats_for


def _named_cases():
    """One recorded player per boundary. There are 15 names in the fixture."""
    assert len(_PLAYER_NAMES) >= 15
    roles = (
        ("exact_strong", (0.70, 0.20, 12)),
        ("just_below_strong", (0.6999, 0.20, 12)),
        ("exact_playable", (0.65, 0.25, 10)),
        ("just_below_playable", (0.6499, 0.30, 15)),
        ("exact_lean", (0.56, 0.30, 18)),
        ("just_below_lean", (0.5599, 0.30, 18)),
        ("short_sample", (0.80, 0.10, 5)),
        ("too_few", (0.95, 0.02, 4)),
        ("over_wins_tie_bar", (0.65, 0.90, 20)),
        ("lean_must_not_steal", (0.57, 0.90, 22)),
        ("under_only", (None, 0.80, 12)),
        ("over_only", (0.82, None, 12)),
        ("missing_both", (None, None, 20)),
        ("push", "push"),
        ("nine_games", (0.80, 0.10, 9)),
    )
    by_role = {}
    assignments = {}
    for (role, spec), name in zip(roles, _PLAYER_NAMES):
        by_role[role] = name
        assignments[name] = spec
    return by_role, assignments


_ROLES, _ASSIGNMENTS = _named_cases()


class TestTierBoundariesMatchReadTier:
    @pytest.mark.parametrize(
        ("probability", "tier"),
        [
            (None, None),
            (0.5599, None),
            (0.56, "Lean"),
            (0.6499, "Lean"),
            (0.65, "Playable"),
            (0.6999, "Playable"),
            (0.70, "Strong play"),
            (1.0, "Strong play"),
        ],
    )
    def test_inclusive_cuts_match_read_tier(self, probability, tier):
        assert read_tier(probability) == tier
        assert _frontend_read_tier(probability) == tier

    def test_value_just_below_a_cut_does_not_use_the_higher_label(self):
        assert read_tier(0.70) == "Strong play"
        assert read_tier(0.6999) != "Strong play"
        assert read_tier(0.65) == "Playable"
        assert read_tier(0.6499) != "Playable"
        assert read_tier(0.56) == "Lean"
        assert read_tier(0.5599) is None

    def test_stored_rows_use_those_same_cuts(self):
        picks = _analyze(_case_stats(_ASSIGNMENTS))
        by_name = {pick.player_name: pick for pick in picks}

        assert by_name[_ROLES["exact_strong"]].tier == "Strong play"
        assert by_name[_ROLES["exact_strong"]].probability == pytest.approx(0.70)
        assert by_name[_ROLES["just_below_strong"]].tier == "Playable"
        assert by_name[_ROLES["just_below_strong"]].probability == pytest.approx(0.6999)
        assert by_name[_ROLES["exact_playable"]].tier == "Playable"
        assert by_name[_ROLES["exact_playable"]].probability == pytest.approx(0.65)
        assert by_name[_ROLES["exact_playable"]].n_games == 10
        assert by_name[_ROLES["just_below_playable"]].tier == "Lean"
        assert by_name[_ROLES["exact_lean"]].tier == "Lean"
        assert by_name[_ROLES["exact_lean"]].probability == pytest.approx(0.56)
        assert _ROLES["just_below_lean"] not in by_name
        assert _ROLES["too_few"] not in by_name
        assert _ROLES["missing_both"] not in by_name


class TestHistoricalRatesAreNotDevigged:
    def test_push_stays_below_one_and_is_not_the_book_fair_pair(self):
        picks = _analyze(_case_stats(_ASSIGNMENTS))
        push = next(pick for pick in picks if pick.player_name == _ROLES["push"])
        assert push.p_over == pytest.approx(0.8)
        assert push.p_under == pytest.approx(0.1)
        assert 0.0 <= push.p_over <= 1.0
        assert 0.0 <= push.p_under <= 1.0
        assert push.p_over + push.p_under == pytest.approx(0.9)
        assert push.p_over + push.p_under < 1.0
        fair, _point = _fair_pair(_PLAYER_POINTS["bookmakers"], push.player_name)
        assert fair is not None
        assert push.p_over != pytest.approx(fair[0], abs=0.02)
        assert push.p_under != pytest.approx(fair[1], abs=0.02)

    def test_no_push_can_sum_to_one_without_being_de_vigged(self):
        name = _ROLES["exact_strong"]
        picks = _analyze(
            _case_stats({name: "all_over"}),
            only={name},
        )
        assert len(picks) == 1
        pick = picks[0]
        assert pick.p_over == pytest.approx(1.0)
        assert pick.p_under == pytest.approx(0.0)
        assert pick.p_over + pick.p_under == pytest.approx(1.0)
        fair, _point = _fair_pair(_books(_PLAYER_POINTS, only={name}), name)
        assert fair is not None
        assert fair[0] != pytest.approx(1.0)
        assert pick.p_over != pytest.approx(fair[0], abs=0.02)

    def test_missing_side_stays_null(self):
        picks = _analyze(_case_stats(_ASSIGNMENTS))
        by_name = {pick.player_name: pick for pick in picks}
        under_only = by_name[_ROLES["under_only"]]
        over_only = by_name[_ROLES["over_only"]]
        assert under_only.direction == "under"
        assert under_only.p_over is None
        assert under_only.p_under == pytest.approx(0.80)
        assert under_only.probability == pytest.approx(0.80)
        assert over_only.direction == "over"
        assert over_only.p_over == pytest.approx(0.82)
        assert over_only.p_under is None

    def test_one_sided_or_missing_price_does_not_replace_the_historical_rate(self):
        name = _ROLES["push"]
        history = _case_stats({name: "push"})
        for kwargs in ({"drop_under": True}, {"null_under_price": True}):
            picks = _analyze(history, only={name}, **kwargs)
            assert len(picks) == 1
            pick = picks[0]
            assert pick.p_over == pytest.approx(0.8)
            assert pick.p_under == pytest.approx(0.1)
            books = _books(_PLAYER_POINTS, only={name}, **kwargs)
            posted = []
            for book in books:
                for market in book["markets"]:
                    for outcome in market["outcomes"]:
                        if outcome.get("description") != name:
                            continue
                        price = posted_american_odds(outcome.get("price"))
                        if price is not None and outcome.get("name") == "Over":
                            posted.append(american_to_prob(price))
            assert posted
            assert pick.p_over != pytest.approx(posted[0], abs=0.02)
            assert pick.p_under is not None


class TestTopReadSelection:
    def _row(self, player, probability, event_id="evt", metric="points", side="over", line=10.5):
        return {
            "event_id": event_id,
            "player_name": player,
            "metric": metric,
            "direction": side,
            "threshold": line,
            "probability": probability,
        }

    def test_tie_keeps_the_earlier_row_and_a_higher_later_row_wins(self):
        reads = best_top_reads({
            "picks": [
                self._row("First", 0.80, event_id="tie", metric="points"),
                self._row("Second", 0.80, event_id="tie", metric="rebounds", side="under", line=8.5),
                self._row("Low", 0.66, event_id="best", metric="assists", line=6.5),
                self._row("High", 0.91, event_id="best", metric="points", side="under", line=24.5),
            ]
        })
        assert reads["tie"].player == "First"
        assert reads["tie"].market == "player_points"
        assert reads["best"].player == "High"
        assert reads["best"].market == "player_points"
        assert reads["best"].side == "under"
        assert reads["best"].probability == pytest.approx(0.91)

    def test_no_picks_and_none_probability_leave_the_event_unread(self):
        assert best_top_reads(None) == {}
        assert best_top_reads({}) == {}
        assert best_top_reads({"picks": []}) == {}
        assert best_top_reads({"picks": None}) == {}
        only_missing = best_top_reads({
            "picks": [self._row("Nobody", None)]
        })
        assert only_missing == {}
        reads = best_top_reads({
            "picks": [
                self._row("Missing", None),
                self._row("Kept", 0.72, metric="rebounds", line=7.5),
            ]
        })
        assert reads["evt"].player == "Kept"
        assert reads["evt"].market == "player_rebounds"
        assert reads["evt"].probability == pytest.approx(0.72)

    def test_non_finite_probability_does_not_replace_a_finite_pick(self):
        """A NaN row must not become top_read.

        ``float('nan') <= probability`` is false, so the current selector
        treats NaN as a new maximum. This test pins that bug.
        """
        reads = best_top_reads({
            "picks": [
                self._row("Finite", 0.80),
                self._row("NotANumber", float("nan"), side="under", line=22.5),
            ]
        })
        assert "evt" in reads
        assert reads["evt"].player == "Finite"
        assert math.isfinite(reads["evt"].probability)


class TestDefaultBoardBackCompat:
    def _stored(self):
        picks = _analyze(_case_stats(_ASSIGNMENTS))
        return DailyPicksResponse(
            date="2026-11-10",
            analyzed_at="2026-11-10T12:00:00+00:00",
            total_picks=len(picks),
            picks=picks,
            stats=AnalysisStats(
                total_events=1,
                total_players=len(_PLAYER_NAMES),
                total_props=len(picks),
                high_prob_count=len(_prechange_board(picks)),
                analysis_duration_seconds=0.1,
            ),
        )

    def test_default_params_equal_the_prechange_filter_and_overrides_widen_it(self):
        from app.api.daily_picks import get_daily_picks, trigger_daily_analysis

        stored = self._stored()
        signature = inspect.signature(get_daily_picks)
        default_probability = signature.parameters["min_probability"].default.default
        default_games = signature.parameters["min_games"].default.default
        assert default_probability == HIGH_PROBABILITY_THRESHOLD == 0.65
        assert default_games == MIN_SAMPLE_GAMES == 10

        old = [_identity(pick) for pick in _prechange_board(stored.picks)]
        presented = [_identity(pick) for pick in present_daily_picks(stored).picks]
        assert presented == old
        assert any(row[3] == pytest.approx(0.65) and row[4] == 10 for row in old)
        assert all(row[3] >= 0.65 and row[4] >= 10 for row in old)

        async def run_analysis(**kwargs):
            return stored

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            "app.api.daily_picks.daily_analysis_service.run_daily_analysis",
            run_analysis,
        )
        try:
            default = asyncio.run(
                get_daily_picks(
                    date="2026-11-10",
                    tz_offset=0,
                    refresh=False,
                    min_probability=default_probability,
                    min_games=default_games,
                )
            )
            lean = asyncio.run(
                get_daily_picks(
                    date="2026-11-10",
                    tz_offset=0,
                    refresh=False,
                    min_probability=0.56,
                    min_games=default_games,
                )
            )
            with_short = asyncio.run(
                get_daily_picks(
                    date="2026-11-10",
                    tz_offset=0,
                    refresh=False,
                    min_probability=0.56,
                    min_games=5,
                )
            )
            trigger = asyncio.run(
                trigger_daily_analysis(date="2026-11-10", tz_offset=0)
            )
        finally:
            monkeypatch.undo()

        assert [_identity(pick) for pick in default.picks] == old
        assert [_identity(pick) for pick in trigger.picks] == old
        assert [_identity(pick) for pick in lean.picks] == [
            _identity(pick)
            for pick in _prechange_board(stored.picks, min_probability=0.56, min_games=10)
        ]
        assert [_identity(pick) for pick in with_short.picks] == [
            _identity(pick)
            for pick in _prechange_board(stored.picks, min_probability=0.56, min_games=5)
        ]
        lean_names = {pick.player_name for pick in lean.picks}
        assert _ROLES["exact_lean"] in lean_names
        assert _ROLES["just_below_playable"] in lean_names
        assert _ROLES["exact_lean"] not in {pick.player_name for pick in default.picks}
        assert _ROLES["nine_games"] in {pick.player_name for pick in with_short.picks}
        assert _ROLES["short_sample"] in {pick.player_name for pick in with_short.picks}
        assert _ROLES["nine_games"] not in {pick.player_name for pick in default.picks}

        over_wins = next(pick for pick in default.picks if pick.player_name == _ROLES["over_wins_tie_bar"])
        assert over_wins.direction == "over"
        assert over_wins.probability == pytest.approx(0.65)
        assert over_wins.p_under == pytest.approx(0.90)
        stolen = next(pick for pick in default.picks if pick.player_name == _ROLES["lean_must_not_steal"])
        assert stolen.direction == "under"
        assert stolen.probability == pytest.approx(0.90)


class TestResponseSchema:
    def test_events_top_read_matches_the_contract(self, monkeypatch):
        from app.api.nba import get_events

        props_calls = {"n": 0}

        async def fake_events(**kwargs):
            return list(_EVENTS)

        async def fake_props(*args, **kwargs):
            props_calls["n"] += 1
            raise AssertionError("top_read must not request props")

        hawks = _PLAYER_POINTS["id"]
        store = {
            daily_picks_cache_key("nba", "2026-11-10", 0): {
                "picks": [
                    {
                        "event_id": hawks,
                        "player_name": "Weaker",
                        "metric": "assists",
                        "direction": "over",
                        "threshold": 6.5,
                        "probability": 0.66,
                    },
                    {
                        "event_id": hawks,
                        "player_name": "Missing",
                        "metric": "points",
                        "direction": "over",
                        "threshold": 10.5,
                        "probability": None,
                    },
                    {
                        "event_id": hawks,
                        "player_name": "Stronger",
                        "metric": "points",
                        "direction": "under",
                        "threshold": 24.5,
                        "probability": 0.91,
                    },
                ]
            }
        }

        async def fake_get(key):
            return store.get(key)

        async def fake_set(key, value, ttl):
            store[key] = value
            return True

        monkeypatch.setattr("app.api.nba.odds_provider.get_events", fake_events)
        monkeypatch.setattr("app.api.nba.odds_gateway.get_market_snapshot", fake_props)
        monkeypatch.setattr(cache_service, "get", fake_get)
        monkeypatch.setattr(cache_service, "set", fake_set)

        response = asyncio.run(
            get_events(date="2026-11-10", regions="us", tz_offset=0)
        )
        assert props_calls["n"] == 0
        body = response.model_dump(mode="json")
        assert body["date"] == "2026-11-10"
        assert isinstance(body["events"], list)
        by_id = {event["event_id"]: event for event in body["events"]}
        assert hawks in by_id
        top = by_id[hawks]["top_read"]
        assert set(top) == {"player", "market", "side", "line", "probability"}
        assert top["player"] == "Stronger"
        assert isinstance(top["player"], str)
        assert top["market"] == "player_points"
        assert top["side"] == "under"
        assert isinstance(top["line"], float)
        assert top["line"] == 24.5
        assert isinstance(top["probability"], float)
        assert 0.0 <= top["probability"] <= 1.0
        empty_id = next(
            event["id"]
            for event in _EVENTS
            if event["id"] != hawks and event["commence_time"].startswith("2026-11-10")
        )
        assert by_id[empty_id]["top_read"] is None
        assert all(
            event["commence_time"].startswith("2026-11-10")
            for event in body["events"]
        )

    def test_daily_pick_and_bot_pick_fields_match_the_contract(self, monkeypatch):
        from app.api.daily_picks import get_daily_picks
        from app.api.picks import get_picks_today

        picks = _analyze(_case_stats(_ASSIGNMENTS))
        stored = DailyPicksResponse(
            date="2026-11-10",
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_picks=len(picks),
            picks=picks,
            stats=None,
        )

        async def run_analysis(**kwargs):
            return stored

        monkeypatch.setattr(
            "app.api.daily_picks.daily_analysis_service.run_daily_analysis",
            run_analysis,
        )
        monkeypatch.setattr(
            "app.api.picks.daily_analysis_service.run_daily_analysis",
            run_analysis,
        )
        monkeypatch.setattr("app.api.picks.settings.bot_api_keys_premium", "prem-key")

        signature = inspect.signature(get_daily_picks)
        daily = asyncio.run(
            get_daily_picks(
                date="2026-11-10",
                tz_offset=0,
                refresh=False,
                min_probability=signature.parameters["min_probability"].default.default,
                min_games=signature.parameters["min_games"].default.default,
            )
        )
        for row in daily.model_dump(mode="json")["picks"]:
            assert row["tier"] in ("Strong play", "Playable")
            assert row["direction"] in ("over", "under")
            for key in ("p_over", "p_under"):
                assert row[key] is None or isinstance(row[key], float)
                if row[key] is not None:
                    assert 0.0 <= row[key] <= 1.0

        endpoint = get_picks_today
        while hasattr(endpoint, "__wrapped__"):
            endpoint = endpoint.__wrapped__
        bot_signature = inspect.signature(endpoint)
        bot = asyncio.run(
            endpoint(
                request=type("Req", (), {"headers": {}})(),
                api_key="prem-key",
                tz_offset=0,
                min_confidence=bot_signature.parameters["min_confidence"].default.default,
            )
        )
        bot_body = bot.model_dump(mode="json")
        assert bot_body["tier"] == "premium"
        assert bot_body["tier"] not in ("Strong play", "Playable", "Lean")
        assert bot_body["picks"]
        for row in bot_body["picks"]:
            assert "tier" not in row
            assert "p_over" in row and "p_under" in row
            assert row["direction"] in ("over", "under")


class TestWnbaDoesNotInheritNbaReads:
    def test_wnba_storage_keeps_the_old_floors(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.daily_analysis.wnba_csv_player_service.get_player_stats",
            lambda player_name, metric, threshold, n=0, exclude_dnp=True: _case_stats(
                _ASSIGNMENTS
            )(player_name, threshold),
        )
        picks = _analyze(_case_stats(_ASSIGNMENTS), league="wnba")
        names = {pick.player_name for pick in picks}
        assert _ROLES["exact_lean"] not in names
        assert _ROLES["just_below_playable"] not in names
        assert _ROLES["short_sample"] not in names
        assert _ROLES["nine_games"] not in names
        assert _ROLES["just_below_lean"] not in names
        assert names == {pick.player_name for pick in _prechange_board(picks)}
        assert all(pick.probability >= 0.65 and pick.n_games >= 10 for pick in picks)

    def test_wnba_events_leave_top_read_null_when_an_nba_cache_exists(self, monkeypatch):
        from app.api.wnba import get_events as get_wnba_events
        from app.models.schemas import EventsResponse

        event = NBAEvent(
            event_id=_PLAYER_POINTS["id"],
            sport_key="basketball_wnba",
            home_team="Las Vegas Aces",
            away_team="New York Liberty",
            commence_time=datetime(2026, 11, 10, 0, 10, tzinfo=timezone.utc),
        )
        cached = EventsResponse(date="2026-11-10", events=[event]).model_dump(mode="json")
        events_key = f"{CacheService.build_events_key('2026-11-10', 'us', league='wnba')}:tz0"
        nba_picks_key = daily_picks_cache_key("nba", "2026-11-10", 0)
        store = {
            events_key: cached,
            nba_picks_key: {
                "picks": [
                    {
                        "event_id": event.event_id,
                        "player_name": "Should Not Attach",
                        "metric": "points",
                        "direction": "over",
                        "threshold": 18.5,
                        "probability": 0.91,
                    }
                ]
            },
        }
        seen = []

        async def fake_get(key):
            seen.append(key)
            return store.get(key)

        async def fake_events(**kwargs):
            raise AssertionError("WNBA cache hit must not call the Odds API")

        monkeypatch.setattr(cache_service, "get", fake_get)
        monkeypatch.setattr("app.api.wnba.odds_provider.get_events", fake_events)

        response = asyncio.run(
            get_wnba_events(date="2026-11-10", regions="us", tz_offset=0)
        )
        body = response.model_dump(mode="json")
        assert body["events"][0]["top_read"] is None
        assert nba_picks_key not in seen
        assert events_key in seen

    def test_wnba_get_still_applies_the_old_filter(self, monkeypatch):
        from app.api.wnba import get_wnba_daily_picks

        picks = _analyze(_case_stats(_ASSIGNMENTS))
        stored = DailyPicksResponse(
            date="2026-11-10",
            analyzed_at="2026-11-10T12:00:00+00:00",
            total_picks=len(picks),
            picks=picks,
            stats=None,
        )

        async def run_analysis(**kwargs):
            assert kwargs.get("league") == "wnba"
            return stored

        monkeypatch.setattr(
            "app.api.wnba.daily_analysis_service.run_daily_analysis",
            run_analysis,
        )
        signature = inspect.signature(get_wnba_daily_picks)
        response = asyncio.run(
            get_wnba_daily_picks(
                date="2026-11-10",
                tz_offset=0,
                refresh=False,
                min_probability=signature.parameters["min_probability"].default.default,
                min_games=signature.parameters["min_games"].default.default,
            )
        )
        assert [_identity(pick) for pick in response.picks] == [
            _identity(pick) for pick in _prechange_board(stored.picks)
        ]
        assert _ROLES["exact_lean"] not in {pick.player_name for pick in response.picks}
