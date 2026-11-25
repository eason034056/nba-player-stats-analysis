# SPO-154 — Injury status weights

## Data shape

One fit row is one player in one game:

| Field | Meaning |
|---|---|
| `season` | `games.season`. The training season is 2024, which is the 2024-25 season. |
| `bdl_game_id` | The game. |
| `bdl_player_id` | The matched player. A line with no id is not a fit row. |
| `status` | Official word on the latest report with `report_at <= T`. |
| `report_at` | That report's time. |
| `as_of` | T from `prediction_instant`: tip minus 3 hours. A NULL tip uses midnight America/New_York and does not subtract again. |
| `did_not_play` | True when that game's box-score row has `dnp`. A player with no box-score row has no label and is left out. |

One weight is one official status:

| Field | Meaning |
|---|---|
| `status` | Out, Doubtful, Questionable, Probable, or Available. |
| `row_count` | Fit rows with that status. |
| `did_not_play_count` | How many of those rows have `dnp`. |
| `p_out` | `did_not_play_count / row_count`. None when the count is 0. |

The feature table is `P_OUT_BY_OFFICIAL_STATUS`: one float per status. Feature code reads it when it scores a row. It does not contain a second copy of the five numbers.

## Summary

The official injury path now reads Out, Doubtful, Questionable, Probable, and Available from one table in `backend/app/ml/injury_weights.py`. The fitter builds the rates from the report known at T and from the box-score `dnp` flag. T is tip minus 3 hours. A report at T counts. A report one second later does not. Games with `season` 2025 or 2026 are refused.

No history database was available, so the real 2024-25 rates are PENDING. The table still holds the old fixed scale, marked `WEIGHT_TABLE_SOURCE = "prior"`. Those numbers are not a measured did-not-play rate. A 21-player fixture was fit by hand and by the fitter. The two counts match. The fixture rates were not written into the feature table.

How a report is chosen, and the NULL rule for a missing report, are unchanged. The model default is unchanged. The ablation is not in this change.

## Changes

| File | What it does |
|---|---|
| `backend/app/ml/injury_weights.py` | Holds the one weight table and fits p_out from T-time status plus the box-score label. |
| `backend/app/ml/absence.py` | Reads that table when it maps a status. Adds the coverage comment and a second time cut on the player's own status. |
| `backend/tests/test_spo154_injury_status_weights.py` | Checks the hand counts, the leak rules, and that feature minutes follow the table. |
| `backend/tests/test_spo153_qa_empty_table.py` | Runs `export_dataset` on Postgres for an empty official table and for a database with no such table. |
| `docs/decisions/SPO-154/p-out-by-status.md` | Writes the PENDING 2024-25 table and the fixture counts. |
| `docs/task-summaries/SPO-154-injury-status-weights.md` | This note. |

`load.py`, `build_dataset.py`, `features.py`, the fetcher, the parser, the matcher, and the injury service files are not edited. `docs/progress.md` is not edited.

## Why

A fixed 0.75 for Doubtful is a guess. The rate we want is the share of players with that status at T who did not play. Using a report from after T, or a later season, would mix in facts that were not part of the 2024-25 training cut. Keeping the five numbers in one table means the feature path cannot drift onto a second scale.

## Tests

From `backend/`, with `DATABASE_URL` set to a local throwaway Postgres (not `127.0.0.1:5434`):

`python -m pytest tests/test_spo154_injury_status_weights.py tests/test_spo153_qa_empty_table.py tests/test_spo153_official_injury_features.py tests/test_spo138l_ml_absence.py tests/test_spo147_138l_test_followups.py -q`

Result after the mutation edits were reverted: 58 passed. That run is the new weight file, the two Postgres export tests, the official-feature file, the absence file, and the follow-up status-word file. The empty-table export produced one row with `injury_report_missing` 1 and `team_missing_minutes` null. The database without `nba_injury_report_rows` left `injury_report_missing` null and still left minutes null.

Fixture command, from `backend/`:

`python -c "import tests.test_spo154_injury_status_weights as t; from app.ml.injury_weights import fit_official_status_weights; fit = fit_official_status_weights(*t.hand_world())"`

Printed counts: Out 4/4, Doubtful 3/4, Questionable 2/4, Probable 1/5, Available 0/4. Season on the fit object was 2024. `WEIGHT_TABLE_SOURCE` stayed `prior`.

## Follow-ups

