"""Recorded headline counts for this CSV.

Daily MED20, L10, L5, and ALL counts are the walk-forward prototype on
origin/dev @ 5407401. They did not move when pushes became refunds or when
an identical same-day row stopped being counted twice. Proxy lines are
x.5, the box score is an integer, and the only duplicate date is the last
WNBA game.

Agent MED20 pick counts are lower than that prototype. The pre-gate side
is the unrounded model probability. A value in [0.54995, 0.55) used to
round to 0.5500 and become an over; it is now avoid. The same thing
happens just above 0.45, where rounding used to create an under. NBA
picks went from 60,829 to 60,781. WNBA picks went from 8,590 to 8,579,
and the WNBA average predicted probability rounds to 61.4% instead of 61.3%.

``compare_oracle`` is a same-data check. SPO-97 and SPO-98 change the CSV;
the report says which tables move when they do.
"""

from __future__ import annotations

from typing import Mapping

# props, picks, hit%, ROI%, pick Brier, Wilson low, Wilson high, avg pred%, naive%, lift pp
_DAILY = {
    ("nba", "MED20"): (277398, 55708, 64.9, 24.0, 0.227, 64.5, 65.3, 72.7, 50.8, 14.2),
    ("wnba", "MED20"): (43560, 7199, 68.4, 30.6, 0.210, 67.3, 69.5, 74.3, 50.9, 17.5),
    ("nba", "L10"): (277398, 101614, 64.9, 23.9, 0.232, 64.6, 65.2, 73.6, 54.5, 10.4),
    ("wnba", "L10"): (43560, 15413, 64.5, 23.2, 0.231, 63.8, 65.3, 73.7, 55.0, 9.6),
    ("nba", "L5"): (277398, 135012, 67.4, 28.8, 0.223, 67.2, 67.7, None, None, None),
    ("wnba", "L5"): (43560, 20575, 68.1, 30.0, 0.219, 67.4, 68.7, None, None, None),
    ("nba", "ALL"): (277398, 48160, 68.9, 31.6, 0.209, 68.5, 69.3, None, None, None),
    ("wnba", "ALL"): (43560, 8174, 67.1, 28.1, 0.216, 66.1, 68.1, None, None, None),
}

# Daily MED20 pick counts by market. A mismatch here means one extractor drifted.
_MARKET_PICKS = {
    ("nba", "threes_made"): 9407,
    ("nba", "ftm"): 7872,
    ("nba", "steals"): 8333,
    ("nba", "assists"): 5305,
    ("nba", "fgm"): 4303,
    ("nba", "rebounds"): 3916,
    ("nba", "ra"): 3561,
    ("nba", "points"): 3241,
    ("nba", "pr"): 3179,
    ("nba", "pa"): 3349,
    ("nba", "pra"): 3242,
    ("wnba", "threes_made"): 1698,
    ("wnba", "pra"): 258,
    ("wnba", "points"): 234,
}

# props, picks, hit%, Wilson low, Wilson high, avg pred%, lift pp, Brier of model p_over
_AGENT = {
    ("nba", "MED20"): (100872, 60781, 57.9, 57.5, 58.3, 62.0, 7.9, 0.2467),
    ("wnba", "MED20"): (15840, 8579, 57.6, 56.5, 58.6, 61.4, 7.7, 0.2463),
}

_TARGETS = {
    "nba": (25218, "2025-10-21", "2026-05-11"),
    "wnba": (3960, "2025-06-05", "2026-05-08"),
}

_COMPOSITION = {
    "nba": (65.5, 44.0),
    "wnba": (73.6, 60.5),
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
        agent_med = [row for row in agent_rows if row.proxy == "MED20"]
        by_league = grouped(agent_med, lambda row: (row.league, row.proxy))
        agent_found = {key: summary for key, summary in by_league}
        avoid = sum(1 for row in agent_med if row.prod_decision == "avoid")
        if avoid != len(agent_med):
            mismatches.append(f"agent production avoid {avoid} of {len(agent_med)}")
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
