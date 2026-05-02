"""
nba.py - NBA related API endpoints

Includes:
1. Game List API (GET /api/nba/events)
2. No-Vig Probability Calculation API (POST /api/nba/props/no-vig)
3. Player Suggestions API (GET /api/nba/players/suggest)

This is the core functional module of the application.
"""

from fastapi import APIRouter, HTTPException, Query, Request
from datetime import datetime, timezone, timedelta, time
from typing import List, Optional
from zoneinfo import ZoneInfo

from app.middleware.rate_limit import limiter
from app.models.schemas import (
    EventsResponse,
    NBAEvent,
    NoVigRequest,
    NoVigResponse,
    BookmakerResult,
    Consensus,
    PlayerSuggestResponse,
    CSVPlayersResponse,
    PlayerHistoryResponse,
    HistogramBin,
    GameLog
)
from app.services.odds_theoddsapi import odds_provider
from app.services.odds_provider import OddsAPIError
from app.services.cache import cache_service, CacheService
from app.services.odds_gateway import odds_gateway, MarketSnapshotResult
from app.services.prob import (
    american_to_prob,
    calculate_vig,
    devig,
    calculate_consensus_mean
)
from app.services.normalize import extract_player_names, find_player, suggest_players as suggest_player_names
from app.services.csv_player_history import csv_player_service
from app.settings import settings

# Initialize router
router = APIRouter(
    prefix="/api/nba",
    tags=["nba"]
)


def _snapshot_metadata(snapshot: MarketSnapshotResult) -> dict:
    return {
        "fetched_at": snapshot.fetched_at,
        "data_age_seconds": snapshot.data_age_seconds,
        "cache_state": snapshot.cache_state,
        "source": snapshot.source,
    }


def _collect_player_names(
    bookmakers_data: list[dict],
    market_key: str,
) -> list[str]:
    player_set = set()
    for bookmaker in bookmakers_data:
        for market in bookmaker.get("markets", []):
            if market.get("key") != market_key:
                continue
            for outcome in market.get("outcomes", []):
                if "description" in outcome:
                    player_set.add(outcome["description"])
    return sorted(player_set)


