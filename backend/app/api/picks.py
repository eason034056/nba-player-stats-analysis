"""
picks.py - AI Picks API for Discord bot integration

Provides a bot-friendly endpoint for today's AI-generated picks:
  GET /api/picks/today - Returns today's picks in structured JSON

Features:
- API key authentication (via X-API-Key header)
- Two tiers: free (delayed by configurable minutes) and premium (real-time)
- Rate limiting for bot polling
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.middleware.rate_limit import limiter
from app.services.daily_analysis import daily_analysis_service
from app.settings import settings


# ---------------------------------------------------------------------------
# Response models (bot-friendly, slimmed down from DailyPick)
# ---------------------------------------------------------------------------

class BotPick(BaseModel):
    """Single AI pick formatted for Discord bot consumption."""
    game: str = Field(..., description="Matchup string, e.g. 'Lakers @ Warriors'")
    player: str = Field(..., description="Player name")
    team: str = Field(default="", description="Player team code")
    pick_type: str = Field(..., description="Pick category: spread, total, or moneyline (currently maps to metric)")
    metric: str = Field(..., description="Stat metric (points/rebounds/assists/pra)")
    direction: str = Field(..., description="over or under")
    line: float = Field(..., description="Betting line threshold")
    confidence: float = Field(..., description="Confidence score (0-1)")
    reasoning: str = Field(..., description="Short reasoning summary")
    projected_value: Optional[float] = Field(default=None, description="AI-projected stat value")
    edge: Optional[float] = Field(default=None, description="Edge vs line (projected - line)")
    sample_size: int = Field(..., description="Number of historical games used")
    commence_time: str = Field(..., description="Game start time (ISO 8601)")


class BotPicksResponse(BaseModel):
    """Response for GET /api/picks/today."""
    date: str = Field(..., description="Picks date (YYYY-MM-DD)")
    tier: str = Field(..., description="free or premium")
    delayed_minutes: Optional[int] = Field(
        default=None,
        description="Minutes picks were delayed (free tier only)",
    )
    total_picks: int = Field(..., description="Number of picks returned")
    picks: List[BotPick] = Field(default_factory=list, description="AI picks list")
    analyzed_at: str = Field(..., description="When the analysis ran (ISO 8601)")


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def _extract_api_key(request: Request) -> str:
    """Extract and validate the bot API key from request headers."""
    api_key = request.headers.get("X-API-Key", "").strip()
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    all_keys = settings.bot_api_keys_set
    if not all_keys:
        # No keys configured — reject all requests
        raise HTTPException(status_code=503, detail="Bot API keys not configured")
    if api_key not in all_keys:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key


def _is_premium(api_key: str) -> bool:
    return api_key in settings.bot_api_keys_premium_set


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_METRIC_TO_PICK_TYPE = {
    "points": "total",
    "rebounds": "total",
    "assists": "total",
    "pra": "total",
}


def _build_reasoning(pick) -> str:
    """Generate a concise reasoning string from a DailyPick."""
    parts = []
    parts.append(
        f"Hit {pick.direction} {pick.threshold} {pick.metric} in "
        f"{pick.probability:.0%} of last {pick.n_games} games."
    )
    if pick.has_projection and pick.projected_value is not None:
        parts.append(f"Projected {pick.projected_value} {pick.metric}.")
    if pick.edge is not None:
        direction_word = "above" if pick.edge > 0 else "below"
        parts.append(f"Edge: {abs(pick.edge):.1f} {direction_word} line.")
    if pick.opponent_rank is not None:
        parts.append(f"Opp defense rank: {pick.opponent_rank}/30.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/picks",
    tags=["picks-bot"],
)


@router.get(
    "/today",
    response_model=BotPicksResponse,
    summary="Get today's AI picks for Discord bot",
    description="Returns today's AI-generated picks. Requires X-API-Key header. "
                "Free-tier keys receive picks delayed by 1 hour; premium keys get real-time picks.",
)
@limiter.limit(settings.rate_limit_bot_picks)
async def get_picks_today(
    request: Request,
    api_key: str = Depends(_extract_api_key),
    tz_offset: Optional[int] = Query(
        default=None,
        description="Timezone offset in minutes (e.g. 480 for UTC+8, -300 for EST)",
    ),
    min_confidence: float = Query(
        default=0.65,
        ge=0.5,
        le=0.95,
        description="Minimum confidence threshold (0.5-0.95)",
    ),
) -> BotPicksResponse:
    """
    GET /api/picks/today

    Headers:
        X-API-Key: <your-bot-api-key>

    Query params:
        tz_offset: timezone offset in minutes (default 480 / UTC+8)
        min_confidence: minimum confidence score (default 0.65)
    """
    premium = _is_premium(api_key)
    offset_minutes = tz_offset if tz_offset is not None else 480
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        result = await daily_analysis_service.run_daily_analysis(
            date=today,
            use_cache=True,
            tz_offset_minutes=offset_minutes,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis unavailable: {e}")

    # Filter by confidence
    picks = [p for p in result.picks if p.probability >= min_confidence]

    # Free tier: filter out picks from games starting within the delay window
    delayed_minutes: Optional[int] = None
    if not premium:
        delay = settings.bot_picks_free_delay_minutes
        delayed_minutes = delay
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=delay)
        filtered = []
        for p in picks:
            try:
                commence = datetime.fromisoformat(
                    p.commence_time.replace("Z", "+00:00")
                )
                # Only include picks whose game starts AFTER the delay cutoff
                # (i.e., analysis was available > delay minutes ago relative to game time)
                if commence > cutoff:
                    # Game hasn't started yet but picks are delayed:
                    # only show if analysis was at least `delay` minutes old
                    analyzed_at = datetime.fromisoformat(
                        result.analyzed_at.replace("Z", "+00:00")
                    )
                    if (datetime.now(timezone.utc) - analyzed_at).total_seconds() >= delay * 60:
                        filtered.append(p)
                else:
                    # Game already started / in past — always show
                    filtered.append(p)
            except (ValueError, TypeError):
                # Can't parse commence_time — include anyway
                filtered.append(p)
        picks = filtered

    # Convert to bot-friendly format
    bot_picks = []
    for p in picks:
        bot_picks.append(
            BotPick(
                game=f"{p.away_team} @ {p.home_team}",
                player=p.player_name,
                team=p.player_team_code or p.player_team,
                pick_type=_METRIC_TO_PICK_TYPE.get(p.metric, "total"),
                metric=p.metric,
                direction=p.direction,
                line=p.threshold,
                confidence=p.probability,
                reasoning=_build_reasoning(p),
                projected_value=p.projected_value,
                edge=p.edge,
                sample_size=p.n_games,
                commence_time=p.commence_time,
            )
        )

    return BotPicksResponse(
        date=today,
        tier="premium" if premium else "free",
        delayed_minutes=delayed_minutes,
        total_picks=len(bot_picks),
        picks=bot_picks,
        analyzed_at=result.analyzed_at,
    )
