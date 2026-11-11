"""
bdl_client.py - BALLDONTLIE HTTP client.

This module only talks to https://api.balldontlie.io. It is not imported by
a route, the scheduler, or the odds gateway. A later ticket wires it in.

Authentication is the raw API key in the Authorization header
(``Authorization: <BALLDONTLIE_API_KEY>``). The setting is a ``SecretStr``.
The client calls ``get_secret_value()`` and keeps a plain ``str``. A
constructor ``api_key`` overrides that and is also a plain ``str``. The key
is never written to a log line or to ``repr``.

Paths below are the paths in the recorded captures under
``backend/tests/fixtures/bdl/``:

- ``GET /v1/games``
- ``GET /v1/players`` (query key ``player_ids[]``, not ``ids[]``)
- ``GET /v1/player_injuries``
- ``GET /v2/odds/player_props``
- ``GET /v2/odds``
- ``GET /nba/v1/projected_lineups``

The 429 capture is ``GET /nba/v1/lineups``. This client does not call that
path. The capture is only evidence for the rate-limit headers.

Pagination is cursor based. ``meta.next_cursor`` may be missing or null.
``iter_pages`` follows it. No recorded request shows the page-2 query
string; the outgoing name is ``cursor`` because that is the argument the
list methods take and the value ``meta.next_cursor`` already is.
"""

from __future__ import annotations

import inspect
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import redis.asyncio as redis_async

from app.settings import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.balldontlie.io"

# Recorded request paths. Do not rename these to match a remembered doc.
_PATH_GAMES = "/v1/games"
_PATH_PLAYERS = "/v1/players"
_PATH_INJURIES = "/v1/player_injuries"
_PATH_PLAYER_PROPS = "/v2/odds/player_props"
_PATH_ODDS = "/v2/odds"
_PATH_PROJECTED_LINEUPS = "/nba/v1/projected_lineups"

_MAX_ATTEMPTS = 3
_FALLBACK_BACKOFF_SECONDS = 60.0
_MAX_WAIT_SECONDS = 65.0
_WINDOW_TTL_SECONDS = 120
_OBSERVED_LIMIT_TTL_SECONDS = 86400
_MAX_PLAYER_IDS_PER_CALL = 100
_OBSERVED_LIMIT_KEY = "bdl:ratelimit:v1:observed_limit"
_PAUSE_UNTIL_KEY = "bdl:ratelimit:v1:pause_until"
_ACQUIRE_ATTEMPTS = 8

SleepFn = Callable[[float], Awaitable[None]]
ClockFn = Callable[[], float]


class BdlError(Exception):
    """Base error for the BALLDONTLIE client.

    Raised for transport failures, a non-JSON success body, a refused
    ``list_players`` batch, or a rate limiter that cannot run safely.
    """


class BdlRateLimitError(BdlError):
    """Raised when a call is still HTTP 429 after three attempts.

    ``reset`` is the last ``x-ratelimit-reset`` epoch second, or ``None``
    when the header was missing. ``status_code`` is always 429.
    """

    def __init__(self, message: str, *, reset: int | None = None) -> None:
        super().__init__(message)
        self.reset = reset
        self.status_code = 429


class BdlApiError(BdlError):
    """Raised for a non-2xx response that is not a retryable 429.

    5xx is retried with the same bounded backoff as 429. This error is
    what remains after those retries, and what a 4xx other than 429
    raises immediately. ``status_code`` is the HTTP status.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def _parse_header_int(value: str | None) -> int | None:
    """Parse one rate-limit header. Blank or non-numeric becomes ``None``."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _window_key(window_start: int) -> str:
    """Redis key for one clock minute.

    ``window_start`` is the epoch second the minute began. The next minute
    is a different key, so processes share a budget without a lease that
    lives forever. The 120 second TTL only deletes the old key.
    """
    return f"bdl:ratelimit:v1:window:{window_start}"


