#!/usr/bin/env python3
"""
run_demos.py – Run 5+ prompt demos and generate sample_outputs.md.

Usage:
  python evaluation/run_demos.py
"""

import asyncio
import json
import os
import sys
import traceback
from datetime import datetime

_AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROJECT_ROOT = os.path.abspath(os.path.join(_AGENTS_DIR, "..", ".."))
sys.path.insert(0, _AGENTS_DIR)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from graph import compile_graph, export_mermaid

DEMO_PROMPTS = [
    "Should I bet Stephen Curry over 28.5 points tonight?",
    "Is Giannis under 12.5 rebounds a good bet?",
    "Should I bet A.J. Green over 10.5 points when Giannis is out?",
    "Who is more consistent for assists overs, Haliburton or Brunson?",
    "Should I bet Victor Wembanyama over 22.5 PRA?",
]


async def _run_one(app, query: str) -> dict:
    """Run a single query through the graph, return full final state."""
    initial = {
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

    final = {}
    async for event in app.astream(initial, stream_mode="updates"):
        for node, update in event.items():
            final.update(update)

    return final


async def main():
    app = compile_graph()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    results = []
    for i, prompt in enumerate(DEMO_PROMPTS, 1):
        print(f"\n{'='*60}")
        print(f"  Demo {i}/{len(DEMO_PROMPTS)}: {prompt}")
        print(f"{'='*60}")
        try:
            state = await _run_one(app, prompt)
            sc = state.get("scorecard", {})
            fd = state.get("final_decision", {})
            critic = state.get("critic_notes", [])

            entry = {
                "prompt": prompt,
                "parsed_query": state.get("parsed_query", {}),
                "scorecard": sc,
                "final_decision": fd,
                "critic_notes": critic,
                "data_quality_flags": state.get("data_quality_flags", []),
                "status": "success",
            }
            results.append(entry)

            print(f"  Decision: {fd.get('decision', '?').upper()}")
            print(f"  Confidence: {fd.get('confidence', 0)}")
            print(f"  Model Prob: {sc.get('model_probability', 0)}")
            print(f"  EV: {sc.get('expected_value_pct', 0)}")
        except Exception as e:
            traceback.print_exc()
            results.append({"prompt": prompt, "status": "error", "error": str(e)})

    # Generate sample_outputs.md
    out_path = os.path.join(_PROJECT_ROOT, "sample_outputs.md")
    mermaid = ""
    try:
        mermaid = export_mermaid()
    except Exception:
        mermaid = "(mermaid export failed)"

    with open(out_path, "w") as f:
        f.write(f"# Sample Outputs – NBA Multi-Agent Betting Advisor\n\n")
        f.write(f"Generated: {timestamp}\n\n")

        f.write("## Agent Graph\n\n")
        f.write(f"```mermaid\n{mermaid}\n```\n\n")

        f.write("---\n\n")

        for i, r in enumerate(results, 1):
            f.write(f"## Demo {i}: {r['prompt']}\n\n")

            if r["status"] == "error":
                f.write(f"**ERROR**: {r.get('error')}\n\n")
                continue

            pq = r.get("parsed_query", {})
            f.write(f"**Parsed**: player=`{pq.get('player')}`, metric=`{pq.get('metric')}`, "
                    f"threshold=`{pq.get('threshold')}`, direction=`{pq.get('direction', 'over')}`\n\n")

            sc = r.get("scorecard", {})
            f.write("### Scorecard\n\n")
            f.write(f"| Field | Value |\n|---|---|\n")
            sc_dir = sc.get('direction', 'over')
            f.write(f"| Direction | {sc_dir} |\n")
            f.write(f"| Decision | **{sc.get('decision', '?').upper()}** |\n")
            f.write(f"| Confidence | {sc.get('confidence', 0):.1%} |\n")
            f.write(f"| Model Probability ({sc_dir}) | {sc.get('model_probability', 0):.1%} |\n")
            mip = sc.get('market_implied_probability')
            f.write(f"| Market Implied ({sc_dir}) | {f'{mip:.1%}' if mip else 'N/A'} |\n")
            f.write(f"| Expected Value | {sc.get('expected_value_pct', 0):+.2%} |\n")
            f.write(f"| Best Book | {sc.get('best_book', 'N/A')} |\n")
            f.write(f"| Eligible | {'Yes' if sc.get('eligible_for_bet') else 'No'} |\n")
            pr = sc.get('pass_reason')
            if pr:
                f.write(f"| Pass Reason | {pr} |\n")
            f.write("\n")

            flags = r.get("data_quality_flags", [])
            if flags:
                f.write("**Data Quality Flags**: " + ", ".join(flags) + "\n\n")

            fd = r.get("final_decision", {})
            dims = fd.get("dimensions", {})
            if dims:
                f.write("### Dimension Signals\n\n")
                f.write("| Dimension | Signal | Reliability | Detail |\n|---|---|---|---|\n")
                for dname, dinfo in dims.items():
                    if isinstance(dinfo, dict):
                        f.write(f"| {dname} | {dinfo.get('signal','?')} | {dinfo.get('reliability',0):.2f} | {str(dinfo.get('detail',''))[:80]} |\n")
                f.write("\n")

            critic = r.get("critic_notes", [])
            if critic:
                f.write("### Critic Risk Factors\n\n")
                for c in critic:
                    f.write(f"- {c}\n")
                f.write("\n")

            summary = fd.get("summary", "")
            if summary:
                f.write(f"### Summary\n\n{summary}\n\n")

            f.write("---\n\n")

    print(f"\n\nWrote {out_path}")
    print(f"Total demos: {len(results)}, Successes: {sum(1 for r in results if r['status']=='success')}")


if __name__ == "__main__":
    asyncio.run(main())
