# Sports Lab walk-forward backtest

Generated 2026-11-10 03:53 UTC. Command: `python scripts/agents/evaluation/backtest.py --report backtest_report.md`. Elapsed 76s.

The previous `scripts/agents/evaluation/backtest.py` scored five hard-coded players
in-sample: the "actual rate" was the same history the model had just fit.
This report walks forward. Each headline player-game is a regular-season
game scored with that player's regular-season, non-DNP games dated strictly
before it. That is the set `CSVPlayerHistoryService._allowed_game_types`
uses in production, and it is the information Daily Picks and the scorecard
would have had on the morning of the game if the CSV had been frozen there.
Playoff and play-in games are scored with that same history and reported
in their own section. They are not in the headline tables.

## Assumptions

(a) The repo has no historical sportsbook lines, so hit rates are measured against a proxy line. The default proxy, MED20, is the x.5 line that splits the player's last 20 games closest to 50/50. The L10 alternative is also supported.

(b) ROI assumes -110 on every bet.

(c) CLV is not measured.

This run loaded no odds file. The CLV hook is inactive and was skipped. (b) and (c) apply to every pick.

L5 (`floor` of the last 5 games, plus 0.5) and ALL (the same rule on every
prior game) are extra sensitivity proxies. They are not the default.
MED20 ties go to the lower x.5 line. Candidate lines are the positive
half-point numbers from `floor(min) - 0.5` through `floor(max) + 0.5`.

## Data

| League | Rows | Players | File dates | Season labels | Duplicate player-dates | Multi-team players | Rows before 2025-10-21 |
|---|---|---|---|---|---|---|---|
| NBA | 28,820 | 573 | 2024-10-22 → 2026-05-11 | 2024-2025=730, 2025-2026=28090 | none | 74 | 730 |
| WNBA | 4,875 | 147 | 2025-05-16 → 2026-05-08 | 2025=4836, 2026=39 | none | 24 | 4,836 |

Headline target windows (a regular-season game is scored only if it has at
least 10 prior regular-season non-DNP games, the same floor as `MIN_SAMPLE_GAMES`):

- **NBA** configured start 2025-10-21; scored targets 2025-11-09 → 2026-04-12 (21,236 player-games).
- **WNBA** configured start 2025-05-01; scored targets 2025-06-11 → 2026-05-08 (3,198 player-games).

## Method

**Daily Picks.** For each supported market in `daily_analysis.SUPPORTED_MARKETS`,
the over rate is the share of prior games strictly above the line and the under
rate is the share strictly below it, rounded to 4 decimals. That is the return
value of `CSVPlayerHistoryService.get_player_stats(n=0, exclude_dnp=True)`,
which reads regular-season games only unless the caller opts in.
The side comes from `choose_daily_pick_side`: over when `p_over` clears
`HIGH_PROBABILITY_THRESHOLD` (0.65), otherwise under when `p_under` does.
The tier is the frontend `getProbabilityLevel`: high at or above 0.70,
otherwise medium. A sample of replay rates is checked against the real
`get_player_stats` on a cache that contains only the prior games.

**Agent scorecard.** `tools.historical` and `scoring.compute_scorecard` run
on a cache that has been swapped to those same prior games, for points,
rebounds, assists, and pra. There is no stored market price, lineup, or
injury report, so the returned decision is avoid and `eligible_for_bet`
is false. The tables below the avoid rate use the pre-gate side:
`decision_from_over_probability` on the unrounded model probability
(over at or above 0.55, under at or below 0.45). The published probability
is rounded to 4 decimals and that rounding can cross the band, so the side
is decided before rounding. That is the market gate ignored, and nothing else.
A push (`actual == line`) refunds the stake: profit is 0, and the bet is left
out of the hit rate and the Brier score.

**Naive baseline.** `naive = (over picks × over-rate of every prop in the group
+ under picks × under-rate of every prop) / picks`. Lift is the pick hit rate
minus that number, in percentage points. It is the hit rate of the same mix
of directions if the directions had been assigned without looking at which
props were extreme. On a direction-only split the group is already one side,
so the baseline equals the hit rate and the lift is zero.

**Intervals.** The hit-rate interval is a Wilson 95% interval. When every
pick is priced at -110, the ROI interval is that Wilson interval passed
through `roi = hit_rate × 210/110 − 1`. When a pick carries a real American
price, the ROI interval is a normal approximation on the mean profit.
The Brier interval is a normal approximation on the mean squared error.
Picks that share a game are not independent, so every interval is too narrow.

