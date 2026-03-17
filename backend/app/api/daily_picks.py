"""
daily_picks.py - Daily High-Probability Player API Endpoints

Provides the following endpoints:
1. GET /api/nba/daily-picks - Get the list of today's high-probability player picks
2. POST /api/nba/daily-picks/trigger - Manually trigger analysis (for development/administrative use)

These endpoints allow the frontend to:
- Retrieve already analyzed high-probability player data
- Manually trigger re-analysis when needed
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from datetime import datetime, timezone
from typing import Optional

from app.models.schemas import DailyPicksResponse
from app.services.daily_analysis import daily_analysis_service
from app.services.cache import cache_service


# Create the router
# prefix: All routes will have the /api/nba prefix
# tags: For API documentation grouping
router = APIRouter(
    prefix="/api/nba",
    tags=["daily-picks"]
)


@router.get(
    "/daily-picks",
    response_model=DailyPicksResponse,
    summary="Get daily high-probability player picks",
    description="Retrieve player picks for a given date with probabilities higher than 65%"
)
async def get_daily_picks(
    date: Optional[str] = Query(
        default=None,
        description="Query date (YYYY-MM-DD), default is today",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    tz_offset: Optional[int] = Query(
        default=None,
        description="Timezone offset (minutes), e.g., 480 for UTC+8, -360 for UTC-6"
    ),
    refresh: bool = Query(
        default=False,
        description="Whether to force re-analysis (ignore cache)"
    ),
    min_probability: float = Query(
        default=0.65,
        ge=0.5,
        le=0.95,
        description="Minimum probability threshold (0.5-0.95)"
    ),
    min_games: int = Query(
        default=10,
        ge=5,
        le=100,
        description="Minimum number of sample games (5-100)"
    )
) -> DailyPicksResponse:
    """
    Get daily high-probability player picks
    
    GET /api/nba/daily-picks?date=2026-01-24
    GET /api/nba/daily-picks?refresh=true  # Force re-analysis
    
    This endpoint returns all player picks for the day that meet or exceed the probability threshold.
    Analysis process:
    1. Get all NBA games for the given day
    2. For each game, get all player props (points, rebounds, assists, PRA)
    3. Calculate the mode of bookmaker lines as the threshold
    4. Compute over/under probabilities from historical data
    5. Filter for results above the probability threshold
    
    Args:
        date: The query date (YYYY-MM-DD), default is today
        refresh: Whether to force re-analysis
        min_probability: Minimum probability threshold
        min_games: Minimum number of sample games
    
    Returns:
        DailyPicksResponse: List of high-probability player picks
    
    Example Response:
        {
            "date": "2026-01-24",
            "analyzed_at": "2026-01-24T12:00:00Z",
            "total_picks": 15,
            "picks": [
                {
                    "player_name": "Stephen Curry",
                    "event_id": "abc123",
                    "home_team": "Warriors",
                    "away_team": "Lakers",
                    "metric": "points",
                    "threshold": 24.5,
                    "direction": "over",
                    "probability": 0.73,
                    "n_games": 68
                }
            ],
            "stats": {...}
        }
    """
    # Determine query date
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Default timezone offset is UTC+8 (Taipei time)
    offset_minutes = tz_offset if tz_offset is not None else 480
    
    try:
        # Run analysis (uses cache automatically, unless refresh=True)
        result = await daily_analysis_service.run_daily_analysis(
            date=date,
            use_cache=not refresh,
            tz_offset_minutes=offset_minutes
        )
        
        # Filter results by parameters
        if result.picks:
            filtered_picks = [
                pick for pick in result.picks
                if pick.probability >= min_probability
                and pick.n_games >= min_games
            ]
            result.picks = filtered_picks
            result.total_picks = len(filtered_picks)
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}"
        )


@router.post(
    "/daily-picks/trigger",
    response_model=DailyPicksResponse,
    summary="Manually trigger daily analysis",
    description="Manually trigger re-analysis (for development/administrative purposes)"
)
async def trigger_daily_analysis(
    date: Optional[str] = Query(
        default=None,
        description="Analysis date (YYYY-MM-DD), default is today",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    tz_offset: Optional[int] = Query(
        default=None,
        description="Timezone offset (minutes), e.g., 480 for UTC+8"
    )
) -> DailyPicksResponse:
    """
    Manually trigger daily analysis
    
    POST /api/nba/daily-picks/trigger?date=2026-01-24
    
    This endpoint is used to manually trigger a re-analysis, ignoring cache.
    Mainly used for:
    - Development testing
    - Administrators needing to force update data
    - Called by scheduled jobs
    
    Args:
        date: Analysis date (YYYY-MM-DD), default is today
        tz_offset: Timezone offset (minutes)
    
    Returns:
        DailyPicksResponse: New analysis result
    """
    # Determine analysis date
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Default timezone offset is UTC+8 (Taipei time)
    offset_minutes = tz_offset if tz_offset is not None else 480
    
    try:
        # Force re-analysis (ignore cache)
        result = await daily_analysis_service.run_daily_analysis(
            date=date,
            use_cache=False,
            tz_offset_minutes=offset_minutes
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}"
        )


@router.delete(
    "/daily-picks/cache",
    summary="Clear analysis cache",
    description="Clear analysis cache for a specified date"
)
async def clear_daily_picks_cache(
    date: Optional[str] = Query(
        default=None,
        description="Date to clear the cache for (YYYY-MM-DD), default is today",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    tz_offset: Optional[int] = Query(
        default=None,
        description="Timezone offset (minutes), e.g., 480 for UTC+8"
    )
) -> dict:
    """
    Clear daily analysis cache
    
    DELETE /api/nba/daily-picks/cache?date=2026-01-24
    
    Args:
        date: The date to clear the cache for
        tz_offset: Timezone offset
    
    Returns:
        {"success": True, "message": "..."}
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Default timezone offset is UTC+8
    offset_minutes = tz_offset if tz_offset is not None else 480
    
    # Clear new-style cache key
    cache_key_new = f"daily_picks:{date}:tz{offset_minutes}"
    # Also clear old-style cache key (for backward compatibility)
    cache_key_old = f"daily_picks:{date}"
    
    try:
        await cache_service.delete(cache_key_new)
        await cache_service.delete(cache_key_old)
        return {
            "success": True,
            "message": f"Cleared analysis cache for {date}"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear cache: {str(e)}"
        )

