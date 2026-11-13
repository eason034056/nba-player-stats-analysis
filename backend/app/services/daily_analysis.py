"""
daily_analysis.py - Daily High-Probability Player Analysis Service

This is the core module for automated analysis, responsible for:
1. Fetching all events for the day
2. Retrieving all player props (4 metrics) for each event
3. Calculating the mode of bookmaker lines as a threshold
4. Calculating over/under probabilities from historical CSV data
5. Filtering for high-value picks with probability > 65%

Main functions:
- run_daily_analysis(): Runs the full daily analysis
- analyze_single_event(): Analyzes a single event
- get_player_props_for_event(): Gets all player props for an event

Dependencies:
- odds_theoddsapi: Fetches sportsbook data
- csv_player_history: Calculates historical probabilities
- prob: Calculates mode
"""

import asyncio
import logging
import math
import re
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter, defaultdict

from pydantic import ValidationError

logger = logging.getLogger(__name__)

from app.services.odds_gateway import odds_gateway
from app.services.slate_date import nba_slate_date
from app.services.odds_theoddsapi import odds_provider
from app.services.odds_provider import OddsAPIError
from app.services.csv_player_history import (
    csv_player_service,
    team_on_event,
    wnba_csv_player_service,
)
from app.services.prob import (
    american_to_prob,
    calculate_mode_threshold,
    posted_american_odds,
)
from app.services.cache import cache_service
from app.settings import settings
from app.services.defense_ranks import defense_fields
from app.models.schemas import (
    AnalysisStats,
    DailyPick,
    DailyPicksResponse,
    EventsResponse,
    TopRead,
)
from app.services.nba_injuries import (
    NBA_INJURIES_CACHE_KEY,
    injury_snapshot_is_fresh,
    load_nba_pick_injuries,
    match_injury_entry,
    matched_injury_words,
)
from app.services.pick_signals import build_nba_signals, injury_blocks_combined


# ==================== League routing (SPO-35) ====================
#
# Single source of truth for "league key → external identifiers / runtime
# dependencies". Adding a new league later (e.g. NCAA) becomes a one-line
# addition here — daily_analysis is one function tree, not a fork
# (CLAUDE.md § Architectural guardrails: "Parameterize, don't fork").
#
# Tied tests:
#   - test_daily_analysis_league_routes_sport_key (NBA vs WNBA dispatch)
#   - test_daily_analysis_league_routes_csv_service
#   - test_daily_analysis_league_namespaces_cache_key

# The Odds API sport key per league — proven via curl evidence in
# docs/research/wnba-rollout/odds_api_wnba_markets.md §3.
_SPORT_KEY_BY_LEAGUE: Dict[str, str] = {
    "nba": "basketball_nba",
    "wnba": "basketball_wnba",
}

# CSV historical service singletons created in csv_player_history.py
# (one per league CSV file). Indirection keeps the league dispatch
# centralized rather than scattered through _analyze_single_event.
_CSV_SERVICE_BY_LEAGUE: Dict[str, Any] = {
    "nba": csv_player_service,
    "wnba": wnba_csv_player_service,
}

def _resolve_sport_key(league: str) -> str:
    """Look up The Odds API sport key for a league, raising on unknown."""
    sport_key = _SPORT_KEY_BY_LEAGUE.get(league.lower())
    if sport_key is None:
        raise ValueError(
            f"Unsupported league: {league!r}. "
            f"Registered: {sorted(_SPORT_KEY_BY_LEAGUE.keys())}"
        )
    return sport_key


def _resolve_csv_service(league: str):
    """Return the CSV history service for the given league."""
    service = _CSV_SERVICE_BY_LEAGUE.get(league.lower())
    if service is None:
        raise ValueError(
            f"Unsupported league: {league!r}. "
            f"Registered: {sorted(_CSV_SERVICE_BY_LEAGUE.keys())}"
        )
    return service


# Supported market types (metrics)
# Corresponds to The Odds API market keys (left) and CSV metric keys (right).
# The CSV metric key is what `csv_player_service.get_player_stats(metric=...)`
# accepts — see `csv_player_history.get_player_stats` docstring.
#
# Phase 1 expansion (SPO-10, decision §Addendum 1) — adds 7 single/combo
# Over/Under markets on top of the original 4. The DD binary market is in
# `BINARY_MARKETS` below (separate parser path) so this list stays usable as
# "all the markets that follow the standard Over/Under flow".
SUPPORTED_MARKETS = [
    # Original 4
    ("player_points", "points"),
    ("player_rebounds", "rebounds"),
    ("player_assists", "assists"),
    ("player_points_rebounds_assists", "pra"),
    # Single Over/Under (new in SPO-16)
    ("player_threes", "threes_made"),
    ("player_steals", "steals"),
    # Tier B graceful-degrade (schema-valid + currently empty inventory).
    # Adding to SUPPORTED_MARKETS is safe: the API call still works and costs
    # 0 units while empty; when bookmakers eventually post, the tile lights up
    # automatically without any code change.
    ("player_frees_made", "ftm"),
    ("player_field_goals", "fgm"),  # working hypothesis: FGM (made), per Override 3
    # Native combo Over/Under (no derive math — the bookmaker posts the line)
    ("player_rebounds_assists", "ra"),
    ("player_points_rebounds", "pr"),
    ("player_points_assists", "pa"),
]

# Binary Yes/No markets handled via the DD parser path (see §4 of decision log).
# Listed separately because the standard Over/Under flow in
# `_analyze_single_event` would silently drop them (no `point` field).
# DailyAnalysis Phase 1 leaves DD analysis to the historical-only pipeline —
# no edge-vs-line picks because there's no projection (Phase 2).
BINARY_MARKETS = [
    ("player_double_double", "dd"),
]

# CSV metric key -> Odds API market key. DailyPick.metric stores the CSV
# key. top_read.market and the no-vig request use the Odds API key.
_METRIC_TO_MARKET_KEY: Dict[str, str] = {
    metric: market for market, metric in (*SUPPORTED_MARKETS, *BINARY_MARKETS)
}


def market_key_for_metric(metric: str | None) -> str | None:
    """Return the Odds API market key for a daily-pick metric.

    ``points`` becomes ``player_points``. A missing or unknown metric
    returns None. Callers skip that pick instead of emitting ``market: ""``.

    Args:
        metric: CSV / DailyPick metric key, or None.

    Returns:
        Odds API market key when the metric is in the supported map.
        None when it is missing or not a market we can name.
    """
    if not isinstance(metric, str) or not metric:
        return None
    return _METRIC_TO_MARKET_KEY.get(metric)


# High probability threshold
HIGH_PROBABILITY_THRESHOLD = 0.65

# Minimum non-DNP games before a historical rate can become a pick.
# The walk-forward harness imports this so it gates on the same sample size.
# The NBA daily-picks query uses this as its default, not as the storage floor.
MIN_SAMPLE_GAMES = 10

# Read tiers for a stored pick. Same numeric cutoffs as frontend/lib/today-board.ts
# readTier on Frontend PR #39 (strong 0.70, playable 0.65, lean 0.56).
# Backend labels are "Strong play" / "Playable" / "Lean". Below 0.56 and
# non-finite values are null. Highest cutoff is first; read_tier stops at
# the first match.
# See docs/decisions/spo-111-read-data/decision_20261110_read-tier-cutoffs.md.
READ_TIER_CUTOFFS: tuple[tuple[str, float], ...] = (
    ("Strong play", 0.70),
    ("Playable", 0.65),
    ("Lean", 0.56),
)

# NBA candidate storage stops at the Lean cutoff. The published board is
# still HIGH_PROBABILITY_THRESHOLD, applied when the query is served.
LEAN_PROBABILITY_FLOOR = READ_TIER_CUTOFFS[-1][1]

