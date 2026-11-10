# Decision — Signal verdicts and combined probability

- **Epic:** SPO-112 — per-prop signal verdicts and a combined probability on Daily Pick
- **Date:** 2026-11-10
- **Author:** CTO
- **Status:** Accepted

## Context

Daily Pick already publishes one historical rate, `probability`, for the chosen side. The redesign wants five readable signals on that pick, each with a verdict relative to the side, plus one calibrated probability for the same side.

NBA only. WNBA picks keep the fields and leave both null. Nothing in this change adds a WNBA signal path.

`DailyPick` is a Redis cache model. Another branch (SPO-111) adds `tier`, `p_over`, and `p_under` in the same class. The two new fields sit in their own block at the end of the model so that merge stays a matter of keeping both blocks. `probability` is not redefined.

Another branch (SPO-115) edits `_group_props_by_player` and the two `bookmakers_count=len(lines)` assignments in `daily_analysis.py`. Those lines are unchanged here. Per-book prices for the market signal are read by a new helper, `american_pairs_at_line`, from the bookmaker list the pipeline already fetched.

## Decision

### Schema

`PickSignal` sits immediately above `DailyPick` in `backend/app/models/schemas.py`.

| Field | Meaning |
|---|---|
| `key` | Stable id: `market`, `last10`, `history`, `projection`, `defense` |
| `label` | Display label, matching frontend PR #40 |
| `value` | Display text. `None` when the input is missing |
| `verdict` | `supports`, `neutral`, or `against`, relative to the pick's side. `None` when the input cannot be judged |

`DailyPick` gains, in a marked block that should stay intact:

