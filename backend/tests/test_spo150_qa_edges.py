"""QA edges for SPO-150. Every PDF and every name in this file is synthetic.

reportlab draws the bytes in memory. parse_pdf, ingest_store, and
injury_rows_as_of are the functions under test. Nothing here reads a
stored official PDF or a copied report line.
"""

from __future__ import annotations

import io
import sys
from datetime import UTC, date, datetime, timedelta
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
from app.services.injury_report_parser import category_from_reason, parse_pdf
from app.services.injury_report_store import LocalInjuryReportStore

DATE_X = 40
TIME_X = 140
MATCH_X = 250
TEAM_X = 370
PLAYER_X = 560
STATUS_X = 760
REASON_X = 900


def _pdf(title: str | None, lines: list[tuple[float, list[tuple[float, str]]]] | None = None) -> bytes:
    """Build one in-memory PDF. ``lines`` are (y, [(x, text), ...])."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(1100, 620))
    pdf.setProducer("iTextSharp 5.5.0")
    pdf.setFont("Helvetica", 8)
    if title is not None:
        pdf.drawString(40, 590, title)
    y_header = 550
    for x, label in (
        (DATE_X, "Game Date"),
        (TIME_X, "Game Time"),
        (MATCH_X, "Matchup"),
        (TEAM_X, "Team"),
        (PLAYER_X, "Player Name"),
        (STATUS_X, "Current Status"),
        (REASON_X, "Reason"),
    ):
        pdf.drawString(x, y_header, label)
    for y, cells in lines or []:
        for x, text in cells:
            pdf.drawString(x, y, text)
    pdf.save()
    return buffer.getvalue()


def _player_line(
    y: float,
    *,
    game_date: str = "01/15/2024",
    matchup: str = "BOS@NYK",
    team: str = "Boston Celtics",
    player: str = "Doe, Alex",
    status: str = "Out",
    reason: str = "Rest",
    include_context: bool = True,
) -> tuple[float, list[tuple[float, str]]]:
    cells: list[tuple[float, str]] = []
    if include_context:
        cells.extend(
            (
                (DATE_X, game_date),
                (MATCH_X, matchup),
                (TEAM_X, team),
            )
        )
    if player:
        cells.append((PLAYER_X, player))
    if status:
        cells.append((STATUS_X, status))
    if reason:
        cells.append((REASON_X, reason))
    return y, cells


def test_title_12am_and_12pm_convert_in_winter_and_summer() -> None:
    """The title clock is Eastern. 12:00 AM is midnight and 12:00 PM is noon.

    January is UTC-5. July is UTC-4. Both use the same parser path.
    """
    body = [_player_line(500)]
    expected = {
        "Injury Report: 01/15/24 12:00 AM": datetime(2024, 1, 15, 5, 0, tzinfo=UTC),
        "Injury Report: 01/15/24 12:00 PM": datetime(2024, 1, 15, 17, 0, tzinfo=UTC),
        "Injury Report: 01/15/2024 12:00 AM": datetime(2024, 1, 15, 5, 0, tzinfo=UTC),
        "Injury Report: 07/15/24 12:00 AM": datetime(2024, 7, 15, 4, 0, tzinfo=UTC),
        "Injury Report: 07/15/24 12:00 PM": datetime(2024, 7, 15, 16, 0, tzinfo=UTC),
    }
    for title, instant in expected.items():
        result = parse_pdf(_pdf(title, body))
        assert result.tag == "ok"
        assert result.report_at_source == "title"
        assert result.report_at == instant


def test_filename_12am_and_12pm_when_the_title_is_missing() -> None:
    """An hour filename is HH:30. A minute filename is the printed minute.

    12AM is 12:30 AM. 12_00AM is midnight. July shifts the UTC hour.
    """
    data = _pdf(None, [_player_line(500)])
    expected = {
        "Injury-Report_2024-01-15_12AM.pdf": datetime(2024, 1, 15, 5, 30, tzinfo=UTC),
        "Injury-Report_2024-01-15_12_00AM.pdf": datetime(2024, 1, 15, 5, 0, tzinfo=UTC),
        "Injury-Report_2024-01-15_12PM.pdf": datetime(2024, 1, 15, 17, 30, tzinfo=UTC),
        "Injury-Report_2024-01-15_12_00PM.pdf": datetime(2024, 1, 15, 17, 0, tzinfo=UTC),
        "Injury-Report_2024-07-15_12AM.pdf": datetime(2024, 7, 15, 4, 30, tzinfo=UTC),
        "Injury-Report_2024-07-15_12_00AM.pdf": datetime(2024, 7, 15, 4, 0, tzinfo=UTC),
        "Injury-Report_2024-07-15_12PM.pdf": datetime(2024, 7, 15, 16, 30, tzinfo=UTC),
        "Injury-Report_2024-07-15_12_00PM.pdf": datetime(2024, 7, 15, 16, 0, tzinfo=UTC),
    }
    for filename, instant in expected.items():
        result = parse_pdf(data, filename=filename)
        assert result.tag == "ok", filename
        assert result.report_at_source == "filename"
        assert result.report_at == instant


def test_a_malformed_title_uses_last_modified_before_the_filename() -> None:
    """A title that does not name a real Eastern minute is not the report clock.

    Last-Modified wins over the filename. A naive Last-Modified is ignored,
    and the filename is used. An impossible calendar day follows the same rule.
    """
    data = _pdf("Injury Report: TBD", [_player_line(500)])
    last_modified = datetime(2024, 3, 10, 12, 0, tzinfo=UTC)
    result = parse_pdf(
        data,
        last_modified=last_modified,
        filename="Injury-Report_2024-03-10_05PM.pdf",
    )
    assert result.tag == "ok"
    assert result.report_at_source == "last_modified"
    assert result.report_at == last_modified

    invalid = _pdf("Injury Report: 02/31/24 05:30 PM", [_player_line(500)])
    fallback = parse_pdf(
        invalid,
        last_modified=last_modified,
        filename="Injury-Report_2024-01-15_12AM.pdf",
    )
    assert fallback.tag == "ok"
    assert fallback.report_at_source == "last_modified"
    assert fallback.report_at == last_modified

    naive = datetime(2024, 3, 10, 12, 0)
    from_name = parse_pdf(
        data,
        last_modified=naive,
        filename="Injury-Report_2024-01-15_12_00AM.pdf",
    )
    assert from_name.report_at_source == "filename"
    assert from_name.report_at == datetime(2024, 1, 15, 5, 0, tzinfo=UTC)


def test_a_title_in_the_spring_forward_gap_is_not_the_report_clock() -> None:
    """02:30 AM on 2024-03-10 does not exist in America/New_York.

    Building that wall clock with a zone attaches the pre-transition
    offset, so the UTC instant is 07:30, which is 3:30 AM EDT and later
    than a real 3:00 AM title (07:00 UTC). The report clock must not be
    that instant. Last-Modified is the fallback, the same rule as any
    other title that does not name a real minute.
    """
    last_modified = datetime(2024, 3, 10, 11, 0, tzinfo=UTC)
    titled = parse_pdf(
        _pdf("Injury Report: 03/10/24 02:30 AM", [_player_line(500, game_date="03/10/2024")]),
        last_modified=last_modified,
        filename="Injury-Report_2024-03-10_05PM.pdf",
    )
    assert titled.tag == "ok"
    assert titled.report_at_source == "last_modified"
    assert titled.report_at == last_modified
    assert titled.report_at != datetime(2024, 3, 10, 7, 30, tzinfo=UTC)

    # 02AM means 02:30, the same missing minute. No Last-Modified is passed,
    # so there is no real clock left. The parse fails instead of inventing
    # 07:30 UTC or a minute past the gap.
    from_name = parse_pdf(
        _pdf(None, [_player_line(500, game_date="03/10/2024")]),
        filename="Injury-Report_2024-03-10_02AM.pdf",
    )
    assert from_name.tag == "failed"
    assert from_name.report_at is None


def test_category_prefixes_and_a_split_reason() -> None:
    """Each prefix is the category, including both apostrophes in Coach's Decision.

    A reason that continues on the next line, within 16 points, stays one
    reason, and the prefix is read from the joined text.
    """
    curly = "Coach\u2019s Decision"
    assert category_from_reason(curly) == curly
    lines = [
        _player_line(500, player="One, Lea", status="Out", reason="League Suspension"),
        _player_line(470, player="Two, Con", status="Out", reason="Concussion Protocol", include_context=False),
        _player_line(440, player="Three, Tea", status="Out", reason="Team Suspension", include_context=False),
        _player_line(410, player="Four, Coa", status="Out", reason="Coach's Decision", include_context=False),
        _player_line(380, player="Five, Kne", status="Questionable", reason="Injury/Illness - Right Knee;", include_context=False),
        (372, [(REASON_X, "Soreness")]),
    ]
    result = parse_pdf(_pdf("Injury Report: 01/15/24 05:30 PM", lines))
    assert result.tag == "ok"
    by_name = {row.player_raw: row for row in result.rows}
    assert by_name["One, Lea"].category == "League Suspension"
    assert by_name["Two, Con"].category == "Concussion Protocol"
    assert by_name["Three, Tea"].category == "Team Suspension"
    assert by_name["Four, Coa"].category == "Coach's Decision"
    joined = by_name["Five, Kne"]
    assert joined.reason == "Injury/Illness - Right Knee; Soreness"
    assert joined.category == "Injury/Illness"
    assert result.unattached_reasons == 0


def test_not_yet_submitted_clears_a_name_on_the_same_line() -> None:
    """A NOT YET SUBMITTED line is a team row even when a name was drawn beside it."""
    result = parse_pdf(
        _pdf(
            "Injury Report: 01/15/24 05:30 PM",
            [_player_line(500, player="Doe, Alex", status="Out", reason="NOT YET SUBMITTED")],
        )
    )
    assert result.tag == "ok"
    assert result.nys_rows == 1
    assert result.player_rows == 0
    row = result.rows[0]
    assert row.not_yet_submitted is True
    assert row.player_raw == ""
    assert row.status is None
    assert row.reason is None


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    applied = await upgrade(scratch_conn)
    assert "006" in applied
    assert applied[-1] == "007"
    await scratch_conn.execute(
        """
        INSERT INTO seasons (league, season_start_year, label) VALUES
            ('nba', 2023, '2023-24'),
            ('nba', 2024, '2024-25'),
            ('wnba', 2024, '2024');
        INSERT INTO teams (league, bdl_team_id, abbreviation, full_name) VALUES
            ('nba', 2, 'BOS', 'Boston Celtics'),
            ('nba', 20, 'NYK', 'New York Knicks'),
            ('wnba', 1, 'LVA', 'Las Vegas Aces'),
            ('wnba', 2, 'NYL', 'New York Liberty');
        """
    )
    return scratch_conn


def _put(store: LocalInjuryReportStore, name: str, data: bytes, modified: datetime) -> None:
    store.put_pdf(
        f"https://ak-static.cms.nba.com/referee/injury/{name}",
        data,
        fetched_at=datetime(2024, 1, 15, 18, 0, tzinfo=UTC),
        last_modified_raw="Mon, 15 Jan 2024 18:00:00 GMT",
        last_modified_utc=modified.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def _status_pdf(status: str, reason: str) -> bytes:
    return _pdf(
        "Injury Report: 01/15/24 05:30 PM",
        [_player_line(500, player="Doe, Alex", status=status, reason=reason)],
    )


@pytest.mark.asyncio
async def test_a_changed_status_at_the_same_key_updates_the_row(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """The second PDF shares the natural key and changes the status.

    This was ``test_a_changed_status_at_the_same_key_writes_zero_rows``.
    That name locked ON CONFLICT DO NOTHING, which left Out in place.
    That drop is the bug. The row count stays one, and the stored
    status becomes Questionable.
    """
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    store = LocalInjuryReportStore(tmp_path)
    _put(store, "Injury-Report_2024-01-15_05PM.pdf", _status_pdf("Out", "Rest"), moment)
    first = await ingest_store(db, store)
    assert first[0].tag == "stored"
    assert first[0].rows_written == 1

    _put(store, "Injury-Report_2024-01-15_05PM.pdf", _status_pdf("Questionable", "Personal Reasons"), moment)
    second = await ingest_store(db, store)
    assert second[0].tag == "stored"
    assert second[0].rows_written == 1
    assert await db.fetchval("SELECT count(*) FROM nba_injury_report_rows") == 1
    status = await db.fetchval("SELECT status FROM nba_injury_report_rows")
    reason = await db.fetchval("SELECT reason FROM nba_injury_report_rows")
    assert status == "Questionable"
    assert reason == "Personal Reasons"
    refresh = await db.fetchrow(
        "SELECT complete, rows_written FROM source_refreshes WHERE source = 'injuries_nba_official'"
    )
    assert refresh["complete"] is True
    assert refresh["rows_written"] == 1
    assert await db.fetchval("SELECT count(*) FROM source_refreshes") == 1


@pytest.mark.asyncio
async def test_dry_run_writes_nothing_for_a_good_pdf_and_a_broken_one(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    store = LocalInjuryReportStore(tmp_path)
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    _put(store, "Injury-Report_2024-01-15_01PM.pdf", b"this is not a pdf", datetime(2024, 1, 15, 18, 30, tzinfo=UTC))
    _put(store, "Injury-Report_2024-01-15_05PM.pdf", _status_pdf("Out", "Rest"), moment)
    dry = await ingest_store(db, store, dry_run=True)
    assert {item.tag for item in dry} == {"dry_run", "failed"}
    assert all(item.rows_written == 0 for item in dry)
    assert await db.fetchval("SELECT count(*) FROM nba_injury_report_rows") == 0
    assert await db.fetchval("SELECT count(*) FROM source_refreshes") == 0

    written = await ingest_store(db, store)
    assert sum(item.rows_written for item in written) == 1
    again = await ingest_store(db, store, dry_run=True)
    assert all(item.rows_written == 0 for item in again)
    assert await db.fetchval("SELECT count(*) FROM nba_injury_report_rows") == 1
    assert await db.fetchval(
        "SELECT count(*) FROM source_refreshes WHERE complete"
    ) == 1


async def _game(
    conn: asyncpg.Connection,
    league: str,
    game_id: int,
    on: date,
    tip: datetime,
    season: int,
    home: int,
    away: int,
) -> None:
    await conn.execute(
        """
        INSERT INTO games (
            league, bdl_game_id, season, date, datetime_utc, status_state,
            season_type, home_team_id, visitor_team_id
        ) VALUES ($1, $2, $3, $4, $5, 'scheduled', 'regular_season', $6, $7)
        """,
        league,
        game_id,
        season,
        on,
        tip,
        home,
        away,
    )


async def _row(
    conn: asyncpg.Connection,
    league: str,
    game_id: int,
    report_at: datetime,
    team_id: int,
    team_name: str,
    player: str,
    status: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO nba_injury_report_rows (
            league, report_at, game_date, matchup, team_name,
            bdl_game_id, bdl_team_id, player_raw, status,
            not_yet_submitted, all_players_available
        ) VALUES ($1, $2, $3, 'BOS@NYK', $4, $5, $6, $7, $8, false, false)
        """,
        league,
        report_at,
        report_at.date(),
        team_name,
        game_id,
        team_id,
        player,
        status,
    )


