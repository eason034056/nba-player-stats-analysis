"""SPO-150: parse official injury-report PDFs into rows.

The PDFs in this file are built in memory. Names and reasons are fake.
See tests/fixtures/injury_report_rows/README.md (synthetic: true).
"""

from __future__ import annotations

import io
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import asyncpg
import pytest
import pytest_asyncio
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.migrations.runner import upgrade
from app.services.injury_report_ingest import (
    OFFICIAL_SOURCE,
    ingest_report,
    ingest_store,
    injury_rows_as_of,
)
from app.services.injury_report_parser import STATUSES, parse_pdf
from app.services.injury_report_store import LocalInjuryReportStore
from app.services.injury_report_types import RunReport
from app.settings import settings

ET = ZoneInfo("America/New_York")
TITLE = "01/15/24 05:30 PM"
REPORT_AT = datetime(2024, 1, 15, 17, 30, tzinfo=ET)

# Column x positions. Gaps are wide so a word stays in its column.
DATE_X = 40
TIME_X = 140
MATCH_X = 250
TEAM_X = 370
PLAYER_X = 560
STATUS_X = 760
REASON_X = 900
CATEGORY_X = 700
REASON_A_X = 860
STATUS_A_X = 1040
PREVIOUS_X = 1180


def _canvas(producer: str, width: float, height: float = 620) -> tuple[canvas.Canvas, io.BytesIO]:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    pdf.setProducer(producer)
    pdf.setFont("Helvetica", 8)
    return pdf, buffer


def _title(pdf: canvas.Canvas, y: float) -> None:
    pdf.drawString(40, y, f"Injury Report: {TITLE}")


def _finish(pdf: canvas.Canvas, buffer: io.BytesIO) -> bytes:
    pdf.save()
    return buffer.getvalue()


def layout_a_pdf() -> bytes:
    """iText shape: Category and Previous Status, plus a team note."""
    pdf, buffer = _canvas("iTextSharp 5.5.0", 1320)
    _title(pdf, 590)
    y = 550
    headers = [
        (DATE_X, "Game Date"),
        (TIME_X, "Game Time"),
        (MATCH_X, "Matchup"),
        (TEAM_X, "Team"),
        (PLAYER_X, "Player Name"),
        (CATEGORY_X, "Category"),
        (REASON_A_X, "Reason"),
        (STATUS_A_X, "Current Status"),
        (PREVIOUS_X, "Previous Status"),
    ]
    for x, label in headers:
        pdf.drawString(x, y, label)
    y = 500
    pdf.drawString(DATE_X, y, "01/15/2024")
    pdf.drawString(TIME_X, y, "07:00 (ET)")
    pdf.drawString(MATCH_X, y, "BOS@NYK")
    pdf.drawString(TEAM_X, y, "Boston Celtics")
    pdf.drawString(PLAYER_X, y, "Doe, Jr., Alex")
    pdf.drawString(CATEGORY_X, y, "Injury/Illness")
    pdf.drawString(REASON_A_X, y, "Left Thumb Sprain")
    pdf.drawString(STATUS_A_X, y, "Out")
    pdf.drawString(PREVIOUS_X, y, "Available")
    y = 460
    pdf.drawString(TEAM_X, y, "New York Knicks")
    pdf.drawString(CATEGORY_X, y, "ALL PLAYERS AVAILABLE")
    y = 420
    pdf.drawString(DATE_X, y, "01/16/2024")
    pdf.drawString(TIME_X, y, "08:00 (ET)")
    pdf.drawString(MATCH_X, y, "LAL@GSW")
    pdf.drawString(TEAM_X, y, "Golden State Warriors")
    pdf.drawString(CATEGORY_X, y, "NOT YET SUBMITTED")
    return _finish(pdf, buffer)


