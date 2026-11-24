"""QA gaps for SPO-157. Every PDF and every name in this file is synthetic.

reportlab draws the bytes in memory. Nothing here reads a stored official PDF.
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
from app.services.injury_report_ingest import (
    LEAGUE,
    _INSERT_REFRESH,
    _INSERT_ROW,
    ingest_report,
    ingest_store,
    injury_rows_as_of,
)
from app.services.injury_report_parser import parse_pdf
from app.services.injury_report_store import LocalInjuryReportStore

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

TITLE = "Injury Report: 01/15/24 05:30 PM"
GAP_07 = datetime(2024, 3, 10, 7, 0, tzinfo=UTC)


def _pdf(
    title: str | None,
    lines: list[list[tuple[float, str]]],
    *,
    headers: list[tuple[float, str]],
    width: float,
) -> bytes:
    """Draw one in-memory PDF. ``lines`` are rows of ``(x, text)`` cells."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width, 620))
    pdf.setProducer("iTextSharp 5.5.0")
    pdf.setFont("Helvetica", 8)
    if title is not None:
        pdf.drawString(40, 590, title)
    for x, label in headers:
        pdf.drawString(x, 550, label)
    y = 500
    for cells in lines:
        for x, text in cells:
            pdf.drawString(x, y, text)
        y -= 40
    pdf.save()
    return buffer.getvalue()


_B_HEADERS = [
    (DATE_X, "Game Date"),
    (TIME_X, "Game Time"),
    (MATCH_X, "Matchup"),
    (TEAM_X, "Team"),
    (PLAYER_X, "Player Name"),
    (STATUS_X, "Current Status"),
    (REASON_X, "Reason"),
]


def _b_line(
    *,
    game_date: str = "01/15/2024",
    game_time: str = "07:00 (ET)",
    matchup: str = "BOS@NYK",
    team: str = "Boston Celtics",
    player: str = "",
    status: str = "",
    reason: str = "",
) -> list[tuple[float, str]]:
    cells = [
        (DATE_X, game_date),
        (TIME_X, game_time),
        (MATCH_X, matchup),
        (TEAM_X, team),
    ]
    if player:
        cells.append((PLAYER_X, player))
    if status:
        cells.append((STATUS_X, status))
    if reason:
        cells.append((REASON_X, reason))
    return cells


def _layout_b(title: str | None, rows: list[list[tuple[float, str]]]) -> bytes:
    return _pdf(title, rows, headers=_B_HEADERS, width=1100)


def _layout_a(
    *,
    status: str,
    reason: str,
    category: str,
    previous: str,
    game_time: str,
    player: str = "Doe, Alex",
) -> bytes:
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
    line = [
        (DATE_X, "01/15/2024"),
        (TIME_X, game_time),
        (MATCH_X, "BOS@NYK"),
        (TEAM_X, "Boston Celtics"),
        (PLAYER_X, player),
        (CATEGORY_X, category),
        (REASON_A_X, reason),
        (STATUS_A_X, status),
        (PREVIOUS_X, previous),
    ]
    return _pdf(TITLE, [line], headers=headers, width=1320)


