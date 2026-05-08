"""
projection.py – Dimension 6 stub tools.

SportsDataIO feed is dummy data. All tools return 'unavailable' with zero
weight so the deterministic scoring node never incorporates them.
The interfaces are preserved for future activation.
"""

from datetime import datetime, timezone
from typing import Any, Dict

_NOW_ISO = lambda: datetime.now(timezone.utc).isoformat()

_STUB = {
    "status": "unavailable",
    "reason": "SportsDataIO data is dummy and excluded from scoring",
}


def _unavailable_signal(tool_name: str, **kwargs) -> Dict[str, Any]:
    return {
        "signal": "unavailable",
        "effect_size": 0.0,
        "sample_size": 0,
        "reliability": 0.0,
        "window": "n/a",
        "source": "sportsdataio_stub",
        "as_of": _NOW_ISO(),
        "details": {**_STUB, "tool": tool_name, "params": kwargs},
    }


def get_full_projection(player: str, date: str = "") -> Dict[str, Any]:
    """Projected points/reb/ast/pra, minutes, usage%, PER, DFS salary."""
    return _unavailable_signal("get_full_projection", player=player, date=date)


def calculate_edge(projected_value: float, threshold: float) -> Dict[str, Any]:
    """Projected value minus threshold, with interpretation."""
    return _unavailable_signal("calculate_edge", projected_value=projected_value, threshold=threshold)


def get_opponent_defense_profile(player: str, date: str = "") -> Dict[str, Any]:
    """Opponent defensive rank and position-specific rank."""
    return _unavailable_signal("get_opponent_defense_profile", player=player, date=date)


def get_minutes_confidence(player: str, date: str = "") -> Dict[str, Any]:
    """Compare projected minutes to CSV season average."""
    return _unavailable_signal("get_minutes_confidence", player=player, date=date)


ALL_PROJECTION_TOOLS = [
    get_full_projection,
    calculate_edge,
    get_opponent_defense_profile,
    get_minutes_confidence,
]
