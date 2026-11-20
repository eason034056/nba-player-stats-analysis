"""
test_backfill_cli.py - ``python -m app.backfill``.

``run_backfill`` is driven by the real ``BdlClient`` answered from recorded
captures (``backfill_support.py``). The database tests apply the shipped
migrations to a scratch database (``conftest.py``). ``main`` is called in
process for its usage errors and its error output.
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from app.backfill import cli
from app.backfill.cli import SeasonOutcome, current_season, describe, main, parse_seasons, run_backfill
from app.migrations.runner import upgrade
from tests.backfill_support import (
    RecordedSeasons,
    capture,
    next_cursor,
    recorded_client,
    season_2000_routes,
    season_2025_routes,
)

DSN_ENV = "SPO138_BACKFILL_TEST_DSN"


# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tokens", "seasons"),
    [
        (["2025"], [2025]),
        (["2000-2002"], [2000, 2001, 2002]),
        (["2025", "2000", "2025"], [2000, 2025]),
    ],
)
def test_seasons_are_start_years_or_ranges(tokens: list[str], seasons: list[int]) -> None:
    assert parse_seasons(tokens) == seasons


@pytest.mark.parametrize("token", ["2000-01", "2002-2000", "25", "abc"])
def test_a_season_label_or_a_backwards_range_is_refused(token: str) -> None:
    """``2000-01`` is how a season is labelled, not how it is asked for: that is ``2000``."""
    with pytest.raises(ValueError):
        parse_seasons([token])


@pytest.mark.parametrize(
    ("today", "season"),
    [
        (date(2026, 11, 17), 2026),
        (date(2027, 3, 1), 2026),
        (date(2027, 6, 30), 2026),
        (date(2027, 7, 1), 2027),
    ],
)
def test_the_current_season_turns_over_on_july_first(today: date, season: int) -> None:
    """The finals end in June, so from July the last season is complete."""
    assert current_season(today) == season


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    await upgrade(scratch_conn)
    return scratch_conn


async def _run(
    conn: asyncpg.Connection,
    bdl: RecordedSeasons,
    seasons: list[int],
    *,
    current: int = 2026,
    restart: frozenset[int] = frozenset(),
) -> list[SeasonOutcome]:
    client = recorded_client(bdl)
    try:
        return [
            outcome
            async for outcome in run_backfill(
                conn, client, league="nba", seasons=seasons, restart=restart, current=current
            )
        ]
    finally:
        await client.aclose()


async def _statuses(conn: asyncpg.Connection, season: int) -> set[str]:
    rows = await conn.fetch("SELECT status FROM bdl_backfill_checkpoints WHERE season = $1", season)
    return {row["status"] for row in rows}


@pytest.mark.asyncio
async def test_a_past_season_is_walked_verified_and_done(db: asyncpg.Connection) -> None:
    bdl = RecordedSeasons({2025: season_2025_routes()})

    [outcome] = await _run(db, bdl, [2025])

    assert (outcome.season, outcome.passed, outcome.current) == (2025, True, False)
    assert await _statuses(db, 2025) == {"done"}


@pytest.mark.asyncio
async def test_a_done_season_is_verified_again_without_a_request(db: asyncpg.Connection) -> None:
    await _run(db, RecordedSeasons({2025: season_2025_routes()}), [2025])
    bdl = RecordedSeasons({2025: season_2025_routes()})

    [outcome] = await _run(db, bdl, [2025])

    assert bdl.seen == []
    assert outcome.passed
    assert await _statuses(db, 2025) == {"done"}


@pytest.mark.asyncio
async def test_a_restarted_season_is_walked_again_from_page_one(db: asyncpg.Connection) -> None:
    await _run(db, RecordedSeasons({2025: season_2025_routes()}), [2025])
    bdl = RecordedSeasons({2025: season_2025_routes()})

    [outcome] = await _run(db, bdl, [2025], restart=frozenset({2025}))

    assert [route for _, route in bdl.seen] == list(season_2025_routes())
    assert outcome.passed
    pages = await db.fetchval("SELECT sum(pages_fetched) FROM bdl_backfill_checkpoints WHERE season = 2025")
    assert pages == len(season_2025_routes())


@pytest.mark.asyncio
async def test_the_current_season_is_walked_every_run_and_never_done(db: asyncpg.Connection) -> None:
    """Its games keep being played, so each run walks it from page one and only reports on it."""
    for _ in range(2):
        bdl = RecordedSeasons({2025: season_2025_routes()})
        [outcome] = await _run(db, bdl, [2025], current=2025)
        assert [route for _, route in bdl.seen] == list(season_2025_routes())

    assert (outcome.passed, outcome.current) == (True, True)
    assert await _statuses(db, 2025) == {"in_progress"}


@pytest.mark.asyncio
async def test_a_failed_verification_is_reported_and_the_next_season_still_runs(db: asyncpg.Connection) -> None:
    """A 2000 regular game also comes back on the ist page, so 2000 fails its check. 2025 is independent."""
    routes_2000 = season_2000_routes()
    regular_game = capture("games__season2000_page1.json")["response"]["data"][-1]
    ist = capture("games__season1900_empty.json")
    ist["response"]["data"] = [regular_game]
    routes_2000[("/v1/games", "ist", None)] = ist
    bdl = RecordedSeasons({2000: routes_2000, 2025: season_2025_routes()})

    outcomes = await _run(db, bdl, [2000, 2025])

    assert [(outcome.season, outcome.passed) for outcome in outcomes] == [(2000, False), (2025, True)]
    assert "error" in await _statuses(db, 2000)
    assert await _statuses(db, 2025) == {"done"}


@pytest.mark.asyncio
async def test_a_failed_page_stops_the_run(db: asyncpg.Connection) -> None:
    routes_2000 = season_2000_routes()
    regular = routes_2000[("/v1/games", "regular", None)]
    routes_2000[("/v1/games", "regular", next_cursor(regular))] = capture("games__season2025_ist_page1.json")
    bdl = RecordedSeasons({2000: routes_2000, 2025: season_2025_routes()})

    with pytest.raises(Exception, match="2025"):
        await _run(db, bdl, [2000, 2025])

    assert {season for season, _ in bdl.seen} == {2000}


# ---------------------------------------------------------------------------
# Output and the command line
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_summary_names_the_season_and_its_counts(db: asyncpg.Connection) -> None:
    [outcome] = await _run(db, RecordedSeasons({2025: season_2025_routes()}), [2025])

    line = describe(outcome)

    assert line.startswith("2025-26 done")
    for part in (
        "regular_season 100", "playoffs 85", "play_in 6", "cup_championship 1", "100 lines",
        "points off the score: 0 games", "under 230 minutes: 0 games",
    ):
        assert part in line


def _env(monkeypatch: pytest.MonkeyPatch, dsn: str | None, api_key: str | None) -> None:
    for name, value in ((DSN_ENV, dsn), ("BALLDONTLIE_API_KEY", api_key)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


@pytest.mark.parametrize(
    ("dsn", "api_key", "named"),
    [(None, "key-for-usage-test", DSN_ENV), ("postgresql://u@127.0.0.1:1/x", None, "BALLDONTLIE_API_KEY")],
)
def test_a_missing_variable_is_a_usage_error_that_names_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    dsn: str | None, api_key: str | None, named: str,
) -> None:
    _env(monkeypatch, dsn, api_key)
    with pytest.raises(SystemExit) as exit_info:
        main(["2025", "--dsn-env", DSN_ENV], today=date(2026, 11, 17))
    assert exit_info.value.code == 2
    assert named in capsys.readouterr().err


def test_a_season_after_the_current_one_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, "postgresql://u@127.0.0.1:1/x", "key-for-usage-test")
    with pytest.raises(SystemExit) as exit_info:
        main(["2027", "--dsn-env", DSN_ENV], today=date(2026, 11, 17))
    assert exit_info.value.code == 2
    assert "2027" in capsys.readouterr().err


def test_an_unreachable_database_stops_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, "postgresql://nba:pw-must-not-leak@127.0.0.1:1/nba_history", "key-must-not-leak")

    code = main(["2025", "--dsn-env", DSN_ENV], today=date(2026, 11, 17))

    assert code == 1
    assert capsys.readouterr().err.startswith("backfill stopped: ")


def test_a_failure_that_repeats_the_secrets_prints_neither(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """asyncpg leaves the DSN out of its errors today. This failure repeats both secrets, so the mask is what hides them."""
    dsn = "postgresql://nba:pw-must-not-leak@127.0.0.1:1/nba_history"
    _env(monkeypatch, dsn, "key-must-not-leak")

    async def failing_run(dsn: str, api_key: str, **_: object) -> bool:
        raise RuntimeError(f"could not use {dsn} with key {api_key}")

    monkeypatch.setattr(cli, "_run", failing_run)

    code = main(["2025", "--dsn-env", DSN_ENV], today=date(2026, 11, 17))

    output = capsys.readouterr()
    assert code == 1
    assert output.err.startswith("backfill stopped: RuntimeError: could not use ")
    assert "pw-must-not-leak" not in output.out + output.err
    assert "key-must-not-leak" not in output.out + output.err


def _failing_2000_routes() -> dict:
    """2000-01 with its last regular game also on the ist page, so its check fails."""
    routes = season_2000_routes()
    ist = capture("games__season1900_empty.json")
    ist["response"]["data"] = [capture("games__season2000_page1.json")["response"]["data"][-1]]
    routes[("/v1/games", "ist", None)] = ist
    return routes


async def _migrate(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        await upgrade(conn)
    finally:
        await conn.close()


@pytest.mark.parametrize(
    ("seasons", "states", "code"),
    [
        (["2000", "2025"], ["2000-01 FAILED", "2025-26 done"], 1),
        (["2025"], ["2025-26 done"], 0),
    ],
)
def test_main_prints_each_season_and_exits_by_its_checks(
    scratch_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    seasons: list[str],
    states: list[str],
    code: int,
) -> None:
    """The run reaches the database for real. Only HTTP is answered from the recordings."""
    asyncio.run(_migrate(scratch_dsn))
    made: dict[str, object] = {}

    def recorded(**kwargs: object):
        made.update(kwargs)
        return recorded_client(RecordedSeasons({2000: _failing_2000_routes(), 2025: season_2025_routes()}))

    monkeypatch.setattr(cli, "BdlClient", recorded)
    _env(monkeypatch, scratch_dsn, "key-for-the-run-test")

    exit_code = main([*seasons, "--dsn-env", DSN_ENV, "--raw-dir", str(tmp_path)], today=date(2026, 11, 17))

    lines = capsys.readouterr().out.splitlines()
    assert [line.split(" | ")[0] for line in lines] == states
    assert exit_code == code
    assert (made["api_key"], made["rate_limit_per_min"], made["rate_limit_ceiling"]) == (
        "key-for-the-run-test", 500, 500,
    )
    assert {path.relative_to(tmp_path).parts[2] for path in tmp_path.rglob("*.json.gz")} == {
        season for season in seasons
    }


def test_a_dry_run_needs_no_database_and_writes_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """No DSN is set, so any database use would fail. The pages are still kept."""
    monkeypatch.setattr(cli, "BdlClient", lambda **_: recorded_client(RecordedSeasons({2025: season_2025_routes()})))
    _env(monkeypatch, None, "key-for-the-dry-run")

    code = main(["2025", "--dry-run", "--dsn-env", DSN_ENV, "--raw-dir", str(tmp_path)], today=date(2026, 11, 17))

    [line] = capsys.readouterr().out.splitlines()
    assert code == 0
    assert line.startswith("2025-26 dry run | games regular: 2 pages, 100 rows")
    assert "stats: 2 pages, 100 rows, 0 refused" in line
    assert len(list(tmp_path.rglob("*.json.gz"))) == len(season_2025_routes())