## Daily Picks, proxy MED20

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba | 233596 | 48258 | 64.5 (64.1–65.0) | +23.2 (+22.4–+24.0) | 0.230 (0.228–0.232) | 73.5 | 50.4 | +14.2 |
| wnba | 35178 | 5433 | 68.1 (66.8–69.3) | +29.9 (+27.6–+32.3) | 0.212 (0.206–0.218) | 74.7 | 50.8 | +17.2 |

### By market

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / assists | 21236 | 4742 | 61.9 (60.5–63.3) | +18.2 (+15.5–+20.8) | 0.245 (0.239–0.251) | 71.8 | 50.0 | +11.9 |
| nba / fgm | 21236 | 3698 | 59.7 (58.1–61.2) | +13.9 (+10.8–+16.9) | 0.253 (0.247–0.260) | 70.2 | 49.7 | +9.9 |
| nba / ftm | 21236 | 7433 | 70.0 (68.9–71.0) | +33.6 (+31.5–+35.5) | 0.210 (0.204–0.216) | 77.0 | 56.8 | +13.1 |
| nba / pa | 21236 | 2659 | 57.0 (55.1–58.9) | +8.8 (+5.2–+12.4) | 0.265 (0.257–0.272) | 70.0 | 49.5 | +7.5 |
| nba / points | 21236 | 2780 | 56.9 (55.1–58.7) | +8.6 (+5.1–+12.1) | 0.264 (0.256–0.271) | 69.8 | 49.6 | +7.3 |
| nba / pr | 21236 | 2571 | 57.0 (55.1–58.9) | +8.9 (+5.2–+12.5) | 0.263 (0.256–0.271) | 69.8 | 49.5 | +7.5 |
| nba / pra | 21236 | 2572 | 56.0 (54.1–57.9) | +7.0 (+3.3–+10.6) | 0.268 (0.260–0.276) | 70.0 | 49.5 | +6.6 |
| nba / ra | 21236 | 2656 | 59.7 (57.8–61.5) | +13.9 (+10.3–+17.5) | 0.251 (0.243–0.258) | 69.9 | 49.7 | +9.9 |
| nba / rebounds | 21236 | 3056 | 60.3 (58.5–62.0) | +15.1 (+11.7–+18.4) | 0.249 (0.242–0.256) | 69.5 | 49.9 | +10.4 |
| nba / steals | 21236 | 7839 | 67.1 (66.0–68.1) | +28.1 (+26.1–+30.0) | 0.224 (0.219–0.229) | 74.2 | 53.0 | +14.0 |
| nba / threes_made | 21236 | 8252 | 74.1 (73.1–75.0) | +41.5 (+39.6–+43.3) | 0.176 (0.171–0.181) | 79.4 | 54.3 | +19.8 |
| wnba / assists | 3198 | 496 | 63.1 (58.8–67.2) | +20.5 (+12.2–+28.4) | 0.235 (0.216–0.253) | 71.8 | 49.8 | +13.3 |
| wnba / fgm | 3198 | 318 | 64.5 (59.1–69.5) | +23.1 (+12.8–+32.7) | 0.233 (0.212–0.255) | 69.7 | 50.0 | +14.5 |
| wnba / ftm | 3198 | 942 | 70.8 (67.8–73.6) | +35.2 (+29.5–+40.5) | 0.205 (0.190–0.221) | 76.3 | 57.7 | +13.1 |
| wnba / pa | 3198 | 116 | 57.8 (48.7–66.4) | +10.3 (-7.1–+26.7) | 0.250 (0.218–0.281) | 67.6 | 49.4 | +8.3 |
| wnba / points | 3198 | 156 | 60.3 (52.4–67.6) | +15.0 (+0.1–+29.1) | 0.250 (0.222–0.279) | 68.1 | 49.7 | +10.5 |
| wnba / pr | 3198 | 121 | 55.4 (46.5–63.9) | +5.7 (-11.3–+22.0) | 0.264 (0.231–0.297) | 68.3 | 50.3 | +5.1 |
| wnba / pra | 3198 | 136 | 59.6 (51.2–67.4) | +13.7 (-2.3–+28.7) | 0.251 (0.221–0.282) | 68.1 | 49.9 | +9.6 |
| wnba / ra | 3198 | 268 | 61.9 (56.0–67.5) | +18.2 (+6.9–+29.0) | 0.242 (0.219–0.264) | 69.0 | 50.3 | +11.6 |
| wnba / rebounds | 3198 | 303 | 59.7 (54.1–65.1) | +14.0 (+3.3–+24.3) | 0.248 (0.227–0.270) | 69.1 | 50.0 | +9.7 |
| wnba / steals | 3198 | 1236 | 66.3 (63.7–68.9) | +26.7 (+21.5–+31.6) | 0.226 (0.214–0.239) | 73.3 | 53.7 | +12.7 |
| wnba / threes_made | 3198 | 1341 | 77.3 (75.0–79.5) | +47.6 (+43.2–+51.8) | 0.159 (0.147–0.171) | 82.1 | 59.0 | +18.3 |

