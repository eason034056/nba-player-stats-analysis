"""Compare the historical daily-picks board with the combined-probability board.

Storage is unchanged: a row is still kept when a historical side clears
the Lean floor. The published board and the tier now use
``combined_probability``. This module counts who enters, who leaves, and
whose tier label changes on one stored list. It does not recompute the
signal model.
"""

from __future__ import annotations

from typing import Any

from app.models.schemas import DailyPick
from app.services.daily_analysis import (
    HIGH_PROBABILITY_THRESHOLD,
    MIN_SAMPLE_GAMES,
    read_tier,
    select_daily_picks,
)


def _historical_board(
    picks: list[DailyPick],
    min_probability: float = HIGH_PROBABILITY_THRESHOLD,
    min_games: int = MIN_SAMPLE_GAMES,
) -> list[DailyPick]:
    """The board before this change: historical probability and sample size."""
    return [
        pick
        for pick in picks
        if pick.probability >= min_probability and pick.n_games >= min_games
    ]


def _label(pick: DailyPick) -> str:
    """Stable name for one stored row. Metric separates two markets."""
    return f"{pick.player_name}|{pick.metric}|{pick.direction}"


def measure_board_shift(
    picks: list[DailyPick],
    *,
    min_probability: float = HIGH_PROBABILITY_THRESHOLD,
    min_games: int = MIN_SAMPLE_GAMES,
) -> dict[str, Any]:
    """Count enter, leave, and tier changes on one stored candidate list.

    ``entered`` were off the old 0.65 / 10 historical board and are on
    the combined board. ``left`` is the reverse. ``tier_changed`` is
    every stored row whose ``read_tier(probability)`` differs from
    ``read_tier(combined_probability)``, including a change to or from
    null. A row can both change tier and enter or leave.

    Args:
        picks: Stored candidates, already carrying ``combined_probability``
            and a tier computed from it.
        min_probability: Inclusive board floor. Default 0.65.
        min_games: Inclusive sample floor. Default 10.

    Returns:
        Counts and the row labels for each bucket. Labels are
        ``player|metric|direction``.
    """
    old_rows = _historical_board(picks, min_probability, min_games)
    new_rows = select_daily_picks(
        picks, min_probability, min_games, league="nba"
    )
    old_labels = {_label(pick) for pick in old_rows}
    new_labels = {_label(pick) for pick in new_rows}
    entered = tuple(sorted(new_labels - old_labels))
    left = tuple(sorted(old_labels - new_labels))
    changes: list[dict[str, Any]] = []
    for pick in picks:
        old_tier = read_tier(pick.probability)
        new_tier = read_tier(pick.combined_probability)
        if old_tier == new_tier:
            continue
        changes.append(
            {
                "label": _label(pick),
                "player": pick.player_name,
                "metric": pick.metric,
                "direction": pick.direction,
                "probability": pick.probability,
                "combined_probability": pick.combined_probability,
                "old_tier": old_tier,
                "new_tier": new_tier,
            }
        )
    changes.sort(key=lambda item: item["label"])
    return {
        "stored": len(picks),
        "old_board": len(old_rows),
        "new_board": len(new_rows),
        "entered": len(entered),
        "left": len(left),
        "tier_changed": len(changes),
        "entered_labels": list(entered),
        "left_labels": list(left),
        "tier_changes": changes,
    }