@router.get(
    "/events",
    response_model=EventsResponse,
    summary="Get NBA games list",
    description="Get NBA games list for a specified date"
)
async def get_events(
    date: Optional[str] = Query(
        default=None,
        description="Query date (YYYY-MM-DD), defaults to today",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    regions: str = Query(
        default="us",
        description="Region code (us, uk, eu, au)"
    ),
    tz_offset: Optional[int] = Query(
        default=None,
        description="Timezone offset (minutes), e.g. UTC-6 send -360, UTC+8 send 480. Used for filtering local date games."
    )
) -> EventsResponse:
    """
    Get NBA games list

    GET /api/nba/events?date=YYYY-MM-DD&regions=us

    Flow:
    1. Check Redis cache
    2. If cache hit, return directly
    3. If cache miss, call The Odds API
    4. Store result in cache
    5. Return result

    Args:
        date: Query date (YYYY-MM-DD), defaults to today
        regions: Region code, affects available bookmakers

    Returns:
        EventsResponse: Games list

    Raises:
        HTTPException: API call fails

    Example Response:
        {
            "date": "2026-01-14",
            "events": [
                {
                    "event_id": "abc123",
                    "sport_key": "basketball_nba",
                    "home_team": "Los Angeles Lakers",
                    "away_team": "Golden State Warriors",
                    "commence_time": "2026-01-15T01:00:00Z"
                }
            ]
        }
    """
    # Handle date param: defaults to today
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Handle timezone offset: default UTC (0 minutes)
    # Note: JavaScript's getTimezoneOffset() returns "UTC - Local" minutes
    # Example: UTC-6 returns 360 (positive), UTC+8 returns -480 (negative)
    # But front-end should send "normal" offset (UTC-6 send -360, UTC+8 send 480)
    offset_minutes = tz_offset if tz_offset is not None else 0
    
    # 1. Check cache (include timezone offset to distinguish different local time requests)
    cache_key = f"{CacheService.build_events_key(date, regions)}:tz{offset_minutes}"
    cached_data = await cache_service.get(cache_key)
    
    if cached_data:
        # Cache hit
        return EventsResponse(**cached_data)
    
    # 2. Cache miss, call external API
    try:
        # Calculate UTC time range for user's local date
        # Example: If user is UTC-6 and selects "2026-01-17"
        # Local 2026-01-17 00:00:00 = UTC 2026-01-17 06:00:00
        # Local 2026-01-17 23:59:59 = UTC 2026-01-18 05:59:59
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        
        # Local 00:00:00 to UTC
        local_start = datetime.combine(date_obj.date(), datetime.min.time())
        utc_start = local_start - timedelta(minutes=offset_minutes)
        
        # Local 23:59:59 to UTC (avoid datetime.max.time to skip microseconds)
        local_end = datetime.combine(date_obj.date(), time(23, 59, 59))
        utc_end = local_end - timedelta(minutes=offset_minutes)
        
        # Expand search range to cover boundary cases
        date_from = utc_start - timedelta(hours=1)
        date_to = utc_end + timedelta(hours=1)
        
        raw_events = await odds_provider.get_events(
            sport="basketball_nba",
            regions=regions,
            date_from=date_from,
            date_to=date_to
        )
        
        # 3. Transform and filter data by date
        # Filter: return only games whose commence time falls within local date
        events = []
        for raw_event in raw_events:
            commence_time_str = raw_event.get("commence_time", "")
            
            if commence_time_str:
                # Parse UTC time (e.g. 2026-01-17T00:10:00Z)
                try:
                    commence_utc = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                    # Convert to local time
                    commence_local = commence_utc + timedelta(minutes=offset_minutes)
                    # Get local date
                    commence_local_date = commence_local.strftime("%Y-%m-%d")
                    
                    # Only return games where local date matches request
                    if commence_local_date != date:
                        continue
                except ValueError:
                    # Couldn't parse time, skip filter
                    pass
            
            events.append(NBAEvent(
                event_id=raw_event.get("id", ""),
                sport_key=raw_event.get("sport_key", "basketball_nba"),
                home_team=raw_event.get("home_team", ""),
                away_team=raw_event.get("away_team", ""),
                commence_time=commence_time_str
            ))
        
        # 4. Build response
        response = EventsResponse(
            date=date,
            events=events
        )
        
        # 5. Store in cache
        await cache_service.set(
            cache_key,
            response.model_dump(mode='json'),
            ttl=settings.cache_ttl_events
        )
        
        return response
        
    except OddsAPIError as e:
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {str(e)}"
        )


