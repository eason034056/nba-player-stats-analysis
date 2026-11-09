"""Fail when a league's Brier score or calibration gap gets too large.

The check is the regression gate for the walk-forward replay. It watches
the Daily Picks rule on the default MED20 proxy:

* Brier score of the selected picks, ``mean((probability - hit)^2)``.
* Calibration gap, ``|mean(probability) - hit rate|`` on those picks.

Both are per league. A league with fewer than 30 picks falls back to the
Brier score of ``p_over`` on every prop and the absolute gap between mean
``p_over`` and the realized over rate, and the result says so.

Thresholds default to 0.30 (Brier) and 0.15 (gap). The full-sample MED20
run sits near 0.23 and 0.08, so the defaults trip on a broken join or a
probability that no longer tracks the outcome, not on the overconfidence
already in the current model. Override them with
``BACKTEST_GUARD_MAX_BRIER`` and ``BACKTEST_GUARD_MAX_GAP``.

``run_sample_guard`` replays a deterministic player sample so CI can run
the check without the full history. The sample size is
``BACKTEST_GUARD_PLAYERS`` (default 40) drawn with seed 7.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from evaluation.metrics import Summary


@dataclass
class Thresholds:
    """Upper bounds. A league fails when its statistic is strictly greater."""

    max_brier: float = 0.30
    max_calibration_gap: float = 0.15


@dataclass
class GuardResult:
    """Outcome of one guard evaluation."""

    ok: bool
    lines: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        return "\n".join(self.lines)


def thresholds_from_env() -> Thresholds:
    """Read the two bounds from the environment, falling back to the defaults."""
    return Thresholds(
        max_brier=float(os.environ.get("BACKTEST_GUARD_MAX_BRIER", "0.30")),
        max_calibration_gap=float(os.environ.get("BACKTEST_GUARD_MAX_GAP", "0.15")),
    )


def evaluate_guard(
    snapshots: list[tuple[str, Summary]], thresholds: Thresholds | None = None
) -> GuardResult:
    """Apply ``thresholds`` to one ``Summary`` per league.

    Args:
        snapshots: ``(league, summary)`` pairs. The summary should be the
            MED20 daily replay for that league.
        thresholds: Bounds. Defaults to ``thresholds_from_env``.

    Returns:
        A result whose ``ok`` flag is false when any league exceeds a bound.
    """
    bounds = thresholds if thresholds is not None else thresholds_from_env()
    result = GuardResult(ok=True)
    result.lines.append(
        f"Calibration guard: max Brier {bounds.max_brier:.3f}, "
        f"max |pred - hit| {bounds.max_calibration_gap:.3f} (MED20 Daily Picks)."
    )
    if not snapshots:
        result.ok = False
        result.failures.append("no leagues to check")
        result.lines.append("FAIL no leagues to check")
        return result
    for league, summary in snapshots:
        if summary.picks >= 30:
            brier = summary.brier
            gap = summary.calibration_gap
            source = f"picks n={summary.picks}"
        elif summary.props > 0:
            brier = summary.p_over_brier
            gap = abs(summary.mean_p_over - summary.actual_over_rate)
            source = f"all props n={summary.props} (fewer than 30 picks)"
        else:
            result.ok = False
            detail = f"{league}: no props"
            result.failures.append(detail)
            result.lines.append(f"FAIL {detail}")
            continue
        brier_ok = brier <= bounds.max_brier
        gap_ok = gap <= bounds.max_calibration_gap
        status = "ok" if brier_ok and gap_ok else "FAIL"
        result.lines.append(
            f"{status} {league}: Brier {brier:.3f}, calibration gap {gap:.3f} ({source})"
        )
        if not brier_ok:
            result.ok = False
            result.failures.append(
                f"{league} Brier {brier:.3f} > {bounds.max_brier:.3f}"
            )
        if not gap_ok:
            result.ok = False
            result.failures.append(
                f"{league} calibration gap {gap:.3f} > {bounds.max_calibration_gap:.3f}"
            )
    return result


def run_sample_guard(
    players: int | None = None,
    seed: int = 7,
    thresholds: Thresholds | None = None,
) -> GuardResult:
    """Replay a player sample and evaluate the guard.

    Args:
        players: Players per league. ``None`` reads ``BACKTEST_GUARD_PLAYERS``,
            default 40. The draw is ``random.Random(seed).sample`` on the
            sorted player list, so the same CSV always yields the same sample.
        seed: Sample seed. Default 7, the same seed the rate check uses.
        thresholds: Bounds. Defaults to the environment.

    Returns:
        The guard result for the sample. ``ok`` is false when a league
        exceeds a bound.
    """
    from evaluation.metrics import summarize
    from evaluation.walk_forward import load_historical, replay_league, select_players

    if players is None:
        players = int(os.environ.get("BACKTEST_GUARD_PLAYERS", "40"))
    historical = load_historical()
    snapshots: list[tuple[str, Summary]] = []
    for league in ("nba", "wnba"):
        service = historical._csv_for(league)
        chosen = select_players(list(service._cache), players, seed)
        replay = replay_league(
            service,
            league,
            ["MED20"],
            players=chosen,
            do_agent=False,
            validate=0,
        )
        rows = [row for row in replay.daily if row.proxy == "MED20"]
        snapshots.append((league, summarize(rows)))
    result = evaluate_guard(snapshots, thresholds)
    result.lines.insert(
        1,
        f"Sample: {players} players per league, seed {seed}, proxy MED20, agent path off.",
    )
    return result
