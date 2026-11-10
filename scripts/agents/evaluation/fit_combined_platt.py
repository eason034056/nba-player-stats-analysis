"""Refit the Platt pair on the NBA MED20 walk-forward replay.

The market term is the fair 0.5 prior on every row (logit 0), because this
repo has no historical sportsbook lines. Only the intercept and slope on
the clipped adjustment total are fit. The market coefficient stays 1.

Run from ``scripts/agents``::

    python -m evaluation.fit_combined_platt

The command rewrites ``PLATT_A``, ``PLATT_B``, and ``FIT_SAMPLE`` in
``backend/app/services/pick_signal_constants.py``. It does not call an
external API.
"""

from __future__ import annotations

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
    return np.clip(np.round(probabilities, 4), 1e-4, 1.0 - 1e-4)


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
    gap = abs(float(np.mean(probabilities) - np.mean(outcomes)))
    log_loss = binary_log_loss(probabilities.tolist(), outcomes.tolist())
    ece = expected_calibration_error(probabilities.tolist(), outcomes.tolist(), COMBINED_EDGES)
    base_brier = float(np.mean(baseline_sq))
    base_gap = abs(float(np.mean(baseline) - np.mean(outcomes)))
    combined_se = float(np.std(combined_sq, ddof=1) / math.sqrt(n))
    baseline_se = float(np.std(baseline_sq, ddof=1) / math.sqrt(n))
    combined_ci = (brier - 1.96 * combined_se, brier + 1.96 * combined_se)
    baseline_ci = (base_brier - 1.96 * baseline_se, base_brier + 1.96 * baseline_se)
    base_log_loss = binary_log_loss(baseline.tolist(), outcomes.tolist())
    base_ece = expected_calibration_error(baseline.tolist(), outcomes.tolist(), PICK_EDGES)

    class _Row:
        def __init__(self, probability: float, hit: float):
            self.combined_probability = probability
            self.hit = hit

    rows = [_Row(float(probability), float(hit)) for probability, hit in zip(probabilities, outcomes)]
    bins = reliability(rows, lambda row: row.combined_probability, lambda row: row.hit, COMBINED_EDGES)
    widest = max((abs(item.gap) for item in bins), default=float("nan"))
    print(
        f"{label}: n={n} combined Brier {brier:.4f} "
        f"({combined_ci[0]:.4f}–{combined_ci[1]:.4f}) (gap {gap:.4f}, "
        f"log loss {log_loss:.4f}, ECE {ece:.4f}, widest bucket {widest:.4f}, "
        f"mean {float(np.mean(probabilities)):.4f} vs hit {float(np.mean(outcomes)):.4f}) "
        f"vs probability Brier {base_brier:.4f} "
        f"({baseline_ci[0]:.4f}–{baseline_ci[1]:.4f}) (gap {base_gap:.4f}, "
        f"log loss {base_log_loss:.4f}, ECE {base_ece:.4f}, "
        f"mean {float(np.mean(baseline)):.4f})"
    )
    return {
        "n": n,
        "brier": brier,
        "gap": gap,
        "log_loss": log_loss,
        "ece": ece,
        "widest_bucket": widest,
        "baseline_brier": base_brier,
        "baseline_gap": base_gap,
        "baseline_log_loss": base_log_loss,
        "baseline_ece": base_ece,
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
        f"    \"n\": {sample['n']},\n"
        f"    \"date_start\": \"{sample['date_start']}\",\n"
        f"    \"date_end\": \"{sample['date_end']}\",\n"
        '    "note": "Platt fit on the clipped adjustment total. '
        "Market log-odds coefficient is fixed at 1. "
        f"In-sample Brier {sample['brier']:.4f}, gap {sample['gap']:.4f}.\",\n"
        "}\n"
    )
    text, count = re.subn(r"FIT_SAMPLE = \{.*?\n\}\n", replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("FIT_SAMPLE block was not found in the constants file")
    path.write_text(text, encoding="utf-8")
    print(f"Wrote PLATT_A={intercept:.8f} PLATT_B={slope:.8f} to {path}")


def main() -> None:
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
    if len(rows) < 30:
        raise RuntimeError(f"only {len(rows)} NBA MED20 picks; refusing to fit")
    rows.sort(key=lambda row: row.date)
    adjustments = np.array([float(row.combined_adjustment) for row in rows])
    outcomes = np.array([float(row.hit) for row in rows])
    baseline = np.array([float(row.prob) for row in rows])
    intercept, slope = fit_platt(adjustments, outcomes)
    print(f"PLATT_A={intercept:.8f} PLATT_B={slope:.8f}")
    in_sample = _score(adjustments, outcomes, intercept, slope)
    full = _report("in-sample", in_sample, outcomes, baseline)

    dates = sorted({row.date for row in rows})
    cut = dates[max(0, math.floor(len(dates) * 0.70) - 1)]
    train_mask = np.array([row.date <= cut for row in rows])
    if train_mask.sum() >= 30 and (~train_mask).sum() >= 30:
        train_a, train_b = fit_platt(adjustments[train_mask], outcomes[train_mask])
        holdout = _score(adjustments[~train_mask], outcomes[~train_mask], train_a, train_b)
        print(f"holdout fit on dates <= {cut}: A={train_a:.8f} B={train_b:.8f}")
        _report("holdout", holdout, outcomes[~train_mask], baseline[~train_mask])
    else:
        print("holdout skipped: not enough picks on both sides of the date cut")

    _write_constants(
        intercept,
        slope,
        {
            "n": len(rows),
            "date_start": rows[0].date,
            "date_end": rows[-1].date,
            "brier": full["brier"],
            "gap": full["gap"],
        },
    )


if __name__ == "__main__":
    main()
