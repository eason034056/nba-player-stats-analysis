"""Fetch official NBA injury-report PDFs, slowly, and store them locally.

The fetcher itself waits at least ``MIN_GAP_SECONDS`` (1.0) between HTTP
calls. Callers do not have to sleep. A URL that is already stored, or
already recorded as 403, is not requested again during a backfill.
The live current slot may check a recorded 403 again on a later call.
That later call is the next 15-minute tick.

HTTP 403 on a URL we have never stored means the file is not there
when the body is the CDN's XML error. The CDN does not send 404. That
403 is recorded and is not retried in the same run. A run of those
403s is normal before a report is posted and does not pause the fetcher.
A 403 whose body or content type is HTML is a possible block, including
the first time that URL is seen.

A 403 on a URL we already stored as a PDF, a 200 that is not a PDF,
an HTML or XML body on a 200, or any other unexpected status is treated
as a possible block. The run pauses. 5xx, 429, and timeouts back off
and pause after ``PAUSE_AFTER_CONSECUTIVE`` failures in a row. The wait
before a retry is ``min_gap * 2^(n-1)``, capped, and is never shorter
than ``min_gap``.

If NBA blocks access or ends the agreement, stop calling this and delete
the stored files. The runtime IAM user cannot delete them. An admin does
that. This module has no delete method and does not talk to S3.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol

import httpx

from app.services.injury_report_slots import report_slot
from app.services.injury_report_store import LocalInjuryReportStore
from app.services.injury_report_types import (
    Blocked,
    Failed,
    FetchResult,
    Missing,
    RunReport,
    Stored,
)

logger = logging.getLogger(__name__)

# Crawl-Delay on NBA.com is 1. The gap lives here so a caller cannot go faster.
MIN_GAP_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 60.0
PAUSE_AFTER_CONSECUTIVE = 5
USER_AGENT = "sportslab-injury-pdf/1.0"

UTC = timezone.utc


class Clock(Protocol):
    """Now, a monotonic counter, and sleep. Tests pass ``FakeClock``."""

    def now(self) -> datetime:
        """Aware UTC time used for ``fetched_at`` and ``checked_at``."""

    def monotonic(self) -> float:
        """Seconds that only move when ``sleep`` is awaited, in tests."""

    async def sleep(self, seconds: float) -> None:
        """Wait ``seconds``. Must not be faster than the caller asked."""


class SystemClock:
    """The process clock. ``sleep`` is ``asyncio.sleep``."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        import asyncio

        await asyncio.sleep(seconds)


class FakeClock:
    """A clock that advances only inside ``sleep``.

    Tests read ``sleeps`` and ``monotonic`` to check the gap. Nothing here
    waits on the wall clock.
    """

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)
        self._mono = 0.0
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    async def sleep(self, seconds: float) -> None:
        delay = 0.0 if seconds < 0 else seconds
        self.sleeps.append(delay)
        self._mono += delay
        self._now += timedelta(seconds=delay)


class RateLimiter:
    """Space HTTP calls.

    ``acquire`` waits until ``gap`` seconds have passed since the previous
    acquire. The first acquire does not wait. ``gap`` defaults to
    ``min_gap``. A retry passes a larger ``gap``. The wait is never
    shorter than ``min_gap``.

    ``retry_gap`` is the wait after ``consecutive`` retryable failures.
    It starts at ``min_gap`` and doubles, then stops growing at ``cap``.
    It does not shrink, so a retry is never faster than the one before it
    and never faster than ``min_gap``.
    """

    def __init__(
        self,
        clock: Clock,
        *,
        min_gap: float = MIN_GAP_SECONDS,
        cap: float = BACKOFF_CAP_SECONDS,
    ) -> None:
        self.clock = clock
        self.min_gap = min_gap
        self.cap = cap
        self._last: float | None = None

    async def acquire(self, gap: float | None = None) -> None:
        needed = self.min_gap if gap is None else gap
        if needed < self.min_gap:
            needed = self.min_gap
        if self._last is not None:
            delay = needed - (self.clock.monotonic() - self._last)
            if delay > 0:
                await self.clock.sleep(delay)
        self._last = self.clock.monotonic()

    def retry_gap(self, consecutive: int) -> float:
        if consecutive < 1:
            raise ValueError("consecutive must be at least 1")
        raw = self.min_gap * (2 ** (consecutive - 1))
        if raw < self.min_gap:
            raw = self.min_gap
        if raw > self.cap:
            raw = self.cap
        return raw


