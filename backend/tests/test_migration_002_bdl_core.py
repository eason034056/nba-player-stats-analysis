"""
test_migration_002_bdl_core.py - the SPO-138 core tables in a real PostgreSQL.

Each test creates a scratch database, applies ``app/migrations/002_bdl_core.sql``
inside one transaction, and drops the database afterwards. The server is
``DATABASE_URL`` (the postgres:16 service in CI). The tests skip when no
server answers, like ``test_spo132c_migrate_verify.py``.

The upserts below use the conflict targets the backfill writer will use, so a
key that cannot serve ``ON CONFLICT`` fails here first.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import pytest_asyncio

from app.services.game_log_hygiene import CANONICAL_GAME_TYPES

MIGRATION = Path(__file__).resolve().parents[1] / "app" / "migrations" / "002_bdl_core.sql"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"

CORE_TABLES = {
    "books", "seasons", "teams", "players", "games", "player_game_stats",
    "injury_snapshots", "game_lineups", "projected_lineups", "projected_lineup_players", "prop_markets",
    "game_odds_snapshots", "player_prop_snapshots", "bdl_backfill_checkpoints",
}
CORE_VIEWS = {"player_game_log"}

# The 130d allow-list, as BALLDONTLIE spells each vendor.
ALLOWED_BOOKS = {
    "draftkings", "fanduel", "betmgm", "caesars", "betrivers",
    "fanatics", "betparx", "ballybet", "betway", "rebet",
}

TIP_DAY = date(2026, 1, 15)


def _at(hour: int, minute: int) -> datetime:
    return datetime(2026, 1, 15, hour, minute, tzinfo=UTC)


def _recorded(name: str) -> list[dict[str, Any]]:
    capture = json.loads((FIXTURE_DIR / name).read_text())
    return capture.get("response", capture)["data"]


@pytest.fixture
def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    """An empty scratch database (``conftest.py``), dropped after the test."""
    return scratch_conn


async def _apply(conn: asyncpg.Connection) -> None:
    async with conn.transaction():
        await conn.execute(MIGRATION.read_text(encoding="utf-8"))


@pytest_asyncio.fixture
async def migrated(db: asyncpg.Connection) -> asyncpg.Connection:
    """Scratch database with 002 applied and one game to hang facts on."""
    await _apply(db)
    await db.execute(
        """
        INSERT INTO seasons (league, season_start_year, label) VALUES ('nba', 2025, '2025-26');
        INSERT INTO teams (league, bdl_team_id, abbreviation) VALUES ('nba', 14, 'LAL'), ('nba', 10, 'GSW');
        INSERT INTO players (league, bdl_player_id, display_name)
        VALUES ('nba', 237, 'LeBron James'), ('nba', 115, 'Stephen Curry');
        INSERT INTO games (league, bdl_game_id, season, date, season_type, home_team_id, visitor_team_id)
        VALUES ('nba', 123, 2025, '2026-01-15', 'regular_season', 14, 10);
        """
    )
    return db


async def _public_tables(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    return {row["table_name"] for row in rows}


# ---------------------------------------------------------------------------
# Applying the file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creates_the_core_tables(db: asyncpg.Connection) -> None:
    await _apply(db)
    assert await _public_tables(db) == CORE_TABLES | CORE_VIEWS


@pytest.mark.asyncio
async def test_failure_after_the_file_leaves_no_table_behind(db: asyncpg.Connection) -> None:
    """The file has no COMMIT of its own, so the runner's transaction decides all or nothing."""
    with pytest.raises(asyncpg.DivisionByZeroError):
        async with db.transaction():
            await db.execute(MIGRATION.read_text(encoding="utf-8"))
            await db.execute("SELECT 1 / 0")
    assert await _public_tables(db) == set()
    assert await db.fetchval("SELECT count(*) FROM pg_type WHERE typname = 'league_code'") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("league", "error"),
    [(None, asyncpg.NotNullViolationError), ("NBA", asyncpg.CheckViolationError)],
    ids=["league-left-out", "league-misspelled"],
)
async def test_a_row_must_name_a_known_league(
    migrated: asyncpg.Connection, league: str | None, error: type[Exception]
) -> None:
    """BALLDONTLIE's NBA and WNBA ids overlap, so a row never falls back to NBA."""
    with pytest.raises(error):
        await migrated.execute(
            "INSERT INTO players (league, bdl_player_id, display_name) VALUES ($1, 999, 'Someone')",
            league,
        )