- When a read-only 2024-25 history database is available, run `fit_official_status_weights` on the full season and replace the prior numbers in the one table. Set `WEIGHT_TABLE_SOURCE` to `fit_2024_25` in that same change. Do not fit on 2025-26 or 2026-27.
- The ablation that decides whether these columns belong in the model is still open. This change does not turn them on.
- Day-To-Day is still the old 0.25. Official reports do not use that word, so this fitter does not estimate it.

## Pstack steps

1. Smallest change: ran. The fitter and the one table live next to `absence.py`. The official path calls `official_scale()`. No second pipeline. T-time selection and the missing-report NULL rule were left as they were, plus the two small review notes below.
2. Name the shape: ran. The shapes in the table above were the ones implemented. One fit row is `(game, player, status at T, box-score did-not-play)`. One weight is `(status, p_out, row_count, did_not_play_count)`.
3. Prove it: ran. The fitter on the 21-player fixture returned 4/4, 3/4, 2/4, 1/5, and 0/4. Those are the hand counts. A report at T was included. A report one second later was not. Changing the table's Doubtful entry from 0.75 to 0.25 changed team missing minutes from the old 15 to 5 on a 20-minute teammate. Real 2024-25 data was not used.
4. Blast radius: ran. `backend/app/main.py` does not mention `app.ml`. `test_importing_the_api_does_not_import_app_ml` passed. `git diff --name-only` does not include the fetcher, parser, matcher, injury service files, `load.py`, `build_dataset.py`, `features.py`, or `docs/progress.md`. The diff does not mention `predictions`. A missing report still stores null minutes. One safety fact: starting the API does not import `app.ml`. Proved by reading `main.py` and by that test.
5. Explain the numbers: ran. Every count in the decision doc names the season, the T rule, the row count, and whether it is the real fit (PENDING) or the fixture. The feature table numbers are labeled prior.
6. Mutation check: ran. The three edits below were reverted. The files were compared with the copies taken before the edits. The weight tests and the empty-table test were run again after the revert.

## Mutation check

(a) The fitter was changed to keep games from every season and to treat a report up to 400 days after T as eligible. The checks that refuse a post-T row and a 2025 row were removed. `test_post_t_and_later_seasons_do_not_change_the_weights` failed with `assert 1 == 4` on the Out row count. The post-T report had replaced the T report. `test_a_post_t_observation_is_refused` and `test_a_later_season_observation_is_refused` failed with `DID NOT RAISE WeightFitError`. The fitter was restored.

(b) `read_official_team` was given a second dict with Doubtful 0.75 instead of `official_scale()`. `test_feature_code_reads_the_weight_table` failed with `assert 15.0 == 5.0`. `test_absence_module_has_no_second_hardcoded_scale` failed because `0.75` was back in `absence.py`. The call was restored.

(c) `features_when_official_report_missing` set `team_missing_minutes` to 0.0. `test_empty_official_table_marks_every_row_missing` failed on `assert False` inside the null-minutes check. The 0.0 assignment was removed.

## Weight table

Real 2024-25 T-time fit: PENDING. No history database was available. Counts were not invented. See `docs/decisions/SPO-154/p-out-by-status.md`.

Feature table today (`WEIGHT_TABLE_SOURCE = prior`, not a measured rate): Out 1.0, Doubtful 0.75, Questionable 0.5, Probable 0.1, Available 0.0.

Fixture, season field 2024, T = 2024-12-01 20:00 UTC, report exactly at T: Out 4 rows / 4 sat out / 1.0, Doubtful 4 / 3 / 0.75, Questionable 4 / 2 / 0.5, Probable 5 / 1 / 0.2, Available 4 / 0 / 0.0. This fixture was not copied into the feature table.

## Progress notes (for the docs PR)

SPO-154 puts the five official status weights in one table that the reported injury features read. The fitter counts did-not-play from the box score using only the report at tip minus 3 hours and only `games.season` 2024. A post-T report and a 2025-26 or 2026-27 game cannot enter the count. Real 2024-25 rates are PENDING because no history database was available. The table still holds the old fixed scale and says so with `WEIGHT_TABLE_SOURCE = prior`. A 21-player fixture matched a hand count and was not written into the table. The missing-report NULL rule is unchanged. An empty `nba_injury_report_rows` table stays on the official path (`injury_report_missing` 1, minutes null). A database without that table still uses snapshots. The matcher is not wired. The fetcher, parser, and matcher are not edited. The model default is unchanged. The ablation is still open.
