# SPO-138i — Read layer: predictions table and four views

- **Ticket:** SPO-138i (provisional number; Paperclip was offline, so the ticket is not created yet)
- **Branch:** `feature/SPO-138i-read-layer`
- **Base:** `dev`
- **Depends on:** SPO-138b (`002_bdl_core`), already in `dev`

## Summary

This PR adds `004_read_layer.sql`: one table and four views on top of the 002 schema. It is 004 because SPO-138g's `003_bdl_game_gaps.sql` (not yet in `dev`) holds 003. A database that records 003 would otherwise skip this file, and the runner refuses two files with one version. No 002 table changes, and nothing writes `predictions` yet.

1. `predictions` stores one row per model run for a game, player, and market. Triggers set `predicted_at` to the transaction start time, refuse an INSERT whose wall clock is at or after tip-off, and refuse UPDATE and DELETE. No line, book, or price is stored.
2. `prop_actuals` gives the result of all 12 markets for each stat line of a final game, using `prop_markets.stat_columns` and `settle_rule`. It reads no odds.
3. `current_predictions`, `current_injuries`, and `current_projected_lineups` give the newest row for the frontend.
4. The ER diagram and `data-model.md` are updated, and a decision file records the read layer, the model's input rules, and the injury-status rule.

## Changes

| Area | Files | Change |
|---|---|---|
| Schema | `backend/app/migrations/004_read_layer.sql` | New. `predictions` with two triggers and an index; views `current_predictions`, `prop_actuals`, `current_injuries`, `current_projected_lineups` |
| Tests | `backend/tests/test_migration_004_read_layer.py` | New. 17 tests on a scratch database |
| Tests | `backend/tests/test_spo138i_qa_read_layer.py` | A post-tip INSERT inside a transaction opened before tip-off is refused; a double-double needs two of the five categories |
| Tests | `backend/tests/test_migration_runner.py`, `test_migration_001_baseline.py` | The shipped migration list is now `["001", "002", "004"]` |
| Docs | `docs/decisions/SPO-138/decision_20261120_read-layer-and-ml-inputs.md` | New. Decisions, rejected alternatives, tradeoffs |
| Docs | `docs/decisions/SPO-138/data-model.md` | §1.7 `status` stores BDL's word (Doubtful kept); new §11 for 004. The `predictions` row says the tip-off check is the wall clock at the INSERT |
| Docs | `docs/decisions/SPO-138/data-model-er.drawio.svg` | The new table, the four views, and the planned rules (orange border) |

## Why

- **The 002 tables stay as they are.** They already record when each fact was known. What was missing was one shared way to read "newest" and "settled".
- **The database sets `predicted_at`.** It is the transaction start time, so a writer that sends an older time cannot backfill one. The tip-off check uses the wall clock at the INSERT, so a stored row proves the INSERT itself ran before tip-off.
- **`predictions` carries no prop odds.** The model must not see the line, and each row must stay readable after live odds are downsampled at 14 days.
- **`prop_actuals` covers final games only, and NULL is never guessed.** A live game is not a result. A `dnp` line is void, and a missing component makes only the markets that need it NULL.
- **`current_injuries` picks the newest row before it filters on `listed`.** Filtering first would show an older Out for a player whose newest row says he left the list.

## Tests / Verification

- **004:** `pytest tests/test_migration_004_read_layer.py tests/test_spo138i_qa_read_layer.py` → 19 passed (17 plus the two QA checks), on PostgreSQL 16.
- **Mutation check:** two rules were broken on purpose and the tests failed both times. Filtering `listed` before picking the newest row failed the injury test. Removing `NEW.predicted_at := now()` failed the insert-time, after-tip-off, and latest-run tests. Putting the tip-off check back on `NEW.predicted_at` made `test_an_insert_after_tip_off_is_refused_even_in_a_long_transaction` fail (`DID NOT RAISE`); `test_a_replay_inside_one_transaction_keeps_one_row` still kept one row.
- **Migrations and pool:** `test_migration_runner.py`, `test_migration_001_baseline.py`, `test_migration_002_bdl_core.py`, `test_migration_004_read_layer.py`, `test_db.py` → 113 passed.
- **Full backend suite** (`pytest --tb=line -q`, PostgreSQL 16, Redis, `fakeredis` installed): 1855 passed, 34 skipped, 7 xfailed.
- **Diagram:** exported with the draw.io CLI with the diagram embedded. The CLI's PNG fallbacks were replaced with text, which took the file from 4.2 MB to 125 KB. Rendered with Quick Look to check that every label shows.
- **Frontend:** not touched.

## Follow-ups

- [ ] SPO-138j: the dataset module (as-of reads, `info_source`, `team_absences`).
- [ ] SPO-135i: Redis keeps Doubtful (supersedes SPO-135h).
- [ ] The injury writer stores BDL's word in `injury_snapshots.status` (`data-model.md` §1.7).
- [ ] A writer for `predictions`, once the model exists.

## Progress notes (for the docs PR)

- SPO-138i: `004_read_layer` adds `predictions` and the read views for the frontend and the player-props model.