### By confidence tier

The tier is only defined for picks. Naive and lift inside a tier use that
tier's own props, which are the picks, so they are not the headline baseline.

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / high (>=0.70) | 26314 | 26314 | 68.7 (68.2–69.3) | +31.2 (+30.1–+32.3) | 0.216 (0.213–0.219) | 78.8 | 57.2 | +11.6 |
| nba / medium [0.65, 0.70) | 21944 | 21944 | 59.5 (58.9–60.2) | +13.6 (+12.4–+14.9) | 0.247 (0.245–0.249) | 67.2 | 50.2 | +9.3 |
| wnba / high (>=0.70) | 3126 | 3126 | 72.6 (71.0–74.1) | +38.6 (+35.5–+41.5) | 0.193 (0.184–0.202) | 80.3 | 61.5 | +11.1 |
| wnba / medium [0.65, 0.70) | 2307 | 2307 | 61.9 (59.9–63.9) | +18.3 (+14.4–+22.0) | 0.238 (0.231–0.244) | 67.1 | 50.7 | +11.3 |

### By direction

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / over | 14105 | 14105 | 62.7 (61.9–63.5) | +19.8 (+18.3–+21.3) | 0.238 (0.235–0.241) | 69.5 | 62.7 | +0.0 |
| nba / under | 34153 | 34153 | 65.3 (64.8–65.8) | +24.6 (+23.7–+25.6) | 0.227 (0.224–0.229) | 75.2 | 65.3 | +0.0 |
| wnba / over | 1462 | 1462 | 62.0 (59.5–64.4) | +18.3 (+13.5–+23.0) | 0.240 (0.231–0.250) | 69.3 | 62.0 | +0.0 |
| wnba / under | 3971 | 3971 | 70.3 (68.9–71.7) | +34.2 (+31.5–+36.9) | 0.201 (0.194–0.209) | 76.7 | 70.3 | +0.0 |

### By month

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / 2025-11 | 25916 | 3093 | 66.9 (65.2–68.5) | +27.7 (+24.5–+30.8) | 0.221 (0.212–0.229) | 76.3 | 49.5 | +17.4 |
| nba / 2025-12 | 42482 | 5809 | 66.7 (65.5–67.9) | +27.4 (+25.0–+29.7) | 0.219 (0.213–0.224) | 75.1 | 50.8 | +15.9 |
| nba / 2026-01 | 52998 | 9611 | 67.7 (66.8–68.7) | +29.3 (+27.5–+31.1) | 0.215 (0.211–0.219) | 73.4 | 50.9 | +16.8 |
| nba / 2026-02 | 37532 | 8079 | 63.8 (62.8–64.9) | +21.9 (+19.9–+23.9) | 0.231 (0.227–0.236) | 72.9 | 50.0 | +13.8 |
| nba / 2026-03 | 53757 | 15109 | 63.5 (62.7–64.2) | +21.1 (+19.7–+22.6) | 0.235 (0.232–0.239) | 72.9 | 50.7 | +12.7 |
| nba / 2026-04 | 20911 | 6557 | 60.2 (59.0–61.4) | +14.9 (+12.7–+17.2) | 0.253 (0.248–0.259) | 73.1 | 49.5 | +10.7 |
| wnba / 2025-06 | 5687 | 715 | 64.6 (61.0–68.0) | +23.4 (+16.5–+29.9) | 0.236 (0.217–0.254) | 76.8 | 49.7 | +14.9 |
| wnba / 2025-07 | 10439 | 1339 | 68.0 (65.4–70.4) | +29.7 (+24.9–+34.4) | 0.215 (0.203–0.228) | 75.9 | 50.5 | +17.5 |
| wnba / 2025-08 | 13915 | 2329 | 68.1 (66.2–70.0) | +30.0 (+26.3–+33.6) | 0.210 (0.201–0.218) | 73.8 | 51.2 | +16.9 |
| wnba / 2025-09 | 4895 | 1001 | 71.1 (68.2–73.9) | +35.8 (+30.3–+41.0) | 0.194 (0.182–0.207) | 73.7 | 51.8 | +19.3 |
| wnba / 2026-05 | 242 | 49 | 57.1 (43.3–70.0) | +9.1 (-17.4–+33.6) | 0.248 (0.188–0.308) | 73.2 | 49.3 | +7.8 |

