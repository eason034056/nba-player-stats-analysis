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
MAX_ROLE_WEIGHT = 0.85
MINIMUM_ROLE_SAMPLE = 4


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


def _round_optional(val: Optional[float], digits: int) -> Optional[float]:
    if val is None:
        return None
    return round(float(val), digits)


def _historical_rate(details: Dict[str, Any], *, default: float = 0.5) -> float:
    raw_rate = details.get("hit_rate")
    if raw_rate is not None:
        return float(raw_rate)

    shrunk_rate = details.get("shrunk_rate")
    if shrunk_rate is not None:
        return float(shrunk_rate)

    return default


def _role_confidence_weight(confidence: Optional[str]) -> float:
    return {
        "high": 0.85,
        "medium": 0.70,
        "low": 0.55,
    }.get(str(confidence or "").lower(), 0.0)


def _role_sample_discount(sample_size: int) -> float:
    if sample_size < MINIMUM_ROLE_SAMPLE:
        return 0.0
    if sample_size <= 7:
        return 0.60
    if sample_size <= 11:
        return 0.80
    return 1.00


def _query_side_probability(p_over: Optional[float], direction: str) -> Optional[float]:
    if p_over is None:
        return None
    return 1.0 - float(p_over) if direction == "under" else float(p_over)


def _unique_names(names: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for name in names:
        clean = str(name or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _trend_alignment(
    query_side: str,
    recent_average: Optional[float],
    threshold: Optional[float],
) -> tuple[str, bool]:
    if recent_average is None or threshold is None:
        return "neutral", False

    if abs(recent_average - threshold) < 1e-9:
        return "neutral", False

    supports = (recent_average > threshold) if query_side == "over" else (recent_average < threshold)
    return ("supports_query_side" if supports else "against_query_side"), supports


def _lineup_team_context(details: dict, player_is_projected_starter: Optional[bool]) -> Optional[Dict[str, Any]]:
    team = str(details.get("team", "")).strip()
    status = str(details.get("status", "")).strip()
    if not team or not status:
        return None
    return {
        "team": team,
        "status": status,
        "confidence": details.get("confidence"),
        "source_disagreement": bool(details.get("source_disagreement")),
        "updated_at": details.get("updated_at"),
        "player_is_projected_starter": player_is_projected_starter,
        "starters": list(details.get("starters") or []),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compute_scorecard(
    historical_signals: Dict[str, Any],
    projection_signals: Dict[str, Any],
    market_signals: Dict[str, Any],
    direction: str = "over",
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
    direction : str
        "over" | "under" | "any". When "under", model/market/EV use P(under) instead of P(over).

    Returns
    -------
    dict  with keys:
        decision, confidence, model_probability, market_implied_probability,
        expected_value_pct, best_book, best_line, eligible_for_bet, pass_reason,
        dimension_scores, data_quality_flags
    """

    flags: List[str] = []
    dir_lower = (direction or "over").lower()

    # ------------------------------------------------------------------
    # 1. Baseline from get_base_stats + projected role context
    # ------------------------------------------------------------------
    base = historical_signals.get("get_base_stats", {})
    base_details = _safe(base, "details", default={})
    all_games_rate = _historical_rate(base_details, default=0.5)
    all_games_mean = _safe(base, "details", "mean", default=None)
    all_games_rel = float(_safe(base, "reliability", default=0.0))
    base_n = int(_safe(base, "sample_size", default=0) or 0)

    if base_n < MIN_SAMPLE_FOR_BET:
        flags.append(f"base_sample_too_small ({base_n})")

    player_lineup = historical_signals.get("get_player_lineup_context", {})
    own_team_lineup = historical_signals.get("get_own_team_projected_lineup", {})
    opponent_lineup = historical_signals.get("get_opponent_projected_lineup", {})
    player_lineup_details = _safe(player_lineup, "details", default={})
    own_team_lineup_details = _safe(own_team_lineup, "details", default={})
    opponent_lineup_details = _safe(opponent_lineup, "details", default={})

    player_is_projected_starter = player_lineup_details.get("player_is_projected_starter")
    lineup_source_disagreement = bool(
        player_lineup_details.get("source_disagreement")
        or own_team_lineup_details.get("source_disagreement")
        or opponent_lineup_details.get("source_disagreement")
    )
    freshness_risk = bool(player_lineup_details.get("freshness_risk"))
    lineup_confidence = (
        player_lineup_details.get("confidence")
        or own_team_lineup_details.get("confidence")
        or opponent_lineup_details.get("confidence")
    )

    if player_is_projected_starter is False:
        flags.append("player_not_in_projected_starting_lineup")
    if lineup_source_disagreement:
        flags.append("lineup_sources_disagree")
    if freshness_risk:
        flags.append("stale_lineup_context")

    role_base = historical_signals.get("get_role_conditioned_base_stats", {})
    role_base_details = _safe(role_base, "details", default={})
    role_rate = (
        _historical_rate(role_base_details, default=0.5)
        if isinstance(role_base_details, dict) and role_base_details
        else None
    )
    role_mean = _safe(role_base, "details", "mean", default=None)
    role_rel = _safe(role_base, "reliability", default=None)
    role_sample_size = int(_safe(role_base, "sample_size", default=0) or 0)
    role_name = role_base_details.get("role")
    if not role_name and isinstance(player_is_projected_starter, bool):
        role_name = "starter" if player_is_projected_starter else "bench"

    role_weight = 0.0
    if (
        isinstance(player_is_projected_starter, bool)
        and role_rate is not None
        and role_mean is not None
        and role_sample_size >= MINIMUM_ROLE_SAMPLE
    ):
        role_weight = _role_confidence_weight(lineup_confidence)
        role_weight *= _role_sample_discount(role_sample_size)
        if lineup_source_disagreement:
            role_weight *= 0.50
        if freshness_risk:
            role_weight *= 0.50
    role_weight = _clamp(role_weight, 0.0, MAX_ROLE_WEIGHT)

    blended_base_rate = all_games_rate
    if role_weight > 0.0 and role_rate is not None:
        blended_base_rate = role_weight * float(role_rate) + (1.0 - role_weight) * all_games_rate

    blended_base_mean = float(all_games_mean) if all_games_mean is not None else None
    if role_weight > 0.0 and role_mean is not None and all_games_mean is not None:
        blended_base_mean = role_weight * float(role_mean) + (1.0 - role_weight) * float(all_games_mean)
    elif role_weight > 0.0 and role_mean is not None and blended_base_mean is None:
        blended_base_mean = float(role_mean)

    blended_base_rel = all_games_rel
    if role_weight > 0.0 and role_rel is not None:
        blended_base_rel = role_weight * float(role_rel) + (1.0 - role_weight) * all_games_rel

    historical_mode = "role_blended" if role_weight > 0.0 else "all_games"
    model_prob = blended_base_rate

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
    # 5. Teammate / own-team injury adjustment
    # ------------------------------------------------------------------
    teammate = historical_signals.get("auto_teammate_impact", {})
    tm_chemistry = _safe(teammate, "details", "teammate_chemistry", default=[])
    tm_adj = 0.0
    unresolved_injury = False
    out_stars = []
    questionable_stars = []

    for c in (tm_chemistry if isinstance(tm_chemistry, list) else []):
        status = c.get("injury_status", "Healthy")
        delta = c.get("chemistry_delta", 0)
        star = c.get("star", "")
        w_n = c.get("with", {}).get("n", 0) or 0
        wo_n = c.get("without", {}).get("n", 0) or 0
        has_data = w_n >= 3 and wo_n >= 3

        if status in ("Questionable", "Day-To-Day"):
            unresolved_injury = True
            questionable_stars.append(star)

        if status == "Out" and has_data:
            tm_adj += (-delta) * 0.02
            out_stars.append(star)
        elif status in ("Questionable", "Day-To-Day") and has_data:
            tm_adj += (-delta) * 0.01

    own_report = historical_signals.get("get_own_team_injury_report", {})
    own_injuries = _safe(own_report, "details", "injuries", default=[])
    serious_out = [
        e for e in (own_injuries if isinstance(own_injuries, list) else [])
        if e.get("status", "") in ("Out",)
    ]
    questionable_list = [
        e for e in (own_injuries if isinstance(own_injuries, list) else [])
        if e.get("status", "") in ("Questionable", "Day-To-Day")
    ]

    if len(serious_out) >= 3:
        tm_adj -= 0.02
        flags.append(f"multiple_teammates_out ({len(serious_out)} confirmed out)")

    if questionable_list:
        flags.append(
            f"teammates_questionable: {', '.join(e.get('player', '?') for e in questionable_list[:5])}"
        )

    model_prob += _clamp(tm_adj, -MAX_TEAMMATE_ADJ, MAX_TEAMMATE_ADJ)

    if unresolved_injury:
        flags.append("unresolved_teammate_injury")
    if out_stars:
        flags.append(f"star_teammates_out: {', '.join(out_stars)}")

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
    market_quote = market_signals.get("get_market_quote_for_line", {})
    pricing_mode = _safe(market_quote, "details", "pricing_mode", default="unavailable")
    queried_line = _safe(market_quote, "details", "queried_line", default=None)
    available_lines = _safe(market_quote, "details", "available_lines", default=[])
    market_implied_for_query = _safe(market_quote, "details", "market_implied_for_query", default=None)
    best_book = _safe(market_quote, "details", "best_book", default=None)
    best_line = _safe(market_quote, "details", "best_line", default=None)
    best_odds = _safe(market_quote, "details", "best_odds", default=None)
    has_current_market = market.get("signal") != "unavailable" and _safe(
        market, "details", "n_books", default=0
    ) > 0

    # ------------------------------------------------------------------
    # Clamp final probability
    # ------------------------------------------------------------------
    model_prob = _clamp(model_prob, 0.05, 0.95)

    # ------------------------------------------------------------------
    # Direction-aware: user asked over vs under
    # ------------------------------------------------------------------
    model_prob_display = _query_side_probability(model_prob, dir_lower) or 0.0
    market_implied = (
        float(market_implied_for_query)
        if pricing_mode == "exact_line" and market_implied_for_query is not None
        else None
    )

    if pricing_mode == "line_moved":
        flags.append("line_moved")
        if available_lines:
            flags.append(f"available_lines: {', '.join(str(line) for line in available_lines)}")
    elif not has_current_market:
        flags.append("no_market_data")
    elif market_implied is None:
        flags.append("no_market_data")

    # ------------------------------------------------------------------
    # Expected value（針對用戶問的方向）
    # ------------------------------------------------------------------
    if market_implied is not None and market_implied > 0:
        ev_pct = (model_prob_display - market_implied) / market_implied
    else:
        ev_pct = None

    trend_details = trend.get("details", {}) if isinstance(trend, dict) else {}
    rolling_averages = trend_details.get("rolling_averages", {}) if isinstance(trend_details, dict) else {}
    season_average = trend_details.get("season_avg")
    recent_average = rolling_averages.get("last_5") if isinstance(rolling_averages, dict) else None
    if recent_average is None:
        recent_average = season_average

    trend_alignment, trend_supports_query_side = _trend_alignment(
        dir_lower,
        recent_average,
        queried_line,
    )
    historical_query_probability = _query_side_probability(blended_base_rate, dir_lower) or 0.0
    historical_p_over = blended_base_rate
    historical_p_under = 1.0 - blended_base_rate
    all_games_query_probability = _query_side_probability(all_games_rate, dir_lower)
    role_query_probability = _query_side_probability(role_rate, dir_lower) if role_rate is not None else None

    questionable_players = _unique_names(
        [e.get("player", "") for e in questionable_list]
        + questionable_stars
    )
    out_players = _unique_names(
        [e.get("player", "") for e in serious_out]
        + out_stars
    )

    query_aligned_context = {
        "query_side": dir_lower,
        "historical": {
            "mode": historical_mode,
            "role": role_name,
            "p_over": round(historical_p_over, 4),
            "p_under": round(historical_p_under, 4),
            "query_probability": round(historical_query_probability, 4),
            "all_games_query_probability": _round_optional(all_games_query_probability, 4),
            "role_query_probability": _round_optional(role_query_probability, 4),
            "role_weight": round(role_weight, 4),
            "role_sample_size": role_sample_size,
            "mean": _round_optional(blended_base_mean, 2),
            "threshold": _round_optional(queried_line, 2),
            "mean_minus_threshold": (
                round(float(blended_base_mean) - float(queried_line), 2)
                if blended_base_mean is not None and queried_line is not None
                else None
            ),
            "supports_query_side": historical_query_probability >= 0.5,
        },
        "trend": {
            "window": "last_5",
            "recent_average": _round_optional(recent_average, 2),
            "season_average": _round_optional(season_average, 2),
            "recent_minus_threshold": (
                round(float(recent_average) - float(queried_line), 2)
                if recent_average is not None and queried_line is not None
                else None
            ),
            "supports_query_side": trend_supports_query_side,
            "signal_alignment": trend_alignment,
        },
        "market": {
            "pricing_mode": pricing_mode,
            "query_probability": round(market_implied, 4) if market_implied is not None else None,
            "queried_line": _round_optional(queried_line, 2),
            "best_line": _round_optional(best_line, 2),
            "available_lines": [round(float(line), 2) for line in available_lines],
            "best_book": best_book,
            "best_odds": best_odds,
        },
        "schedule": {
            "is_back_to_back": bool(is_b2b),
        },
        "injuries": {
            "unresolved": unresolved_injury or bool(questionable_players),
            "questionable_players": questionable_players,
            "out_players": out_players,
        },
        "lineup": {
            "player_is_projected_starter": player_is_projected_starter,
            "source_disagreement": lineup_source_disagreement,
            "freshness_risk": freshness_risk,
        },
    }

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
    confidence = blended_base_rel * 0.5 + _safe(trend, "reliability", default=0.0) * 0.15 + \
                 _safe(shooting, "reliability", default=0.0) * 0.1 + \
                 _safe(market, "reliability", default=0.0) * 0.25
    if lineup_source_disagreement:
        confidence -= 0.05
    if freshness_risk:
        confidence -= 0.05
    confidence = _clamp(confidence, 0.0, 1.0)

    lineup_summary = "Lineup context is unavailable."
    if player_is_projected_starter is True and not lineup_source_disagreement and not freshness_risk:
        lineup_summary = "Projected starters are aligned across both sources and the player's role looks stable."
    elif player_is_projected_starter is False:
        lineup_summary = "Player is outside the projected starting five, which raises rotation uncertainty."
    elif lineup_source_disagreement:
        lineup_summary = "Free lineup sources still disagree, so lineup context is moving."
    elif freshness_risk:
        lineup_summary = "Lineup data is stale and should be treated as a soft signal."

    lineup_context = {
        "summary": lineup_summary,
        "freshness_risk": freshness_risk,
        "player_team": _lineup_team_context(own_team_lineup_details, player_is_projected_starter),
        "opponent_team": _lineup_team_context(opponent_lineup_details, None),
    }

    # ------------------------------------------------------------------
    # Eligibility gating
    # ------------------------------------------------------------------
    eligible = True
    pass_reason = None

    if base_n < MIN_SAMPLE_FOR_BET:
        eligible = False
        pass_reason = f"sample size too small ({base_n})"
    elif pricing_mode == "line_moved":
        eligible = False
        pass_reason = "live market line moved from pick"
    elif not has_current_market or market_implied is None:
        eligible = False
        pass_reason = "no market price available"
    elif unresolved_injury:
        eligible = False
        pass_reason = "key teammate injury status unresolved"
    elif ev_pct is not None and abs(ev_pct) < MIN_EV_FOR_BET and decision_candidate != "avoid":
        eligible = False
        pass_reason = f"expected value too thin ({ev_pct:.2%})"

    if not eligible and decision_candidate != "avoid":
        decision_candidate = "avoid"

    # ------------------------------------------------------------------
    # Assemble scorecard
    # ------------------------------------------------------------------
    return {
        "decision": decision_candidate,
        "direction": dir_lower,  # 用戶問的方向，供 CLI 顯示
        "confidence": round(confidence, 3),
        "model_probability": round(model_prob_display, 4),
        "market_implied_probability": round(market_implied, 4) if market_implied is not None else None,
        "expected_value_pct": round(ev_pct, 4) if ev_pct is not None else None,
        "market_pricing_mode": pricing_mode,
        "queried_line": queried_line,
        "available_lines": available_lines,
        "best_book": best_book,
        "best_line": best_line,
        "best_odds": best_odds,
        "eligible_for_bet": eligible,
        "pass_reason": pass_reason,
        "data_quality_flags": flags,
        "query_aligned_context": query_aligned_context,
        "lineup_context": lineup_context,
        "adjustments": {
            "base_rate_over": round(blended_base_rate, 4),
            "base_rate_over_all_games": round(all_games_rate, 4),
            "base_rate_over_role": round(float(role_rate), 4) if role_rate is not None else None,
            "base_rate_over_blended": round(blended_base_rate, 4),
            "base_rate_display": round(model_prob_display, 4),
            "role_weight": round(role_weight, 4),
            "trend_adj": round(trend_adj, 4),
            "shoot_adj": round(shoot_adj, 4),
            "combined_ts_capped": round(combined_ts, 4),
            "schedule_adj": round(sched_adj, 4),
            "teammate_adj": round(tm_adj, 4),
            "note": "base_rate_over and base_rate_over_blended are always P(over). base_rate_display is adjusted for user direction.",
        },
    }