def layout_b_pdf() -> bytes:
    """iText shape: status, reason, a two-comma name, and both dates."""
    pdf, buffer = _canvas("iTextSharp 5.5.0", 1100)
    _title(pdf, 590)
    y = 550
    for x, label in (
        (DATE_X, "Game Date"),
        (TIME_X, "Game Time"),
        (MATCH_X, "Matchup"),
        (TEAM_X, "Team"),
        (PLAYER_X, "Player Name"),
        (STATUS_X, "Current Status"),
        (REASON_X, "Reason"),
    ):
        pdf.drawString(x, y, label)
    y = 500
    pdf.drawString(DATE_X, y, "01/15/2024")
    pdf.drawString(TIME_X, y, "07:00 (ET)")
    pdf.drawString(MATCH_X, y, "BOS@NYK")
    pdf.drawString(TEAM_X, y, "Boston Celtics")
    pdf.drawString(PLAYER_X, y, "Doe, Jr., Alex")
    pdf.drawString(STATUS_X, y, "Questionable")
    pdf.drawString(REASON_X, y, "Injury/Illness - Right Knee; Soreness")
    y = 460
    pdf.drawString(TEAM_X, y, "New York Knicks")
    pdf.drawString(PLAYER_X, y, "Smith, Alex")
    pdf.drawString(STATUS_X, y, "Out")
    pdf.drawString(REASON_X, y, "Rest")
    y = 420
    pdf.drawString(DATE_X, y, "01/16/2024")
    pdf.drawString(TIME_X, y, "09:00 (ET)")
    pdf.drawString(MATCH_X, y, "LAL@GSW")
    pdf.drawString(TEAM_X, y, "Los Angeles Lakers")
    pdf.drawString(REASON_X, y, "NOT YET SUBMITTED")
    y = 380
    pdf.drawString(TEAM_X, y, "Golden State Warriors")
    pdf.drawString(PLAYER_X, y, "Rivera, Ana")
    pdf.drawString(STATUS_X, y, "Probable")
    pdf.drawString(REASON_X, y, "Personal Reasons")
    return _finish(pdf, buffer)


def layout_c_pdf() -> bytes:
    """GemBox shape: wrapped reason, a page-break join, and both dates."""
    pdf, buffer = _canvas("GemBox.Document 3.1 for .NET", 1100)
    _title(pdf, 590)
    header_y = 550
    pdf.drawString(DATE_X, header_y, "Game")
    pdf.drawString(DATE_X + 28, header_y, "Date")
    pdf.drawString(TIME_X, header_y, "Game")
    pdf.drawString(TIME_X + 28, header_y, "Time")
    pdf.drawString(MATCH_X, header_y, "Matchup")
    pdf.drawString(TEAM_X, header_y, "Team")
    pdf.drawString(PLAYER_X, header_y, "Player")
    pdf.drawString(PLAYER_X + 36, header_y, "Name")
    pdf.drawString(STATUS_X, header_y, "Current")
    pdf.drawString(STATUS_X + 42, header_y, "Status")
    pdf.drawString(REASON_X, header_y, "Reason")

    pdf.drawString(REASON_X, 508, "Injury/Illness - Right Knee;")
    pdf.drawString(DATE_X, 500, "01/15/2024")
    pdf.drawString(TIME_X, 500, "07:00 (ET)")
    pdf.drawString(MATCH_X, 500, "BOS@NYK")
    pdf.drawString(TEAM_X, 500, "Boston Celtics")
    pdf.drawString(PLAYER_X, 500, "Doe, Jr., Alex")
    pdf.drawString(STATUS_X, 500, "Questionable")
    pdf.drawString(REASON_X, 492, "Soreness")

    pdf.drawString(TEAM_X, 450, "New York Knicks")
    pdf.drawString(PLAYER_X, 450, "Smith, Alex")
    pdf.drawString(STATUS_X, 450, "Out")
    pdf.drawString(REASON_X, 450, "Rest")

    pdf.drawString(DATE_X, 400, "01/15/2024")
    pdf.drawString(TIME_X, 400, "08:00 (ET)")
    pdf.drawString(MATCH_X, 400, "MIA@CHI")
    pdf.drawString(TEAM_X, 400, "Miami Heat")
    pdf.drawString(PLAYER_X, 400, "Rivera, Ana")
    pdf.drawString(STATUS_X, 400, "Out")
    pdf.drawString(REASON_X, 400, "Injury/Illness - Left Ankle;")

    pdf.showPage()
    pdf.setFont("Helvetica", 8)
    _title(pdf, 590)
    # Far from the next player, so this joins Rivera on the previous page.
    pdf.drawString(REASON_X, 540, "Dislocation")
    pdf.drawString(DATE_X, 450, "01/16/2024")
    pdf.drawString(TIME_X, 450, "10:00 (ET)")
    pdf.drawString(MATCH_X, 450, "LAL@GSW")
    pdf.drawString(TEAM_X, 450, "Los Angeles Lakers")
    pdf.drawString(REASON_X, 450, "NOT YET SUBMITTED")
    pdf.drawString(TEAM_X, 410, "Golden State Warriors")
    pdf.drawString(PLAYER_X, 410, "Chen, Mei")
    pdf.drawString(STATUS_X, 410, "Doubtful")
    pdf.drawString(REASON_X, 410, "G League - Two-Way")
    return _finish(pdf, buffer)


