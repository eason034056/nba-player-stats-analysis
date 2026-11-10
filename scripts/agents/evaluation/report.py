"""Markdown report for one walk-forward run.

The numbers come from the rows the harness just scored. The narrative
around SPO-97 and SPO-98 is fixed: those tickets are not fixed here, and
the section says which of these tables can move when they land.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from typing import Sequence

from evaluation.assumptions import assumption_lines
from evaluation.metrics import (
    AGENT_P_OVER_EDGES,
    PICK_EDGES,
    P_OVER_EDGES,
    Summary,
    composition,
    confidence_bucket,
    grouped,
    is_postable,
    pearson,
    reliability,
    summarize,
    tier_name,
)
from evaluation.odds_history import OddsHistory
from evaluation.walk_forward import EVAL_START, LeagueReplay

_DASH = "–"


def _blank(value: float | None) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _pct(value: float | None, digits: int = 1, signed: bool = False) -> str:
    if _blank(value):
        return "—"
    number = 100.0 * float(value)
    if signed:
        return f"{number:+.{digits}f}"
    return f"{number:.{digits}f}"


def _num(value: float | None, digits: int = 3) -> str:
    if _blank(value):
        return "—"
    return f"{float(value):.{digits}f}"


def _ci(
    low: float, high: float, digits: int = 1, scale: float = 100.0, signed: bool = False
) -> str:
    if _blank(low) or _blank(high):
        return "—"
    left = scale * low
    right = scale * high
    if signed:
        return f"{left:+.{digits}f}{_DASH}{right:+.{digits}f}"
    return f"{left:.{digits}f}{_DASH}{right:.{digits}f}"


def _hit_cell(summary: Summary) -> str:
    return f"{_pct(summary.hit_rate)} ({_ci(summary.hit_lo, summary.hit_hi)})"


def _roi_cell(summary: Summary) -> str:
    return f"{_pct(summary.roi, signed=True)} ({_ci(summary.roi_lo, summary.roi_hi, signed=True)})"


def _brier_cell(summary: Summary) -> str:
    return f"{_num(summary.brier)} ({_ci(summary.brier_lo, summary.brier_hi, digits=3, scale=1.0)})"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    rule = "|" + "|".join("---" for _ in headers) + "|"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([head, rule, *body])


def _summary_row(label: str, summary: Summary) -> list[str]:
    return [
        label,
        str(summary.props),
        str(summary.picks),
        _hit_cell(summary),
        _roi_cell(summary),
        _brier_cell(summary),
        _pct(summary.avg_pred),
        _pct(summary.naive),
        _pct(summary.lift, signed=True),
    ]


_HEADERS = [
    "Group",
    "Props",
    "Picks",
    "Hit% (95% CI)",
    "ROI% (95% CI)",
    "Brier (95% CI)",
    "Avg pred%",
    "Naive%",
    "Lift pp",
]


def _summary_table(pairs: Sequence[tuple[object, Summary]], label_fn) -> str:
    rows = [_summary_row(label_fn(key), summary) for key, summary in pairs]
    if not rows:
        return "_No rows._"
    return _table(_HEADERS, rows)


def _reliability_table(bins) -> str:
    if not bins:
        return "_No rows in these buckets._"
    rows = []
    for item in bins:
        hi = "1" if item.hi > 1 else f"{item.hi:.2f}".rstrip("0").rstrip(".")
        lo = f"{item.lo:.2f}".rstrip("0").rstrip(".")
        rows.append(
            [
                f"[{lo}, {hi})",
                str(item.n),
                _num(item.avg_pred),
                _num(item.actual),
                _num(item.gap, 3),
            ]
        )
    return _table(["Bucket", "N", "Avg predicted", "Actual", "Gap (pred−actual)"], rows)


def _key_label(key: object) -> str:
    if isinstance(key, tuple):
        return " / ".join(str(part) for part in key)
    return str(key)


def render_report(
    replays: dict[str, LeagueReplay],
    inventories: dict[str, dict],
    odds: OddsHistory,
    *,
    command: str,
    oracle_note: str,
    guard_note: str,
    elapsed_s: float,
) -> str:
    """Build the markdown report for a finished run."""
    daily = [row for replay in replays.values() for row in replay.daily]
    agent = [row for replay in replays.values() for row in replay.agent]
    med = [row for row in daily if row.proxy == "MED20"]
    agent_med = [row for row in agent if row.proxy == "MED20"]
    lines: list[str] = []
    add = lines.append
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    add("# Sports Lab walk-forward backtest")
    add("")
    add(f"Generated {generated}. Command: `{command}`. Elapsed {elapsed_s:.0f}s.")
    add("")
    add(
        "The previous `scripts/agents/evaluation/backtest.py` scored five hard-coded players"
    )
    add('in-sample: the "actual rate" was the same history the model had just fit.')
    add("This report walks forward. Each player-game is scored with that player's")
    add("non-DNP games dated strictly before it, which is the information Daily Picks")
    add("and the scorecard would have had on the morning of the game if the CSV had")
    add("been frozen there.")
    add("")
    add("## Assumptions")
    add("")
    for line in assumption_lines():
        add(line)
        add("")
    add(_odds_status(odds, daily))
    add("")
    add("L5 (`floor` of the last 5 games, plus 0.5) and ALL (the same rule on every")
    add("prior game) are extra sensitivity proxies. They are not the default.")
    add("MED20 ties go to the lower x.5 line. Candidate lines are the positive")
    add("half-point numbers from `floor(min) - 0.5` through `floor(max) + 0.5`.")
    add("")
    add("## Data")
    add("")
    add(_inventory_table(inventories))
    add("")
    add(
        "Target windows (a game is scored only if it has at least 10 prior non-DNP games,"
    )
    add("the same floor as `MIN_SAMPLE_GAMES`):")
    add("")
    for league, replay in replays.items():
        configured = EVAL_START[league].strftime("%Y-%m-%d")
        add(
            f"- **{league.upper()}** configured start {configured}; "
            f"scored targets {replay.target_start} → {replay.target_end} "
            f"({replay.targets:,} player-games)."
        )
    add("")
    add("## Method")
    add("")
    add(
        "**Daily Picks.** For each supported market in `daily_analysis.SUPPORTED_MARKETS`,"
    )
    add(
        "the over rate is the share of prior games strictly above the line and the under"
    )
    add(
        "rate is the share strictly below it, rounded to 4 decimals. That is the return"
    )
    add("value of `CSVPlayerHistoryService.get_player_stats(n=0, exclude_dnp=True)`.")
    add("The side comes from `choose_daily_pick_side`: over when `p_over` clears")
    add("`HIGH_PROBABILITY_THRESHOLD` (0.65), otherwise under when `p_under` does.")
    add("The tier is the frontend `getProbabilityLevel`: high at or above 0.70,")
    add("otherwise medium. A sample of replay rates is checked against the real")
    add("`get_player_stats` on a cache that contains only the prior games.")
    add("")
    add("**Agent scorecard.** `tools.historical` and `scoring.compute_scorecard` run")
    add("on a cache that has been swapped to those same prior games, for points,")
    add("rebounds, assists, and pra. There is no stored market price, lineup, or")
    add("injury report, so the returned decision is avoid and `eligible_for_bet`")
    add("is false. The tables below the avoid rate use the pre-gate side:")
    add("`decision_from_over_probability` on the unrounded model probability")
    add("(over at or above 0.55, under at or below 0.45). The published probability")
    add("is rounded to 4 decimals and that rounding can cross the band, so the side")
    add("is decided before rounding. That is the market gate ignored, and nothing else.")
    add("A push (`actual == line`) refunds the stake: profit is 0, and the bet is left")
    add("out of the hit rate and the Brier score.")
    add("")
    add(
        "**Naive baseline.** `naive = (over picks × over-rate of every prop in the group"
    )
    add("+ under picks × under-rate of every prop) / picks`. Lift is the pick hit rate")
    add("minus that number, in percentage points. It is the hit rate of the same mix")
    add("of directions if the directions had been assigned without looking at which")
    add("props were extreme. On a direction-only split the group is already one side,")
    add("so the baseline equals the hit rate and the lift is zero.")
    add("")
    add("**Intervals.** The hit-rate interval is a Wilson 95% interval. When every")
    add("pick is priced at -110, the ROI interval is that Wilson interval passed")
    add("through `roi = hit_rate × 210/110 − 1`. When a pick carries a real American")
    add("price, the ROI interval is a normal approximation on the mean profit.")
    add("The Brier interval is a normal approximation on the mean squared error.")
    add("Picks that share a game are not independent, so every interval is too narrow.")
    add("")
    add("## Daily Picks, proxy MED20")
    add("")
    add(_summary_table(grouped(med, lambda row: row.league), _key_label))
    add("")
    add("### By market")
    add("")
    add(_summary_table(grouped(med, lambda row: (row.league, row.market)), _key_label))
    add("")
    add("### By confidence tier")
    add("")
    add("The tier is only defined for picks. Naive and lift inside a tier use that")
    add("tier's own props, which are the picks, so they are not the headline baseline.")
    add("")
    add(
        _summary_table(
            grouped(
                med,
                lambda row: (
                    (row.league, tier_name(row.prob)) if row.prob is not None else None
                ),
            ),
            _key_label,
        )
    )
    add("")
    add("### By direction")
    add("")
    add(
        _summary_table(
            grouped(med, lambda row: (row.league, row.pick) if row.pick else None),
            _key_label,
        )
    )
    add("")
    add("### By month")
    add("")
    add(
        _summary_table(grouped(med, lambda row: (row.league, row.date[:7])), _key_label)
    )
    add("")
    add("### Pick composition")
    add("")
    add(_composition_table(med))
    add("")
    add("### Calibration of the pick probability")
    add("")
    for league in replays:
        picked = [row for row in med if row.league == league and row.pick is not None]
        add(f"**{league.upper()}**")
        add("")
        add(
            _reliability_table(
                reliability(
                    picked, lambda row: row.prob, lambda row: row.hit, PICK_EDGES
                )
            )
        )
        add("")
    add("### Calibration of p_over on every prop")
    add("")
    add(_overall_brier_table(med))
    add("")
    for league in replays:
        rows = [row for row in med if row.league == league]
        add(f"**{league.upper()}**")
        add("")
        add(
            _reliability_table(
                reliability(
                    rows, lambda row: row.p_over, lambda row: row.over_hit, P_OVER_EDGES
                )
            )
        )
        add("")
    add("### Proxy sensitivity")
    add("")
    add("The level moves with the proxy. That is the reason the absolute hit rate")
    add("is not a market edge: MED20, L10, L5, and ALL are different questions.")
    add("")
    add(_summary_table(grouped(daily, lambda row: (row.league, row.proxy)), _key_label))
    add("")
    add("### Postable subset (MED20)")
    add("")
    add("Prior-10 average minutes at least 20, free throws and field goals made")
    add("removed, and threes or steals at 0.5 removed when `p_under` was already")
    add("at least 0.95. This is closer to a number a book would post, and it is")
    add("lower than the headline because the headline includes the 0.5 lines.")
    add("")
    postable = [row for row in med if is_postable(row)]
    add(_summary_table(grouped(postable, lambda row: row.league), _key_label))
    add("")
    add("## Agent scorecard, proxy MED20")
    add("")
    add(_agent_gate(agent_med))
    add("")
    add("### Pre-gate results (market gate ignored)")
    add("")
    add(_summary_table(grouped(agent_med, lambda row: row.league), _key_label))
    add("")
    add("### By market")
    add("")
    add(
        _summary_table(
            grouped(agent_med, lambda row: (row.league, row.market)), _key_label
        )
    )
    add("")
    add("### By scorecard confidence")
    add("")
    add(
        _summary_table(
            grouped(
                agent_med, lambda row: (row.league, confidence_bucket(row.confidence))
            ),
            _key_label,
        )
    )
    add("")
    add("### Back-to-back")
    add("")
    add(
        _summary_table(
            grouped(
                agent_med, lambda row: (row.league, "b2b" if row.b2b else "not b2b")
            ),
            _key_label,
        )
    )
    add("")
    add("### Calibration of model p_over")
    add("")
    add(_agent_brier_table(agent_med))
    add("")
    for league in replays:
        rows = [row for row in agent_med if row.league == league]
        add(f"**{league.upper()}**")
        add("")
        add(
            _reliability_table(
                reliability(
                    rows,
                    lambda row: row.p_over,
                    lambda row: float(row.over_hit),
                    AGENT_P_OVER_EDGES,
                )
            )
        )
        add("")
    if odds.active:
        add("## Odds-backed ROI and CLV")
        add("")
        add(_odds_section(daily, agent))
        add("")
    add("## What moves when SPO-97 and SPO-98 land")
    add("")
    add(_shift_section(inventories, replays))
    add("")
    add("## Check against the recorded headlines")
    add("")
    add(oracle_note)
    add("")
    add("## Calibration guard")
    add("")
    add(guard_note)
    add("")
    add("The CI job runs `pytest` on `scripts/agents/tests/test_calibration_guard.py`,")
    add("which replays a 40-player sample (seed 7) per league and fails if the")
    add("MED20 Brier score exceeds `BACKTEST_GUARD_MAX_BRIER` (default 0.30) or")
    add("the calibration gap exceeds `BACKTEST_GUARD_MAX_GAP` (default 0.15).")
    add("The full-run figures above are the same check on every player.")
    add("")
    add("## How to read the hit rate")
    add("")
    add("A proxy built from the last 20 games is a noisier number than a book")
    add("that has projections, injuries, and minutes. Beating MED20 mostly says")
    add("that a long unshrunk history is more extreme than a 20-game split.")
    add("It does not say the bet would have beaten a closing line. Closing-line")
    add("value stays unmeasured until the odds hook has a file to read.")
    add("")
    return "\n".join(lines)


def _odds_status(odds: OddsHistory, daily: list) -> str:
    if not odds.active:
        return (
            "This run loaded no odds file. The CLV hook is inactive and was skipped. "
            "(b) and (c) apply to every pick."
        )
    matched = sum(1 for row in daily if row.line_source == "open")
    return (
        f"This run loaded {len(odds.quotes):,} quotes from `{odds.source}` "
        f"({odds.skipped_rows} rows skipped, {odds.duplicate_keys} duplicate keys). "
        f"{matched:,} daily prop rows were graded on the opening line. "
        "ROI on those picks uses the opening American price of the side that was "
        "bet. CLV is the mean, over those picks only, of the closing vig-free "
        "probability of that side minus the opening vig-free probability. "
        "Props with no quote stay on the proxy line at assumed -110 and are "
        "left out of the CLV average. (b) and (c) describe the unmatched props."
    )


def _inventory_table(inventories: dict[str, dict]) -> str:
    rows = []
    for league, info in inventories.items():
        seasons = ", ".join(
            f"{name or 'blank'}={count}"
            for name, count in sorted(info["seasons"].items())
        )
        dup = (
            "; ".join(
                f"{item['player']} {item['date']} ×{item['copies']}"
                for item in info["duplicates"]
            )
            or "none"
        )
        rows.append(
            [
                league.upper(),
                f"{info['rows']:,}",
                str(info["players"]),
                f"{info['date_start']} → {info['date_end']}",
                seasons,
                dup,
                str(info["multi_team_players"]),
                f"{info['rows_before_nba_cutoff']:,}",
            ]
        )
    return _table(
        [
            "League",
            "Rows",
            "Players",
            "File dates",
            "Season labels",
            "Duplicate player-dates",
            "Multi-team players",
            "Rows before 2025-10-21",
        ],
        rows,
    )


def _composition_table(med: list) -> str:
    rows = []
    for league in ("nba", "wnba"):
        comp = composition([row for row in med if row.league == league])
        rows.append(
            [
                league.upper(),
                str(comp.picks),
                _pct(comp.under_share),
                _pct(comp.line_half_share),
                _pct(comp.hot_share),
            ]
        )
    return _table(
        ["League", "Picks", "Under share", "0.5-line share", "Prob ≥ 0.95 share"], rows
    )


def _overall_brier_table(med: list) -> str:
    rows = []
    for league in ("nba", "wnba"):
        summary = summarize([row for row in med if row.league == league])
        rows.append(
            [
                league.upper(),
                str(summary.props),
                _num(summary.p_over_brier, 4),
                "0.2500",
                _num(summary.base_rate_brier, 4),
                _pct(summary.actual_over_rate, 2),
                _pct(summary.mean_p_over, 2),
            ]
        )
    return _table(
        [
            "League",
            "Props",
            "Brier(p_over)",
            "Brier(constant 0.5)",
            "Brier(base rate)",
            "Actual over%",
            "Mean p_over%",
        ],
        rows,
    )


def _agent_gate(rows: list) -> str:
    if not rows:
        return "Agent path was not run."
    decisions = Counter(row.prod_decision for row in rows)
    reasons = Counter(row.pass_reason for row in rows)
    eligible = Counter(row.eligible for row in rows)
    pre_avoid = sum(1 for row in rows if row.pick is None)
    return (
        f"Production avoid rate: {decisions.get('avoid', 0):,} / {len(rows):,} "
        f"({decisions.get('avoid', 0) / len(rows):.1%}). "
        f"Decisions: {dict(decisions)}. Eligible: {dict(eligible)}. "
        f"Pass reasons: {dict(reasons)}. "
        f"With the market gate ignored, the probability band itself abstains on "
        f"{pre_avoid:,} / {len(rows):,} props (P(over) strictly between 0.45 and 0.55)."
    )


def _agent_brier_table(rows: list) -> str:
    if not rows:
        return "_Agent path was not run._"
    table_rows = []
    for league in ("nba", "wnba"):
        subset = [row for row in rows if row.league == league]
        if not subset:
            continue
        summary = summarize(subset)
        correlation = pearson(
            [row.confidence for row in subset],
            [abs(row.p_over - 0.5) for row in subset],
        )
        table_rows.append(
            [
                league.upper(),
                str(summary.props),
                _num(summary.p_over_brier, 4),
                "0.2500",
                _num(correlation, 4),
            ]
        )
    return _table(
        [
            "League",
            "Props",
            "Brier(model p_over)",
            "Brier(constant 0.5)",
            "Corr(confidence, |p−0.5|)",
        ],
        table_rows,
    )


def _odds_section(daily: list, agent: list) -> str:
    parts = ["Graded on the opening line, priced at the opening American odds."]
    for label, rows in (("Daily Picks", daily), ("Agent pre-gate", agent)):
        matched = [row for row in rows if row.line_source == "open"]
        if not matched:
            parts.append(f"{label}: no matched props.")
            continue
        summary = summarize(matched)
        clv = (
            "not computed"
            if summary.clv_n == 0
            else (
                f"probability CLV {_pct(summary.clv_prob, digits=2, signed=True)} pp, "
                f"line CLV {_num(summary.clv_line, 2)} points, n={summary.clv_n}"
            )
        )
        parts.append(
            f"{label}: {summary.picks} picks of {summary.props} props, "
            f"hit {_hit_cell(summary)}, ROI {_roi_cell(summary)}, {clv}."
        )
    return "\n\n".join(parts)


def _shift_section(
    inventories: dict[str, dict], replays: dict[str, LeagueReplay]
) -> str:
    nba = inventories.get("nba", {})
    wnba = inventories.get("wnba", {})
    nba_exposure = replays["nba"].exposure if "nba" in replays else {}
    wnba_exposure = replays["wnba"].exposure if "wnba" in replays else {}
    months = nba.get("before_cutoff_by_month", {})
    month_text = (
        ", ".join(f"{month}={count}" for month, count in months.items()) or "none"
    )
    dup_text = (
        ", ".join(
            f"{item['player']} {item['date']} ×{item['copies']}"
            for item in wnba.get("duplicates", [])
        )
        or "none"
    )
    nba_targets = nba_exposure.get("targets") or 0
    last20 = nba_exposure.get("last_20_includes_pre_cutoff") or 0
    any_prior = nba_exposure.get("any_prior_before_cutoff") or 0
    dup_in_prior = (nba_exposure.get("prior_includes_duplicate_date") or 0) + (
        wnba_exposure.get("prior_includes_duplicate_date") or 0
    )
    seasons = nba.get("seasons", {})
    return "\n".join(
        [
            "These four data bugs are left for SPO-97 and SPO-98. This run does not correct them.",
            "",
            f"**Season label.** The NBA cache has {nba.get('rows', 0):,} rows and season counts {seasons}. "
            f"{nba.get('rows_before_nba_cutoff', 0):,} of those rows are dated before 2025-10-21 "
            f"({month_text}). `get_player_stats(n=0)` does not read the Season column, and neither "
            "does this replay, so correcting the label by itself does not move a hit rate, an ROI, "
            "a Brier score, or a calibration bucket. What does move them is the natural companion "
            "of that fix: dropping Summer League, preseason, and the stray older rows out of the "
            "history the model consumes. "
            f"{any_prior:,} of {nba_targets:,} scored NBA player-games have at least one such row "
            f"in their prior window, and {last20:,} have one inside the last 20 games that MED20 "
            "and the rotation split look at. Those are the NBA tables that shift: the MED20 and "
            "L10 hit rates, ROI, Brier, calibration, monthly rates (October and November most of "
            "all, because the short window is still full of pre-cutoff games), and the proxy-"
            "sensitivity table. WNBA is a separate file and does not move because of the NBA label.",
            "",
            f"**Duplicate WNBA row.** Duplicate player-dates in the WNBA cache: {dup_text}. "
            "A second copy of the same date is not scored as its own target. When that copy "
            "is the same box score (these two rows differ only in Season), the replay keeps "
            "one copy, so a later game does not count it twice. A same-day row with a different "
            "box score, such as a doubleheader, stays in the later prior. "
            f"Scored player-games whose prior still contains a date that had a duplicate row: {dup_in_prior}. "
            "Deleting the extra row therefore does not move the WNBA headline hit rate, ROI, "
            "Brier, or calibration on this file. The replay has already stopped the double count.",
            "",
            "**Team taken from the oldest game.** Daily Picks falls back to `game_logs[0]` when "
            "there is no projection, and `get_player_stats` returns logs oldest-first, so a traded "
            f"player is labelled with their oldest team. {nba.get('multi_team_players', 0)} NBA "
            f"and {wnba.get('multi_team_players', 0)} WNBA players in this cache have more than "
            "one team. This replay never reads the team. Hit rate, ROI, Brier, calibration, "
            "monthly rates, under share, and the 0.5-line share do not move. The team badge on "
            "the picks page does.",
            "",
            "**Substring name match.** `get_player_stats` and `_games_for` accept a name when "
            "either string contains the other. This replay iterates the CSV's own player keys "
            "and looks them up exactly, so the fuzzy branch does not fire. None of the tables "
            "in this report move when matching gets stricter. A live request that passes a "
            "partial or overlapping name can change, because that request is the one that "
            "uses the fuzzy branch.",
        ]
    )