def _put(store: LocalInjuryReportStore, name: str, data: bytes, modified: datetime) -> None:
    store.put_pdf(
        f"https://ak-static.cms.nba.com/referee/injury/{name}",
        data,
        fetched_at=datetime(2024, 1, 15, 18, 0, tzinfo=UTC),
        last_modified_raw="Mon, 15 Jan 2024 18:00:00 GMT",
        last_modified_utc=modified.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    applied = await upgrade(scratch_conn)
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


def test_a_0200_title_is_not_stored_as_the_0300_instant() -> None:
    """02:00 and 02:59 on 2024-03-10 do not exist. 02:00 would otherwise be 07:00 UTC.

    07:00 UTC is also the real 03:00 AM title. The missing minute must not
    share that instant. With no Last-Modified and no filename, the parse fails.
    """
    body = [_b_line(game_date="03/10/2024", player="Doe, Alex", status="Out", reason="Rest")]
    for title in (
        "Injury Report: 03/10/24 02:00 AM",
        "Injury Report: 03/10/24 02:59 AM",
    ):
        result = parse_pdf(_layout_b(title, body))
        assert result.tag == "failed", title
        assert result.report_at is None
        assert result.report_at != GAP_07

    named = parse_pdf(
        _layout_b(None, body),
        filename="Injury-Report_2024-03-10_02_00AM.pdf",
    )
    assert named.tag == "failed"
    assert named.report_at is None

    real = parse_pdf(_layout_b("Injury Report: 03/10/24 03:00 AM", body))
    assert real.tag == "ok"
    assert real.report_at_source == "title"
    assert real.report_at == GAP_07

    before = parse_pdf(_layout_b("Injury Report: 03/10/24 01:30 AM", body))
    assert before.tag == "ok"
    assert before.report_at == datetime(2024, 3, 10, 6, 30, tzinfo=UTC)


def test_a_fallback_filename_at_0130_keeps_the_earlier_offset() -> None:
    """``01_30AM`` is the same ambiguous wall time as the title test, via the filename."""
    body = [_b_line(game_date="11/03/2024", player="Doe, Alex", status="Out", reason="Rest")]
    result = parse_pdf(
        _layout_b(None, body),
        filename="Injury-Report_2024-11-03_01_30AM.pdf",
    )
    assert result.tag == "ok"
    assert result.report_at_source == "filename"
    assert result.report_at == datetime(2024, 11, 3, 5, 30, tzinfo=UTC)
    assert result.report_at != datetime(2024, 11, 3, 6, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_status_change_updates_the_other_corrected_columns(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """One natural key. The second PDF changes every column the upsert is allowed to change.

    ``all_players_available`` stays false. A player row cannot flip that flag
    without leaving the natural key.
    """
    store = LocalInjuryReportStore(tmp_path)
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_a(
            status="Out",
            reason="Left Thumb Sprain",
            category="Injury/Illness",
            previous="Available",
            game_time="07:00 (ET)",
        ),
        datetime(2024, 1, 15, 22, 30, tzinfo=UTC),
    )
    first = await ingest_store(db, store)
    assert first[0].tag == "stored"
    assert first[0].rows_written == 1

    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_a(
            status="Questionable",
            reason="Personal Reasons",
            category="Personal Reasons",
            previous="Out",
            game_time="08:30 (ET)",
        ),
        datetime(2024, 1, 15, 22, 30, tzinfo=UTC),
    )
    second = await ingest_store(db, store)
    assert second[0].tag == "stored"
    assert second[0].rows_written == 1
    assert await db.fetchval("SELECT count(*) FROM nba_injury_report_rows") == 1
    row = await db.fetchrow(
        """
        SELECT status, reason, category, previous_status, game_time_et,
               all_players_available, bdl_game_id, bdl_team_id, league
        FROM nba_injury_report_rows
        """
    )
    assert row["status"] == "Questionable"
    assert row["reason"] == "Personal Reasons"
    assert row["category"] == "Personal Reasons"
    assert row["previous_status"] == "Out"
    assert row["game_time_et"] == "08:30 (ET)"
    assert row["all_players_available"] is False
    assert row["bdl_game_id"] == 701
    assert row["bdl_team_id"] == 2
    assert row["league"] == LEAGUE
    pit = await injury_rows_as_of(db, 701)
    assert [(item["status"], item["previous_status"], item["game_time_et"]) for item in pit] == [
        ("Questionable", "Out", "08:30 (ET)")
    ]


@pytest.mark.asyncio
async def test_a_status_change_keeps_bdl_player_id_and_match_method(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """Those two columns are filled after the first ingest. The correction must leave them."""
    await db.execute(
        """
        INSERT INTO players (league, bdl_player_id, display_name)
        VALUES ('nba', 4242, 'Alex Doe')
        """
    )
    store = LocalInjuryReportStore(tmp_path)
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(player="Doe, Alex", status="Out", reason="Rest")]),
        moment,
    )
    assert (await ingest_store(db, store))[0].rows_written == 1
    await db.execute(
        """
        UPDATE nba_injury_report_rows
        SET bdl_player_id = 4242, match_method = 'held'
        WHERE player_raw = 'Doe, Alex'
        """
    )
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(player="Doe, Alex", status="Questionable", reason="Rest")]),
        moment,
    )
    second = await ingest_store(db, store)
    assert second[0].tag == "stored"
    assert second[0].rows_written == 1
    kept = await db.fetchrow(
        """
        SELECT status, bdl_player_id, match_method
        FROM nba_injury_report_rows
        WHERE player_raw = 'Doe, Alex'
        """
    )
    assert kept["status"] == "Questionable"
    assert kept["bdl_player_id"] == 4242
    assert kept["match_method"] == "held"


