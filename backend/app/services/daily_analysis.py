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
import re
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

from app.services.odds_gateway import odds_gateway
from app.services.odds_theoddsapi import odds_provider
from app.services.odds_provider import OddsAPIError
from app.services.csv_player_history import (
    csv_player_service,
    team_from_game_logs,
    wnba_csv_player_service,
)
from app.services.prob import calculate_mode_threshold
from app.services.cache import cache_service
from app.services.projection_service import projection_service
from app.models.schemas import (
    AnalysisStats,
    DailyPick,
    DailyPicksResponse,
    EventsResponse,
    TopRead,
)


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

# Leagues with wired projections (SportsDataIO Projection API).
# WNBA is intentionally absent here: the wrapper hasn't been ported and
# SPO-35 explicitly defers it (graceful-degrade to history-only, see
# decision_20260514_db-schema-audit.md §6 step 1). When WNBA projections
# land, add "wnba" here and the pre-fetch loop below will pick it up
# without other changes.
_LEAGUES_WITH_PROJECTIONS: set[str] = {"nba"}


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


def market_key_for_metric(metric: str) -> str:
    """Return the Odds API market key for a daily-pick metric.

    ``points`` becomes ``player_points``. An unknown metric is returned
    unchanged so this helper does not invent a market key.

    Args:
        metric: CSV / DailyPick metric key.

    Returns:
        Odds API market key when the metric is known.
    """
    return _METRIC_TO_MARKET_KEY.get(metric, metric)


# Alias map: CSV metric key -> SportsDataIO projection field name.
# Most metrics use the same key in both places (points, rebounds, etc.) but
# a handful diverge — chiefly the SPO-16 additions where the CSV key is the
# concise frontend label (`threes_made`) but the projection field follows the
# SportsDataIO API convention (`three_pointers_made`). Without this map, the
# `edge` column on new-metric picks would be permanently None even when a
# projection exists.
# ⚠ ra/pr/pa: projection_provider.normalize_projection() writes these combos
# as r_a / p_r / p_a (underscored). Forgetting the alias here silently nulls
# `edge` and `projected_value` on every R+A / P+R / P+A pick — the SPO-17
# regression. Keep these three rows in sync with normalize_projection.
PROJECTION_FIELD_ALIASES: Dict[str, str] = {
    "threes_made": "three_pointers_made",
    "ftm": "free_throws_made",
    "fgm": "field_goals_made",
    "ra": "r_a",
    "pr": "p_r",
    "pa": "p_a",
}

# High probability threshold
HIGH_PROBABILITY_THRESHOLD = 0.65

# Minimum non-DNP games before a historical rate can become a pick.
# The walk-forward harness imports this so it gates on the same sample size.
# The NBA daily-picks query uses this as its default, not as the storage floor.
MIN_SAMPLE_GAMES = 10

# Read tiers for a stored pick. Frontend has no readTier helper (searched
# frontend/ on 2026-11-10). Strong / Playable match the picks-page buckets
# (high at 0.70, medium from 0.65). Lean is the floor added here. Highest
# cutoff is first; read_tier stops at the first match.
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
    """Map a pick probability onto a read tier.

    Args:
        probability: Chosen-side historical rate, or None.

    Returns:
        ``"Strong play"`` when probability >= 0.70, ``"Playable"`` when
        probability >= 0.65, ``"Lean"`` when probability >= 0.56, or None
        below that cutoff and when probability is missing.
    """
    if probability is None:
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

# Cache TTL (15 minutes)
DAILY_PICKS_CACHE_TTL = 15 * 60


def daily_picks_cache_key(league: str, date: str, tz_offset_minutes: int) -> str:
    """Redis key for one league, local date, and timezone offset.

    Args:
        league: ``nba`` or ``wnba``.
        date: Local date YYYY-MM-DD.
        tz_offset_minutes: Minutes east of UTC. UTC+8 is 480.

    Returns:
        ``daily_picks:{league}:{date}:tz{offset}``.
    """
    return f"{DAILY_PICKS_CACHE_KEY}:{league.lower()}:{date}:tz{tz_offset_minutes}"


def select_daily_picks(
    picks: List[DailyPick],
    min_probability: float = HIGH_PROBABILITY_THRESHOLD,
    min_games: int = MIN_SAMPLE_GAMES,
) -> List[DailyPick]:
    """Keep picks that clear the query floors.

    The stored list can include Lean rows and short NBA samples. This is
    the filter the daily-picks route applies. Defaults are the published
    board: probability 0.65 and 10 games.

    Args:
        picks: Stored picks, highest probability first.
        min_probability: Inclusive probability floor.
        min_games: Inclusive sample floor.

    Returns:
        Picks that meet both floors, in the original order.
    """
    return [
        pick
        for pick in picks
        if pick.probability >= min_probability and pick.n_games >= min_games
    ]


