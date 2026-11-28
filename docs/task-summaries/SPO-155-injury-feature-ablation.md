# SPO-155 — Ablate official injury features against the baseline

- **Ticket:** SPO-155
- **Base:** `feature/SPO-159-train-baseline-real-data` (`e3a68c4`), which is PR #137 and is not merged
- **Merge into:** `dev`, after #137

## Summary

`python -m app.ml.ablation_injury` scores four arms on one shared set of rows and writes aggregate JSON. The arms are `official`, `no_official`, `boxscore_standin`, and `naive_last10`. `no_official` calls `fit_baseline`. The other fitted arms use the same hyperparameters, the same drop-all-missing-in-train rule, and the same scorers. The production feature list stays the locked 28 names.

When the validation rows have no official injury value, the official arm is `not_measurable` and the recommendation is the gated sentence. Equal errors are not reported as a gain.

The real history run (this branch at `c405221`, 85,089 rows in each of the two exports, seasons 2023 through 2025) has official coverage 0 of 26,623 validation rows and 0 of 26,251 train rows, so the official arm is not measurable. On the shared 26,100 rows, `no_official` matches `docs/decisions/SPO-158/baseline_metrics_real.json` on the sum markets and loses to the naive mean on all 10. `boxscore_standin` beats that mean on 8 of 10 sum markets and on double-double. Those minutes come from the box score after the game, so they are an upper bound, not a pregame feature. The recommendation is do not ship: keep the official path gated and re-run after the 2024-25 official reports are backfilled. The aggregate is in `docs/decisions/SPO-155/ablation_results.md`. The stand-in export's metadata note now says the minute and share columns are filled. The reported note is unchanged.

## Changes

| Area | Files | Change |
|---|---|---|
| Ablation | `backend/app/ml/ablation_injury.py` | One CLI. Arms, protocol checks, scoring, recommendation. |
| Export | `backend/app/ml/build_dataset.py` | `--absence-source` with default `reported`. `actual` writes the box-score stand-in. Its metadata note says the minute and share columns are filled. Output column names are unchanged. |
| Fixtures | `backend/tests/fixtures/spo155/` | Synthetic JSON only. One file where official values carry the label, one stand-in twin, one file with every official value missing. |
| Tests | `backend/tests/test_spo155_injury_feature_ablation.py` | Win, zero coverage, 2026-27, stand-in contamination, different row sets, CLI, and the unchanged export columns. |
| Docs | `docs/decisions/SPO-155/ablation_protocol.md`, `ablation_results.md` | Protocol, and the real-history aggregate. |

`train_baseline.py`, `baseline.py`, `load.py`, `absence.py`, and `injury_weights.py` are not in this diff. `docs/progress.md` is not edited.

## Why

- **One trainer.** A second model would not answer the question. The ablation reuses `fit_baseline` for the locked list and the same fit settings for the wider lists.
- **Two exports.** The minute columns have one name. The official path and the box-score path cannot share a row. The stand-in arm copies minute, share, and `is_starter` onto the pregame keys. Official count columns are not features of that arm and must stay null on `info_source=standin` rows.
- **Zero coverage is not a result.** On the real history database the official columns are missing in train, so #137 drops them and the official arm matches `no_official`. The harness says that instead of printing a comparison.

## Tests

From `backend/`, with `DATABASE_URL=""`. Nothing pointed at `127.0.0.1:5434`. `requirements.txt` and `requirements-test.txt` were installed.

```
DATABASE_URL="" python -m pytest tests/test_spo155_injury_feature_ablation.py -q
DATABASE_URL="" python -m pytest -q
```

- SPO-155 file: 15 passed.
- Full backend suite: **1801 passed, 291 skipped, 3 xfailed, 0 failed**. The session ran. The skips are tests whose Postgres fixture found no server because `DATABASE_URL` was empty. They were not a conftest skip of the whole session.

## Numbers

Synthetic only. These are not the real-database result.

Signal fixture, 40 shared validation rows, official coverage 40 of 40:

- `official` player_points MAE 0.0003718595573514172 on 40 rows. Pinball at q=0.5 is 0.0001859297786757086 on 40 rows. The same MAE is on each of the 10 sum markets. Double-double and triple-double Brier 0.12500000042496967 on 40 rows, log loss 0.34658603624235335 on 40 rows.
- `no_official`, `boxscore_standin`, and `naive_last10` player_points MAE 14.0 on 40 rows. Pinball at q=0.5 is 7.0 on 40 rows. Double-double and triple-double Brier 0.1875 on 40 rows.
- Recommendation: ship, on all 12 markets, on those 40 rows. Production still leaves the features off.

