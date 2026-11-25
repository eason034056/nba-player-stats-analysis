# SPO-158 — Baseline player-props model without official injury features

- **Ticket:** SPO-158
- **Base:** `dev` (`c7bf587`)

## Summary

The pregame baseline predicts each catalog stat from features already on the dataset export and known at T (tip minus 3 hours). It is the fixed "no official injury features" arm. One row is one player-game. Labels are `y_<market>`. Prop lines are not features. A line grades a row only when `snapshot_at` is present and `snapshot_at <= T`.

Train on season 2024 (2024-25), regular season, `info_source = pregame`. Report on season 2025 (2025-26), same filter. Season 2026 (2026-27) is not used to fit or to pick the model. Headline features are form, schedule, and opening game odds. Absence columns stay out of the matrix. Unknown injury coverage is still not stored as zero.

No history database was available. The checked-in numbers are a 17-row synthetic fixture whose MAE and hit rate can be recomputed by hand. Real-database metrics are **PENDING**. The trainer does not open a database and does not point at `127.0.0.1:5434`.

## Changes

| Area | Files | Change |
|---|---|---|
| Trainer | `backend/app/ml/baseline.py`, `backend/app/ml/train_baseline.py` | Split, feature lock, pre-T line median, naive last-10, metrics. `python -m app.ml.train_baseline`. |
| Sample | `backend/tests/fixtures/spo158/synthetic_player_games.json`, `synthetic_prop_lines.json` | 17 player-games and the grade lines, including a post-T line and a null timestamp. |
| Tests | `backend/tests/test_spo158_ml_baseline.py` | Hand-checked scores, leak guards, Parquet path, API import. |
| Docs | `docs/decisions/SPO-158/model_card.md`, `baseline_metrics.json` | Model card and the synthetic metrics. Real-database status is PENDING. |
| Dependency | `backend/requirements.txt` | `scikit-learn==1.9.1`. |
| Ignore | `.gitignore` | Parquet, joblib, pickle, PDF, and per-player prediction dumps. |

## Why

- **One export, one trainer.** The row already exists in `build_dataset`. A second feature stack would drift from T, from the prior-date rule, and from the opening-odds median.
- **The line is a grade, not an input.** A model that sees the line can copy the market. The matrix builder refuses `player_prop_snapshots` and the line columns by name.
- **2026-27 stays out.** The validation season is for the report. It is not an argument of `fit_baseline`. Season 2026 raises before fit.
- **Every rate has a denominator.** A missing line stays in the scored row count. A push leaves the hit-rate count. The synthetic hit rate is 2/3 on 3 rows, not on all 8.
- **The leaf size is the library default.** `min_samples_leaf` is 20. The sample has 4 training rows, so the model predicts the training mean (20 for points). That is why 9.25 can be checked by hand. It is not a real-season error.

## Tests

```
cd backend
DATABASE_URL="" python -m pytest tests/test_spo158_ml_baseline.py -q
DATABASE_URL="" python -m pytest tests/test_spo138j_ml_dataset.py tests/test_spo138k_ml_game_odds.py tests/test_spo138l_ml_absence.py tests/test_spo147_138l_test_followups.py -q
```

Python 3.11.18. `scikit-learn==1.9.1` installed in that interpreter with `pandas==3.0.1` and `pyarrow==23.0.1`. `ruff check` with `--select E9,F63,F7,F82` passed on the new Python files.

- SPO-158 file: 18 passed. Points MAE is 9.25 on 8 scored rows. Naive last-10 MAE is 2.5 on those 8. Usable lines 4, missing lines 4, pushes 1, hit rate 2/3 on 3 rows. One void row is the ninth validation row and is not scored. Rebounds naive MAE is 0 on 8 rows with 0 lines, so its hit rate is null. Double-double Brier is 0.25 on 8 rows. Triple-double Brier is 0.0625 on 8 rows. Season 2026 row count excluded is 1. Train seasons are `[2024]`. Validation seasons are `[2025]`. A Parquet copy of the same rows scores the same points block. The committed metrics file matches a fresh run.
- A four-row hand vector with one missing line keeps that row in the MAE denominator (`rows_scored` 4, `rows_without_line` 1, hit-rate rows 2).
- Existing in-memory dataset tests: 57 passed (SPO-138j, SPO-138k, SPO-138l, SPO-147).
- The full backend suite was not re-run. Known failures that are not this ticket: 3 tests in `test_spo132b_optional_vpc.py::TestVpcIdConsole`.

Trainer command, from `backend/`:

```
DATABASE_URL="" python -m app.ml.train_baseline \
  --dataset tests/fixtures/spo158/synthetic_player_games.json \
  --lines tests/fixtures/spo158/synthetic_prop_lines.json \
  --out ../docs/decisions/SPO-158/baseline_metrics.json
```

Stdout: `player_points season_2025_regular_season_pregame MAE 9.25 on 8 rows; lines 4/8; hit rate 0.6666666666666666 on 3 rows; real-database metrics PENDING`. The same fields are in `docs/decisions/SPO-158/baseline_metrics.json`.

