"""
scoring.py – Deterministic scoring node.

Aggregates structured signals from Dimensions 1-7 into a single scorecard:
  model_probability, confidence, expected_value_pct, eligible_for_bet.

Design principles:
  - Base historical rate is the anchor (prior).
  - Bounded adjustments from trend, shooting, schedule, teammate context.
  - Correlated signals are capped to prevent double-counting.
  - Projection stub always contributes zero.
  - Low-reliability or small-sample signals are penalized.
  - Market-implied probability is required for bet eligibility.
"""

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------
MAX_TREND_ADJ = 0.08
MAX_SHOOTING_ADJ = 0.05
MAX_SCHEDULE_ADJ = 0.04
MAX_TEAMMATE_ADJ = 0.06
CORRELATION_CAP = 0.10       # max total adjustment from correlated trend+shooting
MIN_SAMPLE_FOR_BET = 10
MIN_EV_FOR_BET = 0.01        # 1 %


def _safe(d: dict, *keys, default=0.0):
    """Drill into nested dict safely."""
    cur = d
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k, default)
        else:
            return default
    return cur if cur is not None else default


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compute_scorecard(
    historical_signals: Dict[str, Any],
    projection_signals: Dict[str, Any],
    market_signals: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build the deterministic decision payload.

    Parameters
    ----------
    historical_signals : dict
        Keyed by tool name -> signal payload (from historical.py).
    projection_signals : dict
        Keyed by tool name -> signal payload (from projection.py – all 'unavailable').
    market_signals : dict
        Keyed by tool name -> signal payload (from market.py).

    Returns
    -------
    dict  with keys:
        decision, confidence, model_probability, market_implied_probability,
        expected_value_pct, best_book, best_line, eligible_for_bet, pass_reason,
        dimension_scores, data_quality_flags
    """

    flags: List[str] = []

    # ------------------------------------------------------------------
    # 1. Baseline from get_base_stats
    # ------------------------------------------------------------------
    base = historical_signals.get("get_base_stats", {})
    base_rate = _safe(base, "details", "shrunk_rate", default=0.5)
    base_n = _safe(base, "sample_size", default=0)
    base_rel = _safe(base, "reliability", default=0.0)

    if base_n < MIN_SAMPLE_FOR_BET:
        flags.append(f"base_sample_too_small ({base_n})")

    model_prob = base_rate

    # ------------------------------------------------------------------
    # 2. Trend adjustment (capped)
    # ------------------------------------------------------------------
    trend = historical_signals.get("get_trend_analysis", {})
    trend_pct = _safe(trend, "details", "recent_vs_season_pct", default=0.0)
    trend_rel = _safe(trend, "reliability", default=0.0)
    trend_adj = _clamp(trend_pct * 0.5 * trend_rel, -MAX_TREND_ADJ, MAX_TREND_ADJ)

    # ------------------------------------------------------------------
    # 3. Shooting adjustment (capped)
    # ------------------------------------------------------------------
    shooting = historical_signals.get("get_shooting_profile", {})
    fg_diff = _safe(shooting, "details", "fg_diff", default=0.0)
    shoot_rel = _safe(shooting, "reliability", default=0.0)
    shoot_adj = _clamp(fg_diff * 0.4 * shoot_rel, -MAX_SHOOTING_ADJ, MAX_SHOOTING_ADJ)

    # Correlation cap: trend + shooting combined
    combined_ts = _clamp(trend_adj + shoot_adj, -CORRELATION_CAP, CORRELATION_CAP)
    model_prob += combined_ts

    # ------------------------------------------------------------------
    # 4. Schedule adjustment
    # ------------------------------------------------------------------
    sched = historical_signals.get("get_schedule_context", {})
    is_b2b = _safe(sched, "details", "is_back_to_back", default=False)
    sched_adj = -0.03 if is_b2b else 0.0
    model_prob += _clamp(sched_adj, -MAX_SCHEDULE_ADJ, MAX_SCHEDULE_ADJ)

    if is_b2b:
        flags.append("back_to_back")

    # ------------------------------------------------------------------
    # 5. Teammate / injury adjustment
    # ------------------------------------------------------------------
    teammate = historical_signals.get("auto_teammate_impact", {})
    tm_chemistry = _safe(teammate, "details", "teammate_chemistry", default=[])
    tm_adj = 0.0
    unresolved_injury = False
    for c in (tm_chemistry if isinstance(tm_chemistry, list) else []):
        status = c.get("injury_status", "Healthy")
        delta = c.get("chemistry_delta", 0)
        if status in ("Questionable", "Day-To-Day"):
            unresolved_injury = True
        if status == "Out":
            tm_adj += (-delta) * 0.01
        elif status in ("Questionable", "Day-To-Day"):
            tm_adj += (-delta) * 0.005

    model_prob += _clamp(tm_adj, -MAX_TEAMMATE_ADJ, MAX_TEAMMATE_ADJ)

    if unresolved_injury:
        flags.append("unresolved_teammate_injury")

    # ------------------------------------------------------------------
    # 6. Variance penalty
    # ------------------------------------------------------------------
    variance = historical_signals.get("get_variance_profile", {})
    cv = _safe(variance, "details", "cv", default=0.0)
    if cv > 0.4:
        flags.append(f"high_variance (cv={cv:.2f})")

    # ------------------------------------------------------------------
    # 7. Projection (always zero)
    # ------------------------------------------------------------------
    # No adjustment – stub data excluded by design.

    # ------------------------------------------------------------------
    # 8. Market comparison
    # ------------------------------------------------------------------
    market = market_signals.get("get_current_market", {})
    market_fair = _safe(market, "details", "consensus_fair_over", default=None)
    best_price_data = market_signals.get("get_best_price", {})
    best_book = _safe(best_price_data, "details", "best_book", default=None)
    best_line = _safe(best_price_data, "details", "best_line", default=None)
    best_fair_prob = _safe(best_price_data, "details", "best_fair_prob", default=None)

    market_implied = float(market_fair) if market_fair else None
    if market_implied is None:
        flags.append("no_market_data")

    # ------------------------------------------------------------------
    # Clamp final probability
    # ------------------------------------------------------------------
    model_prob = _clamp(model_prob, 0.05, 0.95)

    # ------------------------------------------------------------------
    # Expected value
    # ------------------------------------------------------------------
    if market_implied and market_implied > 0:
        ev_pct = (model_prob - market_implied) / market_implied
    else:
        ev_pct = 0.0

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------
    if model_prob >= 0.55:
        decision_candidate = "over"
    elif model_prob <= 0.45:
        decision_candidate = "under"
    else:
        decision_candidate = "avoid"

    # ------------------------------------------------------------------
    # Confidence (reliability-weighted)
    # ------------------------------------------------------------------
    confidence = base_rel * 0.5 + _safe(trend, "reliability", default=0.0) * 0.15 + \
                 _safe(shooting, "reliability", default=0.0) * 0.1 + \
                 _safe(market, "reliability", default=0.0) * 0.25
    confidence = _clamp(confidence, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Eligibility gating
    # ------------------------------------------------------------------
    eligible = True
    pass_reason = None

    if base_n < MIN_SAMPLE_FOR_BET:
        eligible = False
        pass_reason = f"sample size too small ({base_n})"
    elif market_implied is None:
        eligible = False
        pass_reason = "no market price available"
    elif unresolved_injury:
        eligible = False
        pass_reason = "key teammate injury status unresolved"
    elif abs(ev_pct) < MIN_EV_FOR_BET and decision_candidate != "avoid":
        eligible = False
        pass_reason = f"expected value too thin ({ev_pct:.2%})"

    if not eligible and decision_candidate != "avoid":
        decision_candidate = "avoid"

    # ------------------------------------------------------------------
    # Assemble scorecard
    # ------------------------------------------------------------------
    return {
        "decision": decision_candidate,
        "confidence": round(confidence, 3),
        "model_probability": round(model_prob, 4),
        "market_implied_probability": round(market_implied, 4) if market_implied else None,
        "expected_value_pct": round(ev_pct, 4),
        "best_book": best_book,
        "best_line": best_line,
        "eligible_for_bet": eligible,
        "pass_reason": pass_reason,
        "data_quality_flags": flags,
        "adjustments": {
            "base_rate": round(base_rate, 4),
            "trend_adj": round(trend_adj, 4),
            "shoot_adj": round(shoot_adj, 4),
            "combined_ts_capped": round(combined_ts, 4),
            "schedule_adj": round(sched_adj, 4),
            "teammate_adj": round(tm_adj, 4),
        },
    }
