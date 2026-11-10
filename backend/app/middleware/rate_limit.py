"""
rate_limit.py - API rate limiting via slowapi.

Applies per-IP rate limits to protect backend resources and
prevent abuse of expensive upstream API calls.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.settings import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.rate_limit_default],
    storage_uri=settings.redis_url,
    # Redis down must not 500 the request. The in-memory fallback keeps
    # the same limits for this process. swallow_errors covers a failure
    # of that fallback too: the route still answers, and slowapi logs it.
    swallow_errors=True,
    in_memory_fallback_enabled=True,
)


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": "Rate limit exceeded", "detail": str(exc.detail)},
    )


def install_rate_limiter(app: FastAPI) -> None:
    """Attach the slowapi limiter and error handler to the FastAPI app."""
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
