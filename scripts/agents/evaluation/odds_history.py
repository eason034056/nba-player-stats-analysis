"""Re-export opening and closing lines from the backend.

The functions live in ``app.services.snapshot_open_close``. This module
keeps ``from evaluation.odds_history import ...`` working for the
walk-forward package while ``scripts/agents`` is still in the tree.
"""

from __future__ import annotations

from evaluation.paths import bootstrap

bootstrap()

from app.services.snapshot_open_close import (  # noqa: E402
    ASSUMED_AMERICAN_ODDS,
    OddsHistory,
    PropOddsQuote,
    closing_line_value,
    inactive_history,
    load_odds_history,
    normalize_game_date,
    open_close_from_snapshots,
    player_key,
    unit_profit,
)

__all__ = [
    "ASSUMED_AMERICAN_ODDS",
    "OddsHistory",
    "PropOddsQuote",
    "closing_line_value",
    "inactive_history",
    "load_odds_history",
    "normalize_game_date",
    "open_close_from_snapshots",
    "player_key",
    "unit_profit",
]
