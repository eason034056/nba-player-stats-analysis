"""
test_migration_005_bdl_pit.py - point-in-time reads and write refusals on real PostgreSQL.

Each test builds a scratch database, applies 001 through 005 with the runner,
and drops the database afterwards. The tests skip when no server answers
``DATABASE_URL``, like the other migration tests. Nothing here connects to
port 5434.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from app.migrations.runner import discover, upgrade

MIGRATIONS = Path(__file__).resolve().parents[1] / "app" / "migrations"
SQL_005 = MIGRATIONS / "005_bdl_pit.sql"

TABLES_002 = (
    "books", "seasons", "teams", "players", "games", "player_game_stats",
    "injury_snapshots", "game_lineups", "projected_lineups", "projected_lineup_players",
    "prop_markets", "game_odds_snapshots", "player_prop_snapshots", "bdl_backfill_checkpoints",
)

NEW_INDEXES = {
    "player_game_stats_league_bdl_stat_id_uidx",
    "player_prop_snapshots_player_market_game_idx",
    "injury_snapshots_team_latest_idx",
}
NEW_TRIGGERS = {
    "games_refuse_same_team",
    "games_refuse_orphan_stat_team",
    "player_game_stats_refuse_team_not_in_game",
    "player_prop_snapshots_refuse_market_type_mismatch",
}

# Tip of game 1 is 2026-01-02 00:00Z, so T is 21:00Z the day before.
TIP_MINUS_3H = datetime(2026, 1, 1, 21, 0, tzinfo=UTC)
TIP_MINUS_1H = datetime(2026, 1, 1, 23, 0, tzinfo=UTC)
# 2026-01-09 00:00 in New York is EST (UTC-5).
NULL_TIP = datetime(2026, 1, 9, 5, 0, tzinfo=UTC)
# 2026-07-09 00:00 in New York is EDT (UTC-4).
NULL_TIP_SUMMER = datetime(2026, 7, 9, 4, 0, tzinfo=UTC)

SEED = """
INSERT INTO seasons (league, season_start_year, label) VALUES ('nba', 2025, '2025-26');
INSERT INTO teams (league, bdl_team_id, abbreviation) VALUES ('nba', 1, 'AAA'), ('nba', 2, 'BBB');
INSERT INTO players (league, bdl_player_id, display_name)
VALUES ('nba', 10, 'P10'), ('nba', 11, 'P11'), ('nba', 12, 'P12');
INSERT INTO games
    (league, bdl_game_id, season, date, datetime_utc, status_state, season_type,
     home_team_id, visitor_team_id)
VALUES
    ('nba', 1, 2025, '2026-01-01', '2026-01-02 00:00Z', 'final', 'regular_season', 1, 2),
    ('nba', 2, 2025, '2026-01-03', '2026-01-04 00:00Z', 'final', 'regular_season', 2, 1),
    ('nba', 3, 2025, '2026-01-05', '2026-01-06 00:00Z', 'final', 'regular_season', 1, 2),
    ('nba', 4, 2025, '2026-01-07', '2026-01-08 00:00Z', 'final', 'regular_season', 1, 2),
    ('nba', 5, 2025, '2026-01-09', NULL, 'scheduled', 'regular_season', 1, 2);
INSERT INTO player_game_stats
    (league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id, season, date,
     seconds_played, dnp, pts, reb, ast, stl, blk, fg3m)
VALUES
    ('nba', 101, 1, 10, 1, 2025, '2026-01-01', 1800, false, 25, 10, 10, 0, 0, 1),
    ('nba', 102, 2, 10, 1, 2025, '2026-01-03', 1800, false, 20, 2, 2, 0, 0, 1),
    ('nba', 103, 3, 10, 1, 2025, '2026-01-05', 1800, false, 24, 2, 2, 0, 0, 1),
    ('nba', 105, 1, 11, 1, 2025, '2026-01-01', 1800, false, 5, 1, 1, 0, 0, 0),
    ('nba', 106, 3, 11, 1, 2025, '2026-01-05', 1800, false, 5, 1, 1, 0, 0, 0),
    ('nba', 107, 4, 11, 2, 2025, '2026-01-07', 1800, false, 5, 1, 1, 0, 0, 0);
INSERT INTO player_game_stats
    (league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id, season, date, dnp)
