# Model card — SPO-158 baseline, no official injury features

This is the fixed comparison model for a later ablation. It predicts each catalog stat from facts known at T. It does not use the official NBA injury report. The numbers in `baseline_metrics_synthetic.json` are synthetic fixture output from a 17-row made-up sample. Do not read 9.25 as a real-season error.

Real-database metrics are in `SPO-158_real_metrics.md` and `baseline_metrics_real.json`. Headline: on 26,100 matching 2025-26 validation rows the model is worse than the naive last-10 mean on all 10 sum markets (points 4.791 vs 4.691, PRA 6.334 vs 6.212), better on double-double Brier (0.0550 vs 0.0670), worse on triple-double Brier (0.0062 vs 0.0051); 0 rows have a prop line, so no hit rate.

## Command

From `backend/`:

```
DATABASE_URL="" python -m app.ml.train_baseline \
  --dataset tests/fixtures/spo158/synthetic_player_games.json \
  --lines tests/fixtures/spo158/synthetic_prop_lines.json \
  --out ../docs/decisions/SPO-158/baseline_metrics_synthetic.json
```

A history export uses the same trainer on a Parquet file from the existing command. That file stays on disk and out of git:

```
python -m app.ml.build_dataset \
  --dsn-env ML_DATABASE_URL \
  --seasons 2023:2025 \
  --hours-before-tip 3 \
  --out <local>.parquet
```

`--seasons` is inclusive. A start of 2023 only gives early 2024-25 rows a last-5 and last-10 window. Training labels are still season 2024. This trainer never opens a database. Pass the Parquet path as `--dataset`. Pass a JSON list of prop lines as `--lines` when you have one. With no `--lines`, every row is counted as missing a line.

## T

T is the row's `as_of` column. The export already set it: tip minus 3 hours, or 00:00 America/New_York on the game date when the tip is null. That midnight is not shifted again. The trainer does not subtract 3 hours a second time. A prop line is usable only when its `snapshot_at` is present and `snapshot_at <= as_of`.

## Split

| Role | Rule | Used to fit or to pick the model |
|---|---|---|
| Train | Season 2024 (2024-25), regular season, `info_source = pregame` | Fit only |
| Validation | Season 2025 (2025-26), regular season, `info_source = pregame` | No. Reporting only |
| Side table | Season 2025, pregame, not regular season (playoffs, play-in, Cup) | No |
| Left out | Season 2026 (2026-27), any non-pregame row, any other season | No |

Hyperparameters are fixed. They are not searched on the validation season. Early stopping is off, so the trainer does not hold out part of the training season either.

## Headline features (28)

Form, schedule, and opening game odds. All of these are on the existing export and are knowable at T.

- Schedule: `is_home`, `n_prev_games`, `n_played_prev`, `dnp_last_10`, `dnp_last_10_window`, `days_rest`, `is_back_to_back`
- Last 5 played games, then last 10, for `pts`, `reb`, `ast`, `fg3m`, `stl`, `blk`, `seconds_played`
- Opening odds: `opening_spread_home`, `opening_total`, `team_implied_points`, `opp_implied_points`, `opening_books`, `opening_spread_books`, `opening_total_books`

`season_type` is a filter (regular season), not a column of the matrix. A short window stays null. It is not filled with zero.

A column that is missing on every training row is left out of the fit. The locked `features` list still names all 28. `features_dropped_all_missing_in_train` names the ones left out. `features_actually_fit` names the ones the model saw. On this synthetic file the dropped list is empty: each of the 4 training rows has a number in every feature. The same kept list is used to score the 9 validation rows and the 1 side-table row.

## Left out of the matrix

- Official injury: `nba_injury_report_rows`, `injuries_nba_official`, `current_injuries`, `source_covered`
- The target box score: `pts`, `reb`, `ast`, `fg3m`, `stl`, `blk`, `seconds_played`, `dnp`, `home_score`, `visitor_score`
- Prop lines: `player_prop_snapshots`, `line`, `over_odds`, `under_odds`, `milestone_odds`
- Absence and starter columns, including every `team_missing_share_<market>`, `team_missing_minutes`, `opp_missing_minutes`, `is_starter`, `player_injury_status`
- Identity columns (`league`, `season`, `date`, ids, `info_source`, `as_of`, `tip_fallback`) and every `y_<market>` label

