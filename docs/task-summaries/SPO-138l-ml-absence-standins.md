# SPO-138l — ML dataset: teammate absence, starter stand-in, info_source

- **Ticket:** SPO-138l
- **Base:** `dev` (`3b5ee9c`, SPO-142b)

## Summary

The dataset row now carries NBA teammate absence, a starter flag, and the player's own injury word. Every read uses the same T as SPO-138j and SPO-138k: tip minus `--hours-before-tip` (default 3), or 00:00 America/New_York on the game date when the tip is NULL. That midnight is not shifted again. This change does not build a second cutoff.

`team_absences` is the one function for a training row and for a live team-game. The live loader fetches that team's last 10 earlier games, each candidate's latest earlier game, the target box score, and those players' injury rows. It does not hold the rest of the history, and the injury SQL does not filter `snapshot_at`. Python applies T.

A rotation player played at least 3 of the team's last 10 games dated before the target and averaged at least 15:00 in the games he played among them. Exactly 3 of 10 and exactly 900 seconds are in. 2 of 10 and 899 seconds are out. A game on the target date does not count. A player whose latest earlier game is for another team is not this team's rotation player.

`source='actual'` is the box-score stand-in: a rotation player with no target row, or a DNP row, has `p_out` 1. A player who played is not absent. `source='reported'` keeps the newest injury row with `snapshot_at <= T`, then applies `listed`. A newer `listed = false` row at or before T removes him. The scale is Out 1, Doubtful 0.75, Questionable 0.5, Day-To-Day 0.25, Probable 0.1, from the shared injury-status constants. An unknown word or a blank status is counted and is not given a probability.

Minutes and per-market shares are `p_out`-weighted and use earlier games only. The row's own player is left out of his missing totals. He is not left out of the opponent's minutes. `source_covered` is not on this branch, so coverage is `unknown` and a pregame row stores NULL, not 0. `source='actual'` may store numbers, and those rows are `info_source='standin'`. `game_lineups.starter` (season 2025 and later) is also a stand-in. A projected five with `first_seen_at <= T` stays pregame. Final scores count `info_source='pregame'` only. The player's own status is NULL on a stand-in row.

NBA only. `team_absences` rejects any other league. The existing `--league` choice is left as it is. A non-NBA export keeps the older columns and leaves the new ones empty. WNBA removal is SPO-145 and is not started here.

## Changes

| Area | Files | Change |
|---|---|---|
| Absence | `backend/app/ml/absence.py` | Rotation rule, `team_absences`, weighted minutes and shares, starter choice, `rows_for_final_scores`. |
| Sources | `backend/app/ml/sources.py` | Injury and lineup names live on `ABSENCE_SOURCES`. They are not added to `feature_source_names()`. |
| Load | `backend/app/ml/load.py` | Season reads for injuries, `game_lineups`, and projected starters. `injury_coverage_status` checks `to_regclass('public.source_covered')` and stays `unknown`. `load_team_absence_inputs` is the live bundle. `games` now also selects `visitor_team_id`. |
| Export | `backend/app/ml/build_dataset.py` | Same T. Default `absence_source='reported'` and unknown coverage, so a default row stays `pregame` and the new features stay NULL. Metadata adds coverage, stand-in counts, and the new columns. `feature_sources` is unchanged. |
| Tests | `backend/tests/test_spo138l_ml_absence.py`, `test_spo138l_ml_absence_db.py` | Rotation boundaries, T, listed order, stand-in, and one function called from both the live bundle and the training history. |

Columns added, after the opening-odds columns and before the labels: `team_missing_minutes`, `team_missing_share_<market>` for each catalog market, `opp_missing_minutes`, `is_starter`, `player_injury_status`.

Double-double and triple-double have no continuous stat. Their share uses the counting columns those markets already read (`pts`, `reb`, `ast`, `stl`, `blk`). It is not a share of double-double events. A NULL component on a played row makes that share NULL. A team total of 0 does the same. An empty absence list is 0 only when numbers are allowed.

`metadata["info_source"]` stays `pregame` when every kept row is pregame, `standin` when every kept row is a stand-in, and `mixed` when both are present. `pregame_row_count` is the count `rows_for_final_scores` returns. The CLI has no new flag. The default export does not switch rows to `standin`.

## Why

- **One function, one T.** Training and live both call `team_absences`. The live SQL stops at the last 10 team games plus each candidate's latest earlier row, so a trade is visible without loading every season. T stays in Python, including the NULL-tip midnight, so `--hours-before-tip` cannot drift from a second predicate in SQL.
- **Newest snapshot, then listed.** That is the `current_injuries` order. Filtering `listed` first would revive an older Out after a removal.
- **Unknown is not healthy.** Migration 005 is not on `dev`. An empty `injury_snapshots` table is missing coverage. Pregame features stay NULL so a later reader does not treat 0 as a complete report. `team_absences` still returns the pairs it can see.
- **Stand-in is labeled.** The target box score and `game_lineups.starter` are not known at T. Those rows are `standin`, and the player's own status is NULL there. Projected starters with `first_seen_at <= T` stay pregame. A backfill whose `first_seen_at` is after T stays invisible. `projected_lineup_sources` is not added.
- **The 138j allow-list stays put.** Injury and lineup tables are absence sources. `metadata["feature_sources"]` is still `games`, `player_game_stats`, `game_odds_snapshots`. `player_prop_snapshots` stays rejected.
- **NBA only.** New absence, stand-in, `info_source`, and rotation behavior is NBA. Existing league selection on the exporter is untouched. Deleting WNBA code is a different ticket.

