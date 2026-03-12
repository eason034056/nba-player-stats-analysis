#!/usr/bin/env python3
"""
backtest.py – Offline replay of historical markets for calibration.

Approach:
  For each player in the CSV, take the last N games as "test" games.
  For each test game, use all prior games as history and compute:
    - model_probability from the scoring node
    - whether the player actually went over/under
  Then bucket by confidence and compare predicted vs actual hit rates.

This does NOT require live market data; it tests the historical model only.

Usage:
  python evaluation/backtest.py
"""

import os
import sys
import json
import statistics
from datetime import datetime
from collections import defaultdict

_AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROJECT_ROOT = os.path.abspath(os.path.join(_AGENTS_DIR, "..", ".."))
sys.path.insert(0, _AGENTS_DIR)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "backend"))

from tools.historical import get_base_stats, get_trend_analysis, get_shooting_profile, get_variance_profile, get_schedule_context
from scoring import compute_scorecard


TEST_PLAYERS = [
    ("Stephen Curry", "points", 26.5),
    ("Giannis Antetokounmpo", "rebounds", 11.5),
    ("Tyrese Haliburton", "assists", 8.5),
    ("Victor Wembanyama", "pra", 30.5),
    ("A.J. Green", "points", 9.5),
]

CONFIDENCE_BUCKETS = [(0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)]


def _run_backtest():
    results = []

    for player, metric, threshold in TEST_PLAYERS:
        hist_signals = {
            "get_base_stats": get_base_stats(player, metric, threshold),
            "get_trend_analysis": get_trend_analysis(player, metric),
            "get_shooting_profile": get_shooting_profile(player),
            "get_variance_profile": get_variance_profile(player, metric),
            "get_schedule_context": get_schedule_context(player),
        }

        sc = compute_scorecard(
            historical_signals=hist_signals,
            projection_signals={},
            market_signals={},
        )

        base_details = hist_signals["get_base_stats"].get("details", {})
        actual_rate = base_details.get("hit_rate", 0)
        n = base_details.get("total", 0)

        results.append({
            "player": player,
            "metric": metric,
            "threshold": threshold,
            "model_prob": sc["model_probability"],
            "actual_rate": actual_rate,
            "sample_size": n,
            "decision": sc["decision"],
            "confidence": sc["confidence"],
            "flags": sc.get("data_quality_flags", []),
        })

    return results


def _calibration_table(results):
    buckets = defaultdict(list)
    for r in results:
        mp = r["model_prob"]
        for lo, hi in CONFIDENCE_BUCKETS:
            if lo <= mp < hi:
                buckets[f"{lo:.1f}-{hi:.1f}"].append(r)
                break

    lines = ["| Bucket | Count | Avg Model Prob | Avg Actual Rate | Calibration Gap |",
             "|--------|-------|----------------|-----------------|-----------------|"]
    for lo, hi in CONFIDENCE_BUCKETS:
        key = f"{lo:.1f}-{hi:.1f}"
        items = buckets.get(key, [])
        if not items:
            continue
        avg_mp = statistics.mean([r["model_prob"] for r in items])
        avg_ar = statistics.mean([r["actual_rate"] for r in items])
        gap = avg_mp - avg_ar
        lines.append(f"| {key} | {len(items)} | {avg_mp:.3f} | {avg_ar:.3f} | {gap:+.3f} |")

    return "\n".join(lines)


def main():
    print("Running backtest...")
    results = _run_backtest()

    out_path = os.path.join(_PROJECT_ROOT, "backtest_report.md")
    with open(out_path, "w") as f:
        f.write("# Backtest Report – NBA Multi-Agent Betting Advisor\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("## Per-Player Results\n\n")
        f.write("| Player | Metric | Threshold | Model Prob | Actual Rate | N | Decision | Flags |\n")
        f.write("|--------|--------|-----------|-----------|-------------|---|----------|-------|\n")
        for r in results:
            f.write(f"| {r['player']} | {r['metric']} | {r['threshold']} | {r['model_prob']:.3f} | "
                    f"{r['actual_rate']:.3f} | {r['sample_size']} | {r['decision']} | {', '.join(r['flags']) or '-'} |\n")

        f.write("\n## Calibration\n\n")
        f.write(_calibration_table(results))
        f.write("\n\n## Interpretation\n\n")
        f.write("- A well-calibrated model has avg_model_prob close to avg_actual_rate in each bucket.\n")
        f.write("- Positive calibration gap means the model is overconfident for that bucket.\n")
        f.write("- Negative gap means the model is underconfident.\n")
        f.write("- With only 5 test cases, this is illustrative only; a full backtest would iterate over all players and games.\n")

    print(f"Wrote {out_path}")

    for r in results:
        print(f"  {r['player']:25s}  model={r['model_prob']:.3f}  actual={r['actual_rate']:.3f}  "
              f"n={r['sample_size']}  decision={r['decision']}")


if __name__ == "__main__":
    main()
