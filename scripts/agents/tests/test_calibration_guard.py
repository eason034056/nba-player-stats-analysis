"""The CI calibration guard: it fails on a bad sample and passes on a small real one."""

from __future__ import annotations

from evaluation.calibration_guard import (
    PRODUCTION_CHECK_ROWS,
    GuardResult,
    Thresholds,
    evaluate_guard,
    record_production_check,
    run_sample_guard,
)
from evaluation.metrics import summarize


class _Row:
    def __init__(self, prob: float, hit: int):
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


def test_guard_fails_when_brier_or_gap_exceeds_the_threshold():
    # Every pick is a confident miss. Brier is 0.81 and the gap is 0.90.
    summary = summarize([_Row(0.90, 0) for _ in range(40)])
    result = evaluate_guard(
        [("nba", summary)], Thresholds(max_brier=0.30, max_calibration_gap=0.15)
    )
    assert result.ok is False
    assert any("Brier" in item for item in result.failures)
    assert any("calibration gap" in item for item in result.failures)


def test_guard_passes_inside_the_threshold():
    rows = [_Row(0.60, 1 if index % 2 == 0 else 0) for index in range(40)]
    summary = summarize(rows)
    result = evaluate_guard(
        [("nba", summary)], Thresholds(max_brier=0.30, max_calibration_gap=0.15)
    )
    assert result.ok is True
    assert summary.brier < 0.30
    assert summary.calibration_gap < 0.15


def test_guard_fails_when_combined_probability_is_miscalibrated():
    # The published probability is inside the bounds. combined_probability is not.
    rows = []
    for index in range(40):
        hit = 1 if index % 2 == 0 else 0
        row = _Row(0.60, hit)
        row.combined_probability = 0.95
        rows.append(row)
    summary = summarize(rows)
    assert summary.brier < 0.30
    assert summary.calibration_gap < 0.15
    assert summary.combined_n == 40
    result = evaluate_guard(
        [("nba", summary)], Thresholds(max_brier=0.30, max_calibration_gap=0.15)
    )
    assert result.ok is False
    assert any("combined_probability" in item for item in result.failures)
    assert "FAIL nba combined_probability" in result.message


def test_guard_skips_combined_probability_when_the_column_is_empty():
    rows = [_Row(0.60, 1 if index % 2 == 0 else 0) for index in range(40)]
    summary = summarize(rows)
    assert summary.combined_n == 0
    result = evaluate_guard(
        [("wnba", summary)], Thresholds(max_brier=0.30, max_calibration_gap=0.15)
    )
    assert result.ok is True
    assert "skip wnba combined_probability: n=0" in result.message


def test_production_mismatch_fails_the_guard():
    # Brier can be fine and the guard still fails when get_player_stats disagrees.
    result = GuardResult(ok=True, lines=["Calibration guard: ok"])
    record_production_check(result, "nba", {"checked": PRODUCTION_CHECK_ROWS, "mismatches": 1})
    assert result.ok is False
    assert result.failures == [f"nba production rate mismatches 1 of {PRODUCTION_CHECK_ROWS}"]


def test_production_check_with_zero_rows_fails():
    result = GuardResult(ok=True)
    record_production_check(result, "wnba", {"checked": 0, "mismatches": 0})
    assert result.ok is False
    assert "sampled 0 rows" in result.failures[0]


def test_sample_walk_forward_stays_within_the_default_thresholds():
    # The default sample is 40 players per league, seed 7. That is the CI check.
    # The production comparison is 25 L10 rows per league on that same seed.
    result = run_sample_guard(seed=7)
    assert result.ok, result.message
    assert "nba" in result.message and "wnba" in result.message
    assert result.message.count(f"matched on {PRODUCTION_CHECK_ROWS}") == 2
