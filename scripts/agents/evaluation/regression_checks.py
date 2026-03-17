#!/usr/bin/env python3
"""
regression_checks.py - Focused regression checks for agent decision authority
and same-line EV pricing.

Usage:
  python evaluation/regression_checks.py
"""

import asyncio
import json
import os
import sys

_AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROJECT_ROOT = os.path.abspath(os.path.join(_AGENTS_DIR, "..", ".."))
sys.path.insert(0, _AGENTS_DIR)

import agents as agents_module
from agents import synthesizer_node
from scoring import compute_scorecard
from tools.market import _build_market_quote_for_line


def _fake_hist(
    base_over_prob: float = 0.2,
    *,
    base_mean: float = 20.0,
    player_is_projected_starter: bool | None = None,
    lineup_confidence: str = "high",
    source_disagreement: bool = False,
    freshness_risk: bool = False,
    role_over_prob: float | None = None,
    role_mean: float | None = None,
    role_sample_size: int = 12,
    role_reliability: float = 0.7,
) -> dict:
    hist = {
        "get_base_stats": {
            "sample_size": 40,
            "reliability": 0.9,
            "details": {"shrunk_rate": base_over_prob, "mean": base_mean},
        },
        "get_trend_analysis": {"reliability": 0.8, "details": {"recent_vs_season_pct": 0.0}},
        "get_shooting_profile": {"reliability": 0.8, "details": {"fg_diff": 0.0}},
        "get_variance_profile": {"details": {"cv": 0.2}},
        "get_schedule_context": {"details": {"is_back_to_back": False}},
        "auto_teammate_impact": {"details": {"teammate_chemistry": []}},
        "get_own_team_injury_report": {"details": {"injuries": []}},
    }
    if player_is_projected_starter is not None:
        hist["get_player_lineup_context"] = {
            "details": {
                "player_is_projected_starter": player_is_projected_starter,
                "confidence": lineup_confidence,
                "source_disagreement": source_disagreement,
                "freshness_risk": freshness_risk,
            }
        }
        hist["get_own_team_projected_lineup"] = {
            "details": {
                "team": "BOS",
                "status": "projected",
                "confidence": lineup_confidence,
                "source_disagreement": source_disagreement,
                "updated_at": "2026-03-16T20:00:00Z",
                "starters": ["A", "B", "C", "D", "E"],
            }
        }
        hist["get_opponent_projected_lineup"] = {
            "details": {
                "team": "LAL",
                "status": "projected",
                "confidence": lineup_confidence,
                "source_disagreement": False,
                "updated_at": "2026-03-16T20:00:00Z",
                "starters": ["F", "G", "H", "I", "J"],
            }
        }
    if role_over_prob is not None and role_mean is not None and player_is_projected_starter is not None:
        hist["get_role_conditioned_base_stats"] = {
            "sample_size": role_sample_size,
            "reliability": role_reliability,
            "details": {
                "shrunk_rate": role_over_prob,
                "mean": role_mean,
                "role": "starter" if player_is_projected_starter else "bench",
                "role_label": "projected_starter" if player_is_projected_starter else "projected_bench",
                "minimum_role_sample": 4,
            },
        }
    return hist


def _fake_market_signals(query_quote: dict) -> dict:
    return {
        "get_current_market": {
            "reliability": 0.3,
            "details": {
                # Deliberately wrong for the queried side so we can prove
                # compute_scorecard ignores mixed-line overview pricing.
                "consensus_fair_over": 0.9,
                "books": [],
                "n_books": 2,
            },
        },
        "get_market_quote_for_line": query_quote,
    }


