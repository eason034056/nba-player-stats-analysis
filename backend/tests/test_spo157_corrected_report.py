"""SPO-157: a re-issued PDF with the same title minute replaces the row.

The PDF bytes are drawn in memory. The player name and the reasons are
made up. Nothing here reads a stored official PDF.
"""

from __future__ import annotations

import io
import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.migrations.runner import upgrade
from app.services.injury_report_ingest import ingest_store, injury_rows_as_of
from app.services.injury_report_store import LocalInjuryReportStore

DATE_X = 40
MATCH_X = 250
TEAM_X = 370
PLAYER_X = 560
STATUS_X = 760
REASON_X = 900


def _pdf(status: str, reason: str) -> bytes:
    """One synthetic report. The title minute is 5:30 PM Eastern on 2024-01-15."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(1100, 620))
    pdf.setProducer("iTextSharp 5.5.0")
    pdf.setFont("Helvetica", 8)
    pdf.drawString(40, 590, "Injury Report: 01/15/24 05:30 PM")
    for x, label in (
        (DATE_X, "Game Date"),
        (140, "Game Time"),
        (MATCH_X, "Matchup"),
        (TEAM_X, "Team"),
        (PLAYER_X, "Player Name"),
        (STATUS_X, "Current Status"),
        (REASON_X, "Reason"),
    ):
        pdf.drawString(x, 550, label)
    for x, text in (
        (DATE_X, "01/15/2024"),
        (MATCH_X, "BOS@NYK"),
        (TEAM_X, "Boston Celtics"),
        (PLAYER_X, "Doe, Alex"),
        (STATUS_X, status),
        (REASON_X, reason),
    ):
        pdf.drawString(x, 500, text)
    pdf.save()
    return buffer.getvalue()


def _put(store: LocalInjuryReportStore, data: bytes) -> None:
    store.put_pdf(
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2024-01-15_05PM.pdf",
        data,
        fetched_at=datetime(2024, 1, 15, 22, 30, tzinfo=UTC),
        last_modified_raw="Mon, 15 Jan 2024 22:30:00 GMT",
        last_modified_utc="2024-01-15T22:30:00Z",
    )


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    applied = await upgrade(scratch_conn)
    assert "006" in applied
    assert applied[-1] == "007"
    await scratch_conn.execute(
        """
        INSERT INTO seasons (league, season_start_year, label)
        VALUES ('nba', 2023, '2023-24');
        INSERT INTO teams (league, bdl_team_id, abbreviation, full_name) VALUES
            ('nba', 2, 'BOS', 'Boston Celtics'),
            ('nba', 20, 'NYK', 'New York Knicks');
        INSERT INTO games (
            league, bdl_game_id, season, date, datetime_utc, status_state,
            season_type, home_team_id, visitor_team_id
        ) VALUES (
            'nba', 701, 2023, '2024-01-15', '2024-01-16 02:00:00+00',
            'scheduled', 'regular_season', 20, 2
        );
        """
    )
    return scratch_conn


@pytest.mark.asyncio
async def test_a_corrected_pdf_replaces_status_and_an_identical_retry_does_not(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """The second PDF keeps the title minute and changes Out to Questionable.

    The natural key does not include status. The stored row must become
    Questionable, and a later point-in-time read must return that status.
    Storing the corrected file again inserts no second row.
    """
    store = LocalInjuryReportStore(tmp_path)
    _put(store, _pdf("Out", "Rest"))
    first = await ingest_store(db, store)
    assert first[0].tag == "stored"
    assert first[0].rows_written == 1

    _put(store, _pdf("Questionable", "Personal Reasons"))
    second = await ingest_store(db, store)
    assert second[0].tag == "stored"
    assert second[0].rows_written == 1
    assert await db.fetchval("SELECT count(*) FROM nba_injury_report_rows") == 1

    stored = await db.fetchrow(
        "SELECT status, reason, category FROM nba_injury_report_rows"
    )
    assert stored["status"] == "Questionable"
    assert stored["reason"] == "Personal Reasons"
    assert stored["category"] == "Personal Reasons"

    pit = await injury_rows_as_of(db, 701)
    assert [(row["status"], row["reason"], row["category"]) for row in pit] == [
        ("Questionable", "Personal Reasons", "Personal Reasons")
    ]
    sql_rows = await db.fetch(
        """
        SELECT status, reason, category
        FROM injury_report_rows_asof('nba', 701)
        """
    )
    assert [(row["status"], row["reason"]) for row in sql_rows] == [
        ("Questionable", "Personal Reasons")
    ]

    refresh = await db.fetchrow(
        """
        SELECT complete, rows_written
        FROM source_refreshes
        WHERE source = 'injuries_nba_official'
        """
    )
    assert refresh["complete"] is True
    assert refresh["rows_written"] == 1
    assert await db.fetchval("SELECT count(*) FROM source_refreshes") == 1

    third = await ingest_store(db, store)
    assert third[0].tag == "unchanged"
    assert third[0].rows_written == 0
    assert await db.fetchval("SELECT count(*) FROM nba_injury_report_rows") == 1
    assert await db.fetchval("SELECT status FROM nba_injury_report_rows") == "Questionable"