# Lowest sample the NBA daily-picks query accepts (Query ge=5). Default NBA
# storage keeps rows down to this count. The default query still asks for
# MIN_SAMPLE_GAMES, so those shorter rows stay off the default board.
STORED_MIN_SAMPLE_GAMES = 5


def read_tier(probability: float | None) -> str | None:
    """Map a probability onto a read tier.

    NBA passes ``combined_probability``. WNBA passes the historical
    rate, because a WNBA pick has no combined probability. The cutoffs
    are the same either way.

    Args:
        probability: The probability the tier is based on, or None.

    Returns:
        ``"Strong play"`` when probability >= 0.70, ``"Playable"`` when
        probability >= 0.65, ``"Lean"`` when probability >= 0.56, or None
        below that cutoff, when probability is missing, and when it is
        not finite (NaN or Infinity).
    """
    if probability is None:
        return None
    if isinstance(probability, bool) or not isinstance(probability, (int, float)):
        return None
    if not math.isfinite(probability):
        return None
    for name, cutoff in READ_TIER_CUTOFFS:
        if probability >= cutoff:
            return name
    return None


def choose_daily_pick_side(
    p_over: float | None,
    p_under: float | None,
    threshold: float = HIGH_PROBABILITY_THRESHOLD,
) -> tuple[str | None, float | None]:
    """Choose the Daily Picks side from empirical over/under rates.

    OVER wins when both rates clear `threshold`. That is the order in
    `_analyze_single_event`: a player who is extreme on both sides of a
    line is published as an over, not an under.

    Args:
        p_over: Share of prior games strictly above the line, or None.
        p_under: Share of prior games strictly below the line, or None.
        threshold: Minimum rate. Defaults to `HIGH_PROBABILITY_THRESHOLD`.

    Returns:
        `("over", rate)` or `("under", rate)` when a side clears the
        threshold. The rate is rounded to 4 decimals, which is what
        `DailyPick.probability` stores. `(None, None)` when neither side
        clears the threshold.
    """
    if p_over is not None and p_over >= threshold:
        return "over", round(p_over, 4)
    if p_under is not None and p_under >= threshold:
        return "under", round(p_under, 4)
    return None, None


# Cache key prefix
DAILY_PICKS_CACHE_KEY = "daily_picks"

# NBA payloads from before injury_status_raw live under the unversioned
# key. Readers and writers use v2 only. WNBA stays unversioned.
NBA_DAILY_PICKS_CACHE_VERSION = "v2"

# Cache TTL (15 minutes)
DAILY_PICKS_CACHE_TTL = 15 * 60


def daily_picks_cache_key(league: str, date: str, tz_offset_minutes: int) -> str:
    """Redis key for one league, local date, and timezone offset.

    NBA keys include ``v2`` so a payload stored before
    ``injury_status_raw`` is not read. WNBA keys stay
    ``daily_picks:wnba:{date}:tz{offset}``.

    Args:
        league: ``nba`` or ``wnba``.
        date: Local date YYYY-MM-DD.
        tz_offset_minutes: Minutes east of UTC. UTC+8 is 480.

    Returns:
        ``daily_picks:nba:v2:{date}:tz{offset}`` or the unversioned WNBA key.
    """
    league_key = league.lower()
    if league_key == "nba":
        return (
            f"{DAILY_PICKS_CACHE_KEY}:nba:{NBA_DAILY_PICKS_CACHE_VERSION}:"
            f"{date}:tz{tz_offset_minutes}"
        )
    return f"{DAILY_PICKS_CACHE_KEY}:{league_key}:{date}:tz{tz_offset_minutes}"


