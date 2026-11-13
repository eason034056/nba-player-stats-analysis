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
from typing import Optional

from app.models.schemas import DailyPicksResponse
from app.services.daily_analysis import (
    HIGH_PROBABILITY_THRESHOLD,
    MIN_SAMPLE_GAMES,
    STORED_MIN_SAMPLE_GAMES,
    daily_analysis_service,
    daily_picks_cache_key,
    present_daily_picks,
)
from app.services.cache import cache_service
from app.services.slate_date import nba_slate_date


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
    description=(
        "Retrieve NBA picks whose combined_probability is at least "
        "min_probability (default 0.65) and whose sample is at least "
        "min_games (default 10). The stored candidates still include "
        "historical Lean rows. probability on each row stays the "
        "historical hit rate."
    )
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
        default=HIGH_PROBABILITY_THRESHOLD,
        ge=0.5,
        le=0.95,
        description=(
            "Minimum combined_probability (0.5-0.95). "
            "Default 0.65 is the published board. "
            "0.56 returns stored rows whose combined probability is Lean. "
            "This is not the historical hit rate. That rate is still "
            "probability on each row."
        ),
    ),
    min_games: int = Query(
        default=MIN_SAMPLE_GAMES,
        ge=STORED_MIN_SAMPLE_GAMES,
        le=100,
        description=(
            "Minimum number of sample games. "
            "Default 10 is the published board. "
            "Stored NBA rows go down to 5."
        ),
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
        date = nba_slate_date()[0]
    
    # Default timezone offset is UTC+8 (Taipei time)
    offset_minutes = tz_offset if tz_offset is not None else 480
    
    try:
        # Run analysis (uses cache automatically, unless refresh=True).
        # The stored set includes NBA candidates down to the Lean floor.
        # This filter is what keeps the default response on the 0.65 / 10 board.
        result = await daily_analysis_service.run_daily_analysis(
            date=date,
            use_cache=not refresh,
            tz_offset_minutes=offset_minutes
        )
        return present_daily_picks(
            result,
            min_probability=min_probability,
            min_games=min_games,
        )
        
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
        date = nba_slate_date()[0]
    
    # Default timezone offset is UTC+8 (Taipei time)
    offset_minutes = tz_offset if tz_offset is not None else 480
    
    try:
        # Force re-analysis (ignore cache). The service caches the
        # candidate set, including Lean rows. The body of this call stays
        # the published board, matching the GET default.
        result = await daily_analysis_service.run_daily_analysis(
            date=date,
            use_cache=False,
            tz_offset_minutes=offset_minutes
        )
        return present_daily_picks(result)
        
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
        date = nba_slate_date()[0]
    
    # Default timezone offset is UTC+8
    offset_minutes = tz_offset if tz_offset is not None else 480
    
    # The live NBA key, the previous unversioned NBA key, and the
    # pre-league keys. Readers only use the versioned key.
    keys = (
        daily_picks_cache_key("nba", date, offset_minutes),
        f"daily_picks:nba:{date}:tz{offset_minutes}",
        f"daily_picks:{date}:tz{offset_minutes}",
        f"daily_picks:{date}",
    )
    
    try:
        for key in keys:
            await cache_service.delete(key)
        return {
            "success": True,
            "message": f"Cleared analysis cache for {date}"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear cache: {str(e)}"
        )

