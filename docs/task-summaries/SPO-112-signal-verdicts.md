# SPO-112 — Signal verdicts and combined probability

- Ticket: SPO-112
- Branch: `feature/SPO-112-signal-verdicts` (from `dev` @ `a14370d`)
- Base: `dev`

## Summary

NBA Daily Picks now carry five side-relative signals and a calibrated `combined_probability`. A missing input is null on that signal, not a neutral verdict. No modal-line price, or an injury status of Out or Doubtful, leaves `combined_probability` null. WNBA picks get `signals=None` and `combined_probability=None`.

The blend starts from the market no-vig log-odds, adds four capped adjustments, and applies Platt only to the adjustment total. The market coefficient stays 1. Stored constants are the regular-season fit on rows dated ≤ 2026-03-17 (`PLATT_A = 0.28036258`, `PLATT_B = 2.15982400`, n = 34,507). Playoffs and the play-in are excluded. The holdout is 2026-03-18 → 2026-04-12 (n = 13,751): combined Brier 0.2309 (0.2284–0.2333), signed gap +0.0181, ECE 0.0192, widest bucket 0.0270, against `probability` Brier 0.2440 (0.2403–0.2477), signed gap +0.1105, ECE 0.1105, widest bucket 0.1565. Paired Brier difference −0.0132 (−0.0151 to −0.0112). Scores on the rows that chose A and B are not comparable to that holdout.

`combined_probability` is not the headline. `probability` stays the headline until a separate real-line calibration check passes. That check is a separate ticket. Backtest Analyst verdict: INSUFFICIENT REAL-LINE DATA (2026-11-10).

## Changes

| 檔案 | 變更 |
|---|---|
| `backend/app/models/schemas.py` | `PickSignal` above `DailyPick`. `signals` and `combined_probability` in a self-contained block at the end of `DailyPick`. The block comment names `tier`, `p_over`, and `p_under`. `probability` is unchanged. |
| `backend/app/services/pick_signals.py` | Pure verdicts, modal-line no-vig consensus, and the combined probability. |
| `backend/app/services/pick_signal_constants.py` | Versioned priors. Platt pair fit on rows dated ≤ 2026-03-17. `FIT_SAMPLE` records the cutoff. |
| `backend/app/services/daily_analysis.py` | NBA picks call a new helper after the pick is built. `_group_props_by_player` and both `bookmakers_count=len(lines)` lines are untouched. |
| `backend/tests/test_pick_signals.py` | Thresholds on both sides, missing inputs, recorded Odds API fixture, DailyPick JSON shape, WNBA stays null. |
| `backend/tests/test_daily_analysis_league.py` | WNBA pick asserts `signals is None` and `combined_probability is None`. |
| `scripts/agents/evaluation/walk_forward.py` | NBA rows store `combined_probability` and `combined_adjustment`. WNBA leaves both null. |
| `scripts/agents/evaluation/defense_ranks.py` | No-lookahead CSV defense rank. Rank 1 allowed the most. |
| `scripts/agents/evaluation/metrics.py` | Log loss, ECE, and combined-column Brier, gap, and ECE. |
| `scripts/agents/evaluation/calibration_guard.py` | Same 0.30 / 0.15 bounds on the new column when n ≥ 30. Empty column is skipped. |
| `scripts/agents/evaluation/report.py` | Combined calibration section. |
| `scripts/agents/evaluation/backtest.py` | Daily CSV gains the two columns. |
| `scripts/agents/evaluation/fit_combined_platt.py` | Default `--cutoff 2026-03-17`. Writes that fit. Scores later dates as the holdout. |
| `scripts/agents/tests/test_combined_metrics.py` | Log loss, ECE, and a separate combined column. |
| `scripts/agents/tests/test_defense_ranks.py` | Rank direction, same-day exclusion, position-rank preference. |
| `scripts/agents/tests/test_calibration_guard.py` | Combined failure and the empty-column skip. |
| `docs/decisions/SPO-112/decision_20261110_signal-verdicts-combined-probability.md` | Rules, blend, rank check, numbers, rejected alternatives. |
| `docs/progress.md` | In-flight SPO-112 note. |

## Why

The five labels match PR #40. Verdicts are side-relative, so market, last 10, and history display the side's number rather than the over's number. The history cuts are 0.55 and 0.45, so a rate of 0.65 supports and a rate near 0.56 supports too. The ±0.5 projection cut is flat across metrics and should later scale with each metric's spread.

Platt multiplies only the clipped adjustment. Training rows use a 0.5 market, so a slope on `logit(market) + adjustment` would scale live prices that were never observed. The prototype's 25/25/25/15/10 average is uncalibrated and was not used. `compute_scorecard` stays the agent's gate and is not reused as these signals.

