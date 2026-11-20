# SPO-138b — BDL core schema and the migration runner

- **Ticket:** SPO-138b, the second of SPO-138a–g (the NBA history backfill, one layer per PR)
- **Branch:** `feature/SPO-138b-bdl-core-schema`
- **Base:** `dev`
- **Depends on:** nothing. SPO-138a is independent of this PR; either can merge first.

## Summary

This PR adds the history schema, keyed by BDL ids, and the runner that applies it. Nothing writes the new tables yet (the writer is SPO-138c), and RDS is not touched.

1. `001_baseline.sql` is the text of `SCHEMA_SQL` in `backend/app/services/db.py`. A blank database gets the six legacy tables. A database that already ran `SCHEMA_SQL` (RDS today) does not change.
2. `002_bdl_core.sql`: 14 tables, plus the `player_game_log` view, which rebuilds the row that today's CSV readers expect.
3. `python -m app.migrations upgrade` applies `NNN_*.sql` in order. Each file commits in one transaction with its `schema_migrations` row. A session advisory lock covers discover and apply, so two containers starting together apply each file once.
4. `backend/docker-entrypoint.sh` runs that upgrade, then execs uvicorn. `DatabaseService.init()` no longer executes `SCHEMA_SQL`. It opens the pool and checks `schema_migrations` is at head. A bare `uvicorn` start that skips the entrypoint logs one ERROR naming the missing versions and `python -m app.migrations upgrade`. `DATABASE_REQUIRED=true` still aborts startup, with that same message.
5. `langsmith==0.14.17` is pinned next to `langchain-openai` in the three requirements files. langsmith 0.15.x fails to import under pydantic 2.8.0, so pytest exited before any test.

## Changes

| Area | Files | Change |
|---|---|---|
| Schema | `backend/app/migrations/001_baseline.sql` | New. The `SCHEMA_SQL` body. `IF NOT EXISTS` and guarded `ALTER`s, so a second apply is a no-op |
| Schema | `backend/app/migrations/002_bdl_core.sql` | New. `books`, `seasons`, `teams`, `players`, `games`, `player_game_stats`, `injury_snapshots`, `game_lineups`, `projected_lineups`, `projected_lineup_players`, `prop_markets`, `game_odds_snapshots`, `player_prop_snapshots`, `bdl_backfill_checkpoints`; the `player_game_log` view |
| Migrations | `backend/app/migrations/runner.py`, `__main__.py`, `__init__.py` | `discover` and `upgrade`. The upgrade holds `pg_advisory_lock(138138001)` across discover and apply |
| Boot | `backend/docker-entrypoint.sh`, `backend/Dockerfile`, `docker-compose.yml` | The image entrypoint upgrades, then execs the command. The root compose file does not set `command`, so it keeps that entrypoint. `deploy/docker-compose.prod.yml` is not on `dev` |
| Pool | `backend/app/services/db.py`, `backend/app/main.py` | `init()` confirms head and does not execute `SCHEMA_SQL`. Not-at-head logs one ERROR with the missing versions and `python -m app.migrations upgrade` |
| Dependencies | `backend/requirements.txt`, `scripts/agents/requirements_agents.txt`, `nba_lineup_rag/requirements.txt` | `langsmith==0.14.17` immediately after each file's `langchain-openai` line |
| Tests | `backend/tests/conftest.py`, `test_migration_001_baseline.py`, `test_migration_002_bdl_core.py`, `test_migration_runner.py`, `test_docker_entrypoint.py` | Scratch databases. When `DATABASE_URL` is set, the session fixture applies the shipped files to that database before the suite |
| Docs | `docs/decisions/SPO-138/data-model.md`, `data-model-er.drawio.svg` | The SPO-138 data model and its decisions |

## Why