VALUES ('nba', 104, 4, 10, 1, 2025, '2026-01-07', true);
"""


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    """001 through 005 applied, plus a clean four-game stat seed."""
    assert await upgrade(scratch_conn) == ["001", "002", "003", "004", "005"]
    await scratch_conn.execute(SEED)
    return scratch_conn


def _statements(sql: str) -> list[str]:
    """SQL lines that are not comments or blank."""
    kept: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            kept.append(stripped)
    return kept


async def _columns(conn: asyncpg.Connection) -> list[tuple]:
    rows = await conn.fetch(
        """
        SELECT table_name, ordinal_position, column_name, udt_name, data_type,
               is_nullable, column_default, character_maximum_length,
               numeric_precision, numeric_scale, datetime_precision
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = ANY($1::text[])
        ORDER BY table_name, ordinal_position
        """,
        list(TABLES_002),
    )
    return [tuple(row) for row in rows]


async def _constraints(conn: asyncpg.Connection) -> list[tuple]:
    rows = await conn.fetch(
        """
        SELECT conrelid::regclass::text, conname, contype, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace
          AND conrelid IN (
              SELECT c.oid FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              WHERE n.nspname = 'public' AND c.relname = ANY($1::text[])
          )
        ORDER BY 1, 2
        """,
        list(TABLES_002),
    )
    return [tuple(row) for row in rows]


async def _indexes(conn: asyncpg.Connection) -> list[tuple]:
    rows = await conn.fetch(
        """
        SELECT c.relname, ic.relname, pg_get_indexdef(i.indexrelid)
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_class ic ON ic.oid = i.indexrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = ANY($1::text[])
        ORDER BY 1, 2
        """,
        list(TABLES_002),
    )
    return [tuple(row) for row in rows]


async def _triggers(conn: asyncpg.Connection) -> list[tuple]:
    rows = await conn.fetch(
        """
        SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid)
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND NOT t.tgisinternal
          AND c.relname = ANY($1::text[])
        ORDER BY 1, 2
        """,
        list(TABLES_002),
    )
    return [tuple(row) for row in rows]


async def _hit(
    conn: asyncpg.Connection,
    league: str,
    player: int,
    market: str,
    threshold: Decimal | None,
    before: str,
    last_n: int | None,
    home: str | None,
    opponent: int | None,
    season_type: str | None,
) -> tuple:
    row = await conn.fetchrow(
        """
        SELECT games, hits, misses, pushes, hit_rate
        FROM player_hit_rate($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        league, player, market, threshold, date.fromisoformat(before), last_n, home, opponent, season_type,
    )
    return (row["games"], row["hits"], row["misses"], row["pushes"], row["hit_rate"])


# ---------------------------------------------------------------------------
# The file and the 002 tables
# ---------------------------------------------------------------------------


def test_005_does_not_alter_drop_or_comment_on_a_002_object() -> None:
    """Refusal is an index and triggers. The 14 tables are not rewritten."""
    statements = _statements(SQL_005.read_text(encoding="utf-8"))
    upper = "\n".join(statements).upper()
    assert "ALTER TABLE" not in upper
    assert "DROP " not in upper
    comments = [line for line in statements if line.upper().startswith("COMMENT ON")]
    assert comments == ["COMMENT ON COLUMN projected_lineup_versions.known_from IS"]
    for name in TABLES_002:
        assert f"COMMENT ON COLUMN {name}." not in upper
        assert f"COMMENT ON TABLE {name}" not in upper


@pytest.mark.asyncio
async def test_a_second_runner_pass_is_a_no_op(db: asyncpg.Connection) -> None:
    assert await upgrade(db) == []
    versions = await db.fetch("SELECT version FROM schema_migrations ORDER BY version")
    assert [row["version"] for row in versions] == ["001", "002", "003", "004", "005"]
    assert await db.fetchval("SELECT to_regclass('public.bdl_games_with_gaps') IS NOT NULL")
    assert await db.fetchval("SELECT to_regclass('public.player_game_log') IS NOT NULL")


