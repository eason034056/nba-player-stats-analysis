#!/usr/bin/env python3
"""
regression_checks.py - Focused regression checks for agent decision authority
and same-line EV pricing.

Usage:
  python evaluation/regression_checks.py
"""

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


def _fake_hist(base_over_prob: float = 0.2) -> dict:
    return {
        "get_base_stats": {
            "sample_size": 40,
            "reliability": 0.9,
            "details": {"shrunk_rate": base_over_prob},
        },
        "get_trend_analysis": {"reliability": 0.8, "details": {"recent_vs_season_pct": 0.0}},
        "get_shooting_profile": {"reliability": 0.8, "details": {"fg_diff": 0.0}},
        "get_variance_profile": {"details": {"cv": 0.2}},
        "get_schedule_context": {"details": {"is_back_to_back": False}},
        "auto_teammate_impact": {"details": {"teammate_chemistry": []}},
        "get_own_team_injury_report": {"details": {"injuries": []}},
    }


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


def test_synthesizer_cannot_override_scorecard_decision():
    class _FakeResp:
        def __init__(self, content: str):
            self.content = content

    class _FakeLLM:
        def invoke(self, _messages):
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
        result = synthesizer_node({
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
    assert details["pricing_mode"] == "overview_only"
    assert details["matched_n_books"] == 0
    assert details["available_lines"] == [23.5, 24.5]

    sc = compute_scorecard(
        historical_signals=_fake_hist(base_over_prob=0.2),
        projection_signals={},
        market_signals=_fake_market_signals(quote),
        direction="under",
    )
    assert sc["market_pricing_mode"] == "overview_only"
    assert sc["market_implied_probability"] is None
    assert sc["expected_value_pct"] == 0.0
    assert sc["eligible_for_bet"] is False
    assert sc["decision"] == "avoid"
    assert sc["pass_reason"] == "queried line not currently available"


def main():
    tests = [
        test_synthesizer_cannot_override_scorecard_decision,
        test_same_line_quote_only_uses_exact_threshold,
        test_no_exact_line_disables_ev_and_bet,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")


if __name__ == "__main__":
    main()
