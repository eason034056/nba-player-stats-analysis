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
from app.services.csv_player_history import csv_player_service
from app.services.prob import calculate_mode_threshold
from app.services.cache import cache_service
from app.services.projection_service import projection_service
from app.models.schemas import DailyPick, DailyPicksResponse, AnalysisStats


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


# Alias map: CSV metric key -> SportsDataIO projection field name.
# Most metrics use the same key in both places (points, rebounds, etc.) but
# a handful diverge — chiefly the SPO-16 additions where the CSV key is the
# concise frontend label (`threes_made`) but the projection field follows the
# SportsDataIO API convention (`three_pointers_made`). Without this map, the
# `edge` column on new-metric picks would be permanently None even when a
# projection exists.
PROJECTION_FIELD_ALIASES: Dict[str, str] = {
    "threes_made": "three_pointers_made",
    "ftm": "free_throws_made",
    "fgm": "field_goals_made",
    # ra/pr/pa: projection_provider.normalize_projection() exposes these
    # exact keys as derived fields, so no alias needed.
}

# High probability threshold
HIGH_PROBABILITY_THRESHOLD = 0.65

# Cache key prefix
DAILY_PICKS_CACHE_KEY = "daily_picks"

# Cache TTL (15 minutes)
DAILY_PICKS_CACHE_TTL = 15 * 60

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