Zero-coverage fixture, same 40 rows, official coverage 0 of 40:

- Official arm status `not_measurable`. Markets are omitted. Dropped columns are the 14 minute and share columns, the 4 official counts, and `player_injury_p_out`. The 28 headline names are what would have been fit.
- Recommendation text: `not measurable: official coverage 0 rows. With 0 coverage, keep the official path gated/dark; re-run after the 2024-25 official reports are backfilled.`
- `no_official` player_points MAE stays 14.0 on 40 rows.

q=0.25 and q=0.75 are null. The trainer has no quantile model. The point model gives q=0.5 only.

## Commands for the real export

From `backend/`. Keep the DSN in `ML_DATABASE_URL`. Do not print it. Do not commit the Parquet or any player row.

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

Arm 3 needs the second export. `--absence-source` defaults to `reported`, so the first command is the pregame file.

## Follow-ups

- [x] The real-history aggregate is in `docs/decisions/SPO-155/ablation_results.md`. Official coverage was 0.
- [ ] Re-run after the 2024-25 official reports are backfilled. Leave the official path gated until then.

## pstack steps

1. **Smallest change — ran.** One module, `backend/app/ml/ablation_injury.py`. It calls `fit_baseline` for the locked 28 columns and reuses the trainer's drop rule, hyperparameters, and scorers for the wider lists. No second trainer.
2. **Name the data shape — ran.** An arm is a name, a feature-column list, and a source rule. Every measured arm is scored on one shared set: season 2025 regular-season pregame rows where every catalog label is present and the last-10/last-5 naive exists for every sum market.
3. **Prove it works — ran.** CLI on `tests/fixtures/spo155/signal_pregame.json` with `signal_standin.json` wrote `/tmp/spo155_signal.json`. Opened it: recommendation `ship`, official points MAE about 0.00037186 on 40 rows, the other three arms 14.0 on 40 rows, coverage 40 of 40, dropped list empty. CLI on `zero_coverage_pregame.json` wrote `/tmp/spo155_zero.json`. Opened it: recommendation code `not_measurable`, official markets `null`, coverage 0 of 40, the gated sentence. Full backend suite: 1801 passed, 291 skipped, 3 xfailed, 0 failed.
4. **Blast radius — ran.** `DATABASE_URL="" python -m app.ml.train_baseline --dataset tests/fixtures/spo158/synthetic_player_games.json --lines tests/fixtures/spo158/synthetic_prop_lines.json --out /tmp/spo158_after.json` printed `player_points season_2025_regular_season_pregame MAE 9.25 on 8 rows; lines 4/8; hit rate 0.6666666666666666 on 3 rows; real-database metrics PENDING`. The JSON matches `docs/decisions/SPO-158/baseline_metrics_synthetic.json` on every key. `build_dataset` default remains `reported`. `OUTPUT_COLUMNS` is not in the diff.
5. **Explain the number — ran.** Every line in the report names the arm and the row count. See Numbers. The ship sentence is 12 markets on 40 rows. The gated sentence is 0 of 40 validation rows.
6. **Mutation check — ran.** See below. All three edits were restored. The SPO-155 file then passed inside the full suite (15 tests, 0 failed in that run).

## Mutation check

Restored before commit.

1. **Allow 2026-27.** `assert_frame_allowed` returned immediately. `DATABASE_URL="" python -m pytest tests/test_spo155_injury_feature_ablation.py::test_season_2026_in_train_or_selection_raises tests/test_spo155_injury_feature_ablation.py::test_signal_fixture_official_arm_beats_the_baseline -q --tb=line` reported **1 failed, 1 passed**. The 2026-27 test failed with `Failed: DID NOT RAISE AblationError`. The signal test still passed because the split already drops that season before the guard.
2. **Copy stand-in values into official columns.** `assert_standin_rows_leave_official_counts_empty` returned immediately. The copy test and the stand-in-row-inside-the-pregame-file test both failed with `Failed: DID NOT RAISE AblationError`. Result: **2 failed**.
3. **Call zero coverage a gain.** The coverage-0 branch returned `ship` and a lower-error sentence. `test_zero_official_coverage_is_not_a_gain`, `test_cli_on_zero_coverage_writes_the_gated_sentence`, and `test_decision_ship_some_and_dont_ship` failed (`assert 'ship' == 'not_measurable'`, and the CLI text was the lower-error sentence). Result: **3 failed**.
