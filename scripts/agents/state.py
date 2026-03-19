"""
state.py – LangGraph state definition.

BettingState is a TypedDict consumed by every node in the graph.
Using structured dicts (not free-form strings) enables:
  - deterministic post-processing by the scoring node
  - backtesting and auditability
  - prompt debugging
"""

import operator
from typing import Any, Dict, List, Optional
from typing_extensions import Annotated, TypedDict

from langgraph.graph.message import add_messages


def _merge_dicts(left: dict, right: dict) -> dict:
    """Merge two dicts (right wins on key collisions)."""
    merged = left.copy() if left else {}
    if right:
        merged.update(right)
    return merged


class BettingState(TypedDict):
    messages: Annotated[list, add_messages]
    user_query: str
    parsed_query: Dict[str, Any]
    event_context: Dict[str, Any]
    availability: Dict[str, bool]
    historical_signals: Dict[str, Dict[str, Any]]
    projection_signals: Dict[str, Dict[str, Any]]
    market_signals: Dict[str, Dict[str, Any]]
    scorecard: Dict[str, Any]
    data_quality_flags: Annotated[List[str], operator.add]
    critic_notes: Annotated[List[str], operator.add]
    final_decision: Dict[str, Any]
    audit_log: Annotated[List[Dict[str, Any]], operator.add]
    iteration: int