### Pick composition

| League | Picks | Under share | 0.5-line share | Prob ≥ 0.95 share |
|---|---|---|---|---|
| NBA | 48258 | 70.8 | 47.1 | 4.7 |
| WNBA | 5433 | 73.1 | 65.5 | 7.5 |

### Calibration of the pick probability

**NBA**

| Bucket | N | Avg predicted | Actual | Gap (pred−actual) |
|---|---|---|---|---|
| [0.65, 0.7) | 21944 | 0.672 | 0.595 | 0.077 |
| [0.7, 0.75) | 11522 | 0.720 | 0.624 | 0.096 |
| [0.75, 0.8) | 6022 | 0.768 | 0.647 | 0.121 |
| [0.8, 0.85) | 3243 | 0.819 | 0.693 | 0.126 |
| [0.85, 0.9) | 1739 | 0.871 | 0.792 | 0.080 |
| [0.9, 0.95) | 1542 | 0.920 | 0.821 | 0.099 |
| [0.95, 1) | 2246 | 0.991 | 0.942 | 0.049 |

**WNBA**

| Bucket | N | Avg predicted | Actual | Gap (pred−actual) |
|---|---|---|---|---|
| [0.65, 0.7) | 2307 | 0.671 | 0.619 | 0.052 |
| [0.7, 0.75) | 1221 | 0.717 | 0.630 | 0.087 |
| [0.75, 0.8) | 586 | 0.765 | 0.677 | 0.088 |
| [0.8, 0.85) | 459 | 0.820 | 0.760 | 0.060 |
| [0.85, 0.9) | 236 | 0.872 | 0.818 | 0.054 |
| [0.9, 0.95) | 217 | 0.919 | 0.802 | 0.117 |
| [0.95, 1) | 407 | 0.994 | 0.951 | 0.043 |

### Calibration of p_over on every prop

| League | Props | Brier(p_over) | Brier(constant 0.5) | Brier(base rate) | Actual over% | Mean p_over% |
|---|---|---|---|---|---|---|
| NBA | 233596 | 0.2456 | 0.2500 | 0.2499 | 49.09 | 47.13 |
| WNBA | 35178 | 0.2434 | 0.2500 | 0.2497 | 48.17 | 47.21 |

**NBA**

| Bucket | N | Avg predicted | Actual | Gap (pred−actual) |
|---|---|---|---|---|
| [0, 0.1) | 3557 | 0.034 | 0.101 | -0.067 |
| [0.1, 0.2) | 4401 | 0.153 | 0.257 | -0.104 |
| [0.2, 0.3) | 12175 | 0.255 | 0.378 | -0.122 |
| [0.3, 0.4) | 33785 | 0.355 | 0.429 | -0.074 |
| [0.4, 0.5) | 66485 | 0.447 | 0.477 | -0.031 |
| [0.5, 0.6) | 80380 | 0.537 | 0.532 | 0.005 |
| [0.6, 0.7) | 27396 | 0.636 | 0.585 | 0.051 |
| [0.7, 0.8) | 5236 | 0.730 | 0.658 | 0.072 |
| [0.8, 0.9) | 179 | 0.822 | 0.693 | 0.129 |
| [0.9, 1) | 2 | 0.913 | 1.000 | -0.087 |

**WNBA**