async def _insert_game_of_type(conn: asyncpg.Connection, game_type: str) -> None:
    await conn.execute(
        "INSERT INTO games (league, bdl_game_id, season, date, season_type, home_team_id, visitor_team_id)"
        " VALUES ('nba', 456, 2025, '2026-04-15', $1, 14, 10)",
        game_type,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("game_type", sorted(CANONICAL_GAME_TYPES))
async def test_games_store_each_product_game_type(migrated: asyncpg.Connection, game_type: str) -> None:
    """The column holds the same tokens the history readers already filter on."""
    await _insert_game_of_type(migrated, game_type)
    assert await migrated.fetchval("SELECT season_type FROM games WHERE bdl_game_id = 456") == game_type


@pytest.mark.asyncio
@pytest.mark.parametrize("game_type", ["regular", "playin", "ist", "preseason"])
async def test_games_refuse_balldontlie_season_type_names(migrated: asyncpg.Connection, game_type: str) -> None:
    """The writer translates BALLDONTLIE's names. An untranslated one, or preseason, fails the insert."""
    with pytest.raises(asyncpg.CheckViolationError):
        await _insert_game_of_type(migrated, game_type)


@pytest.mark.asyncio
async def test_unique_key_columns_are_not_null_except_tick_times(db: asyncpg.Connection) -> None:
    """A nullable key column cannot match ON CONFLICT (NULL = NULL is unknown).

    The only exception is ``snapshot_at`` in the live/closing keys: it is
    nullable for opening rows, and a CHECK requires it on every live or
    closing row, which are the only rows those partial indexes cover.
    """
    await _apply(db)
    rows = await db.fetch(
        """
        SELECT i.indexrelid::regclass::text AS index_name, a.attname
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
        WHERE i.indisunique AND NOT a.attnotnull
        """
    )
    assert {(row["index_name"], row["attname"]) for row in rows} == {
        ("game_odds_snapshots_tick_key", "snapshot_at"),
        ("player_prop_snapshots_tick_key", "snapshot_at"),
    }


# ---------------------------------------------------------------------------
# Seed rows match what BALLDONTLIE sends
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prop_markets_seed_is_the_full_game_bdl_prop_types(db: asyncpg.Connection) -> None:
    """The 12 seeded types are the recorded ones minus first-quarter and first-3-minute props."""
    await _apply(db)
    recorded = {row["prop_type"] for row in _recorded("props_live_21718080_OKC@POR_pregame.json")}
    full_game = {t for t in recorded if not t.endswith(("_1q", "_first3min"))}
    seeded = {row["bdl_prop_type"] for row in await db.fetch("SELECT bdl_prop_type FROM prop_markets")}
    assert seeded == full_game
    assert len(seeded) == 12


@pytest.mark.asyncio
async def test_prop_markets_settle_from_real_stat_columns(db: asyncpg.Connection) -> None:
    await _apply(db)
    stat_columns = {
        row["column_name"]
        for row in await db.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'player_game_stats'"
        )
    }
    for row in await db.fetch("SELECT market, stat_columns FROM prop_markets"):
        assert set(row["stat_columns"]) <= stat_columns, row["market"]


@pytest.mark.asyncio
async def test_books_seed_is_the_allow_list_spelled_as_bdl_vendors(db: asyncpg.Connection) -> None:
    """Every seeded key appears as a vendor in the recorded odds; BetParx and Bally Bet share a vote."""
    await _apply(db)
    recorded_vendors = {row["vendor"] for row in _recorded("odds_2026-11-11.json")}
    books = {row["book_key"]: row["source_group"] for row in await db.fetch("SELECT * FROM books")}
    assert set(books) == ALLOWED_BOOKS
    assert ALLOWED_BOOKS <= recorded_vendors
    assert {key for key, group in books.items() if group != key} == {"betparx", "ballybet"}
    assert {books["betparx"], books["ballybet"]} == {"parx_bally"}


