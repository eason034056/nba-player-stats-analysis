"""Recorded headline counts for this CSV.

The numbers are the regular-season walk-forward on the post-SPO-97 files.
Headline targets and the history behind them are regular-season games, the
same set ``CSVPlayerHistoryService._allowed_game_types`` uses in production.
Playoffs and the play-in are not in these headlines.

Proxy lines are x.5. ROI assumes -110. The pre-gate agent side is the
unrounded model probability.

``compare_oracle`` is a same-data check. A CSV change or a different game-type
filter moves the counts, and the report says so.
"""

from __future__ import annotations

from typing import Mapping

# props, picks, hit%, ROI%, pick Brier, Wilson low, Wilson high, avg pred%, naive%, lift pp
# Regular-season targets only. Rounded the same way the report prints them.
_DAILY = {
    ("nba", "MED20"): (233596, 48258, 64.5, 23.2, 0.230, 64.1, 65.0, 73.5, 50.4, 14.2),
    ("wnba", "MED20"): (35178, 5433, 68.1, 29.9, 0.212, 66.8, 69.3, 74.7, 50.8, 17.2),
    ("nba", "L10"): (233596, 91663, 64.3, 22.8, 0.236, 64.0, 64.6, 74.3, 54.2, 10.2),
    ("wnba", "L10"): (35178, 12232, 63.9, 22.1, 0.233, 63.1, 64.8, 73.7, 54.8, 9.2),
    ("nba", "L5"): (233596, 118169, 67.7, 29.3, 0.223, 67.5, 68.0, None, None, None),
    ("wnba", "L5"): (35178, 16592, 67.5, 28.9, 0.221, 66.8, 68.3, None, None, None),
    ("nba", "ALL"): (233596, 42240, 65.0, 24.2, 0.227, 64.6, 65.5, None, None, None),
    ("wnba", "ALL"): (35178, 6637, 65.7, 25.4, 0.222, 64.5, 66.8, None, None, None),
}

# Daily MED20 pick counts by market. A mismatch here means one extractor drifted.
_MARKET_PICKS = {
    ("nba", "threes_made"): 8252,
    ("nba", "steals"): 7839,
    ("nba", "ftm"): 7433,
    ("nba", "assists"): 4742,
    ("nba", "fgm"): 3698,
    ("nba", "rebounds"): 3056,
    ("nba", "points"): 2780,
    ("nba", "pa"): 2659,
    ("nba", "ra"): 2656,
    ("nba", "pra"): 2572,
    ("nba", "pr"): 2571,
    ("wnba", "threes_made"): 1341,
    ("wnba", "steals"): 1236,
    ("wnba", "ftm"): 942,
    ("wnba", "assists"): 496,
    ("wnba", "fgm"): 318,
    ("wnba", "rebounds"): 303,
    ("wnba", "ra"): 268,
    ("wnba", "points"): 156,
    ("wnba", "pra"): 136,
    ("wnba", "pr"): 121,
    ("wnba", "pa"): 116,
}

# props, picks, hit%, Wilson low, Wilson high, avg pred%, lift pp, Brier of model p_over
_AGENT = {
    ("nba", "MED20"): (84944, 50832, 57.4, 57.0, 57.9, 62.1, 7.6, 0.2477),
    ("wnba", "MED20"): (12792, 6623, 57.0, 55.8, 58.2, 61.2, 7.1, 0.2472),
    ("nba", "L10"): (84944, 61715, 58.1, 57.7, 58.5, 64.5, 6.0, 0.2477),
    ("wnba", "L10"): (12792, 8950, 56.3, 55.3, 57.3, 63.8, 3.9, 0.2497),
}

_TARGETS = {
    "nba": (21236, "2025-11-09", "2026-04-12"),
    "wnba": (3198, "2025-06-11", "2026-05-08"),
}

_COMPOSITION = {
    "nba": (70.8, 47.1),
    "wnba": (73.1, 65.5),
}

ORACLE_SOURCE = "recorded headlines for this CSV"


def _near(got: float, expected: float, digits: int) -> bool:
    return round(got, digits) == expected