| Bucket | N | Avg predicted | Actual | Gap (pred−actual) |
|---|---|---|---|---|
| [0, 0.1) | 583 | 0.027 | 0.081 | -0.053 |
| [0.1, 0.2) | 616 | 0.151 | 0.214 | -0.063 |
| [0.2, 0.3) | 1233 | 0.255 | 0.335 | -0.079 |
| [0.3, 0.4) | 4292 | 0.358 | 0.407 | -0.049 |
| [0.4, 0.5) | 10819 | 0.446 | 0.474 | -0.028 |
| [0.5, 0.6) | 13693 | 0.531 | 0.523 | 0.008 |
| [0.6, 0.7) | 3381 | 0.632 | 0.579 | 0.053 |
| [0.7, 0.8) | 549 | 0.727 | 0.634 | 0.093 |
| [0.8, 0.9) | 12 | 0.806 | 0.500 | 0.306 |

### Proxy sensitivity

The level moves with the proxy. That is the reason the absolute hit rate
is not a market edge: MED20, L10, L5, and ALL are different questions.

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / ALL | 233596 | 42240 | 65.0 (64.6–65.5) | +24.2 (+23.3–+25.0) | 0.227 (0.224–0.229) | 73.9 | 54.4 | +10.7 |
| nba / L10 | 233596 | 91663 | 64.3 (64.0–64.6) | +22.8 (+22.2–+23.4) | 0.236 (0.235–0.238) | 74.3 | 54.2 | +10.2 |
| nba / L5 | 233596 | 118169 | 67.7 (67.5–68.0) | +29.3 (+28.8–+29.8) | 0.223 (0.222–0.224) | 76.2 | 53.6 | +14.1 |
| nba / MED20 | 233596 | 48258 | 64.5 (64.1–65.0) | +23.2 (+22.4–+24.0) | 0.230 (0.228–0.232) | 73.5 | 50.4 | +14.2 |
| wnba / ALL | 35178 | 6637 | 65.7 (64.5–66.8) | +25.4 (+23.2–+27.5) | 0.222 (0.217–0.228) | 74.0 | 55.8 | +9.9 |
| wnba / L10 | 35178 | 12232 | 63.9 (63.1–64.8) | +22.1 (+20.4–+23.7) | 0.233 (0.229–0.237) | 73.7 | 54.8 | +9.2 |
| wnba / L5 | 35178 | 16592 | 67.5 (66.8–68.3) | +28.9 (+27.6–+30.3) | 0.221 (0.218–0.225) | 75.8 | 54.0 | +13.5 |
| wnba / MED20 | 35178 | 5433 | 68.1 (66.8–69.3) | +29.9 (+27.6–+32.3) | 0.212 (0.206–0.218) | 74.7 | 50.8 | +17.2 |

### Postable subset (MED20)

Prior-10 average minutes at least 20, free throws and field goals made
removed, and threes or steals at 0.5 removed when `p_under` was already
at least 0.95. This is closer to a number a book would post, and it is
lower than the headline because the headline includes the 0.5 lines.

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba | 122890 | 20584 | 60.1 (59.5–60.8) | +14.8 (+13.5–+16.1) | 0.251 (0.248–0.253) | 70.4 | 49.9 | +10.2 |
| wnba | 18827 | 2048 | 64.6 (62.6–66.7) | +23.4 (+19.4–+27.3) | 0.229 (0.221–0.238) | 70.9 | 50.0 | +14.7 |

## Agent scorecard, proxy MED20

Production avoid rate: 97,736 / 97,736 (100.0%). Decisions: {'avoid': 97736}. Eligible: {False: 97736}. Pass reasons: {'no market price available': 97736}. With the market gate ignored, the probability band itself abstains on 40,281 / 97,736 props (P(over) strictly between 0.45 and 0.55).

### Pre-gate results (market gate ignored)

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba | 84944 | 50832 | 57.4 (57.0–57.9) | +9.7 (+8.8–+10.5) | 0.246 (0.245–0.247) | 62.1 | 49.8 | +7.6 |
| wnba | 12792 | 6623 | 57.0 (55.8–58.2) | +8.8 (+6.5–+11.1) | 0.245 (0.242–0.248) | 61.2 | 49.9 | +7.1 |

