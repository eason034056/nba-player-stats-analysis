# Sports Lab walk-forward backtest

Generated 2026-11-09 22:02 UTC. Command: `python scripts/agents/evaluation/backtest.py --report backtest_report.md`. Elapsed 73s.

The previous `scripts/agents/evaluation/backtest.py` scored five hard-coded players
in-sample: the "actual rate" was the same history the model had just fit.
This report walks forward. Each player-game is scored with that player's
non-DNP games dated strictly before it, which is the information Daily Picks
and the scorecard would have had on the morning of the game if the CSV had
been frozen there.

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
| NBA | 31,572 | 579 | 2021-08-04 → 2026-05-11 | 2025-2026=31572 | none | 126 | 3,416 |
| WNBA | 5,365 | 184 | 2025-05-02 → 2026-05-08 | 2025=5046, 2026=319 | Maria Conde 2026-05-08 ×2 | 52 | 5,045 |

Target windows (a game is scored only if it has at least 10 prior non-DNP games,
the same floor as `MIN_SAMPLE_GAMES`):

- **NBA** configured start 2025-10-21; scored targets 2025-10-21 → 2026-05-11 (25,218 player-games).
- **WNBA** configured start 2025-05-01; scored targets 2025-06-05 → 2026-05-08 (3,960 player-games).

## Method

**Daily Picks.** For each supported market in `daily_analysis.SUPPORTED_MARKETS`,
the over rate is the share of prior games strictly above the line and the under
rate is the share strictly below it, rounded to 4 decimals. That is the return
value of `CSVPlayerHistoryService.get_player_stats(n=0, exclude_dnp=True)`.
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
| nba | 277398 | 55708 | 64.9 (64.5–65.3) | +24.0 (+23.2–+24.7) | 0.227 (0.225–0.228) | 72.7 | 50.8 | +14.2 |
| wnba | 43560 | 7199 | 68.4 (67.3–69.5) | +30.6 (+28.6–+32.7) | 0.210 (0.206–0.215) | 74.3 | 50.9 | +17.5 |

### By market

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / assists | 25218 | 5305 | 62.7 (61.4–64.0) | +19.7 (+17.2–+22.2) | 0.240 (0.235–0.246) | 71.0 | 50.3 | +12.4 |
| nba / fgm | 25218 | 4303 | 60.3 (58.8–61.8) | +15.1 (+12.3–+17.9) | 0.250 (0.244–0.256) | 70.2 | 50.0 | +10.3 |
| nba / ftm | 25218 | 7872 | 71.7 (70.7–72.6) | +36.8 (+34.9–+38.7) | 0.200 (0.195–0.205) | 74.9 | 57.3 | +14.4 |
| nba / pa | 25218 | 3349 | 56.5 (54.8–58.2) | +7.9 (+4.7–+11.1) | 0.265 (0.258–0.272) | 69.8 | 50.0 | +6.5 |
| nba / points | 25218 | 3241 | 57.8 (56.1–59.5) | +10.4 (+7.1–+13.6) | 0.260 (0.253–0.266) | 69.8 | 50.0 | +7.8 |
| nba / pr | 25218 | 3179 | 57.5 (55.8–59.2) | +9.8 (+6.5–+13.0) | 0.260 (0.253–0.267) | 69.7 | 50.0 | +7.5 |
| nba / pra | 25218 | 3242 | 55.4 (53.7–57.1) | +5.7 (+2.4–+9.0) | 0.269 (0.262–0.276) | 69.8 | 50.0 | +5.4 |
| nba / ra | 25218 | 3561 | 59.1 (57.5–60.7) | +12.8 (+9.7–+15.9) | 0.253 (0.247–0.260) | 69.9 | 50.0 | +9.1 |
| nba / rebounds | 25218 | 3916 | 60.0 (58.4–61.5) | +14.5 (+11.6–+17.4) | 0.248 (0.242–0.255) | 69.7 | 50.0 | +10.0 |
| nba / steals | 25218 | 8333 | 67.7 (66.7–68.7) | +29.3 (+27.4–+31.2) | 0.220 (0.215–0.224) | 72.9 | 53.4 | +14.3 |
| nba / threes_made | 25218 | 9407 | 75.8 (74.9–76.6) | +44.7 (+43.0–+46.3) | 0.166 (0.162–0.171) | 79.1 | 54.5 | +21.2 |
| wnba / assists | 3960 | 642 | 67.6 (63.9–71.1) | +29.1 (+22.0–+35.8) | 0.218 (0.202–0.233) | 71.8 | 50.0 | +17.6 |
| wnba / fgm | 3960 | 425 | 63.8 (59.1–68.2) | +21.7 (+12.8–+30.2) | 0.234 (0.216–0.253) | 70.1 | 49.9 | +13.9 |
| wnba / ftm | 3960 | 1137 | 71.2 (68.5–73.8) | +36.0 (+30.9–+40.9) | 0.203 (0.189–0.217) | 76.2 | 56.9 | +14.3 |
| wnba / pa | 3960 | 220 | 61.8 (55.2–68.0) | +18.0 (+5.5–+29.8) | 0.239 (0.216–0.263) | 68.0 | 49.6 | +12.3 |
| wnba / points | 3960 | 234 | 64.1 (57.8–70.0) | +22.4 (+10.3–+33.6) | 0.232 (0.209–0.255) | 68.4 | 49.8 | +14.3 |
| wnba / pr | 3960 | 241 | 56.0 (49.7–62.1) | +6.9 (-5.1–+18.6) | 0.265 (0.241–0.289) | 68.7 | 50.1 | +5.9 |
| wnba / pra | 3960 | 258 | 60.1 (54.0–65.9) | +14.7 (+3.1–+25.7) | 0.253 (0.230–0.276) | 68.6 | 49.5 | +10.5 |
| wnba / ra | 3960 | 425 | 60.7 (56.0–65.2) | +15.9 (+6.9–+24.5) | 0.246 (0.228–0.264) | 69.2 | 50.2 | +10.5 |
| wnba / rebounds | 3960 | 430 | 57.9 (53.2–62.5) | +10.5 (+1.5–+19.3) | 0.255 (0.237–0.274) | 69.5 | 50.1 | +7.8 |
| wnba / steals | 3960 | 1489 | 66.9 (64.5–69.2) | +27.7 (+23.1–+32.2) | 0.225 (0.214–0.236) | 73.3 | 54.2 | +12.7 |
| wnba / threes_made | 3960 | 1698 | 78.4 (76.4–80.3) | +49.8 (+45.9–+53.4) | 0.153 (0.142–0.163) | 81.5 | 59.5 | +19.0 |