def _with_page(
    params: list[tuple[str, str]],
    *,
    per_page: int,
    cursor: int | None,
) -> list[tuple[str, str]]:
    """Append ``per_page`` and, when the caller asked for a later page, ``cursor``."""
    paged = list(params)
    paged.append(("per_page", str(per_page)))
    if cursor is not None:
        paged.append(("cursor", str(cursor)))
    return paged


async def _default_sleep(seconds: float) -> None:
    """Wait without blocking the event loop. Tests replace this."""
    import asyncio

    await asyncio.sleep(seconds)


class BdlClient:
    """Async client for the BALLDONTLIE NBA endpoints used by Sports Lab.

    Construct it with the defaults in production. Tests pass ``transport``,
    ``redis``, ``sleep``, and ``clock`` so no network call and no real
    wait happens.

    The shared budget is a Redis counter keyed by the current minute.
    ``BDL_RATE_LIMIT_PER_MIN`` (default 5) is the limit until a response
    includes ``x-ratelimit-limit``. That value is stored for one day
    (``bdl:ratelimit:v1:observed_limit``, TTL 86400). A day with no
    response falls back to ``BDL_RATE_LIMIT_PER_MIN``. Before a call, a
    spent budget waits until that minute ends. A response with
    ``x-ratelimit-remaining: 0``, or an HTTP 429, writes
    ``bdl:ratelimit:v1:pause_until`` so every process waits out the
    server window. The server reset is not aligned to the clock minute.
    Any wait derived from ``x-ratelimit-reset`` is capped at 65 seconds
    so a clock that is behind the server cannot sleep for an hour.

    Usage:
        client = BdlClient()
        page = await client.list_games(dates=["2026-11-11"])
        await client.aclose()
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        redis: redis_async.Redis | None = None,
        base_url: str = BASE_URL,
        rate_limit_per_min: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepFn | None = None,
        clock: ClockFn | None = None,
        timeout: float = 30.0,
    ) -> None:
        if api_key is None:
            # SecretStr stays out of repr. The header needs a plain str.
            api_key = settings.balldontlie_api_key.get_secret_value()
        if rate_limit_per_min is None:
            rate_limit_per_min = settings.bdl_rate_limit_per_min
        if rate_limit_per_min < 1:
            raise BdlError("BDL_RATE_LIMIT_PER_MIN must be at least 1")

        self._api_key = api_key
        self._configured_limit = rate_limit_per_min
        self._sleep = sleep or _default_sleep
        self._clock = clock or time.time
        self._last_limit: int | None = None
        self._last_remaining: int | None = None
        self._last_reset: int | None = None
        # Reset epoch we already waited for. Stops a capped 65s wait from
        # repeating while the stored reset is still in the future.
        self._pause_observed: int | None = None

        if redis is None:
            self._redis = redis_async.from_url(settings.redis_url, decode_responses=True)
            self._owns_redis = True
        else:
            self._redis = redis
            self._owns_redis = False

        # The key lives only in this default header. Nothing logs the header map.
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": api_key},
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        """Close the HTTP client and, if this object opened Redis, that connection too."""
        await self._http.aclose()
        if self._owns_redis:
            await self._redis.close()

    def __repr__(self) -> str:
        """Identify the client without the API key."""
        return (
            f"BdlClient(base_url={self._http.base_url!s}, "
            f"rate_limit_per_min={self._configured_limit})"
        )

    def rate_status(self) -> dict[str, int | None]:
        """Return the last ``limit``, ``remaining``, and ``reset`` header values.

        Does not call the network. Values stay ``None`` until a response
        has carried that header. ``reset`` is the epoch second from
        ``x-ratelimit-reset``.
        """
        return {
            "limit": self._last_limit,
            "remaining": self._last_remaining,
            "reset": self._last_reset,
        }

    async def list_games(
        self,
        *,
        dates: list[str],
        per_page: int = 100,
        cursor: int | None = None,
    ) -> dict[str, Any]:
        """List NBA games for one or more calendar dates.

        Calls ``GET /v1/games``. The recorded query uses a repeated
        ``dates[]`` parameter, not a comma-joined string. ``dates`` are
        the Eastern game dates the API stores on each game.

        Returns the raw JSON object (``data`` plus ``meta``). Pass
        ``cursor`` from ``meta.next_cursor`` to read the next page, or
        use ``iter_pages``. An empty ``dates`` list raises ``BdlError``
        before a budget slot is taken: the API would otherwise return an
        unfiltered page.
        """
        if not dates:
            raise BdlError("list_games requires at least one date")
        params = [("dates[]", date) for date in dates]
        return await self._get(_PATH_GAMES, _with_page(params, per_page=per_page, cursor=cursor))

    async def list_players(
        self,
        *,
        player_ids: list[int],
        per_page: int = 100,
        cursor: int | None = None,
    ) -> dict[str, Any]:
        """Fetch players by BALLDONTLIE id.

        Calls ``GET /v1/players``. The query key is ``player_ids[]``.
        ``ids[]`` is ignored by the API and must not be sent. One call
        carries at most 100 ids, which is the recorded maximum page size.
        A longer list raises ``BdlError`` before a request is sent, so
        the caller splits the batch instead of silently dropping ids.

        Returns the raw JSON object. An empty ``player_ids`` list raises
        ``BdlError`` before a budget slot is taken, because the API then
        returns the first page of every player.
        """
        if not player_ids:
            raise BdlError("list_players requires at least one player_id")
        if len(player_ids) > _MAX_PLAYER_IDS_PER_CALL:
            raise BdlError("list_players accepts at most 100 player_ids per call")
        params = [("player_ids[]", str(player_id)) for player_id in player_ids]
        return await self._get(
            _PATH_PLAYERS,
            _with_page(params, per_page=per_page, cursor=cursor),
        )

    async def list_player_injuries(
        self,
        *,
        cursor: int | None = None,
        per_page: int = 100,
    ) -> dict[str, Any]:
        """List current player injuries, one page at a time.

        Calls ``GET /v1/player_injuries``. The recorded first page has
        ``meta.next_cursor``. Pass that value as ``cursor``, or use
        ``iter_pages``. The signature is keyword-only because a later
        ticket calls it by these names.

        Returns the raw JSON object.
        """
        return await self._get(
            _PATH_INJURIES,
            _with_page([], per_page=per_page, cursor=cursor),
        )

    async def get_player_props(self, *, game_id: int) -> dict[str, Any]:
        """Fetch every player prop currently posted for one game.

        Calls ``GET /v2/odds/player_props?game_id=``. The recorded body is
        a single object: ``meta.per_page`` is the row count, and there is
        no ``next_cursor``. Do not paginate this call.

        Returns the raw JSON object.
        """
        return await self._get(_PATH_PLAYER_PROPS, [("game_id", str(game_id))])

    async def list_odds(
        self,
        *,
        dates: list[str],
        per_page: int = 100,
        cursor: int | None = None,
    ) -> dict[str, Any]:
        """List game lines (spread, moneyline, total) for one or more dates.

        Calls ``GET /v2/odds``. That path is the one in
        ``odds_2026-11-11.json``, not ``/v1/odds``. The recorded query uses
        repeated ``dates[]``. ``meta.next_cursor`` is how later pages are
        addressed when a date has more than ``per_page`` rows.

        Returns the raw JSON object. An empty ``dates`` list raises
        ``BdlError`` before a budget slot is taken.
        """
        if not dates:
            raise BdlError("list_odds requires at least one date")
        params = [("dates[]", date) for date in dates]
        return await self._get(_PATH_ODDS, _with_page(params, per_page=per_page, cursor=cursor))

    async def list_projected_lineups(self, *, game_ids: list[int]) -> dict[str, Any]:
        """Fetch projected lineups for the given games.

        Calls ``GET /nba/v1/projected_lineups``. That path is the one in
        ``projected_lineups_21718080.json``. The query key is a repeated
        ``game_ids[]``. The recorded request does not send ``per_page``
        or ``cursor``, so this method does not either.

        Returns the raw JSON object. An empty ``game_ids`` list raises
        ``BdlError`` before a budget slot is taken.
        """
        if not game_ids:
            raise BdlError("list_projected_lineups requires at least one game_id")
        params = [("game_ids[]", str(game_id)) for game_id in game_ids]
        return await self._get(_PATH_PROJECTED_LINEUPS, params)

    async def _get(self, path: str, params: list[tuple[str, str]]) -> dict[str, Any]:
        """GET ``path`` inside the shared budget, retrying 429 and 5xx.

        Three HTTP responses are the maximum. A 429 sleeps until
        ``x-ratelimit-reset`` (or 60 seconds when that header is missing
        or already past) and then tries again. That wait, and the
        ``remaining == 0`` pause, never exceed 65 seconds. A 5xx uses
        that same wait. Any other non-2xx raises ``BdlApiError``
        immediately. A transport error waits 60 seconds and tries again.
        The wait is ``self._sleep``, so a test clock can skip the real delay.

        Retry backoff is at most 2 times 65 seconds: two waits between the
        three attempts. Each attempt may also wait for a budget slot, up
        to 8 waits, and each of those is capped at 65 seconds. The real
        bound is ``3 * 8 * 65 + 2 * 65`` = 1690 seconds.
        """
        last_status: int | None = None
        for attempt in range(_MAX_ATTEMPTS):
            await self._acquire_budget()
            try:
                response = await self._http.get(path, params=params)
            except httpx.HTTPError as exc:
                logger.warning(
                    "bdl_request path=%s transport_error=%s",
                    path,
                    type(exc).__name__,
                )
                if attempt == _MAX_ATTEMPTS - 1:
                    raise BdlError(
                        f"BALLDONTLIE request failed for {path}: {type(exc).__name__}"
                    ) from exc
                await self._sleep_for(_FALLBACK_BACKOFF_SECONDS)
                continue

            await self._record_rate_headers(response)
            status = response.status_code
            self._log_response(path, status)
            if 200 <= status < 300:
                return self._json_body(path, response)

            last_status = status
            if status != 429 and status < 500:
                raise BdlApiError(
                    f"BALLDONTLIE returned HTTP {status} for {path}",
                    status,
                )
            if attempt == _MAX_ATTEMPTS - 1:
                break
            self._mark_waited_for(_parse_header_int(response.headers.get("x-ratelimit-reset")))
            await self._sleep_for(self._backoff_seconds(response))

        if last_status == 429:
            raise BdlRateLimitError(
                f"BALLDONTLIE rate limit persisted for {path}",
                reset=self._last_reset,
            )
        raise BdlApiError(
            f"BALLDONTLIE returned HTTP {last_status} for {path}",
            last_status or 0,
        )

    def _json_body(self, path: str, response: httpx.Response) -> dict[str, Any]:
        """Parse a success body. The recorded successes are JSON objects."""
        try:
            body = response.json()
        except ValueError as exc:
            raise BdlError(f"BALLDONTLIE returned a non-JSON body for {path}") from exc
        if not isinstance(body, dict):
            raise BdlError(f"BALLDONTLIE returned a non-object body for {path}")
        return body

    def _log_response(self, path: str, status: int) -> None:
        """Log the path, status, and rate-limit numbers. Never the headers map.

        The Authorization value is not an argument here, so it cannot land
        in the message.
        """
        logger.info(
            "bdl_request path=%s status=%s limit=%s remaining=%s reset=%s",
            path,
            status,
            self._last_limit,
            self._last_remaining,
            self._last_reset,
        )

    def _backoff_seconds(self, response: httpx.Response) -> float:
        """How long to wait before another try of this response.

        A future ``x-ratelimit-reset`` is the server's window end, so the
        wait ends there, but never later than 65 seconds. A missing header,
        or a reset that is not still in the future, waits 60 seconds. Zero
        is never returned: a tight retry loop would burn the shared key.
        """
        reset = _parse_header_int(response.headers.get("x-ratelimit-reset"))
        if reset is None:
            return _FALLBACK_BACKOFF_SECONDS
        delay = float(reset) - self._clock()
        if delay <= 0:
            return _FALLBACK_BACKOFF_SECONDS
        return self._clamp_wait(delay)

    def _clamp_wait(self, delay: float) -> float:
        """Cap a server-window wait at 65 seconds.

        A clock that is behind the API would otherwise sleep until a reset
        that is hours away. The warning records the two durations only.
        """
        if delay > _MAX_WAIT_SECONDS:
            logger.warning(
                "bdl_rate_limit_clock_skew delay_s=%.0f clamped_s=%.0f",
                delay,
                _MAX_WAIT_SECONDS,
            )
            return _MAX_WAIT_SECONDS
        return delay

    def _mark_waited_for(self, reset: int | None) -> None:
        """Remember a reset we are about to sleep for, so acquire does not sleep again."""
        if reset is None:
            return
        if self._clock() < reset:
            self._pause_observed = reset

    async def _sleep_for(self, seconds: float) -> None:
        """Sleep for ``seconds``, or 60 when that delay is not positive.

        If the injected clock does not move, raise instead of looping.
        """
        delay = float(seconds)
        if delay <= 0:
            delay = _FALLBACK_BACKOFF_SECONDS
        started = self._clock()
        await self._sleep(delay)
        if self._clock() <= started:
            raise BdlError("rate limiter sleep returned without time advancing")

    async def _acquire_budget(self) -> None:
        """Take one slot in the current minute, waiting when the minute is full.

        Also waits out a server window stored in Redis (or remembered on
        this client) when the last response said ``remaining`` is 0 or
        was HTTP 429. That wait is capped at 65 seconds and happens once
        per reset value.
        """
        for _ in range(_ACQUIRE_ATTEMPTS):
            now = self._clock()
            pause_until = await self._pause_target(now)
            if pause_until is not None and self._pause_observed != pause_until:
                self._pause_observed = pause_until
                await self._sleep_for(self._clamp_wait(pause_until - now))
                continue

            window_start = int(now) // 60 * 60
            window_end = window_start + 60
            limit = await self._effective_limit()
            if await self._reserve(window_start, limit):
                return
            await self._sleep_for(window_end - self._clock())

        raise BdlRateLimitError("shared per-minute budget was still exhausted after waiting")

    async def _pause_target(self, now: float) -> int | None:
        """Epoch second every process should wait for, or ``None`` when the window is open."""
        candidates: list[int] = []
        try:
            raw = await self._redis.get(_PAUSE_UNTIL_KEY)
        except redis_async.RedisError:
            logger.warning("bdl_rate_limit_redis_error op=get_pause")
            raise BdlError("BALLDONTLIE rate limiter could not reach Redis") from None
        parsed = _parse_header_int(str(raw)) if raw is not None else None
        if parsed is not None and now < parsed:
            candidates.append(parsed)
        if (
            self._last_remaining == 0
            and self._last_reset is not None
            and now < self._last_reset
        ):
            candidates.append(self._last_reset)
        if not candidates:
            return None
        return max(candidates)

    async def _effective_limit(self) -> int:
        """Observed ``x-ratelimit-limit`` when Redis has one, else the configured limit."""
        try:
            raw = await self._redis.get(_OBSERVED_LIMIT_KEY)
        except redis_async.RedisError:
            logger.warning("bdl_rate_limit_redis_error op=get_limit")
            raise BdlError("BALLDONTLIE rate limiter could not reach Redis") from None
        if raw is not None:
            parsed = _parse_header_int(str(raw))
            if parsed is not None and parsed >= 1:
                return parsed
        return self._configured_limit

    async def _reserve(self, window_start: int, limit: int) -> bool:
        """Atomically take one count in this minute. False means the minute is full.

        ``INCR`` then ``DECR`` when the count passes the limit keeps the
        stored count at the limit. A caller who sees False does not send
        HTTP. Two processes racing past the limit both decrement, so neither
        sends an extra call.
        """
        key = _window_key(window_start)
        try:
            # INCR and EXPIRE in one transaction so a crash between them
            # cannot leave a window key with no TTL.
            pipe = self._redis.pipeline(transaction=True)
            pipe.incr(key)
            pipe.expire(key, _WINDOW_TTL_SECONDS)
            count, _expired = await pipe.execute()
            count = int(count)
            if count > limit:
                await self._redis.decr(key)
                return False
        except redis_async.RedisError:
            logger.warning("bdl_rate_limit_redis_error op=reserve")
            raise BdlError("BALLDONTLIE rate limiter could not reach Redis") from None
        return True

    async def _record_rate_headers(self, response: httpx.Response) -> None:
        """Remember the three rate-limit headers and publish the observed limit.

        Publishing to Redis is what lets another process on the same key
        pick up 5/min or 600/min without a restart. The observed limit
        lives for one day; after that the configured
        ``BDL_RATE_LIMIT_PER_MIN`` is used again. A failed publish does
        not discard a response the server already accepted.
        """
        limit = _parse_header_int(response.headers.get("x-ratelimit-limit"))
        remaining = _parse_header_int(response.headers.get("x-ratelimit-remaining"))
        reset = _parse_header_int(response.headers.get("x-ratelimit-reset"))
        if limit is not None:
            self._last_limit = limit
        if remaining is not None:
            self._last_remaining = remaining
        if reset is not None:
            self._last_reset = reset
        if response.status_code == 429 or remaining == 0:
            await self._publish_pause(reset)
        if limit is None:
            return
        try:
            await self._redis.set(
                _OBSERVED_LIMIT_KEY,
                str(limit),
                ex=_OBSERVED_LIMIT_TTL_SECONDS,
            )
        except redis_async.RedisError:
            logger.warning("bdl_rate_limit_redis_error op=set_limit")

    async def _publish_pause(self, reset: int | None) -> None:
        """Share the server reset with other processes. Best effort.

        The TTL is the seconds until reset, capped at 65, so a skewed
        clock cannot pin the pause for the rest of the day.
        """
        if reset is None:
            return
        delay = reset - self._clock()
        if delay <= 0:
            return
        ttl = max(1, int(min(delay, _MAX_WAIT_SECONDS)))
        try:
            await self._redis.set(_PAUSE_UNTIL_KEY, str(reset), ex=ttl)
        except redis_async.RedisError:
            logger.warning("bdl_rate_limit_redis_error op=set_pause")


async def iter_pages(
    fetch: Callable[..., Awaitable[dict[str, Any]]],
    **kwargs: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Yield each page from a list method, following ``meta.next_cursor``.

    ``fetch`` is ``list_games``, ``list_players``, ``list_player_injuries``,
    or ``list_odds``. Keyword arguments are forwarded on every page
    (``dates``, ``player_ids``, ``per_page``). ``cursor`` may be passed to
    start later than the first page.

    The loop stops when ``meta`` is missing, ``next_cursor`` is missing,
    ``next_cursor`` is null, or the next cursor is the one just requested.
    A method that has no ``cursor`` parameter (player props, projected
    lineups) is yielded once.

    Usage:
        async for page in iter_pages(client.list_player_injuries):
            rows = page["data"]
    """
    parameters = inspect.signature(fetch).parameters
    accepts_cursor = "cursor" in parameters
    cursor = kwargs.pop("cursor", None)
    while True:
        if accepts_cursor:
            page = await fetch(cursor=cursor, **kwargs)
        else:
            page = await fetch(**kwargs)
        yield page
        if not accepts_cursor:
            return
        meta = page.get("meta") if isinstance(page, dict) else None
        next_cursor = meta.get("next_cursor") if isinstance(meta, dict) else None
        if next_cursor is None or next_cursor == cursor:
            return
        cursor = next_cursor