@router.post(
    "/props/no-vig",
    response_model=NoVigResponse,
    summary="Calculate no-vig probabilities",
    description="Query specific player props and calculate no-vig probabilities"
)
@limiter.limit(settings.rate_limit_props)
async def calculate_no_vig(request: Request, body: NoVigRequest) -> NoVigResponse:
    """
    Calculate no-vig probability for player props

    POST /api/nba/props/no-vig

    This is a core feature of the application!

    Flow:
    1. Check cache (using event_id + market + regions + bookmakers as key)
    2. If cache miss, call The Odds API for props data
    3. Search for specified player in outcomes (fuzzy matching)
    4. For each bookmaker:
       a. Get line (threshold), over_odds, under_odds
       b. Calculate implied probability
       c. Calculate vig
       d. Calculate fair probability (no-vig)
    5. Calculate market consensus (average of all bookmakers)
    6. Store in cache and return

    Args:
        request: NoVigRequest containing:
            - event_id: Game ID
            - player_name: Player name
            - market: Market type (default player_points)
            - regions: Region code
            - bookmakers: Specific bookmakers (optional)
            - odds_format: Odds format

    Returns:
        NoVigResponse: Contains results from each bookmaker and market consensus

    Example Request:
        {
            "event_id": "abc123",
            "player_name": "Stephen Curry",
            "market": "player_points",
            "regions": "us",
            "bookmakers": ["draftkings", "fanduel"]
        }
    """
    try:
        snapshot = await odds_gateway.get_market_snapshot(
            sport="basketball_nba",
            event_id=body.event_id,
            regions=body.regions,
            markets=body.market,
            odds_format=body.odds_format,
            bookmakers=body.bookmakers,
            priority="interactive",
        )
        bookmakers_data = snapshot.data.get("bookmakers", [])
        all_player_names = _collect_player_names(bookmakers_data, body.market)

        # 3. Match player name
        matched_player = find_player(
            body.player_name,
            all_player_names
        )

        if not matched_player:
            suggestions = suggest_player_names(body.player_name, all_player_names, limit=5, threshold=70)
            if suggestions:
                hint = ", ".join(f"{name} ({score})" for name, score in suggestions)
                message = f"Player '{body.player_name}' not found. Closest names: {hint}"
            else:
                message = f"Player '{body.player_name}' not found. Available players: {all_player_names[:10]}"
            return NoVigResponse(
                event_id=body.event_id,
                player_name=body.player_name,
                market=body.market,
                results=[],
                consensus=None,
                message=message,
                **_snapshot_metadata(snapshot),
            )

        # 4. Calculate no-vig probabilities for each bookmaker
        results: List[BookmakerResult] = []
        fair_probs_for_consensus = []

        for bookmaker in bookmakers_data:
            bookmaker_key = bookmaker.get("key", "unknown")

            for market in bookmaker.get("markets", []):
                if market.get("key") != body.market:
                    continue

                # Find Over and Under outcomes for player
                over_outcome = None
                under_outcome = None
                line = None

                for outcome in market.get("outcomes", []):
                    if outcome.get("description") == matched_player:
                        outcome_name = outcome.get("name", "").lower()

                        if outcome_name == "over":
                            over_outcome = outcome
                            line = outcome.get("point")
                        elif outcome_name == "under":
                            under_outcome = outcome
                            if line is None:
                                line = outcome.get("point")

                # Require both Over and Under to calculate
                if over_outcome is None or under_outcome is None or line is None:
                    continue

                over_odds = over_outcome.get("price", 0)
                under_odds = under_outcome.get("price", 0)

                if over_odds == 0 or under_odds == 0:
                    continue

                # 5. Calculate probabilities
                try:
                    # Implied probabilities (with vig)
                    p_over_imp = american_to_prob(over_odds)
                    p_under_imp = american_to_prob(under_odds)

                    # Vig (house edge)
                    vig = calculate_vig(p_over_imp, p_under_imp)

                    # No-vig (fair) probabilities
                    p_over_fair, p_under_fair = devig(p_over_imp, p_under_imp)

                    # Build result
                    result = BookmakerResult(
                        bookmaker=bookmaker_key,
                        line=line,
                        over_odds=over_odds,
                        under_odds=under_odds,
                        p_over_imp=round(p_over_imp, 4),
                        p_under_imp=round(p_under_imp, 4),
                        vig=round(vig, 4),
                        p_over_fair=round(p_over_fair, 4),
                        p_under_fair=round(p_under_fair, 4),
                        fetched_at=snapshot.fetched_at
                    )
                    results.append(result)
                    fair_probs_for_consensus.append((p_over_fair, p_under_fair))

                except (ValueError, ZeroDivisionError):
                    # Calculation error, skip this bookmaker
                    continue

        # 6. Calculate market consensus
        consensus = None
        if fair_probs_for_consensus:
            consensus_probs = calculate_consensus_mean(fair_probs_for_consensus)
            if consensus_probs:
                consensus = Consensus(
                    method="mean",
                    p_over_fair=round(consensus_probs[0], 4),
                    p_under_fair=round(consensus_probs[1], 4)
                )

        # 7. Build response
        return NoVigResponse(
            event_id=body.event_id,
            player_name=matched_player,  # Use the matched name
            market=body.market,
            results=results,
            consensus=consensus,
            message=None if results else "No props data for this player at the selected bookmakers",
            **_snapshot_metadata(snapshot),
        )
        
    except OddsAPIError as e:
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {str(e)}"
        )