### By confidence tier

The tier is only defined for picks. Naive and lift inside a tier use that
tier's own props, which are the picks, so they are not the headline baseline.

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / high (>=0.70) | 28973 | 28973 | 69.5 (69.0–70.1) | +32.7 (+31.7–+33.7) | 0.209 (0.207–0.212) | 77.8 | 55.9 | +13.6 |
| nba / medium [0.65, 0.70) | 26735 | 26735 | 60.0 (59.4–60.6) | +14.5 (+13.4–+15.6) | 0.245 (0.243–0.247) | 67.2 | 50.5 | +9.5 |
| wnba / high (>=0.70) | 3993 | 3993 | 73.4 (72.0–74.7) | +40.1 (+37.4–+42.7) | 0.189 (0.181–0.197) | 80.0 | 60.6 | +12.8 |
| wnba / medium [0.65, 0.70) | 3206 | 3206 | 62.3 (60.6–63.9) | +18.9 (+15.6–+22.0) | 0.237 (0.231–0.243) | 67.1 | 51.7 | +10.6 |

### By direction

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / over | 19231 | 19231 | 59.6 (58.9–60.3) | +13.8 (+12.5–+15.1) | 0.251 (0.248–0.254) | 69.8 | 59.6 | +0.0 |
| nba / under | 36477 | 36477 | 67.8 (67.3–68.2) | +29.3 (+28.4–+30.3) | 0.214 (0.211–0.216) | 74.2 | 67.8 | +0.0 |
| wnba / over | 1902 | 1902 | 61.8 (59.6–63.9) | +17.9 (+13.7–+22.1) | 0.243 (0.234–0.251) | 69.6 | 61.8 | +0.0 |
| wnba / under | 5297 | 5297 | 70.8 (69.6–72.0) | +35.2 (+32.8–+37.5) | 0.199 (0.193–0.205) | 75.9 | 70.8 | +0.0 |

