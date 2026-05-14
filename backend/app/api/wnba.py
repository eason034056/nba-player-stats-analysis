"""
wnba.py - WNBA related API endpoints (Phase 1, SPO-32)

Sibling of backend/app/api/nba.py. Phase 1 is the data layer + read-only
frontend for WNBA — no /events, no /no-vig, no agent integration (Phase 2+).

Endpoints (4):
1. GET  /api/wnba/csv/players         — paginated player listing
2. POST /api/wnba/csv/reload          — admin cache reload
3. GET  /api/wnba/player-history      — per-player game log + Over/Under
4. GET  /api/wnba/player-dd-history   — per-player Double-Double rate
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.models.schemas import (
    CSVPlayersResponse,
    PlayerHistoryResponse,
    PlayerDDHistoryResponse,
    HistogramBin,
    GameLog,
)
from app.services.csv_player_history import (
    wnba_csv_player_service,
    CONTINUOUS_METRIC_EXTRACTORS,
)


router = APIRouter(prefix="/api/wnba", tags=["wnba"])


@router.get(
    "/csv/players",
    response_model=CSVPlayersResponse,
    summary="Get WNBA CSV player list",
    description="Get all WNBA player names from the CSV file (for autocomplete)",
)
async def get_csv_players(
    q: str = Query(default="", description="Search keyword (case-insensitive)"),
) -> CSVPlayersResponse:
    """Get WNBA player names from data/wnba_player_game_logs.csv."""
    try:
        players = wnba_csv_player_service.get_all_players(search=q if q else None)
        return CSVPlayersResponse(players=players, total=len(players))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read WNBA CSV: {str(e)}")


@router.post(
    "/csv/reload",
    summary="Reload WNBA CSV data",
    description="Force clear cache and reload the WNBA CSV file",
)
async def reload_csv():
    """Force reload WNBA CSV data."""
    try:
        wnba_csv_player_service.reload()
        return {
            "success": True,
            "message": "WNBA CSV data reloaded",
            "total_players": len(wnba_csv_player_service.get_all_players()),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"WNBA CSV reload failed: {str(e)}")


@router.get(
    "/player-history",
    response_model=PlayerHistoryResponse,
    summary="Get WNBA player historical stats",
    description="Calculate empirical probability and distribution for a WNBA player's historical data on a specified metric.",
)
async def get_player_history(
    player: str = Query(..., description="Player name"),
    metric: str = Query(default="points", description="Stat metric: points, assists, rebounds, pra, etc."),
    threshold: float = Query(..., description="Threshold (e.g. 20.5)"),
    n: int = Query(default=0, ge=0, description="Last N games, 0 means all"),
    bins: int = Query(default=15, ge=5, le=50, description="Histogram bins (5-50)"),
    exclude_dnp: bool = Query(default=True, description="Exclude DNP (Did Not Play, 0 minutes) games"),
    opponent: Optional[str] = Query(default=None, description="Opponent filter (team name), None means all"),
    is_starter: Optional[bool] = Query(default=None, description="Starter filter"),
    teammate_filter: Optional[str] = Query(default=None, description="Comma-separated teammate names"),
    teammate_played: Optional[bool] = Query(default=None, description="Teammate played filter"),
) -> PlayerHistoryResponse:
    """Get WNBA player historical statistical summary."""
    valid_metrics = sorted(CONTINUOUS_METRIC_EXTRACTORS.keys())
    if metric not in valid_metrics:
        hint = ""
        if metric in ("dd", "double_double"):
            hint = " — DD is binary; use GET /api/wnba/player-dd-history instead."
        raise HTTPException(status_code=400, detail=f"Invalid metric: {metric}. Valid: {valid_metrics}{hint}")

    try:
        teammate_list = None
        if teammate_filter:
            teammate_list = [t.strip() for t in teammate_filter.split(",") if t.strip()]

        stats = wnba_csv_player_service.get_player_stats(
            player_name=player,
            metric=metric,
            threshold=threshold,
            n=n,
            bins=bins,
            exclude_dnp=exclude_dnp,
            opponent=opponent,
            is_starter=is_starter,
            teammate_filter=teammate_list,
            teammate_played=teammate_played,
        )

        histogram_bins = [
            HistogramBin(binStart=b["binStart"], binEnd=b["binEnd"], count=b["count"])
            for b in stats.get("histogram", [])
        ]
        game_logs = [
            GameLog(
                date=log["date"],
                date_full=log["date_full"],
                opponent=log["opponent"],
                value=log["value"],
                is_over=log["is_over"],
                team=log.get("team", ""),
                minutes=log.get("minutes", 0.0),
                is_starter=log.get("is_starter", False),
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
            message=stats.get("message"),
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"WNBA player history calculation failed: {str(e)}")


@router.get(
    "/player-dd-history",
    response_model=PlayerDDHistoryResponse,
    summary="Get WNBA player Double-Double historical rate",
    description="Compute historical P(DD = 1) for a WNBA player. DD is binary (Yes/No), no threshold.",
)
async def get_player_dd_history(
    player: str = Query(..., description="Player name (fuzzy-matched if exact match fails)"),
    season: Optional[str] = Query(default=None, description="Season filter; None means all seasons"),
) -> PlayerDDHistoryResponse:
    """Get WNBA player Double-Double historical rate."""
    try:
        stats = wnba_csv_player_service.player_dd_history(player_name=player, season=season)
        return PlayerDDHistoryResponse(
            player=stats["player"],
            season=stats.get("season"),
            n_games=stats.get("n_games", 0),
            dd_games=stats.get("dd_games", 0),
            prob_dd=stats.get("prob_dd"),
            message=stats.get("message"),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"WNBA DD history calculation failed: {str(e)}")