def _by_player(result, name: str):
    matches = [row for row in result.rows if row.player_raw == name]
    assert len(matches) == 1
    return matches[0]


class TestLayouts:
    def test_layout_a_has_category_previous_status_and_both_dates(self) -> None:
        later = REPORT_AT.astimezone(UTC) + timedelta(seconds=7)
        result = parse_pdf(layout_a_pdf(), last_modified=later, filename="Injury-Report_2024-01-15_05PM.pdf")
        assert result.tag == "ok"
        assert result.layout.value == "A"
        assert result.report_at == REPORT_AT
        assert result.report_at_source == "title"
        assert result.player_rows == 1
        assert result.nys_rows == 1
        assert result.pagebreak_joins == 0
        player = _by_player(result, "Doe, Jr., Alex")
        assert player.game_date == date(2024, 1, 15)
        assert player.matchup == "BOS@NYK"
        assert player.team_name == "Boston Celtics"
        assert player.team_abbr == "BOS"
        assert player.status == "Out"
        assert player.reason == "Left Thumb Sprain"
        assert player.category == "Injury/Illness"
        assert player.previous_status == "Available"
        assert player.player_raw.count(",") == 2
        notes = [row for row in result.rows if row.all_players_available]
        assert len(notes) == 1
        assert notes[0].team_name == "New York Knicks"
        assert notes[0].player_raw == ""
        assert notes[0].not_yet_submitted is False
        nys = [row for row in result.rows if row.not_yet_submitted]
        assert len(nys) == 1
        assert nys[0].game_date == date(2024, 1, 16)
        assert nys[0].matchup == "LAL@GSW"
        assert nys[0].team_abbr == "GSW"
        assert {row.game_date for row in result.rows} == {date(2024, 1, 15), date(2024, 1, 16)}

    def test_layout_b_reads_status_reason_and_a_two_comma_name(self) -> None:
        result = parse_pdf(layout_b_pdf())
        assert result.tag == "ok"
        assert result.layout.value == "B"
        assert result.report_at_source == "title"
        player = _by_player(result, "Doe, Jr., Alex")
        assert player.status == "Questionable"
        assert player.reason == "Injury/Illness - Right Knee; Soreness"
        assert player.category == "Injury/Illness"
        carried = _by_player(result, "Smith, Alex")
        assert carried.game_date == date(2024, 1, 15)
        assert carried.matchup == "BOS@NYK"
        assert carried.team_abbr == "NYK"
        assert carried.category == "Rest"
        nys = [row for row in result.rows if row.not_yet_submitted]
        assert len(nys) == 1
        assert nys[0].team_name == "Los Angeles Lakers"
        assert nys[0].reason is None
        assert nys[0].status is None
        warriors = _by_player(result, "Rivera, Ana")
        assert warriors.game_date == date(2024, 1, 16)
        assert warriors.category == "Personal Reasons"
        assert warriors.status == "Probable"

    def test_a_suspension_reason_keeps_its_category_prefix(self) -> None:
        pdf, buffer = _canvas("GemBox.Document 3.1 for .NET", 1100)
        _title(pdf, 590)
        for x, label in (
            (DATE_X, "Game Date"),
            (TIME_X, "Game Time"),
            (MATCH_X, "Matchup"),
            (TEAM_X, "Team"),
            (PLAYER_X, "Player Name"),
            (STATUS_X, "Current Status"),
            (REASON_X, "Reason"),
        ):
            pdf.drawString(x, 550, label)
        pdf.drawString(DATE_X, 500, "01/15/2024")
        pdf.drawString(MATCH_X, 500, "BOS@NYK")
        pdf.drawString(TEAM_X, 500, "Boston Celtics")
        pdf.drawString(PLAYER_X, 500, "Smith, Alex")
        pdf.drawString(STATUS_X, 500, "Out")
        pdf.drawString(REASON_X, 500, "League Suspension")
        result = parse_pdf(_finish(pdf, buffer))
        assert result.tag == "ok"
        assert _by_player(result, "Smith, Alex").category == "League Suspension"

    def test_layout_c_joins_a_wrapped_reason_and_a_page_break(self) -> None:
        result = parse_pdf(layout_c_pdf())
        assert result.tag == "ok"
        assert result.layout.value == "C"
        assert result.unattached_reasons == 0
        assert result.pagebreak_joins == 1
        wrapped = _by_player(result, "Doe, Jr., Alex")
        assert wrapped.reason == "Injury/Illness - Right Knee; Soreness"
        assert wrapped.category == "Injury/Illness"
        assert wrapped.status == "Questionable"
        joined = _by_player(result, "Rivera, Ana")
        assert joined.reason == "Injury/Illness - Left Ankle; Dislocation"
        assert joined.matchup == "MIA@CHI"
        nys = [row for row in result.rows if row.not_yet_submitted]
        assert len(nys) == 1
        assert nys[0].game_date == date(2024, 1, 16)
        assert nys[0].team_abbr == "LAL"
        chen = _by_player(result, "Chen, Mei")
        assert chen.status == "Doubtful"
        assert chen.category == "G League - Two-Way"
        assert chen.status in STATUSES
        assert {row.game_date for row in result.rows} == {date(2024, 1, 15), date(2024, 1, 16)}

    def test_filename_time_is_used_only_when_the_title_is_missing(self) -> None:
        pdf, buffer = _canvas("iTextSharp 5.5.0", 1100)
        pdf.drawString(DATE_X, 550, "Game Date")
        pdf.drawString(TIME_X, 550, "Game Time")
        pdf.drawString(MATCH_X, 550, "Matchup")
        pdf.drawString(TEAM_X, 550, "Team")
        pdf.drawString(PLAYER_X, 550, "Player Name")
        pdf.drawString(STATUS_X, 550, "Current Status")
        pdf.drawString(REASON_X, 550, "Reason")
        pdf.drawString(DATE_X, 500, "01/15/2024")
        pdf.drawString(MATCH_X, 500, "BOS@NYK")
        pdf.drawString(TEAM_X, 500, "Boston Celtics")
        pdf.drawString(PLAYER_X, 500, "Smith, Alex")
        pdf.drawString(STATUS_X, 500, "Out")
        pdf.drawString(REASON_X, 500, "Rest")
        data = _finish(pdf, buffer)
        from_name = parse_pdf(data, filename="Injury-Report_2024-01-15_05PM.pdf")
        assert from_name.tag == "ok"
        assert from_name.report_at_source == "filename"
        assert from_name.report_at == REPORT_AT
        modified = datetime(2024, 1, 15, 18, 30, tzinfo=UTC)
        from_header = parse_pdf(data, last_modified=modified, filename="Injury-Report_2024-01-15_05PM.pdf")
        assert from_header.report_at_source == "last_modified"
        assert from_header.report_at == modified

    def test_a_broken_pdf_is_a_failure_and_not_an_exception(self) -> None:
        moment = datetime(2024, 1, 15, 18, 30, tzinfo=UTC)
        result = parse_pdf(b"this is not a pdf", last_modified=moment, filename="Injury-Report_2024-01-15_01PM.pdf")
        assert result.tag == "failed"
        assert result.error
        assert result.report_at == moment
        assert "not a pdf" not in result.error


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    applied = await upgrade(scratch_conn)
    assert "006" in applied
    assert applied[-1] == "007"
    await scratch_conn.execute(
        """
        INSERT INTO seasons (league, season_start_year, label)
        VALUES ('nba', 2023, '2023-24'), ('nba', 2025, '2025-26');
        INSERT INTO teams (league, bdl_team_id, abbreviation, full_name) VALUES
            ('nba', 2, 'BOS', 'Boston Celtics'),
            ('nba', 20, 'NYK', 'New York Knicks'),
            ('nba', 14, 'LAL', 'Los Angeles Lakers'),
            ('nba', 10, 'GSW', 'Golden State Warriors'),
            ('nba', 16, 'MIA', 'Miami Heat'),
            ('nba', 5, 'CHI', 'Chicago Bulls');
        INSERT INTO games (
            league, bdl_game_id, season, date, datetime_utc, status_state,
            season_type, home_team_id, visitor_team_id
        ) VALUES
            ('nba', 101, 2023, '2024-01-15', '2024-01-16 00:30:00+00', 'scheduled',
             'regular_season', 20, 2),
            ('nba', 102, 2023, '2024-01-16', '2024-01-17 02:00:00+00', 'scheduled',
             'regular_season', 10, 14);
        """
    )
    return scratch_conn