@router.get(
    "/players/suggest",
    response_model=PlayerSuggestResponse,
    summary="Player name suggestion",
    description="Get available player names for a specific game (for autocomplete)"
)
async def suggest_players(
    event_id: str = Query(..., description="Game ID"),
    q: str = Query(default="", description="Search keyword (optional)"),
    market: str = Query(default="player_points", description="Market type")
) -> PlayerSuggestResponse:
    """
    Get player name suggestions (for Autocomplete)

    GET /api/nba/players/suggest?event_id=abc123&q=cur

    Flow:
    1. Check cache
    2. If cache miss, call The Odds API for game props
    3. Extract all player names from outcomes
    4. Filter by keyword if given
    5. Store in cache and return

    Args:
        event_id: Game ID
        q: Search keyword (for filtering)
        market: Market type

    Returns:
        PlayerSuggestResponse: List of player names

    Example Response:
        {
            "players": ["Stephen Curry", "Seth Curry", "LeBron James"]
        }
    """
    try:
        snapshot = await odds_gateway.get_market_snapshot(
            sport="basketball_nba",
            event_id=event_id,
            regions="us",
            markets=market,
            odds_format="american",
            priority="interactive",
        )
        all_players = _collect_player_names(snapshot.data.get("bookmakers", []), market)
    except OddsAPIError as e:
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=str(e)
        )
    
    # 5. Filter if keyword is given
    if q:
        q_lower = q.lower()
        all_players = [p for p in all_players if q_lower in p.lower()]
    
    return PlayerSuggestResponse(
        players=all_players,
        **_snapshot_metadata(snapshot),
    )


# ==================== CSV Player History Data API ====================

@router.get(
    "/csv/players",
    response_model=CSVPlayersResponse,
    summary="Get CSV player list",
    description="Get all player names from CSV file (for autocomplete)"
)
async def get_csv_players(
    q: str = Query(default="", description="Search keyword (optional)")
) -> CSVPlayersResponse:
    """
    Get player names from the CSV file

    GET /api/nba/csv/players?q=curry

    This endpoint reads player names from data/nba_player_game_logs.csv
    Used for frontend player autocomplete

    Args:
        q: Search keyword (case-insensitive)

    Returns:
        CSVPlayersResponse: List of player names

    Example Response:
        {
            "players": ["Stephen Curry", "Seth Curry"],
            "total": 2
        }
    """
    try:
        players = csv_player_service.get_all_players(search=q if q else None)
        return CSVPlayersResponse(
            players=players,
            total=len(players)
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read CSV: {str(e)}"
        )


@router.post(
    "/csv/reload",
    summary="Reload CSV data",
    description="Force clear cache and reload CSV file"
)
async def reload_csv():
    """
    Force reload CSV data

    Used for:
    - Refreshing data after CSV file updates
    - Clearing cache after code changes

    POST /api/nba/csv/reload

    Returns:
        dict: Reload result, including player count
    """
    try:
        csv_player_service.reload()
        return {
            "success": True,
            "message": "CSV data reloaded",
            "total_players": len(csv_player_service.get_all_players())
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Reload failed: {str(e)}"
        )


