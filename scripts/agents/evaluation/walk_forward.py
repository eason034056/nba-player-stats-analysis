"""Walk-forward replay of Daily Picks and the agent scorecard.

Every target game is scored with games dated strictly before it. The daily
path calls ``choose_daily_pick_side`` and the same empirical rate that
``CSVPlayerHistoryService.get_player_stats`` returns (``n=0``,
``exclude_dnp=True``). A sample of those rates is checked against the real
method at the end of each league. The agent path calls
``tools.historical`` and ``scoring.compute_scorecard`` on a cache that has
been temporarily replaced with that same prior-game list, so the tools
cannot see the target or anything after it.

There is no historical market, lineup, or injury feed. ``compute_scorecard``
therefore gates every agent row to ``avoid`` with ``no market price
available``. The row's ``pick`` is the pre-gate candidate,
``decision_from_over_probability`` applied to the rounded model
probability the scorecard returns. That is the decision a caller sees
before the market gate rewrites it.
"""

from __future__ import annotations

import logging
import random
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator

import numpy as np

from evaluation.odds_history import OddsHistory, closing_line_value, inactive_history
from evaluation.paths import bootstrap
from evaluation.proxy_lines import AGENT_PROXIES, proxy_line

logger = logging.getLogger(__name__)

# First date a game can be a target. Earlier games are history only.
# NBA is the 2025-26 regular-season opener. WNBA is the start of the 2025
# file; the 10-game minimum is what actually pushes the first scored game
# into June.
EVAL_START = {
    "nba": datetime(2025, 10, 21),
    "wnba": datetime(2025, 5, 1),
}
NBA_REGULAR_SEASON_START = datetime(2025, 10, 21)
AGENT_METRICS = ("points", "rebounds", "assists", "pra")


class DailyRow(tuple):
    """One player-game-market scored by the Daily Picks rule.

    Named fields, stored as a tuple so a full multi-proxy replay stays
    cheap. ``line_source`` is ``proxy`` unless an odds quote replaced the
    line with that prop's opening number.
    """

    __slots__ = ()

    def __new__(
        cls,
        league: str,
        proxy: str,
        date: str,
        market: str,
        line: float,
        actual: float,
        n_games: int,
        l10_min: float,
        p_over: float,
        p_under: float,
        over_hit: int,
        pick: str | None,
        prob: float | None,
        hit: int | None,
        line_source: str,
        price: int | None = None,
        clv_prob: float | None = None,
        clv_line: float | None = None,
    ):
        return tuple.__new__(
            cls,
            (
                league,
                proxy,
                date,
                market,
                line,
                actual,
                n_games,
                l10_min,
                p_over,
                p_under,
                over_hit,
                pick,
                prob,
                hit,
                line_source,
                price,
                clv_prob,
                clv_line,
            ),
        )

    league = property(lambda self: self[0])
    proxy = property(lambda self: self[1])
    date = property(lambda self: self[2])
    market = property(lambda self: self[3])
    line = property(lambda self: self[4])
    actual = property(lambda self: self[5])
    n_games = property(lambda self: self[6])
    l10_min = property(lambda self: self[7])
    p_over = property(lambda self: self[8])
    p_under = property(lambda self: self[9])
    over_hit = property(lambda self: self[10])
    pick = property(lambda self: self[11])
    prob = property(lambda self: self[12])
    hit = property(lambda self: self[13])
    line_source = property(lambda self: self[14])
    price = property(lambda self: self[15])
    clv_prob = property(lambda self: self[16])
    clv_line = property(lambda self: self[17])