### By market

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / assists | 21236 | 14330 | 58.7 (57.9–59.5) | +12.0 (+10.5–+13.5) | 0.244 (0.242–0.246) | 63.7 | 50.0 | +8.7 |
| nba / points | 21236 | 12029 | 56.4 (55.5–57.3) | +7.7 (+6.0–+9.4) | 0.249 (0.247–0.252) | 61.4 | 49.8 | +6.6 |
| nba / pra | 21236 | 11360 | 56.5 (55.6–57.5) | +8.0 (+6.2–+9.7) | 0.248 (0.246–0.250) | 61.0 | 49.7 | +6.8 |
| nba / rebounds | 21236 | 13113 | 57.8 (57.0–58.6) | +10.4 (+8.7–+12.0) | 0.245 (0.243–0.247) | 61.8 | 49.9 | +7.9 |
| wnba / assists | 3198 | 1994 | 56.1 (53.9–58.2) | +7.0 (+2.9–+11.2) | 0.248 (0.242–0.254) | 62.8 | 49.9 | +6.2 |
| wnba / points | 3198 | 1490 | 56.4 (53.8–58.9) | +7.6 (+2.8–+12.4) | 0.248 (0.242–0.253) | 60.4 | 49.9 | +6.5 |
| wnba / pra | 3198 | 1348 | 57.3 (54.7–60.0) | +9.5 (+4.4–+14.5) | 0.244 (0.239–0.250) | 59.7 | 49.8 | +7.5 |
| wnba / rebounds | 3198 | 1791 | 58.2 (55.9–60.5) | +11.2 (+6.8–+15.5) | 0.242 (0.236–0.247) | 61.2 | 50.0 | +8.2 |

### By scorecard confidence

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / [0.0, 0.3) | 29152 | 14240 | 56.8 (55.9–57.6) | +8.4 (+6.8–+9.9) | 0.249 (0.247–0.251) | 61.3 | 49.8 | +7.0 |
| nba / [0.3, 0.5) | 17808 | 11176 | 57.4 (56.5–58.3) | +9.6 (+7.9–+11.4) | 0.245 (0.243–0.248) | 61.7 | 49.8 | +7.6 |
| nba / [0.5, 0.6) | 7344 | 4779 | 58.5 (57.1–59.9) | +11.6 (+8.9–+14.3) | 0.242 (0.239–0.246) | 62.1 | 49.9 | +8.6 |
| nba / [0.6, 0.7) | 8008 | 5247 | 57.3 (55.9–58.6) | +9.3 (+6.8–+11.9) | 0.247 (0.243–0.251) | 62.6 | 49.9 | +7.4 |
| nba / [0.7, 0.76) | 22632 | 15390 | 57.8 (57.0–58.6) | +10.4 (+8.9–+11.8) | 0.246 (0.244–0.248) | 62.8 | 50.0 | +7.8 |
| wnba / [0.0, 0.3) | 7524 | 3438 | 56.9 (55.2–58.5) | +8.6 (+5.4–+11.8) | 0.246 (0.242–0.250) | 60.8 | 49.9 | +7.0 |
| wnba / [0.3, 0.5) | 3860 | 2302 | 57.2 (55.1–59.2) | +9.1 (+5.3–+13.0) | 0.245 (0.240–0.250) | 61.5 | 50.2 | +7.0 |
| wnba / [0.5, 0.6) | 1128 | 706 | 57.4 (53.7–61.0) | +9.5 (+2.5–+16.4) | 0.244 (0.235–0.253) | 61.7 | 49.6 | +7.8 |
| wnba / [0.6, 0.7) | 280 | 177 | 54.8 (47.4–62.0) | +4.6 (-9.4–+18.3) | 0.247 (0.228–0.266) | 62.1 | 50.1 | +4.7 |

### Back-to-back

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / b2b | 13172 | 8244 | 55.4 (54.4–56.5) | +5.8 (+3.8–+7.9) | 0.252 (0.250–0.255) | 62.4 | 48.6 | +6.9 |
| nba / not b2b | 71772 | 42588 | 57.8 (57.4–58.3) | +10.4 (+9.5–+11.3) | 0.245 (0.244–0.246) | 62.0 | 49.9 | +7.9 |
| wnba / b2b | 784 | 432 | 50.0 (45.3–54.7) | -4.5 (-13.5–+4.4) | 0.262 (0.250–0.274) | 61.2 | 48.7 | +1.3 |
| wnba / not b2b | 12008 | 6191 | 57.5 (56.2–58.7) | +9.7 (+7.4–+12.1) | 0.244 (0.241–0.247) | 61.2 | 49.9 | +7.5 |