- `signals: list[PickSignal] | None = None`
- `combined_probability: float | None = None` (0 to 1, the calibrated probability of the pick's side)

An NBA pick always carries all five signals, in that order. A missing input is `value=None` and `verdict=None`. It is not stored as `neutral`, and it does not count as a neutral vote. WNBA leaves `signals` and `combined_probability` null.

### The five signals

Every cut is relative to the published side (over or under). Keys and labels match `frontend/lib/event-page.ts` on `feature/SPO-110b-game-page` (PR #40).

| Key | Label | Value | Supports | Against | Neutral |
|---|---|---|---|---|---|
| `market` | Market price | No-vig consensus of the side, as a percent | `>= 0.52` | `<= 0.48` | between the cuts |
| `last10` | Last 10 games | Strict hits, `k/10` | `>= 6` | `<= 4` | 5 |
| `history` | All-game hit rate | The existing `probability` | `>= 0.55` | `<= 0.45` | between the cuts |
| `projection` | Projection | `projected_value`, one decimal | directional edge `>= +0.5` | directional edge `<= -0.5` | between the cuts |
| `defense` | Opponent defense | `#rank` | see below | see below | rank 11–20 |

`market` uses only books that post both Over and Under at the pick's line (the modal line). Alternate ladders are dropped. Each book contributes one pair. The pair is de-vigged with `prob.devig`, then the fair pairs are averaged with `calculate_consensus_mean`. The displayed value is the side's fair probability, not always the over. No book at that line means `value=None`, `verdict=None`, and `combined_probability=None`. Production does not substitute 0.5.

`last10` counts strict hits in the last 10 non-DNP games. Over is `value > line`. Under is `value < line`. A push is a miss for both sides. Fewer than 10 numeric values is missing (`value=None`, `verdict=None`), not a short sample. The adjustment for a missing window is 0.

`history` is the published side rate. Every published pick is at least 0.65, which is above 0.55, so this signal reads Supports on every pick that actually ships. The pure function still implements the 0.55 / 0.45 cuts so a caller can test a rate that would not be published.

`projection` displays `projected_value` with one decimal, half away from zero, matching the client's `toFixed(1)`. The edge is measured in the side's direction: over is `projected − line`, under is `line − projected`. The stored `DailyPick.edge` stays `projected − line`.

The ±0.5 point cut is the same for every metric. It should later be scaled by that metric's spread (for example its standard deviation). A 0.5-point edge on points is not the same evidence as 0.5 on threes.

`defense` prefers `opponent_position_rank` and falls back to `opponent_rank`. Display is `#8` for an integer rank. Rank 1 is the weakest defense, which is the direction stored on `DailyPick`. For an over, rank `<= 10` supports and rank `> 20` is against. An under is the mirror. Rank 11–20 is neutral.

Lineup and injury are not signals. If `injury_status` is `Out` or `Doubtful` (case-insensitive, surrounding whitespace stripped), `combined_probability` is null. The five signals are still attached.

### Defense-rank direction

Checked against the load path, not against a second UI comment.

- `projection_provider.FIELD_MAPPING` copies `OpponentRank` to `opponent_rank` and `OpponentPositionRank` to `opponent_position_rank`.
- `normalize_projection` assigns that value through. There is no `31 - rank` and no other inversion.
- `DailyPick.opponent_rank` is documented as `1-30, 1=weakest defense`.
- `frontend/app/picks/page.tsx` `getMatchupLevel` treats 1–10 as Easy (weak defense, good for the offensive player) and 21–30 as Hard. That page is the Daily Pick consumer.
- `docs/player-stats-projection-api.md` calls the field a defensive-strength rank and does not say which end is 1.
- No recorded SportsDataIO projection payload in this repo pairs a real `OpponentRank` with points allowed, so the direction was not re-measured from a fixture.
- `frontend/components/PlayerProjectionPanel.tsx` `getMatchupInfo` says the opposite (1 = strongest, 1–10 Hard). That comment is not the load path and is not changed here.

The approved cuts stand: 1 is weakest. The walk-forward proxy uses the same direction (rank 1 allowed the most of that stat before the date).

### Combined probability

Option A, with one justified change to how Platt is applied.

Start from the market no-vig log-odds of the side. Add four bounded log-odds adjustments (last 10, history, defense, projection). Clip each at ±0.15 and the sum at ±0.35. A missing input adds 0. That is "no information". It is not a neutral verdict.

The priors, not fit from outcomes, live in `backend/app/services/pick_signal_constants.py` (`CONSTANTS_VERSION = "spo112-v1"`):

| Constant | Value | Role |
|---|---|---|
| `LAST10_LOGIT_WEIGHT` | 0.25 | Times the logit of hits/10 |
| `HISTORY_LOGIT_WEIGHT` | 0.10 | Times the logit of the side rate |
| `DEFENSE_WEIGHT` | 0.15 | Times `(15.5 − rank) / 14.5` for an over, negated for an under. Rank 1 is +1, rank 30 is −1, so the weight lands on ±0.15 |
| `PROJECTION_EDGE_WEIGHT` | 0.04 | Per point of directional edge. ±0.5 moves log-odds by 0.02. The cap binds at ±3.75 points. Small because there is no projection history |
| `ADJUSTMENT_CAP` | 0.15 | Per term |
| `TOTAL_ADJUSTMENT_CAP` | 0.35 | On the sum |
| `OFFLINE_MARKET_PRIOR` | 0.5 | Walk-forward only |

**Justified change.** Platt is applied only to the clipped adjustment total. The market log-odds is then added with coefficient 1:

```
combined = sigmoid(logit(market) + PLATT_A + PLATT_B * clipped_adjustment)
```

On the training rows the market prior is 0.5, so `logit(market)` is 0 and this is ordinary Platt of the adjustment. Applying Platt to `logit(market) + adjustment` would multiply the unfitted market by `PLATT_B`. The market coefficient stays 1 because the training set has no market variation. The result is rounded to 4 decimals and clipped to `[0.0001, 0.9999]`.

Fitted on the NBA MED20 walk-forward replay (`cd scripts/agents && python -m evaluation.fit_combined_platt`), full sample, market prior 0.5:

| | Value |
|---|---|
| `PLATT_A` | 0.22281199 |
| `PLATT_B` | 2.37285635 |
| Settled picks | 53,327 |
| Dates | 2025-11-09 → 2026-05-11 |

What is fit: the intercept and the slope on the adjustment total. What is a prior: the four weights, the caps, the projection term (the replay has no projection, so that adjustment is 0), and the market coefficient. The replay's defense rank is a no-lookahead CSV proxy (mean of that stat allowed before the date), not the SportsDataIO fantasy rank production will load. Position rank is used when that position has at least 8 prior player-games against the opponent; otherwise the overall rank is used when the opponent has at least 20; otherwise the rank is missing. Same-day games are excluded. Ties break by opponent name.

### probability vs p_over / p_under vs combined_probability

`probability` is the published historical rate of the chosen side. `p_over` and `p_under` (added on the SPO-111 branch, not here) are the stored per-side historical rates the tier and the default side are based on. `choose_daily_pick_side` and the 0.65 publish rule keep using those rates.

`combined_probability` is a separate estimate for the pick's side. It is not a replacement for `probability` in this change. The frontend keeps `probability` as the headline until the Backtest Analyst signs off, and that check has to include real lines from production `odds_line_snapshots` when enough of them exist. This repo has no historical sportsbook lines, so that check cannot be closed here. If there are not enough real lines, the headline switch waits.

### Reading the values against PR #40

PR #40 names the five keys and labels and does not assign Supports / Neutral / Against. The prototype on PR #39 (`docs/design/redesign-2026-11/`) used verdict tokens `for` / `against` / `neutral`, displayed as Supports / Against / Neutral, and a history label of "Season hit rate". This API uses `supports` / `neutral` / `against` and the PR #40 label "All-game hit rate".

The prototype also showed the over percent for market and history, and counted only overs for the last 10. This API returns the side's number for all three, so the displayed value and the verdict describe the same side. That is intentional: the approved rules are side-relative, and the history input is the existing `probability`.

### Calibration on this replay

Same settled NBA MED20 picks. The market term is the fair 0.5 prior. `probability` is the published side rate. Intervals are a normal approximation of the Brier score.

In-sample (the stored constants; not the final validation):

| | n | Brier (95% CI) | Gap | Log loss | ECE | Widest \|bucket gap\| | Mean predicted | Hit rate |
|---|---|---|---|---|---|---|---|---|
| `combined_probability` | 53,327 | 0.2235 (0.2223–0.2248) | 0.0000 | 0.6386 | 0.0024 | 0.0149 | 0.6434 | 0.6434 |
| `probability` | 53,327 | 0.2306 (0.2288–0.2325) | 0.0908 | 0.7030 | 0.0908 | — | 0.7343 | 0.6434 |

Chronological holdout. Platt was fit on dates on or before 2026-03-17 (about the first 70% of unique pick dates) and scored on the rest. Those constants are not the ones stored. Stored constants are the full-sample fit.

| | n | Brier (95% CI) | Gap | Log loss | ECE | Widest \|bucket gap\| | Mean predicted | Hit rate |
|---|---|---|---|---|---|---|---|---|
| `combined_probability` | 18,817 | 0.2279 (0.2258–0.2300) | 0.0161 | 0.6475 | 0.0229 | 0.0359 | 0.6369 | 0.6208 |
| `probability` | 18,817 | 0.2420 (0.2388–0.2451) | 0.1081 | 0.6980 | 0.1081 | — | 0.7289 | 0.6208 |

Holdout fit: `A = 0.28010420`, `B = 2.16005911`.

On these rows, both the in-sample and the holdout combined score beat `probability` on Brier, gap, log loss, and ECE. No combined reliability bucket is wider than 0.10. The in-sample gap is ~0 because the intercept was fit on those same rows. That is not a license to change the headline.

The checked-in `backtest_report.md` (generated 2026-11-09) reports NBA MED20 `probability` at Brier 0.227 and gap 0.077 on 55,708 picks, from a CSV load of 579 players. This replay loaded 573 players and scored 53,327 settled picks. The comparison above is same-row. It is not a claim that 0.2235 replaces the 0.227 headline in that older report.

Combined ECE uses deciles `(0.0, 0.1, …, 1.0, 1.0001)`. ECE for `probability` uses the existing pick edges, which start at 0.65, because a published pick is never below that. A prediction outside the edges is left out of ECE.

WNBA rows leave the column null. The calibration guard skips a league with fewer than 30 combined values instead of failing it. At 30 or more it uses the same bounds as the published probability: Brier 0.30 and absolute gap 0.15.

Regenerate the fit (no external API):

```
cd scripts/agents && python -m evaluation.fit_combined_platt
```

The full report, including the combined section, is:

```
python scripts/agents/evaluation/backtest.py --report backtest_report.md
```

The guard sample the CI job already runs is `pytest` on `scripts/agents/tests/test_calibration_guard.py` (40 players per league, seed 7, MED20).

## Alternatives

1. **Prototype blend, 25/25/25/15/10.** The redesign prototype averages the five signals with those weights. Rejected. The weights are not calibrated, a missing input would have to be invented or the weights renormalized, and the average is not a probability of the side.
2. **Reuse `compute_scorecard` from `scripts/agents/scoring.py`.** Rejected. The scorecard is the agent's bet/pass gate. It is not the five display signals, and it does not produce this combined probability.
3. **Platt on `logit(market) + adjustment`.** Rejected for this fit. With a constant 0.5 market, the slope would be unidentified as a market coefficient and would then scale live prices that were never in the training set. The slope stays on the adjustment only.

## Tradeoffs

The in-sample intercept absorbs the known overconfidence of `probability` (about 0.73 predicted versus about 0.64 hits on this replay). A later fit on real closing lines can move both coefficients. Until then, a live market far from 0.5 is passed through at coefficient 1 and only shifted by the adjustment.

Projection barely moves the blend. That is deliberate. There is nothing in the CSV to fit it against.

The walk-forward defense rank will not match tomorrow's SportsDataIO rank. It exists so the defense term can be fit at all. Production still reads the integer the projection loader stored.

`bookmakers_count` still counts each outcome, so one book with an Over and an Under contributes 2. That double count is left for SPO-115.

## Impact

- NBA `GET` daily picks responses gain `signals` and `combined_probability`. Cached payloads written before this change still parse: both fields default to null.
- WNBA responses gain the same keys, always null.
- The walk-forward CSV gains `combined_probability` and `combined_adjustment`. The second column is the pre-Platt clipped total, so Platt can be refit without another feature pass.
- Frontend headline stays `probability`.

## Links

- Task summary: `docs/task-summaries/SPO-112-signal-verdicts.md`
- Constants: `backend/app/services/pick_signal_constants.py`
- Pure functions: `backend/app/services/pick_signals.py`
- Fit: `scripts/agents/evaluation/fit_combined_platt.py`
- Checked-in baseline report: `backtest_report.md`
