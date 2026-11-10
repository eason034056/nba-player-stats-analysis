"""Daily Picks side selection stays the production rule the backtest imports."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.daily_analysis import (
    HIGH_PROBABILITY_THRESHOLD,
    MIN_SAMPLE_GAMES,
    choose_daily_pick_side,
)


def test_over_wins_when_both_sides_clear_the_threshold():
    assert HIGH_PROBABILITY_THRESHOLD == 0.65
    assert MIN_SAMPLE_GAMES == 10
    assert choose_daily_pick_side(0.70, 0.80) == ("over", 0.70)


def test_under_is_chosen_only_when_over_misses():
    assert choose_daily_pick_side(0.6499, 0.65) == ("under", 0.65)


def test_neither_side_is_a_pick_below_the_threshold():
    assert choose_daily_pick_side(0.6499, 0.6499) == (None, None)
    assert choose_daily_pick_side(None, None) == (None, None)


def test_missing_over_does_not_block_an_under():
    assert choose_daily_pick_side(None, 0.91) == ("under", 0.91)