def canonical_team_code(team_name: str) -> str:
    if not team_name:
        return ""

    normalized = re.sub(r"[^A-Z0-9]", "", team_name.upper())
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

    def __init__(self, probability_threshold: float = HIGH_PROBABILITY_THRESHOLD):
        """
        Initialize the analysis service

        Args:
            probability_threshold: High probability threshold, default 0.65 (65%)
        """
        self.probability_threshold = probability_threshold
        self.csv_service = csv_player_service

    async def run_daily_analysis(
        self,
        date: Optional[str] = None,
        use_cache: bool = True,
        tz_offset_minutes: int = 480
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

        Returns:
            DailyPicksResponse: Contains all high-probability player picks

        Example:
            >>> service = DailyAnalysisService()
            >>> result = await service.run_daily_analysis()
            >>> print(f"Found {result.total_picks} high-probability picks")
        """
        start_time = time.time()

        # Determine analysis date
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # 1. Check cache (different keys for different timezones)
        if use_cache:
            cache_key = f"{DAILY_PICKS_CACHE_KEY}:{date}:tz{tz_offset_minutes}"
            cached_data = await cache_service.get(cache_key)
            if cached_data:
                print(f"✅ Using cached analysis result: {date} (tz={tz_offset_minutes})")
                return DailyPicksResponse(**cached_data)

        print(f"🚀 Starting daily analysis: {date}")

        # 2. Get all events for the day
        try:
            events = await self._get_events_for_date(date, tz_offset_minutes)
        except Exception as e:
            print(f"❌ Failed to fetch events: {e}")
            return DailyPicksResponse(
                date=date,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                total_picks=0,
                picks=[],
                stats=None,
                message=f"Failed to fetch events: {str(e)}"
            )

        if not events:
            print(f"⚠️ No events today: {date}")
            return DailyPicksResponse(
                date=date,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                total_picks=0,
                picks=[],
                stats=None,
                message="No events today"
            )

        print(f"📅 Found {len(events)} events")

        # 2.5. Pre-fetch player projections (SportsDataIO)
        # One API call for all player projections for the date, re-used in analyses
        projections: Dict[str, Dict] = {}
        try:
            projections = await projection_service.get_projections(date)
            if projections:
                print(f"📊 Retrieved {len(projections)} projection records")
            else:
                print(f"ℹ️ No projection data available, will use only historical probabilities")
        except Exception as e:
            print(f"⚠️ Failed to get projection data (doesn't affect main analysis): {e}")

        # 3. Analyze all events
        all_picks: List[DailyPick] = []
        total_players = 0
        total_props = 0

        for event in events:
            event_id = event.get("id", "")
            home_team = event.get("home_team", "")
            away_team = event.get("away_team", "")
            commence_time = event.get("commence_time", "")

            print(f"\n🏀 Analyzing event: {away_team} @ {home_team}")

            try:
                event_picks, players_count, props_count = await self._analyze_single_event(
                    event_id=event_id,
                    home_team=home_team,
                    away_team=away_team,
                    commence_time=commence_time,
                    projections=projections
                )
                all_picks.extend(event_picks)
                total_players += players_count
                total_props += props_count
            except Exception as e:
                print(f"⚠️ Failed to analyze event {event_id}: {e}")
                continue

        # 4. Sort picks by probability (descending)
        all_picks.sort(key=lambda x: x.probability, reverse=True)

        # 5. Calculate statistics
        duration = time.time() - start_time
        stats = AnalysisStats(
            total_events=len(events),
            total_players=total_players,
            total_props=total_props,
            high_prob_count=len(all_picks),
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

        # 7. Store in cache (including timezone offset)
        # Note: Even if use_cache=False (force-refresh), always store so next GET uses latest result
        cache_key = f"{DAILY_PICKS_CACHE_KEY}:{date}:tz{tz_offset_minutes}"
        await cache_service.set(
            cache_key,
            response.model_dump(mode='json'),
            ttl=DAILY_PICKS_CACHE_TTL
        )

        print(f"\n✅ Analysis complete! Found {len(all_picks)} high-probability picks in {duration:.2f} sec")

        return response

    async def _get_events_for_date(self, date: str, tz_offset_minutes: int = 480) -> List[Dict[str, Any]]:
        """
        Fetch all NBA events for the specified date

        Takes timezone offset into account to fetch events for user-local date.

        Args:
            date: Date string (YYYY-MM-DD)
            tz_offset_minutes: Timezone offset in minutes, default 480 (UTC+8, Taipei)
                               Positive = east (like UTC+8 = 480)
                               Negative = west (like UTC-6 = -360)

        Returns:
            List of events
        """
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

        print(f"📅 Query time range: {date_from.isoformat()} ~ {date_to.isoformat()} (UTC)")

        # Call Odds API
        raw_events = await odds_provider.get_events(
            sport="basketball_nba",
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
        projections: Optional[Dict[str, Dict]] = None
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

        Returns:
            Tuple[List[DailyPick], int, int]: (High probability picks, player count, prop count)
        """
        picks: List[DailyPick] = []
        all_players: set = set()
        total_props = 0

        if projections is None:
            projections = {}

        # Analyze each metric
        for market_key, metric_key in SUPPORTED_MARKETS:
            try:
                # Get all props for this market
                props_data = await self._get_props_for_market(event_id, market_key)

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

                    # Historical probability from CSV
                    history_stats = self.csv_service.get_player_stats(
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

                    # Require at least 10 game samples
                    if n_games < 10:
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
                        # Fallback: last game's team from CSV
                        game_logs = history_stats.get("game_logs", [])
                        if game_logs and len(game_logs) > 0:
                            player_team = game_logs[0].get("team", "")
                    player_team_code = canonical_team_code(player_team)

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

                    # Check if it passes probability threshold
                    if p_over is not None and p_over >= self.probability_threshold:
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
                            direction="over",
                            probability=round(p_over, 4),
                            n_games=n_games,
                            bookmakers_count=len(lines),
                            all_lines=sorted(lines),
                            # Projection data
                            has_projection=has_projection,
                            projected_value=round(projected_value, 2) if projected_value is not None else None,
                            projected_minutes=round(projected_minutes, 1) if projected_minutes is not None else None,
                            edge=edge,
                            opponent_rank=opponent_rank,
                            opponent_position_rank=opponent_position_rank,
                            injury_status=injury_status,
                            lineup_confirmed=lineup_confirmed,
                        )
                        picks.append(pick)

                        # Print log with edge info
                        edge_str = f" (edge: {edge:+.1f})" if edge is not None else ""
                        min_str = f" [{projected_minutes:.0f}min]" if projected_minutes is not None else ""
                        print(f"  ✨ {player_name} ({player_team}) {metric_key} OVER {mode_threshold}: {p_over:.1%}{edge_str}{min_str}")

                    elif p_under is not None and p_under >= self.probability_threshold:
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
                            direction="under",
                            probability=round(p_under, 4),
                            n_games=n_games,
                            bookmakers_count=len(lines),
                            all_lines=sorted(lines),
                            # Projection data
                            has_projection=has_projection,
                            projected_value=round(projected_value, 2) if projected_value is not None else None,
                            projected_minutes=round(projected_minutes, 1) if projected_minutes is not None else None,
                            edge=edge,
                            opponent_rank=opponent_rank,
                            opponent_position_rank=opponent_position_rank,
                            injury_status=injury_status,
                            lineup_confirmed=lineup_confirmed,
                        )
                        picks.append(pick)

                        edge_str = f" (edge: {edge:+.1f})" if edge is not None else ""
                        min_str = f" [{projected_minutes:.0f}min]" if projected_minutes is not None else ""
                        print(f"  ✨ {player_name} ({player_team}) {metric_key} UNDER {mode_threshold}: {p_under:.1%}{edge_str}{min_str}")

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
        market: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch all props for a given event and market

        Args:
            event_id: Event ID
            market: Market type (e.g. player_points)

        Returns:
            List of bookmaker data
        """
        try:
            snapshot = await odds_gateway.get_market_snapshot(
                sport="basketball_nba",
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


# Create a global service instance
daily_analysis_service = DailyAnalysisService()
