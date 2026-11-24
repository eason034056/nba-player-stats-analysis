"""SPO-149: official NBA injury-report PDF fetch.

Filename mapping, the 1 second gap, cache skips, and 403 handling are
behavior tests: HTTP calls, files written, and gaps on a fake clock.
Recorded CDN fixtures are status lines and headers. The body is a hash
and a length. Tests replay those headers with synthetic PDF bytes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.migrations.runner import upgrade
from app.services.injury_report_fetcher import (
    MIN_GAP_SECONDS,
    USER_AGENT,
    FakeClock,
    fetch_urls,
)
from app.services.injury_report_games import has_nba_game_on, tip_times_for_season
from app.services.injury_report_slots import (
    CDN_BASE,
    MINUTE_FORMAT_START,
    decision_time,
    parse_season_start_year,
    report_slot,
    slots_for_tips,
)
from app.services.injury_report_store import LocalInjuryReportStore
from app.settings import Settings

import backend.scripts.fetch_injury_reports as cli

ET = ZoneInfo("America/New_York")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nba_injury_cdn"
SYNTHETIC = b"%PDF-1.4 synthetic"
EXISTING_URL = (
    "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2024-11-14_10AM.pdf"
)
MISSING_URL = (
    "https://ak-static.cms.nba.com/referee/injury/"
    "Injury-Report_2024-11-14_10_00AM.pdf"
)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class RecordingTransport(httpx.AsyncBaseTransport):
    """Counts calls and stamps the fake clock. The handler builds the response."""

    def __init__(self, handler, clock: FakeClock) -> None:
        self.handler = handler
        self.clock = clock
        self.times: list[float] = []
        self.urls: list[str] = []
        self.user_agents: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.times.append(self.clock.monotonic())
        self.urls.append(str(request.url))
        self.user_agents.append(request.headers.get("user-agent", ""))
        response = self.handler(request)
        response.request = request
        return response


def _client(handler, clock: FakeClock) -> tuple[httpx.AsyncClient, RecordingTransport]:
    transport = RecordingTransport(handler, clock)
    return httpx.AsyncClient(transport=transport), transport


def _pdf(headers: dict[str, str] | None = None, body: bytes = SYNTHETIC) -> httpx.Response:
    merged = {"Content-Type": "application/pdf", "Content-Length": str(len(body))}
    if headers:
        merged.update(headers)
    return httpx.Response(200, headers=merged, content=body)


def _gaps(times: list[float]) -> list[float]:
    return [round(later - earlier, 6) for earlier, later in zip(times, times[1:])]


def _url(name: str) -> str:
    return f"{CDN_BASE}{name}"


# ---------------------------------------------------------------------------
# Filename mapping
# ---------------------------------------------------------------------------


class TestReportSlot:
    def test_cutover_constant_is_the_morning_of_2025_12_22(self) -> None:
        assert MINUTE_FORMAT_START == datetime(2025, 12, 22, 9, 0, tzinfo=ET)

    def test_four_pm_before_cutover_is_the_0330_report(self) -> None:
        winter = report_slot(datetime(2025, 1, 15, 16, 0, tzinfo=ET))
        summer = report_slot(datetime(2024, 7, 15, 16, 0, tzinfo=ET))
        assert winter.filename == "Injury-Report_2025-01-15_03PM.pdf"
        assert winter.format_name == "hour"
        assert summer.filename == "Injury-Report_2024-07-15_03PM.pdf"
        assert winter.url == f"{CDN_BASE}{winter.filename}"

    def test_four_pm_after_cutover_is_the_0345_report(self) -> None:
        slot = report_slot(datetime(2025, 12, 23, 16, 0, tzinfo=ET))
        assert slot.filename == "Injury-Report_2025-12-23_03_45PM.pdf"
        assert slot.format_name == "minute"

    def test_both_sides_of_the_cutover(self) -> None:
        before = report_slot(datetime(2025, 12, 22, 8, 59, tzinfo=ET))
        at_cutover = report_slot(datetime(2025, 12, 22, 9, 0, tzinfo=ET))
        after = report_slot(datetime(2025, 12, 22, 9, 15, tzinfo=ET))
        assert before.filename == "Injury-Report_2025-12-22_08AM.pdf"
        assert before.format_name == "hour"
        # 09:00 is the first minute-format file, and it is a few seconds late.
        assert at_cutover.filename == "Injury-Report_2025-12-22_08AM.pdf"
        assert at_cutover.format_name == "hour"
        assert after.filename == "Injury-Report_2025-12-22_09_00AM.pdf"
        assert after.format_name == "minute"

    def test_known_existing_fixture_url_is_the_1030_slot(self) -> None:
        slot = report_slot(datetime(2024, 11, 14, 11, 0, tzinfo=ET))
        exact = report_slot(datetime(2024, 11, 14, 10, 30, tzinfo=ET))
        earlier = report_slot(datetime(2024, 11, 14, 10, 29, tzinfo=ET))
        assert slot.url == EXISTING_URL
        assert exact.url == EXISTING_URL
        assert earlier.filename == "Injury-Report_2024-11-14_09AM.pdf"

    def test_twelve_am_and_twelve_pm_hour_files(self) -> None:
        assert (
            report_slot(datetime(2025, 1, 10, 0, 30, tzinfo=ET)).filename
            == "Injury-Report_2025-01-10_12AM.pdf"
        )
        assert (
            report_slot(datetime(2025, 1, 10, 1, 0, tzinfo=ET)).filename
            == "Injury-Report_2025-01-10_12AM.pdf"
        )
        assert (
            report_slot(datetime(2025, 1, 10, 0, 0, tzinfo=ET)).filename
            == "Injury-Report_2025-01-09_11PM.pdf"
        )
        assert (
            report_slot(datetime(2025, 1, 10, 12, 0, tzinfo=ET)).filename
            == "Injury-Report_2025-01-10_11AM.pdf"
        )
        assert (
            report_slot(datetime(2025, 1, 10, 12, 30, tzinfo=ET)).filename
            == "Injury-Report_2025-01-10_12PM.pdf"
        )
        assert (
            report_slot(datetime(2025, 1, 10, 13, 0, tzinfo=ET)).filename
            == "Injury-Report_2025-01-10_12PM.pdf"
        )

    def test_twelve_am_and_twelve_pm_minute_files(self) -> None:
        assert (
            report_slot(datetime(2025, 12, 23, 0, 0, tzinfo=ET)).filename
            == "Injury-Report_2025-12-22_11_45PM.pdf"
        )
        assert (
            report_slot(datetime(2025, 12, 23, 0, 0, 1, tzinfo=ET)).filename
            == "Injury-Report_2025-12-23_12_00AM.pdf"
        )
        assert (
            report_slot(datetime(2025, 12, 23, 12, 0, tzinfo=ET)).filename
            == "Injury-Report_2025-12-23_11_45AM.pdf"
        )
        assert (
            report_slot(datetime(2025, 12, 23, 12, 15, tzinfo=ET)).filename
            == "Injury-Report_2025-12-23_12_00PM.pdf"
        )

    def test_spring_forward_skips_the_missing_half_hour(self) -> None:
        # 2024-03-10 02:00 EST becomes 03:00 EDT. 02:30 does not exist.
        at_three = report_slot(datetime(2024, 3, 10, 3, 0, tzinfo=ET))
        at_three_thirty = report_slot(datetime(2024, 3, 10, 3, 30, tzinfo=ET))
        assert at_three.filename == "Injury-Report_2024-03-10_01AM.pdf"
        assert at_three_thirty.filename == "Injury-Report_2024-03-10_03AM.pdf"

    def test_fall_back_uses_the_half_hour_before_the_instant(self) -> None:
        first = report_slot(datetime(2024, 11, 3, 1, 30, tzinfo=ET, fold=0))
        second = report_slot(datetime(2024, 11, 3, 1, 30, tzinfo=ET, fold=1))
        after = report_slot(datetime(2024, 11, 3, 2, 0, tzinfo=ET))
        assert first.filename == "Injury-Report_2024-11-03_01AM.pdf"
        assert second.filename == "Injury-Report_2024-11-03_01AM.pdf"
        assert first.url == second.url
        assert after.filename == "Injury-Report_2024-11-03_01AM.pdf"

    def test_decision_time_is_tip_minus_three_hours(self) -> None:
        # 7:00 PM EST on Jan 15 is 00:00 UTC on Jan 16. T is 4:00 PM EST.
        tip = datetime(2025, 1, 16, 0, 0, tzinfo=UTC)
        assert decision_time(tip) == datetime(2025, 1, 15, 21, 0, tzinfo=UTC)
        assert report_slot(decision_time(tip)).filename == "Injury-Report_2025-01-15_03PM.pdf"
        later = datetime(2025, 12, 24, 0, 0, tzinfo=UTC)
        assert (
            report_slot(decision_time(later)).filename
            == "Injury-Report_2025-12-23_03_45PM.pdf"
        )

    def test_shared_tips_become_one_url(self) -> None:
        tip = datetime(2025, 1, 16, 0, 0, tzinfo=UTC)
        other = datetime(2025, 1, 16, 2, 0, tzinfo=UTC)
        slots = slots_for_tips([tip, tip, other])
        assert len(slots) == 2
        assert len({slot.url for slot in slots}) == 2

    def test_naive_decision_time_is_refused(self) -> None:
        with pytest.raises(ValueError):
            report_slot(datetime(2025, 1, 15, 16, 0))

    @pytest.mark.parametrize(
        "text,year",
        [("2021-22", 2021), ("2021", 2021), ("2025-26", 2025), ("2025-2026", 2025)],
    )
    def test_season_labels(self, text: str, year: int) -> None:
        assert parse_season_start_year(text) == year

    @pytest.mark.parametrize("text", ["2018-19", "2019-20", "2020-21", "2021-23", "nope"])
    def test_early_and_bad_seasons_are_refused(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_season_start_year(text)


# ---------------------------------------------------------------------------
# Recorded CDN headers
# ---------------------------------------------------------------------------


class TestFixtures:
    def test_recorded_headers_have_no_pdf_body(self) -> None:
        for path in FIXTURES.glob("*.json"):
            text = path.read_text(encoding="utf-8")
            assert "%PDF" not in text
            body = json.loads(text)
            assert "body" not in body
            assert isinstance(body["body_sha256"], str) and len(body["body_sha256"]) == 64
            assert isinstance(body["body_length"], int)
            assert body["status_line"].startswith("HTTP/1.1 ")

    def test_existing_and_missing_statuses(self) -> None:
        existing = _load("existing.meta.json")
        missing = _load("missing.meta.json")
        assert existing["url"] == EXISTING_URL
        assert existing["status"] == 200
        assert existing["headers"]["Content-Type"] == "application/pdf"
        assert existing["headers"]["Last-Modified"] == "Thu, 14 Nov 2024 15:30:04 GMT"
        assert missing["url"] == MISSING_URL
        assert missing["status"] == 403
        assert missing["headers"]["Content-Type"] == "application/xml"
        assert "Set-Cookie" not in missing["headers"]


# ---------------------------------------------------------------------------
# Fetch behavior
# ---------------------------------------------------------------------------


class TestFetch:
    @pytest.mark.asyncio
    async def test_existing_url_is_stored_with_last_modified_and_fetched_at(
        self, tmp_path: Path
    ) -> None:
        fixture = _load("existing.meta.json")
        clock = FakeClock(datetime(2026, 11, 24, 8, 0, tzinfo=UTC))
        store = LocalInjuryReportStore(tmp_path)

        def handler(_request: httpx.Request) -> httpx.Response:
            return _pdf(
                {
                    "Last-Modified": fixture["headers"]["Last-Modified"],
                    "Content-Type": fixture["headers"]["Content-Type"],
                }
            )

        client, transport = _client(handler, clock)
        report = await fetch_urls(
            [fixture["url"]], store=store, clock=clock, client=client
        )
        await client.aclose()
        assert transport.urls == [fixture["url"]]
        assert report.requests_made == 1
        assert report.paused is False
        stored = report.results[0]
        assert stored.tag == "stored"
        assert stored.last_modified_raw == "Thu, 14 Nov 2024 15:30:04 GMT"
        assert stored.last_modified_utc == "2024-11-14T15:30:04Z"
        assert stored.fetched_at == "2026-11-24T08:00:00Z"
        assert stored.content_length == len(SYNTHETIC)
        assert stored.path.read_bytes() == SYNTHETIC
        sidecar = json.loads(stored.sidecar_path.read_text(encoding="utf-8"))
        assert sidecar["status"] == 200
        assert sidecar["sha256"] == stored.sha256
        assert sidecar["url"] == fixture["url"]

    @pytest.mark.asyncio
    async def test_missing_slot_is_one_403_and_is_not_retried(self, tmp_path: Path) -> None:
        fixture = _load("missing.meta.json")
        clock = FakeClock()
        store = LocalInjuryReportStore(tmp_path)

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                fixture["status"],
                headers={"Content-Type": fixture["headers"]["Content-Type"]},
                content=b"<?xml version='1.0'?><Error>synthetic</Error>",
            )

        client, transport = _client(handler, clock)
        report = await fetch_urls(
            [fixture["url"]], store=store, clock=clock, client=client
        )
        await client.aclose()
        assert transport.urls == [fixture["url"]]
        assert report.requests_made == 1
        assert report.paused is False
        missing = report.results[0]
        assert missing.tag == "missing"
        assert missing.status == 403
        sidecar = json.loads(missing.sidecar_path.read_text(encoding="utf-8"))
        assert sidecar["status"] == 403
        assert sidecar["checked_at"] == missing.checked_at
        assert not missing.sidecar_path.with_suffix("").with_suffix(".pdf").exists()
        pdf, _sidecar = store.paths_for(fixture["url"])
        assert not pdf.exists()

    @pytest.mark.asyncio
    async def test_minimum_gap_over_eleven_files(self, tmp_path: Path) -> None:
        clock = FakeClock()
        store = LocalInjuryReportStore(tmp_path)
        urls = [_url(f"Injury-Report_2024-11-14_{hour:02d}PM.pdf") for hour in range(1, 12)]
        assert len(urls) >= 11

        def handler(_request: httpx.Request) -> httpx.Response:
            return _pdf()

        client, transport = _client(handler, clock)
        report = await fetch_urls(urls, store=store, clock=clock, client=client)
        await client.aclose()
        assert report.requests_made == 11
        assert transport.times[0] == 0
        gaps = _gaps(transport.times)
        assert len(gaps) >= 10
        assert gaps == [MIN_GAP_SECONDS] * 10
        assert all(gap >= 1.0 for gap in gaps)

    @pytest.mark.asyncio
    async def test_second_run_over_cached_urls_makes_no_http_calls(
        self, tmp_path: Path
    ) -> None:
        clock = FakeClock()
        store = LocalInjuryReportStore(tmp_path)
        urls = [EXISTING_URL, MISSING_URL]
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if str(request.url) == MISSING_URL:
                return httpx.Response(403, headers={"Content-Type": "application/xml"})
            return _pdf({"Last-Modified": "Thu, 14 Nov 2024 15:30:04 GMT"})

        first, transport = _client(handler, clock)
        await fetch_urls(urls, store=store, clock=clock, client=first, recheck_missing=False)
        await first.aclose()
        sidecar = store.paths_for(EXISTING_URL)[1].read_bytes()
        second, again = _client(handler, clock)
        report = await fetch_urls(
            urls, store=store, clock=clock, client=second, recheck_missing=False
        )
        await second.aclose()
        assert again.urls == []
        assert report.requests_made == 0
        assert all(item.from_cache for item in report.results)
        assert store.paths_for(EXISTING_URL)[1].read_bytes() == sidecar
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_live_slot_rechecks_a_recorded_403_once(self, tmp_path: Path) -> None:
        clock = FakeClock()
        store = LocalInjuryReportStore(tmp_path)

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, headers={"Content-Type": "application/xml"})

        first, _transport = _client(handler, clock)
        await fetch_urls(
            [MISSING_URL], store=store, clock=clock, client=first, recheck_missing=False
        )
        await first.aclose()
        second, again = _client(handler, clock)
        report = await fetch_urls(
            [MISSING_URL], store=store, clock=clock, client=second, recheck_missing=True
        )
        await second.aclose()
        assert again.urls == [MISSING_URL]
        assert report.requests_made == 1
        assert report.results[0].tag == "missing"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [500, 429])
    async def test_retryable_failures_back_off_then_pause(
        self, tmp_path: Path, status: int
    ) -> None:
        clock = FakeClock()
        store = LocalInjuryReportStore(tmp_path)
        urls = [
            _url("Injury-Report_2024-11-14_01PM.pdf"),
            _url("Injury-Report_2024-11-14_02PM.pdf"),
        ]

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, headers={"Content-Type": "text/plain"}, content=b"no")

        client, transport = _client(handler, clock)
        report = await fetch_urls(urls, store=store, clock=clock, client=client)
        await client.aclose()
        assert report.paused is True
        assert report.results[-1].tag == "error"
        assert transport.urls == [urls[0]] * 5
        gaps = _gaps(transport.times)
        assert gaps == [1.0, 2.0, 4.0, 8.0]
        assert all(later >= earlier for earlier, later in zip(gaps, gaps[1:]))
        assert all(gap >= 1.0 for gap in gaps)

    @pytest.mark.asyncio
    async def test_timeouts_back_off_then_pause(self, tmp_path: Path) -> None:
        clock = FakeClock()
        store = LocalInjuryReportStore(tmp_path)
        url = _url("Injury-Report_2024-11-14_01PM.pdf")

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        client, transport = _client(handler, clock)
        report = await fetch_urls([url], store=store, clock=clock, client=client)
        await client.aclose()
        assert report.paused is True
        assert report.results[-1].tag == "error"
        assert len(transport.urls) == 5
        assert _gaps(transport.times) == [1.0, 2.0, 4.0, 8.0]

    @pytest.mark.asyncio
    async def test_html_block_page_pauses_without_fetching_the_rest(
        self, tmp_path: Path
    ) -> None:
        clock = FakeClock()
        store = LocalInjuryReportStore(tmp_path)
        urls = [
            _url("Injury-Report_2024-11-14_01PM.pdf"),
            _url("Injury-Report_2024-11-14_02PM.pdf"),
            _url("Injury-Report_2024-11-14_03PM.pdf"),
        ]
        seen = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            seen["n"] += 1
            if seen["n"] == 1:
                return _pdf()
            return httpx.Response(
                200, headers={"Content-Type": "text/html"}, content=b"<html>blocked</html>"
            )

        client, transport = _client(handler, clock)
        report = await fetch_urls(urls, store=store, clock=clock, client=client)
        await client.aclose()
        assert report.paused is True
        assert [item.tag for item in report.results] == ["stored", "blocked"]
        assert transport.urls == urls[:2]
        assert _gaps(transport.times) == [1.0]
        _pdf_path, sidecar = store.paths_for(urls[1])
        assert not sidecar.exists()
        assert not _pdf_path.exists()

    @pytest.mark.asyncio
    async def test_403_on_a_stored_url_pauses_and_keeps_the_pdf(self, tmp_path: Path) -> None:
        clock = FakeClock()
        store = LocalInjuryReportStore(tmp_path)
        url = EXISTING_URL

        def ok(_request: httpx.Request) -> httpx.Response:
            return _pdf({"Last-Modified": "Thu, 14 Nov 2024 15:30:04 GMT"})

        client, _transport = _client(ok, clock)
        await fetch_urls([url], store=store, clock=clock, client=client)
        await client.aclose()
        original = store.paths_for(url)[0].read_bytes()
        sidecar = store.paths_for(url)[1].read_bytes()

        def denied(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, headers={"Content-Type": "application/xml"})

        again, transport = _client(denied, clock)
        report = await fetch_urls(
            [url, _url("Injury-Report_2024-11-14_02PM.pdf")],
            store=store,
            clock=clock,
            client=again,
            reuse_stored=False,
        )
        await again.aclose()
        assert report.paused is True
        assert report.results[-1].tag == "blocked"
        assert transport.urls == [url]
        assert store.paths_for(url)[0].read_bytes() == original
        assert store.paths_for(url)[1].read_bytes() == sidecar

    @pytest.mark.asyncio
    async def test_consecutive_403s_do_not_pause(self, tmp_path: Path) -> None:
        clock = FakeClock()
        store = LocalInjuryReportStore(tmp_path)
        urls = [_url(f"Injury-Report_2024-11-14_{hour:02d}AM.pdf") for hour in range(1, 13)]

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                headers={"Content-Type": "application/xml"},
                content=b"<?xml version='1.0'?><Error></Error>",
            )

        client, transport = _client(handler, clock)
        report = await fetch_urls(urls, store=store, clock=clock, client=client)
        await client.aclose()
        assert report.paused is False
        assert report.requests_made == 12
        assert all(item.tag == "missing" for item in report.results)
        assert _gaps(transport.times) == [1.0] * 11

    @pytest.mark.asyncio
    async def test_requests_send_the_fetcher_user_agent(self, tmp_path: Path) -> None:
        clock = FakeClock()
        store = LocalInjuryReportStore(tmp_path)
        client, transport = _client(lambda _request: _pdf(), clock)
        # The CLI client sets the header. This test sets it the same way.
        client.headers["User-Agent"] = USER_AGENT
        await fetch_urls(
            [_url("Injury-Report_2024-11-14_01PM.pdf")],
            store=store,
            clock=clock,
            client=client,
        )
        await client.aclose()
        assert transport.user_agents == [USER_AGENT]


# ---------------------------------------------------------------------------
# CLI, scheduler, repo guard
# ---------------------------------------------------------------------------


class TestCli:
    def test_current_dry_run_prints_the_url_and_does_not_fetch(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("dry-run opened a fetch")

        monkeypatch.setattr(cli, "fetch_urls", boom)
        code = cli.main(["current", "--dry-run", "--at", "2025-12-23T21:00:00Z"])
        assert code == 0
        assert capsys.readouterr().out.strip() == (
            "https://ak-static.cms.nba.com/referee/injury/"
            "Injury-Report_2025-12-23_03_45PM.pdf"
        )

    def test_backfill_dry_run_dedupes_and_does_not_fetch(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tip = datetime(2025, 1, 16, 0, 0, tzinfo=UTC)
        other = datetime(2025, 1, 16, 2, 0, tzinfo=UTC)

        async def tips(year: int) -> list[datetime]:
            assert year == 2021
            return [tip, tip, other]

        monkeypatch.setattr(cli, "_load_tips", tips)
        monkeypatch.setattr(
            cli, "fetch_urls", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("fetched"))
        )
        code = cli.main(["backfill", "--season", "2021-22", "--dry-run"])
        assert code == 0
        lines = [line for line in capsys.readouterr().out.splitlines() if line]
        assert len(lines) == 2
        assert len(set(lines)) == 2

    def test_season_before_2021_22_exits_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["backfill", "--season", "2020-21", "--dry-run"]) == 2
        assert "out of scope" in capsys.readouterr().err


class TestSchedulerFlag:
    def _job_ids(self, enabled: bool) -> set[str]:
        from app.services.scheduler import SchedulerService

        service = SchedulerService()
        with patch("app.services.scheduler.settings") as settings:
            settings.injury_pdf_fetch_enabled = enabled
            with patch("app.services.scheduler.AsyncIOScheduler") as scheduler:
                instance = MagicMock()
                instance.get_jobs.return_value = []
                scheduler.return_value = instance
                service.start()
                ids = set()
                for call in instance.add_job.call_args_list:
                    ids.add(call.kwargs.get("id"))
                service.stop()
        return ids

    def test_job_is_absent_when_the_flag_is_off(self) -> None:
        assert "injury_pdf_fetch_current" not in self._job_ids(False)

    def test_job_is_every_fifteen_minutes_when_the_flag_is_on(self) -> None:
        from app.services.scheduler import SchedulerService

        service = SchedulerService()
        with patch("app.services.scheduler.settings") as settings:
            settings.injury_pdf_fetch_enabled = True
            with patch("app.services.scheduler.AsyncIOScheduler") as scheduler:
                instance = MagicMock()
                instance.get_jobs.return_value = []
                scheduler.return_value = instance
                service.start()
                match = None
                for call in instance.add_job.call_args_list:
                    if call.kwargs.get("id") == "injury_pdf_fetch_current":
                        match = call.kwargs
                service.stop()
        assert match is not None
        assert match["replace_existing"] is True
        assert "0,15,30,45" in str(match["trigger"])

    @pytest.mark.asyncio
    async def test_handler_does_not_fetch_when_the_flag_is_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.scheduler import SchedulerService

        monkeypatch.setattr(
            "app.services.scheduler.settings.injury_pdf_fetch_enabled", False
        )
        called = {"fetch": False, "day": False}

        async def game_day(_now: datetime) -> bool:
            called["day"] = True
            return True

        service = SchedulerService()
        monkeypatch.setattr(service, "_injury_pdf_is_game_day", game_day)
        await service._run_injury_pdf_fetch_job()
        assert called == {"fetch": False, "day": False}

    @pytest.mark.asyncio
    async def test_handler_skips_a_day_with_no_game(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.scheduler import SchedulerService

        monkeypatch.setattr(
            "app.services.scheduler.settings.injury_pdf_fetch_enabled", True
        )

        async def game_day(_now: datetime) -> bool:
            return False

        async def fetch(_now: datetime | None = None) -> None:
            raise AssertionError("fetched")

        service = SchedulerService()
        monkeypatch.setattr(service, "_injury_pdf_is_game_day", game_day)
        monkeypatch.setattr(
            "app.services.injury_report_fetcher.fetch_current_slot", fetch
        )
        await service._run_injury_pdf_fetch_job()

    @pytest.mark.asyncio
    async def test_handler_fetches_on_a_game_day(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.scheduler import SchedulerService

        monkeypatch.setattr(
            "app.services.scheduler.settings.injury_pdf_fetch_enabled", True
        )
        seen: dict[str, datetime] = {}

        async def game_day(now: datetime) -> bool:
            seen["day"] = now
            return True

        async def fetch(now: datetime | None = None) -> MagicMock:
            seen["fetch"] = now  # type: ignore[assignment]
            report = MagicMock()
            report.paused = False
            return report

        moment = datetime(2026, 1, 15, 21, 0, tzinfo=UTC)
        service = SchedulerService()
        monkeypatch.setattr(service, "_injury_pdf_is_game_day", game_day)
        monkeypatch.setattr(
            "app.services.injury_report_fetcher.fetch_current_slot", fetch
        )
        await service._run_injury_pdf_fetch_job(now=moment)
        assert seen["fetch"] == moment


class TestRepoGuard:
    def test_git_tracks_no_pdf(self) -> None:
        listed = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
        pdfs = [line for line in listed.splitlines() if line.lower().endswith(".pdf")]
        assert pdfs == []

    def test_cache_directory_is_gitignored(self) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "nba-injury-pdf/Injury-Report_2024-11-14_10AM.pdf"],
            cwd=ROOT,
            check=False,
        )
        assert result.returncode == 0

    def test_flag_defaults_off_in_settings_env_and_compose(self) -> None:
        assert Settings.model_fields["injury_pdf_fetch_enabled"].default is False
        example = (ROOT / "env.example").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        assert "INJURY_PDF_FETCH_ENABLED=false" in example
        assert "INJURY_PDF_FETCH_ENABLED:-false" in compose
        assert "INJURY_PDF_DIR" in example
        locals_tf = (ROOT / "infra" / "aws" / "locals.tf").read_text(encoding="utf-8")
        iam = (ROOT / "infra" / "aws" / "iam.tf").read_text(encoding="utf-8")
        assert '"nba-injury-pdf/"' in locals_tf
        assert "s3:DeleteObject" not in iam
        assert "s3:GetObject" in iam
        assert "s3:PutObject" in iam


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def migrated(scratch_conn):  # type: ignore[no-untyped-def]
    await upgrade(scratch_conn)
    await scratch_conn.execute(
        """
        INSERT INTO seasons (league, season_start_year, label) VALUES
            ('nba', 2020, '2020-21'),
            ('nba', 2021, '2021-22');
        INSERT INTO teams (league, bdl_team_id, abbreviation) VALUES
            ('nba', 1, 'AAA'),
            ('nba', 2, 'BBB');
        INSERT INTO games
            (league, bdl_game_id, season, date, datetime_utc, postponed, season_type,
             home_team_id, visitor_team_id)
        VALUES
            ('nba', 1, 2021, '2022-01-15', '2022-01-16 00:00Z', false, 'regular_season', 1, 2),
            ('nba', 2, 2021, '2022-01-15', '2022-01-16 00:00Z', false, 'regular_season', 2, 1),
            ('nba', 3, 2021, '2022-01-15', '2022-01-16 02:00Z', false, 'regular_season', 1, 2),
            ('nba', 4, 2021, '2022-01-15', NULL, false, 'regular_season', 1, 2),
            ('nba', 5, 2021, '2022-01-16', '2022-01-17 00:00Z', true, 'regular_season', 1, 2),
            ('nba', 6, 2020, '2021-01-15', '2021-01-16 00:00Z', false, 'regular_season', 1, 2);
        """
    )
    return scratch_conn


@pytest.mark.asyncio
async def test_backfill_reads_2021_tips_and_drops_null_and_postponed(migrated) -> None:
    from datetime import date

    tips = await tip_times_for_season(migrated, 2021)
    assert len(tips) == 3
    slots = slots_for_tips(tips)
    assert len(slots) == 2
    early = await tip_times_for_season(migrated, 2020)
    assert len(early) == 1
    assert await has_nba_game_on(migrated, date(2022, 1, 15)) is True
    assert await has_nba_game_on(migrated, date(2022, 1, 16)) is False
    assert await has_nba_game_on(migrated, date(2022, 2, 1)) is False