@pytest.mark.asyncio
async def test_a_player_dropped_from_the_corrected_pdf_is_removed(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """The second file names only Doe. Kim's row for that minute is deleted.

    Doe is unchanged, so the one write is the delete. The point-in-time
    read returns Doe. The refresh row is rewritten with this file's counts.
    """
    store = LocalInjuryReportStore(tmp_path)
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    both = _layout_b(
        TITLE,
        [
            _b_line(player="Doe, Alex", status="Out", reason="Rest"),
            _b_line(player="Kim, Bea", team="New York Knicks", status="Out", reason="Rest"),
        ],
    )
    _put(store, "Injury-Report_2024-01-15_05PM.pdf", both, moment)
    first = await ingest_store(db, store)
    assert first[0].rows_written == 2

    only_doe = _layout_b(TITLE, [_b_line(player="Doe, Alex", status="Out", reason="Rest")])
    _put(store, "Injury-Report_2024-01-15_05PM.pdf", only_doe, moment)
    second = await ingest_store(db, store)
    assert second[0].tag == "stored"
    assert second[0].rows_written == 1
    names = [row["player_raw"] for row in await injury_rows_as_of(db, 701)]
    assert names == ["Doe, Alex"]
    assert await db.fetchval("SELECT count(*) FROM nba_injury_report_rows") == 1
    refresh = await db.fetchrow(
        """
        SELECT complete, rows_seen, rows_written
        FROM source_refreshes
        WHERE source = 'injuries_nba_official'
        """
    )
    assert refresh["complete"] is True
    assert refresh["rows_seen"] == 1
    assert refresh["rows_written"] == 1


@pytest.mark.asyncio
async def test_a_not_yet_submitted_placeholder_is_removed_when_the_team_lists_a_player(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """The corrected file lists Doe and does not repeat the team note.

    NOT YET SUBMITTED is its own natural key. That placeholder is deleted.
    The write count is Doe's insert plus that delete. The empty row is gone.
    """
    store = LocalInjuryReportStore(tmp_path)
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(reason="NOT YET SUBMITTED")]),
        moment,
    )
    assert (await ingest_store(db, store))[0].tag == "stored"
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(player="Doe, Alex", status="Questionable", reason="Rest")]),
        moment,
    )
    second = await ingest_store(db, store)
    assert second[0].tag == "stored"
    assert second[0].rows_written == 2
    rows = await injury_rows_as_of(db, 701)
    assert [(row["player_raw"], row["not_yet_submitted"], row["status"]) for row in rows] == [
        ("Doe, Alex", False, "Questionable"),
    ]
    assert await db.fetchval(
        "SELECT count(*) FROM nba_injury_report_rows WHERE not_yet_submitted"
    ) == 0


@pytest.mark.asyncio
async def test_an_identical_rerun_does_not_overwrite_a_complete_refresh_that_wrote_rows(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """A complete refresh with writes stays put when the next call writes 0 rows.

    A later call that does change a column replaces ``rows_written`` with that
    call's count. The earlier count is not kept.
    """
    store = LocalInjuryReportStore(tmp_path)
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    original = _layout_b(
        TITLE,
        [
            _b_line(player="Doe, Alex", status="Out", reason="Rest"),
            _b_line(player="Kim, Bea", team="New York Knicks", status="Out", reason="Rest"),
        ],
    )
    _put(store, "Injury-Report_2024-01-15_05PM.pdf", original, moment)
    assert (await ingest_store(db, store))[0].rows_written == 2
    again = await ingest_store(db, store)
    assert again[0].tag == "unchanged"
    assert again[0].rows_written == 0
    held = await db.fetchrow(
        """
        SELECT complete, rows_seen, rows_written, error
        FROM source_refreshes
        WHERE source = 'injuries_nba_official'
        """
    )
    assert held["complete"] is True
    assert held["rows_seen"] == 2
    assert held["rows_written"] == 2
    assert held["error"] is None

    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(
            TITLE,
            [
                _b_line(player="Doe, Alex", status="Questionable", reason="Rest"),
                _b_line(player="Kim, Bea", team="New York Knicks", status="Out", reason="Rest"),
            ],
        ),
        moment,
    )
    changed = await ingest_store(db, store)
    assert changed[0].tag == "stored"
    assert changed[0].rows_written == 1
    replaced = await db.fetchrow(
        """
        SELECT complete, rows_seen, rows_written
        FROM source_refreshes
        WHERE source = 'injuries_nba_official'
        """
    )
    assert replaced["complete"] is True
    assert replaced["rows_seen"] == 2
    assert replaced["rows_written"] == 1