class AgentRow(tuple):
    """One player-game-market scored by ``compute_scorecard``.

    ``prod_decision`` is what the scorecard returned after the market gate.
    ``pick`` is the pre-gate side. With no historical price those two
    differ: production says avoid, and ``pick`` is the side the probability
    band would have taken.
    """

    __slots__ = ()

    def __new__(
        cls,
        league: str,
        proxy: str,
        date: str,
        market: str,
        line: float,
        actual: float,
        l10_min: float,
        p_over: float,
        over_hit: int,
        confidence: float,
        prod_decision: str,
        eligible: bool,
        pass_reason: str | None,
        pick: str | None,
        prob: float | None,
        hit: int | None,
        b2b: int,
        line_source: str,
        price: int | None = None,
        clv_prob: float | None = None,
        clv_line: float | None = None,
    ):
        return tuple.__new__(
            cls,
            (
                league,
                proxy,
                date,
                market,
                line,
                actual,
                l10_min,
                p_over,
                over_hit,
                confidence,
                prod_decision,
                eligible,
                pass_reason,
                pick,
                prob,
                hit,
                b2b,
                line_source,
                price,
                clv_prob,
                clv_line,
            ),
        )

    league = property(lambda self: self[0])
    proxy = property(lambda self: self[1])
    date = property(lambda self: self[2])
    market = property(lambda self: self[3])
    line = property(lambda self: self[4])
    actual = property(lambda self: self[5])
    l10_min = property(lambda self: self[6])
    p_over = property(lambda self: self[7])
    over_hit = property(lambda self: self[8])
    confidence = property(lambda self: self[9])
    prod_decision = property(lambda self: self[10])
    eligible = property(lambda self: self[11])
    pass_reason = property(lambda self: self[12])
    pick = property(lambda self: self[13])
    prob = property(lambda self: self[14])
    hit = property(lambda self: self[15])
    b2b = property(lambda self: self[16])
    line_source = property(lambda self: self[17])
    price = property(lambda self: self[18])
    clv_prob = property(lambda self: self[19])
    clv_line = property(lambda self: self[20])


@dataclass
class ValidationCase:
    """One comparison against the real ``get_player_stats``."""

    player: str
    metric: str
    line: float
    p_over: float
    p_under: float
    n_games: int
    prior_nf: list[dict]


@dataclass
class LeagueReplay:
    """Walk-forward output for one league."""

    league: str
    daily: list[DailyRow] = field(default_factory=list)
    agent: list[AgentRow] = field(default_factory=list)
    targets: int = 0
    target_start: str | None = None
    target_end: str | None = None
    exposure: dict = field(default_factory=dict)
    validation: dict = field(default_factory=dict)


def empirical_rates(values: np.ndarray, line: float) -> tuple[float, float, int]:
    """Over/under rates rounded the way ``get_player_stats`` rounds them.

    Over is ``value > line``. Under is ``value < line``. A push is in
    neither rate. The denominator is every non-null prior value, which is
    ``n=0`` in the production call.
    """
    n = int(values.size)
    p_over = round(float((values > line).sum()) / n, 4)
    p_under = round(float((values < line).sum()) / n, 4)
    return p_over, p_under, n


def select_players(names: list[str], limit: int | None, seed: int) -> set[str] | None:
    """Return a deterministic subset of ``names``, or None to keep all of them.

    ``None`` means "do not filter". A positive ``limit`` draws ``limit``
    names from the sorted list with ``random.Random(seed)``, which is the
    sample the calibration guard replays.
    """
    if limit is None or limit >= len(names):
        return None
    if limit <= 0:
        raise ValueError("player limit must be positive")
    return set(random.Random(seed).sample(sorted(names), limit))


def agent_proxies_for(proxies: list[str]) -> list[str]:
    """Agent tables follow MED20 and L10 when those were requested.

    L5 and ALL stay on the daily sensitivity table. If the caller asked
    only for those, the agent path follows the request instead of skipping.
    """
    preferred = [proxy for proxy in proxies if proxy in AGENT_PROXIES]
    return preferred if preferred else list(proxies)