@pytest.mark.asyncio
async def test_002_tables_keep_columns_types_and_constraints(
    scratch_conn: asyncpg.Connection, tmp_path: Path
) -> None:
    """005 may add indexes and triggers. Columns and constraints stay put."""
    for migration in discover():
        if migration.version != "005":
            (tmp_path / migration.path.name).write_bytes(migration.path.read_bytes())
    assert await upgrade(scratch_conn, tmp_path) == ["001", "002", "003", "004"]

    before_columns = await _columns(scratch_conn)
    before_constraints = await _constraints(scratch_conn)
    before_indexes = await _indexes(scratch_conn)
    before_triggers = await _triggers(scratch_conn)
    before_books = [tuple(row) for row in await scratch_conn.fetch(
        "SELECT league, book_key, source_group, display_name, active FROM books ORDER BY 1, 2"
    )]
    before_markets = [tuple(row) for row in await scratch_conn.fetch(
        "SELECT league, market, bdl_prop_type, stat_columns, settle_rule, min_double_digits "
        "FROM prop_markets ORDER BY 1, 2"
    )]

    assert await upgrade(scratch_conn) == ["005"]

    assert await _columns(scratch_conn) == before_columns
    assert await _constraints(scratch_conn) == before_constraints
    assert [tuple(row) for row in await scratch_conn.fetch(
        "SELECT league, book_key, source_group, display_name, active FROM books ORDER BY 1, 2"
    )] == before_books
    assert [tuple(row) for row in await scratch_conn.fetch(
        "SELECT league, market, bdl_prop_type, stat_columns, settle_rule, min_double_digits "
        "FROM prop_markets ORDER BY 1, 2"
    )] == before_markets

    added_indexes = {name for _table, name, _defn in set(await _indexes(scratch_conn)) - set(before_indexes)}
    assert added_indexes == NEW_INDEXES
    assert {name for _table, name, _defn in before_indexes} <= {
        name for _table, name, _defn in await _indexes(scratch_conn)
    }
    unique = await scratch_conn.fetchval(
        """
        SELECT indisunique FROM pg_index
        WHERE indexrelid = 'player_game_stats_league_bdl_stat_id_uidx'::regclass
        """
    )
    assert unique is True

    added_triggers = {name for _table, name, _defn in set(await _triggers(scratch_conn)) - set(before_triggers)}
    assert added_triggers == NEW_TRIGGERS
    definitions = {name: defn for _table, name, defn in await _triggers(scratch_conn)}
    assert "BEFORE INSERT OR UPDATE" in definitions["games_refuse_same_team"]
    assert "BEFORE UPDATE OF home_team_id, visitor_team_id" in definitions["games_refuse_orphan_stat_team"]
    assert "BEFORE INSERT OR UPDATE" in definitions["player_game_stats_refuse_team_not_in_game"]
    assert "BEFORE INSERT OR UPDATE" in definitions["player_prop_snapshots_refuse_market_type_mismatch"]


@pytest.mark.asyncio
async def test_the_read_objects_exist(db: asyncpg.Connection) -> None:
    rows = await db.fetch(
        """
        SELECT c.relname, c.relkind FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = ANY($1::text[])
        """,
        [
            "source_refreshes", "projected_lineup_sources", "projected_lineup_versions",
            "bdl_integrity_problems",
        ],
    )
    kinds = {
        row["relname"]: (row["relkind"].decode() if isinstance(row["relkind"], bytes) else row["relkind"])
        for row in rows
    }
    assert kinds == {
        "source_refreshes": "r",
        "projected_lineup_sources": "r",
        "projected_lineup_versions": "v",
        "bdl_integrity_problems": "v",
    }
    functions = {
        row["proname"]
        for row in await db.fetch(
            """
            SELECT p.proname FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public'
            """
        )
    }
    assert {
        "game_as_of", "source_covered", "projected_lineups_asof", "injuries_asof",
        "teammate_availability", "player_market_results", "player_hit_rate",
    } <= functions
    comment = await db.fetchval(
        """
        SELECT col_description(c.oid, a.attnum)
        FROM pg_class c
        JOIN pg_attribute a ON a.attrelid = c.oid
        WHERE c.relname = 'projected_lineup_versions' AND a.attname = 'known_from'
        """
    )
    assert comment is not None and "known_from <= T" in comment


# ---------------------------------------------------------------------------
# T, hit rate, teammates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_game_as_of_is_tip_minus_three_hours_unless_the_tip_is_null(
    db: asyncpg.Connection,
) -> None:
    assert await db.fetchval("SELECT game_as_of('nba', 1)") == TIP_MINUS_3H
    assert await db.fetchval("SELECT game_as_of('nba', 1, 3)") == TIP_MINUS_3H
    assert await db.fetchval("SELECT game_as_of('nba', 1, 1)") == TIP_MINUS_1H
    assert await db.fetchval("SELECT game_as_of('nba', 5)") == NULL_TIP
    assert await db.fetchval("SELECT game_as_of('nba', 5, 1)") == NULL_TIP

    await db.execute(
        """
        INSERT INTO games
            (league, bdl_game_id, season, date, datetime_utc, status_state, season_type,
             home_team_id, visitor_team_id)
        VALUES ('nba', 50, 2025, '2026-07-09', NULL, 'scheduled', 'regular_season', 1, 2)
        """
    )
    assert await db.fetchval("SELECT game_as_of('nba', 50)") == NULL_TIP_SUMMER


