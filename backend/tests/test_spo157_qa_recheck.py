"""Recheck gaps for the SPO-157 follow-up. Every PDF and every name is synthetic.

reportlab draws the bytes in memory. Nothing here reads a stored official PDF.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.migrations.runner import upgrade
from app.services.injury_report_ingest import ingest_store, injury_rows_as_of
from app.services.injury_report_store import LocalInjuryReportStore
from tests.test_spo157_qa_review import TITLE, _b_line, _layout_b, _put


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    applied = await upgrade(scratch_conn)
    assert applied[-1] == "007"
    await scratch_conn.execute(
        """
        INSERT INTO seasons (league, season_start_year, label) VALUES
            ('nba', 2023, '2023-24'),
            ('wnba', 2024, '2024');
        INSERT INTO teams (league, bdl_team_id, abbreviation, full_name) VALUES
            ('nba', 2, 'BOS', 'Boston Celtics'),
            ('nba', 20, 'NYK', 'New York Knicks'),
            ('wnba', 1, 'LVA', 'Las Vegas Aces'),
            ('wnba', 2, 'NYL', 'New York Liberty');
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
async def test_a_replaced_minute_leaves_other_report_times_and_the_other_league(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """The DELETE is limited to this league and this report_at.

    Kim is removed from the corrected minute. A row at the next minute, and
    a WNBA row at the same instant, both stay.
    """
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    later = moment + timedelta(hours=1)
    await db.execute(
        """
        INSERT INTO nba_injury_report_rows (
            league, report_at, game_date, matchup, team_name,
            bdl_game_id, bdl_team_id, player_raw, status,
            not_yet_submitted, all_players_available
        ) VALUES
            ('nba', $2, '2024-01-15', 'BOS@NYK', 'Boston Celtics', 701, 2,
             'Later, Lou', 'Out', false, false),
            ('wnba', $1, '2024-01-15', 'BOS@NYK', 'Boston Celtics', NULL, NULL,
             'Other, League', 'Out', false, false)
        """,
        moment,
        later,
    )
    store = LocalInjuryReportStore(tmp_path)
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(
            TITLE,
            [
                _b_line(player="Doe, Alex", status="Out", reason="Rest"),
                _b_line(player="Kim, Bea", team="New York Knicks", status="Out", reason="Rest"),
            ],
        ),
        moment,
    )
    assert (await ingest_store(db, store))[0].rows_written == 2
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(player="Doe, Alex", status="Out", reason="Rest")]),
        moment,
    )
    second = await ingest_store(db, store)
    assert second[0].tag == "stored"
    assert second[0].rows_written == 1
    assert [row["player_raw"] for row in await injury_rows_as_of(db, 701)] == ["Doe, Alex"]
    kept = await db.fetch(
        """
        SELECT league, player_raw
        FROM nba_injury_report_rows
        WHERE player_raw IN ('Later, Lou', 'Other, League')
        ORDER BY league
        """
    )
    assert [(row["league"], row["player_raw"]) for row in kept] == [
        ("nba", "Later, Lou"),
        ("wnba", "Other, League"),
    ]


@pytest.mark.asyncio
async def test_dry_run_does_not_delete_a_player_the_file_omits(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """dry_run returns before the write transaction, so the DELETE does not run."""
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    store = LocalInjuryReportStore(tmp_path)
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(
            TITLE,
            [
                _b_line(player="Doe, Alex", status="Out", reason="Rest"),
                _b_line(player="Kim, Bea", team="New York Knicks", status="Out", reason="Rest"),
            ],
        ),
        moment,
    )
    assert (await ingest_store(db, store))[0].rows_written == 2
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(player="Doe, Alex", status="Out", reason="Rest")]),
        moment,
    )
    dry = await ingest_store(db, store, dry_run=True)
    assert dry[0].tag == "dry_run"
    assert dry[0].rows_written == 0
    names = await db.fetch(
        "SELECT player_raw FROM nba_injury_report_rows ORDER BY player_raw"
    )
    assert [row["player_raw"] for row in names] == ["Doe, Alex", "Kim, Bea"]


@pytest.mark.asyncio
async def test_a_missed_resolve_with_the_same_status_writes_nothing(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """The WHERE clause compares COALESCE(EXCLUDED, stored), so a null miss is not a change.

    Status, reason, and the resolved game id stay. The call is unchanged.
    """
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    store = LocalInjuryReportStore(tmp_path)
    pdf = _layout_b(TITLE, [_b_line(player="Doe, Alex", status="Out", reason="Rest")])
    _put(store, "Injury-Report_2024-01-15_05PM.pdf", pdf, moment)
    assert (await ingest_store(db, store))[0].tag == "stored"
    await db.execute("UPDATE games SET date = '2024-02-01' WHERE bdl_game_id = 701")
    second = await ingest_store(db, store)
    assert second[0].tag == "unchanged"
    assert second[0].rows_written == 0
    row = await db.fetchrow(
        "SELECT status, bdl_game_id, bdl_team_id FROM nba_injury_report_rows"
    )
    assert row["status"] == "Out"
    assert row["bdl_game_id"] == 701
    assert row["bdl_team_id"] == 2
    assert [item["status"] for item in await injury_rows_as_of(db, 701)] == ["Out"]


@pytest.mark.asyncio
async def test_a_successful_file_with_no_player_rows_keeps_that_minute(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """A title and a header with no player lines must not wipe that minute.

    The call is failed, it does not count a delete, and Doe stays stored.
    """
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    store = LocalInjuryReportStore(tmp_path)
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(player="Doe, Alex", status="Out", reason="Rest")]),
        moment,
    )
    assert (await ingest_store(db, store))[0].rows_written == 1
    _put(store, "Injury-Report_2024-01-15_05PM.pdf", _layout_b(TITLE, []), moment)
    second = await ingest_store(db, store)
    assert second[0].tag == "failed"
    assert second[0].rows_written == 0
    assert await db.fetchval("SELECT player_raw FROM nba_injury_report_rows") == "Doe, Alex"
    assert [row["player_raw"] for row in await injury_rows_as_of(db, 701)] == ["Doe, Alex"]