### By month

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / 2025-10 | 2453 | 241 | 66.8 (60.6–72.4) | +27.5 (+15.8–+38.3) | 0.214 (0.187–0.242) | 74.8 | 54.3 | +12.5 |
| nba / 2025-11 | 42955 | 4578 | 69.0 (67.7–70.3) | +31.8 (+29.2–+34.3) | 0.207 (0.201–0.214) | 74.9 | 50.3 | +18.7 |
| nba / 2025-12 | 44880 | 6457 | 66.0 (64.9–67.2) | +26.1 (+23.8–+28.3) | 0.219 (0.214–0.224) | 73.0 | 51.0 | +15.0 |
| nba / 2026-01 | 54274 | 10174 | 67.2 (66.3–68.1) | +28.3 (+26.6–+30.0) | 0.216 (0.212–0.220) | 72.3 | 50.8 | +16.4 |
| nba / 2026-02 | 38511 | 8156 | 64.5 (63.5–65.6) | +23.2 (+21.2–+25.2) | 0.228 (0.223–0.232) | 72.2 | 50.2 | +14.4 |
| nba / 2026-03 | 55374 | 14691 | 64.4 (63.6–65.2) | +23.0 (+21.5–+24.4) | 0.230 (0.227–0.234) | 72.4 | 50.7 | +13.7 |
| nba / 2026-04 | 33550 | 9740 | 61.8 (60.8–62.7) | +17.9 (+16.1–+19.8) | 0.243 (0.238–0.247) | 72.5 | 51.0 | +10.7 |
| nba / 2026-05 | 5401 | 1671 | 60.6 (58.2–62.9) | +15.6 (+11.1–+20.0) | 0.246 (0.236–0.257) | 72.6 | 49.3 | +11.3 |
| wnba / 2025-06 | 7678 | 921 | 66.1 (63.0–69.1) | +26.2 (+20.3–+31.9) | 0.227 (0.211–0.242) | 76.6 | 49.1 | +17.0 |
| wnba / 2025-07 | 10670 | 1368 | 69.2 (66.7–71.5) | +32.0 (+27.2–+36.6) | 0.208 (0.196–0.220) | 75.4 | 50.3 | +18.8 |
| wnba / 2025-08 | 13926 | 2426 | 68.8 (67.0–70.6) | +31.4 (+27.8–+34.9) | 0.207 (0.199–0.216) | 73.4 | 51.3 | +17.6 |
| wnba / 2025-09 | 8371 | 1809 | 69.4 (67.3–71.5) | +32.5 (+28.4–+36.5) | 0.201 (0.192–0.211) | 73.6 | 52.3 | +17.1 |
| wnba / 2025-10 | 660 | 142 | 70.4 (62.5–77.3) | +34.4 (+19.2–+47.6) | 0.202 (0.166–0.238) | 75.5 | 50.9 | +19.5 |
| wnba / 2026-04 | 1232 | 281 | 64.1 (58.3–69.4) | +22.3 (+11.3–+32.6) | 0.245 (0.216–0.273) | 74.0 | 49.8 | +14.2 |
| wnba / 2026-05 | 1023 | 252 | 65.5 (59.4–71.1) | +25.0 (+13.4–+35.7) | 0.227 (0.200–0.254) | 72.7 | 52.9 | +12.6 |

### Pick composition

| League | Picks | Under share | 0.5-line share | Prob ≥ 0.95 share |
|---|---|---|---|---|
| NBA | 55708 | 65.5 | 44.0 | 4.1 |
| WNBA | 7199 | 73.6 | 60.5 | 6.6 |

### Calibration of the pick probability

**NBA**

| Bucket | N | Avg predicted | Actual | Gap (pred−actual) |
|---|---|---|---|---|
| [0.65, 0.7) | 26735 | 0.672 | 0.600 | 0.072 |
| [0.7, 0.75) | 14202 | 0.719 | 0.635 | 0.084 |
| [0.75, 0.8) | 6850 | 0.768 | 0.672 | 0.096 |
| [0.8, 0.85) | 3297 | 0.819 | 0.717 | 0.102 |
| [0.85, 0.9) | 1363 | 0.871 | 0.819 | 0.052 |
| [0.9, 0.95) | 995 | 0.920 | 0.851 | 0.069 |
| [0.95, 1) | 2266 | 0.992 | 0.969 | 0.023 |

**WNBA**