### Calibration of model p_over

| League | Props | Brier(model p_over) | Brier(constant 0.5) | Corr(confidence, |p−0.5|) |
|---|---|---|---|---|
| NBA | 84944 | 0.2477 | 0.2500 | 0.1655 |
| WNBA | 12792 | 0.2472 | 0.2500 | 0.1397 |

**NBA**

| Bucket | N | Avg predicted | Actual | Gap (pred−actual) |
|---|---|---|---|---|
| [0, 0.3) | 3529 | 0.244 | 0.376 | -0.132 |
| [0.3, 0.4) | 12654 | 0.359 | 0.436 | -0.077 |
| [0.4, 0.45) | 12946 | 0.426 | 0.468 | -0.042 |
| [0.45, 0.5) | 16486 | 0.475 | 0.498 | -0.022 |
| [0.5, 0.55) | 17637 | 0.524 | 0.536 | -0.013 |
| [0.55, 0.6) | 10600 | 0.572 | 0.564 | 0.009 |
| [0.6, 0.7) | 9256 | 0.637 | 0.622 | 0.015 |
| [0.7, 1) | 1836 | 0.740 | 0.675 | 0.064 |

**WNBA**

| Bucket | N | Avg predicted | Actual | Gap (pred−actual) |
|---|---|---|---|---|
| [0, 0.3) | 291 | 0.239 | 0.344 | -0.105 |
| [0.3, 0.4) | 1494 | 0.361 | 0.420 | -0.058 |
| [0.4, 0.45) | 1841 | 0.425 | 0.482 | -0.057 |
| [0.45, 0.5) | 2940 | 0.475 | 0.485 | -0.010 |
| [0.5, 0.55) | 3232 | 0.523 | 0.531 | -0.008 |
| [0.55, 0.6) | 1598 | 0.572 | 0.559 | 0.013 |
| [0.6, 0.7) | 1202 | 0.633 | 0.613 | 0.019 |
| [0.7, 1) | 194 | 0.735 | 0.680 | 0.055 |

## Playoffs and play-in

These rows are not in the headline hit rate, ROI, Brier, calibration, or oracle.
Each target is a playoff or play-in game. The prior window is regular season only,
so a series game does not see earlier games from that series. The Cup final is in
neither list: production's allowed set does not include `cup_championship`.

- **NBA play_in**: 126 player-games, 2026-04-14 → 2026-04-17.
- **NBA playoffs**: 1,432 player-games, 2026-04-18 → 2026-05-11.
- **WNBA playoffs**: 376 player-games, 2025-09-14 → 2025-10-10.

**Daily.**

| Group | Picks | Hit% (95% CI) | Pred% | ROI% | Brier | Cal gap | Under% | 0.5-line% |
|---|---|---|---|---|---|---|---|---|
| NBA play_in ALL | 177 | 79.1 (72.5–84.4) | 73.1 | +51.0 | 0.163 | 0.060 | 98.9 | 43.5 |
| NBA play_in L10 | 589 | 67.2 (63.3–70.9) | 73.7 | +28.4 | 0.219 | 0.064 | 63.8 | 17.7 |
| NBA play_in L5 | 716 | 66.9 (63.4–70.2) | 75.6 | +27.7 | 0.226 | 0.087 | 55.7 | 15.1 |
| NBA play_in MED20 | 423 | 62.2 (57.5–66.7) | 71.9 | +18.7 | 0.235 | 0.097 | 61.5 | 27.2 |
| NBA playoffs ALL | 2512 | 78.5 (76.8–80.0) | 73.6 | +49.8 | 0.166 | 0.048 | 98.4 | 43.8 |
| NBA playoffs L10 | 6533 | 73.5 (72.4–74.5) | 74.2 | +40.3 | 0.190 | 0.008 | 76.9 | 17.9 |
| NBA playoffs L5 | 8047 | 75.1 (74.2–76.1) | 76.9 | +43.4 | 0.181 | 0.018 | 69.5 | 15.9 |
| NBA playoffs MED20 | 4269 | 66.9 (65.5–68.3) | 72.5 | +27.7 | 0.216 | 0.056 | 59.5 | 36.5 |
| WNBA playoffs ALL | 725 | 81.5 (78.5–84.2) | 75.2 | +55.6 | 0.150 | 0.063 | 99.6 | 47.0 |
| WNBA playoffs L10 | 1648 | 71.5 (69.3–73.7) | 75.0 | +36.6 | 0.199 | 0.035 | 81.6 | 22.9 |
| WNBA playoffs L5 | 1822 | 74.1 (72.0–76.1) | 76.7 | +41.5 | 0.186 | 0.026 | 70.4 | 22.8 |
| WNBA playoffs MED20 | 908 | 71.6 (68.6–74.4) | 74.4 | +36.7 | 0.194 | 0.029 | 66.7 | 46.1 |

