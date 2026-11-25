"""QA checks for the empty-parse guard and the name matcher.

Every PDF and every catalog person here is synthetic. Nothing in this
file reads a stored official PDF or types a BALLDONTLIE response.
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
from app.services.injury_report_match import match_report_rows
from app.services.injury_report_names import match_report_name
from app.services.injury_report_store import LocalInjuryReportStore
from tests.test_spo151_player_ids import BOS, LAC, OTHER, SEASON, _catalog, _player
from tests.test_spo157_qa_review import TITLE, _b_line, _layout_b, _put

_MOMENT = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)


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


def _store_doe(store: LocalInjuryReportStore) -> None:
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(player="Doe, Alex", status="Out", reason="Rest")]),
        _MOMENT,
    )


async def _refresh(db: asyncpg.Connection) -> asyncpg.Record:
    rows = await db.fetch(
        """
        SELECT complete, rows_seen, rows_written, error
        FROM source_refreshes
        WHERE source = 'injuries_nba_official'
        """
    )
    assert len(rows) == 1
    return rows[0]


@pytest.mark.asyncio
async def test_empty_parse_keeps_counts_and_other_minutes(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """A title and a header with no player lines fails closed.

    The prior complete refresh keeps its counts and gains the error.
    Doe stays. A later minute and the other league stay. The ingest
    did not receive a catalog, so the match columns stay null.
    """
    later = _MOMENT + timedelta(hours=1)
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
        _MOMENT,
        later,
    )
    store = LocalInjuryReportStore(tmp_path)
    _store_doe(store)
    first = await ingest_store(db, store)
    assert first[0].tag == "stored"
    before = await _refresh(db)
    assert before["complete"] is True
    assert before["error"] is None
    doe = await db.fetchrow(
        """
        SELECT bdl_player_id, match_method
        FROM nba_injury_report_rows
        WHERE player_raw = 'Doe, Alex'
        """
    )
    assert doe["bdl_player_id"] is None
    assert doe["match_method"] is None

    _put(store, "Injury-Report_2024-01-15_05PM.pdf", _layout_b(TITLE, []), _MOMENT)
    second = await ingest_store(db, store)
    assert second[0].tag == "failed"
    assert second[0].error == "zero player lines"
    assert second[0].rows_written == 0
    after = await _refresh(db)
    assert after["complete"] is True
    assert after["rows_seen"] == before["rows_seen"]
    assert after["rows_written"] == before["rows_written"]
    assert after["error"] == "zero player lines"
    names = await db.fetch(
        """
        SELECT league, player_raw, bdl_player_id, match_method
        FROM nba_injury_report_rows
        ORDER BY league, player_raw
        """
    )
    assert [(row["league"], row["player_raw"]) for row in names] == [
        ("nba", "Doe, Alex"),
        ("nba", "Later, Lou"),
        ("wnba", "Other, League"),
    ]
    assert all(row["match_method"] is None for row in names)
    assert [row["player_raw"] for row in await injury_rows_as_of(db, 701)] == ["Doe, Alex"]


@pytest.mark.asyncio
async def test_dry_run_of_an_empty_file_writes_nothing(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """dry_run of a header with no players is failed and does not record it."""
    store = LocalInjuryReportStore(tmp_path)
    _store_doe(store)
    assert (await ingest_store(db, store))[0].tag == "stored"
    before = await _refresh(db)
    _put(store, "Injury-Report_2024-01-15_05PM.pdf", _layout_b(TITLE, []), _MOMENT)
    dry = await ingest_store(db, store, dry_run=True)
    assert dry[0].tag == "failed"
    assert dry[0].error == "zero player lines"
    assert dry[0].rows_written == 0
    after = await _refresh(db)
    assert after["complete"] == before["complete"]
    assert after["rows_seen"] == before["rows_seen"]
    assert after["rows_written"] == before["rows_written"]
    assert after["error"] is None
    assert await db.fetchval("SELECT player_raw FROM nba_injury_report_rows") == "Doe, Alex"


@pytest.mark.asyncio
async def test_a_dash_player_line_is_a_zero_player_failure(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """A player cell of '-' is dropped. The file then has no player lines."""
    store = LocalInjuryReportStore(tmp_path)
    _store_doe(store)
    assert (await ingest_store(db, store))[0].tag == "stored"
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(player="-", status="Out", reason="Rest")]),
        _MOMENT,
    )
    second = await ingest_store(db, store)
    assert second[0].tag == "failed"
    assert second[0].error == "zero player lines"
    assert await db.fetchval("SELECT player_raw FROM nba_injury_report_rows") == "Doe, Alex"


@pytest.mark.asyncio
async def test_all_players_available_does_not_delete_named_rows(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """A file that only says ALL PLAYERS AVAILABLE is stored and keeps Doe."""
    store = LocalInjuryReportStore(tmp_path)
    _store_doe(store)
    assert (await ingest_store(db, store))[0].rows_written == 1
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(reason="ALL PLAYERS AVAILABLE")]),
        _MOMENT,
    )
    second = await ingest_store(db, store)
    assert second[0].tag == "stored"
    assert second[0].rows_written == 1
    names = await db.fetch(
        """
        SELECT player_raw, all_players_available, not_yet_submitted
        FROM nba_injury_report_rows
        ORDER BY player_raw
        """
    )
    assert [
        (row["player_raw"], row["all_players_available"], row["not_yet_submitted"])
        for row in names
    ] == [
        ("", True, False),
        ("Doe, Alex", False, False),
    ]


@pytest.mark.parametrize(
    ("label", "raw", "players"),
    [
        (
            "exact team and season",
            "Doe, Alex",
            (
                _player(7, "Alex", "Doe", (BOS, SEASON)),
                _player(8, "Alex", "Doe", (BOS, SEASON)),
            ),
        ),
        (
            "exact season",
            "Doe, Alex",
            (
                _player(7, "Alex", "Doe", (LAC, SEASON)),
                _player(8, "Alex", "Doe", (OTHER, SEASON)),
            ),
        ),
        (
            "fuzzy team",
            "Smith, John",
            (
                _player(7, "Jon", "Smith", (BOS, SEASON)),
                _player(8, "Johnn", "Smith", (BOS, SEASON)),
            ),
        ),
        (
            "surname and initial",
            "Miller, Jordan",
            (
                _player(7, "Julius", "Miller", (BOS, SEASON)),
                _player(8, "Jabari", "Miller", (BOS, SEASON)),
            ),
        ),
        (
            "other season",
            "Doe, Alex",
            (
                _player(7, "Alex", "Doe", (BOS, 2020)),
                _player(8, "Alex", "Doe", (LAC, 2019)),
            ),
        ),
        # Id 7 is also on the team in 2020. Two players at step 1 must
        # stay unmatched, even though step 5 would have picked id 7.
        (
            "exact team then a later season",
            "Doe, Alex",
            (
                _player(7, "Alex", "Doe", (BOS, SEASON), (BOS, 2020)),
                _player(8, "Alex", "Doe", (BOS, SEASON)),
            ),
        ),
    ],
)
def test_two_candidates_at_one_step_stay_unmatched(label: str, raw: str, players: tuple) -> None:
    """A step with two players is a miss. The first id in the catalog is not used."""
    decision = match_report_name(
        raw,
        team_id=BOS,
        season=SEASON,
        catalog=_catalog(*players),
        g_league=False,
    )
    assert decision.bdl_player_id is None, label
    assert decision.match_method == "unmatched", label
    assert decision.on_review_list is True, label


def test_one_candidate_at_the_later_steps_still_matches() -> None:
    """One player above the fuzzy floor, or one surname initial, is that player."""
    fuzzy = match_report_name(
        "Smith, John",
        team_id=BOS,
        season=SEASON,
        catalog=_catalog(_player(7, "Jon", "Smith", (BOS, SEASON))),
        g_league=False,
    )
    assert fuzzy.bdl_player_id == 7
    assert fuzzy.match_method == "fuzzy_team"
    surname = match_report_name(
        "Miller, Jordan",
        team_id=BOS,
        season=SEASON,
        catalog=_catalog(_player(8, "Julius", "Miller", (BOS, SEASON))),
        g_league=False,
    )
    assert surname.bdl_player_id == 8
    assert surname.match_method == "surname_initial"
    other_team = match_report_name(
        "Doe, Alex",
        team_id=BOS,
        season=SEASON,
        catalog=_catalog(_player(9, "Alex", "Doe", (LAC, SEASON))),
        g_league=False,
    )
    assert other_team.bdl_player_id == 9
    assert other_team.match_method == "exact_season"


@pytest.mark.asyncio
async def test_g_league_category_stays_off_the_review_list(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """The category column alone marks a G League miss. The id stays null.

    An empty review list does not create the file, even when a path is set.
    """
    await db.execute(
        """
        INSERT INTO nba_injury_report_rows (
            league, report_at, game_date, matchup, team_name,
            bdl_game_id, bdl_team_id, player_raw, status, reason, category,
            not_yet_submitted, all_players_available
        ) VALUES (
            'nba', $1, '2024-01-15', 'BOS@NYK', 'Boston Celtics',
            701, 2, 'Way, Two', 'Out', 'Rest', 'G League - Two-Way',
            false, false
        )
        """,
        _MOMENT,
    )
    review_path = tmp_path / "injury-report-unmatched" / "review.jsonl"
    review = await match_report_rows(
        db,
        league="nba",
        report_at=_MOMENT,
        catalog=_catalog(_player(501, "Nicolas", "Claxton", (BOS, 2023))),
        review_path=review_path,
    )
    assert review == []
    assert review_path.exists() is False
    row = await db.fetchrow(
        "SELECT bdl_player_id, match_method FROM nba_injury_report_rows"
    )
    assert row["bdl_player_id"] is None
    assert row["match_method"] == "unmatched_g_league"