def _optional_stat(value: Any) -> float | None:
    """A finite stat, or None. Used for fields a test double may omit."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def board_score(pick: DailyPick, league: str = "nba") -> float | None:
    """Probability the daily-picks floor is applied to.

    NBA uses ``combined_probability``. A missing or non-finite combined
    score does not fall back to the historical rate, so that row leaves
    the board. WNBA has no combined probability and keeps the historical
    rate.

    Args:
        pick: One stored pick.
        league: ``nba`` or ``wnba``. Anything else uses the NBA score.

    Returns:
        A finite probability, or None when the score cannot be used.
    """
    raw = pick.probability if league.lower() == "wnba" else pick.combined_probability
    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    number = float(raw)
    if not math.isfinite(number):
        return None
    return number


def sort_stored_picks(picks: List[DailyPick], league: str = "nba") -> None:
    """Order a stored list by the score that board uses.

    NBA orders by ``combined_probability``. WNBA orders by the historical
    rate. A missing or non-finite score sorts last, so a row that cannot
    reach the board does not sit above one that can. Equal scores keep
    the order analysis produced them in.

    ``best_top_reads`` still picks the highest historical probability.
    On a tie it keeps the earlier row of this list, so an NBA tie keeps
    the higher blend. A fresh injury snapshot skips a player whose
    normalized status is Out. A missing or stale snapshot does not.

    Args:
        picks: Stored candidates. Sorted in place.
        league: ``nba`` or ``wnba``. Passed to ``board_score``.
    """

    def key(pick: DailyPick) -> tuple[bool, float]:
        score = board_score(pick, league)
        if score is None:
            return (False, 0.0)
        return (True, score)

    picks.sort(key=key, reverse=True)


def select_daily_picks(
    picks: List[DailyPick],
    min_probability: float = HIGH_PROBABILITY_THRESHOLD,
    min_games: int = MIN_SAMPLE_GAMES,
    *,
    league: str = "nba",
) -> List[DailyPick]:
    """Keep picks that clear the query floors.

    The stored list can include Lean rows and short NBA samples. This is
    the filter the NBA daily-picks route applies. Defaults are the
    published board: combined probability 0.65 and 10 games. WNBA passes
    ``league="wnba"`` and is filtered on the historical rate instead.

    Args:
        picks: Stored picks. An NBA list is ordered by combined
            probability (``board_score``). A WNBA list is ordered by the
            historical rate.
        min_probability: Inclusive floor on ``board_score``.
        min_games: Inclusive sample floor.
        league: ``nba`` (combined probability) or ``wnba`` (historical).

    Returns:
        Picks that meet both floors, in the original order. An NBA row
        whose ``injury_status`` is Out is kept when the sample floor
        passes, even though its blend is null. Doubtful is Questionable
        and uses the blend floor.
    """
    kept: List[DailyPick] = []
    for pick in picks:
        if pick.n_games < min_games:
            continue
        # Out stays on the board with a null blend so injury_status is
        # visible. A missing blend that is not Out still leaves the
        # board. Doubtful is stored as Questionable and follows its
        # blend, the same as any other Questionable row.
        if league.lower() != "wnba" and injury_blocks_combined(pick.injury_status):
            kept.append(pick)
            continue
        score = board_score(pick, league)
        if score is not None and score >= min_probability:
            kept.append(pick)
    return kept


def present_daily_picks(
    result: DailyPicksResponse,
    min_probability: float = HIGH_PROBABILITY_THRESHOLD,
    min_games: int = MIN_SAMPLE_GAMES,
    *,
    league: str = "nba",
) -> DailyPicksResponse:
    """Return a copy of ``result`` whose picks match the query floors.

    ``stats.high_prob_count`` stays the published-board count written at
    analysis time. ``total_picks`` becomes the filtered length. The stored
    object is not mutated, so a later lower ``min_probability`` still sees
    the rows that were cached. NBA compares ``combined_probability``.

    Args:
        result: Stored analysis, including candidates below the board.
        min_probability: Inclusive floor on ``board_score``.
        min_games: Inclusive sample floor.
        league: Passed through to ``select_daily_picks``.

    Returns:
        Response the route can send.
    """
    filtered = select_daily_picks(
        result.picks, min_probability, min_games, league=league
    )
    return result.model_copy(update={"picks": filtered, "total_picks": len(filtered)})

TEAM_CODE_ALIASES: Dict[str, str] = {
    "ATL": "ATL",
    "ATLANTAHAWKS": "ATL",
    "HAWKS": "ATL",
    "BOS": "BOS",
    "BOSTONCELTICS": "BOS",
    "CELTICS": "BOS",
    "BKN": "BKN",
    "BROOKLYNNETS": "BKN",
    "NETS": "BKN",
    "CHA": "CHA",
    "CHARLOTTEHORNETS": "CHA",
    "HORNETS": "CHA",
    "CHI": "CHI",
    "CHICAGOBULLS": "CHI",
    "BULLS": "CHI",
    "CLE": "CLE",
    "CLEVELANDCAVALIERS": "CLE",
    "CAVALIERS": "CLE",
    "DAL": "DAL",
    "DALLASMAVERICKS": "DAL",
    "MAVERICKS": "DAL",
    "DEN": "DEN",
    "DENVERNUGGETS": "DEN",
    "NUGGETS": "DEN",
    "DET": "DET",
    "DETROITPISTONS": "DET",
    "PISTONS": "DET",
    "GS": "GSW",
    "GSW": "GSW",
    "GOLDENSTATEWARRIORS": "GSW",
    "WARRIORS": "GSW",
    "HOU": "HOU",
    "HOUSTONROCKETS": "HOU",
    "ROCKETS": "HOU",
    "IND": "IND",
    "INDIANAPACERS": "IND",
    "PACERS": "IND",
    "LAC": "LAC",
    "LOSANGELESCLIPPERS": "LAC",
    "LACLIPPERS": "LAC",
    "CLIPPERS": "LAC",
    "LAL": "LAL",
    "LOSANGELESLAKERS": "LAL",
    "LALAKERS": "LAL",
    "LAKERS": "LAL",
    "MEM": "MEM",
    "MEMPHISGRIZZLIES": "MEM",
    "GRIZZLIES": "MEM",
    "MIA": "MIA",
    "MIAMIHEAT": "MIA",
    "HEAT": "MIA",
    "MIL": "MIL",
    "MILWAUKEEBUCKS": "MIL",
    "BUCKS": "MIL",
    "MIN": "MIN",
    "MINNESOTATIMBERWOLVES": "MIN",
    "TIMBERWOLVES": "MIN",
    "NO": "NOP",
    "NOP": "NOP",
    "NEWORLEANSPELICANS": "NOP",
    "PELICANS": "NOP",
    "NY": "NYK",
    "NYK": "NYK",
    "NEWYORKKNICKS": "NYK",
    "KNICKS": "NYK",
    "OKC": "OKC",
    "OKLAHOMACITYTHUNDER": "OKC",
    "THUNDER": "OKC",
    "ORL": "ORL",
    "ORLANDOMAGIC": "ORL",
    "MAGIC": "ORL",
    "PHI": "PHI",
    "PHILADELPHIA76ERS": "PHI",
    "76ERS": "PHI",
    "SIXERS": "PHI",
    "PHO": "PHX",
    "PHX": "PHX",
    "PHOENIXSUNS": "PHX",
    "SUNS": "PHX",
    "POR": "POR",
    "PORTLANDTRAILBLAZERS": "POR",
    "TRAILBLAZERS": "POR",
    "SAC": "SAC",
    "SACRAMENTOKINGS": "SAC",
    "KINGS": "SAC",
    "SA": "SAS",
    "SAS": "SAS",
    "SANANTONIOSPURS": "SAS",
    "SPURS": "SAS",
    "TOR": "TOR",
    "TORONTORAPTORS": "TOR",
    "RAPTORS": "TOR",
    "UTA": "UTA",
    "UTAH": "UTA",
    "UTAHJAZZ": "UTA",
    "JAZZ": "UTA",
    "WAS": "WAS",
    "WSH": "WAS",
    "WASHINGTONWIZARDS": "WAS",
    "WIZARDS": "WAS",
}


def canonical_team_code(team_name: str, league: str = "nba") -> str:
    """Map a team name to its league's code.

    ``league`` defaults to ``"nba"`` so existing callers keep the NBA
    alias table. WNBA callers pass ``league="wnba"``. Lynx and Wings
    are not NBA aliases, so they stay unresolved on the default path
    and resolve to MIN and DAL only for WNBA. An unknown league raises
    rather than borrowing the other table.
    """
    if not team_name:
        return ""

    league_key = (league or "nba").strip().lower()
    if league_key == "wnba":
        from app.services.lineup_source_support import detect_team_code

        code = detect_team_code(team_name, league="wnba")
        if code:
            return code
    elif league_key != "nba":
        raise ValueError(f"Unknown league for team code: {league!r}")

    normalized = re.sub(r"[^A-Z0-9]", "", team_name.upper())
    if league_key == "wnba":
        return normalized
    return TEAM_CODE_ALIASES.get(normalized, normalized)


def _empty_rank_fields() -> Dict[str, Any]:
    """Null defense-rank fields. Used when the fill does not run."""
    return {
        "opponent_rank": None,
        "opponent_position_rank": None,
        "opponent_rank_source": None,
        "opponent_position_rank_source": None,
        "opponent_rank_season": None,
        "opponent_position_rank_season": None,
        "opponent_rank_note": None,
        "opponent_position_rank_note": None,
    }


def _opponent_club(
    player_team: str,
    home_team: str,
    away_team: str,
    league: str,
) -> str | None:
    """The other club in the event when ``player_team`` is one of the two.

    Args:
        player_team: Club label already limited to a team in this game.
        home_team: Event home name.
        away_team: Event away name.
        league: ``nba`` or ``wnba``. The code table depends on it.

    Returns:
        The opponent name from the event, or None when the player's club
        is blank or is not home and not away.
    """
    player_code = canonical_team_code(player_team, league=league)
    if not player_code:
        return None
    if player_code == canonical_team_code(home_team, league=league) and away_team:
        return away_team
    if player_code == canonical_team_code(away_team, league=league) and home_team:
        return home_team
    return None


def _book_id(bookmaker: Dict[str, Any], index: int) -> str:
    """Id of one bookmaker entry in an Odds API ``bookmakers`` array.

    ``key`` is the id The Odds API sends (``draftkings``, ``bovada``).
    ``title`` is the fallback. An entry with neither still counts as its
    own book: two blank rows are not merged into one.

    Args:
        bookmaker: One object from the ``bookmakers`` array.
        index: Position of that object. Used only when key and title
            are both missing.

    Returns:
        A non-empty string. Two calls with the same ``key`` return the
        same string, which is how one book is counted once.
    """
    key = bookmaker.get("key") or bookmaker.get("title")
    if isinstance(key, str) and key.strip():
        return key.strip()
    return f"#{index}"


def _even_money_distance(over: float | None, under: float | None) -> float:
    """How far a rung sits from a coin flip. Lower is the main line.

    A two-sided rung uses the vig-free Over,
    ``p_over / (p_over + p_under)``. Over -110 and Under -110 score 0,
    because the book's margin is removed before the comparison.
    A one-sided rung uses the raw implied probability of the posted
    side. Callers only score a one-sided rung when that book posted
    no two-sided rung.

    Args:
        over: American price of Over, or None when that side is absent.
        under: American price of Under, or None when that side is absent.

    Returns:
        Absolute distance from 0.5. ``1.0`` when there is no usable price.
    """
    if over is not None and under is not None:
        p_over = american_to_prob(over)
        p_under = american_to_prob(under)
        total = p_over + p_under
        if total <= 0:
            return 1.0
        return abs((p_over / total) - 0.5)
    price = over if over is not None else under
    if price is None:
        return 1.0
    return abs(american_to_prob(price) - 0.5)


def _posted_point(points: list[float]) -> float:
    """One posted point when the book did not send prices.

    The mode of ``points``, rounded to one decimal (the same rounding
    ``calculate_mode_threshold`` uses). A tie returns a number that is
    in ``points``: the middle tied value, or the lower of the two
    central tied values when the tie count is even. Over 24.5 and
    Under 25.5 therefore stay on 24.5. They are not averaged into 25.0,
    which nobody posted.

    Args:
        points: Line values from one book for one player. At least one.

    Returns:
        One of the rounded posted points.
    """
    rounded = [round(point, 1) for point in points]
    counts = Counter(rounded)
    most = max(counts.values())
    modes = sorted(value for value, count in counts.items() if count == most)
    if len(modes) % 2 == 1:
        return float(modes[len(modes) // 2])
    return float(modes[(len(modes) // 2) - 1])


def _main_line_vote(outcomes: list[dict[str, Any]]) -> tuple[float, float] | None:
    """The main line and how far that rung sits from even money.

    The point is the same one ``_main_book_line`` returns. The distance is
    ``_even_money_distance`` of that rung, so a cross-book tie can prefer
    the vote closest to a coin flip. When the book posted no usable price,
    the distance is ``1.0``, which is farther than any priced rung. The
    point in that case is still ``_posted_point``.

    Args:
        outcomes: Outcome objects for one player from one book and one
            market.

    Returns:
        ``(point, distance)``, or None when no outcome has a numeric point.
    """
    rungs: dict[float, dict[str, float | None]] = {}
    bare_points: list[float] = []
    for outcome in outcomes:
        raw_point = outcome.get("point")
        if raw_point is None:
            continue
        try:
            point = round(float(raw_point), 1)
        except (TypeError, ValueError):
            continue
        bare_points.append(point)
        side = str(outcome.get("name") or "").strip().lower()
        price = posted_american_odds(outcome.get("price"))
        rung = rungs.setdefault(point, {"over": None, "under": None})
        if side in ("over", "under") and price is not None:
            previous = rung[side]
            if (
                previous is None
                or _even_money_distance(price, None)
                < _even_money_distance(previous, None)
            ):
                rung[side] = price

    if not bare_points:
        return None

    two_sided = [
        point
        for point, rung in rungs.items()
        if rung["over"] is not None and rung["under"] is not None
    ]
    priced = [
        point
        for point, rung in rungs.items()
        if rung["over"] is not None or rung["under"] is not None
    ]
    candidates = two_sided or priced
    if not candidates:
        return _posted_point(bare_points), 1.0

    def _sort_key(point: float) -> tuple[float, float]:
        rung = rungs[point]
        return (_even_money_distance(rung["over"], rung["under"]), point)

    chosen = min(candidates, key=_sort_key)
    return float(chosen), float(_sort_key(chosen)[0])


def _main_book_line(outcomes: list[dict[str, Any]]) -> float | None:
    """The one line a book votes with for one player on one market.

    Each distinct ``point`` is a rung. Over and Under at that point are
    the two sides of the rung, not two lines. Use this when reducing a
    book's outcomes to the single float that ``_group_props_by_player``
    appends.

    Choice, in order:

    1. A two-sided rung beats a one-sided rung. The main line is a
       number the book will take on both sides.
    2. Among those rungs, the one closest to a coin flip
       (``_even_money_distance``) is the main line. The other rungs are
       alternates. They do not get their own vote, so one book's ladder
       cannot outvote the rest of the market.
    3. An equal distance keeps the lower posted point.
    4. With no usable prices, ``_posted_point`` returns a posted number.
       It does not average two different points.

    Args:
        outcomes: Outcome objects for one player from one book and one
            market. ``point`` is the line. ``name`` is ``Over`` or
            ``Under``. ``price`` is American odds.

    Returns:
        The main line rounded to one decimal, or None when no outcome
        has a numeric ``point``.
    """
    vote = _main_line_vote(outcomes)
    if vote is None:
        return None
    return vote[0]


class DailyAnalysisService:
    """
    Daily Analysis Service

    Responsible for executing the full high-probability player analysis pipeline.

    Usage:
        service = DailyAnalysisService()
        result = await service.run_daily_analysis()

    Analysis flow:
    1. Fetch today's NBA events
    2. For each event, get all player props for the four metrics
    3. For each player-metric pair:
       a. Gather all bookmaker lines
       b. Calculate mode as threshold
       c. Query CSV historical data for probabilities
    4. Filter for p_over > 0.65 or p_under > 0.65 results
    5. Return picks sorted by probability
    """

    def __init__(self, probability_threshold: float | None = None):
        """
        Initialize the analysis service.

        Args:
            probability_threshold: When set, this cutoff is the only storage
                gate and the sample floor stays ``MIN_SAMPLE_GAMES``. When
                omitted, NBA storage uses the Lean floor and
                ``STORED_MIN_SAMPLE_GAMES``. WNBA stays on 0.65 and 10 games
                either way. The default HTTP query, not this constructor, is
                what the published board shows.
        """
        if probability_threshold is None:
            self.probability_threshold = HIGH_PROBABILITY_THRESHOLD
            self._explicit_probability_threshold = False
        else:
            self.probability_threshold = probability_threshold
            self._explicit_probability_threshold = True
        self.csv_service = csv_player_service

    def _candidate_min_games(self, league: str) -> int:
        """Sample floor for a row that can be stored.

        The default NBA service stores down to ``STORED_MIN_SAMPLE_GAMES``
        so the query's ``min_games`` can go below 10. WNBA, and a service
        constructed with an explicit probability threshold, keep
        ``MIN_SAMPLE_GAMES``.

        Args:
            league: ``nba`` or ``wnba``.

        Returns:
            Inclusive minimum ``n_games``.
        """
        if league.lower() == "nba" and not self._explicit_probability_threshold:
            return STORED_MIN_SAMPLE_GAMES
        return MIN_SAMPLE_GAMES

    def _choose_stored_side(
        self,
        p_over: float | None,
        p_under: float | None,
        league: str,
    ) -> tuple[str | None, float | None]:
        """Choose the side written onto a stored pick.

        The published side is chosen at ``HIGH_PROBABILITY_THRESHOLD``.
        Over wins when both sides clear that bar. The default NBA service
        tries the Lean floor only after that first choice misses. Trying
        Lean first would store a 0.57 over and drop a 0.90 under, and the
        default query would then lose the under. WNBA and an explicit
        threshold use one cutoff only.

        Args:
            p_over: Share of prior games strictly above the line.
            p_under: Share of prior games strictly below the line.
            league: ``nba`` or ``wnba``.

        Returns:
            ``("over"|"under", rate)`` or ``(None, None)``.
        """
        if league.lower() != "nba" or self._explicit_probability_threshold:
            return choose_daily_pick_side(
                p_over, p_under, self.probability_threshold
            )
        side, probability = choose_daily_pick_side(
            p_over,
            p_under,
            HIGH_PROBABILITY_THRESHOLD,
        )
        if side is not None:
            return side, probability
        return choose_daily_pick_side(p_over, p_under, LEAN_PROBABILITY_FLOOR)

    async def run_daily_analysis(
        self,
        date: Optional[str] = None,
        use_cache: bool = True,
        tz_offset_minutes: int = 480,
        league: str = "nba",
    ) -> DailyPicksResponse:
        """
        Run the full daily analysis

        This is the main entry point, performing the following steps:
        1. Check cache (if enabled)
        2. Fetch all events for the day
        3. Analyze each event
        4. Filter for high probability results
        5. Store in cache and return

        Args:
            date: Analysis date (YYYY-MM-DD). None means the America/New_York slate date.
            use_cache: Whether to use cache, default True
            tz_offset_minutes: Timezone offset in minutes, default 480 (UTC+8, Taipei)
            league: League key — ``"nba"`` (default) or ``"wnba"``. Controls
                    The Odds API ``sport_key`` (``basketball_nba`` vs
                    ``basketball_wnba``), which CSV history service is used
                    for probability lookup, and the Redis cache namespace.
                    Default ``"nba"`` preserves existing callers unchanged.
                    Raises ``ValueError`` on an unknown league.

        Returns:
            DailyPicksResponse: Contains all high-probability player picks

        Example:
            >>> service = DailyAnalysisService()
            >>> result = await service.run_daily_analysis()
            >>> print(f"Found {result.total_picks} high-probability picks")
            >>> wnba_result = await service.run_daily_analysis(league="wnba")
        """
        start_time = time.time()

        # Validate the league up front so an invalid value fails fast,
        # before we hit the cache or the network.
        league_normalized = league.lower()
        _resolve_sport_key(league_normalized)

        # US slate date. UTC midnight is still the previous evening in New York.
        if date is None:
            date = nba_slate_date()[0]

        # 1. Check cache (league-namespaced + timezone-scoped, SPO-35)
        # Pre-SPO-35 keys lived under f"daily_picks:{date}:tz{tz}" and would
        # have produced cross-league collisions once WNBA shipped. They roll
        # off naturally within 15 min (DAILY_PICKS_CACHE_TTL).
        if use_cache:
            cache_key = daily_picks_cache_key(
                league_normalized, date, tz_offset_minutes
            )
            cached_data = await cache_service.get(cache_key)
            if cached_data:
                try:
                    cached = DailyPicksResponse.model_validate(cached_data)
                except ValidationError:
                    print(
                        f"⚠️ [{league_normalized.upper()}] Ignoring unreadable "
                        f"daily-picks cache for {date}"
                    )
                else:
                    print(
                        f"✅ [{league_normalized.upper()}] Using cached analysis result: "
                        f"{date} (tz={tz_offset_minutes})"
                    )
                    return cached

        # After the cache read, before any Odds API call or Redis write.
        # A stored board is returned above. A miss becomes an empty board
        # and is not stored. NBA never enters this branch.
        if league_normalized == "wnba" and not settings.wnba_jobs_enabled:
            logger.info(
                "WNBA_JOBS_ENABLED is false; daily analysis skipped for %s",
                date,
            )
            return DailyPicksResponse(
                date=date,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                total_picks=0,
                picks=[],
                stats=None,
                message="WNBA jobs are paused (WNBA_JOBS_ENABLED=false)",
            )

        print(f"🚀 [{league_normalized.upper()}] Starting daily analysis: {date}")

        # 2. Get all events for the day
        try:
            events = await self._get_events_for_date(
                date, tz_offset_minutes, league=league_normalized
            )
        except Exception as e:
            print(f"❌ [{league_normalized.upper()}] Failed to fetch events: {e}")
            return DailyPicksResponse(
                date=date,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                total_picks=0,
                picks=[],
                stats=None,
                message=f"Failed to fetch events: {str(e)}"
            )

        if not events:
            print(f"⚠️ [{league_normalized.upper()}] No events today: {date}")
            return DailyPicksResponse(
                date=date,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                total_picks=0,
                picks=[],
                stats=None,
                message="No events today"
            )

        print(f"📅 [{league_normalized.upper()}] Found {len(events)} events")

        # NBA injury rows come from Redis. A miss, a stale body, or a
        # read error logs once inside the loader and leaves every
        # injury_status null. This does not call BALLDONTLIE, and a
        # failure here must not abort the board. WNBA does not read it.
        injury_entries: list[dict[str, Any]] | None = None
        if league_normalized == "nba":
            try:
                injury_entries = await load_nba_pick_injuries(cache=cache_service)
            except Exception as exc:
                logger.warning(
                    "NBA pick injury read failed (%s); injury_status left null",
                    type(exc).__name__,
                )
                injury_entries = None

        # 3. Analyze all events
        all_picks: List[DailyPick] = []
        total_players = 0
        total_props = 0

        for event in events:
            event_id = event.get("id", "")
            home_team = event.get("home_team", "")
            away_team = event.get("away_team", "")
            commence_time = event.get("commence_time", "")

            print(f"\n🏀 [{league_normalized.upper()}] Analyzing event: {away_team} @ {home_team}")

            try:
                event_picks, players_count, props_count = await self._analyze_single_event(
                    event_id=event_id,
                    home_team=home_team,
                    away_team=away_team,
                    commence_time=commence_time,
                    league=league_normalized,
                    injury_entries=injury_entries,
                )
                all_picks.extend(event_picks)
                total_players += players_count
                total_props += props_count
            except Exception as e:
                print(f"⚠️ Failed to analyze event {event_id}: {e}")
                continue

        # 4. Order the stored list by the score the board uses.
        # NBA: combined_probability. WNBA: the historical rate. A missing
        # score sorts last. Equal scores keep analysis order.
        sort_stored_picks(all_picks, league_normalized)

        # 5. Calculate statistics. high_prob_count stays the published
        # board (0.65 and 10 games) even when NBA storage also kept Lean
        # rows and shorter samples. NBA scores that board on
        # combined_probability. WNBA scores it on the historical rate.
        # The default query then reports the same total_picks as this count.
        duration = time.time() - start_time
        published_count = len(
            select_daily_picks(all_picks, league=league_normalized)
        )
        stats = AnalysisStats(
            total_events=len(events),
            total_players=total_players,
            total_props=total_props,
            high_prob_count=published_count,
            analysis_duration_seconds=round(duration, 2)
        )

        # 6. Build response
        response = DailyPicksResponse(
            date=date,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_picks=len(all_picks),
            picks=all_picks,
            stats=stats,
            message=None
        )

        # 7. Store in cache (league + timezone scoped). Even when
        # use_cache=False (force-refresh), still write so the next GET
        # gets the latest analysis without re-triggering the work.
        # The cached list is the candidate set. GET applies the query floors.
        cache_key = daily_picks_cache_key(
            league_normalized, date, tz_offset_minutes
        )
        await cache_service.set(
            cache_key,
            response.model_dump(mode='json'),
            ttl=DAILY_PICKS_CACHE_TTL
        )

        print(
            f"\n✅ [{league_normalized.upper()}] Analysis complete! "
            f"Found {len(all_picks)} high-probability picks in {duration:.2f} sec"
        )

        return response

    async def _get_events_for_date(
        self,
        date: str,
        tz_offset_minutes: int = 480,
        league: str = "nba",
    ) -> List[Dict[str, Any]]:
        """
        Fetch all events for the specified date and league

        Takes timezone offset into account to fetch events for user-local date.

        Args:
            date: Date string (YYYY-MM-DD)
            tz_offset_minutes: Timezone offset in minutes, default 480 (UTC+8, Taipei)
                               Positive = east (like UTC+8 = 480)
                               Negative = west (like UTC-6 = -360)
            league: League key ("nba" / "wnba"). Default "nba" preserves
                    the pre-SPO-35 call shape; ``_resolve_sport_key``
                    maps to the correct The Odds API ``sport_key``.

        Returns:
            List of events
        """
        sport_key = _resolve_sport_key(league)

        # Parse date
        date_obj = datetime.strptime(date, "%Y-%m-%d")

        # Calculate user-local date range in UTC
        # Example: User at UTC+8 (Taipei) selects "2026-01-24"
        # Local 2026-01-24 00:00:00 = UTC 2026-01-23 16:00:00
        # Local 2026-01-24 23:59:59 = UTC 2026-01-24 15:59:59

        # Local time 00:00:00 to UTC
        local_start = datetime.combine(date_obj.date(), datetime.min.time())
        utc_start = local_start - timedelta(minutes=tz_offset_minutes)

        # Local time 23:59:59 to UTC
        from datetime import time as dt_time
        local_end = datetime.combine(date_obj.date(), dt_time(23, 59, 59))
        utc_end = local_end - timedelta(minutes=tz_offset_minutes)

        # Widen search range to cover edge cases
        date_from = utc_start - timedelta(hours=1)
        date_to = utc_end + timedelta(hours=1)

        print(
            f"📅 [{league.upper()}/{sport_key}] Query time range: "
            f"{date_from.isoformat()} ~ {date_to.isoformat()} (UTC)"
        )

        # Call Odds API
        raw_events = await odds_provider.get_events(
            sport=sport_key,
            regions="us",
            date_from=date_from,
            date_to=date_to
        )

        # Filter: Only return events within the user-local day
        filtered_events = []
        for event in raw_events:
            commence_time_str = event.get("commence_time", "")
            if commence_time_str:
                try:
                    # Parse UTC time (e.g. 2026-01-17T00:10:00Z)
                    commence_utc = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                    # Convert to user-local time
                    commence_local = commence_utc + timedelta(minutes=tz_offset_minutes)
                    # Get local date
                    commence_local_date = commence_local.strftime("%Y-%m-%d")

                    # Only return if local date matches user selection
                    if commence_local_date == date:
                        filtered_events.append(event)
                except ValueError as e:
                    print(f"⚠️ Failed to parse time {commence_time_str}: {e}")
                    continue

        print(f"📊 Found {len(raw_events)} events, filtered to {len(filtered_events)}")

        return filtered_events

    async def _analyze_single_event(
        self,
        event_id: str,
        home_team: str,
        away_team: str,
        commence_time: str,
        projections: Optional[Dict[str, Dict]] = None,
        league: str = "nba",
        injury_entries: list[dict[str, Any]] | None = None,
    ) -> Tuple[List[DailyPick], int, int]:
        """
        Analyze a single event

        For all players in the event, analyze probabilities for the
        supported metrics. There is no projection input. ``projected_value``,
        ``edge``, and ``projected_minutes`` stay null. NBA defense ranks
        come from the game log.

        Args:
            event_id: Event ID
            home_team: Home team
            away_team: Away team
            commence_time: Event start time
            projections: Ignored. Older callers passed a projection map.
                The betting line is not used in its place.
            league: League key — picks the CSV history service to query
                    (``csv_player_service`` for NBA,
                    ``wnba_csv_player_service`` for WNBA). The market
                    list ``SUPPORTED_MARKETS`` is shared today because
                    every entry in it is a hard-supported WNBA market
                    too (Phase 0 evidence in
                    ``docs/research/wnba-rollout/odds_api_wnba_markets.md``).

        Returns:
            Tuple[List[DailyPick], int, int]: (High probability picks, player count, prop count)
        """
        picks: List[DailyPick] = []
        all_players: set = set()
        total_props = 0
        # Older callers still pass this keyword. It is not a projection source.
        _ = projections

        # Resolve the league-specific CSV history service once per event.
        # For the NBA path we keep reading through `self.csv_service` so
        # existing tests that monkey-patch the instance attribute
        # (`service.csv_service = MagicMock()`) keep working without
        # tearing them all up — backward compat for a stable test suite.
        # For non-NBA leagues we resolve via the league registry, which
        # is also where future leagues plug in.
        csv_service = (
            self.csv_service
            if league.lower() == "nba"
            else _resolve_csv_service(league)
        )

        # Analyze each metric
        for market_key, metric_key in SUPPORTED_MARKETS:
            try:
                # Get all props for this market
                props_data = await self._get_props_for_market(
                    event_id, market_key, league=league
                )

                if not props_data:
                    continue

                # Group by player. Each vote is the book's main line and
                # that rung's distance from even money, so a tied mode can
                # prefer the sharper quote instead of averaging.
                player_votes = self._group_main_votes(props_data)

                for player_name, votes in player_votes.items():
                    lines = [line for line, _distance in votes]
                    distances = [distance for _line, distance in votes]
                    all_players.add(player_name)
                    total_props += 1

                    mode_threshold = calculate_mode_threshold(lines, distances)

                    if mode_threshold is None:
                        continue

                    # Historical probability from CSV (per-league service)
                    history_stats = csv_service.get_player_stats(
                        player_name=player_name,
                        metric=metric_key,
                        threshold=mode_threshold,
                        n=0,  # Use all historical data
                        exclude_dnp=True
                    )

                    # Check for valid probability data
                    p_over = history_stats.get("p_over")
                    p_under = history_stats.get("p_under")
                    n_games = history_stats.get("n_games", 0)

                    # Published board stays at MIN_SAMPLE_GAMES via the query.
                    # Default NBA storage keeps a shorter sample so min_games
                    # can ask for it. WNBA stays at MIN_SAMPLE_GAMES.
                    if n_games < self._candidate_min_games(league):
                        continue

                    # Published side first (0.65). Lean is only the fallback
                    # for the default NBA service, so a 0.90 under is not
                    # replaced by a 0.57 over.
                    side, side_probability = self._choose_stored_side(
                        p_over, p_under, league
                    )
                    if side is None or side_probability is None:
                        continue

                    # The CSV club on the US game date is kept only when
                    # that club is home or away. A last-season club that is
                    # not playing is left blank. Chart logs are oldest-first;
                    # ``team_on_event`` dates them and ignores list order.
                    game_logs = history_stats.get("game_logs", [])
                    player_team = team_on_event(
                        game_logs,
                        commence_time,
                        home_team,
                        away_team,
                        league=league,
                    )
                    player_team_code = canonical_team_code(player_team, league=league)
                    position = None
                    if league.lower() == "nba":
                        latest_position = getattr(csv_service, "latest_position", None)
                        if callable(latest_position):
                            raw_position = latest_position(player_name)
                            if isinstance(raw_position, str) and raw_position.strip():
                                position = raw_position.strip()

                    # No projection source. The line is not a stand-in.
                    # lineup_confirmed stays null until projected lineups.
                    # NBA injury_status comes from the cached snapshot.
                    # injury_status_raw is that same row's raw_status,
                    # copied with no case change and no trimming. The
                    # signal builder still receives only injury_status.
                    # Out blocks. A stored Doubtful is already Questionable
                    # and does not. The Odds API description has no
                    # bdl_player_id, so the match is the full name with
                    # the suffix kept. A missing or ambiguous name stays
                    # null on both fields. WNBA stays null on both.
                    has_projection = False
                    projected_value = None
                    projected_minutes = None
                    edge = None
                    injury_status = None
                    injury_status_raw = None
                    lineup_confirmed = None
                    if league.lower() == "nba" and injury_entries is not None:
                        injury_status, injury_status_raw = matched_injury_words(
                            match_injury_entry(injury_entries, player_name)
                        )
                    rank_fields = _empty_rank_fields()
                    if league.lower() == "nba":
                        opponent = _opponent_club(
                            player_team, home_team, away_team, league
                        )
                        try:
                            rank_fields = defense_fields(opponent, position)
                        except Exception as exc:
                            print(f"  ⚠️ Defense rank fill failed for {player_name}: {exc}")

                    pick = DailyPick(
                        player_name=player_name,
                        player_team=player_team,
                        player_team_code=player_team_code,
                        event_id=event_id,
                        home_team=home_team,
                        away_team=away_team,
                        commence_time=commence_time,
                        metric=metric_key,
                        threshold=mode_threshold,
                        direction=side,
                        probability=side_probability,
                        n_games=n_games,
                        bookmakers_count=len(lines),
                        all_lines=sorted(lines),
                        has_projection=has_projection,
                        projected_value=projected_value,
                        projected_minutes=projected_minutes,
                        edge=edge,
                        position=position,
                        opponent_rank=rank_fields["opponent_rank"],
                        opponent_position_rank=rank_fields["opponent_position_rank"],
                        opponent_rank_source=rank_fields["opponent_rank_source"],
                        opponent_rank_season=rank_fields["opponent_rank_season"],
                        opponent_rank_note=rank_fields["opponent_rank_note"],
                        opponent_position_rank_source=rank_fields["opponent_position_rank_source"],
                        opponent_position_rank_season=rank_fields["opponent_position_rank_season"],
                        opponent_position_rank_note=rank_fields["opponent_position_rank_note"],
                        injury_status=injury_status,
                        injury_status_raw=injury_status_raw,
                        lineup_confirmed=lineup_confirmed,
                        # NBA tier is filled after the signal step. Starting
                        # at None means a raised signal call cannot leave
                        # the historical label on a row whose blend is null.
                        # WNBA never runs that step, so it keeps the
                        # historical label here.
                        tier=(
                            None
                            if league.lower() == "nba"
                            else read_tier(side_probability)
                        ),
                        p_over=round(p_over, 4) if p_over is not None else None,
                        p_under=round(p_under, 4) if p_under is not None else None,
                        season_mean=_optional_stat(history_stats.get("season_mean")),
                    )
                    picks.append(pick)
                    pick = _with_nba_signal_verdicts(
                        pick,
                        league=league,
                        bookmakers_data=props_data,
                        game_logs=history_stats.get("game_logs") or [],
                    )

                    edge_str = f" (edge: {edge:+.1f})" if edge is not None else ""
                    min_str = f" [{projected_minutes:.0f}min]" if projected_minutes is not None else ""
                    print(
                        f"  ✨ {player_name} ({player_team}) {metric_key} "
                        f"{side.upper()} {mode_threshold}: {side_probability:.1%}"
                        f"{edge_str}{min_str}"
                    )

            except OddsAPIError as e:
                print(f"  ⚠️ Failed to fetch {market_key}: {e}")
                continue
            except Exception as e:
                print(f"  ⚠️ Failed to analyze {market_key}: {e}")
                continue

        return picks, len(all_players), total_props

    async def _get_props_for_market(
        self,
        event_id: str,
        market: str,
        league: str = "nba",
    ) -> List[Dict[str, Any]]:
        """
        Fetch all props for a given event and market

        Args:
            event_id: Event ID
            market: Market type (e.g. player_points)
            league: League key, mapped to The Odds API ``sport_key`` via
                    ``_resolve_sport_key``. The Odds API ``event_id``
                    is globally unique across sport keys, but the gateway
                    embeds ``sport`` in its snapshot cache key — wrong
                    league → cache miss + a misleading 404 from the API.

        Returns:
            List of bookmaker data
        """
        try:
            snapshot = await odds_gateway.get_market_snapshot(
                sport=_resolve_sport_key(league),
                event_id=event_id,
                regions="us",
                markets=market,
                odds_format="american",
                priority="background",
                record_hot_key=False,
            )

            return snapshot.data.get("bookmakers", [])

        except OddsAPIError as e:
            if e.status_code == 404:
                # No data for this market, not an error
                return []
            raise

    def _group_main_votes(
        self,
        bookmakers_data: List[Dict[str, Any]],
    ) -> Dict[str, List[Tuple[float, float]]]:
        """One ``(main line, even-money distance)`` per bookmaker.

        Same grouping as ``_group_props_by_player``. The distance is the
        second half of the cross-book tie in ``calculate_mode_threshold``.

        Args:
            bookmakers_data: ``bookmakers`` array from an event-odds response.

        Returns:
            Player name to one pair per bookmaker per market, in the order
            the books appear in ``bookmakers_data``.
        """
        buckets: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
        order: List[Tuple[str, str, str]] = []

        for index, bookmaker in enumerate(bookmakers_data):
            book_id = _book_id(bookmaker, index)
            markets = bookmaker.get("markets") or []
            for market_index, market in enumerate(markets):
                market_key = market.get("key")
                if not isinstance(market_key, str) or not market_key.strip():
                    market_key = f"#{market_index}"
                else:
                    market_key = market_key.strip()
                for outcome in market.get("outcomes") or []:
                    player_name = outcome.get("description", "")
                    if not isinstance(player_name, str) or not player_name:
                        continue
                    if outcome.get("point") is None:
                        continue
                    slot = (player_name, book_id, market_key)
                    if slot not in buckets:
                        buckets[slot] = []
                        order.append(slot)
                    buckets[slot].append(outcome)

        player_votes: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
        for player_name, slot_book, slot_market in order:
            vote = _main_line_vote(buckets[(player_name, slot_book, slot_market)])
            if vote is not None:
                player_votes[player_name].append(vote)
        return dict(player_votes)

    def _group_props_by_player(
        self,
        bookmakers_data: List[Dict[str, Any]]
    ) -> Dict[str, List[float]]:
        """One main line per bookmaker for each player.

        The Odds API lists Over and Under as two outcomes that share a
        ``point``. Appending both counted every book twice.
        ``bookmakers_count`` is ``len`` of this list (the DailyPick
        constructors keep that expression), and
        ``calculate_mode_threshold`` weights each entry once, so a book
        that was listed twice cast two votes.

        A book that posts several points — an alternate ladder, or an
        Over point that is not the Under point — contributes one point.
        ``_main_book_line`` picks that point. It is not the average of
        the Over and the Under.

        Different markets in one payload stay separate. A points line
        and a rebounds line are two votes. ``_analyze_single_event``
        requests one market at a time, so in that path the list length
        is the number of distinct bookmakers.

        Args:
            bookmakers_data: ``bookmakers`` array from an event-odds response.

        Returns:
            Player name to one float per bookmaker per market, in the
            order the books appear in ``bookmakers_data``.

        Example:
            One book posts Curry Over 24.5 and Under 24.5. The list is
            ``[24.5]``, not ``[24.5, 24.5]``. A second book at 25.5
            makes ``[24.5, 25.5]``.
        """
        votes = self._group_main_votes(bookmakers_data)
        return {
            player: [line for line, _distance in pairs]
            for player, pairs in votes.items()
        }


def _recent_stat_values(game_logs: List[Dict[str, Any]]) -> List[float]:
    """Stat values from ``get_player_stats`` logs, oldest first.

    Logs without a numeric ``value`` are skipped. The last ten of what
    remains are the non-DNP games the last-10 signal reads.
    """
    values: List[float] = []
    for game in game_logs:
        raw = game.get("value") if isinstance(game, dict) else None
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        number = float(raw)
        if not math.isfinite(number):
            continue
        values.append(number)
    return values


def _with_nba_signal_verdicts(
    pick: DailyPick,
    *,
    league: str,
    bookmakers_data: List[Dict[str, Any]],
    game_logs: List[Dict[str, Any]],
) -> DailyPick:
    """Attach the NBA signals on a pick. WNBA is returned unchanged.

    The projection slot is omitted. A market, last-10, history, or
    defense input that fails still serializes as null.

    Both new fields stay None for WNBA. The bookmaker list is the snapshot
    already fetched for this market; this does not request odds again and
    does not change how lines are grouped.
    """
    if league.lower() != "nba":
        return pick
    values = _recent_stat_values(game_logs)
    last10 = values[-10:] if len(values) >= 10 else None
    signals, combined, _adjustment = build_nba_signals(
        side=pick.direction,
        line=pick.threshold,
        player_name=pick.player_name,
        bookmakers=bookmakers_data,
        last10_values=last10,
        history_rate=pick.probability,
        projected_value=pick.projected_value,
        opponent_rank=pick.opponent_rank,
        opponent_position_rank=pick.opponent_position_rank,
        injury_status=pick.injury_status,
    )
    # Mutate the instance already appended to the pick list. model_copy
    # would leave the list holding the pre-signal object.
    pick.signals = signals
    pick.combined_probability = combined
    # NBA tier follows the calibrated probability. The historical label
    # set on the constructor is what WNBA keeps, because this function
    # returns before this assignment when the league is not NBA.
    pick.tier = read_tier(combined)
    return pick


def _top_read_candidate_is_out(
    player: str,
    injury_entries: list[dict[str, Any]] | None,
) -> bool:
    """True when a fresh snapshot marks this candidate Out.

    The name is the question the chooser asks before a row can become
    ``top_read``: is this player Out? Call it with the stored
    ``player_name`` and the fresh entry list. ``injury_entries`` is
    None when ``injuries:nba:latest`` is missing, stale, malformed, or
    unreadable. The candidate then stays, which is the same rule picks
    use when they leave ``injury_status`` null. An empty list is a
    fresh snapshot and matches nobody.

    The match is :func:`match_injury_entry` with no ``bdl_player_id``.
    A stored pick and a snapshot row are names. The fold is case,
    punctuation, and accents. The suffix stays, so a row for
    ``Gary Trent Jr.`` does not skip ``Gary Trent``. Only Out skips,
    with the same case and whitespace fold the blend uses.
    Questionable, including a source word of Doubtful, does not.
    This does not log and does not call BALLDONTLIE.

    Args:
        player: ``player_name`` on one stored pick.
        injury_entries: Fresh snapshot rows, or None.

    Returns:
        True when that player should be left out of the top read.
    """
    if injury_entries is None:
        return False
    matched = match_injury_entry(injury_entries, player)
    if not isinstance(matched, dict):
        return False
    status = matched.get("status")
    if not isinstance(status, str):
        return False
    return injury_blocks_combined(status)


def best_top_reads(
    cached: Any,
    injury_entries: list[dict[str, Any]] | None = None,
) -> Dict[str, TopRead]:
    """Pick the highest-probability stored pick for each event.

    The cache payload is the JSON written by ``run_daily_analysis``.
    Equal historical probabilities keep the earlier row. The stored
    list is ordered by ``sort_stored_picks`` (the blend for NBA, the
    historical rate for WNBA), so an NBA tie keeps the higher blend.

    Each event is chosen on its own. The game is that ``event_id``.
    The player is the stored ``player_name``. A candidate is skipped
    when ``injury_entries`` is a fresh snapshot and
    :func:`match_injury_entry` matches that name to a row whose
    normalized status is Out. The snapshot has no game id, and picks
    do not carry a ``bdl_player_id``, so this is the same name rule
    picks and ``/reads`` use. The next-highest finite candidate on
    that same event is used. When every candidate is Out, that event
    is absent and its ``top_read`` stays null. ``injury_entries``
    left as None does not skip anyone. WNBA does not call this with
    a snapshot.

    Args:
        cached: Daily-picks cache document, or anything that is not one.
        injury_entries: Fresh NBA injury rows, or None when the
            snapshot cannot be used. The default keeps the old choice.

    Returns:
        Map of event_id to ``TopRead``. Empty when nothing is stored.
    """
    if not isinstance(cached, dict):
        return {}

    best: Dict[str, Dict[str, Any]] = {}
    for pick in cached.get("picks") or []:
        if not isinstance(pick, dict):
            continue
        event_id = pick.get("event_id")
        player = pick.get("player_name")
        side = pick.get("direction")
        if not event_id or not player or side not in ("over", "under"):
            continue
        try:
            probability = float(pick["probability"])
            line = float(pick["threshold"])
        except (KeyError, TypeError, ValueError):
            continue
        # NaN compares false against every number, so a later NaN would
        # replace a real pick. Skip it, and skip a non-finite line.
        if not math.isfinite(probability) or not math.isfinite(line):
            continue
        market = market_key_for_metric(pick.get("metric"))
        if market is None:
            continue
        # The game is event_id. The player is this row. An Out match
        # drops the row before it can replace a lower healthy one.
        if _top_read_candidate_is_out(str(player), injury_entries):
            continue
        current = best.get(str(event_id))
        if current is not None and probability <= current["probability"]:
            continue
        best[str(event_id)] = {
            "player": str(player),
            "market": market,
            "side": side,
            "line": line,
            "probability": probability,
        }

    return {
        event_id: TopRead(
            player=row["player"],
            market=row["market"],
            side=row["side"],
            line=row["line"],
            probability=row["probability"],
        )
        for event_id, row in best.items()
    }


def attach_top_reads(
    response: EventsResponse,
    reads: Dict[str, TopRead],
) -> EventsResponse:
    """Copy ``response`` with ``top_read`` set from ``reads``.

    Events with no stored pick get null. The input response is not mutated.

    Args:
        response: Event list already filtered to the requested date.
        reads: Best stored pick per event_id.

    Returns:
        Event list the NBA events route can send.
    """
    events = [
        event.model_copy(update={"top_read": reads.get(event.event_id)})
        for event in response.events
    ]
    return response.model_copy(update={"events": events})


async def _read_top_read_injuries() -> list[dict[str, Any]] | None:
    """Fresh injury rows for top_read, or None when the snapshot cannot be used.

    ``_read_top_read_injuries`` is the Redis read ``load_stored_top_reads``
    uses. Call it from that loader only. It reads
    ``injuries:nba:latest`` and returns. It does not call BALLDONTLIE.
    A missing key, a stale ``fetched_at``, a body that is not an
    entries list, and a read error all return None with no log line.
    Picks and ``/reads`` already warn once for those cases. A second
    warning on the events request would be noise, and a Redis error
    here must not drop every top_read: the caller still ranks the
    stored picks. A fresh empty list returns ``[]``.

    Returns:
        The entry list, or None when top_read must not skip anyone.
    """
    try:
        raw = await cache_service.get(NBA_INJURIES_CACHE_KEY)
    except Exception:
        return None
    if not injury_snapshot_is_fresh(raw):
        return None
    return [row for row in raw["entries"] if isinstance(row, dict)]


async def load_stored_top_reads(
    date: str,
    tz_offset_minutes: int,
) -> Dict[str, TopRead]:
    """Read the NBA daily-picks cache and index it by event.

    This does not run analysis and does not call the Odds API or
    BALLDONTLIE. A cache miss, including a Redis error that
    ``CacheService.get`` turns into None, yields an empty map so every
    event's ``top_read`` stays null. A fresh injury snapshot is read
    from the same Redis and skips Out players. A missing or stale
    snapshot does not, and that read does not log.

    Args:
        date: Local date YYYY-MM-DD. Must be the same date the events
            request used.
        tz_offset_minutes: Same offset the events request used. Daily
            picks are cached per offset, and a different offset is a
            different local slate.

    Returns:
        Best stored pick per event_id, after Out players are skipped.
    """
    cached = await cache_service.get(
        daily_picks_cache_key("nba", date, tz_offset_minutes)
    )
    return best_top_reads(cached, injury_entries=await _read_top_read_injuries())


# Create a global service instance
daily_analysis_service = DailyAnalysisService()