# ---------------------------------------------------------------------------
# Odds keys: one opening row per market, one live/closing row per time
# ---------------------------------------------------------------------------

OPENING_PROP_KEY = (
    "(league, bdl_game_id, bdl_player_id, book_key, market) WHERE snapshot_kind = 'opening'"
)
TICK_PROP_KEY = (
    "(league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, snapshot_at) "
    "WHERE snapshot_kind IN ('live', 'closing')"
)

OPENING_PROP_UPSERT = f"""
INSERT INTO player_prop_snapshots
    (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type, line,
     over_odds, under_odds, snapshot_at)
VALUES ('nba', 'opening', 123, 237, 'draftkings', 'player_points', 'over_under', $1, -110, -110, $2)
ON CONFLICT {OPENING_PROP_KEY}
DO UPDATE SET line = EXCLUDED.line, snapshot_at = EXCLUDED.snapshot_at
"""

TICK_PROP_UPSERT = f"""
INSERT INTO player_prop_snapshots
    (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type, line,
     over_odds, under_odds, snapshot_at)
VALUES ('nba', $1, 123, 237, 'draftkings', 'player_points', 'over_under', $2, -110, -110, $3)
ON CONFLICT {TICK_PROP_KEY}
DO UPDATE SET line = EXCLUDED.line, over_odds = EXCLUDED.over_odds, under_odds = EXCLUDED.under_odds
"""


@pytest.mark.asyncio
async def test_opening_prop_replay_updates_the_same_row(migrated: asyncpg.Connection) -> None:
    """A retry whose opened_at moved, or went missing, still finds the first row."""
    await migrated.execute(OPENING_PROP_UPSERT, Decimal("25.5"), _at(20, 30))
    await migrated.execute(OPENING_PROP_UPSERT, Decimal("26.5"), _at(20, 31))
    await migrated.execute(OPENING_PROP_UPSERT, Decimal("26.5"), None)
    rows = await migrated.fetch("SELECT line FROM player_prop_snapshots")
    assert [row["line"] for row in rows] == [Decimal("26.5")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("market_type", "over_odds", "under_odds", "milestone_odds"),
    [
        ("over_under", -110, None, None),
        ("over_under", -110, -110, 150),
        ("milestone", None, None, None),
        ("milestone", -110, None, 150),
    ],
    ids=["over-under-missing-a-side", "over-under-with-milestone-odds",
         "milestone-without-odds", "milestone-with-over-odds"],
)
async def test_odds_that_do_not_fit_the_market_type_are_rejected(
    migrated: asyncpg.Connection,
    market_type: str,
    over_odds: int | None,
    under_odds: int | None,
    milestone_odds: int | None,
) -> None:
    """Every recorded over/under row has both prices, and every milestone row has only ``odds``."""
    with pytest.raises(asyncpg.CheckViolationError):
        await migrated.execute(
            """
            INSERT INTO player_prop_snapshots
                (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type, line,
                 over_odds, under_odds, milestone_odds, snapshot_at)
            VALUES ('nba', 'live', 123, 237, 'draftkings', 'player_points', $1, 25.5, $2, $3, $4, now())
            """,
            market_type, over_odds, under_odds, milestone_odds,
        )


@pytest.mark.asyncio
async def test_live_prop_ticks_keep_one_row_per_time(migrated: asyncpg.Connection) -> None:
    await migrated.execute(TICK_PROP_UPSERT, "live", Decimal("25.5"), _at(16, 5))
    await migrated.execute(TICK_PROP_UPSERT, "live", Decimal("26.5"), _at(22, 5))
    await migrated.execute(TICK_PROP_UPSERT, "live", Decimal("26.5"), _at(22, 5))
    await migrated.execute(TICK_PROP_UPSERT, "closing", Decimal("27.0"), _at(23, 35))
    rows = await migrated.fetch(
        "SELECT snapshot_kind, line FROM player_prop_snapshots ORDER BY snapshot_at"
    )
    assert [(row["snapshot_kind"], row["line"]) for row in rows] == [
        ("live", Decimal("25.5")), ("live", Decimal("26.5")), ("closing", Decimal("27.0")),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["live", "closing"])