| Bucket | N | Avg predicted | Actual | Gap (pred−actual) |
|---|---|---|---|---|
| [0.65, 0.7) | 3206 | 0.671 | 0.623 | 0.049 |
| [0.7, 0.75) | 1663 | 0.718 | 0.651 | 0.068 |
| [0.75, 0.8) | 717 | 0.766 | 0.689 | 0.077 |
| [0.8, 0.85) | 543 | 0.821 | 0.751 | 0.069 |
| [0.85, 0.9) | 294 | 0.871 | 0.813 | 0.058 |
| [0.9, 0.95) | 298 | 0.920 | 0.832 | 0.088 |
| [0.95, 1) | 478 | 0.993 | 0.960 | 0.033 |

### Calibration of p_over on every prop

| League | Props | Brier(p_over) | Brier(constant 0.5) | Brier(base rate) | Actual over% | Mean p_over% |
|---|---|---|---|---|---|---|
| NBA | 277398 | 0.2445 | 0.2500 | 0.2494 | 47.54 | 47.99 |
| WNBA | 43560 | 0.2426 | 0.2500 | 0.2496 | 48.12 | 47.07 |

**NBA**

| Bucket | N | Avg predicted | Actual | Gap (pred−actual) |
|---|---|---|---|---|
| [0, 0.1) | 3123 | 0.027 | 0.060 | -0.034 |
| [0.1, 0.2) | 3861 | 0.158 | 0.235 | -0.077 |
| [0.2, 0.3) | 13269 | 0.258 | 0.337 | -0.079 |
| [0.3, 0.4) | 39849 | 0.355 | 0.405 | -0.049 |
| [0.4, 0.5) | 77446 | 0.447 | 0.461 | -0.013 |
| [0.5, 0.6) | 96719 | 0.537 | 0.514 | 0.024 |
| [0.6, 0.7) | 35230 | 0.636 | 0.566 | 0.071 |
| [0.7, 0.8) | 7523 | 0.731 | 0.620 | 0.111 |
| [0.8, 0.9) | 375 | 0.821 | 0.621 | 0.199 |
| [0.9, 1) | 3 | 0.903 | 0.000 | 0.903 |

**WNBA**

| Bucket | N | Avg predicted | Actual | Gap (pred−actual) |
|---|---|---|---|---|
| [0, 0.1) | 729 | 0.031 | 0.082 | -0.052 |
| [0.1, 0.2) | 737 | 0.150 | 0.199 | -0.049 |
| [0.2, 0.3) | 1593 | 0.258 | 0.324 | -0.066 |
| [0.3, 0.4) | 5861 | 0.356 | 0.400 | -0.043 |
| [0.4, 0.5) | 13494 | 0.447 | 0.473 | -0.026 |
| [0.5, 0.6) | 16073 | 0.532 | 0.530 | 0.002 |
| [0.6, 0.7) | 4285 | 0.632 | 0.579 | 0.053 |
| [0.7, 0.8) | 759 | 0.729 | 0.657 | 0.072 |
| [0.8, 0.9) | 29 | 0.815 | 0.414 | 0.401 |

### Proxy sensitivity

The level moves with the proxy. That is the reason the absolute hit rate
is not a market edge: MED20, L10, L5, and ALL are different questions.

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / ALL | 277398 | 48160 | 68.9 (68.5–69.3) | +31.6 (+30.8–+32.4) | 0.209 (0.207–0.211) | 72.8 | 56.5 | +12.4 |
| nba / L10 | 277398 | 101614 | 64.9 (64.6–65.2) | +23.9 (+23.3–+24.4) | 0.232 (0.230–0.233) | 73.6 | 54.5 | +10.4 |
| nba / L5 | 277398 | 135012 | 67.4 (67.2–67.7) | +28.8 (+28.3–+29.2) | 0.223 (0.222–0.224) | 75.6 | 53.4 | +14.0 |
| nba / MED20 | 277398 | 55708 | 64.9 (64.5–65.3) | +24.0 (+23.2–+24.7) | 0.227 (0.225–0.228) | 72.7 | 50.8 | +14.2 |
| wnba / ALL | 43560 | 8174 | 67.1 (66.1–68.1) | +28.1 (+26.1–+30.0) | 0.216 (0.212–0.221) | 73.8 | 55.9 | +11.2 |
| wnba / L10 | 43560 | 15413 | 64.5 (63.8–65.3) | +23.2 (+21.8–+24.7) | 0.231 (0.227–0.234) | 73.7 | 55.0 | +9.6 |
| wnba / L5 | 43560 | 20575 | 68.1 (67.4–68.7) | +30.0 (+28.8–+31.2) | 0.219 (0.215–0.222) | 75.7 | 54.1 | +13.9 |
| wnba / MED20 | 43560 | 7199 | 68.4 (67.3–69.5) | +30.6 (+28.6–+32.7) | 0.210 (0.206–0.215) | 74.3 | 50.9 | +17.5 |