**Agent pre-gate.**

| Group | Picks | Hit% (95% CI) | Pred% | ROI% | Brier | Cal gap | Under% | 0.5-line% |
|---|---|---|---|---|---|---|---|---|
| NBA play_in L10 | 368 | 63.3 (58.3–68.1) | 63.8 | +20.9 | 0.227 | 0.005 | 60.6 | 4.6 |
| NBA play_in MED20 | 366 | 57.7 (52.5–62.6) | 62.6 | +10.1 | 0.245 | 0.049 | 56.3 | 7.4 |
| NBA playoffs L10 | 4297 | 67.0 (65.6–68.4) | 64.2 | +27.9 | 0.218 | 0.028 | 68.9 | 5.2 |
| NBA playoffs MED20 | 4133 | 59.0 (57.5–60.5) | 63.1 | +12.7 | 0.248 | 0.041 | 49.1 | 11.3 |
| WNBA playoffs L10 | 1091 | 63.6 (60.7–66.4) | 64.9 | +21.4 | 0.225 | 0.013 | 68.0 | 6.4 |
| WNBA playoffs MED20 | 889 | 57.6 (54.3–60.8) | 62.1 | +9.9 | 0.239 | 0.045 | 55.3 | 11.1 |

## Game-type scope

SPO-97 labeled each row with a game type and dropped Summer League and preseason from the CSVs this run reads. Headline history and headline targets are regular season only, the same set as `CSVPlayerHistoryService._allowed_game_types` with both opt-in flags off. A row that has no game type still counts as regular season, which is what `_game_type_of` does. Playoffs and the play-in stay in the file and are the section above, not the headline metrics.

SPO-98 matches names by exact key. This replay iterates the CSV's own player keys, so the tables do not move when a live request stops accepting a partial name. The replay does not read the team column. A traded player's badge on the picks page is outside these numbers.

Duplicate player-dates in the WNBA cache: none. A second copy of the same date is not its own target. When the box score matches, the later prior keeps one copy. Scored headline player-games whose prior still contains such a date: 0.

## Check against the recorded headlines

Headlines match the recorded regular-season walk-forward for this CSV. Headline targets: NBA 2025-11-09 → 2026-04-12 (21,236 player-games), WNBA 2025-06-11 → 2026-05-08 (3,198 player-games). History and those targets are regular-season games, the same set `CSVPlayerHistoryService._allowed_game_types` uses in production. Playoffs and the play-in are scored with that history and reported in their own section; they are not part of these headlines. Proxy lines are x.5. ROI assumes -110. CLV is not measured.

## Calibration guard

Calibration guard: max Brier 0.300, max |pred - hit| 0.150 (MED20 Daily Picks).
ok nba: Brier 0.230, calibration gap 0.090 (picks n=48258)
ok wnba: Brier 0.212, calibration gap 0.066 (picks n=5433)

The CI job runs `pytest` on the walk-forward and calibration-guard tests.
The guard replays a 40-player sample (seed 7) per league and fails if the
MED20 Brier score exceeds `BACKTEST_GUARD_MAX_BRIER` (default 0.30) or
the calibration gap exceeds `BACKTEST_GUARD_MAX_GAP` (default 0.15).
It also compares 25 daily L10 rates per league, same seed, with
`get_player_stats`. Any mismatch fails the job. The full-run figures
above are the Brier and gap check on every player.

## How to read the hit rate

A proxy built from the last 20 games is a noisier number than a book
that has projections, injuries, and minutes. Beating MED20 mostly says
that a long unshrunk history is more extreme than a 20-game split.
It does not say the bet would have beaten a closing line. Closing-line
value stays unmeasured until the odds hook has a file to read.