- **001 is applied, not stamped.** `SCHEMA_SQL` is already idempotent, and today's image runs it on every boot, including RDS. `001_baseline.sql` is that text, so applying it on RDS is the same operation the database already survives. A `stamp 001` path would skip the SPO-35 and SPO-117 blocks. Those blocks are what repair a database that still has the old unique keys. The test applies `001` after `SCHEMA_SQL` and compares `information_schema` plus `pg_dump --schema-only`. The two dumps match, and `odds_line_snapshots.line` stays nullable and stays in `odds_line_snapshots_book_line_key`.
- **`init()` stops running `SCHEMA_SQL`.** The design says the foundation image must migrate before uvicorn and stop executing `SCHEMA_SQL`, in the same image. Otherwise a later `DROP TABLE` is recreated empty on the next boot. `init()` opens the pool and, when a shipped version is missing, logs one error and leaves the pool unset. The line names the versions and `python -m app.migrations upgrade`. The CLI reads `DATABASE_URL` by default, so the line has no `--dsn-env` flag and no DSN. `DATABASE_REQUIRED=true` still fails boot, and the exception text is that same line, not a second log. A missing `schema_migrations` table (RDS built only by `SCHEMA_SQL`) is reported as every shipped version missing. The README local-dev steps run the upgrade before uvicorn. Tests that open the CI database get the same tables from the session fixture.
- **The entrypoint is a script, not `&&` in a YAML list.** A YAML list does not treat `&&` as a shell operator. `docker-entrypoint.sh` uses `set -e`, runs `python -m app.migrations upgrade`, then `exec`s the command. The Dockerfile sets `ENTRYPOINT` to that script and leaves uvicorn as `CMD`. Replacing only `CMD` (for example to add `--proxy-headers`) still migrates first. Replacing the entrypoint skips the upgrade.
- **The lock is session-scoped.** Each file already commits with its `schema_migrations` row, so a crash rolls that file back. Without a lock, two starters can both read "not applied" and both run the file. The second then fails on the primary key. The lock makes the second wait, see the recorded versions, and apply nothing. A dead connection drops the lock.
- **Fact tables store ids only.** `player_game_log` joins names, abbreviations, and home/away back in. When BDL corrects a name, no stale copy is left behind.
- **`league` has no default.** BDL's NBA and WNBA ids overlap. A write that forgets the league fails instead of landing as NBA.
- **`player_game_stats` copies `season` and `date`** to answer "a player's last N games before a date". A composite FK with `ON UPDATE CASCADE` ties the copies to `games`. A wrong date is rejected, and a rescheduled game moves its lines with it. A wrong date would let a backtest see the future.
- **Every game type is stored under its product name:** `regular_season`, `playoffs`, `play_in`, `cup_championship`, the tokens in `CANONICAL_GAME_TYPES`. The CHECK refuses BDL's own names and preseason, so a value that was never translated fails the insert. The reader's query decides whether the play-in counts with the regular season (Q7).
- **Checkpoints count what BDL sent.** `bdl_backfill_checkpoints` keeps, for each shard, the cursor and the pages and rows fetched, dropped, and rejected. A season resumed across runs can then still be checked against what BDL sent. Dropped and rejected rows are not stored, so the tables cannot recount them.
- **The injury, lineup, and odds tables are in `002` with their rules** (`data-model.md` §1.7–1.9). Nothing writes them yet.
- **The DSN stays out of the output.** The CLI reads it from the variable named by `--dsn-env`. Errors are printed with the password masked.

`data-model.md` covers the whole SPO-138 design, including parts that land in other PRs: stats rows in SPO-138a, and BDL's data gaps in SPO-138e and g.

## Tests / Verification

- **langsmith:** under `pydantic==2.8.0`, `import langsmith.pytest_plugin` raises `NameError: name 'FeedbackConfigSchema' is not defined` on langsmith 0.15.0 and 0.15.1. `langsmith==0.14.17` imports. The same two lines are in PR #94's three requirements files.
- **Full backend suite** with `DATABASE_URL` pointing at local Postgres 16: `cd backend && .venv/bin/python -m pytest -q` → 1712 passed, 28 skipped, 7 xfailed, in 75.59s. The skips are live API tests (`RUN_INTEGRATION` unset), one docker-verify test (no docker), and three terraform tests (terraform not on PATH). None of the migration tests were in the skip list. `test_init_logs_missing_versions_once` checks the one ERROR line (missing versions, `python -m app.migrations upgrade`, no DSN) for a behind schema and for a missing `schema_migrations` table. `test_init_at_head_does_not_log_a_schema_error` checks a database at head.
- **001, runner, 002, entrypoint:** `pytest tests/test_migration_001_baseline.py tests/test_migration_runner.py tests/test_migration_002_bdl_core.py tests/test_docker_entrypoint.py -q` → 67 passed, 0 skipped, in 7.60s. That includes the empty-database `pg_dump --schema-only` match, the no-op apply after `SCHEMA_SQL`, 001 then 002 then a second upgrade, two concurrent upgrades, and the entrypoint refusing to start uvicorn when the upgrade fails.
- **Walk-forward files** after `pip install -r backend/requirements.txt -r scripts/agents/requirements_agents.txt` (langsmith 0.14.17, pydantic 2.8.0): 29 passed, in 21.75s.
- **Mutation check:** without the per-file transaction, `test_file_and_its_record_commit_together` fails. That test uses a trap trigger, because a test that only feeds in a failing file still passes when the transaction is removed.
- **Fabrication scan:** PASS, checked by hand. The injury, lineup, prop, and odds rows in the 002 tests come from recordings already in `dev`.
- **Frontend:** not touched.

## Follow-ups

- [ ] SPO-138c writes games and stats. Writers for opening props, opening odds, injuries, and lineups come later (rules in `data-model.md` §1.7–1.9). A recorded successful lineups response is still missing.
- [ ] CLV opening/closing definitions.
- [ ] PR #64's `deploy/docker-compose.prod.yml` is not on `dev`. When that file lands, it must keep `backend/docker-entrypoint.sh` as the entrypoint. A YAML list that starts at uvicorn skips the upgrade. Replacing only `CMD`, including the `--proxy-headers` flags, still runs the upgrade first.

## Progress notes (for the docs PR)

- SPO-138b: `001_baseline.sql` plus `002_bdl_core.sql`, `python -m app.migrations upgrade` before uvicorn, and `langsmith==0.14.17`. Applied only to local databases so far.

---

**Ticket**: SPO-138b
**Branch**: `feature/SPO-138b-bdl-core-schema`
**Task summary**: `docs/task-summaries/SPO-138b-bdl-core-schema.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
