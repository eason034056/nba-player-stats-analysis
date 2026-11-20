"""
test_migration_runner.py - ``python -m app.migrations upgrade``.

The runner applies ``backend/app/migrations/NNN_*.sql`` in order. Each file
and the ``schema_migrations`` row that records it commit together, so a file
is either applied and recorded or neither. The database tests use the
scratch databases in ``conftest.py`` and skip when no Postgres answers.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest

from app.migrations.runner import MigrationError, discover, upgrade

BACKEND_DIR = Path(__file__).resolve().parents[1]


async def _versions(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch("SELECT version FROM schema_migrations ORDER BY version")
    return [row["version"] for row in rows]


async def _has_table(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{name}")


def _write(directory: Path, files: dict[str, str]) -> Path:
    for name, sql in files.items():
        (directory / name).write_text(sql, encoding="utf-8")
    return directory


@pytest.mark.asyncio
async def test_upgrade_applies_the_shipped_files_once(scratch_conn: asyncpg.Connection) -> None:
    assert await upgrade(scratch_conn) == ["001", "002"]
    assert await _has_table(scratch_conn, "odds_line_snapshots")
    assert await _has_table(scratch_conn, "player_game_stats")
    assert await _versions(scratch_conn) == ["001", "002"]

    assert await upgrade(scratch_conn) == []
    assert await _versions(scratch_conn) == ["001", "002"]


@pytest.mark.asyncio
async def test_failed_file_is_not_recorded_and_earlier_files_stay(
    scratch_conn: asyncpg.Connection, tmp_path: Path
) -> None:
    directory = _write(tmp_path, {
        "001_first.sql": "CREATE TABLE first_table (id INTEGER);",
        "002_second.sql": "CREATE TABLE second_table (id INTEGER); SELECT 1 / 0;",
    })
    with pytest.raises(asyncpg.DivisionByZeroError):
        await upgrade(scratch_conn, directory)
    assert await _versions(scratch_conn) == ["001"]
    assert await _has_table(scratch_conn, "first_table")
    assert not await _has_table(scratch_conn, "second_table")

    _write(directory, {"002_second.sql": "CREATE TABLE second_table (id INTEGER);"})
    assert await upgrade(scratch_conn, directory) == ["002"]
    assert await _versions(scratch_conn) == ["001", "002"]


@pytest.mark.asyncio
async def test_file_and_its_record_commit_together(
    scratch_conn: asyncpg.Connection, tmp_path: Path
) -> None:
    """The file succeeds and recording it fails: the file must roll back too, or a rerun hits its objects."""
    directory = _write(tmp_path, {
        "001_refuses_its_record.sql": """
            CREATE TABLE created_by_001 (id INTEGER);
            CREATE FUNCTION refuse() RETURNS trigger LANGUAGE plpgsql
                AS $$ BEGIN RAISE EXCEPTION 'record refused'; END $$;
            CREATE TRIGGER refuse BEFORE INSERT ON schema_migrations
                FOR EACH ROW EXECUTE FUNCTION refuse();
        """,
    })
    with pytest.raises(asyncpg.RaiseError):
        await upgrade(scratch_conn, directory)
    assert not await _has_table(scratch_conn, "created_by_001")
    assert await _versions(scratch_conn) == []


def test_shipped_files_are_in_version_order() -> None:
    assert [migration.version for migration in discover()] == ["001", "002"]


@pytest.mark.parametrize(
    "names",
    [
        ["002_bdl_core.sql", "notes.sql"],
        ["002_bdl_core.sql", "2_short.sql"],
        ["002_bdl_core.sql", "002_other.sql"],
    ],
    ids=["unnumbered", "short-number", "duplicate-version"],
)
def test_discover_rejects_files_it_cannot_order(tmp_path: Path, names: list[str]) -> None:
    """A file the runner would skip or order wrongly stops the run before any SQL."""
    _write(tmp_path, dict.fromkeys(names, "SELECT 1;"))
    with pytest.raises(MigrationError):
        discover(tmp_path)


def _cli(env_name: str, dsn: str | None) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != env_name}
    if dsn is not None:
        env[env_name] = dsn
    return subprocess.run(
        [sys.executable, "-m", "app.migrations", "upgrade", "--dsn-env", env_name],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_reads_the_dsn_from_the_named_variable(scratch_dsn: str) -> None:
    result = _cli("SPO138_TEST_DSN", scratch_dsn)
    assert result.returncode == 0, result.stderr
    assert "002" in result.stdout
    assert scratch_dsn not in result.stdout + result.stderr


def test_cli_failure_does_not_print_the_password() -> None:
    result = _cli("SPO138_TEST_DSN", "postgresql://nba:pw-must-not-leak@127.0.0.1:1/nba_history")
    assert result.returncode == 1
    assert "pw-must-not-leak" not in result.stdout + result.stderr


def test_cli_without_the_variable_names_it() -> None:
    result = _cli("SPO138_TEST_DSN", None)
    assert result.returncode == 2
    assert "SPO138_TEST_DSN" in result.stderr


@pytest.mark.asyncio
async def test_concurrent_upgrades_apply_each_file_once(
    scratch_dsn: str, tmp_path: Path
) -> None:
    """Two upgrades at once, holding the advisory lock, run each file one time."""
    directory = _write(tmp_path, {
        "001_slow.sql": (
            "CREATE TABLE apply_once (n INTEGER);"
            "INSERT INTO apply_once VALUES (1);"
            "SELECT pg_sleep(0.8);"
        ),
        "002_next.sql": (
            "CREATE TABLE apply_once_b (n INTEGER);"
            "INSERT INTO apply_once_b VALUES (1);"
        ),
    })
    first = await asyncpg.connect(scratch_dsn, timeout=5)
    second = await asyncpg.connect(scratch_dsn, timeout=5)
    try:
        results = await asyncio.gather(
            upgrade(first, directory),
            upgrade(second, directory),
        )
        count_a = await first.fetchval("SELECT count(*) FROM apply_once")
        count_b = await first.fetchval("SELECT count(*) FROM apply_once_b")
    finally:
        await first.close()
        await second.close()
    assert sorted(results, key=len) == [[], ["001", "002"]]
    assert count_a == 1
    assert count_b == 1
