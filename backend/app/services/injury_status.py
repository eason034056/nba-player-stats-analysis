"""NBA injury status words shared by the injury cache and the agents that read it.

This module imports nothing, so ``scripts/agents/scoring.py`` can use it
without pulling in Redis or settings.
"""

from __future__ import annotations

OUT = "Out"
DOUBTFUL = "Doubtful"
QUESTIONABLE = "Questionable"
DAY_TO_DAY = "Day-To-Day"
PROBABLE = "Probable"

UNRESOLVED_INJURY_STATUSES: frozenset[str] = frozenset({DOUBTFUL, QUESTIONABLE, DAY_TO_DAY})
"""The player may or may not play. Out is decided, so it is not in this set."""


def is_unresolved_injury(status: str | None) -> bool:
    """True for Doubtful, Questionable, or Day-To-Day, compared exactly."""
    return status in UNRESOLVED_INJURY_STATUSES


def is_out_or_unresolved(status: str | None) -> bool:
    """True when the injury report says Out or leaves the player in doubt."""
    return status == OUT or is_unresolved_injury(status)