@pytest.mark.asyncio
async def test_a_later_failure_leaves_the_complete_refresh_in_place(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """A bad PDF at the same report time records the error and keeps the success.

    ``complete`` stays true. ``rows_written`` stays 1. ``error`` is set.
    """
    store = LocalInjuryReportStore(tmp_path)
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(player="Doe, Alex", status="Out", reason="Rest")]),
        moment,
    )
    first = await ingest_store(db, store)
    assert first[0].tag == "stored"
    report_at = first[0].report_at
    assert report_at is not None
    _put(store, "Injury-Report_2024-01-15_01PM.pdf", b"this is not a pdf", report_at)
    broken = next(
        item for item in store.iter_stored() if item.path.name == "Injury-Report_2024-01-15_01PM.pdf"
    )
    failed = await ingest_report(db, broken)
    assert failed.tag == "failed"
    refresh = await db.fetchrow(
        """
        SELECT complete, rows_seen, rows_written, error
        FROM source_refreshes
        WHERE source = 'injuries_nba_official' AND refreshed_at = $1
        """,
        report_at,
    )
    assert refresh["complete"] is True
    assert refresh["rows_seen"] == 1
    assert refresh["rows_written"] == 1
    assert refresh["error"] is not None
    assert await db.fetchval("SELECT count(*) FROM source_refreshes") == 1
    assert await db.fetchval("SELECT count(*) FROM nba_injury_report_rows") == 1


@pytest.mark.asyncio
async def test_a_reingest_that_cannot_resolve_the_game_keeps_bdl_game_id(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """A miss does not clear a resolved game. The new status is still readable.

    ``bdl_player_id`` and ``match_method`` stay. ``injury_rows_as_of`` keys
    on ``bdl_game_id``, so the Questionable row comes back for game 701.
    """
    await db.execute(
        """
        INSERT INTO players (league, bdl_player_id, display_name)
        VALUES ('nba', 4242, 'Alex Doe')
        """
    )
    store = LocalInjuryReportStore(tmp_path)
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(player="Doe, Alex", status="Out", reason="Rest")]),
        moment,
    )
    assert (await ingest_store(db, store))[0].tag == "stored"
    await db.execute(
        """
        UPDATE nba_injury_report_rows
        SET bdl_player_id = 4242, match_method = 'held'
        WHERE player_raw = 'Doe, Alex'
        """
    )
    await db.execute("UPDATE games SET date = '2024-02-01' WHERE bdl_game_id = 701")
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(player="Doe, Alex", status="Questionable", reason="Personal Reasons")]),
        moment,
    )
    second = await ingest_store(db, store)
    assert second[0].tag == "stored"
    row = await db.fetchrow(
        """
        SELECT status, bdl_game_id, bdl_team_id, bdl_player_id, match_method
        FROM nba_injury_report_rows
        """
    )
    assert row["status"] == "Questionable"
    assert row["bdl_game_id"] == 701
    assert row["bdl_team_id"] == 2
    assert row["bdl_player_id"] == 4242
    assert row["match_method"] == "held"
    kept = await injury_rows_as_of(db, 701)
    assert [item["status"] for item in kept] == ["Questionable"]