Absence columns stay on the export. With injury coverage still unknown, a pregame row stores null there, not zero. This trainer does not read them. A missing injury row is not treated as "everyone is healthy." A stand-in row (`info_source = standin`) is not in the headline fit.

## Lines

Lines are for grading only. For one player, game, and market, keep rows with a non-null `snapshot_at <= T`. Each book keeps its latest such row (closing beats live beats opening when the timestamp ties). The grade line is the median of those book lines. A null timestamp is dropped, not filled in. A line after T is dropped. A row with no usable line stays in the scored row count and in the MAE. It is not given a hit or a miss. A push (the actual equals the line) stays in the "had a line" count and leaves the hit-rate count.

## Model

- Library: scikit-learn 1.9.1 (`HistGradientBoostingRegressor` for the ten sum stats, `HistGradientBoostingClassifier` for double-double and triple-double)
- Seed: 158
- `loss` squared error, `learning_rate` 0.1, `max_iter` 100, `max_leaf_nodes` 31, `min_samples_leaf` 20, `l2_regularization` 0, `early_stopping` false
- `min_samples_leaf` 20 is the library default. It was not tuned on 2025-26.

The checked-in sample has 4 training rows. A leaf needs 20 rows, so the trees do not split. Each model predicts its training mean. On a full season the same settings can split. The synthetic MAE is the distance from that mean, which is why it can be checked by hand.

The synthetic file was regenerated with Python 3.12.3, `pandas==3.0.1`, `pyarrow==23.0.1`, and scikit-learn 1.9.1. The trees still do not split on 4 training rows, so the hand-checked MAE is unchanged.

## Synthetic validation (season 2025, regular season, pregame)

The file has 17 rows: 4 train, 9 validation (one of those has every label null), 1 playoff side row, 1 stand-in, 1 season-2023 row, 1 season-2026 row.

Training points labels are 10, 10, 30, 30. The mean is 20, and that is the prediction on every validation row.

Eight labeled validation rows, plus one void row that is counted and not scored:

| Check | Value | Rows |
|---|---|---|
| Points MAE | 9.25 | 8 scored (7 errors of 10, and one error of 4: `(70 + 4) / 8`) |
| Points last-10 naive MAE | 2.5 | 8 (seven errors of 0, one error of 20 where the label is 30 and last-10 is 10: `20 / 8`) |
| Rows with a usable line | 4 | of the 8 scored |
| Rows with no usable line | 4 | of the 8 scored. These stay in the MAE |
| Pushes | 1 | actual equals the line. Out of the hit-rate count |
| Hit rate | 2/3 | 2 hits and 1 miss, on 3 rows. Not on all 8 |
| Label-null rows in the split | 1 | the void row. Split size is 9 |

The four lines are 9.5 (hit: both sides over), 31.5 (hit: both sides under), 10 (push), and 25 (miss: prediction under, actual over). One of the four missing-line rows has only a line posted one second after T. Another has only a null timestamp. Both are missing, not scored.

Rebounds, on the same 8 rows: model MAE 9.25, naive MAE 0, usable lines 0. The hit rate is null. It is not reported as if every row had a line.

Double-double: training rate 0.5, so the model probability is 0.5. Brier is 0.25 on 8 rows. Log loss is `log(2)`. All 8 probabilities sit in the bin `[0.4, 0.6)`, and 3 of the 8 labels are 1 (mean outcome 0.375). No lines, so no hit rate.

Triple-double: training rate 0.25. Brier is 0.0625 on 8 rows (every validation label is 0). Log loss is `-log(0.75)`.

Side table: 1 playoff row. Points MAE is 10 on that 1 row. `not_used_for_selection` is true. Season 2026 is not in the train seasons or the validation seasons.

## Known gap

Opening prop lines in the data model start in 2024-25, and the historical odds backfill has not been run. A real export will have many rows with no usable line. The metrics still count those rows. Opening game-odds timing against a real tip is still the PENDING note in `docs/decisions/SPO-138/game-odds-opener-timing.md`. This card does not add a timing number.

## What this does not do

- It does not read official injury tables or `current_injuries`.
- It does not write the `predictions` table. Backtests write this JSON file.
- It is not imported when the API process starts.
- It does not train or pick a model on 2026-27.
- Real-database metrics are in `SPO-158_real_metrics.md` and `baseline_metrics_real.json`.
