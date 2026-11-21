"""Pivot ``prop_actuals`` onto one row per player-game.

Each market becomes ``y_<market>``. A NULL actual stays NULL so that
market's trainer can skip the row. The row is dropped only when every
market is NULL. DNP is that case: the prop is void, and the label is not
zero. ``player_double_double`` and ``player_triple_double`` are already 0
or 1 in ``prop_actuals``. This module does not recount double-digit stats.
"""

from __future__ import annotations

from collections.abc import Mapping

# The 002 prop_markets seed, in catalog order. A database test checks this
# tuple against the rows 002 inserts.
CATALOG_MARKETS = (
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_steals",
    "player_blocks",
    "player_points_rebounds",
    "player_points_assists",
    "player_rebounds_assists",
    "player_points_rebounds_assists",
    "player_double_double",
    "player_triple_double",
)


def label_column_names() -> tuple[str, ...]:
    """``y_<market>`` for every catalog market, in catalog order."""
    return tuple(f"y_{market}" for market in CATALOG_MARKETS)


def pivot_labels(values: Mapping[str, int | None]) -> dict[str, int | None] | None:
    """Pivot one player-game's actuals onto ``y_<market>`` columns.

    Args:
        values: ``market -> actual_value``. A missing market is NULL.
            Markets outside the catalog are ignored.

    Returns:
        The label columns, or None when every label is NULL. None means
        the dataset row is dropped. A zero is a real result and keeps the row.
    """
    pivoted = {f"y_{market}": values.get(market) for market in CATALOG_MARKETS}
    if all(value is None for value in pivoted.values()):
        return None
    return pivoted
