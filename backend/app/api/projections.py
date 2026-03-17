"""
projections.py - API endpoints for Player Projections

Provides REST API endpoints for player projection data, supporting frontend queries and manual refresh.

Endpoints:
- GET  /api/nba/projections          - Get all player projections for a specified date
- GET  /api/nba/projections/{player} - Get projection for a single player
- POST /api/nba/projections/refresh  - Manually refresh projection data

Data Sources:
    SportsDataIO Projected Player Game Stats API
    Uses a composite fetching strategy via projection_service (Redis + PostgreSQL)

Usage Examples:
    # Get all player projections for today
    GET /api/nba/projections?date=2026-02-08

    # Get a specific player's projection
    GET /api/nba/projections/Stephen Curry?date=2026-02-08

    # Manual refresh (force API call)
    POST /api/nba/projections/refresh?date=2026-02-08
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.services.projection_service import projection_service
from app.services.projection_provider import SportsDataProjectionError
from app.models.schemas import (
    PlayerProjection,
    ProjectionsResponse,
    ProjectionRefreshResponse,
)


# Create the router
# prefix: All endpoints begin with /api/nba/projections
# tags: Group label in Swagger docs
router = APIRouter(
    prefix="/api/nba/projections",
    tags=["projections"],
)


@router.get(
    "",
    response_model=ProjectionsResponse,
    summary="Get player projections",
    description="""
    Retrieve projections data for all players on a specified date.

    Fetching strategy:
    1. Prefer reading from Redis cache
    2. If cache is expired, triggers background refresh
    3. If cache miss, synchronously calls SportsDataIO API

    **Note**: InjuryStatus / LineupStatus will be null for the Free Trial version.
    """
)
async def get_projections(
    date: Optional[str] = Query(
        default=None,
        description="Query date (YYYY-MM-DD), defaults to today"
    ),
):
    """
    Get all player projections for the specified date

    Args:
        date: Game date in YYYY-MM-DD format.
              If not provided, today in UTC is used.

    Returns:
        ProjectionsResponse: Response containing all player projections

    Example:
        GET /api/nba/projections?date=2026-02-08
    """
    # Default to today (UTC)
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        projections_dict = await projection_service.get_projections(date)
    except SportsDataProjectionError as e:
        raise HTTPException(
            status_code=502,
            detail=f"SportsDataIO API error: {e.message}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve projections: {str(e)}"
        )

    # Convert dict to list of PlayerProjection
    projections_list = []
    for player_name, proj_data in projections_dict.items():
        try:
            projection = PlayerProjection(
                player_id=proj_data.get("player_id"),
                player_name=player_name,
                team=proj_data.get("team"),
                position=proj_data.get("position"),
                opponent=proj_data.get("opponent"),
                home_or_away=proj_data.get("home_or_away"),
                minutes=proj_data.get("minutes"),
                points=proj_data.get("points"),
                rebounds=proj_data.get("rebounds"),
                assists=proj_data.get("assists"),
                steals=proj_data.get("steals"),
                blocked_shots=proj_data.get("blocked_shots"),
                turnovers=proj_data.get("turnovers"),
                pra=proj_data.get("pra"),
                field_goals_made=proj_data.get("field_goals_made"),
                field_goals_attempted=proj_data.get("field_goals_attempted"),
                three_pointers_made=proj_data.get("three_pointers_made"),
                three_pointers_attempted=proj_data.get("three_pointers_attempted"),
                free_throws_made=proj_data.get("free_throws_made"),
                free_throws_attempted=proj_data.get("free_throws_attempted"),
                started=proj_data.get("started"),
                lineup_confirmed=proj_data.get("lineup_confirmed"),
                injury_status=proj_data.get("injury_status"),
                injury_body_part=proj_data.get("injury_body_part"),
                opponent_rank=proj_data.get("opponent_rank"),
                opponent_position_rank=proj_data.get("opponent_position_rank"),
                draftkings_salary=proj_data.get("draftkings_salary"),
                fanduel_salary=proj_data.get("fanduel_salary"),
                fantasy_points_dk=proj_data.get("fantasy_points_dk"),
                fantasy_points_fd=proj_data.get("fantasy_points_fd"),
                usage_rate_percentage=proj_data.get("usage_rate_percentage"),
                player_efficiency_rating=proj_data.get("player_efficiency_rating"),
            )
            projections_list.append(projection)
        except Exception as e:
            # Malformed single player projection data does not affect overall results
            print(f"⚠️ Player projection format error ({player_name}): {e}")
            continue

    # Sort by player name
    projections_list.sort(key=lambda p: p.player_name)

    return ProjectionsResponse(
        date=date,
        player_count=len(projections_list),
        fetched_at=datetime.now(timezone.utc).isoformat(),
        projections=projections_list,
    )


@router.get(
    "/{player_name}",
    response_model=PlayerProjection,
    summary="Get single player projection",
    description="Get a player's projection for a specified date."
)
async def get_player_projection(
    player_name: str,
    date: Optional[str] = Query(
        default=None,
        description="Query date (YYYY-MM-DD), defaults to today"
    ),
):
    """
    Get a single player's projection

    Args:
        player_name: Player's name (URL path parameter)
        date: Game date

    Returns:
        PlayerProjection: Player's projection data

    Raises:
        404: Player projection not found

    Example:
        GET /api/nba/projections/Stephen%20Curry?date=2026-02-08
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        proj = await projection_service.get_player_projection(date, player_name)
    except SportsDataProjectionError as e:
        raise HTTPException(
            status_code=502,
            detail=f"SportsDataIO API error: {e.message}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve player projection: {str(e)}"
        )

    if proj is None:
        raise HTTPException(
            status_code=404,
            detail=f"Projection for {player_name} on {date} not found"
        )

    return PlayerProjection(
        player_id=proj.get("player_id"),
        player_name=player_name,
        team=proj.get("team"),
        position=proj.get("position"),
        opponent=proj.get("opponent"),
        home_or_away=proj.get("home_or_away"),
        minutes=proj.get("minutes"),
        points=proj.get("points"),
        rebounds=proj.get("rebounds"),
        assists=proj.get("assists"),
        steals=proj.get("steals"),
        blocked_shots=proj.get("blocked_shots"),
        turnovers=proj.get("turnovers"),
        pra=proj.get("pra"),
        field_goals_made=proj.get("field_goals_made"),
        field_goals_attempted=proj.get("field_goals_attempted"),
        three_pointers_made=proj.get("three_pointers_made"),
        three_pointers_attempted=proj.get("three_pointers_attempted"),
        free_throws_made=proj.get("free_throws_made"),
        free_throws_attempted=proj.get("free_throws_attempted"),
        started=proj.get("started"),
        lineup_confirmed=proj.get("lineup_confirmed"),
        injury_status=proj.get("injury_status"),
        injury_body_part=proj.get("injury_body_part"),
        opponent_rank=proj.get("opponent_rank"),
        opponent_position_rank=proj.get("opponent_position_rank"),
        draftkings_salary=proj.get("draftkings_salary"),
        fanduel_salary=proj.get("fanduel_salary"),
        fantasy_points_dk=proj.get("fantasy_points_dk"),
        fantasy_points_fd=proj.get("fantasy_points_fd"),
        usage_rate_percentage=proj.get("usage_rate_percentage"),
        player_efficiency_rating=proj.get("player_efficiency_rating"),
    )


@router.post(
    "/refresh",
    response_model=ProjectionRefreshResponse,
    summary="Manually refresh projections",
    description="""
    Force refresh of projections by calling SportsDataIO API and updating cache/database.

    Typical use cases:
    - Manual update outside of scheduler
    - Confirm the latest lineup changes
    - Troubleshooting
    """
)
async def refresh_projections(
    date: Optional[str] = Query(
        default=None,
        description="Refresh date (YYYY-MM-DD), defaults to today"
    ),
):
    """
    Manually trigger projections refresh

    Calls SportsDataIO API directly, updating Redis and PostgreSQL.

    Args:
        date: Game date

    Returns:
        ProjectionRefreshResponse: Refresh result

    Example:
        POST /api/nba/projections/refresh?date=2026-02-08
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        projections = await projection_service.fetch_and_store(date)

        return ProjectionRefreshResponse(
            date=date,
            player_count=len(projections),
            message=f"Successfully refreshed {len(projections)} player projections"
        )

    except SportsDataProjectionError as e:
        raise HTTPException(
            status_code=502,
            detail=f"SportsDataIO API error: {e.message}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to refresh projections: {str(e)}"
        )
