"""
metrics.py - Observability metrics endpoint.

Exposes request counts, latency averages, error rates,
Odds API quota status, and cache health in a single JSON payload.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter

from app.middleware.logging_config import get_metrics_snapshot
from app.services.odds_gateway import odds_gateway

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["observability"])


@router.get(
    "/metrics",
    summary="Application Metrics",
    description="Request stats, latency, error rates, and Odds API quota status",
)
async def get_metrics():
    snapshot = get_metrics_snapshot()

    # Odds API quota
    quota_usage = await odds_gateway.get_quota_usage()
    quota_protected = await odds_gateway.is_quota_protected()

    quota_info = None
    if quota_usage:
        quota_info = {
            "remaining": quota_usage.remaining,
            "used": quota_usage.used,
            "total": quota_usage.total,
            "remaining_ratio": (
                round(quota_usage.remaining_ratio, 4)
                if quota_usage.remaining_ratio is not None
                else None
            ),
            "quota_protected": quota_protected,
        }

    return {
        "time": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": snapshot["uptime_seconds"],
        "requests": snapshot["request_counts"],
        "errors": snapshot["error_counts"],
        "avg_latency_ms": snapshot["avg_latency_ms"],
        "odds_api_quota": quota_info,
    }
