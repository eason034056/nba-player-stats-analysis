# SPO-159 — Train the baseline when a feature is missing on every training row

- **Ticket:** SPO-159
- **Base:** `dev` (`b029654`)

## Summary

`python -m app.ml.train_baseline` crashed on a history export when four opening-odds value columns were NaN on every training row. scikit-learn 1.9.1 then raised `ValueError: window shape cannot be larger than input array shape`. The trainer now drops a headline column only when every training row is missing it, records that list, and scores validation and the side table with the same kept columns. The locked `features` list is unchanged.

`injury_coverage_status` asked `to_regclass` for `source_covered`. Migration 005 creates a function, not a table, so the check was always null and the note said the function was not in the schema. The check now uses `to_regprocedure`. The status stays `unknown`. A player with no injury row is still not treated as healthy, and this change does not compute coverage for one game.

The checked-in metrics file is synthetic fixture output. Real-database metrics are added in this PR's next commit.

## Changes

| Area | Files | Change |
|---|---|---|
| Trainer | `backend/app/ml/train_baseline.py` | `FittedBaseline` carries the models plus the kept and dropped names. Both lists are decided from the training split. |
| Coverage | `backend/app/ml/load.py` | `COVERAGE_SQL` uses `to_regprocedure('public.source_covered(league_code,text,timestamptz,interval)')`. The docstring no longer says migration 005 is absent. |
| Tests | `backend/tests/test_spo159_train_baseline_missing.py`, `backend/tests/test_spo158_ml_baseline.py`, `backend/tests/test_spo138l_ml_absence_db.py` | All-missing, train-decides, partial, and all-columns-missing cases. A throwaway database creates the function and expects the note to say it is present. |
| Docs | `docs/decisions/SPO-158/baseline_metrics_synthetic.json`, `model_card.md` | Renamed the synthetic file, regenerated it so the two new keys appear, and left a placeholder for the real-database file. |

`backend/app/ml/baseline.py` and `backend/app/ml/build_dataset.py` are not in the diff. `feature_matrix` still locks the same 28 names. `OUTPUT_COLUMNS` is unchanged.

## Why

- **The crash is an all-missing column, not a bad hyperparameter.** The three `opening_*_books` columns are 0 when no odds row qualifies, so they are fine. The four value columns are null in that case. HistGradientBoosting can use a column that is only partly missing. It cannot use a column that is missing on every row it is given.
- **Train decides.** A value that exists only in validation must not put a column back, or the fitted model and the scored matrix would disagree, and the empty odds table would leak back in through the validation season.
- **The kept list belongs on the fitted object.** Scoring reads `FittedBaseline.features_actually_fit`. There is no module global.
- **The coverage note was looking at the wrong catalog.** `to_regclass` sees tables and views. `source_covered(league_code, text, timestamptz, interval)` is a function. `to_regprocedure` with that argument list returns null when the function is absent and the function name when it is present. On a Postgres 16 probe, `to_regclass('public.source_covered')` stayed null after `CREATE FUNCTION`.

## Tests

From `backend/`, with `DATABASE_URL` set explicitly. No-database commands used an empty value. Database commands used a throwaway Postgres 16 on `127.0.0.1:5441`. Nothing pointed at `127.0.0.1:5434`.

```
DATABASE_URL="" python -m pytest tests/test_spo159_train_baseline_missing.py tests/test_spo158_ml_baseline.py -q
DATABASE_URL=<throwaway> python -m pytest tests/test_spo138l_ml_absence_db.py -q
DATABASE_URL=<throwaway> python -m pytest -q
```

`requirements.txt` and `requirements-test.txt` were installed. `reportlab` is only in the test file. Without it, seven injury-PDF modules fail at collection.

- Before the fix, `test_all_nan_train_column_is_dropped_and_scoring_succeeds` and `test_train_nan_column_with_validation_values_is_still_dropped` failed with `ValueError: window shape cannot be larger than input array shape`.
- After the fix: SPO-159 file 4 passed. SPO-158 file 18 passed (22 together). Absence database file 4 passed, including the new function test. The older absence tests still see "schema" in the note, because those databases do not create the function.
- Full backend suite: **2059 passed, 17 skipped, 4 xfailed, 0 failed** (about 2 minutes). `TestVpcIdConsole` was 3 skipped because `terraform` is not on PATH. Those 3 known failures did not appear.
- CLI on the synthetic fixture, after setting `opening_spread_home` to NaN on the 4 training rows and leaving it filled on all 9 validation rows: exit 0. The written JSON has `features_dropped_all_missing_in_train` = `["opening_spread_home"]`, `features_actually_fit` length 27, locked `feature_count` 28. Points MAE is 9.25 on 8 scored rows (4 with a line, 4 without). Side-table points MAE is 10 on 1 row.