def present_daily_picks(
    result: DailyPicksResponse,
    min_probability: float = HIGH_PROBABILITY_THRESHOLD,
    min_games: int = MIN_SAMPLE_GAMES,
) -> DailyPicksResponse:
    """Return a copy of ``result`` whose picks match the query floors.

    ``stats.high_prob_count`` stays the published-board count written at
    analysis time. ``total_picks`` becomes the filtered length. The stored
    object is not mutated, so a later lower ``min_probability`` still sees
    the Lean rows that were cached.

    Args:
        result: Stored analysis, including candidates below the board.
        min_probability: Inclusive probability floor.
        min_games: Inclusive sample floor.

    Returns:
        Response the route can send.
    """
    filtered = select_daily_picks(result.picks, min_probability, min_games)
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
    "CLIPPERS": "LAC",
    "LAL": "LAL",
    "LOSANGELESLAKERS": "LAL",
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
            date: Analysis date (YYYY-MM-DD), None means today
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

        # Determine analysis date
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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
                print(
                    f"✅ [{league_normalized.upper()}] Using cached analysis result: "
                    f"{date} (tz={tz_offset_minutes})"
                )
                return DailyPicksResponse(**cached_data)

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

        # 2.5. Pre-fetch player projections (SportsDataIO).
        # Only NBA has the projection wrapper wired today (see
        # _LEAGUES_WITH_PROJECTIONS). For WNBA we skip the network call
        # entirely and let the per-pick projection lookup degrade
        # gracefully — `proj.get(...)` returns None, `edge` stays None,
        # `has_projection` stays False, opponent_rank/injury_status all
        # null. Tile-side UX already handles this empty state (SPO-26).
        projections: Dict[str, Dict] = {}
        if league_normalized in _LEAGUES_WITH_PROJECTIONS:
            try:
                projections = await projection_service.get_projections(date)
                if projections:
                    print(f"📊 Retrieved {len(projections)} projection records")
                else:
                    print(f"ℹ️ No projection data available, will use only historical probabilities")
            except Exception as e:
                print(f"⚠️ Failed to get projection data (doesn't affect main analysis): {e}")
        else:
            print(
                f"ℹ️ [{league_normalized.upper()}] Projections not wired for this "
                f"league; running history-only (edge / opponent_rank stay None)"
            )

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
                    projections=projections,
                    league=league_normalized,
                )
                all_picks.extend(event_picks)
                total_players += players_count
                total_props += props_count
            except Exception as e:
                print(f"⚠️ Failed to analyze event {event_id}: {e}")
                continue

        # 4. Sort picks by probability (descending)
        all_picks.sort(key=lambda x: x.probability, reverse=True)

        # 5. Calculate statistics. high_prob_count stays the published
        # board (0.65 and 10 games) even when NBA storage also kept Lean
        # rows and shorter samples. The default query then reports the
        # same total_picks as this count.
        duration = time.time() - start_time
        published_count = len(select_daily_picks(all_picks))
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
    ) -> Tuple[List[DailyPick], int, int]:
        """
        Analyze a single event

        For all players in the event, analyze probabilities for the 4 metrics,
        and incorporate projection data to compute Value Edge.

        Args:
            event_id: Event ID
            home_team: Home team
            away_team: Away team
            commence_time: Event start time
            projections: Projection dict (keyed by player_name),
                         obtained up front in run_daily_analysis
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

        if projections is None:
            projections = {}

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

                # Group by player
                player_props = self._group_props_by_player(props_data)

                for player_name, lines in player_props.items():
                    all_players.add(player_name)
                    total_props += 1

                    # Calculate mode threshold
                    mode_threshold = calculate_mode_threshold(lines)

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

                    # === Integrate projection data (Value Edge Detection) ===
                    # Lookup pre-fetched projection for player
                    proj = projections.get(player_name, {})
                    has_projection = bool(proj)

                    # Prefer fetching player team from projections
                    # SportsDataIO's team field updates for in-season trades and is more accurate than CSV
                    # Projections API returns abbreviations (like "GS", "MIL"), CSV gives short names ("Warriors", "Bucks")
                    player_team = ""
                    if proj and proj.get("team"):
                        player_team = proj.get("team")
                    else:
                        # Chart logs are oldest-first. ``commence_time`` is
                        # UTC; ``team_from_game_logs`` converts it to the US
                        # game date, then uses that day's club or the latest
                        # club on or before it (a gap day keeps the prior club).
                        game_logs = history_stats.get("game_logs", [])
                        player_team = team_from_game_logs(game_logs, commence_time)
                    player_team_code = canonical_team_code(player_team, league=league)

                    # Get projection value for this metric.
                    # 💡 Translate via PROJECTION_FIELD_ALIASES because the
                    # CSV/frontend metric key isn't always the projection-API
                    # field name (e.g. `threes_made` ↔ `three_pointers_made`).
                    projection_field = PROJECTION_FIELD_ALIASES.get(metric_key, metric_key)
                    projected_value = proj.get(projection_field) if proj else None
                    projected_minutes = proj.get("minutes") if proj else None
                    opponent_rank = proj.get("opponent_rank") if proj else None
                    opponent_position_rank = proj.get("opponent_position_rank") if proj else None
                    injury_status = proj.get("injury_status") if proj else None
                    lineup_confirmed = proj.get("lineup_confirmed") if proj else None

                    # Calculate Edge (projection - line)
                    # Positive: projection above line (favors Over)
                    # Negative: projection below line (favors Under)
                    edge = None
                    if projected_value is not None and mode_threshold is not None:
                        edge = round(projected_value - mode_threshold, 2)

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
                        projected_value=round(projected_value, 2) if projected_value is not None else None,
                        projected_minutes=round(projected_minutes, 1) if projected_minutes is not None else None,
                        edge=edge,
                        opponent_rank=opponent_rank,
                        opponent_position_rank=opponent_position_rank,
                        injury_status=injury_status,
                        lineup_confirmed=lineup_confirmed,
                        tier=read_tier(side_probability),
                        p_over=round(p_over, 4) if p_over is not None else None,
                        p_under=round(p_under, 4) if p_under is not None else None,
                    )
                    picks.append(pick)

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

    def _group_props_by_player(
        self,
        bookmakers_data: List[Dict[str, Any]]
    ) -> Dict[str, List[float]]:
        """
        Group props data by player

        From all bookmaker data, extract each player's line values

        Args:
            bookmakers_data: List of bookmaker data

        Returns:
            Dict[player_name, List[lines]]: Mapping of player name to line list

        Example:
            Input:
            [
                {"key": "draftkings", "markets": [{"outcomes": [...]}]},
                {"key": "fanduel", "markets": [{"outcomes": [...]}]}
            ]

            Output:
            {
                "Stephen Curry": [24.5, 24.5, 25.5],
                "LeBron James": [27.5, 27.5, 28.5]
            }
        """
        player_lines: Dict[str, List[float]] = defaultdict(list)

        for bookmaker in bookmakers_data:
            for market in bookmaker.get("markets", []):
                for outcome in market.get("outcomes", []):
                    # description field contains player name
                    player_name = outcome.get("description", "")
                    # point field contains line value
                    line = outcome.get("point")

                    if player_name and line is not None:
                        player_lines[player_name].append(float(line))

        return dict(player_lines)


def best_top_reads(cached: Any) -> Dict[str, TopRead]:
    """Pick the highest-probability stored pick for each event.

    The cache payload is the JSON written by ``run_daily_analysis``.
    Equal probabilities keep the earlier row. Analysis sorts by
    probability descending, so a tie keeps the row that was stored first.

    Args:
        cached: Daily-picks cache document, or anything that is not one.

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
        current = best.get(str(event_id))
        if current is not None and probability <= current["probability"]:
            continue
        best[str(event_id)] = {
            "player": str(player),
            "market": market_key_for_metric(str(pick.get("metric") or "")),
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


async def load_stored_top_reads(
    date: str,
    tz_offset_minutes: int,
) -> Dict[str, TopRead]:
    """Read the NBA daily-picks cache and index it by event.

    This does not run analysis and does not call the Odds API. A cache
    miss, including a Redis error that ``CacheService.get`` turns into
    None, yields an empty map so every event's ``top_read`` stays null.

    Args:
        date: Local date YYYY-MM-DD. Must be the same date the events
            request used.
        tz_offset_minutes: Same offset the events request used. Daily
            picks are cached per offset, and a different offset is a
            different local slate.

    Returns:
        Best stored pick per event_id.
    """
    cached = await cache_service.get(
        daily_picks_cache_key("nba", date, tz_offset_minutes)
    )
    return best_top_reads(cached)


# Create a global service instance
daily_analysis_service = DailyAnalysisService()
