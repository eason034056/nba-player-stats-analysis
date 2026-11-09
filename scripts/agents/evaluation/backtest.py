#!/usr/bin/env python3
"""Walk-forward backtest of Daily Picks and the agent scorecard.

Replays every scored player-game with history strictly before that game.
The default proxy is MED20. L10 is the supported alternative. ROI is
-110 and CLV is not measured unless ``--odds-history`` points at a file
of opening and closing lines.

From the repository root:

    pip install -r backend/requirements.txt -r scripts/agents/requirements_agents.txt
    python scripts/agents/evaluation/backtest.py --report backtest_report.md
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time

# The script's own directory is put on sys.path[0] by Python, which hides
# the `evaluation` package that lives one level up. Put `scripts/agents`
# in front so `import evaluation` resolves.
_AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)

from evaluation.assumptions import assumption_lines  # noqa: E402
from evaluation.calibration_guard import evaluate_guard, run_sample_guard  # noqa: E402
from evaluation.metrics import summarize  # noqa: E402
from evaluation.odds_history import load_odds_history  # noqa: E402
from evaluation.oracle import ORACLE_SOURCE, compare_oracle  # noqa: E402
from evaluation.paths import bootstrap  # noqa: E402
from evaluation.proxy_lines import DEFAULT_PROXIES  # noqa: E402
from evaluation.report import render_report  # noqa: E402
from evaluation.walk_forward import (
    inventory,
    load_historical,
    replay_league,
    select_players,
)  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk-forward backtest of Daily Picks and the agent scorecard."
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Write the markdown report to this path. Relative paths are from the current directory.",
    )
    parser.add_argument(
        "--proxies",
        default=",".join(DEFAULT_PROXIES),
        help="Comma-separated proxy kinds. Default MED20,L10,L5,ALL. The agent path uses MED20 and L10.",
    )
    parser.add_argument(
        "--leagues",
        default="nba,wnba",
        help="Comma-separated leagues. Default nba,wnba.",
    )
    parser.add_argument(
        "--no-agent", action="store_true", help="Skip the agent scorecard replay."
    )
    parser.add_argument(
        "--validate",
        type=int,
        default=150,
        help="Daily rows per league to check against get_player_stats. Default 150. Zero skips the check.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=7,
        help="Seed for the rate check and the player sample.",
    )
    parser.add_argument(
        "--odds-history",
        default=None,
        help="CSV or JSONL of opening and closing lines with two-sided American prices. "
        "Omit it and the CLV hook stays inactive.",
    )
    parser.add_argument(
        "--players",
        type=int,
        default=None,
        help="Replay only this many players per league (deterministic sample). Default is every player.",
    )
    parser.add_argument(
        "--check-oracle",
        action="store_true",
        help=f"Exit 1 when headline counts differ from the {ORACLE_SOURCE}.",
    )
    parser.add_argument(
        "--fail-on-guard",
        action="store_true",
        help="Exit 1 when the full-run MED20 Brier score or calibration gap exceeds the guard thresholds.",
    )
    parser.add_argument(
        "--guard-only",
        action="store_true",
        help="Replay the CI player sample and exit. Does not write the report.",
    )
    parser.add_argument(
        "--save-rows",
        default=None,
        help="Directory for row-level CSV output. Off by default. The directory is gitignored.",
    )
    return parser.parse_args(argv)


def _print_assumptions(odds_active: bool) -> None:
    print("Assumptions")
    for line in assumption_lines():
        print(line)
    if odds_active:
        print(
            "An odds file was loaded. Matched props use the opening line and the opening price."
        )
        print("CLV is computed for those picks. Unmatched props stay on (b) and (c).")
    else:
        print(
            "No odds file was loaded. The CLV hook is inactive and was skipped. (b) and (c) apply to every pick."
        )
    print()


def _headline(league: str, rows: list, proxy: str) -> str:
    subset = [row for row in rows if row.league == league and row.proxy == proxy]
    if not subset:
        return f"{league} {proxy}: no rows"
    summary = summarize(subset)
    return (
        f"{league} {proxy}: props {summary.props:,}  picks {summary.picks:,}  "
        f"hit {100 * summary.hit_rate:.1f}% ({100 * summary.hit_lo:.1f}–{100 * summary.hit_hi:.1f})  "
        f"ROI {100 * summary.roi:+.1f}%  Brier {summary.brier:.3f}  "
        f"naive {100 * summary.naive:.1f}%  lift {100 * summary.lift:+.1f} pp"
    )


_DAILY_FIELDS = (
    "league",
    "proxy",
    "date",
    "market",
    "line",
    "actual",
    "n_games",
    "l10_min",
    "p_over",
    "p_under",
    "over_hit",
    "pick",
    "prob",
    "hit",
    "line_source",
    "price",
    "clv_prob",
    "clv_line",
)
_AGENT_FIELDS = (
    "league",
    "proxy",
    "date",
    "market",
    "line",
    "actual",
    "l10_min",
    "p_over",
    "over_hit",
    "confidence",
    "prod_decision",
    "eligible",
    "pass_reason",
    "pick",
    "prob",
    "hit",
    "b2b",
    "line_source",
    "price",
    "clv_prob",
    "clv_line",
)


def _write_rows(directory: str, daily: list, agent: list) -> None:
    """Write opt-in row dumps. Callers should point this at a gitignored directory."""
    os.makedirs(directory, exist_ok=True)
    _write_csv(os.path.join(directory, "daily_rows.csv"), daily, _DAILY_FIELDS)
    _write_csv(os.path.join(directory, "agent_rows.csv"), agent, _AGENT_FIELDS)
    print(f"Wrote row-level CSV to {directory}")


def _write_csv(path: str, rows: list, fields: tuple[str, ...]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for row in rows:
            writer.writerow([getattr(row, name) for name in fields])


def main(argv: list[str] | None = None) -> int:
    """Run the backtest. Returns a process exit code."""
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    bootstrap()
    if args.guard_only:
        _print_assumptions(False)
        guard = run_sample_guard(players=args.players, seed=args.seed)
        print(guard.message)
        return 0 if guard.ok else 1

    odds = load_odds_history(args.odds_history)
    _print_assumptions(odds.active)
    if odds.active:
        print(f"Odds hook active: {len(odds.quotes):,} quotes from {odds.source}")
    proxies = [part.strip() for part in args.proxies.split(",") if part.strip()]
    leagues = [part.strip().lower() for part in args.leagues.split(",") if part.strip()]
    historical = load_historical()
    started = time.time()
    replays = {}
    inventories = {}
    for league in leagues:
        service = historical._csv_for(league)
        inventories[league] = inventory(service)
        chosen = select_players(list(service._cache), args.players, args.seed)
        logging.info(
            "Replaying %s (%s players)",
            league,
            "all" if chosen is None else len(chosen),
        )
        replays[league] = replay_league(
            service,
            league,
            proxies,
            players=chosen,
            odds=odds,
            do_agent=not args.no_agent,
            validate=args.validate,
            seed=args.seed,
        )
        checked = replays[league].validation
        print(
            f"{league}: targets {replays[league].targets:,} "
            f"{replays[league].target_start} → {replays[league].target_end}  "
            f"daily rows {len(replays[league].daily):,}  agent rows {len(replays[league].agent):,}  "
            f"get_player_stats checked {checked['checked']} mismatches {checked['mismatches']}"
        )
    elapsed = time.time() - started
    daily = [row for replay in replays.values() for row in replay.daily]
    agent = [row for replay in replays.values() for row in replay.agent]

    print()
    print("Headlines")
    for league in leagues:
        info = inventories[league]
        replay = replays[league]
        print(
            f"{league} file {info['date_start']} → {info['date_end']} "
            f"({info['rows']:,} rows, {info['players']} players); "
            f"targets {replay.target_start} → {replay.target_end} ({replay.targets:,} player-games)"
        )
        for proxy in ("MED20", "L10"):
            if proxy in proxies:
                print(_headline(league, daily, proxy))
        if agent:
            print(
                _headline(league, agent, "MED20").replace(
                    f"{league} MED20", f"{league} agent MED20", 1
                )
            )
    print()

    mismatches = []
    for league, replay in replays.items():
        if replay.validation["mismatches"]:
            mismatches.append(
                f"{league} get_player_stats mismatches {replay.validation['mismatches']}"
            )
    oracle_mismatches = compare_oracle(replays, daily, agent)
    if args.players is not None:
        oracle_note = (
            "Oracle check skipped: this run replayed a player sample, not the full CSV."
        )
        oracle_mismatches = []
    elif oracle_mismatches:
        oracle_note = (
            "Differences from the "
            + ORACLE_SOURCE
            + ":\n\n"
            + "\n".join(f"- {item}" for item in oracle_mismatches)
        )
        print("Oracle mismatches:")
        for item in oracle_mismatches:
            print(f"  {item}")
    else:
        oracle_note = (
            "Daily headlines match the walk-forward prototype on origin/dev @ 5407401. "
            "Agent MED20 picks are 60,781 NBA and 8,579 WNBA (prototype 60,829 and 8,590). "
            "The side is now the unrounded probability, so a value that only crosses "
            "0.55 or 0.45 after rounding to 4 decimals is an abstention. "
            "WNBA average predicted probability rounds to 61.4% (prototype 61.3%). "
            "Push refunds and the duplicate-row filter did not move a headline: "
            "proxy lines are x.5, stats are integers, and the only duplicate date "
            "is the last WNBA game."
        )
        print(oracle_note)
    print()

    med_snapshots = []
    for league in leagues:
        rows = [row for row in replays[league].daily if row.proxy == "MED20"]
        if rows:
            med_snapshots.append((league, summarize(rows)))
    guard = evaluate_guard(med_snapshots)
    print(guard.message)
    print()

    if args.save_rows:
        _write_rows(args.save_rows, daily, agent)

    if args.report:
        report_path = (
            args.report
            if os.path.isabs(args.report)
            else os.path.join(os.getcwd(), args.report)
        )
        command = (
            "python scripts/agents/evaluation/backtest.py --report backtest_report.md"
        )
        text = render_report(
            replays,
            inventories,
            odds,
            command=command,
            oracle_note=oracle_note,
            guard_note=guard.message,
            elapsed_s=elapsed,
        )
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"Wrote {report_path}")

    exit_code = 0
    if mismatches:
        print("VALIDATION FAILED")
        for item in mismatches:
            print(item)
        exit_code = 1
    if args.check_oracle and oracle_mismatches and args.players is None:
        print("ORACLE CHECK FAILED")
        exit_code = 1
    if args.fail_on_guard and not guard.ok:
        print("CALIBRATION GUARD FAILED")
        exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
