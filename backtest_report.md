# Backtest Report – NBA Multi-Agent Betting Advisor

Generated: 2026-03-12 14:09

## Per-Player Results

| Player | Metric | Threshold | Model Prob | Actual Rate | N | Decision | Flags |
|--------|--------|-----------|-----------|-------------|---|----------|-------|
| Stephen Curry | points | 26.5 | 0.514 | 0.535 | 43 | avoid | no_market_data |
| Giannis Antetokounmpo | rebounds | 11.5 | 0.291 | 0.278 | 36 | avoid | high_variance (cv=0.42), no_market_data |
| Tyrese Haliburton | assists | 8.5 | 0.427 | 0.525 | 99 | avoid | no_market_data |
| Victor Wembanyama | pra | 30.5 | 0.740 | 0.714 | 56 | avoid | no_market_data |
| A.J. Green | points | 9.5 | 0.387 | 0.484 | 64 | avoid | high_variance (cv=0.58), no_market_data |

## Calibration

| Bucket | Count | Avg Model Prob | Avg Actual Rate | Calibration Gap |
|--------|-------|----------------|-----------------|-----------------|
| 0.0-0.4 | 2 | 0.339 | 0.381 | -0.042 |
| 0.4-0.5 | 1 | 0.427 | 0.525 | -0.098 |
| 0.5-0.6 | 1 | 0.514 | 0.535 | -0.020 |
| 0.7-0.8 | 1 | 0.740 | 0.714 | +0.026 |

## Interpretation

- A well-calibrated model has avg_model_prob close to avg_actual_rate in each bucket.
- Positive calibration gap means the model is overconfident for that bucket.
- Negative gap means the model is underconfident.
- With only 5 test cases, this is illustrative only; a full backtest would iterate over all players and games.