### Postable subset (MED20)

Prior-10 average minutes at least 20, free throws and field goals made
removed, and threes or steals at 0.5 removed when `p_under` was already
at least 0.95. This is closer to a number a book would post, and it is
lower than the headline because the headline includes the 0.5 lines.

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba | 139917 | 23795 | 61.3 (60.7–62.0) | +17.1 (+15.9–+18.3) | 0.245 (0.242–0.247) | 70.3 | 49.9 | +11.4 |
| wnba | 23195 | 2854 | 65.4 (63.7–67.1) | +24.9 (+21.5–+28.2) | 0.226 (0.219–0.234) | 70.7 | 50.0 | +15.4 |

## Agent scorecard, proxy MED20

Production avoid rate: 116,712 / 116,712 (100.0%). Decisions: {'avoid': 116712}. Eligible: {False: 116712}. Pass reasons: {'no market price available': 116712}. With the market gate ignored, the probability band itself abstains on 47,352 / 116,712 props (P(over) strictly between 0.45 and 0.55).

### Pre-gate results (market gate ignored)

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba | 100872 | 60781 | 57.9 (57.5–58.3) | +10.6 (+9.9–+11.3) | 0.245 (0.244–0.246) | 62.0 | 50.1 | +7.9 |
| wnba | 15840 | 8579 | 57.6 (56.5–58.6) | +10.0 (+7.9–+11.9) | 0.244 (0.241–0.246) | 61.4 | 49.9 | +7.7 |

### By market

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / assists | 25218 | 16882 | 59.1 (58.4–59.9) | +12.9 (+11.4–+14.3) | 0.242 (0.240–0.244) | 63.3 | 50.3 | +8.8 |
| nba / points | 25218 | 14381 | 57.1 (56.3–57.9) | +9.0 (+7.4–+10.5) | 0.247 (0.245–0.249) | 61.4 | 50.0 | +7.1 |
| nba / pra | 25218 | 13758 | 57.2 (56.3–58.0) | +9.2 (+7.6–+10.7) | 0.247 (0.244–0.249) | 61.1 | 50.0 | +7.2 |
| nba / rebounds | 25218 | 15760 | 58.1 (57.3–58.9) | +10.9 (+9.4–+12.4) | 0.244 (0.242–0.246) | 62.0 | 50.0 | +8.1 |
| wnba / assists | 3960 | 2507 | 57.9 (55.9–59.8) | +10.5 (+6.8–+14.2) | 0.242 (0.237–0.247) | 62.9 | 50.0 | +7.9 |
| wnba / points | 3960 | 1996 | 58.2 (56.0–60.3) | +11.0 (+6.9–+15.1) | 0.244 (0.239–0.249) | 60.6 | 49.9 | +8.3 |
| wnba / pra | 3960 | 1775 | 56.2 (53.8–58.5) | +7.2 (+2.8–+11.6) | 0.246 (0.241–0.251) | 60.1 | 49.7 | +6.4 |
| wnba / rebounds | 3960 | 2301 | 57.9 (55.9–59.9) | +10.5 (+6.6–+14.3) | 0.243 (0.238–0.248) | 61.3 | 50.0 | +7.9 |