@contextmanager
def _prior_games_only(
    service: object, player: str, prior_nf: list[dict]
) -> Iterator[None]:
    """Show ``player``'s tools only ``prior_nf``, then put the cache back.

    ``tools.historical._games_for`` reads this cache. Swapping the list is
    what keeps the target game, and every game after it, out of the
    scorecard. The list is newest-first, which is the order the cache
    already uses.
    """
    cache = service._cache  # type: ignore[attr-defined]
    previous = cache[player]
    cache[player] = prior_nf
    try:
        yield
    finally:
        cache[player] = previous


def _active_games(logs: list[dict]) -> list[dict]:
    """Non-DNP games with a date, oldest first. Equal dates keep cache order."""
    active = [
        game for game in logs if game.get("minutes", 0) > 0 and game.get("game_date")
    ]
    active.sort(key=lambda game: game["game_date"])
    return active


def _price_fields(
    quote: object | None, pick: str | None, line: float
) -> tuple[float, str, int | None, float | None, float | None]:
    """Apply an opening line and its price when a quote exists and a side was bet."""
    if quote is None:
        return line, "proxy", None, None, None
    open_line = float(quote.open_line)  # type: ignore[attr-defined]
    if pick is None:
        return open_line, "open", None, None, None
    price = quote.open_over_price if pick == "over" else quote.open_under_price  # type: ignore[attr-defined]
    clv_prob, clv_line = closing_line_value(quote, pick)  # type: ignore[arg-type]
    return open_line, "open", int(price), clv_prob, clv_line


