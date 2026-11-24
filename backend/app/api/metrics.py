"""
metrics.py - Observability metrics endpoint.

Exposes request counts, latency averages, error rates,
and the BALLDONTLIE rate status.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter

from app.middleware.logging_config import get_metrics_snapshot
from app.services.odds_gateway import PROVIDERS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["observability"])


@router.get(
    "/metrics",
    summary="Application Metrics",
    description="Request stats, latency, error rates, and BALLDONTLIE rate status",
)
async def get_metrics():
    snapshot = get_metrics_snapshot()

    # Last BALLDONTLIE rate-limit headers on the NBA provider.
    # ``recorded`` is false until a response has carried a header.
    # A failure here is an empty rate, not a 500.
    rate_info = None
    try:
        rate = await PROVIDERS["nba"].rate_status()
    except Exception:
        logger.warning("bdl rate status unavailable")
        rate = None
    if rate is not None and rate.recorded:
        rate_info = {
            "remaining": rate.remaining,
            "used": rate.used,
            "total": rate.total,
            "remaining_ratio": (
                round(rate.remaining_ratio, 4)
                if rate.remaining_ratio is not None
                else None
            ),
        }

    return {
        "time": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": snapshot["uptime_seconds"],
        "requests": snapshot["request_counts"],
        "errors": snapshot["error_counts"],
        "avg_latency_ms": snapshot["avg_latency_ms"],
        "bdl_rate": rate_info,
    }