@pytest.mark.asyncio
async def test_spring_forward_night_selects_the_report_at_tip_minus_3h(
    db: asyncpg.Connection,
) -> None:
    """Tip 2024-03-10 07:00 UTC is 3:00 AM EDT. T is 04:00 UTC, which is 11:00 PM EST on March 9.

    A report at T is selected. A report one second later is stored and is not.
    """
    tip = datetime(2024, 3, 10, 7, 0, tzinfo=UTC)
    await _game(db, "nba", 801, date(2024, 3, 10), tip, 2023, 20, 2)
    t_value = await db.fetchval("SELECT game_as_of('nba', 801)")
    assert t_value == tip - timedelta(hours=3)
    titled = parse_pdf(
        _pdf("Injury Report: 03/09/24 11:00 PM", [_player_line(500, game_date="03/09/2024")])
    )
    assert titled.tag == "ok"
    assert titled.report_at == t_value
    await _row(db, "nba", 801, t_value - timedelta(seconds=1), 2, "Boston Celtics", "Before, Spring", "Out")
    await _row(db, "nba", 801, t_value, 2, "Boston Celtics", "On, Spring", "Questionable")
    await _row(db, "nba", 801, t_value + timedelta(seconds=1), 2, "Boston Celtics", "After, Spring", "Doubtful")
    selected = await injury_rows_as_of(db, 801)
    assert [row["player_raw"] for row in selected] == ["On, Spring"]
    at_t = await injury_rows_as_of(db, 801, as_of=t_value)
    assert [row["player_raw"] for row in at_t] == ["On, Spring"]
    just_before = await injury_rows_as_of(db, 801, as_of=t_value - timedelta(seconds=1))
    assert [row["player_raw"] for row in just_before] == ["Before, Spring"]