@router.get(
    "/player-history",
    response_model=PlayerHistoryResponse,
    summary="Get player historical stats",
    description="Calculate empirical probability and distribution for player historical data on a specified metric"
)
async def get_player_history(
    player: str = Query(..., description="Player name"),
    metric: str = Query(
        default="points",
        description="Stat metric: points, assists, rebounds, pra (points+rebounds+assists)"
    ),
    threshold: float = Query(..., description="Threshold (e.g. 24.5)"),
    n: int = Query(
        default=0,
        ge=0,
        description="Last N games, 0 means all"
    ),
    bins: int = Query(
        default=15,
        ge=5,
        le=50,
        description="Histogram bins (5-50)"
    ),
    exclude_dnp: bool = Query(
        default=True,
        description="Exclude DNP (Did Not Play, 0 minutes) games"
    ),
    opponent: Optional[str] = Query(
        default=None,
        description="Opponent filter (team name), None means all"
    ),
    is_starter: Optional[bool] = Query(
        default=None,
        description="Starter filter: True (starter only), False (bench only), None (all)"
    ),
    teammate_filter: Optional[str] = Query(
        default=None,
        description="Star teammate filter, comma separated (e.g. 'Giannis Antetokounmpo,Khris Middleton')"
    ),
    teammate_played: Optional[bool] = Query(
        default=None,
        description="Star teammate played filter: True (all played), False (all DNP), None (no filter)"
    )
) -> PlayerHistoryResponse:
    """
    Get player historical statistical summary

    GET /api/nba/player-history?player=Stephen+Curry&metric=points&threshold=24.5
    GET /api/nba/player-history?player=Stephen+Curry&metric=points&threshold=24.5&opponent=Lakers
    GET /api/nba/player-history?player=Stephen+Curry&metric=points&threshold=24.5&is_starter=true

    This endpoint computes the "empirical probability" of a player on a statistic,
    based on historical data, not model predictions!

    Probability definition (aligned with sportsbook props):
    - Over: value > threshold (strictly greater)
    - Under: value < threshold (strictly less)
    - If value == threshold, does not count toward Over or Under

    Args:
        player: Player name
        metric: Statistical metric (points/assists/rebounds/pra)
        threshold: Threshold (can be decimal, e.g. 24.5)
        n: Last N games (0 means use all history)
        bins: Histogram bin number
        exclude_dnp: Whether to exclude DNP games
        opponent: Opponent filter (optional)
        is_starter: Starter status filter (True=only starter, False=only bench, None=all)

    Returns:
        PlayerHistoryResponse: Contains probabilities, mean, stddev, game_logs, opponent list

    Example Response:
        {
            "player": "Stephen Curry",
            "metric": "points",
            "threshold": 24.5,
            "n_games": 68,
            "p_over": 0.47,
            "p_under": 0.53,
            "mean": 25.1,
            "std": 5.7,
            "game_logs": [
                {"date": "01/15", "opponent": "Lakers", "value": 28, "is_over": true},
                ...
            ],
            "opponents": ["Lakers", "Celtics", ...],
            "histogram": [...]
        }
    """
    # Validate metric param
    valid_metrics = ["points", "assists", "rebounds", "pra"]
    if metric not in valid_metrics:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid metric: {metric}. Valid: {valid_metrics}"
        )
    
    try:
        # Parse teammate_filter comma-separated string to list
        teammate_list = None
        if teammate_filter:
            teammate_list = [t.strip() for t in teammate_filter.split(",") if t.strip()]
        
        # Call CSV service for statistics
        stats = csv_player_service.get_player_stats(
            player_name=player,
            metric=metric,
            threshold=threshold,
            n=n,
            bins=bins,
            exclude_dnp=exclude_dnp,
            opponent=opponent,
            is_starter=is_starter,
            teammate_filter=teammate_list,
            teammate_played=teammate_played
        )
        
        # Convert histogram to Pydantic model
        histogram_bins = [
            HistogramBin(
                binStart=bin_data["binStart"],
                binEnd=bin_data["binEnd"],
                count=bin_data["count"]
            )
            for bin_data in stats.get("histogram", [])
        ]
        
        # Convert game_logs to Pydantic model
        game_logs = [
            GameLog(
                date=log["date"],
                date_full=log["date_full"],
                opponent=log["opponent"],
                value=log["value"],
                is_over=log["is_over"],
                team=log.get("team", ""),
                minutes=log.get("minutes", 0.0),  # Playing time
                is_starter=log.get("is_starter", False)  # Starter status
            )
            for log in stats.get("game_logs", [])
        ]
        
        return PlayerHistoryResponse(
            player=stats["player"],
            metric=stats["metric"],
            threshold=stats["threshold"],
            n_games=stats["n_games"],
            p_over=stats["p_over"],
            p_under=stats["p_under"],
            equal_count=stats.get("equal_count", 0),
            mean=stats["mean"],
            std=stats["std"],
            histogram=histogram_bins,
            game_logs=game_logs,
            opponents=stats.get("opponents", []),
            teammates=stats.get("teammates", []),
            opponent_filter=stats.get("opponent_filter"),
            teammate_filter=stats.get("teammate_filter"),
            teammate_played=stats.get("teammate_played"),
            message=stats.get("message")
        )
        
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Calculation failed: {str(e)}"
        )
