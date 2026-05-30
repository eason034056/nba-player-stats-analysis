"""SPO-73 — direct unit tests for scripts/agents/scoring.py numeric guards.

`scoring.py` is the pick-generation critical path: it turns historical /
projection / market signals into the recommendation scorecard. Today it has
only two happy-path role-blend tests in
``backend/tests/test_role_conditioned_scoring.py``; the deterministic numeric
guard helpers the math depends on are exercised only incidentally. A silent
regression in any of them corrupts *every* recommendation, so this file pins
their edge-case behaviour directly.

Tests only — does NOT modify scoring.py. One focused test per guard helper
hitting bounds / None / empty / zero / both-direction branches, plus two
``compute_scorecard`` edges the role-blend suite does not cover. Assertions pin
*actual* behaviour: notably ``_safe`` only falls back on a missing key, a
non-dict node, or an explicit ``None`` — a present non-numeric value passes
through unchanged. Import style mirrors test_data_logger.py (conftest.py puts
``scripts/agents`` on sys.path, so ``scoring`` is a top-level module).
"""

from scoring import (
    _clamp,
    _historical_rate,
    _query_side_probability,
    _role_confidence_weight,
    _role_sample_discount,
    _round_optional,
    _safe,
    _trend_alignment,
    _unique_names,
    compute_scorecard,
)


def test_clamp_respects_bounds():
    assert _clamp(-1.0, 0.0, 1.0) == 0.0   # below lo -> lo
    assert _clamp(2.0, 0.0, 1.0) == 1.0    # above hi -> hi
    assert _clamp(0.5, 0.0, 1.0) == 0.5    # within -> identity
    assert _clamp(0.0, 0.0, 1.0) == 0.0    # exactly at lo
    assert _clamp(1.0, 0.0, 1.0) == 1.0    # exactly at hi


def test_safe_drills_in_with_graceful_fallback():
    assert _safe({"a": {"b": 7}}, "a", "b", default=0.0) == 7   # present
    assert _safe({"a": 1}, "b", default=0.0) == 0.0             # missing key
    assert _safe({"a": {"x": 1}}, "a", "y", default=0.0) == 0.0  # nested miss
    assert _safe({"a": 5}, "a", "b", default=0.0) == 0.0        # drill thru non-dict
    assert _safe({"a": None}, "a", default=7) == 7             # present None -> default
    # ⚠️ Guard contract: a present non-numeric value is NOT coerced to default.
    assert _safe({"a": "foo"}, "a", default=0.0) == "foo"


def test_round_optional_none_passthrough_vs_round():
    assert _round_optional(None, 2) is None
    assert _round_optional(1.23456, 2) == 1.23


def test_historical_rate_precedence_hit_then_shrunk_then_default():
    assert _historical_rate({"hit_rate": 0.6, "shrunk_rate": 0.4}) == 0.6
    assert _historical_rate({"shrunk_rate": 0.4}) == 0.4
    assert _historical_rate({}, default=0.5) == 0.5


def test_role_confidence_weight_known_vs_unknown():
    assert _role_confidence_weight("high") == 0.85
    assert _role_confidence_weight("medium") == 0.70
    assert _role_confidence_weight("low") == 0.55
    assert _role_confidence_weight("HIGH") == 0.85   # case-insensitive
    assert _role_confidence_weight("bogus") == 0.0   # unknown -> 0
    assert _role_confidence_weight(None) == 0.0       # None -> 0


def test_role_sample_discount_curve_including_zero_sample():
    assert _role_sample_discount(0) == 0.0    # no div-by-zero / over-discount
    assert _role_sample_discount(3) == 0.0    # below MINIMUM_ROLE_SAMPLE (4)
    assert _role_sample_discount(4) == 0.60   # 4..7  -> 0.60
    assert _role_sample_discount(7) == 0.60
    assert _role_sample_discount(8) == 0.80   # 8..11 -> 0.80
    assert _role_sample_discount(11) == 0.80
    assert _role_sample_discount(12) == 1.00  # >=12  -> full weight


def test_query_side_probability_over_under_and_none():
    assert _query_side_probability(0.6, "over") == 0.6
    assert _query_side_probability(0.6, "under") == 0.4   # complements
    assert _query_side_probability(None, "over") is None


def test_unique_names_dedupes_strips_and_preserves_order():
    assert _unique_names(["A", "A", " B ", "", None, "B"]) == ["A", "B"]


def test_trend_alignment_branches():
    assert _trend_alignment("over", None, 5.0) == ("neutral", False)   # None avg
    assert _trend_alignment("over", 5.0, None) == ("neutral", False)   # None threshold
    assert _trend_alignment("over", 5.0, 5.0) == ("neutral", False)    # equal (epsilon)
    assert _trend_alignment("over", 6.0, 5.0) == ("supports_query_side", True)
    assert _trend_alignment("over", 4.0, 5.0) == ("against_query_side", False)
    assert _trend_alignment("under", 4.0, 5.0) == ("supports_query_side", True)
    assert _trend_alignment("under", 6.0, 5.0) == ("against_query_side", False)


# compute_scorecard — edges NOT covered by test_role_conditioned_scoring.py

def test_compute_scorecard_empty_signals_is_graceful_neutral():
    """Empty signal dicts must not crash and must yield a neutral, ineligible
    scorecard with the full key contract intact."""
    card = compute_scorecard({}, {}, {}, direction="over")

    assert card["decision"] == "avoid"
    assert card["eligible_for_bet"] is False
    assert card["pass_reason"] == "sample size too small (0)"
    assert card["model_probability"] == 0.5           # neutral midpoint anchor
    assert card["market_implied_probability"] is None
    assert card["expected_value_pct"] is None
    assert card["query_aligned_context"]["historical"]["mode"] == "all_games"
    assert "base_sample_too_small (0)" in card["data_quality_flags"]
    assert "no_market_data" in card["data_quality_flags"]
    # Downstream synthesizer / CLI depend on these keys always existing.
    for key in (
        "decision", "confidence", "model_probability", "eligible_for_bet",
        "query_aligned_context", "lineup_context", "adjustments",
    ):
        assert key in card


def test_compute_scorecard_sufficient_sample_without_market_is_ineligible():
    """Enough history to clear the sample gate, but no market price -> the
    no-market branch (distinct from sample-too-small) must fire."""
    historical = {
        "get_base_stats": {
            "reliability": 0.9,
            "sample_size": 40,
            "details": {"hit_rate": 0.5, "mean": 25.0},
        }
    }
    card = compute_scorecard(historical, {}, {}, direction="over")

    assert card["eligible_for_bet"] is False
    assert card["pass_reason"] == "no market price available"
    assert "no_market_data" in card["data_quality_flags"]
    # sample gate cleared, so the small-sample flag must be absent.
    assert not any(
        f.startswith("base_sample_too_small") for f in card["data_quality_flags"]
    )