async def test_tick_without_a_time_is_rejected(migrated: asyncpg.Connection, kind: str) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await migrated.execute(TICK_PROP_UPSERT, kind, Decimal("25.5"), None)


@pytest.mark.asyncio
async def test_opening_game_odds_replay_updates_the_same_row(migrated: asyncpg.Connection) -> None:
    upsert = """
    INSERT INTO game_odds_snapshots
        (league, snapshot_kind, bdl_game_id, book_key, spread_home_value, spread_home_odds, snapshot_at)
    VALUES ('nba', 'opening', 123, 'fanduel', $1, -110, $2)
    ON CONFLICT (league, bdl_game_id, book_key) WHERE snapshot_kind = 'opening'
    DO UPDATE SET spread_home_value = EXCLUDED.spread_home_value, snapshot_at = EXCLUDED.snapshot_at
    """
    await migrated.execute(upsert, Decimal("-5.5"), _at(20, 30))
    await migrated.execute(upsert, Decimal("-6.5"), _at(20, 31))
    rows = await migrated.fetch("SELECT spread_home_value FROM game_odds_snapshots")
    assert [row["spread_home_value"] for row in rows] == [Decimal("-6.5")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("column", "value"),
    [("market", "player_frees_made"), ("book_key", "kalshi")],
)
async def test_prop_outside_the_reference_tables_is_rejected(
    migrated: asyncpg.Connection, column: str, value: str
) -> None:
    """FTM has no BDL prop type and Kalshi is not on the allow-list; the writer filters both first."""
    row = {"book_key": "draftkings", "market": "player_points", column: value}
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await migrated.execute(
            """
            INSERT INTO player_prop_snapshots
                (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type, line,
                 over_odds, under_odds, snapshot_at)
            VALUES ('nba', 'live', 123, 237, $1, $2, 'over_under', 25.5, -110, -110, now())
            """,
            row["book_key"], row["market"],
        )


# ---------------------------------------------------------------------------
# Projected lineups: every version is kept and read as of a time
# ---------------------------------------------------------------------------

LINEUP_AS_OF = """
SELECT DISTINCT ON (bdl_team_id) bdl_team_id, updated_at
FROM projected_lineups
WHERE league = 'nba' AND bdl_game_id = $1 AND first_seen_at <= $2
ORDER BY bdl_team_id, updated_at DESC
"""


async def _write_projected_lineup(
    conn: asyncpg.Connection, lineup: dict[str, Any], updated_at: datetime, seen_at: datetime
) -> None:
    """Write one version the way a poll will. A replay keeps the time the version was first seen."""
    version = (lineup["game_id"], lineup["team_id"], updated_at)
    await conn.execute(
        """
        INSERT INTO projected_lineups (league, bdl_game_id, bdl_team_id, updated_at, first_seen_at, status)
        VALUES ('nba', $1, $2, $3, $4, $5)
        ON CONFLICT (league, bdl_game_id, bdl_team_id, updated_at) DO NOTHING
        """,
        *version, seen_at, lineup["status"],
    )
    await conn.executemany(
        """
        INSERT INTO projected_lineup_players
            (league, bdl_game_id, bdl_team_id, updated_at, bdl_player_id, position)
        VALUES ('nba', $1, $2, $3, $4, $5)
        ON CONFLICT (league, bdl_game_id, bdl_team_id, updated_at, bdl_player_id) DO NOTHING
        """,
        [(*version, slot["player"]["id"], slot["position"]) for slot in lineup["lineup"]],
    )


