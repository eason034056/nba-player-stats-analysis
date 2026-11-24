"""SPO-151 name matching. Every person in this file is synthetic, except

the recorded ``/v1/players`` objects loaded from ``players_ids_v2.json``.
Those objects were already in the repo. This file does not read a PDF.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.migrations.runner import upgrade
from app.services.bdl_client import BdlError, iter_pages
from app.services.injury_report_ingest import ingest_store
from app.services.injury_report_match import catalog_from_database, match_report_rows
from app.services.injury_report_names import (
    CatalogPlayer,
    PlayerCatalog,
    catalog_from_player_pages,
    match_report_name,
    report_name_keys,
)
from app.services.injury_report_store import LocalInjuryReportStore
from tests.test_bdl_client import FIXTURE_DIR, ManualClock, _client, _json_response, _load
from tests.test_spo157_qa_review import TITLE, _b_line, _layout_b, _put

BOS = 2
LAC = 13
OTHER = 14
SEASON = 2026
_MINUTE = 1_800_000_000.0


def _player(
    player_id: int,
    first: str,
    last: str,
    *memberships: tuple[int, int],
    current_team_id: int | None = None,
    draft_year: int | None = None,
) -> CatalogPlayer:
    """One synthetic catalog player. ``memberships`` are ``(team_id, season)``."""
    return CatalogPlayer(
        bdl_player_id=player_id,
        first_name=first,
        last_name=last,
        position=None,
        memberships=frozenset(memberships),
        current_team_id=current_team_id,
        draft_year=draft_year,
    )


def _catalog(*players: CatalogPlayer) -> PlayerCatalog:
    return PlayerCatalog(players)


def test_fold_splits_on_the_last_comma_and_drops_suffixes() -> None:
    """``Udeh, Jr., Ernest`` keeps Ernest as the first name. ``III`` is dropped."""
    udeh = report_name_keys("Udeh, Jr., Ernest")
    assert udeh[0].first == "ernest"
    assert udeh[0].last == "udeh"
    jemison = report_name_keys("Jemison III, Trey")
    assert (jemison[0].first, jemison[0].last) == ("trey", "jemison")
    hyphen = report_name_keys("Smith-Jones, Alex")
    assert hyphen[0].full == "alex smith jones"


def test_known_aliases_resolve_on_that_team_and_season() -> None:
    """Nic, Nate, and Sasha are the short names. The catalog has the long names.

    Noah Claxton is also on the team, so a surname plus the letter N is
    not one person. The alias is what makes Nic an exact Nicolas.
    """
    catalog = _catalog(
        _player(501, "Nicolas", "Claxton", (BOS, SEASON)),
        _player(509, "Noah", "Claxton", (BOS, SEASON)),
        _player(502, "Jeenathan", "Williams", (BOS, SEASON)),
        _player(503, "Aleksandar", "Vezenkov", (BOS, SEASON)),
    )
    cases = (
        ("Claxton, Nic", 501),
        ("Williams, Nate", 502),
        ("Vezenkov, Sasha", 503),
    )
    for raw, player_id in cases:
        decision = match_report_name(
            raw, team_id=BOS, season=SEASON, catalog=catalog, g_league=False
        )
        assert decision.bdl_player_id == player_id, raw
        assert decision.match_method == "exact_team_season", raw
        assert decision.on_review_list is False


def test_jordan_miller_does_not_match_baba_miller() -> None:
    """Baba is the only Miller on the team this season. Jordan played another year.

    Same surname is not enough. The first letters differ, so the match is
    Jordan in the other season.
    """
    catalog = _catalog(
        _player(1, "Baba", "Miller", (LAC, SEASON), current_team_id=None),
        _player(2, "Jordan", "Miller", (OTHER, 2024), current_team_id=None),
    )
    decision = match_report_name(
        "Miller, Jordan",
        team_id=LAC,
        season=SEASON,
        catalog=catalog,
        g_league=False,
    )
    assert decision.bdl_player_id == 2
    assert decision.match_method == "exact_other_season"
    assert decision.on_review_list is False


def test_a_rookie_with_no_stat_row_uses_the_payload_team() -> None:
    """No box score yet. The players payload team counts for this season only."""
    catalog = _catalog(
        _player(99, "Riley", "Rook", current_team_id=BOS, draft_year=SEASON),
    )
    this_year = match_report_name(
        "Rook, Riley", team_id=BOS, season=SEASON, catalog=catalog, g_league=False
    )
    assert this_year.bdl_player_id == 99
    assert this_year.match_method == "exact_team_season"
    earlier = match_report_name(
        "Rook, Riley", team_id=BOS, season=SEASON - 1, catalog=catalog, g_league=False
    )
    assert earlier.bdl_player_id is None
    assert earlier.match_method == "unmatched"


def test_unmatched_non_g_league_is_on_the_review_list() -> None:
    """A miss stays unmatched. It is not given another player's id."""
    catalog = _catalog(_player(501, "Nicolas", "Claxton", (BOS, SEASON)))
    decision = match_report_name(
        "Nobody, Special",
        team_id=BOS,
        season=SEASON,
        catalog=catalog,
        g_league=False,
    )
    assert decision.bdl_player_id is None
    assert decision.match_method == "unmatched"
    assert decision.on_review_list is True
    g_league = match_report_name(
        "Nobody, Special",
        team_id=BOS,
        season=SEASON,
        catalog=catalog,
        g_league=True,
    )
    assert g_league.bdl_player_id is None
    assert g_league.match_method == "unmatched_g_league"
    assert g_league.on_review_list is False


