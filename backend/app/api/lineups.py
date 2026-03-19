from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import LineupRefreshResponse, LineupsResponse, TeamLineup
from app.services.lineup_service import lineup_service


router = APIRouter(
    prefix="/api/nba/lineups",
    tags=["lineups"],
)


@router.get("", response_model=LineupsResponse, summary="Get lineup consensus for a specified date")
async def get_lineups(
    date: Optional[str] = Query(default=None, description="Query date (YYYY-MM-DD), defaults to today"),
) -> LineupsResponse:
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        result = await lineup_service.get_lineups(target_date)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve lineup: {exc}") from exc

    lineups = [TeamLineup.model_validate(lineup) for lineup in result.lineups.values()]
    lineups.sort(key=lambda item: item.team)

    return LineupsResponse(
        date=target_date,
        team_count=len(lineups),
        fetched_at=result.fetched_at,
        cache_state=result.cache_state,
        lineups=lineups,
    )


@router.get("/{team}", response_model=TeamLineup, summary="Get lineup consensus for a single team")
async def get_team_lineup(
    team: str,
    date: Optional[str] = Query(default=None, description="Query date (YYYY-MM-DD), defaults to today"),
) -> TeamLineup:
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        lineup, _cache_state, _fetched_at = await lineup_service.get_team_lineup(target_date, team)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve team lineup: {exc}") from exc

    if lineup is None:
        raise HTTPException(status_code=404, detail=f"No lineup data found for {team} on {target_date}")

    return TeamLineup.model_validate(lineup)


@router.post("/refresh", response_model=LineupRefreshResponse, summary="Manually refresh lineup consensus data")
async def refresh_lineups(
    date: Optional[str] = Query(default=None, description="Refresh date (YYYY-MM-DD), defaults to today"),
) -> LineupRefreshResponse:
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        lineups = await lineup_service.fetch_and_store(target_date)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to refresh lineup: {exc}") from exc

    return LineupRefreshResponse(
        date=target_date,
        team_count=len(lineups),
        message=f"Successfully refreshed lineup data for {len(lineups)} teams",
    )