@pytest_asyncio.fixture
async def recorded_lineups(migrated: asyncpg.Connection) -> list[dict[str, Any]]:
    """The recorded OKC at POR projected lineups, with their game, teams, and players in place."""
    lineups = _recorded("projected_lineups_21718080.json")
    await migrated.execute(
        """
        INSERT INTO seasons (league, season_start_year, label) VALUES ('nba', 2026, '2026-27');
        INSERT INTO teams (league, bdl_team_id, abbreviation) VALUES ('nba', 25, 'POR'), ('nba', 21, 'OKC');
        INSERT INTO games (league, bdl_game_id, season, date, season_type, home_team_id, visitor_team_id)
        VALUES ('nba', 21718080, 2026, '2026-11-10', 'regular_season', 25, 21);
        """
    )
    players = [slot["player"] for lineup in lineups for slot in lineup["lineup"]]
    await migrated.executemany(
        "INSERT INTO players (league, bdl_player_id, first_name, last_name, display_name)"
        " VALUES ('nba', $1, $2, $3, $4)",
        [(p["id"], p["first_name"], p["last_name"], f"{p['first_name']} {p['last_name']}") for p in players],
    )
    return lineups


@pytest.mark.asyncio
async def test_recorded_projected_lineups_are_one_row_per_player(
    migrated: asyncpg.Connection, recorded_lineups: list[dict[str, Any]]
) -> None:
    for lineup in recorded_lineups:
        updated_at = datetime.fromisoformat(lineup["updated_at"])
        await _write_projected_lineup(migrated, lineup, updated_at, seen_at=updated_at)
    rows = await migrated.fetch("SELECT bdl_team_id, position FROM projected_lineup_players")
    assert len(rows) == 10
    assert {(row["bdl_team_id"], row["position"]) for row in rows} == {
        (team, position) for team in (21, 25) for position in ("PG", "SG", "SF", "PF", "C")
    }


@pytest.mark.asyncio
async def test_projected_lineup_must_say_when_we_first_saw_it(
    migrated: asyncpg.Connection, recorded_lineups: list[dict[str, Any]]
) -> None:
    with pytest.raises(asyncpg.NotNullViolationError):
        await migrated.execute(
            "INSERT INTO projected_lineups (league, bdl_game_id, bdl_team_id, updated_at, status)"
            " VALUES ('nba', 21718080, 25, $1, 'confirmed')",
            datetime.fromisoformat(recorded_lineups[0]["updated_at"]),
        )


@pytest.mark.asyncio
async def test_projected_lineup_read_as_of_a_time_sees_only_versions_we_had_seen(
    migrated: asyncpg.Connection, recorded_lineups: list[dict[str, Any]]
) -> None:
    """Portland's confirmed lineup was published 10 minutes before our next poll stored it."""
    portland = next(lineup for lineup in recorded_lineups if lineup["team_id"] == 25)
    confirmed_at = datetime.fromisoformat(portland["updated_at"])
    earlier_at = confirmed_at - timedelta(hours=2)
    poll_lag = timedelta(minutes=10)
    await _write_projected_lineup(migrated, portland, earlier_at, seen_at=earlier_at + poll_lag)
    await _write_projected_lineup(migrated, portland, confirmed_at, seen_at=confirmed_at + poll_lag)
    await _write_projected_lineup(migrated, portland, confirmed_at, seen_at=confirmed_at + 3 * poll_lag)

    async def version_as_of(moment: datetime) -> list[datetime]:
        return [row["updated_at"] for row in await migrated.fetch(LINEUP_AS_OF, 21718080, moment)]

    assert await migrated.fetchval("SELECT count(*) FROM projected_lineups") == 2
    assert await migrated.fetchval("SELECT count(*) FROM projected_lineup_players") == 10
    assert await migrated.fetchval(
        "SELECT first_seen_at FROM projected_lineups WHERE updated_at = $1", confirmed_at
    ) == confirmed_at + poll_lag
    assert await version_as_of(earlier_at) == []
    assert await version_as_of(confirmed_at) == [earlier_at]
    assert await version_as_of(confirmed_at + poll_lag) == [confirmed_at]


# ---------------------------------------------------------------------------
# Injuries are a change-log, including the player leaving the list
# ---------------------------------------------------------------------------


INJURY_AS_OF = """
SELECT DISTINCT ON (bdl_player_id) bdl_player_id, listed, status
FROM injury_snapshots
WHERE league = 'nba' AND snapshot_at <= $1
ORDER BY bdl_player_id, snapshot_at DESC
"""