async def test_synthesizer_cannot_override_scorecard_decision():
    class _FakeResp:
        def __init__(self, content: str):
            self.content = content

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _FakeResp(json.dumps({
                "decision": "avoid",
                "confidence": 0.11,
                "model_probability": 0.11,
                "market_implied_probability": 0.11,
                "expected_value_pct": -0.1,
                "dimensions": {},
                "risk_factors": ["llm tried to override"],
                "summary": "LLM returned avoid",
                "needs_retry": False,
                "retry_reason": None,
            }))

    old_get_llm = agents_module._get_llm
    agents_module._get_llm = lambda: _FakeLLM()
    try:
        result = await synthesizer_node({
            "scorecard": {
                "decision": "under",
                "confidence": 0.72,
                "model_probability": 0.73,
                "market_implied_probability": 0.51,
                "expected_value_pct": 0.43,
            },
            "historical_signals": {},
            "market_signals": {},
            "projection_signals": {},
            "critic_notes": ["high variance"],
            "iteration": 0,
        })
        assert result["final_decision"]["decision"] == "under"
    finally:
        agents_module._get_llm = old_get_llm


def test_same_line_quote_only_uses_exact_threshold():
    lines = [
        {
            "bookmaker": "book_a",
            "line": 23.5,
            "over_odds": -101,
            "under_odds": -119,
            "fair_over": 0.49,
            "fair_under": 0.51,
        },
        {
            "bookmaker": "book_b",
            "line": 24.5,
            "over_odds": -110,
            "under_odds": -120,
            "fair_over": 0.40,
            "fair_under": 0.60,
        },
    ]
    quote = _build_market_quote_for_line(lines, 24.5, "under")
    details = quote["details"]
    assert details["pricing_mode"] == "exact_line"
    assert details["matched_n_books"] == 1
    assert details["best_line"] == 24.5
    assert details["market_implied_for_query"] == 0.6

    sc = compute_scorecard(
        historical_signals=_fake_hist(base_over_prob=0.2),
        projection_signals={},
        market_signals=_fake_market_signals(quote),
        direction="under",
    )
    assert sc["market_pricing_mode"] == "exact_line"
    assert sc["market_implied_probability"] == 0.6
    assert sc["expected_value_pct"] == 0.3333
    assert sc["best_line"] == 24.5
    assert sc["query_aligned_context"]["query_side"] == "under"
    assert sc["query_aligned_context"]["historical"]["query_probability"] == 0.8
    assert sc["query_aligned_context"]["market"]["query_probability"] == 0.6
    assert sc["query_aligned_context"]["market"]["pricing_mode"] == "exact_line"


def test_no_exact_line_disables_ev_and_bet():
    lines = [
        {
            "bookmaker": "book_a",
            "line": 23.5,
            "over_odds": -101,
            "under_odds": -119,
            "fair_over": 0.49,
            "fair_under": 0.51,
        },
        {
            "bookmaker": "book_b",
            "line": 24.5,
            "over_odds": -110,
            "under_odds": -120,
            "fair_over": 0.40,
            "fair_under": 0.60,
        },
    ]
    quote = _build_market_quote_for_line(lines, 24.0, "under")
    details = quote["details"]
    assert details["pricing_mode"] == "line_moved"
    assert details["matched_n_books"] == 1
    assert details["available_lines"] == [23.5, 24.5]
    assert details["best_line"] == 23.5

    sc = compute_scorecard(
        historical_signals=_fake_hist(base_over_prob=0.2),
        projection_signals={},
        market_signals=_fake_market_signals(quote),
        direction="under",
    )
    assert sc["market_pricing_mode"] == "line_moved"
    assert sc["market_implied_probability"] is None
    assert sc["expected_value_pct"] is None
    assert sc["eligible_for_bet"] is False
    assert sc["decision"] == "avoid"
    assert sc["pass_reason"] == "live market line moved from pick"
    assert sc["query_aligned_context"]["market"]["query_probability"] is None
    assert sc["query_aligned_context"]["market"]["pricing_mode"] == "line_moved"
    assert sc["query_aligned_context"]["market"]["best_line"] == 23.5