Rank 1 is weakest. The loader copies SportsDataIO's integer with no inversion. The Daily Pick schema and `getMatchupLevel` on the picks page agree. `PlayerProjectionPanel.getMatchupInfo` says the opposite and was left alone. No fixture in the repo pairs `OpponentRank` with points allowed.

`bookmakers_count` still double-counts the two outcomes of one book. That bug is out of scope (SPO-115).

## Tests

```
cd backend && python3 -m pytest
# 856 passed, 23 skipped, 6 xfailed, 2 failed
cd scripts/agents && python3 -m pytest
# 114 passed
```

Rerun after the regular-season merge and the refit. The two backend failures are `test_agent_chat_endpoint_validates_action_and_uses_service` and `test_lineups_api_returns_team_count`. Both die in the rate limiter because Redis is not running in this environment (`ConnectionError` has no `detail`). They do not import the signal module.

- Verdict boundaries for over and under, including the exact cuts.
- Each missing input stays null and adds 0 to the blend.
- WNBA helper and the existing WNBA daily-analysis test leave both fields null.
- Recorded `backend/tests/fixtures/odds_api_event_odds__player_points.json`, loaded with `load_odds_fixture`: Luka Doncic's modal line is 36.5 (5 books). The 37.5 outcomes are filtered out of that consensus. Putting the recorded 37.5 pair back in changes the mean.
- DailyPick JSON shape, and a cached payload without the new fields still parses.
- Calibration guard fails a miscalibrated combined column and skips an empty one.
- Integration test: SKIPPED (not part of this change).
- Fabrication scan: PASS. Market tests load `odds_api_event_odds__player_points.json` through `load_odds_fixture` and keep recorded outcomes. No book, price, or line is typed in those tests.

## Calibration

Stored coefficients: `PLATT_A = 0.28036258`, `PLATT_B = 2.15982400`, fit on 34,507 regular-season NBA MED20 rows dated 2025-11-09 → 2026-03-17. Playoffs and the play-in are excluded by the walk-forward game-type filter. The market term is the fair 0.5 prior. The holdout below is scored with those coefficients and was not used to choose them.

| Slice | n | Combined Brier | Combined signed gap | Probability Brier | Probability signed gap |
|---|---|---|---|---|---|
| Holdout 2026-03-18 → 2026-04-12 | 13,751 | 0.2309 (0.2284–0.2333) | +0.0181 | 0.2440 (0.2403–0.2477) | +0.1105 |

Holdout ECE 0.0192, widest combined bucket 0.0270, log loss 0.6539. `probability` ECE 0.1105, widest bucket 0.1565, log loss 0.7067. Paired Brier difference −0.0132 (95% CI −0.0151 to −0.0112).

The rebaseline after PR #38 is done. The holdout is regular season only and ends 2026-04-12. 4,692 settled playoff and play-in rows were kept out of the fit.

A score on the 34,507 fit rows is not comparable to the holdout. The earlier full-sample fit on all 53,327 rows (Brier 0.2235, gap 0.0000) included the holdout and postseason games and is not comparable either. Those coefficients are not stored.

## Validation status

INSUFFICIENT REAL-LINE DATA (2026-11-10). The proxy-line holdout met the pass bar. `combined_probability` is not the headline. A separate ticket owns the real-line check: at least 1,000 graded two-sided rows. The Backtest Analyst queried the local project database read-only and found `odds_line_snapshots` has 0 rows, even though `odds_snapshot_logs` has 22 runs. The real-line check cannot start until lines are being stored.

## Known limitations

- Early-season fits are unstable. In a rolling monthly check before this rebaseline, January 2026 (trained on November–December only, n = 8,902) had combined Brier 0.2171 versus `probability` 0.2149, and the 0.4–0.5 bucket gap was −0.102.
- With a constant 0.5 market, offline `combined_probability` is a recalibrated adjustment total. On the sample before this rebaseline it shared `history_rate` with `probability` (correlation 0.38 overall, 0.40 on the fit rows, 0.35 on the holdout). `A = 0.2804` encodes that the pick side beats a coin flip, and on a real no-vig market that can double-count recent form. Refit A and B once real lines exist.

Regenerate:

```
cd scripts/agents && python -m evaluation.fit_combined_platt
python scripts/agents/evaluation/backtest.py --report backtest_report.md
```

## Follow-ups

- Separate ticket: real-line calibration before `combined_probability` can replace `probability` as the headline. Needs at least 1,000 graded two-sided rows from `odds_line_snapshots`. That table has 0 rows in the local project database (22 runs are in `odds_snapshot_logs`), so the check cannot start until lines are being stored.
- Regular-season rebaseline after PR #38: done. Stored coefficients are the regular-season fit.
- Scale the ±0.5 projection cut by each metric's spread.
- SPO-115 owns the `bookmakers_count` double-count. This branch does not edit that function.
- `PlayerProjectionPanel` still describes rank 1 as the strongest defense.