@pytest_asyncio.fixture
async def recorded_injury(migrated: asyncpg.Connection) -> dict[str, Any]:
    """The first recorded injury row (Dominick Barlow, Out), with his team and player in place."""
    injury = _recorded("player_injuries__page1.json")[0]
    player = injury["player"]
    await migrated.execute("INSERT INTO teams (league, bdl_team_id) VALUES ('nba', $1)", player["team_id"])
    await migrated.execute(
        "INSERT INTO players (league, bdl_player_id, display_name) VALUES ('nba', $1, $2)",
        player["id"], f"{player['first_name']} {player['last_name']}",
    )
    return injury


async def _write_listed(conn: asyncpg.Connection, injury: dict[str, Any], snapshot_at: datetime) -> None:
    return_date = injury["return_date"]
    await conn.execute(
        """
        INSERT INTO injury_snapshots
            (league, snapshot_at, bdl_player_id, listed, bdl_team_id, status, return_date, description)
        VALUES ('nba', $1, $2, true, $3, $4, $5, $6)
        """,
        snapshot_at, injury["player"]["id"], injury["player"]["team_id"], injury["status"],
        date.fromisoformat(return_date) if return_date else None, injury["description"],
    )


async def _write_removal(conn: asyncpg.Connection, bdl_player_id: int, snapshot_at: datetime) -> None:
    await conn.execute(
        "INSERT INTO injury_snapshots (league, snapshot_at, bdl_player_id, listed) VALUES ('nba', $1, $2, false)",
        snapshot_at, bdl_player_id,
    )


@pytest.mark.asyncio
async def test_injury_row_must_say_whether_the_player_is_listed(
    migrated: asyncpg.Connection, recorded_injury: dict[str, Any]
) -> None:
    """No default: a writer that forgets the flag fails instead of passing a removal off as a listing."""
    with pytest.raises(asyncpg.NotNullViolationError):
        await migrated.execute(
            "INSERT INTO injury_snapshots (league, snapshot_at, bdl_player_id, status) VALUES ('nba', $1, $2, 'Out')",
            _at(10, 0), recorded_injury["player"]["id"],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("column", "value"),
    [("status", "Available"), ("return_date", TIP_DAY), ("description", "Cleared to play")],
    ids=["status", "return_date", "description"],
)
async def test_removal_row_carries_no_injury_details(
    migrated: asyncpg.Connection, recorded_injury: dict[str, Any], column: str, value: object
) -> None:
    """A player off the list has no status. BALLDONTLIE's Available is a player still on the list."""
    with pytest.raises(asyncpg.CheckViolationError, match="injury_snapshots_removal_has_no_details"):
        await migrated.execute(
            f"INSERT INTO injury_snapshots (league, snapshot_at, bdl_player_id, listed, {column})"
            " VALUES ('nba', $1, $2, false, $3)",
            _at(10, 0), recorded_injury["player"]["id"], value,
        )


@pytest.mark.asyncio
async def test_injury_read_as_of_a_time_sees_the_player_leave_the_list(
    migrated: asyncpg.Connection, recorded_injury: dict[str, Any]
) -> None:
    """Without the removal row, every read after 11:00 would still say Out."""
    await _write_listed(migrated, recorded_injury, _at(10, 0))
    await _write_removal(migrated, recorded_injury["player"]["id"], _at(11, 0))

    async def state_as_of(moment: datetime) -> list[tuple[bool, str | None]]:
        return [(row["listed"], row["status"]) for row in await migrated.fetch(INJURY_AS_OF, moment)]

    assert await state_as_of(_at(9, 59)) == []
    assert await state_as_of(_at(10, 59)) == [(True, "Out")]
    assert await state_as_of(_at(11, 0)) == [(False, None)]


# ---------------------------------------------------------------------------
# player_game_stats holds exactly the shapes normalize_stat_row produces
# ---------------------------------------------------------------------------