## Numbers

Synthetic file `docs/decisions/SPO-158/baseline_metrics_synthetic.json`, regenerated by the fixed trainer. Input 17 rows: train 4, validation 9 (8 scored, 1 label-null), side 1, season-2026 excluded 1, not-pregame excluded 1, other ignored 1. `features` and `features_actually_fit` are the same 28 names. `features_dropped_all_missing_in_train` is empty because 0 of those 28 columns are missing on all 4 training rows. Points MAE is 9.25 on those 8 scored rows. Markets, rows, the locked feature list, and the side table match the previous synthetic file. `python_version` in the file is 3.12.3, which is the interpreter that regenerated it. `library_version` is 1.9.1.

## Follow-ups

- [ ] Add the real-database metrics on this same branch in the next commit. The model card placeholder says that.
- [ ] A column that is missing on every labeled training row, but filled on an unlabeled training row, is still kept. This ticket drops a column only when the whole training split is missing it.

## pstack steps

1. **Smallest change — ran.** Goal: the trainer survives a column that is missing on every training row and says which columns it dropped; the coverage note tells the truth about the function. `feature_matrix` still builds the locked 28 columns. The new code only slices that matrix. No new module. `injury_coverage_status` still returns `unknown`.
2. **Name the data shape — ran.** The kept-column list is a property of the fitted model (`FittedBaseline.features_actually_fit`). It is decided from the training matrix only, then reused when `_score_frame` builds the validation matrix and the side-table matrix.
3. **Prove it works — ran.** The CLI above wrote `/tmp/spo159_nan_metrics.json`. Opened it: dropped list is `opening_spread_home` only, fit list has 27 names, points MAE 9.25 on 8 rows, side table scored 1 row. The checked-in synthetic file has an empty dropped list and 28 fitted names. Full backend suite: 2059 passed, 17 skipped, 4 xfailed, 0 failed.
4. **Blast radius — ran.** `fit_baseline` is called from `train_and_score` and from tests. Its parameters are still `(train, seed)`. The return value is now `FittedBaseline`; `train_and_score` is the only production caller and it reads `.models` and the two name lists. `feature_matrix` is called from `train_baseline.py` and `test_spo158_ml_baseline.py`. Its signature is unchanged, and it still rejects a list that is not the locked 28. `injury_coverage_status` is called from `build_dataset.py` and the absence database tests. The status string is still `unknown`, so `assemble_dataset` does not start storing a pregame zero. `git diff -- backend/app/ml/build_dataset.py backend/app/ml/baseline.py` is empty, so `OUTPUT_COLUMNS` did not change.
5. **Explain the number — ran.** See Numbers. Every quoted MAE names its row count: 9.25 is 8 scored validation rows; the side-table 10 is 1 row; the dropped column was blank on 4 training rows and filled on 9 validation rows.
6. **Mutation check — ran.** See below. The three edits were restored. SPO-159 (4) and SPO-158 (18) then passed with `DATABASE_URL=""`. The absence database file (4) passed on the throwaway database.

## Mutation check

Restored before commit.

1. **Stop dropping.** In `fit_baseline`, the kept list was replaced with every headline name and the model was fit on the full matrix. `DATABASE_URL="" python -m pytest tests/test_spo159_train_baseline_missing.py -q --tb=line` reported **3 failed, 1 passed**. The all-NaN train column, the train-NaN/validation-filled column, and the all-columns-missing case failed with `ValueError: window shape cannot be larger than input array shape`. The partly missing column still passed.
2. **Decide the drop list from validation.** `train_and_score` stored the validation frame on the training frame, and `fit_baseline` chose columns from that frame while still fitting the training rows. The same command reported **3 failed, 1 passed**, again with the window-shape `ValueError` on the three drop tests. The partial column stayed kept, so that test passed.
3. **Revert the function check.** `COVERAGE_SQL` was put back to `to_regclass('public.source_covered')`. The new database test failed: the note was `source_covered is not in the schema` even though the function had been created (`assert 'present' in note`). The older absence test, which does not create the function, still passed. Result: **1 failed, 1 passed**.