def test_query_aligned_probabilities_follow_direction():
    lines = [
        {
            "bookmaker": "book_a",
            "line": 24.5,
            "over_odds": -110,
            "under_odds": -120,
            "fair_over": 0.4,
            "fair_under": 0.6,
        },
    ]

    over_quote = _build_market_quote_for_line(lines, 24.5, "over")
    over_sc = compute_scorecard(
        historical_signals=_fake_hist(base_over_prob=0.2),
        projection_signals={},
        market_signals=_fake_market_signals(over_quote),
        direction="over",
    )
    assert over_sc["query_aligned_context"]["historical"]["query_probability"] == 0.2
    assert over_sc["query_aligned_context"]["market"]["query_probability"] == 0.4

    under_quote = _build_market_quote_for_line(lines, 24.5, "under")
    under_sc = compute_scorecard(
        historical_signals=_fake_hist(base_over_prob=0.2),
        projection_signals={},
        market_signals=_fake_market_signals(under_quote),
        direction="under",
    )
    assert under_sc["query_aligned_context"]["historical"]["query_probability"] == 0.8
    assert under_sc["query_aligned_context"]["market"]["query_probability"] == 0.6


def test_under_query_alignment_marks_conflicting_trend_signal():
    hist = _fake_hist(base_over_prob=0.1136)
    hist["get_base_stats"]["details"]["mean"] = 2.98
    hist["get_trend_analysis"]["details"] = {
        "rolling_averages": {"last_3": 5.33, "last_5": 5.33, "last_10": None, "last_20": None},
        "season_avg": 2.98,
        "recent_vs_season_pct": 0.2,
    }

    quote = _build_market_quote_for_line(
        [
            {
                "bookmaker": "book_b",
                "line": 4.5,
                "over_odds": -108,
                "under_odds": -112,
                "fair_over": 0.4677,
                "fair_under": 0.5323,
            },
        ],
        4.5,
        "under",
    )
    sc = compute_scorecard(
        historical_signals=hist,
        projection_signals={},
        market_signals=_fake_market_signals(quote),
        direction="under",
    )

    assert sc["query_aligned_context"]["historical"]["query_probability"] == 0.8864
    assert sc["query_aligned_context"]["trend"]["window"] == "last_5"
    assert sc["query_aligned_context"]["trend"]["recent_average"] == 5.33
    assert sc["query_aligned_context"]["trend"]["supports_query_side"] is False
    assert sc["query_aligned_context"]["trend"]["signal_alignment"] == "against_query_side"
    assert sc["query_aligned_context"]["market"]["query_probability"] == 0.5323


def test_role_conditioned_base_changes_decision_for_same_market():
    lines = [
        {
            "bookmaker": "book_a",
            "line": 25.5,
            "over_odds": -110,
            "under_odds": -110,
            "fair_over": 0.48,
            "fair_under": 0.52,
        },
    ]
    quote = _build_market_quote_for_line(lines, 25.5, "over")

    baseline = compute_scorecard(
        historical_signals=_fake_hist(base_over_prob=0.52, base_mean=26.0, player_is_projected_starter=True),
        projection_signals={},
        market_signals=_fake_market_signals(quote),
        direction="over",
    )
    starter = compute_scorecard(
        historical_signals=_fake_hist(
            base_over_prob=0.52,
            base_mean=26.0,
            player_is_projected_starter=True,
            role_over_prob=0.82,
            role_mean=31.0,
        ),
        projection_signals={},
        market_signals=_fake_market_signals(quote),
        direction="over",
    )
    bench = compute_scorecard(
        historical_signals=_fake_hist(
            base_over_prob=0.52,
            base_mean=26.0,
            player_is_projected_starter=False,
            role_over_prob=0.22,
            role_mean=18.0,
        ),
        projection_signals={},
        market_signals=_fake_market_signals(quote),
        direction="over",
    )

    assert baseline["decision"] == "avoid"
    assert starter["decision"] == "over"
    assert bench["decision"] == "under"
    assert starter["query_aligned_context"]["historical"]["mode"] == "role_blended"
    assert bench["query_aligned_context"]["historical"]["mode"] == "role_blended"


async def main():
    await test_synthesizer_cannot_override_scorecard_decision()
    print("PASS test_synthesizer_cannot_override_scorecard_decision")

    for test in (
        test_same_line_quote_only_uses_exact_threshold,
        test_no_exact_line_disables_ev_and_bet,
        test_query_aligned_probabilities_follow_direction,
        test_under_query_alignment_marks_conflicting_trend_signal,
        test_role_conditioned_base_changes_decision_for_same_market,
    ):
        test()
        print(f"PASS {test.__name__}")


if __name__ == "__main__":
    asyncio.run(main())