@pytest.mark.asyncio
async def test_fall_back_night_selects_the_report_at_tip_minus_3h(
    db: asyncpg.Connection,
) -> None:
    """Tip 2024-11-03 06:30 UTC is 1:30 AM EST, the later of the two 1:30s.

    Three absolute hours earlier is 03:30 UTC, which is 11:30 PM EDT on November 2.
    """
    tip = datetime(2024, 11, 3, 6, 30, tzinfo=UTC)
    await _game(db, "nba", 802, date(2024, 11, 3), tip, 2024, 20, 2)
    t_value = await db.fetchval("SELECT game_as_of('nba', 802)")
    assert t_value == datetime(2024, 11, 3, 3, 30, tzinfo=UTC)
    titled = parse_pdf(
        _pdf("Injury Report: 11/02/24 11:30 PM", [_player_line(500, game_date="11/02/2024")])
    )
    assert titled.tag == "ok"
    assert titled.report_at == t_value
    await _row(db, "nba", 802, t_value, 2, "Boston Celtics", "On, Fall", "Out")
    await _row(db, "nba", 802, t_value + timedelta(seconds=1), 2, "Boston Celtics", "After, Fall", "Questionable")
    selected = await injury_rows_as_of(db, 802)
    assert [row["player_raw"] for row in selected] == ["On, Fall"]


