# SPO-112 — Signal verdicts and combined probability

- Ticket: SPO-112
- Branch: `feature/SPO-112-signal-verdicts` (from `dev` @ `a14370d`)
- Base: `dev`

## Summary

NBA Daily Picks now carry five side-relative signals and a calibrated `combined_probability`. A missing input is null on that signal, not a neutral verdict. No modal-line price, or an injury status of Out or Doubtful, leaves `combined_probability` null. WNBA picks get `signals=None` and `combined_probability=None`.

The blend starts from the market no-vig log-odds, adds four capped adjustments, and applies Platt only to the adjustment total. The market coefficient stays 1. Stored constants are the full-sample NBA MED20 fit (`PLATT_A = 0.22281199`, `PLATT_B = 2.37285635`). On the same 53,327 settled picks the combined Brier is 0.2235 (gap 0.0000) against a `probability` Brier of 0.2306 (gap 0.0908). A chronological holdout is 0.2279 versus 0.2420. The frontend headline stays `probability` until the Backtest Analyst signs off, including real lines from `odds_line_snapshots` if enough exist. If they do not, the switch waits.

## Changes

| 檔案 | 變更 |
|---|---|
| `backend/app/models/schemas.py` | `PickSignal` above `DailyPick`. `signals` and `combined_probability` in a self-contained block at the end of `DailyPick`. `probability` is unchanged. |
| `backend/app/services/pick_signals.py` | Pure verdicts, modal-line no-vig consensus, and the combined probability. |
| `backend/app/services/pick_signal_constants.py` | Versioned priors and the fitted Platt pair. |
| `backend/app/services/daily_analysis.py` | NBA picks call a new helper after the pick is built. `_group_props_by_player` and both `bookmakers_count=len(lines)` lines are untouched. |
| `backend/tests/test_pick_signals.py` | Thresholds on both sides, missing inputs, recorded Odds API fixture, DailyPick JSON shape, WNBA stays null. |
| `backend/tests/test_daily_analysis_league.py` | WNBA pick asserts `signals is None` and `combined_probability is None`. |
| `scripts/agents/evaluation/walk_forward.py` | NBA rows store `combined_probability` and `combined_adjustment`. WNBA leaves both null. |
| `scripts/agents/evaluation/defense_ranks.py` | No-lookahead CSV defense rank. Rank 1 allowed the most. |
| `scripts/agents/evaluation/metrics.py` | Log loss, ECE, and combined-column Brier, gap, and ECE. |
| `scripts/agents/evaluation/calibration_guard.py` | Same 0.30 / 0.15 bounds on the new column when n ≥ 30. Empty column is skipped. |
| `scripts/agents/evaluation/report.py` | Combined calibration section. |
| `scripts/agents/evaluation/backtest.py` | Daily CSV gains the two columns. |
| `scripts/agents/evaluation/fit_combined_platt.py` | Refits `PLATT_A` and `PLATT_B` and prints the holdout. |
| `scripts/agents/tests/test_combined_metrics.py` | Log loss, ECE, and a separate combined column. |
| `scripts/agents/tests/test_defense_ranks.py` | Rank direction, same-day exclusion, position-rank preference. |
| `scripts/agents/tests/test_calibration_guard.py` | Combined failure and the empty-column skip. |
| `docs/decisions/SPO-112/decision_20261110_signal-verdicts-combined-probability.md` | Rules, blend, rank check, numbers, rejected alternatives. |
| `docs/progress.md` | In-flight SPO-112 note. |

## Why

The five labels match PR #40. Verdicts are side-relative, so market, last 10, and history display the side's number rather than the over's number. A published pick is at least 0.65, so the history signal is Supports on every pick that ships. The ±0.5 projection cut is flat across metrics and should later scale with each metric's spread.

Platt multiplies only the clipped adjustment. Training rows use a 0.5 market, so a slope on `logit(market) + adjustment` would scale live prices that were never observed. The prototype's 25/25/25/15/10 average is uncalibrated and was not used. `compute_scorecard` stays the agent's gate and is not reused as these signals.

Rank 1 is weakest. The loader copies SportsDataIO's integer with no inversion. The Daily Pick schema and `getMatchupLevel` on the picks page agree. `PlayerProjectionPanel.getMatchupInfo` says the opposite and was left alone. No fixture in the repo pairs `OpponentRank` with points allowed.

`bookmakers_count` still double-counts the two outcomes of one book. That bug is out of scope (SPO-115).

## Tests

```
cd backend && python3 -m pytest
# 835 passed, 23 skipped, 6 xfailed, 2 failed
cd scripts/agents && python3 -m pytest
# 94 passed
```

The two backend failures are `test_agent_chat_endpoint_validates_action_and_uses_service` and `test_lineups_api_returns_team_count`. Both die in the rate limiter because Redis is not running in this environment (`ConnectionError` has no `detail`). They do not import the signal module.

- Verdict boundaries for over and under, including the exact cuts.
- Each missing input stays null and adds 0 to the blend.
- WNBA helper and the existing WNBA daily-analysis test leave both fields null.
- Recorded `backend/tests/fixtures/odds_api_event_odds__player_points.json`: Luka Doncic's modal line is 36.5 (5 books). The 37.5 pair is excluded. Adding BetMGM's `(−105, −125)` changes the mean.
- DailyPick JSON shape, and a cached payload without the new fields still parses.
- Calibration guard fails a miscalibrated combined column and skips an empty one.
- Integration test: SKIPPED (not part of this change).
- Fabrication scan: PASS. The market test reads the recorded Odds API fixture. No invented book payload.

## Calibration

Same settled NBA MED20 picks. Market term is the fair 0.5 prior. Full-sample constants are what the module stores.

| Slice | n | Combined Brier | Combined gap | Probability Brier | Probability gap |
|---|---|---|---|---|---|
| In-sample | 53,327 | 0.2235 (0.2223–0.2248) | 0.0000 | 0.2306 (0.2288–0.2325) | 0.0908 |
| Holdout after 2026-03-17 | 18,817 | 0.2279 (0.2258–0.2300) | 0.0161 | 0.2420 (0.2388–0.2451) | 0.1081 |

In-sample combined log loss 0.6386, ECE 0.0024, widest bucket gap 0.0149. Holdout log loss 0.6475, ECE 0.0229, widest bucket gap 0.0359. Probability log loss is 0.7030 in-sample and 0.6980 on the holdout. ECE on the pick edges (from 0.65) matches the probability gap on both slices.

`backtest_report.md` (2026-11-09) measured probability Brier 0.227 and gap 0.077 on 55,708 picks. This CSV load is 573 NBA players and 53,327 settled picks. Compare combined with `probability` on the same rows.

Regenerate:

```
cd scripts/agents && python -m evaluation.fit_combined_platt
python scripts/agents/evaluation/backtest.py --report backtest_report.md
```

## Follow-ups

- Backtest Analyst validates before `combined_probability` replaces `probability` as the headline. That includes production `odds_line_snapshots` when the table has enough two-sided lines. If it does not, the switch waits.
- Scale the ±0.5 projection cut by each metric's spread.
- SPO-115 owns the `bookmakers_count` double-count. This branch does not edit that function.
- `PlayerProjectionPanel` still describes rank 1 as the strongest defense.