def build_client() -> httpx.AsyncClient:
    """HTTP client for the CDN. Redirects are not followed.

    A redirect would be a second URL and might be an HTML page. The fetch
    loop treats a 3xx as unexpected and pauses.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"},
    )


def _parse_last_modified(raw: str | None) -> str | None:
    """UTC stamp of a Last-Modified header.

    An empty or unreadable value is None. The PDF is still stored, and
    the rest of the run continues. ``parsedate_to_datetime`` raises
    ``ValueError`` for a string that is not a date.
    """
    if raw is None or not raw.strip():
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_html(response: httpx.Response) -> bool:
    """True when the content type or the body is HTML.

    A first-seen 403 with an HTML body is a possible block. The recorded
    missing file is ``application/xml`` and starts with ``<?xml``.
    """
    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type:
        return True
    sample = response.content.lstrip()[:64].lower()
    return sample.startswith((b"<html", b"<!doctype html"))


def _is_pdf(response: httpx.Response) -> bool:
    """True when the body starts with the PDF marker and the type is not HTML or XML."""
    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type or "xml" in content_type:
        return False
    return response.content.startswith(b"%PDF-")


def _retryable_status(status: int) -> bool:
    return status == 429 or status >= 500


async def fetch_urls(
    urls: list[str],
    *,
    store: LocalInjuryReportStore,
    clock: Clock,
    client: httpx.AsyncClient,
    recheck_missing: bool = False,
    reuse_stored: bool = True,
) -> RunReport:
    """Fetch ``urls`` in order, or skip the ones already recorded.

    ``recheck_missing`` false (the backfill) does not request a URL whose
    sidecar says 403. ``recheck_missing`` true (the live slot) requests
    that URL once in this call. A stored PDF is skipped when
    ``reuse_stored`` is true, which is how the CLI runs.

    A 403 for a URL ``store.had_success`` already counts as a block even
    when ``reuse_stored`` is false. That is the "this file used to exist"
    case. The PDF on disk is left in place.

    Args:
        urls: Absolute CDN URLs. Duplicates are the caller's job.
        store: Where PDFs and sidecars go.
        clock: Sleep and timestamps. Tests pass ``FakeClock``.
        client: HTTPX client. Tests pass one with a fake transport.
        recheck_missing: True for the live current slot.
        reuse_stored: False only to re-request a URL that is already stored.

    Returns:
        A ``RunReport``. ``paused`` means the caller should stop.
    """
    limiter = RateLimiter(clock)
    results: list[FetchResult] = []
    requests_made = 0
    streak = 0
    pending: float | None = None

    for url in urls:
        existed = store.had_success(url)
        if reuse_stored:
            cached = store.get(url)
            if isinstance(cached, Stored) or (
                isinstance(cached, Missing) and not recheck_missing
            ):
                results.append(cached)
                continue

        while True:
            await limiter.acquire(pending)
            pending = None
            requests_made += 1
            try:
                response = await client.get(url)
            except httpx.TimeoutException:
                streak += 1
                if streak >= PAUSE_AFTER_CONSECUTIVE:
                    results.append(Failed(tag="error", url=url, kind="timeout", status=None))
                    return RunReport(tuple(results), paused=True, requests_made=requests_made)
                pending = limiter.retry_gap(streak)
                continue
            except httpx.TransportError:
                streak += 1
                if streak >= PAUSE_AFTER_CONSECUTIVE:
                    results.append(Failed(tag="error", url=url, kind="timeout", status=None))
                    return RunReport(tuple(results), paused=True, requests_made=requests_made)
                pending = limiter.retry_gap(streak)
                continue

            status = response.status_code
            if status == 200 and _is_pdf(response):
                raw_modified = response.headers.get("last-modified")
                stored = store.put_pdf(
                    url,
                    response.content,
                    fetched_at=clock.now(),
                    last_modified_raw=raw_modified,
                    last_modified_utc=_parse_last_modified(raw_modified),
                )
                results.append(stored)
                streak = 0
                break

            if status == 403 and not existed and not _is_html(response):
                missing = store.put_missing(url, checked_at=clock.now())
                results.append(missing)
                # A string of 403s is a report that is not posted yet.
                # It must not add to the pause streak.
                streak = 0
                break

            if _retryable_status(status):
                streak += 1
                if streak >= PAUSE_AFTER_CONSECUTIVE:
                    results.append(
                        Failed(tag="error", url=url, kind="http", status=status)
                    )
                    return RunReport(tuple(results), paused=True, requests_made=requests_made)
                pending = limiter.retry_gap(streak)
                continue

            if status == 403 and _is_html(response):
                reason = "403 body was html"
            elif status == 403 and existed:
                reason = "stored report returned 403"
            elif status == 200:
                reason = "response was not a pdf"
            else:
                reason = f"unexpected status {status}"
            logger.warning("injury pdf fetch paused (%s)", reason)
            results.append(Blocked(tag="blocked", url=url, reason=reason))
            return RunReport(tuple(results), paused=True, requests_made=requests_made)

    return RunReport(tuple(results), paused=False, requests_made=requests_made)


async def fetch_current_slot(
    now: datetime | None = None,
    *,
    store: LocalInjuryReportStore | None = None,
    clock: Clock | None = None,
    client: httpx.AsyncClient | None = None,
) -> RunReport:
    """Fetch the report slot for ``now``.

    A recorded 403 for that one URL is checked again. A stored PDF is
    not. The scheduler calls this once per 15-minute tick, and only on
    an NBA game day, and only when ``INJURY_PDF_FETCH_ENABLED`` is set.

    Args:
        now: Decision time. None means the clock's current time.
        store: Defaults to ``INJURY_PDF_DIR`` from settings.
        clock: Defaults to ``SystemClock``.
        client: Defaults to ``build_client``, closed before return.

    Returns:
        The ``RunReport`` for that single URL.
    """
    used_clock = clock or SystemClock()
    moment = now if now is not None else used_clock.now()
    slot = report_slot(moment)
    own_store = store or _default_store()
    if client is None:
        async with build_client() as owned:
            return await fetch_urls(
                [slot.url],
                store=own_store,
                clock=used_clock,
                client=owned,
                recheck_missing=True,
            )
    return await fetch_urls(
        [slot.url],
        store=own_store,
        clock=used_clock,
        client=client,
        recheck_missing=True,
    )


def _default_store() -> LocalInjuryReportStore:
    from app.settings import settings

    return LocalInjuryReportStore(Path(settings.injury_pdf_dir))