@pytest.mark.asyncio
async def test_game_as_of_accepts_wnba(db: asyncpg.Connection) -> None:
    """005 does not narrow league_code. WNBA uses the same T."""
    await db.execute(
        """
        INSERT INTO seasons (league, season_start_year, label) VALUES ('wnba', 2026, '2026');
        INSERT INTO teams (league, bdl_team_id) VALUES ('wnba', 1), ('wnba', 2);
        INSERT INTO games
            (league, bdl_game_id, season, date, datetime_utc, status_state, season_type,
             home_team_id, visitor_team_id)
        VALUES ('wnba', 1, 2026, '2026-06-01', '2026-06-02 00:00Z', 'scheduled', 'regular_season', 1, 2);
        """
    )
    assert await db.fetchval("SELECT game_as_of('wnba', 1)") == datetime(2026, 6, 1, 21, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_results_mark_over_under_push_and_void(db: asyncpg.Connection) -> None:
    results = await db.fetch(
        """
        SELECT bdl_game_id, result FROM player_market_results('nba', 10, 'player_points', 24.5, '2026-01-08')
        ORDER BY date
        """
    )
    assert [tuple(row) for row in results] == [(1, "over"), (2, "under"), (3, "under"), (4, "void")]
    push = await db.fetchval(
        """
        SELECT result FROM player_market_results('nba', 10, 'player_points', 24, '2026-01-08')
        WHERE bdl_game_id = 3
        """
    )
    assert push == "push"


@pytest.mark.asyncio
async def test_a_null_stat_is_unknown_and_left_out_of_the_hit_rate(db: asyncpg.Connection) -> None:
    await db.execute(
        """
        INSERT INTO player_game_stats
            (league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id, season, date,
             seconds_played, dnp, pts)
        VALUES ('nba', 201, 1, 12, 1, 2025, '2026-01-01', 1800, false, NULL)
        """
    )
    assert await db.fetchval(
        """
        SELECT result FROM player_market_results('nba', 12, 'player_points', 24.5, '2026-01-02')
        """
    ) == "unknown"
    assert await _hit(db, "nba", 12, "player_points", Decimal("24.5"), "2026-01-08", None, None, None, None) == (
        0, 0, 0, 0, None,
    )


@pytest.mark.asyncio
async def test_hit_rate_keeps_a_push_out_of_the_denominator(db: asyncpg.Connection) -> None:
    """Void is excluded. A push is counted and is not a hit or a miss."""
    assert await _hit(db, "nba", 10, "player_points", Decimal("24.5"), "2026-01-08", None, None, None, None) == (
        3, 1, 2, 0, Decimal("0.3333"),
    )
    assert await _hit(db, "nba", 10, "player_points", Decimal("24"), "2026-01-08", None, None, None, None) == (
        3, 1, 1, 1, Decimal("0.5"),
    )


@pytest.mark.asyncio
async def test_last_n_skips_a_void_and_a_push_uses_one_slot(db: asyncpg.Connection) -> None:
    """Settled 2026-11-21: a push stays in the last-N window."""
    assert await _hit(db, "nba", 10, "player_points", Decimal("24.5"), "2026-01-08", 2, None, None, None) == (
        2, 0, 2, 0, Decimal("0"),
    )
    # Newest settled games at line 24 are the push, then the under. The older over is outside N.
    assert await _hit(db, "nba", 10, "player_points", Decimal("24"), "2026-01-08", 2, None, None, None) == (
        2, 0, 1, 1, Decimal("0"),
    )


@pytest.mark.asyncio
async def test_before_date_and_splits(db: asyncpg.Connection) -> None:
    assert await _hit(db, "nba", 10, "player_points", Decimal("24.5"), "2026-01-03", None, None, None, None) == (
        1, 1, 0, 0, Decimal("1"),
    )
    assert await _hit(db, "nba", 10, "player_points", Decimal("24.5"), "2026-01-08", None, "home", None, None) == (
        2, 1, 1, 0, Decimal("0.5"),
    )
    assert await _hit(db, "nba", 10, "player_points", Decimal("24.5"), "2026-01-08", None, None, 2, None) == (
        3, 1, 2, 0, Decimal("0.3333"),
    )
    assert await _hit(db, "nba", 10, "player_points", Decimal("24.5"), "2026-01-08", None, None, 1, None) == (
        0, 0, 0, 0, None,
    )
    assert await _hit(
        db, "nba", 10, "player_points", Decimal("24.5"), "2026-01-08", None, None, None, "regular_season"
    ) == (3, 1, 2, 0, Decimal("0.3333"))
    assert await _hit(
        db, "nba", 10, "player_points", Decimal("24.5"), "2026-01-08", None, None, None, "playoffs"
    ) == (0, 0, 0, 0, None)


@pytest.mark.asyncio
async def test_double_digit_markets_are_yes_or_no(db: asyncpg.Connection) -> None:
    assert await db.fetchval(
        "SELECT result FROM player_market_results('nba', 10, 'player_triple_double', NULL, '2026-01-02')"
    ) == "yes"
    assert await db.fetchval(
        """
        SELECT result FROM player_market_results('nba', 10, 'player_triple_double', 100, '2026-01-04')
        WHERE bdl_game_id = 2
        """
    ) == "no"
    rate = await _hit(db, "nba", 10, "player_triple_double", None, "2026-01-08", None, None, None, None)
    assert rate == (3, 1, 2, 0, Decimal("0.3333"))


@pytest.mark.asyncio
async def test_teammate_availability_is_inferred_without_leaking_or_trading(
    db: asyncpg.Connection,
) -> None:
    out = await db.fetchrow(
        """
        SELECT state, is_out, out_basis
        FROM teammate_availability('nba', 1, 2025, '2026-01-06')
        WHERE bdl_player_id = 11 AND bdl_game_id = 2
        """
    )
    assert (out["state"], out["is_out"], out["out_basis"]) == ("absent", True, "inferred_from_stats")
    assert await db.fetchval(
        """
        SELECT count(*) FROM teammate_availability('nba', 1, 2025, '2026-01-04')
        WHERE bdl_player_id = 11 AND bdl_game_id = 2
        """
    ) == 0
    assert await db.fetchval(
        """
        SELECT count(*) FROM teammate_availability('nba', 1, 2025, '2026-01-08')
        WHERE bdl_player_id = 11 AND bdl_game_id = 4
        """
    ) == 0
    played = await db.fetchrow(
        """
        SELECT state, is_out, out_basis
        FROM teammate_availability('nba', 1, 2025, '2026-01-08')
        WHERE bdl_player_id = 10 AND bdl_game_id = 1
        """
    )
    assert (played["state"], played["is_out"], played["out_basis"]) == ("played", False, "inferred_from_stats")
    dnp = await db.fetchrow(
        """
        SELECT state, is_out, out_basis
        FROM teammate_availability('nba', 1, 2025, '2026-01-08')
        WHERE bdl_player_id = 10 AND bdl_game_id = 4
        """
    )
    assert (dnp["state"], dnp["is_out"], dnp["out_basis"]) == ("dnp", True, "inferred_from_stats")


@pytest.mark.asyncio
async def test_a_stat_on_the_home_team_or_the_visitor_is_stored(db: asyncpg.Connection) -> None:
    rows = await db.fetch(
        """
        SELECT bdl_game_id, bdl_team_id FROM player_game_stats
        WHERE bdl_player_id = 11 ORDER BY bdl_game_id
        """
    )
    assert [tuple(row) for row in rows] == [(1, 1), (3, 1), (4, 2)]


# ---------------------------------------------------------------------------
# Lineups, injuries, coverage
# ---------------------------------------------------------------------------


async def _lineups(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        INSERT INTO projected_lineups
            (league, bdl_game_id, bdl_team_id, updated_at, first_seen_at, status)
        VALUES
            ('nba', 4, 1, '2026-01-07 20:00Z', '2026-01-07 20:30Z', 'expected'),
            ('nba', 4, 1, '2026-01-07 22:00Z', '2026-01-07 22:05Z', 'confirmed'),
            ('nba', 4, 2, '2026-01-07 20:00Z', '2026-11-21 06:00Z', 'confirmed');
        INSERT INTO projected_lineup_players
            (league, bdl_game_id, bdl_team_id, updated_at, bdl_player_id, position)
        VALUES
            ('nba', 4, 1, '2026-01-07 20:00Z', 10, 'G'),
            ('nba', 4, 1, '2026-01-07 22:00Z', 11, 'G'),
            ('nba', 4, 2, '2026-01-07 20:00Z', 12, 'F');
        """
    )


@pytest.mark.asyncio
async def test_projected_lineups_asof_hides_a_backfill_until_it_is_marked(
    db: asyncpg.Connection,
) -> None:
    await _lineups(db)
    tip_t = await db.fetchval("SELECT game_as_of('nba', 4)")
    assert await db.fetchval(
        "SELECT count(*) FROM projected_lineups_asof('nba', 4, $1) WHERE bdl_team_id = 2", tip_t
    ) == 0

    await db.execute(
        """
        INSERT INTO projected_lineup_sources
            (league, bdl_game_id, bdl_team_id, updated_at, source)
        VALUES ('nba', 4, 2, '2026-01-07 20:00Z', 'backfill_final')
        """
    )
    picked = await db.fetch(
        """
        SELECT bdl_team_id, bdl_player_id FROM projected_lineups_asof('nba', 4, $1)
        ORDER BY bdl_team_id
        """,
        tip_t,
    )
    assert [tuple(row) for row in picked] == [(1, 10), (2, 12)]
    # The poll version first seen at 22:05 is after T, so the frontend's latest row is not the as-of row.
    assert await db.fetchval(
        "SELECT bdl_player_id FROM current_projected_lineups WHERE bdl_game_id = 4 AND bdl_team_id = 1"
    ) == 11


@pytest.mark.asyncio
async def test_known_from_equal_to_t_is_visible_and_one_second_later_is_not(
    db: asyncpg.Connection,
) -> None:
    """The filter is known_from <= T. Equality is inside the window."""
    await db.execute(
        """
        INSERT INTO projected_lineups
            (league, bdl_game_id, bdl_team_id, updated_at, first_seen_at, status)
        VALUES
            ('nba', 5, 1, '2026-01-09 05:00Z', '2026-01-09 05:00Z', 'expected'),
            ('nba', 5, 1, '2026-01-09 05:01Z', '2026-01-09 05:00:01Z', 'confirmed');
        INSERT INTO projected_lineup_players
            (league, bdl_game_id, bdl_team_id, updated_at, bdl_player_id, position)
        VALUES
            ('nba', 5, 1, '2026-01-09 05:00Z', 10, 'G'),
            ('nba', 5, 1, '2026-01-09 05:01Z', 11, 'G');
        """
    )
    players = await db.fetch(
        """
        SELECT bdl_player_id FROM projected_lineups_asof('nba', 5, game_as_of('nba', 5))
        """
    )
    assert [row["bdl_player_id"] for row in players] == [10]


@pytest.mark.asyncio
async def test_injuries_asof_keeps_the_latest_listed_row(db: asyncpg.Connection) -> None:
    await db.execute(
        """
        INSERT INTO injury_snapshots
            (league, snapshot_at, bdl_player_id, listed, bdl_team_id, status, description)
        VALUES
            ('nba', '2026-01-07 18:00Z', 11, true, 1, 'Out', 'knee'),
            ('nba', '2026-01-07 22:00Z', 11, false, NULL, NULL, NULL);
        """
    )
    status = await db.fetchval(
        "SELECT status FROM injuries_asof('nba', game_as_of('nba', 4)) WHERE bdl_player_id = 11"
    )
    assert status == "Out"
    assert await db.fetchval(
        "SELECT count(*) FROM injuries_asof('nba', '2026-01-07 23:00Z') WHERE bdl_player_id = 11"
    ) == 0


@pytest.mark.asyncio
async def test_source_covered_is_false_before_go_live_when_stale_and_when_incomplete(
    db: asyncpg.Connection,
) -> None:
    tip_t = await db.fetchval("SELECT game_as_of('nba', 4)")
    assert await db.fetchval("SELECT source_covered('nba', 'injuries', $1)", tip_t) is False

    await db.execute(
        """
        INSERT INTO source_refreshes (league, source, refreshed_at, complete, error)
        VALUES ('nba', 'injuries', '2026-01-07 20:37Z', false, 'timeout')
        """
    )
    assert await db.fetchval("SELECT source_covered('nba', 'injuries', $1)", tip_t) is False

    await db.execute(
        """
        INSERT INTO source_refreshes (league, source, refreshed_at, complete)
        VALUES ('nba', 'injuries', '2026-01-07 20:07Z', true)
        """
    )
    assert await db.fetchval("SELECT source_covered('nba', 'injuries', $1)", tip_t) is True
    assert await db.fetchval(
        "SELECT source_covered('nba', 'injuries', '2026-01-07 22:00Z')"
    ) is False

    await db.execute(
        """
        INSERT INTO source_refreshes (league, source, refreshed_at, complete)
        VALUES ('nba', 'projected_lineups', $1::timestamptz - interval '90 minutes', true)
        """,
        tip_t,
    )
    assert await db.fetchval("SELECT source_covered('nba', 'projected_lineups', $1)", tip_t) is True
    await db.execute(
        """
        INSERT INTO source_refreshes (league, source, refreshed_at, complete)
        VALUES ('nba', 'props_live', $1::timestamptz - interval '90 minutes' - interval '1 second', true)
        """,
        tip_t,
    )
    assert await db.fetchval("SELECT source_covered('nba', 'props_live', $1)", tip_t) is False
    assert await db.fetchval(
        "SELECT source_covered('nba', 'props_live', $1, interval '91 minutes')", tip_t
    ) is True


@pytest.mark.asyncio
async def test_source_refreshes_rejects_an_unknown_source_and_a_silent_failure(
    db: asyncpg.Connection,
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await db.execute(
            """
            INSERT INTO source_refreshes (league, source, refreshed_at, complete)
            VALUES ('nba', 'not_a_source', now(), true)
            """
        )
    with pytest.raises(asyncpg.CheckViolationError):
        await db.execute(
            """
            INSERT INTO source_refreshes (league, source, refreshed_at, complete)
            VALUES ('nba', 'injuries', now(), false)
            """
        )


# ---------------------------------------------------------------------------
# Refusal, and the view behind it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_clean_seed_has_no_integrity_problems(db: asyncpg.Connection) -> None:
    assert await db.fetchval("SELECT count(*) FROM bdl_integrity_problems") == 0


@pytest.mark.asyncio
async def test_a_game_between_one_team_is_refused(db: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.CheckViolationError, match="games_same_team"):
        await db.execute(
            """
            INSERT INTO games
                (league, bdl_game_id, season, date, status_state, season_type, home_team_id, visitor_team_id)
            VALUES ('nba', 6, 2025, '2026-01-11', 'scheduled', 'regular_season', 1, 1)
            """
        )
    assert await db.fetchval("SELECT count(*) FROM games WHERE bdl_game_id = 6") == 0
    with pytest.raises(asyncpg.CheckViolationError, match="games_same_team"):
        await db.execute("UPDATE games SET visitor_team_id = home_team_id WHERE bdl_game_id = 5")


@pytest.mark.asyncio
async def test_a_duplicate_stat_id_is_refused(db: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.UniqueViolationError, match="player_game_stats_league_bdl_stat_id_uidx"):
        await db.execute(
            """
            INSERT INTO player_game_stats
                (league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id, season, date, dnp)
            VALUES ('nba', 101, 4, 12, 1, 2025, '2026-01-07', true)
            """
        )
    assert await db.fetchval("SELECT count(*) FROM player_game_stats WHERE bdl_stat_id = 101") == 1


@pytest.mark.asyncio
async def test_a_stat_team_outside_the_game_is_refused(db: asyncpg.Connection) -> None:
    await db.execute("INSERT INTO teams (league, bdl_team_id, abbreviation) VALUES ('nba', 3, 'CCC')")
    with pytest.raises(asyncpg.CheckViolationError, match="stat_team_not_in_game"):
        await db.execute(
            """
            INSERT INTO player_game_stats
                (league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id, season, date,
                 seconds_played, dnp, pts)
            VALUES ('nba', 301, 1, 12, 3, 2025, '2026-01-01', 1800, false, 8)
            """
        )
    with pytest.raises(asyncpg.CheckViolationError, match="stat_team_not_in_game"):
        await db.execute(
            "UPDATE player_game_stats SET bdl_team_id = 3 WHERE bdl_game_id = 1 AND bdl_player_id = 10"
        )
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await db.execute(
            """
            INSERT INTO player_game_stats
                (league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id, season, date,
                 seconds_played, dnp, pts)
            VALUES ('nba', 302, 1, 12, 99999, 2025, '2026-01-01', 1800, false, 8)
            """
        )


@pytest.mark.asyncio
async def test_a_game_update_cannot_orphan_a_stat_and_a_swap_can(db: asyncpg.Connection) -> None:
    await db.execute("INSERT INTO teams (league, bdl_team_id, abbreviation) VALUES ('nba', 3, 'CCC')")
    with pytest.raises(asyncpg.CheckViolationError, match="stat_team_not_in_game"):
        await db.execute("UPDATE games SET home_team_id = 2, visitor_team_id = 3 WHERE bdl_game_id = 1")
    await db.execute("UPDATE games SET home_score = 100 WHERE bdl_game_id = 1")
    await db.execute("UPDATE games SET home_team_id = 2, visitor_team_id = 1 WHERE bdl_game_id = 1")
    sides = await db.fetchval(
        "SELECT home_team_id::text || ':' || visitor_team_id::text FROM games WHERE bdl_game_id = 1"
    )
    assert sides == "2:1"
    assert await db.fetchval("SELECT count(*) FROM bdl_integrity_problems") == 0


@pytest.mark.asyncio
async def test_a_prop_market_type_that_does_not_match_its_settle_rule_is_refused(
    db: asyncpg.Connection,
) -> None:
    with pytest.raises(asyncpg.CheckViolationError, match="prop_market_type_mismatch"):
        await db.execute(
            """
            INSERT INTO player_prop_snapshots
                (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type,
                 line, milestone_odds)
            VALUES ('nba', 'opening', 4, 10, 'draftkings', 'player_points', 'milestone', 25, 150)
            """
        )
    with pytest.raises(asyncpg.CheckViolationError, match="prop_market_type_mismatch"):
        await db.execute(
            """
            INSERT INTO player_prop_snapshots
                (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type,
                 line, over_odds, under_odds)
            VALUES ('nba', 'opening', 4, 10, 'draftkings', 'player_double_double', 'over_under',
                    0.5, -110, -110)
            """
        )
    with pytest.raises(asyncpg.CheckViolationError, match="prop_market_type_mismatch"):
        await db.execute(
            """
            INSERT INTO player_prop_snapshots
                (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type,
                 line, over_odds, under_odds)
            VALUES ('nba', 'opening', 4, 11, 'draftkings', 'player_triple_double', 'over_under',
                    0.5, -110, -110)
            """
        )

    await db.execute(
        """
        INSERT INTO player_prop_snapshots
            (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type,
             line, over_odds, under_odds)
        VALUES ('nba', 'opening', 4, 10, 'draftkings', 'player_points', 'over_under', 24.5, -110, -110)
        """
    )
    await db.execute(
        """
        INSERT INTO player_prop_snapshots
            (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type,
             line, milestone_odds)
        VALUES ('nba', 'opening', 4, 10, 'draftkings', 'player_double_double', 'milestone', 0.5, 150)
        """
    )
    await db.execute(
        """
        INSERT INTO player_prop_snapshots
            (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type,
             line, milestone_odds)
        VALUES ('nba', 'opening', 4, 11, 'fanduel', 'player_triple_double', 'milestone', 0.5, 400)
        """
    )
    with pytest.raises(asyncpg.CheckViolationError, match="prop_market_type_mismatch"):
        await db.execute(
            """
            INSERT INTO player_prop_snapshots
                (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type,
                 line, milestone_odds)
            VALUES ('nba', 'opening', 4, 10, 'draftkings', 'player_points', 'milestone', 25, 150)
            ON CONFLICT (league, bdl_game_id, bdl_player_id, book_key, market)
                WHERE snapshot_kind = 'opening'
            DO UPDATE SET market_type = EXCLUDED.market_type,
                          milestone_odds = EXCLUDED.milestone_odds,
                          over_odds = NULL,
                          under_odds = NULL
            """
        )
    stored = await db.fetchrow(
        """
        SELECT market_type, over_odds, milestone_odds FROM player_prop_snapshots
        WHERE market = 'player_points'
        """
    )
    assert (stored["market_type"], stored["over_odds"], stored["milestone_odds"]) == ("over_under", -110, None)
    assert await db.fetchval("SELECT count(*) FROM bdl_integrity_problems") == 0


@pytest.mark.asyncio
async def test_the_integrity_view_finds_each_problem_when_refusal_is_lifted(
    db: asyncpg.Connection,
) -> None:
    """The view is the backstop. It sees a row only when the refusal object is not enforcing."""
    tx = db.transaction()
    await tx.start()
    try:
        await db.execute("ALTER TABLE games DISABLE TRIGGER games_refuse_same_team")
        await db.execute(
            "ALTER TABLE player_game_stats DISABLE TRIGGER player_game_stats_refuse_team_not_in_game"
        )
        await db.execute(
            "ALTER TABLE player_prop_snapshots DISABLE TRIGGER player_prop_snapshots_refuse_market_type_mismatch"
        )
        await db.execute("DROP INDEX player_game_stats_league_bdl_stat_id_uidx")
        await db.execute("INSERT INTO teams (league, bdl_team_id, abbreviation) VALUES ('nba', 3, 'CCC')")
        await db.execute(
            """
            INSERT INTO games
                (league, bdl_game_id, season, date, status_state, season_type, home_team_id, visitor_team_id)
            VALUES ('nba', 6, 2025, '2026-01-11', 'scheduled', 'regular_season', 1, 1);
            INSERT INTO player_game_stats
                (league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id, season, date, dnp)
            VALUES ('nba', 101, 4, 12, 1, 2025, '2026-01-07', true);
            INSERT INTO player_game_stats
                (league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id, season, date,
                 seconds_played, dnp, pts)
            VALUES ('nba', 301, 1, 12, 3, 2025, '2026-01-01', 1800, false, 8);
            INSERT INTO player_prop_snapshots
                (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type,
                 line, milestone_odds)
            VALUES ('nba', 'opening', 4, 10, 'draftkings', 'player_points', 'milestone', 25, 150);
            """
        )
        found = await db.fetch("SELECT problem, key FROM bdl_integrity_problems ORDER BY problem, key")
        assert [(row["problem"], row["key"]) for row in found] == [
            ("games_same_team", "6"),
            ("prop_market_type_mismatch", "1"),
            ("stat_id_duplicate", "101"),
            ("stat_team_not_in_game", "1:12"),
        ]
    finally:
        await tx.rollback()

    assert await db.fetchval("SELECT count(*) FROM bdl_integrity_problems") == 0
    assert await db.fetchval(
        "SELECT to_regclass('public.player_game_stats_league_bdl_stat_id_uidx') IS NOT NULL"
    )
