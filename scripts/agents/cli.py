#!/usr/bin/env python3
"""
cli.py – CLI frontend for the NBA Multi-Agent Betting Advisor.

Usage:
  python cli.py                           # interactive mode
  python cli.py "Should I bet Curry over 28.5 points tonight?"   # one-shot mode
"""

import json
import os
import sys
from datetime import datetime

_AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_AGENTS_DIR, "..", ".."))
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from graph import compile_graph


def _print_header():
    print("\n" + "=" * 64)
    print("  NBA Multi-Agent Betting Advisor (Assignment 4)")
    print("  6 LLM Agents + Deterministic Scoring | 7 Dimensions")
    print("=" * 64)


def _format_scorecard(sc: dict) -> str:
    lines = []
    lines.append(f"  Decision       : {sc.get('decision', '?').upper()}")
    lines.append(f"  Confidence     : {sc.get('confidence', 0):.1%}")
    lines.append(f"  Model Prob     : {sc.get('model_probability', 0):.1%}")
    mip = sc.get('market_implied_probability')
    lines.append(f"  Market Implied : {mip:.1%}" if mip else "  Market Implied : N/A")
    ev = sc.get('expected_value_pct', 0)
    lines.append(f"  Expected Value : {ev:+.2%}")
    bb = sc.get('best_book')
    bl = sc.get('best_line')
    if bb:
        lines.append(f"  Best Book      : {bb} @ {bl}")
    lines.append(f"  Eligible       : {'YES' if sc.get('eligible_for_bet') else 'NO'}")
    pr = sc.get('pass_reason')
    if pr:
        lines.append(f"  Pass Reason    : {pr}")
    flags = sc.get('data_quality_flags', [])
    if flags:
        lines.append(f"  Quality Flags  : {', '.join(flags)}")
    return "\n".join(lines)


def _format_dimensions(dims: dict) -> str:
    lines = []
    for name, info in dims.items():
        if isinstance(info, dict):
            sig = info.get("signal", "?")
            rel = info.get("reliability", 0)
            det = info.get("detail", "")
            lines.append(f"    {name:15s}  {sig:12s}  rel={rel:.2f}  {det[:60]}")
    return "\n".join(lines) if lines else "    (none)"


def run_query(query: str, app=None, verbose: bool = False) -> dict:
    if app is None:
        app = compile_graph()

    today = datetime.now().strftime("%Y-%m-%d")

    initial_state = {
        "messages": [],
        "user_query": query,
        "parsed_query": {},
        "event_context": {},
        "availability": {},
        "historical_signals": {},
        "projection_signals": {},
        "market_signals": {},
        "scorecard": {},
        "data_quality_flags": [],
        "critic_notes": [],
        "final_decision": {},
        "audit_log": [],
        "iteration": 0,
    }

    print(f"\n{'─' * 64}")
    print(f"  Query: {query}")
    print(f"{'─' * 64}")

    # Stream node events
    for event in app.stream(initial_state, stream_mode="updates"):
        for node_name, update in event.items():
            if node_name == "planner":
                pq = update.get("parsed_query", {})
                player = pq.get("player", "?")
                metric = pq.get("metric", "?")
                threshold = pq.get("threshold", "?")
                print(f"  [Planner]    Parsed: {player}, {metric}, {threshold}")

            elif node_name == "historical_agent":
                n_tools = len(update.get("historical_signals", {}))
                print(f"  [Stats]      Ran {n_tools} historical/context tools")

            elif node_name == "projection_agent":
                print(f"  [Projection] Unavailable (SportsDataIO dummy feed excluded)")

            elif node_name == "market_agent":
                ms = update.get("market_signals", {})
                cm = ms.get("get_current_market", {})
                n_books = (cm.get("details") or {}).get("n_books", 0)
                print(f"  [Market]     Loaded {n_books} books")

            elif node_name == "scoring":
                sc = update.get("scorecard", {})
                dec = sc.get("decision", "?").upper()
                mp = sc.get("model_probability", 0)
                mip = sc.get("market_implied_probability")
                ev = sc.get("expected_value_pct", 0)
                mip_str = f"{mip:.1%}" if mip else "N/A"
                print(f"  [Scoring]    Model {mp:.1%} vs Market {mip_str} -> EV {ev:+.2%}")

            elif node_name == "critic":
                notes = update.get("critic_notes", [])
                print(f"  [Critic]     {len(notes)} risk factor(s)")

            elif node_name == "synthesizer":
                fd = update.get("final_decision", {})
                dec = fd.get("decision", "?").upper()
                conf = fd.get("confidence", 0)
                print(f"  [Synth]      Final: {dec} (confidence {conf:.1%})")

    # Gather final state
    final_state = initial_state.copy()
    for event in app.stream(initial_state, stream_mode="updates"):
        for _, update in event.items():
            final_state.update(update)

    fd = final_state.get("final_decision", {})
    sc = final_state.get("scorecard", {})

    print(f"\n{'━' * 64}")
    print("  SCORECARD")
    print("━" * 64)
    print(_format_scorecard(sc))

    dims = fd.get("dimensions", {})
    if dims:
        print(f"\n  DIMENSIONS")
        print(_format_dimensions(dims))

    risks = fd.get("risk_factors", [])
    if risks:
        print(f"\n  RISK FACTORS")
        for r in risks:
            print(f"    - {r}")

    summary = fd.get("summary", "")
    if summary:
        print(f"\n  SUMMARY")
        print(f"    {summary}")

    print(f"\n{'━' * 64}\n")

    if verbose:
        print("\n--- FULL FINAL DECISION JSON ---")
        print(json.dumps(fd, indent=2, default=str))
        print("\n--- FULL SCORECARD JSON ---")
        print(json.dumps(sc, indent=2, default=str))

    return fd


def main():
    _print_header()

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        run_query(query)
        return

    print("\nType a question, or 'quit' to exit.\n")
    app = compile_graph()
    while True:
        try:
            query = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not query:
            continue
        if query.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        try:
            run_query(query, app=app)
        except Exception as e:
            print(f"\n  ERROR: {e}\n")


if __name__ == "__main__":
    main()
