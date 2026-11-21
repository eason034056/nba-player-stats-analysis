# SPO-138g — Leave BDL's broken games out of `player_game_log`

- **Ticket:** SPO-138g, the last of SPO-138a–g (the NBA history backfill, one layer per PR)
- **Branch:** `feature/SPO-138g-bdl-game-gaps`
- **Base:** `dev`
- **Depends on:** SPO-138f (the backfill command), merged into `dev`.

## Summary

In 50 final games, BDL's lines do not add up to the game. Migration `003` adds `bdl_games_with_gaps`, a view that computes the list from the stored lines. `player_game_log` leaves out every line of a listed game. Verify reads the same view, so the rule lives in one place.

## Changes

| Area | Files | Change |
|---|---|---|
| Schema | `backend/app/migrations/003_bdl_game_gaps.sql` | New. `bdl_games_with_gaps`; `player_game_log` redefined with the same columns, in the same order, as in `002`, without listed games |
| Backfill | `backend/app/backfill/verify.py` | Points and minutes gaps read from the view; its own copy of the SQL removed |
| Tests | `test_migration_003_bdl_game_gaps.py` (new), `test_migration_runner.py`, `test_migration_001_baseline.py` | The view on recorded games; a corrected game comes back; the runner ships `001` to `004`; `003` applies on a database that already ran `004` |
| Docs | `docs/decisions/SPO-138/data-model.md` | §1.6 upstream gaps, `player_game_log`, §4 `003` and `004`, §9 Eason's decision |

## Why

For each final game, verify compares each team's player points with its score, and the team's player minutes with 240. Fifty games fail:

| Kind | Games | What is wrong |
|---|---|---|
| Minutes field, 2005-06 and 2006-07 | 30 | Points match; `min` is wrong (for example, 37 points in `"0"` minutes) |
| Four overtimes | 5 | The game object has only `ot1`–`ot3`, so its score stops tied after the third overtime. The lines are right |
| Line left out, 2018-19 | 1 | A team is 4 points and about 4 minutes short |
| 2024-02-01 to 2024-03-08 | 14 | Points short, minutes short, or both |

- **The errors are BDL's.**
  - A scan of the raw pages, with no app code in the path, finds the same 50 games.
  - Every stored minute and point in them equals the raw value.
  - Seven of them were fetched again by game id, a path the walk never used, and returned the same lines. They are recorded as fixtures (SPO-138a).
- **They are left out whole, on the read side (Eason, 2026-11-19).**
  - The lines stay in `player_game_stats` as BDL sent them; `player_game_log` leaves out the 1,362 lines of listed games.
  - The list is computed, not stored. When BDL corrects a game and its season is walked again, the game comes back.
  - Two alternatives were rejected. Leaving out only the wrong field would make each column null for its own reason. Not storing the games would break the stored-equals-fetched check, and they would come back on the next walk.
- **`season` is a grouping column of the view**, so verify's per-season read filters before it sums: 0.04 s for a season.
- **The data is not corrected from Basketball-Reference.** Its terms forbid using its content to train models, and these rows feed the ML work.
- **`003` reached `dev` after `004`** (SPO-138i took 004 because this branch already held 003). A database that recorded `004` first still gets `003`: the runner applies every version that is not in `schema_migrations`, and `004` reads neither view. A test applies `001`, `002`, and `004`, then the shipped files, and expects `003` alone.
- **Cost:** the anti-join adds about 0.1 s to one player's last 10 games and 0.2 s to a full scan. That is why it is a plain view, not a materialized one, which would need a refresh after every write.

## Tests / Verification

The test runs use a throwaway `postgres:16-alpine`, with `DATABASE_URL` set explicitly to it.

- **Full backend suite** on this branch: `cd backend && DATABASE_URL=<throwaway db> python -m pytest -q` → 6 failed, 1960 passed, 30 skipped, 7 xfailed. The 6 failures are Terraform console tests: 3 in `test_spo132b_optional_vpc.py::TestVpcIdConsole` and 3 in `test_spo140_terraform_environments.py::TestNamePrefixConsole`. They fail the same way on a clean `origin/dev` checkout, because the local Terraform has no provider plugins installed (`terraform init` was not run). They are not from this PR.
- **Database tests** on this branch: `pytest tests/test_backfill_*.py tests/test_migration_*.py tests/test_bdl_*.py tests/test_db.py` → 296 passed, 5 skipped. The skips are the live tests.
- **Mutation checks:**
  - The `003` view: 4 of 4 mutants caught (the 230 threshold, either team's points, either team's minutes, and the anti-join).
  - Version order: a runner that skips versions below the highest applied one fails only `test_003_applies_on_a_database_that_already_ran_004`.
- **Applied to the local `nba_history`** with the runner. `player_game_log` has 884,511 rows: 885,873 minus the 1,362 left out. Verify still lists the same 50 games, in 1.8 s for all 27 seasons.
- **Fabrication scan:** PASS, checked by hand. The view is tested on games recorded by game id. The re-walk test changes a copy of a recorded page.
- **Frontend:** not touched.

## Follow-ups

- [ ] Send BDL the report on the 50 games. When BDL corrects them, walk the affected seasons again with `--restart-season`.
- [ ] `002` to `004` on RDS, after `001_baseline.sql` is stamped there.
- [ ] Turn `bdl_games_with_gaps` into a materialized view if a product read of `player_game_log` needs to be under 0.1 s.

## Progress notes (for the docs PR)

- SPO-138g: 50 games where BDL's data does not add up are left out of `player_game_log` (a computed view, so corrected games come back after a re-walk). A report for BDL is drafted.

---

**Ticket**: SPO-138g
**Branch**: `feature/SPO-138g-bdl-game-gaps`
**Task summary**: `docs/task-summaries/SPO-138g-bdl-game-gaps.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
