"""Versioned constants for the NBA combined-probability blend.

Two kinds of numbers live here.

Priors, not estimated from outcomes:

* Verdict thresholds and the log-odds caps.
* The weight on each adjustment. Projection's weight is deliberately small
  because this repo has no projection history to fit against.
* The offline market prior (fair 0.5). Walk-forward has no sportsbook
  prices, so every training row uses ``logit(0.5) = 0``. The live market
  coefficient stays 1; it is not multiplied by the Platt slope.

Fitted on walk-forward data:

* ``PLATT_A`` and ``PLATT_B`` only. They map the clipped adjustment total
  onto the log-odds residual versus a fair 0.5 market. ``FIT_SAMPLE``
  records the rows those two numbers came from, including the cutoff.
  Rows dated after the cutoff are the holdout and are not in the fit.

Regenerate the fitted pair (does not call an external API)::

    cd scripts/agents && python -m evaluation.fit_combined_platt

That command replays NBA MED20, fits Platt on rows dated on or before
2026-03-17 (pass ``--cutoff`` to use another date), and rewrites
``PLATT_A``, ``PLATT_B``, and ``FIT_SAMPLE`` in this file.
"""

from __future__ import annotations

CONSTANTS_VERSION = "spo112-v1"

# Verdict thresholds. A missing input is None, never neutral.
MARKET_SUPPORTS_AT = 0.52
MARKET_AGAINST_AT = 0.48
LAST10_SUPPORTS_AT = 6
LAST10_AGAINST_AT = 4
LAST10_GAMES = 10
HISTORY_SUPPORTS_AT = 0.55
HISTORY_AGAINST_AT = 0.45
PROJECTION_SUPPORTS_AT = 0.5
PROJECTION_AGAINST_AT = -0.5
DEFENSE_WEAK_AT = 10  # rank <= 10 is the weak-defense end (1 = weakest)
DEFENSE_STRONG_AT = 20  # rank > 20 is the strong-defense end

# Log-odds adjustments. Each term is clipped, then the sum is clipped.
ADJUSTMENT_CAP = 0.15
TOTAL_ADJUSTMENT_CAP = 0.35

# Multiply the side-rate logit. 0.5 is zero adjustment; the cap binds
# before a rate of 0 or 1.
LAST10_LOGIT_WEIGHT = 0.25
HISTORY_LOGIT_WEIGHT = 0.10

# Rank 1 → +1 (weakest, favors the over), rank 30 → -1. Times this weight
# that span is exactly ±ADJUSTMENT_CAP.
DEFENSE_WEIGHT = 0.15
DEFENSE_RANK_MIDPOINT = 15.5
DEFENSE_RANK_SCALE = 14.5

# Log-odds per point of edge in the pick's direction. Small on purpose:
# there is no projection history, so this weight is a prior. ±0.5, the
# verdict boundary, moves the log-odds by 0.02. The cap binds at ±3.75.
PROJECTION_EDGE_WEIGHT = 0.04

# Walk-forward only. Production returns None when no book posts the modal line.
OFFLINE_MARKET_PRIOR = 0.5

# Platt on the clipped adjustment total. Rewritten by fit_combined_platt.
# Market log-odds is added afterwards with coefficient 1.
PLATT_A = 0.28036258
PLATT_B = 2.15982400

FIT_SAMPLE = {
    "league": "nba",
    "proxy": "MED20",
    "market_prior": OFFLINE_MARKET_PRIOR,
    "cutoff": "2026-03-17",
    "n": 34507,
    "date_start": "2025-11-09",
    "date_end": "2026-03-17",
    "game_types": "regular_season",
    "note": "Platt fit on regular-season rows dated on or before cutoff. Playoffs and the play-in are excluded by the walk-forward game-type filter, the same set CSVPlayerHistoryService._allowed_game_types uses. Later regular-season rows are the holdout and were not used to choose A or B. Market log-odds coefficient is fixed at 1. Holdout n=13751, Brier 0.2309, signed gap +0.0181.",
}