### By scorecard confidence

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / [0.0, 0.3) | 30936 | 14800 | 57.8 (57.0–58.6) | +10.3 (+8.8–+11.8) | 0.246 (0.244–0.248) | 60.8 | 50.0 | +7.7 |
| nba / [0.3, 0.5) | 18816 | 11727 | 57.5 (56.6–58.4) | +9.7 (+8.0–+11.4) | 0.244 (0.242–0.247) | 61.6 | 49.9 | +7.6 |
| nba / [0.5, 0.6) | 7956 | 5098 | 57.7 (56.4–59.1) | +10.2 (+7.6–+12.8) | 0.245 (0.242–0.249) | 62.1 | 49.8 | +7.9 |
| nba / [0.6, 0.7) | 8948 | 5926 | 59.0 (57.8–60.3) | +12.7 (+10.3–+15.0) | 0.241 (0.238–0.245) | 62.5 | 50.1 | +9.0 |
| nba / [0.7, 0.76) | 34216 | 23230 | 58.0 (57.4–58.7) | +10.8 (+9.6–+12.0) | 0.245 (0.243–0.247) | 62.8 | 50.2 | +7.9 |
| wnba / [0.0, 0.3) | 7776 | 3631 | 57.7 (56.1–59.3) | +10.1 (+7.0–+13.1) | 0.245 (0.241–0.248) | 60.9 | 49.8 | +7.9 |
| wnba / [0.3, 0.5) | 4508 | 2722 | 58.0 (56.2–59.9) | +10.8 (+7.3–+14.3) | 0.243 (0.239–0.248) | 61.4 | 50.1 | +7.9 |
| wnba / [0.5, 0.6) | 1556 | 991 | 56.9 (53.8–60.0) | +8.7 (+2.7–+14.5) | 0.242 (0.234–0.249) | 62.1 | 50.2 | +6.7 |
| wnba / [0.6, 0.7) | 1340 | 865 | 59.3 (56.0–62.5) | +13.2 (+6.9–+19.4) | 0.238 (0.229–0.246) | 62.1 | 50.5 | +8.8 |
| wnba / [0.7, 0.76) | 660 | 370 | 51.4 (46.3–56.4) | -2.0 (-11.7–+7.7) | 0.257 (0.244–0.270) | 61.7 | 50.1 | +1.3 |

### Back-to-back

| Group | Props | Picks | Hit% (95% CI) | ROI% (95% CI) | Brier (95% CI) | Avg pred% | Naive% | Lift pp |
|---|---|---|---|---|---|---|---|---|
| nba / b2b | 14536 | 9081 | 55.8 (54.8–56.8) | +6.5 (+4.6–+8.5) | 0.251 (0.248–0.254) | 62.2 | 48.7 | +7.1 |
| nba / not b2b | 86336 | 51700 | 58.3 (57.9–58.7) | +11.3 (+10.5–+12.1) | 0.244 (0.243–0.245) | 62.0 | 50.1 | +8.2 |
| wnba / b2b | 796 | 469 | 53.1 (48.6–57.6) | +1.4 (-7.3–+9.9) | 0.257 (0.246–0.268) | 61.1 | 48.7 | +4.4 |
| wnba / not b2b | 15044 | 8110 | 57.9 (56.8–58.9) | +10.4 (+8.4–+12.5) | 0.243 (0.240–0.246) | 61.4 | 49.9 | +7.9 |

### Calibration of model p_over

| League | Props | Brier(model p_over) | Brier(constant 0.5) | Corr(confidence, |p−0.5|) |
|---|---|---|---|---|
| NBA | 100872 | 0.2467 | 0.2500 | 0.1972 |
| WNBA | 15840 | 0.2463 | 0.2500 | 0.1514 |

**NBA**

| Bucket | N | Avg predicted | Actual | Gap (pred−actual) |
|---|---|---|---|---|
| [0, 0.3) | 3657 | 0.250 | 0.357 | -0.107 |
| [0.3, 0.4) | 14783 | 0.360 | 0.413 | -0.053 |
| [0.4, 0.45) | 15471 | 0.426 | 0.447 | -0.022 |
| [0.45, 0.5) | 19552 | 0.475 | 0.478 | -0.002 |
| [0.5, 0.55) | 20558 | 0.523 | 0.521 | 0.002 |
| [0.55, 0.6) | 12383 | 0.573 | 0.557 | 0.016 |
| [0.6, 0.7) | 11941 | 0.638 | 0.591 | 0.047 |
| [0.7, 1) | 2527 | 0.742 | 0.664 | 0.078 |

**WNBA**

| Bucket | N | Avg predicted | Actual | Gap (pred−actual) |
|---|---|---|---|---|
| [0, 0.3) | 397 | 0.242 | 0.302 | -0.060 |
| [0.3, 0.4) | 2027 | 0.361 | 0.412 | -0.051 |
| [0.4, 0.45) | 2422 | 0.426 | 0.472 | -0.046 |
| [0.45, 0.5) | 3429 | 0.475 | 0.489 | -0.014 |
| [0.5, 0.55) | 3834 | 0.523 | 0.541 | -0.018 |
| [0.55, 0.6) | 1977 | 0.572 | 0.555 | 0.017 |
| [0.6, 0.7) | 1461 | 0.635 | 0.614 | 0.021 |
| [0.7, 1) | 293 | 0.738 | 0.676 | 0.063 |