def replay_league(
    service: object,
    league: str,
    proxies: list[str],
    *,
    eval_start: datetime | None = None,
    markets: list[tuple[str, str]] | None = None,
    threshold: float | None = None,
    min_games: int | None = None,
    players: set[str] | None = None,
    odds: OddsHistory | None = None,
    do_agent: bool = True,
    validate: int = 0,
    seed: int = 7,
    cutoff: datetime = NBA_REGULAR_SEASON_START,
) -> LeagueReplay:
    """Replay one league.

    Args:
        service: A ``CSVPlayerHistoryService``. The agent path requires the
            singleton ``tools.historical._csv_for(league)`` returns, because
            that is the cache the tools read.
        league: ``nba`` or ``wnba``.
        proxies: Proxy kinds to score on the daily path.
        eval_start: First eligible target date. Defaults to ``EVAL_START``.
        markets: ``(odds_key, metric)`` pairs. Defaults to
            ``daily_analysis.SUPPORTED_MARKETS``.
        threshold: Daily Picks probability floor. Defaults to
            ``HIGH_PROBABILITY_THRESHOLD``.
        min_games: Prior-game floor. Defaults to ``MIN_SAMPLE_GAMES``.
        players: If set, only these cache keys are replayed.
        odds: Opening and closing lines. Inactive histories are ignored.
        do_agent: Also run ``compute_scorecard`` on the prior-game view.
        validate: How many daily rows to check against ``get_player_stats``.
            Zero skips the check.
        seed: Reservoir-sample seed for that check.
        cutoff: Date used only for the exposure counts (games before the
            NBA regular season sitting inside a player's prior window).

    Returns:
        Daily rows, agent rows, target-date range, exposure counts, and
        the validation tally.
    """
    bootstrap()
    from app.services.csv_player_history import CONTINUOUS_METRIC_EXTRACTORS

    if markets is None or threshold is None or min_games is None:
        from app.services.daily_analysis import (
            HIGH_PROBABILITY_THRESHOLD,
            MIN_SAMPLE_GAMES,
            SUPPORTED_MARKETS,
        )

        markets = markets if markets is not None else list(SUPPORTED_MARKETS)
        threshold = HIGH_PROBABILITY_THRESHOLD if threshold is None else threshold
        min_games = MIN_SAMPLE_GAMES if min_games is None else min_games
    from app.services.daily_analysis import choose_daily_pick_side

    odds = odds if odds is not None else inactive_history()
    start = eval_start if eval_start is not None else EVAL_START[league]
    historical = None
    scorecard = None
    decide = None
    agent_min = min_games
    agent_kinds = agent_proxies_for(proxies)
    if do_agent:
        import tools.historical as historical_module
        from scoring import (
            MIN_SAMPLE_FOR_BET,
            compute_scorecard,
            decision_from_over_probability,
        )

        singleton = historical_module._csv_for(league)
        if service is not singleton:
            raise RuntimeError(
                "Agent replay reads tools.historical._csv_for(league). "
                "Pass that service so the prior-game window is the one the tools see."
            )
        historical = historical_module
        scorecard = compute_scorecard
        decide = decision_from_over_probability
        agent_min = MIN_SAMPLE_FOR_BET

    result = LeagueReplay(league=league)
    rng = random.Random(seed)
    seen_cases = 0
    cases: list[ValidationCase] = []
    exposure = {
        "targets": 0,
        "any_prior_before_cutoff": 0,
        "last_20_includes_pre_cutoff": 0,
        "prior_includes_duplicate_date": 0,
    }
    target_dates: list[str] = []
    cache = service._cache  # type: ignore[attr-defined]
    n_players = 0

    for player, logs in cache.items():
        if players is not None and player not in players:
            continue
        n_players += 1
        if n_players % 50 == 0:
            logger.info("%s: %s players replayed", league, n_players)
        active = _active_games(logs)
        dup_dates = {
            date
            for date, count in Counter(game["game_date"] for game in active).items()
            if count > 1
        }
        seen_dates: set[datetime] = set()
        for index, game in enumerate(active):
            game_date = game["game_date"]
            if game_date in seen_dates:
                # Same player-date twice. The second row is not a new game,
                # and it is not strictly before the first, so it is not a
                # target and it is not prior for that date. A later game
                # still sees both copies, because both are strictly before it.
                continue
            seen_dates.add(game_date)
            if game_date < start:
                continue
            prior = [
                earlier
                for earlier in active[:index]
                if earlier["game_date"] < game_date
            ]
            if len(prior) < min_games:
                continue
            prior_nf = prior[::-1]
            l10_min = float(np.mean([earlier["minutes"] for earlier in prior_nf[:10]]))
            date_text = game_date.strftime("%Y-%m-%d")
            exposure["targets"] += 1
            target_dates.append(date_text)
            if any(earlier["game_date"] < cutoff for earlier in prior):
                exposure["any_prior_before_cutoff"] += 1
            if any(earlier["game_date"] < cutoff for earlier in prior_nf[:20]):
                exposure["last_20_includes_pre_cutoff"] += 1
            if any(earlier["game_date"] in dup_dates for earlier in prior):
                exposure["prior_includes_duplicate_date"] += 1

            for _odds_key, metric in markets:
                extractor = CONTINUOUS_METRIC_EXTRACTORS[metric]
                actual = extractor(game)
                if actual is None:
                    continue
                values = [
                    value
                    for value in (extractor(earlier) for earlier in prior_nf)
                    if value is not None
                ]
                if len(values) < min_games:
                    continue
                array = np.asarray(values, dtype=float)
                for kind in proxies:
                    raw_line = proxy_line(values, kind)
                    if raw_line is None:
                        continue
                    quote = (
                        odds.lookup(league, player, date_text, metric)
                        if odds.active
                        else None
                    )
                    # Rates are computed on the line that will actually be graded.
                    graded_line = (
                        float(quote.open_line) if quote is not None else raw_line
                    )
                    p_over, p_under, n_games = empirical_rates(array, graded_line)
                    side, _rounded = choose_daily_pick_side(p_over, p_under, threshold)
                    line, line_source, price, clv_prob, clv_line = _price_fields(
                        quote, side, graded_line
                    )
                    over_hit = int(actual > line)
                    hit = (
                        None
                        if side is None
                        else int(over_hit if side == "over" else actual < line)
                    )
                    prob = (
                        None
                        if side is None
                        else (p_over if side == "over" else p_under)
                    )
                    result.daily.append(
                        DailyRow(
                            league,
                            kind,
                            date_text,
                            metric,
                            line,
                            float(actual),
                            n_games,
                            l10_min,
                            p_over,
                            p_under,
                            over_hit,
                            side,
                            prob,
                            hit,
                            line_source,
                            price,
                            clv_prob,
                            clv_line,
                        )
                    )
                    if validate and line_source == "proxy" and kind == "L10":
                        seen_cases += 1
                        case = ValidationCase(
                            player, metric, line, p_over, p_under, n_games, prior_nf
                        )
                        if len(cases) < validate:
                            cases.append(case)
                        else:
                            slot = rng.randrange(seen_cases)
                            if slot < validate:
                                cases[slot] = case

            if (
                do_agent
                and historical is not None
                and scorecard is not None
                and decide is not None
            ):
                result.agent.extend(
                    _agent_rows(
                        historical,
                        scorecard,
                        decide,
                        service,
                        league,
                        player,
                        game,
                        date_text,
                        prior_nf,
                        l10_min,
                        agent_kinds,
                        agent_min,
                        odds,
                    )
                )

    result.targets = exposure["targets"]
    result.exposure = exposure
    if target_dates:
        result.target_start = min(target_dates)
        result.target_end = max(target_dates)
    result.validation = (
        _validate(league, cases)
        if validate
        else {"league": league, "checked": 0, "mismatches": 0}
    )
    return result


