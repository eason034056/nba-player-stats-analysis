# SPO-155 — Do official injury features help the baseline?

Compare four arms on one export. The production trainer stays the SPO-158 list. This ablation does not turn official features on.

## Arms

| Arm | What it reads | Where those numbers come from |
|---|---|---|
| `official` | The 28 baseline columns, plus `team_missing_minutes`, every `team_missing_share_<market>`, `opp_missing_minutes`, `rot_out_n`, `rot_q_n`, `unmatched_listed_n`, `injury_report_missing`, and `player_injury_p_out` | Pregame export. `player_injury_p_out` is `player_injury_status` looked up in `P_OUT_BY_OFFICIAL_STATUS` at read time. The table is not refit. |
| `no_official` | The 28 baseline columns only | Same pregame rows. This calls `fit_baseline`. |
| `boxscore_standin` | The 28 baseline columns from the pregame row, plus the minute and share columns and `is_starter` | A second export with `--absence-source actual`. Those rows are `info_source=standin`. Official count columns are not features. |
| `naive_last10` | No fit | Last-10 played mean, last-5 when last-10 is missing. Same function as the SPO-158 trainer. Double-double and triple-double use the training positive rate. |

`baseline.OFFICIAL_INJURY_COLUMNS` (`nba_injury_report_rows`, `injuries_nba_official`, `current_injuries`, `source_covered`) are source-table locks, not columns on the export. They are not features.

## Split

Train: season 2024 (2024-25), regular season, `info_source=pregame`. The fit uses that whole split.

Validation: season 2025 (2025-26), regular season, `info_source=pregame`.

Shared scored rows: validation rows where every catalog label is present and the naive exists for every sum market. Every measured arm is scored on that same set. A mismatch raises.

Season 2026 (2026-27) is not used to fit and not used to pick the recommendation. A frame that still contains it raises.

A stand-in row with a number in `rot_out_n`, `rot_q_n`, `unmatched_listed_n`, or `injury_report_missing` raises. The box-score path leaves those null.

## Metrics

Each market names the arm and the row count.

Sum markets: MAE, pinball at q=0.5, and binned residuals (below -5, within 5, above 5). The trainer has no quantile model, so q=0.25 and q=0.75 are not scored. The point model gives q=0.5 only.

Double-double and triple-double: Brier, log loss, and reliability bins.

Official coverage: how many validation rows have any non-missing official injury value (a minute, a share, a count, or a status word). A null is missing. A zero is a value.

## Decision

- Coverage is 0: `not measurable: official coverage 0 rows`. Keep the official path gated. Re-run only after (a) migrations 006/007 are applied to the history database and (b) official injury reports are backfilled for both the 2024-25 training window and the 2025-26 validation window. The dump used (migrations 001-005) has no official report, injury, lineup, source_refreshes, or odds snapshot rows, so 0 coverage is structural, not a join bug; production was not checked. Do not treat equal errors as a gain.
- Every official column missing on every training row is a different sentence. The fit is the no-official baseline. The re-run condition is the same (a) and (b). It is not the zero-coverage sentence.
- Every market is strictly better (lower MAE, or lower Brier): `ship`.
- At least one market is strictly better and another is not: `ship-some`.
- No market is strictly better: `don't-ship`.

A tie is not a win. The stand-in arm is reported and does not pick the sentence. None of these sentences turns the features on in the production model.

## Commands

From `backend/`. The DSN stays in the environment variable. It is not printed.

```
python -m app.ml.build_dataset \
  --dsn-env ML_DATABASE_URL \
  --seasons 2023:2025 \
  --hours-before-tip 3 \
  --out <pregame.parquet>

python -m app.ml.build_dataset \
  --dsn-env ML_DATABASE_URL \
  --seasons 2023:2025 \
  --hours-before-tip 3 \
  --absence-source actual \
  --out <standin.parquet>

DATABASE_URL="" python -m app.ml.ablation_injury \
  --dataset <pregame.parquet> \
  --standin-dataset <standin.parquet> \
  --out <ablation.json> \
  --report <ablation.md>
```

`--absence-source` defaults to `reported`. The default output column list does not change. `--lines` is optional and is used only for grading. Season 2023 is history for last-10. It is not a training label season. Do not point the export at `127.0.0.1:5434`.

## Results

The real-database aggregate is in `ablation_results.md`. The tool report pasted under that headline is the c405221 output, byte for byte, including its older re-run sentence. The headline and the code use the condition above.