## What moves when SPO-97 and SPO-98 land

These four data bugs are left for SPO-97 and SPO-98. This run does not correct them.

**Season label.** The NBA cache has 31,572 rows and season counts {'2025-2026': 31572}. 3,416 of those rows are dated before 2025-10-21 (2021-08=4, 2024-07=5, 2024-10=72, 2024-11=127, 2024-12=116, 2025-01=158, 2025-02=99, 2025-03=117, 2025-04=70, 2025-05=22, 2025-06=7, 2025-07=849, 2025-10=1770). `get_player_stats(n=0)` does not read the Season column, and neither does this replay, so correcting the label by itself does not move a hit rate, an ROI, a Brier score, or a calibration bucket. What does move them is the natural companion of that fix: dropping Summer League, preseason, and the stray older rows out of the history the model consumes. 23,937 of 25,218 scored NBA player-games have at least one such row in their prior window, and 6,832 have one inside the last 20 games that MED20 and the rotation split look at. Those are the NBA tables that shift: the MED20 and L10 hit rates, ROI, Brier, calibration, monthly rates (October and November most of all, because the short window is still full of pre-cutoff games), and the proxy-sensitivity table. WNBA is a separate file and does not move because of the NBA label.

**Duplicate WNBA row.** Duplicate player-dates in the WNBA cache: Maria Conde 2026-05-08 ×2. A second copy of the same date is not scored as its own target. When that copy is the same box score (these two rows differ only in Season), the replay keeps one copy, so a later game does not count it twice. A same-day row with a different box score, such as a doubleheader, stays in the later prior. Scored player-games whose prior still contains a date that had a duplicate row: 0. Deleting the extra row therefore does not move the WNBA headline hit rate, ROI, Brier, or calibration on this file. The replay has already stopped the double count.

**Team taken from the oldest game.** Daily Picks falls back to `game_logs[0]` when there is no projection, and `get_player_stats` returns logs oldest-first, so a traded player is labelled with their oldest team. 126 NBA and 52 WNBA players in this cache have more than one team. This replay never reads the team. Hit rate, ROI, Brier, calibration, monthly rates, under share, and the 0.5-line share do not move. The team badge on the picks page does.

**Substring name match.** `get_player_stats` and `_games_for` accept a name when either string contains the other. This replay iterates the CSV's own player keys and looks them up exactly, so the fuzzy branch does not fire. None of the tables in this report move when matching gets stricter. A live request that passes a partial or overlapping name can change, because that request is the one that uses the fuzzy branch.

## Check against the recorded headlines

Daily headlines match the walk-forward prototype on origin/dev @ 5407401. Agent MED20 picks are 60,781 NBA and 8,579 WNBA (prototype 60,829 and 8,590). The side is now the unrounded probability, so a value that only crosses 0.55 or 0.45 after rounding to 4 decimals is an abstention. WNBA average predicted probability rounds to 61.4% (prototype 61.3%). Push refunds and the duplicate-row filter did not move a headline: proxy lines are x.5, stats are integers, and the only duplicate date is the last WNBA game.

## Calibration guard

Calibration guard: max Brier 0.300, max |pred - hit| 0.150 (MED20 Daily Picks).
ok nba: Brier 0.227, calibration gap 0.077 (picks n=55708)
ok wnba: Brier 0.210, calibration gap 0.058 (picks n=7199)

The CI job runs `pytest` on `scripts/agents/tests/test_calibration_guard.py`,
which replays a 40-player sample (seed 7) per league and fails if the
MED20 Brier score exceeds `BACKTEST_GUARD_MAX_BRIER` (default 0.30) or
the calibration gap exceeds `BACKTEST_GUARD_MAX_GAP` (default 0.15).
The full-run figures above are the same check on every player.

## How to read the hit rate

A proxy built from the last 20 games is a noisier number than a book
that has projections, injuries, and minutes. Beating MED20 mostly says
that a long unshrunk history is more extreme than a 20-game split.
It does not say the bet would have beaten a closing line. Closing-line
value stays unmeasured until the odds hook has a file to read.