def _agent_rows(
    historical: object,
    scorecard,
    decide,
    service: object,
    league: str,
    player: str,
    game: dict,
    date_text: str,
    prior_nf: list[dict],
    l10_min: float,
    proxies: list[str],
    min_games: int,
    odds: OddsHistory,
) -> list[AgentRow]:
    rows: list[AgentRow] = []
    with _prior_games_only(service, player, prior_nf):
        shooting = historical.get_shooting_profile(player, league=league)  # type: ignore[attr-defined]
        schedule = historical.get_schedule_context(
            player, date=date_text, league=league
        )  # type: ignore[attr-defined]
        back_to_back = int(bool(schedule.get("details", {}).get("is_back_to_back")))
        for metric in AGENT_METRICS:
            actual = game.get(metric)
            values = [
                earlier[metric]
                for earlier in prior_nf
                if earlier.get(metric) is not None
            ]
            if actual is None or len(values) < min_games:
                continue
            trend = historical.get_trend_analysis(player, metric, league=league)  # type: ignore[attr-defined]
            variance = historical.get_variance_profile(player, metric, league=league)  # type: ignore[attr-defined]
            for kind in proxies:
                raw_line = proxy_line(values, kind)
                if raw_line is None:
                    continue
                quote = (
                    odds.lookup(league, player, date_text, metric)
                    if odds.active
                    else None
                )
                graded_line = float(quote.open_line) if quote is not None else raw_line
                base = historical.get_base_stats(
                    player, metric, graded_line, league=league
                )  # type: ignore[attr-defined]
                card = scorecard(
                    {
                        "get_base_stats": base,
                        "get_trend_analysis": trend,
                        "get_shooting_profile": shooting,
                        "get_variance_profile": variance,
                        "get_schedule_context": schedule,
                    },
                    {},
                    {},
                    direction="over",
                )
                # The returned probability is already rounded to 4 decimals.
                # The pre-gate side is read off that returned value, which is
                # what a caller of compute_scorecard can see. The market gate
                # has already rewritten `decision` to avoid.
                p_over = float(card["model_probability"])
                side = decide(p_over)
                pick = None if side == "avoid" else side
                line, line_source, price, clv_prob, clv_line = _price_fields(
                    quote, pick, graded_line
                )
                over_hit = int(actual > line)
                hit = (
                    None
                    if pick is None
                    else int(over_hit if pick == "over" else actual < line)
                )
                prob = (
                    None
                    if pick is None
                    else (p_over if pick == "over" else round(1.0 - p_over, 4))
                )
                rows.append(
                    AgentRow(
                        league,
                        kind,
                        date_text,
                        metric,
                        line,
                        float(actual),
                        l10_min,
                        p_over,
                        over_hit,
                        float(card["confidence"]),
                        str(card["decision"]),
                        bool(card["eligible_for_bet"]),
                        card.get("pass_reason"),
                        pick,
                        prob,
                        hit,
                        back_to_back,
                        line_source,
                        price,
                        clv_prob,
                        clv_line,
                    )
                )
    return rows


