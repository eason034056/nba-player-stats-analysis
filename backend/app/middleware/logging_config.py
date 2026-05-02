"""
logging_config.py - Structured JSON logging configuration.

Configures Python's logging to emit JSON-formatted log lines for
machine-parseable observability.
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.settings import settings


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Merge any extra structured fields attached to the record
        for key in ("endpoint", "method", "status_code", "duration_ms",
                     "client_ip", "quota_remaining", "quota_used"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val
        return json.dumps(log_entry, default=str)


def setup_logging() -> None:
    """Configure root logger with JSON output."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicate output
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# In-process metrics counters (lightweight, no external dependency)
# ---------------------------------------------------------------------------

_request_counts: Dict[str, int] = {}
_error_counts: Dict[str, int] = {}
_latency_sums: Dict[str, float] = {}
_latency_counts: Dict[str, int] = {}

_start_time: float = time.monotonic()


def get_metrics_snapshot() -> Dict[str, Any]:
    """Return a point-in-time snapshot of collected metrics."""
    uptime = time.monotonic() - _start_time
    avg_latencies = {}
    for path, total in _latency_sums.items():
        count = _latency_counts.get(path, 1)
        avg_latencies[path] = round(total / count, 2)
    return {
        "uptime_seconds": round(uptime, 1),
        "request_counts": dict(_request_counts),
        "error_counts": dict(_error_counts),
        "avg_latency_ms": avg_latencies,
    }


def reset_metrics() -> None:
    """Reset all counters (useful for tests)."""
    _request_counts.clear()
    _error_counts.clear()
    _latency_sums.clear()
    _latency_counts.clear()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request/response with timing and update in-process metrics."""

    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        path = request.url.path
        method = request.method

        response: Response = await call_next(request)

        duration_ms = round((time.monotonic() - start) * 1000, 2)
        status = response.status_code

        # Update counters
        key = f"{method} {path}"
        _request_counts[key] = _request_counts.get(key, 0) + 1
        _latency_sums[key] = _latency_sums.get(key, 0.0) + duration_ms
        _latency_counts[key] = _latency_counts.get(key, 0) + 1
        if status >= 400:
            err_key = f"{status} {path}"
            _error_counts[err_key] = _error_counts.get(err_key, 0) + 1

        logger = logging.getLogger("request")
        logger.info(
            "%s %s %s %.0fms",
            method,
            path,
            status,
            duration_ms,
            extra={
                "endpoint": path,
                "method": method,
                "status_code": status,
                "duration_ms": duration_ms,
                "client_ip": request.client.host if request.client else None,
            },
        )

        return response