## Follow-ups

- [ ] When a read-only history DSN is available, export with `build_dataset` and rerun this trainer. Replace the PENDING mark only after that run. Do not point the export at `127.0.0.1:5434`.
- [ ] Line coverage on a real export will stay low until the odds backfill. Keep reporting the missing-line count.
- [ ] A stand-in arm (`info_source = standin`, box-score absence) was not trained. It must stay out of this feature list.
- [ ] Quantile heads (pinball at 0.1 / 0.5 / 0.9) were not trained. Point MAE is the required number.
- [ ] Do not fill pregame absence with zeros while injury coverage is unknown.

## pstack steps

1. **Smallest change — ran.** The goal is a leak-safe baseline with no official injury features, so a later ablation can rerun one command. The trainer sits next to `backend/app/ml/build_dataset.py` and reads that export's columns. It does not build a second dataset stack, does not revive the removed agent trees, and does not add a stand-in model or a quantile head. Work order was the row shape, then the trainer, then the hand-checked sample, then the leak tests, then the card.
2. **Name the data shape — ran.** One training row is one player-game. Features are the 28 pregame columns known at that row's `as_of`. Labels are `y_<market>`. Lines are a separate JSON list, may be missing, and never enter the matrix.
3. **Prove it works — ran.** The command above wrote `docs/decisions/SPO-158/baseline_metrics.json`. Opened that file: `markets.player_points.mae` is 9.25, `mae_row_count` is 8, `rows_with_usable_line` is 4, `rows_without_line` is 4, `hit_rate` is 2/3, `hit_rate_row_count` is 3. Those match the stdout and the hand sum `(7 * 10 + 4) / 8 = 9.25`. `test_missing_line_stays_in_the_mae_denominator` scores a 4-row vector whose last line is missing and checks it stays in `rows_scored`.
4. **Blast radius — ran.** Safety fact: fitting cannot see official injury columns or prop lines, because `feature_matrix` accepts only the locked 28 names and raises if a forbidden name is added. Proof: `test_headline_list_rejects_official_injury_and_prop_columns` and `test_extra_injury_and_line_columns_stay_out_of_the_matrix` passed, and the metrics `features` list is those 28 names. `test_importing_the_api_does_not_import_app_ml` starts a fresh interpreter, imports `app.main` with `DATABASE_URL=""`, and exits 0 only when `app.ml` is absent from `sys.modules`. The trainer source has no `asyncpg` and no `INSERT`. `git diff --name-only` plus untracked files do not include `backend/app/services/injury_report_ingest.py`, `injury_report_parser.py`, or migrations 006 and 007. `test_importing_the_trainer_does_not_import_injury_ingest` starts a fresh interpreter, imports `app.ml.train_baseline`, and exits 0 only when `injury_report_ingest` and `injury_report_parser` are absent. The full suite already loads those modules, so an in-process `sys.modules` check cannot show what the trainer itself imports.
5. **Explain the number — ran.** The model card table names the split (2025 regular pregame), the 8 scored rows, the 4 lines, and the 3-row hit rate. Rebounds reports a null hit rate next to 0 lines. The side-table MAE is labeled not used for selection.
6. **Mutation check — ran.** See below. The comparison was restored. The 18 SPO-158 tests then passed.

## Mutation check

Reverted before commit. In `line_visible_at_t`, `return snapshot_at <= as_of` was changed to `return True` (a null timestamp still returned false).

`DATABASE_URL="" python -m pytest tests/test_spo158_ml_baseline.py -q --tb=short` then reported **5 failed, 13 passed**:

- `test_line_at_exactly_t_is_visible_and_one_second_later_is_not`: `assert True is False` for a timestamp one second after T.
- `test_post_t_line_is_excluded_from_the_median`: `assert 54.75 == 9.5`. The live line of 100 posted one second after T entered the median with the pre-T 9.5.
- `test_a_line_after_t_only_counts_as_missing`: `assert 12.0 is None`.
- `test_synthetic_run_matches_the_hand_calculation`: `rows_with_usable_line` was 5, not 4. Stdout on that run: `lines 5/8; hit rate 0.5 on 4 rows` (was `lines 4/8; hit rate 0.666... on 3 rows`).
- `test_committed_metrics_file_matches_a_fresh_run`: fresh hit rate 0.5 on 4 rows versus the committed 2/3 on 3 rows.

The comparison was put back. The same file then reported **18 passed**.

## Progress notes (for the docs PR)

- SPO-158: pregame baseline trainer next to the dataset export. Train 2024-25 regular season, report 2025-26 regular season, leave 2026-27 unused. No official injury features. Prop lines grade a row only when `snapshot_at <= T`.
- SPO-158: committed scores are the synthetic sample (points MAE 9.25 on 8 rows, lines 4/8, hit rate 2/3 on 3 rows). Real-database metrics are PENDING. The API still does not import `app.ml`. The `predictions` table is not written.