def test_recorded_players_page_keeps_team_and_draft_year() -> None:
    """The player object is the one already recorded for ``GET /v1/players``."""
    payload = json.loads((FIXTURE_DIR / "players_ids_v2.json").read_text())
    catalog = catalog_from_player_pages([payload["response"]])
    shai = next(player for player in catalog.players if player.bdl_player_id == 175)
    assert shai.first_name == "Shai"
    assert shai.last_name == "Gilgeous-Alexander"
    assert shai.current_team_id == 21
    assert shai.draft_year == 2018
    decision = match_report_name(
        "Gilgeous-Alexander, Shai",
        team_id=21,
        season=2025,
        catalog=catalog,
        g_league=False,
    )
    assert decision.bdl_player_id == 175
    assert decision.match_method == "exact_team_season"


@pytest.mark.asyncio
async def test_list_players_page_sends_no_player_ids() -> None:
    """The unfiltered page is a different method. ``list_players`` still requires ids."""
    capture = _load("players_ids_v2.json")
    seen: list[httpx.Request] = []
    clock = ManualClock(_MINUTE)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(capture)

    client = _client(handler, clock)
    try:
        with pytest.raises(BdlError):
            await client.list_players(player_ids=[])
        body = await client.list_players_page(cursor=25)
    finally:
        await client.aclose()

    assert seen[0].url.path == "/v1/players"
    assert seen[0].url.params.get_list("player_ids[]") == []
    assert seen[0].url.params.get_list("ids[]") == []
    assert seen[0].url.params.get_list("per_page") == ["100"]
    assert seen[0].url.params.get_list("cursor") == ["25"]
    assert body == capture["response"]
    assert len(seen) == 1
    assert "next_cursor" not in capture["response"]["meta"]

    seen.clear()
    walker = _client(handler, clock)
    try:
        pages = [page async for page in iter_pages(walker.list_players_page)]
    finally:
        await walker.aclose()
    assert pages == [capture["response"]]
    assert len(seen) == 1
    assert seen[0].url.params.get_list("player_ids[]") == []
    assert seen[0].url.params.get_list("cursor") == []


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


@pytest.mark.asyncio
async def test_team_notes_without_players_do_not_delete_named_rows(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """A file that only says NOT YET SUBMITTED is stored and does not wipe Doe."""
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    store = LocalInjuryReportStore(tmp_path)
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(player="Doe, Alex", status="Out", reason="Rest")]),
        moment,
    )
    assert (await ingest_store(db, store))[0].rows_written == 1
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(TITLE, [_b_line(reason="NOT YET SUBMITTED")]),
        moment,
    )
    second = await ingest_store(db, store)
    assert second[0].tag == "stored"
    assert second[0].rows_written == 1
    names = await db.fetch(
        """
        SELECT player_raw, not_yet_submitted
        FROM nba_injury_report_rows
        ORDER BY player_raw
        """
    )
    assert [(row["player_raw"], row["not_yet_submitted"]) for row in names] == [
        ("", True),
        ("Doe, Alex", False),
    ]


