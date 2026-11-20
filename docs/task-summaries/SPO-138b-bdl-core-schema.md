# SPO-138b — BDL core schema (`002_bdl_core.sql`) and the migration runner

- **Ticket:** SPO-138b, the second of SPO-138a–g (the NBA history backfill, one layer per PR)
- **Branch:** `feature/SPO-138b-bdl-core-schema`
- **Base:** `dev`
- **Depends on:** nothing. SPO-138a is independent of this PR; either can merge first.

## Summary

This PR adds the new history schema, keyed by BDL ids, and a runner that applies it. Nothing writes these tables yet (the writer is SPO-138c), and RDS is not touched.

1. `002_bdl_core.sql`: 14 tables, plus the `player_game_log` view, which rebuilds the row that today's CSV readers expect.
2. `python -m app.migrations upgrade` applies `NNN_*.sql` files in order. Each file commits in one transaction with its `schema_migrations` row.
3. `docs/decisions/SPO-138/data-model.md` and the ER diagram record why each table has its shape and what Eason decided.

## Changes

| Area | Files | Change |
|---|---|---|
| Schema | `backend/app/migrations/002_bdl_core.sql` | New. `books`, `seasons`, `teams`, `players`, `games`, `player_game_stats`, `injury_snapshots`, `game_lineups`, `projected_lineups`, `projected_lineup_players`, `prop_markets`, `game_odds_snapshots`, `player_prop_snapshots`, `bdl_backfill_checkpoints`; the `player_game_log` view |
| Migrations | `backend/app/migrations/runner.py`, `__main__.py`, `__init__.py` | New. `discover` and `upgrade`; `python -m app.migrations upgrade --dsn-env NAME` |
| Tests | `backend/tests/conftest.py`, `test_migration_002_bdl_core.py`, `test_migration_runner.py` | New. Each test gets a scratch database and skips when no Postgres answers |
| Docs | `docs/decisions/SPO-138/data-model.md`, `data-model-er.drawio.svg` | New. The SPO-138 data model and its decisions |

## Why

- **Fact tables store ids only.** `player_game_log` joins names, abbreviations, and home/away back in. When BDL corrects a name, no stale copy is left behind.
- **`league` has no default.** BDL's NBA and WNBA ids overlap. A write that forgets the league fails instead of landing as NBA.
- **`player_game_stats` copies `season` and `date`** to answer "a player's last N games before a date". A composite FK with `ON UPDATE CASCADE` ties the copies to `games`. A wrong date is rejected, and a rescheduled game moves its lines with it. A wrong date would let a backtest see the future.
- **Every game type is stored under its product name:** `regular_season`, `playoffs`, `play_in`, `cup_championship`, the tokens in `CANONICAL_GAME_TYPES`. The CHECK refuses BDL's own names and preseason, so a value that was never translated fails the insert. The reader's query decides whether the play-in counts with the regular season (Q7).
- **Checkpoints count what BDL sent.** `bdl_backfill_checkpoints` keeps, for each shard, the cursor and the pages and rows fetched, dropped, and rejected. A season resumed across runs can then still be checked against what BDL sent. Dropped and rejected rows are not stored, so the tables cannot recount them.
- **The injury, lineup, and odds tables are in `002` with their rules** (`data-model.md` §1.7–1.9). Nothing writes them yet.
- **Runner: each file commits in one transaction with its row.** A crash between the two cannot leave a file applied but unrecorded. A badly named file or a duplicate version number stops the run before any SQL. The DSN comes from the variable that `--dsn-env` names, and errors are printed with the password masked.

`data-model.md` covers the whole SPO-138 design, including parts that land in other PRs: stats rows in SPO-138a, and BDL's data gaps in SPO-138e and g.

## Tests / Verification

- **Full backend suite** on this branch: `cd backend && env -u DATABASE_URL .venv/bin/python -m pytest -q` → 3 failed, 1610 passed, 112 skipped, 6 xfailed, in 46.96s. The 3 failures are `tests/test_spo132b_optional_vpc.py::TestVpcIdConsole`, which fail the same way on `origin/dev` in the same checkout (pre-existing, not from this PR).
- **Database tests** on this branch: `DATABASE_URL=<local postgres:16 maintenance db> pytest tests/test_migration_* tests/test_backfill_* tests/test_bdl_*` (here: the 002 and runner tests plus the existing BDL client tests) → 78 passed, 1 skipped, in 7.30s (the skips are the live tests)
- **Mutation check:** without the per-file transaction, `test_file_and_its_record_commit_together` fails. That test uses a trap trigger, because a test that only feeds in a failing file still passes when the transaction is removed.
- **Fabrication scan:** PASS, checked by hand. The injury, lineup, prop, and odds rows in the 002 tests come from recordings already in `dev`.
- **Frontend:** not touched.

## Follow-ups

- [ ] `001_baseline.sql`, stamped on RDS, then `002` on RDS.
- [ ] SPO-138c writes games and stats. Writers for opening props, opening odds, injuries, and lineups come later (rules in `data-model.md` §1.7–1.9). A recorded successful lineups response is still missing.
- [ ] CLV opening/closing definitions.

## Progress notes (for the docs PR)

- SPO-138b: the BDL-keyed history schema (`002_bdl_core.sql`) and `python -m app.migrations upgrade`, applied only to local databases so far.

---

**Ticket**: SPO-138b
**Branch**: `feature/SPO-138b-bdl-core-schema`
**Task summary**: `docs/task-summaries/SPO-138b-bdl-core-schema.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
