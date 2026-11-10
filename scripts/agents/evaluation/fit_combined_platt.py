"""Refit the Platt pair on the NBA MED20 walk-forward replay.

The market term is the fair 0.5 prior on every row (logit 0), because this
repo has no historical sportsbook lines. Only the intercept and slope on
the clipped adjustment total are fit. The market coefficient stays 1.

The stored pair is fit on rows dated on or before ``--cutoff`` (default
2026-03-17). Later rows are the holdout. They are scored and not used to
choose the coefficients, so that holdout is out of sample for the values
written into the constants file.

Run from ``scripts/agents``::

    python -m evaluation.fit_combined_platt
    python -m evaluation.fit_combined_platt --cutoff 2026-03-17

The command rewrites ``PLATT_A``, ``PLATT_B``, and ``FIT_SAMPLE`` in
``backend/app/services/pick_signal_constants.py``. It does not call an
external API.
"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

import numpy as np

from evaluation.metrics import (
    COMBINED_EDGES,
    PICK_EDGES,
    binary_log_loss,
    expected_calibration_error,
    reliability,
)
from evaluation.paths import PROJECT_ROOT, bootstrap

# Rows on or before this date choose the stored coefficients.
# The next date through the end of the replay is the holdout.
DEFAULT_CUTOFF = "2026-03-17"
# Informational slice only. Not a second fit. Rebaseline waits on PR #38.
REGULAR_SEASON_HOLDOUT_END = "2026-04-12"


def fit_platt(adjustments: np.ndarray, outcomes: np.ndarray) -> tuple[float, float]:
    """Intercept and slope for ``P(hit) = sigmoid(a + b * adjustment)``.

    Newton steps on the Bernoulli log loss. ``b`` is free, including a
    negative slope, so a bad feature can be shrunk or flipped.
    """
    intercept = 0.0
    slope = 1.0
    for _ in range(50):
        linear = intercept + slope * adjustments
        linear = np.clip(linear, -30.0, 30.0)
        probability = 1.0 / (1.0 + np.exp(-linear))
        weight = np.maximum(probability * (1.0 - probability), 1e-6)
        residual = probability - outcomes
        grad_intercept = float(np.sum(residual))
        grad_slope = float(np.sum(residual * adjustments))
        hess_ii = float(np.sum(weight))
        hess_is = float(np.sum(weight * adjustments))
        hess_ss = float(np.sum(weight * adjustments * adjustments))
        determinant = hess_ii * hess_ss - hess_is * hess_is
        if determinant <= 1e-12:
            break
        step_intercept = (hess_ss * grad_intercept - hess_is * grad_slope) / determinant
        step_slope = (hess_ii * grad_slope - hess_is * grad_intercept) / determinant
        intercept -= step_intercept
        slope -= step_slope
        if abs(step_intercept) < 1e-10 and abs(step_slope) < 1e-10:
            break
    return intercept, slope


def _score(adjustments: np.ndarray, outcomes: np.ndarray, intercept: float, slope: float) -> np.ndarray:
    """Probabilities under a fair 0.5 market plus this Platt map."""
    from app.services.pick_signals import _logit, _sigmoid

    linear = _logit(0.5) + intercept + slope * adjustments
    probabilities = np.array([_sigmoid(float(value)) for value in linear])
    # Clip, then round, matching combined_probability.
    clipped = np.clip(probabilities, 1e-4, 1.0 - 1e-4)
    return np.round(clipped, 4)


def _report(label: str, probabilities: np.ndarray, outcomes: np.ndarray, baseline: np.ndarray) -> dict:
    """Brier, gap, log loss, ECE, and the widest reliability-bucket gap.

    Combined uses decile edges. The published ``probability`` uses the
    pick edges, which start at 0.65, because every published pick is at
    least that high.
    """
    n = len(outcomes)
    combined_sq = (probabilities - outcomes) ** 2
    baseline_sq = (baseline - outcomes) ** 2
    brier = float(np.mean(combined_sq))
    # Signed: positive means the mean prediction sits above the hit rate.
    gap = float(np.mean(probabilities) - np.mean(outcomes))
    log_loss = binary_log_loss(probabilities.tolist(), outcomes.tolist())
    ece = expected_calibration_error(probabilities.tolist(), outcomes.tolist(), COMBINED_EDGES)
    base_brier = float(np.mean(baseline_sq))
    base_gap = float(np.mean(baseline) - np.mean(outcomes))
    combined_se = float(np.std(combined_sq, ddof=1) / math.sqrt(n))
    baseline_se = float(np.std(baseline_sq, ddof=1) / math.sqrt(n))
    combined_ci = (brier - 1.96 * combined_se, brier + 1.96 * combined_se)
    baseline_ci = (base_brier - 1.96 * baseline_se, base_brier + 1.96 * baseline_se)
    paired = combined_sq - baseline_sq
    paired_mean = float(np.mean(paired))
    paired_se = float(np.std(paired, ddof=1) / math.sqrt(n))
    paired_ci = (paired_mean - 1.96 * paired_se, paired_mean + 1.96 * paired_se)
    base_log_loss = binary_log_loss(baseline.tolist(), outcomes.tolist())
    base_ece = expected_calibration_error(baseline.tolist(), outcomes.tolist(), PICK_EDGES)

    class _Row:
        def __init__(self, probability: float, published: float, hit: float):
            self.combined_probability = probability
            self.prob = published
            self.hit = hit

    rows = [
        _Row(float(probability), float(published), float(hit))
        for probability, published, hit in zip(probabilities, baseline, outcomes)
    ]
    bins = reliability(rows, lambda row: row.combined_probability, lambda row: row.hit, COMBINED_EDGES)
    published_bins = reliability(rows, lambda row: row.prob, lambda row: row.hit, COMBINED_EDGES)
    widest = max((abs(item.gap) for item in bins), default=float("nan"))
    published_widest = max((abs(item.gap) for item in published_bins), default=float("nan"))
    print(
        f"{label}: n={n} combined Brier {brier:.4f} "
        f"({combined_ci[0]:.4f}–{combined_ci[1]:.4f}) (signed gap {gap:+.4f}, "
        f"log loss {log_loss:.4f}, ECE {ece:.4f}, widest bucket {widest:.4f}, "
        f"mean {float(np.mean(probabilities)):.4f} vs hit {float(np.mean(outcomes)):.4f}) "
        f"vs probability Brier {base_brier:.4f} "
        f"({baseline_ci[0]:.4f}–{baseline_ci[1]:.4f}) (signed gap {base_gap:+.4f}, "
        f"log loss {base_log_loss:.4f}, ECE {base_ece:.4f}, "
        f"widest bucket {published_widest:.4f}, "
        f"mean {float(np.mean(baseline)):.4f}) "
        f"paired Brier difference {paired_mean:+.4f} "
        f"({paired_ci[0]:+.4f} to {paired_ci[1]:+.4f})"
    )
    return {
        "n": n,
        "brier": brier,
        "brier_lo": combined_ci[0],
        "brier_hi": combined_ci[1],
        "gap": gap,
        "log_loss": log_loss,
        "ece": ece,
        "widest_bucket": widest,
        "baseline_brier": base_brier,
        "baseline_gap": base_gap,
        "baseline_log_loss": base_log_loss,
        "baseline_ece": base_ece,
        "baseline_widest_bucket": published_widest,
        "paired_brier": paired_mean,
        "paired_lo": paired_ci[0],
        "paired_hi": paired_ci[1],
        "date_start": None,
        "date_end": None,
    }


def _write_constants(intercept: float, slope: float, sample: dict) -> None:
    path = Path(PROJECT_ROOT) / "backend" / "app" / "services" / "pick_signal_constants.py"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^PLATT_A = .*$", f"PLATT_A = {intercept:.8f}", text, count=1, flags=re.M)
    text = re.sub(r"^PLATT_B = .*$", f"PLATT_B = {slope:.8f}", text, count=1, flags=re.M)
    replacement = (
        "FIT_SAMPLE = {\n"
        '    "league": "nba",\n'
        '    "proxy": "MED20",\n'
        "    \"market_prior\": OFFLINE_MARKET_PRIOR,\n"
        f"    \"cutoff\": \"{sample['cutoff']}\",\n"
        f"    \"n\": {sample['n']},\n"
        f"    \"date_start\": \"{sample['date_start']}\",\n"
        f"    \"date_end\": \"{sample['date_end']}\",\n"
        '    "note": "Platt fit on rows dated on or before cutoff. '
        "Later rows are the holdout and were not used to choose A or B. "
        "Market log-odds coefficient is fixed at 1. "
        f"Holdout n={sample['holdout_n']}, "
        f"Brier {sample['holdout_brier']:.4f}, "
        f"signed gap {sample['holdout_gap']:+.4f}.\",\n"
        "}\n"
    )
    text, count = re.subn(r"FIT_SAMPLE = \{.*?\n\}\n", replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("FIT_SAMPLE block was not found in the constants file")
    path.write_text(text, encoding="utf-8")
    print(f"Wrote PLATT_A={intercept:.8f} PLATT_B={slope:.8f} to {path}")


def _arrays(rows: list) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    adjustments = np.array([float(row.combined_adjustment) for row in rows])
    outcomes = np.array([float(row.hit) for row in rows])
    baseline = np.array([float(row.prob) for row in rows])
    return adjustments, outcomes, baseline


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cutoff",
        default=DEFAULT_CUTOFF,
        help=(
            "Fit on rows dated on or before this YYYY-MM-DD. "
            f"Default {DEFAULT_CUTOFF}. Later rows are scored as the holdout "
            "and are not used to choose the stored coefficients."
        ),
    )
    args = parser.parse_args(argv)
    cutoff = args.cutoff
    bootstrap()
    from evaluation.walk_forward import load_historical, replay_league

    historical = load_historical()
    service = historical._csv_for("nba")
    replay = replay_league(
        service,
        "nba",
        ["MED20"],
        players=None,
        do_agent=False,
        validate=0,
    )
    rows = [
        row
        for row in replay.daily
        if row.proxy == "MED20"
        and row.pick is not None
        and row.hit is not None
        and row.combined_adjustment is not None
    ]
    rows.sort(key=lambda row: row.date)
    train = [row for row in rows if row.date <= cutoff]
    hold = [row for row in rows if row.date > cutoff]
    if len(train) < 30 or len(hold) < 30:
        raise RuntimeError(
            f"refusing to fit: {len(train)} rows on or before {cutoff}, "
            f"{len(hold)} after it (need 30 on each side)"
        )
    train_x, train_y, train_base = _arrays(train)
    intercept, slope = fit_platt(train_x, train_y)
    print(
        f"stored fit on dates <= {cutoff} "
        f"({train[0].date} → {train[-1].date}, n={len(train)}): "
        f"PLATT_A={intercept:.8f} PLATT_B={slope:.8f}"
    )
    print(
        "Training-row score uses the same rows that chose A and B. "
        "It is not comparable to the holdout."
    )
    _report("train rows", _score(train_x, train_y, intercept, slope), train_y, train_base)

    hold_x, hold_y, hold_base = _arrays(hold)
    print(
        f"holdout dates {hold[0].date} → {hold[-1].date} "
        "scored with the stored coefficients"
    )
    holdout = _report("holdout", _score(hold_x, hold_y, intercept, slope), hold_y, hold_base)

    regular = [row for row in hold if row.date <= REGULAR_SEASON_HOLDOUT_END]
    if len(regular) >= 30:
        reg_x, reg_y, reg_base = _arrays(regular)
        print(
            f"regular-season slice {regular[0].date} → {regular[-1].date} "
            "uses the same coefficients. It is not a refit."
        )
        _report(
            "regular-season holdout",
            _score(reg_x, reg_y, intercept, slope),
            reg_y,
            reg_base,
        )

    _write_constants(
        intercept,
        slope,
        {
            "cutoff": cutoff,
            "n": len(train),
            "date_start": train[0].date,
            "date_end": train[-1].date,
            "holdout_n": holdout["n"],
            "holdout_brier": holdout["brier"],
            "holdout_gap": holdout["gap"],
        },
    )


if __name__ == "__main__":
    main()
