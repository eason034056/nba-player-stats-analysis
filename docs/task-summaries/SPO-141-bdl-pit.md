# SPO-141 — Migration 005: point-in-time reads, hit rate, and write refusals

- **Ticket:** SPO-141
- **Branch:** `feature/SPO-141-bdl-pit`
- **Base:** `dev` (`3b5ee9c`, which includes `003_bdl_game_gaps.sql` from #106 and #108, #111, #112)
- **Depends on:** 001, 002, 003, 004. Version 005 was free on every branch.

## Summary

`005_bdl_pit.sql` adds the point-in-time read layer on top of 002 and 004: T is tip-off minus 3 hours, poll coverage is 90 minutes, projected-lineup `known_from` is derived from a side table, and hit rate is computed on demand from `prop_actuals`. The 14 tables of 002 are not altered. Bad writes are refused by a unique index and `BEFORE INSERT OR UPDATE` triggers, and `bdl_integrity_problems` stays as the backstop that returns 0 rows while those objects are enforcing.

A push uses one of the last-N games and stays out of the hit-rate denominator. That default from the sketch is settled.

## Changes

| Area | Files | Change |
|---|---|---|
| Schema | `backend/app/migrations/005_bdl_pit.sql` | New. `game_as_of`, `source_refreshes`, `source_covered`, `projected_lineup_sources`, `projected_lineup_versions`, `projected_lineups_asof`, `injuries_asof`, `teammate_availability`, `player_market_results`, `player_hit_rate`, `bdl_integrity_problems`, two plain indexes, unique index `player_game_stats_league_bdl_stat_id_uidx`, and four triggers |
| Tests | `backend/tests/test_migration_005_bdl_pit.py` | New. 28 tests on a scratch database. Skips when no server answers |
| Tests | `backend/tests/test_migration_runner.py`, `test_migration_001_baseline.py` | The shipped list is `001` through `005`. A database that recorded 004 before 003 still receives 003, and 005 with it |
| Docs | `docs/decisions/SPO-138/data-model.md` | New §12. Read notes for `players.position` and `game_lineups.starter` live here, not as comments on 002 |
| Docs | `docs/decisions/SPO-138/data-model-er.drawio.svg` | 005 objects in orange. No PNG image fallback |

## Why

- **003 does not touch the tables 005 reads.** `003_bdl_game_gaps.sql` creates `bdl_games_with_gaps` and replaces the view `player_game_log`. It has no `ALTER` of `games`, `player_game_stats`, `projected_lineups`, `projected_lineup_players`, `injury_snapshots`, `player_prop_snapshots`, or `prop_markets`.
- **The 14 tables of 002 stay as they are.** 005 has no `ALTER TABLE`, no `DROP`, and no `COMMENT ON` for a 002 object. Columns, types, nullability, constraints, and the `books` / `prop_markets` seeds match a database that stopped at 004. The new indexes and triggers are the only additions on those tables.
- **Refusal and the view are the same four problems.** The unique index refuses a second `(league, bdl_stat_id)`. `bdl_stat_id` is `NOT NULL` in 002, so the index has no `WHERE`. Triggers refuse `games_same_team`, `stat_team_not_in_game` (on the stat row, and on a game update that would orphan one), and `prop_market_type_mismatch`. The prop rule is the view's rule: `(settle_rule = 'sum')` must equal `(market_type = 'over_under')`. A points milestone cannot replace the opening over/under row. `double_double` and `triple_double` must be `milestone`. The props adapter copies a milestone only for `player_double_double` and does not map `triple_double`; the database still follows the view.
- **A missing team stays a foreign key.** If `bdl_team_id` is not in `teams`, the stat trigger does not raise. 002's foreign key still rejects the row, and a stats page that fails part way still rolls back.
- **T, coverage, and `known_from`.** `game_as_of` defaults to 3 hours. A NULL `datetime_utc` is 00:00 America/New_York on `games.date`, and the hours parameter is ignored in that case. `source_covered` is false before the first complete refresh, when that refresh is older than 90 minutes, and when the only runs are incomplete. A lineup with no side row is `poll`, so `known_from` is `first_seen_at` and the row is visible when `first_seen_at <= T`. `backfill_final` makes `known_from` the BDL `updated_at`. Equality with T is inside the window.
- **Hit rate is not stored.** DNP is `void` and is left out. A NULL needed stat is `unknown` and is left out. A push stays in the last-N window and out of the denominator. A window of only pushes has an empty denominator, so `hit_rate` is NULL. A played zero is `under`. `current_projected_lineups` and `prop_actuals` are reused, not redefined.
- **Last-N is settled.** A push uses one of the N games.

## Tests / Verification

Throwaway PostgreSQL 16 on this machine (`127.0.0.1:5432`, database `test`). Not port 5434.

- **005:** `pytest tests/test_migration_005_bdl_pit.py` → 28 passed.
- **Migrations 001–005:** `pytest tests/test_migration_*.py` → 112 passed.
- **Full backend suite:** `pytest -q` → 1986 passed, 37 skipped, 6 xfailed, 0 failed. `TestVpcIdConsole` skipped here (3 tests); those tests are not from this PR.
- **Mutation check:**
  - Counting a push in the denominator made the line-24 hit rate `0.3333` instead of `0.5`. `test_hit_rate_keeps_a_push_out_of_the_denominator` failed. Restored. The 005 file passed again.
  - Changing `known_from <= p_as_of` to `<` made `test_known_from_equal_to_t_is_visible_and_one_second_later_is_not` return no player instead of player 10. Restored. The 005 file passed again.
  - `COMMENT ON TABLE games` and `COMMENT ON COLUMN players.position` each change the `pg_description` snapshot that `test_002_tables_keep_columns_types_and_constraints` compares. Both were applied on a throwaway database and then removed. 005 itself adds no comment on a 002 object.
- **Frontend:** not touched. WNBA rows are still accepted (`game_as_of` on a WNBA game).

## Follow-ups

- [ ] Writers (projected lineups, injuries, live odds, closing odds, live props, closing props) insert `source_refreshes` from their first run.
- [ ] The 2026-27 projected backfill writes `projected_lineups` plus a `backfill_final` row in `projected_lineup_sources` in the same transaction.
- [ ] The backfill verifier asserts `bdl_integrity_problems` returns 0 rows for the season it walked.
- [ ] 138l's Python teammate-out path stays separate. `teammate_availability` is the SQL path for API splits.

## Progress notes (for the docs PR)

- SPO-141: `005_bdl_pit` adds point-in-time reads, on-demand hit rate, and database refusals for a same-team game, a duplicate stat id, a stat team outside the game, and a prop market type that does not match its settle rule. The integrity view stays as the backstop. The 14 tables of 002 are unchanged. A push uses one last-N slot.

---

**Ticket**: SPO-141
**Branch**: `feature/SPO-141-bdl-pit`
**Task summary**: `docs/task-summaries/SPO-141-bdl-pit.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