def test_the_ambiguous_130_am_on_the_fallback_morning_is_the_first_offset() -> None:
    """11/03/24 01:30 AM is two UTC instants. The parser stores the earlier one, 05:30 UTC.

    06:30 UTC is the same wall clock after the clocks fall back, and this
    title does not produce it.
    """
    result = parse_pdf(
        _pdf("Injury Report: 11/03/24 01:30 AM", [_player_line(500, game_date="11/03/2024")])
    )
    assert result.tag == "ok"
    assert result.report_at_source == "title"
    assert result.report_at == datetime(2024, 11, 3, 5, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_the_latest_report_for_the_game_drops_a_team_that_it_omits(
    db: asyncpg.Connection,
) -> None:
    """Both clubs are in the older report. The report at T names only New York.

    The read returns that later report, so the older Boston row is not included.
    """
    tip = datetime(2024, 1, 16, 0, 30, tzinfo=UTC)
    await _game(db, "nba", 803, date(2024, 1, 15), tip, 2023, 20, 2)
    t_value = await db.fetchval("SELECT game_as_of('nba', 803)")
    await _row(db, "nba", 803, t_value - timedelta(hours=1), 2, "Boston Celtics", "Old, Bos", "Out")
    await _row(db, "nba", 803, t_value - timedelta(hours=1), 20, "New York Knicks", "Old, Nyk", "Out")
    await _row(db, "nba", 803, t_value, 20, "New York Knicks", "New, Nyk", "Questionable")
    rows = await injury_rows_as_of(db, 803, as_of=t_value)
    assert [row["player_raw"] for row in rows] == ["New, Nyk"]


@pytest.mark.asyncio
async def test_wnba_asof_does_not_return_the_nba_rows_for_the_same_game_id(
    db: asyncpg.Connection,
) -> None:
    """The same bdl_game_id exists in both leagues. Each read uses its own tip and its own rows."""
    nba_tip = datetime(2024, 7, 16, 0, 0, tzinfo=UTC)
    wnba_tip = datetime(2024, 7, 16, 5, 0, tzinfo=UTC)
    await _game(db, "nba", 901, date(2024, 7, 15), nba_tip, 2024, 20, 2)
    await _game(db, "wnba", 901, date(2024, 7, 15), wnba_tip, 2024, 2, 1)
    nba_t = await db.fetchval("SELECT game_as_of('nba', 901)")
    wnba_t = await db.fetchval("SELECT game_as_of('wnba', 901)")
    assert nba_t == nba_tip - timedelta(hours=3)
    assert wnba_t == wnba_tip - timedelta(hours=3)
    assert nba_t != wnba_t
    await _row(db, "nba", 901, nba_t, 2, "Boston Celtics", "Nba, One", "Out")
    await _row(db, "wnba", 901, wnba_t, 1, "Las Vegas Aces", "Wnba, One", "Questionable")
    nba_rows = await injury_rows_as_of(db, 901)
    wnba_rows = await injury_rows_as_of(db, 901, league="wnba")
    assert [row["player_raw"] for row in nba_rows] == ["Nba, One"]
    assert [row["player_raw"] for row in wnba_rows] == ["Wnba, One"]
    assert await db.fetchval(
        "SELECT league FROM nba_injury_report_rows WHERE player_raw = 'Wnba, One'"
    ) == "wnba"


@pytest.mark.asyncio
async def test_006_reverses_and_the_runner_applies_it_again(db: asyncpg.Connection) -> None:
    """006 has no down file. Reverse 007 first, then 006. upgrade() puts both back.

    The official source is allowed only while 006's check is in place.
    The six older sources stay allowed after the reverse.
    """
    moment = datetime(2026, 1, 15, 22, 30, tzinfo=UTC)
    await db.execute(
        """
        INSERT INTO source_refreshes (league, source, refreshed_at, complete, rows_seen)
        VALUES ('nba', 'injuries_nba_official', $1, true, 1)
        """,
        moment,
    )
    await db.execute("DELETE FROM source_refreshes WHERE source = 'injuries_nba_official'")
    # 007 replaced the read and the game index. Forget it before reversing
    # 006, or upgrade() would skip 007 and leave 006's old objects in place.
    await db.execute("DELETE FROM schema_migrations WHERE version = '007'")
    await db.execute("DROP FUNCTION injury_report_rows_asof(league_code, bigint, timestamptz)")
    await db.execute("DROP TABLE nba_injury_report_rows")
    await db.execute("ALTER TABLE source_refreshes DROP CONSTRAINT source_refreshes_source_check")
    await db.execute(
        """
        ALTER TABLE source_refreshes ADD CONSTRAINT source_refreshes_source_check
        CHECK (source IN (
            'injuries',
            'projected_lineups',
            'game_odds_live',
            'game_odds_closing',
            'props_live',
            'props_closing'
        ))
        """
    )
    await db.execute("DELETE FROM schema_migrations WHERE version = '006'")
    assert await db.fetchval("SELECT to_regclass('public.nba_injury_report_rows')") is None
    with pytest.raises(asyncpg.CheckViolationError):
        await db.execute(
            """
            INSERT INTO source_refreshes (league, source, refreshed_at, complete)
            VALUES ('nba', 'injuries_nba_official', $1, true)
            """,
            moment,
        )
    await db.execute(
        """
        INSERT INTO source_refreshes (league, source, refreshed_at, complete)
        VALUES ('nba', 'injuries', $1, true)
        """,
        moment,
    )
    applied = await upgrade(db)
    assert applied == ["006", "007"]
    assert await db.fetchval("SELECT to_regclass('public.nba_injury_report_rows') IS NOT NULL")
    await db.execute(
        """
        INSERT INTO source_refreshes (league, source, refreshed_at, complete)
        VALUES ('nba', 'injuries_nba_official', $1, true)
        """,
        moment + timedelta(minutes=1),
    )