@pytest.mark.asyncio
async def test_ingest_writes_the_alias_and_the_review_list(
    db: asyncpg.Connection, tmp_path: Path
) -> None:
    """Nic is stored under Nicolas's id. Special Nobody is unmatched and listed.

    The players row is inserted before the injury row, because of the
    foreign key. A G League miss stays in the table and stays off the list.
    """
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    store = LocalInjuryReportStore(tmp_path)
    _put(
        store,
        "Injury-Report_2024-01-15_05PM.pdf",
        _layout_b(
            TITLE,
            [
                _b_line(player="Claxton, Nic", status="Out", reason="Rest"),
                _b_line(
                    player="Nobody, Special",
                    team="New York Knicks",
                    status="Out",
                    reason="Rest",
                ),
                _b_line(
                    player="Two, Way",
                    team="New York Knicks",
                    status="Out",
                    reason="G League - Two-Way",
                ),
            ],
        ),
        moment,
    )
    catalog = _catalog(
        _player(501, "Nicolas", "Claxton", (BOS, 2023), current_team_id=BOS),
    )
    review_path = tmp_path / "unmatched.jsonl"
    outcome = await ingest_store(
        db, store, catalog=catalog, review_path=review_path
    )
    assert outcome[0].tag == "stored"
    rows = await db.fetch(
        """
        SELECT player_raw, bdl_player_id, match_method
        FROM nba_injury_report_rows
        ORDER BY player_raw
        """
    )
    by_name = {row["player_raw"]: row for row in rows}
    assert by_name["Claxton, Nic"]["bdl_player_id"] == 501
    assert by_name["Claxton, Nic"]["match_method"] == "exact_team_season"
    assert by_name["Nobody, Special"]["bdl_player_id"] is None
    assert by_name["Nobody, Special"]["match_method"] == "unmatched"
    assert by_name["Two, Way"]["bdl_player_id"] is None
    assert by_name["Two, Way"]["match_method"] == "unmatched_g_league"
    stored_player = await db.fetchrow(
        "SELECT first_name, last_name FROM players WHERE bdl_player_id = 501"
    )
    assert stored_player["first_name"] == "Nicolas"
    assert stored_player["last_name"] == "Claxton"
    listed = [json.loads(line) for line in review_path.read_text().splitlines()]
    assert [item["player_raw"] for item in listed] == ["Nobody, Special"]
    assert "Two, Way" not in review_path.read_text()


@pytest.mark.asyncio
async def test_a_held_match_method_is_not_replaced(
    db: asyncpg.Connection,
) -> None:
    """The match update only fills a null method. ``held`` stays held."""
    await db.execute(
        """
        INSERT INTO players (league, bdl_player_id, display_name)
        VALUES ('nba', 4242, 'Alex Doe')
        """
    )
    moment = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    await db.execute(
        """
        INSERT INTO nba_injury_report_rows (
            league, report_at, game_date, matchup, team_name,
            bdl_game_id, bdl_team_id, player_raw, bdl_player_id, match_method,
            status, not_yet_submitted, all_players_available
        ) VALUES (
            'nba', $1, '2024-01-15', 'BOS@NYK', 'Boston Celtics',
            701, 2, 'Doe, Alex', 4242, 'held',
            'Out', false, false
        )
        """,
        moment,
    )
    catalog = _catalog(_player(501, "Nicolas", "Claxton", (BOS, 2023)))
    review = await match_report_rows(
        db, league="nba", report_at=moment, catalog=catalog, review_path=None
    )
    assert review == []
    kept = await db.fetchrow(
        "SELECT bdl_player_id, match_method FROM nba_injury_report_rows"
    )
    assert kept["bdl_player_id"] == 4242
    assert kept["match_method"] == "held"


@pytest.mark.asyncio
async def test_catalog_from_database_has_no_invented_team(
    db: asyncpg.Connection,
) -> None:
    """A stored name has stat memberships only. This table has no current team."""
    await db.execute(
        """
        INSERT INTO players (league, bdl_player_id, first_name, last_name, display_name)
        VALUES ('nba', 501, 'Nicolas', 'Claxton', 'Nicolas Claxton')
        """
    )
    catalog = await catalog_from_database(db, "nba")
    assert len(catalog.players) == 1
    player = catalog.players[0]
    assert player.bdl_player_id == 501
    assert player.first_name == "Nicolas"
    assert player.memberships == frozenset()
    assert player.current_team_id is None
