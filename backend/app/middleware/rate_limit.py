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
    """Prefer x-real-ip. Otherwise the left-most x-forwarded-for entry.

    x-real-ip has to win. Caddy, with no trusted_proxies, replaces
    X-Forwarded-For with the TCP peer it accepted, which for a Vercel
    rewrite is the egress address. Frontend #63 sets x-real-ip to the
    browser address. That header is not hop-by-hop, so Caddy leaves it.
    """
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

    An empty secret never matches, including an empty or whitespace-only
    header. Leading and trailing spaces are ignored so a padded SSM value
    still matches the trimmed Vercel value. The header value and the
    secret are not logged. This function only answers the comparison.
    ProxySecretMiddleware rejects the request when proxy_secret_required
    is true.
    """
    configured = settings.vercel_proxy_secret.get_secret_value().strip()
    if configured == "":
        return False
    provided = request.headers.get(PROXY_SECRET_HEADER)
    if provided is None:
        return False
    provided = provided.strip()
    if provided == "":
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

    Trust x-real-ip, or else the left-most x-forwarded-for entry, only
    after the proxy secret matches. Every other request uses
    request.client.host.

    On the production host, uvicorn --proxy-headers rewrites
    request.client from X-Forwarded-For before this function runs, and
    only when the TCP peer is Caddy at 172.30.133.10. The fallback is
    therefore the TCP client Caddy accepted: a Vercel egress address, or
    a direct client. It is not the Caddy container. That value is not
    spoofable while the Caddyfile has no trusted_proxies, because Caddy
    replaces X-Forwarded-For instead of appending to it. Adding
    trusted_proxies would keep a client-supplied chain and needs a
    security re-review.
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


# remote-up.sh and the compose healthcheck call these without the header.
HEALTH_PATHS = {"/api/health", "/health"}


def _is_health_path(path: str) -> bool:
    """True for the health routes, with or without a trailing slash."""
    return path.rstrip("/") in HEALTH_PATHS


class ProxySecretMiddleware:
    """Reject non-health requests when PROXY_SECRET_REQUIRED is true.

    The default is false, so local runs and tests stay open. Production
    compose sets the flag. /api/health and /health stay open so the host
    healthcheck can run without the header. A missing, blank, or wrong
    secret is 403. The response does not include the secret or the header.
    The check runs for every HTTP method, including OPTIONS and SSE,
    before the route.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not settings.proxy_secret_required:
            await self.app(scope, receive, send)
            return
        if _is_health_path(scope.get("path") or ""):
            await self.app(scope, receive, send)
            return
        if _proxy_secret_matches(Request(scope)):
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            status_code=403,
            content={"detail": "A valid proxy secret is required."},
        )
        await response(scope, receive, send)


def require_configured_proxy_secret() -> None:
    """Stop startup when the flag is on and the secret is empty.

    The message does not include the secret. Settings construction
    rejects the same combination, and the lifespan calls this again.
    """
    if not settings.proxy_secret_required:
        return
    if settings.vercel_proxy_secret.get_secret_value().strip() == "":
        raise RuntimeError(
            "PROXY_SECRET_REQUIRED is true but VERCEL_PROXY_SECRET is empty"
        )


def install_rate_limiter(app: FastAPI) -> None:
    """Attach the proxy-secret check, the slowapi limiter, and the 429 handler.

    SlowAPIMiddleware is added last so it runs first. A request that fails
    the secret check still counts against the rate limit.
    """
    app.state.limiter = limiter
    app.add_middleware(ProxySecretMiddleware)
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