def compare_oracle(
    replays: Mapping[str, object], daily_rows: list, agent_rows: list
) -> list[str]:
    """Return human-readable mismatches. An empty list means the oracle matched.

    Percent fields are compared after rounding to the same decimal the
    prototype table printed. Counts are exact.
    """
    from evaluation.metrics import composition, grouped

    mismatches: list[str] = []
    for league, (targets, start, end) in _TARGETS.items():
        replay = replays[league]
        if (
            replay.targets != targets
            or replay.target_start != start
            or replay.target_end != end
        ):  # type: ignore[attr-defined]
            mismatches.append(
                f"{league} targets got {replay.targets} {replay.target_start}..{replay.target_end}, "  # type: ignore[attr-defined]
                f"oracle {targets} {start}..{end}"
            )

    by_proxy = grouped(daily_rows, lambda row: (row.league, row.proxy))
    found = {key: summary for key, summary in by_proxy}
    for key, expected in _DAILY.items():
        summary = found.get(key)
        if summary is None:
            mismatches.append(f"daily {key} missing")
            continue
        props, picks, hit, roi, brier, lo, hi, pred, naive, lift = expected
        checks = [
            (summary.props == props, f"props {summary.props} != {props}"),
            (summary.picks == picks, f"picks {summary.picks} != {picks}"),
            (
                _near(100 * summary.hit_rate, hit, 1),
                f"hit {100 * summary.hit_rate:.4f} != {hit}",
            ),
            (_near(100 * summary.roi, roi, 1), f"roi {100 * summary.roi:.4f} != {roi}"),
            (_near(summary.brier, brier, 3), f"brier {summary.brier:.6f} != {brier}"),
            (
                _near(100 * summary.hit_lo, lo, 1),
                f"ci_lo {100 * summary.hit_lo:.4f} != {lo}",
            ),
            (
                _near(100 * summary.hit_hi, hi, 1),
                f"ci_hi {100 * summary.hit_hi:.4f} != {hi}",
            ),
        ]
        if pred is not None:
            checks.append(
                (
                    _near(100 * summary.avg_pred, pred, 1),
                    f"pred {100 * summary.avg_pred:.4f} != {pred}",
                )
            )
            checks.append(
                (
                    _near(100 * summary.naive, naive, 1),
                    f"naive {100 * summary.naive:.4f} != {naive}",
                )
            )
            checks.append(
                (
                    _near(100 * summary.lift, lift, 1),
                    f"lift {100 * summary.lift:.4f} != {lift}",
                )
            )
        for ok, detail in checks:
            if not ok:
                mismatches.append(f"daily {key}: {detail}")

    med20 = [row for row in daily_rows if row.proxy == "MED20"]
    market_picks = grouped(med20, lambda row: (row.league, row.market))
    pick_map = {key: summary.picks for key, summary in market_picks}
    for key, picks in _MARKET_PICKS.items():
        if pick_map.get(key) != picks:
            mismatches.append(f"market picks {key}: {pick_map.get(key)} != {picks}")

    for league, (under_share, half_share) in _COMPOSITION.items():
        comp = composition([row for row in med20 if row.league == league])
        if not _near(100 * comp.under_share, under_share, 1):
            mismatches.append(
                f"{league} under share {100 * comp.under_share:.4f} != {under_share}"
            )
        if not _near(100 * comp.line_half_share, half_share, 1):
            mismatches.append(
                f"{league} 0.5-line share {100 * comp.line_half_share:.4f} != {half_share}"
            )

    if agent_rows:
        by_league = grouped(agent_rows, lambda row: (row.league, row.proxy))
        agent_found = {key: summary for key, summary in by_league}
        avoid = sum(1 for row in agent_rows if row.prod_decision == "avoid")
        if avoid != len(agent_rows):
            mismatches.append(f"agent production avoid {avoid} of {len(agent_rows)}")
        for key, expected in _AGENT.items():
            summary = agent_found.get(key)
            if summary is None:
                mismatches.append(f"agent {key} missing")
                continue
            props, picks, hit, lo, hi, pred, lift, p_brier = expected
            checks = [
                (summary.props == props, f"props {summary.props} != {props}"),
                (summary.picks == picks, f"picks {summary.picks} != {picks}"),
                (
                    _near(100 * summary.hit_rate, hit, 1),
                    f"hit {100 * summary.hit_rate:.4f} != {hit}",
                ),
                (
                    _near(100 * summary.hit_lo, lo, 1),
                    f"ci_lo {100 * summary.hit_lo:.4f} != {lo}",
                ),
                (
                    _near(100 * summary.hit_hi, hi, 1),
                    f"ci_hi {100 * summary.hit_hi:.4f} != {hi}",
                ),
                (
                    _near(100 * summary.avg_pred, pred, 1),
                    f"pred {100 * summary.avg_pred:.4f} != {pred}",
                ),
                (
                    _near(100 * summary.lift, lift, 1),
                    f"lift {100 * summary.lift:.4f} != {lift}",
                ),
                (
                    _near(summary.p_over_brier, p_brier, 4),
                    f"p_over brier {summary.p_over_brier:.6f} != {p_brier}",
                ),
            ]
            for ok, detail in checks:
                if not ok:
                    mismatches.append(f"agent {key}: {detail}")
    return mismatches
