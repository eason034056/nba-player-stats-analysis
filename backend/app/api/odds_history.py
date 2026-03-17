"""
odds_history.py - Odds History API Endpoint

Provides query and manual triggering functionality for line snapshot data, for Line Movement Tracking.

Endpoints:
- GET  /api/nba/odds-history           - Query the odds line snapshot history for a player/market
- POST /api/nba/odds-history/snapshot  - Manually trigger a line snapshot

Data source:
    odds_line_snapshots table (periodically written by odds_snapshot_service)

Usage:
    # Query line movement of Stephen Curry's player_points on 2026-02-08
    GET /api/nba/odds-history?player_name=Stephen Curry&market=player_points&date=2026-02-08

    # Manually trigger today's snapshot
    POST /api/nba/odds-history/snapshot?date=2026-02-08
"""

from datetime import datetime, timezone
from typing import Optional, Dict, List
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query

from app.services.db import db_service
from app.services.odds_snapshot_service import odds_snapshot_service
from app.models.schemas import (
    OddsLineSnapshot,
    OddsConsensus,
    OddsSnapshotGroup,
    OddsHistoryResponse,
    OddsSnapshotTriggerResponse,
)

# Create the router
# prefix: All endpoints start with /api/nba/odds-history
# tags: Group label in the Swagger documentation
router = APIRouter(
    prefix="/api/nba/odds-history",
    tags=["odds-history"],
)

# Query SQL: retrieve all snapshot data for the specified player/market/date
# Sort by snapshot_at and bookmaker for later grouping by time
QUERY_HISTORY_SQL = """
SELECT
    snapshot_at,
    bookmaker,
    line,
    over_odds,
    under_odds,
    vig,
    over_fair_prob,
    under_fair_prob
FROM odds_line_snapshots
WHERE player_name = $1
  AND market = $2
  AND date = $3
ORDER BY snapshot_at ASC, bookmaker ASC
"""


@router.get(
    "",
    response_model=OddsHistoryResponse,
    summary="Query Odds Line History",
    description="""
    Query all line snapshots for a specified player, market, and date.

    Returns a time-ordered list of snapshots. Each snapshot contains:
    - Per-bookmaker lines, odds, no-vig probabilities
    - Market consensus (average no-vig probability across all bookmakers)

    Used for Line Movement Tracking: observe how lines change from opening to closing.
    """
)
async def get_odds_history(
    player_name: str = Query(
        ...,
        description="Player name (e.g. Stephen Curry)"
    ),
    market: str = Query(
        ...,
        description="Market type (player_points, player_rebounds, player_assists, player_points_rebounds_assists)"
    ),
    date: Optional[str] = Query(
        default=None,
        description="Game date (YYYY-MM-DD), defaults to today"
    ),
):
    """
    Query odds line history snapshots.

    Query all snapshots for the specified player/market/date from the odds_line_snapshots table,
    group by snapshot_at, with each group containing the no-vig results for each bookmaker.
    Consensus (AVG) is calculated on the fly during the query and not stored elsewhere.

    Args:
        player_name: Player name (required)
        market: Market type (required)
        date: Game date, defaults to UTC today

    Returns:
        OddsHistoryResponse: List of snapshots sorted by time

    Example:
        GET /api/nba/odds-history?player_name=Stephen Curry&market=player_points&date=2026-02-08
    """
    if not db_service.is_connected:
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL is not connected, cannot query odds history"
        )

    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Validate market
    valid_markets = [
        "player_points", "player_rebounds",
        "player_assists", "player_points_rebounds_assists",
    ]
    if market not in valid_markets:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid market: {market}. Valid values: {valid_markets}"
        )

    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        rows = await db_service.fetch(QUERY_HISTORY_SQL, player_name, market, date_obj)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query odds history: {str(e)}"
        )

    # Group by snapshot_at
    # defaultdict(list): automatically creates an empty list for new keys
    # All bookmaker rows at the same time are grouped together
    groups: Dict[str, list] = defaultdict(list)
    for row in rows:
        # snapshot_at might be a datetime object, convert to ISO string as key
        snap_time = row["snapshot_at"]
        if isinstance(snap_time, datetime):
            snap_key = snap_time.isoformat()
        else:
            snap_key = str(snap_time)

        groups[snap_key].append(row)

    # Build response
    snapshots: List[OddsSnapshotGroup] = []

    for snap_key, group_rows in groups.items():
        # Line data for each bookmaker
        lines = [
            OddsLineSnapshot(
                bookmaker=r["bookmaker"],
                line=float(r["line"]) if r["line"] is not None else None,
                over_odds=int(r["over_odds"]) if r["over_odds"] is not None else None,
                under_odds=int(r["under_odds"]) if r["under_odds"] is not None else None,
                vig=float(r["vig"]) if r["vig"] is not None else None,
                over_fair_prob=float(r["over_fair_prob"]) if r["over_fair_prob"] is not None else None,
                under_fair_prob=float(r["under_fair_prob"]) if r["under_fair_prob"] is not None else None,
            )
            for r in group_rows
        ]

        # Calculate consensus (average no-vig probability)
        # Only include rows with both over_fair_prob and under_fair_prob present
        valid_probs = [
            r for r in group_rows
            if r["over_fair_prob"] is not None and r["under_fair_prob"] is not None
        ]

        consensus = None
        if valid_probs:
            n = len(valid_probs)
            avg_over = sum(float(r["over_fair_prob"]) for r in valid_probs) / n
            avg_under = sum(float(r["under_fair_prob"]) for r in valid_probs) / n

            # Average line value
            valid_lines = [float(r["line"]) for r in valid_probs if r["line"] is not None]
            avg_line = sum(valid_lines) / len(valid_lines) if valid_lines else None

            consensus = OddsConsensus(
                over_fair_prob=round(avg_over, 4),
                under_fair_prob=round(avg_under, 4),
                avg_line=round(avg_line, 2) if avg_line is not None else None,
                bookmaker_count=n,
            )

        snapshots.append(
            OddsSnapshotGroup(
                snapshot_at=snap_key,
                lines=lines,
                consensus=consensus,
            )
        )

    return OddsHistoryResponse(
        date=date,
        player_name=player_name,
        market=market,
        snapshot_count=len(snapshots),
        snapshots=snapshots,
    )


@router.post(
    "/snapshot",
    response_model=OddsSnapshotTriggerResponse,
    summary="Manually Trigger Odds Snapshot",
    description="""
    Manually trigger a snapshot, immediately capture all event line data and write to PostgreSQL.

    Common use cases:
    - Manual updates outside of the scheduler
    - Testing snapshot functionality
    - Capturing line changes at specific moments (e.g. after big injury news)
    """
)
async def trigger_snapshot(
    date: Optional[str] = Query(
        default=None,
        description="Snapshot date (YYYY-MM-DD), defaults to today"
    ),
):
    """
    Manually trigger an odds line snapshot.

    Directly call odds_snapshot_service.take_snapshot(),
    captures all event odds, computes no-vig, writes to PostgreSQL.

    Args:
        date: Snapshot date, defaults to UTC today

    Returns:
        OddsSnapshotTriggerResponse: Snapshot execution result summary
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        result = await odds_snapshot_service.take_snapshot(date)

        return OddsSnapshotTriggerResponse(
            date=result["date"],
            event_count=result["event_count"],
            total_lines=result["total_lines"],
            duration_ms=result["duration_ms"],
            message=(
                f"Successfully captured {result['total_lines']} odds line records "
                f"({result['event_count']} events, took {result['duration_ms']}ms)"
            ),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Odds snapshot failed: {str(e)}"
        )