## Tests

```
cd backend
DATABASE_URL="" .venv/bin/python -m pytest tests/test_spo138l_ml_absence.py tests/test_spo138j_ml_dataset.py tests/test_spo138k_ml_game_odds.py -q
DATABASE_URL=postgresql://test:test@127.0.0.1:5441/test .venv/bin/python -m pytest tests/test_spo138l_ml_absence_db.py tests/test_spo138j_ml_dataset_db.py tests/test_spo138k_ml_game_odds_db.py tests/test_spo138j_qa_review.py tests/test_spo138j_qa_review2.py -q
```

Throwaway PostgreSQL 16.15 on `127.0.0.1:5441`. Not `127.0.0.1:5434`. The URL above is that local server. `ruff check` with `--select E9,F63,F7,F82` passed on the touched Python files.

- In-memory, `DATABASE_URL=""`: 54 passed. 22 are new. 20 are the SPO-138j file. 12 are the SPO-138k file. Rotation: 3 of 10 at 900 seconds in, 2 of 10 out, 899 seconds out, games older than the last 10 out, a trade out, a same-day game excluded. Actual: missing row and DNP are `p_out` 1, a player who played is not absent. Reported: the row at T is kept, the row one second after T is ignored, a removal one second after T does not hide the Out, `listed = false` at T removes the older Out, each status maps, `GTD` and a blank word are counted and not guessed. Weighted minutes and the points share use earlier games only. A NULL component does not become 0. Unknown coverage writes neither 0 nor a partial total. `source='actual'` matches a direct `team_absences` call, nulls own status, and `rows_for_final_scores` drops that row. `game_lineups.starter` from 2025 marks `standin` and clears own status; a 2024 lineup is ignored. A projected five follows `first_seen_at <= T` and stays pregame. NULL-tip T is 05:00 UTC on 2026-01-15. Default rows stay `pregame` with absence features NULL, and `feature_sources` is unchanged. Absence SQL is `SELECT` only and does not encode T. `require_feature_source("injury_snapshots")` still raises.
- Scratch Postgres, `DATABASE_URL=postgresql://test:test@127.0.0.1:5441/test`: 15 passed. 3 are new. 2 are the SPO-138j database file. 2 are the SPO-138k database file. 5 are the first QA file. 3 are the second QA file. The live loader and `load_feature_rows` plus `load_injuries` both call `team_absences` and agree: actual pairs are the missing row and the DNP; reported pairs are Out, Questionable, and the target Out; a played player removed at T, a short sample, 899 seconds, and a trade are not absent. Coverage is `unknown` and the note names the schema, not a DSN. Loaded rows keep pregame features NULL. A loaded `game_lineups.starter` marks that row `standin` and clears own status.

**Mutation check** (reverted before commit):

- `known_at` returned true for every timestamp, so a fact one second after T was kept. `test_a_removal_one_second_after_t_does_not_hide_the_out` failed with `assert () == ((1, 1.0),)`. `test_reported_keeps_the_row_at_t_and_ignores_one_second_later` failed with `assert ((1, 1.0),) == ((1, 0.5),)`. `test_null_tip_t_is_the_midnight_used_for_the_injury_read` failed with `assert 'Questionable' == 'Out'`. `test_projected_starters_follow_first_seen_at_and_stay_pregame` failed with `assert False is True` because a version after T became visible.

The comparison was restored to `observed_at <= as_of`. The 22 in-memory SPO-138l tests then passed.

Known failures that are not this ticket: 3 tests in `test_spo132b_optional_vpc.py::TestVpcIdConsole`. They fail the same way on clean `dev` when terraform is installed. This run did not execute that file. terraform is not on PATH.

## Follow-ups

- [ ] When migration 005 is on the branch, read `source_covered` and only then store a pregame zero. An empty `injury_snapshots` table stays unknown until that reader exists.
- [ ] SPO-141: `projected_lineup_sources`, so a 2026-27 backfill can become visible. `first_seen_at <= T` already hides a backfill time after T. Do not add that table here.
- [ ] SPO-145: remove WNBA. Do not delete it inside this change, and do not add an absence path for it.
- [ ] The CLI still defaults to `reported`. `assemble_dataset(..., absence_source="actual")` is the box-score stand-in. A flag can wait until a caller needs it.

## Progress notes (for the docs PR)

- SPO-138l: NBA teammate absence, starter stand-in, and `info_source` on the dataset row. Same T as SPO-138j, including the NULL-tip midnight. One `team_absences` serves training and a live team-game.
- SPO-138l: pregame absence features stay NULL while `source_covered` is missing. `source='actual'` and `game_lineups.starter` mark `standin`. Final scores count `pregame` rows only. WNBA removal stays on SPO-145.
