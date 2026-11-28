# SPO-158 baseline: real history database metrics

**Source:** Eason's `nba_history` pg_dump (migrations 001–005), restored read-only into a throwaway Postgres 17 (not the live backfill DB). Trainer: `feature/SPO-159-train-baseline-real-data` @ 7e0f99b. Full JSON: `baseline_metrics_real.json`.
**T rule:** `as_of` = `games.datetime_utc − 3h` (0 null-tip fallbacks in 2023–2025).
**Export:** `build_dataset --seasons 2023:2025 --hours-before-tip 3` → 85,089 played rows (138,317 before the label filter; 53,228 DNP rows dropped as void). All rows `info_source=pregame`, 0 stand-in.
**Split:** train = season 2024 (2024-25) regular season, pregame, 26,251 rows. Validation = season 2025 (2025-26) regular season, pregame, 26,623 rows (0 label-null). Side table = season 2025 playoffs/play-in/Cup, 2,065 rows, not used for selection. Ignored = 30,150 rows (season 2023 history + 2024 non-regular). Season 2026 rows in export: 0.
**Model:** sklearn 1.9.1 HistGradientBoosting, seed 158, fixed hyperparameters (100 iterations, no search, no early stopping).

**Dropped columns.** `game_odds_snapshots` is empty, so the four opening-odds value columns (`opening_spread_home`, `opening_total`, `team_implied_points`, `opp_implied_points`) are missing on every training row. Before SPO-159 the trainer crashed on them. With SPO-159 the trainer drops them (decided from the train split only) and records them in the JSON, so 24 of the locked 28 features were fit. The three `opening_*_books` count columns stay in and are all 0.

**Lines:** odds tables empty → **0 line-covered rows on every market**. Hit rate is not reported (0 covered rows, not a rate).
**Naive:** last-10 played mean, last-5 when last-10 is NULL; 523 validation rows have neither. Compare against the "Model MAE on naive rows" column, which uses the same 26,100 rows.

## Validation, season 2025 regular season pregame (sum markets)

| Market | Val rows scored | Model MAE | Naive last-10 MAE (rows) | Model MAE on naive rows | Calibration (binned residual: rows / mean resid) | Line-covered rows |
|---|---|---|---|---|---|---|
| player_points | 26623 | 4.769 | 4.691 (26100) | 4.791 | below_-5: 5303 / -7.95; within_5: 16575 / -0.58; above_5: 4745 / 9.53 | 0 |
| player_rebounds | 26623 | 1.952 | 1.944 (26100) | 1.956 | below_-5: 370 / -6.10; within_5: 25196 / -0.29; above_5: 1057 / 6.82 | 0 |
| player_assists | 26623 | 1.381 | 1.377 (26100) | 1.388 | below_-5: 88 / -5.99; within_5: 26082 / -0.10; above_5: 453 / 6.66 | 0 |
| player_threes | 26623 | 0.945 | 0.906 (26100) | 0.950 | below_-5: 0 / —; within_5: 26516 / -0.11; above_5: 107 / 5.94 | 0 |
| player_steals | 26623 | 0.737 | 0.738 (26100) | 0.740 | below_-5: 0 / —; within_5: 26602 / 0.12; above_5: 21 / 5.72 | 0 |
| player_blocks | 26623 | 0.532 | 0.511 (26100) | 0.535 | below_-5: 0 / —; within_5: 26615 / -0.01; above_5: 8 / 5.92 | 0 |
| player_points_rebounds | 26623 | 5.750 | 5.680 (26100) | 5.768 | below_-5: 6954 / -8.55; within_5: 13902 / -0.46; above_5: 5767 / 10.35 | 0 |
| player_points_assists | 26623 | 5.233 | 5.195 (26100) | 5.252 | below_-5: 5928 / -8.28; within_5: 15311 / -0.52; above_5: 5384 / 9.89 | 0 |
| player_rebounds_assists | 26623 | 2.691 | 2.687 (26100) | 2.696 | below_-5: 1296 / -6.44; within_5: 23165 / -0.43; above_5: 2162 / 7.38 | 0 |
| player_points_rebounds_assists | 26623 | 6.319 | 6.212 (26100) | 6.334 | below_-5: 7811 / -9.12; within_5: 12665 / -0.42; above_5: 6147 / 10.73 | 0 |

## Validation, yes/no markets

| Market | Val rows | Brier | Log loss | Naive Brier (train rate) | Reliability bins: rows, mean pred → mean outcome | Line-covered rows |
|---|---|---|---|---|---|---|
| player_double_double | 26623 | 0.0550 | 0.1969 | 0.0670 (rate 0.0855) | [0.0,0.2): 23395, 0.039→0.036; [0.2,0.4): 2015, 0.281→0.246; [0.4,0.6): 686, 0.492→0.388; [0.6,0.8): 455, 0.681→0.563; [0.8,1.0): 72, 0.847→0.681 | 0 |
| player_triple_double | 26623 | 0.0062 | 0.0390 | 0.0051 (rate 0.0057) | [0.0,0.2): 26509, 0.001→0.004; [0.2,0.4): 24, 0.292→0.167; [0.4,0.6): 7, 0.484→0.286; [0.6,0.8): 9, 0.666→0.333; [0.8,1.0): 74, 0.984→0.284 | 0 |

## Side table (season 2025 postseason/play-in/Cup, 2,065 rows, not used for selection)

| Market | Side rows | Model MAE / Brier | Naive MAE / Brier |
|---|---|---|---|
| player_points | 2065 | 4.979 | 4.534 (2065) |
| player_rebounds | 2065 | 1.978 | 1.889 (2065) |
| player_assists | 2065 | 1.314 | 1.278 (2065) |
| player_threes | 2065 | 0.965 | 0.851 (2065) |
| player_steals | 2065 | 0.720 | 0.718 (2065) |
| player_blocks | 2065 | 0.528 | 0.507 (2065) |
| player_points_rebounds | 2065 | 6.148 | 5.578 (2065) |
| player_points_assists | 2065 | 5.369 | 5.030 (2065) |
| player_rebounds_assists | 2065 | 2.721 | 2.592 (2065) |
| player_points_rebounds_assists | 2065 | 6.809 | 6.094 (2065) |
| player_double_double | 2065 | 0.0551 | 0.0615 |
| player_triple_double | 2065 | 0.0043 | 0.0029 |

## Read-outs

- On the same 26,100 rows, the model is **worse than the naive last-10 mean on all 10 sum markets** (for example points 4.791 vs 4.691, PRA 6.334 vs 6.212, steals 0.740 vs 0.738). With no odds and no absence features, the GBM adds nothing over form.
- Double-double: Brier 0.0550 vs naive 0.0670, which is better. It is overconfident above 0.4.
- Triple-double: Brier 0.0062 vs naive 0.0051, which is **worse than naive**. The 74 rows predicted at about 0.98 hit only 28%. The classifier is badly overconfident.

## SQL checks on the restored DB
- Season 2024 `player_game_stats`: 46,150 rows, **17,946 with `dnp = true`**.
- No `nba_injury_report_rows` table in any season. `injury_snapshots` = 0, `current_injuries` = 0, `source_refreshes` = 0 (so there are no `injuries_nba_official` refreshes either). With no official injury report data, the SPO-154 status→p_out fit can't be done from this DB.