def _put(store: LocalInjuryReportStore, name: str, data: bytes, modified: datetime) -> None:
    store.put_pdf(
        f"https://ak-static.cms.nba.com/referee/injury/{name}",
        data,
        fetched_at=datetime(2024, 1, 15, 22, 30, 8, tzinfo=UTC),
        last_modified_raw="Mon, 15 Jan 2024 22:30:07 GMT",
        last_modified_utc=modified.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


@pytest.mark.asyncio
async def test_ingest_resolves_ids_and_a_second_run_writes_nothing(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    store = LocalInjuryReportStore(tmp_path)
    _put(store, "Injury-Report_2024-01-15_05PM.pdf", layout_b_pdf(), REPORT_AT.astimezone(UTC))
    dry = await ingest_store(db, store, dry_run=True)
    assert dry[0].tag == "dry_run"
    assert dry[0].rows_written == 0
    assert await db.fetchval("SELECT count(*) FROM nba_injury_report_rows") == 0
    assert await db.fetchval("SELECT count(*) FROM source_refreshes") == 0

    first = await ingest_store(db, store)
    assert first[0].tag == "stored"
    assert first[0].rows_seen == 4
    assert first[0].rows_written == 4
    rows = await db.fetch(
        """
        SELECT game_date, matchup, team_name, bdl_game_id, bdl_team_id,
               player_raw, status, reason, category, not_yet_submitted, bdl_player_id, match_method
        FROM nba_injury_report_rows
        ORDER BY game_date, team_name
        """
    )
    by_key = {(row["team_name"], row["player_raw"]): row for row in rows}
    doe = by_key[("Boston Celtics", "Doe, Jr., Alex")]
    assert doe["bdl_game_id"] == 101
    assert doe["bdl_team_id"] == 2
    assert doe["status"] == "Questionable"
    assert doe["category"] == "Injury/Illness"
    assert doe["reason"] == "Injury/Illness - Right Knee; Soreness"
    assert doe["bdl_player_id"] is None
    assert doe["match_method"] is None
    nys = by_key[("Los Angeles Lakers", "")]
    assert nys["not_yet_submitted"] is True
    assert nys["bdl_game_id"] == 102
    assert nys["bdl_team_id"] == 14
    assert by_key[("Golden State Warriors", "Rivera, Ana")]["bdl_team_id"] == 10
    refresh = await db.fetchrow(
        "SELECT source, complete, rows_seen, rows_written, error FROM source_refreshes"
    )
    assert refresh["source"] == OFFICIAL_SOURCE
    assert refresh["complete"] is True
    assert refresh["rows_seen"] == 4
    assert refresh["rows_written"] == 4
    assert refresh["error"] is None

    second = await ingest_store(db, store)
    assert second[0].tag == "unchanged"
    assert second[0].rows_written == 0
    assert await db.fetchval("SELECT count(*) FROM nba_injury_report_rows") == 4
    assert await db.fetchval("SELECT count(*) FROM source_refreshes") == 1


@pytest.mark.asyncio
async def test_a_broken_pdf_records_a_failure_and_the_batch_continues(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    store = LocalInjuryReportStore(tmp_path)
    broken_at = datetime(2024, 1, 15, 18, 30, tzinfo=UTC)
    _put(store, "Injury-Report_2024-01-15_01PM.pdf", b"this is not a pdf", broken_at)
    _put(store, "Injury-Report_2024-01-15_05PM.pdf", layout_b_pdf(), REPORT_AT.astimezone(UTC))
    outcomes = await ingest_store(db, store)
    by_name = {item.filename: item for item in outcomes}
    assert by_name["Injury-Report_2024-01-15_01PM.pdf"].tag == "failed"
    assert by_name["Injury-Report_2024-01-15_01PM.pdf"].error
    assert by_name["Injury-Report_2024-01-15_05PM.pdf"].tag == "stored"
    assert await db.fetchval("SELECT count(*) FROM nba_injury_report_rows") == 4
    failure = await db.fetchrow(
        """
        SELECT complete, error, rows_seen FROM source_refreshes
        WHERE refreshed_at = $1
        """,
        broken_at,
    )
    assert failure["complete"] is False
    assert failure["error"]
    assert failure["rows_seen"] == 0
    again = await ingest_report(
        db,
        store.iter_stored()[0],
        dry_run=False,
    )
    assert again.filename == "Injury-Report_2024-01-15_01PM.pdf"
    assert again.tag == "failed"


T = datetime(2026, 1, 15, 23, 0, tzinfo=UTC)


async def _seed_boundary(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        INSERT INTO games (
            league, bdl_game_id, season, date, datetime_utc, status_state,
            season_type, home_team_id, visitor_team_id
        ) VALUES (
            'nba', 7, 2025, '2026-01-15', $1, 'scheduled', 'regular_season', 20, 2
        )
        """,
        T + timedelta(hours=3),
    )
    await conn.executemany(
        """
        INSERT INTO nba_injury_report_rows (
            league, report_at, game_date, matchup, team_name,
            bdl_game_id, bdl_team_id, player_raw, status,
            not_yet_submitted, all_players_available
        ) VALUES ('nba', $1, '2026-01-15', 'BOS@NYK', 'Boston Celtics', 7, 2, $2, $3, false, false)
        """,
        [
            (T - timedelta(hours=1), "Old, Out", "Out"),
            (T, "On, Time", "Questionable"),
            (T + timedelta(seconds=1), "Late, One", "Doubtful"),
        ],
    )


@pytest.mark.asyncio
async def test_a_report_at_exactly_t_is_selected(db: asyncpg.Connection) -> None:
    await _seed_boundary(db)
    tip_t = await db.fetchval("SELECT game_as_of('nba', 7)")
    assert tip_t == T
    rows = await injury_rows_as_of(db, 7, as_of=T)
    assert [row["player_raw"] for row in rows] == ["On, Time"]
    assert rows[0]["report_at"] == T
    assert rows[0]["status"] == "Questionable"
    default_rows = await injury_rows_as_of(db, 7)
    assert [row["player_raw"] for row in default_rows] == ["On, Time"]


@pytest.mark.asyncio
async def test_a_report_one_second_after_t_is_stored_but_not_selected(
    db: asyncpg.Connection,
) -> None:
    await _seed_boundary(db)
    stored = await db.fetchval(
        "SELECT count(*) FROM nba_injury_report_rows WHERE report_at = $1",
        T + timedelta(seconds=1),
    )
    assert stored == 1
    rows = await injury_rows_as_of(db, 7, as_of=T)
    assert [row["player_raw"] for row in rows] == ["On, Time"]
    assert all(row["player_raw"] != "Late, One" for row in rows)
    later = await injury_rows_as_of(db, 7, as_of=T + timedelta(seconds=1))
    assert [row["player_raw"] for row in later] == ["Late, One"]


class TestSchedulerFlag:
    @pytest.mark.asyncio
    async def test_handler_does_not_ingest_when_the_flag_is_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.scheduler import SchedulerService

        monkeypatch.setattr(settings, "injury_pdf_fetch_enabled", False)

        async def ingest(_report: object) -> None:
            raise AssertionError("ingested")

        monkeypatch.setattr(
            "app.services.injury_report_ingest.ingest_fetch_results",
            ingest,
        )
        await SchedulerService()._run_injury_pdf_fetch_job()

    @pytest.mark.asyncio
    async def test_handler_ingests_after_fetch_when_the_flag_is_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.scheduler import SchedulerService

        monkeypatch.setattr(settings, "injury_pdf_fetch_enabled", True)
        seen: dict[str, int] = {"n": 0}

        async def game_day(_now: datetime) -> bool:
            return True

        async def fetch(_now: datetime | None = None) -> RunReport:
            return RunReport(results=(), paused=False, requests_made=0)

        async def ingest(report: RunReport) -> None:
            seen["n"] += 1
            assert report.paused is False

        service = SchedulerService()
        monkeypatch.setattr(service, "_injury_pdf_is_game_day", game_day)
        monkeypatch.setattr("app.services.injury_report_fetcher.fetch_current_slot", fetch)
        monkeypatch.setattr("app.services.injury_report_ingest.ingest_fetch_results", ingest)
        await service._run_injury_pdf_fetch_job()
        assert seen["n"] == 1


@pytest.mark.asyncio
async def test_cli_dry_run_prints_counts_and_writes_nothing(
    db: asyncpg.Connection,
    scratch_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backend.scripts.ingest_injury_reports as cli

    _put(
        LocalInjuryReportStore(tmp_path),
        "Injury-Report_2024-01-15_05PM.pdf",
        layout_b_pdf(),
        REPORT_AT.astimezone(UTC),
    )
    monkeypatch.setattr(settings, "injury_pdf_dir", str(tmp_path))
    monkeypatch.setattr(settings, "database_url", scratch_dsn)
    code = await cli._run(dry_run=True)
    captured = capsys.readouterr()
    assert code == 0
    assert "dry_run" in captured.out
    assert "rows_written=0" in captured.out
    assert "postgresql://" not in captured.out + captured.err
    assert await db.fetchval("SELECT count(*) FROM nba_injury_report_rows") == 0