async def _insert_stat(conn: asyncpg.Connection, **overrides: Any) -> None:
    row: dict[str, Any] = {
        "league": "nba", "bdl_stat_id": 1, "bdl_game_id": 123, "bdl_player_id": 237,
        "bdl_team_id": 14, "season": 2025, "date": TIP_DAY,
        "min_raw": "33", "seconds_played": 1980, "dnp": False,
        "pts": 25, "fgm": 10, "fga": 20, "fg_pct": Decimal("0.5"), "plus_minus": 7,
    } | overrides
    columns = ", ".join(row)
    params = ", ".join(f"${i}" for i in range(1, len(row) + 1))
    await conn.execute(f"INSERT INTO player_game_stats ({columns}) VALUES ({params})", *row.values())


@pytest.mark.asyncio
async def test_played_and_dnp_lines_are_accepted(migrated: asyncpg.Connection) -> None:
    await _insert_stat(migrated)
    await _insert_stat(
        migrated, bdl_stat_id=2, bdl_player_id=115, bdl_team_id=10, min_raw="00",
        dnp=True, seconds_played=None, pts=None, fgm=None, fga=None, fg_pct=None, plus_minus=None,
    )
    count = await migrated.fetchval("SELECT count(*) FROM player_game_stats WHERE dnp")
    assert count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides", [{"date": date(2026, 1, 16)}, {"season": 2024}], ids=["other-date", "other-season"]
)
async def test_stat_line_cannot_disagree_with_its_game(
    migrated: asyncpg.Connection, overrides: dict[str, Any]
) -> None:
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await _insert_stat(migrated, **overrides)


@pytest.mark.asyncio
async def test_rescheduled_game_moves_its_stat_lines(migrated: asyncpg.Connection) -> None:
    await _insert_stat(migrated)
    await migrated.execute("UPDATE games SET date = '2026-01-20' WHERE bdl_game_id = 123")
    assert await migrated.fetchval("SELECT date FROM player_game_stats") == date(2026, 1, 20)


@pytest.mark.asyncio
async def test_player_game_log_builds_the_reader_row_from_ids(migrated: asyncpg.Connection) -> None:
    """Names, side, opponent, and season type come from the game; starter and position from game_lineups."""
    await _insert_stat(migrated)
    await _insert_stat(migrated, bdl_stat_id=2, bdl_player_id=115, bdl_team_id=10, pts=30)
    await migrated.execute(
        "INSERT INTO game_lineups (league, bdl_game_id, bdl_player_id, bdl_team_id, starter, position)"
        " VALUES ('nba', 123, 237, 14, TRUE, 'F')"
    )
    rows = {row["player_name"]: row for row in await migrated.fetch("SELECT * FROM player_game_log")}
    lebron, curry = rows["LeBron James"], rows["Stephen Curry"]
    assert (lebron["home_or_away"], lebron["team_abbr"], lebron["opponent_abbr"], lebron["opponent_team_id"]) == (
        "home", "LAL", "GSW", 10,
    )
    assert (curry["home_or_away"], curry["team_abbr"], curry["opponent_abbr"], curry["opponent_team_id"]) == (
        "away", "GSW", "LAL", 14,
    )
    assert (lebron["is_starter"], lebron["position"]) == (True, "F")
    assert (curry["is_starter"], curry["position"]) == (None, None)
    assert {(row["season_type"], row["season"], row["date"]) for row in rows.values()} == {
        ("regular_season", 2025, TIP_DAY)
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"dnp": True, "seconds_played": None, "fga": None, "fgm": None, "fg_pct": None, "plus_minus": None},
        {"dnp": True, "seconds_played": None, "pts": None, "fga": None, "fgm": None, "plus_minus": None},
        {"seconds_played": None},
        {"fg_pct": Decimal("1.5")},
        {"fg_pct": Decimal("-0.1")},
    ],
    ids=["dnp-with-points", "dnp-with-a-percentage", "played-without-seconds", "pct-above-1", "pct-below-0"],
)
async def test_stat_lines_the_normalizer_never_makes_are_rejected(
    migrated: asyncpg.Connection, overrides: dict[str, Any]
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await _insert_stat(migrated, **overrides)
