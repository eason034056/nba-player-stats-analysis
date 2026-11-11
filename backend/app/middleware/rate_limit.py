"""
rate_limit.py - API rate limiting via slowapi.

One limiter covers the default limit and every route limit. The key is the
socket peer unless the Vercel rewrite proves it set x-real-ip / x-forwarded-for.
"""

import hmac
import ipaddress

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request

from app.settings import settings

# Frontend sends this from the Vercel rewrite. The name is the contract.
PROXY_SECRET_HEADER = "x-sportslab-proxy-secret"


def _peer_host(request: Request) -> str:
    """Socket peer. This is what slowapi used via get_remote_address."""
    client = request.client
    if client is None or not client.host:
        return "127.0.0.1"
    return client.host


def _valid_ip(value: str | None) -> str | None:
    """Return a normalized IP, or None when the header is missing or garbage."""
    if value is None:
        return None
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if text == "":
        return None
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def _forwarded_client_ip(request: Request) -> str | None:
    """Prefer x-real-ip. Otherwise the left-most x-forwarded-for entry."""
    real_ip = _valid_ip(request.headers.get("x-real-ip"))
    if real_ip is not None:
        return real_ip
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return None
    leftmost = forwarded.split(",", 1)[0]
    return _valid_ip(leftmost)


def _proxy_secret_matches(request: Request) -> bool:
    """True only when a non-empty configured secret matches the header.

    An empty secret never matches, including an empty header. The header
    value and the secret are not logged.
    """
    configured = settings.vercel_proxy_secret.get_secret_value()
    if configured == "":
        return False
    provided = request.headers.get(PROXY_SECRET_HEADER)
    if not provided:
        return False
    try:
        return hmac.compare_digest(
            provided.encode("utf-8"),
            configured.encode("utf-8"),
        )
    except (TypeError, ValueError):
        return False


def client_address_key(request: Request) -> str:
    """Key for every slowapi limit on this process.

    Trust the forwarded client IP only after the proxy secret matches.
    Every other request is bucketed by the socket peer.
    """
    peer = _peer_host(request)
    if not _proxy_secret_matches(request):
        return peer
    forwarded = _forwarded_client_ip(request)
    if forwarded is None:
        return peer
    return forwarded


limiter = Limiter(
    key_func=client_address_key,
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
