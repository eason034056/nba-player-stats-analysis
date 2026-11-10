"""Log loss, ECE, and the combined_probability column on the metrics path."""

from __future__ import annotations

import math

from evaluation.metrics import (
    COMBINED_EDGES,
    binary_log_loss,
    expected_calibration_error,
    reliability,
    summarize,
)


class _Row:
    def __init__(self, prob: float, hit: int, combined: float | None):
        self.over_hit = hit
        self.actual = 11.0 if hit else 0.0
        self.line = 10.5
        self.p_over = prob
        self.pick = "over"
        self.hit = hit
        self.prob = prob
        self.price = None
        self.clv_prob = None
        self.clv_line = None
        self.combined_probability = combined


def test_log_loss_and_ece_match_their_definitions():
    predictions = [0.8, 0.8]
    outcomes = [1.0, 0.0]
    expected_loss = -(math.log(0.8) + math.log(0.2)) / 2
    assert binary_log_loss(predictions, outcomes) == pytest_approx(expected_loss)
    # One bin covering both rows. ECE is |0.8 - 0.5|.
    assert expected_calibration_error(predictions, outcomes, (0.0, 1.0001)) == pytest_approx(0.3)
    assert math.isnan(binary_log_loss([], []))
    assert math.isnan(expected_calibration_error([], [], COMBINED_EDGES))


def pytest_approx(value: float):
    import pytest

    return pytest.approx(value)


def test_summary_scores_combined_probability_separately_from_probability():
    rows = [
        _Row(0.70, 1, 0.60),
        _Row(0.70, 0, 0.40),
    ]
    summary = summarize(rows)
    assert summary.brier == pytest_approx(((0.70 - 1) ** 2 + (0.70 - 0) ** 2) / 2)
    assert summary.log_loss == pytest_approx(binary_log_loss([0.70, 0.70], [1.0, 0.0]))
    assert summary.combined_n == 2
    assert summary.combined_brier == pytest_approx(((0.60 - 1) ** 2 + (0.40 - 0) ** 2) / 2)
    assert summary.combined_hit_rate == pytest_approx(0.5)
    assert summary.combined_avg_pred == pytest_approx(0.5)
    assert summary.combined_calibration_gap == pytest_approx(0.0)
    assert summary.combined_log_loss == pytest_approx(binary_log_loss([0.60, 0.40], [1.0, 0.0]))
    bins = reliability(
        rows,
        lambda row: row.combined_probability,
        lambda row: row.hit,
        COMBINED_EDGES,
    )
    assert bins
    assert summary.combined_ece == pytest_approx(
        expected_calibration_error([0.60, 0.40], [1.0, 0.0], COMBINED_EDGES)
    )


def test_a_row_without_combined_probability_does_not_enter_that_column():
    summary = summarize([_Row(0.66, 1, None), _Row(0.66, 0, None)])
    assert summary.picks == 2
    assert summary.combined_n == 0
    assert math.isnan(summary.combined_brier)
    assert math.isnan(summary.combined_calibration_gap)