def _validate(league: str, cases: list[ValidationCase]) -> dict:
    """Compare replay rates with ``get_player_stats`` on a prior-only cache."""
    if not cases:
        return {"league": league, "checked": 0, "mismatches": 0}
    from app.services.csv_player_history import CSVPlayerHistoryService

    mismatches = 0
    for case in cases:
        service = CSVPlayerHistoryService(league)
        service._cache = {case.player: list(case.prior_nf)}
        service._all_players = [case.player]
        service._loaded = True
        got = service.get_player_stats(
            player_name=case.player,
            metric=case.metric,
            threshold=case.line,
            n=0,
            exclude_dnp=True,
        )
        if (got["p_over"], got["p_under"], got["n_games"]) != (
            case.p_over,
            case.p_under,
            case.n_games,
        ):
            mismatches += 1
            logger.error(
                "get_player_stats mismatch %s %s %s line=%s replay=%s real=%s",
                league,
                case.player,
                case.metric,
                case.line,
                (case.p_over, case.p_under, case.n_games),
                (got["p_over"], got["p_under"], got["n_games"]),
            )
    return {"league": league, "checked": len(cases), "mismatches": mismatches}


def inventory(service: object) -> dict:
    """Describe one league CSV the way the replay sees it.

    Counts come from the loaded cache, which is the production loader's
    view of the file (one row per kept player-game, season string included).
    """
    seasons: Counter[str] = Counter()
    month_before_cutoff: Counter[str] = Counter()
    duplicates: list[dict] = []
    multi_team = 0
    zero_minutes = 0
    rows = 0
    dates: list[datetime] = []
    cache = service._cache  # type: ignore[attr-defined]
    for player, games in cache.items():
        rows += len(games)
        teams: set[str] = set()
        seen: Counter[datetime] = Counter()
        for game in games:
            seasons[str(game.get("season") or "")] += 1
            game_date = game.get("game_date")
            if game_date is not None:
                dates.append(game_date)
                seen[game_date] += 1
                if game_date < NBA_REGULAR_SEASON_START:
                    month_before_cutoff[game_date.strftime("%Y-%m")] += 1
            if not game.get("minutes"):
                zero_minutes += 1
            if game.get("minutes", 0) > 0 and game.get("team"):
                teams.add(game["team"])
        if len(teams) > 1:
            multi_team += 1
        for game_date, copies in seen.items():
            if copies > 1:
                duplicates.append(
                    {
                        "player": player,
                        "date": game_date.strftime("%Y-%m-%d"),
                        "copies": copies,
                    }
                )
    return {
        "league": service.league,  # type: ignore[attr-defined]
        "rows": rows,
        "players": len(cache),
        "date_start": min(dates).strftime("%Y-%m-%d") if dates else None,
        "date_end": max(dates).strftime("%Y-%m-%d") if dates else None,
        "seasons": dict(seasons),
        "rows_before_nba_cutoff": sum(month_before_cutoff.values()),
        "before_cutoff_by_month": dict(sorted(month_before_cutoff.items())),
        "duplicates": duplicates,
        "multi_team_players": multi_team,
        "zero_minute_rows": zero_minutes,
    }


def load_historical():
    """Import the product-agent historical tools, which loads both CSVs."""
    bootstrap()
    import tools.historical as historical

    return historical