@pytest.mark.asyncio
async def test_asof_order_uses_id_when_the_leading_columns_tie(db: asyncpg.Connection) -> None:
    """The two rows share team, player, submission flag, and matchup.

    The January 16 row is inserted first, so its id is lower. ``game_date``
    is not an ORDER BY column, and the function does not return ``id``.
    The read still puts January 16 first. A second call returns the same dates.
    """
    report_at = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    await db.executemany(
        """
        INSERT INTO nba_injury_report_rows (
            league, report_at, game_date, matchup, team_name,
            bdl_game_id, bdl_team_id, player_raw, status,
            not_yet_submitted, all_players_available
        ) VALUES (
            'nba', $1, $2, 'BOS@NYK', 'Boston Celtics', 701, 2, 'Doe, Alex', 'Out', false, false
        )
        """,
        [
            (report_at, datetime(2024, 1, 16).date()),
            (report_at, datetime(2024, 1, 15).date()),
        ],
    )
    sql = "SELECT game_date FROM injury_report_rows_asof('nba', 701, $1)"
    first = await db.fetch(sql, report_at)
    second = await db.fetch(sql, report_at)
    assert [row["game_date"].isoformat() for row in first] == ["2024-01-16", "2024-01-15"]
    assert [row["game_date"] for row in second] == [row["game_date"] for row in first]


@pytest.mark.asyncio
async def test_007_replaces_the_old_index_and_a_second_upgrade_does_nothing(
    db: asyncpg.Connection,
) -> None:
    """The runner records 007 and skips the file. Running the file again drops and recreates one index."""
    assert await upgrade(db) == []
    names = await db.fetch(
        """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'nba_injury_report_rows'
          AND indexname = 'nba_injury_report_rows_game_report_idx'
        """
    )
    assert len(names) == 1
    assert names[0]["indexdef"].endswith("USING btree (league, bdl_game_id, report_at)")
    sql_path = Path(__file__).resolve().parents[1] / "app" / "migrations" / "007_injury_report_rows_order.sql"
    await db.execute(sql_path.read_text(encoding="utf-8"))
    again = await db.fetch(
        """
        SELECT indexdef FROM pg_indexes
        WHERE indexname = 'nba_injury_report_rows_game_report_idx'
        """
    )
    assert len(again) == 1
    assert again[0]["indexdef"].endswith("USING btree (league, bdl_game_id, report_at)")
    body = await db.fetchval(
        """
        SELECT pg_get_functiondef('injury_report_rows_asof(league_code, bigint, timestamptz)'::regprocedure)
        """
    )
    assert "ORDER BY r.team_name, r.player_raw, r.not_yet_submitted, r.matchup, r.id" in body


@pytest.mark.asyncio
async def test_reversing_007_then_006_restores_the_ordered_read(
    db: asyncpg.Connection,
) -> None:
    """A rollback removes 007 before 006. upgrade() applies 006, then 007.

    The function has ORDER BY, and the game index leads with league.
    """
    await db.execute("DELETE FROM schema_migrations WHERE version = '007'")
    await db.execute("DROP FUNCTION injury_report_rows_asof(league_code, bigint, timestamptz)")
    await db.execute("DROP TABLE nba_injury_report_rows")
    await db.execute("DELETE FROM schema_migrations WHERE version = '006'")
    assert await upgrade(db) == ["006", "007"]
    versions = await db.fetch("SELECT version FROM schema_migrations ORDER BY version")
    assert [row["version"] for row in versions] == ["001", "002", "003", "004", "005", "006", "007"]
    indexdef = await db.fetchval(
        """
        SELECT indexdef FROM pg_indexes
        WHERE indexname = 'nba_injury_report_rows_game_report_idx'
        """
    )
    assert indexdef.endswith("USING btree (league, bdl_game_id, report_at)")
    body = await db.fetchval(
        """
        SELECT pg_get_functiondef('injury_report_rows_asof(league_code, bigint, timestamptz)'::regprocedure)
        """
    )
    assert "ORDER BY r.team_name, r.player_raw, r.not_yet_submitted, r.matchup, r.id" in body


def test_league_is_bound_and_the_upsert_sql_has_no_nba_literal() -> None:
    """``LEAGUE`` is the value the writer binds. The SQL text does not quote a league."""
    assert LEAGUE == "nba"
    assert "'nba'" not in _INSERT_ROW
    assert "'nba'" not in _INSERT_REFRESH
    assert "DO UPDATE" in _INSERT_ROW
    assert "IS DISTINCT FROM" in _INSERT_ROW
    assert "bdl_player_id" not in _INSERT_ROW.split("DO UPDATE", 1)[1]
    assert "match_method" not in _INSERT_ROW.split("DO UPDATE", 1)[1]
