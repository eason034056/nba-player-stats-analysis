"""
graph.py – LangGraph StateGraph definition.

Flow:
  Planner
    -> parallel fan-out: Historical, Projection (stub), Market
    -> Deterministic Scoring Node
    -> Critic
    -> Synthesizer
    -> conditional: retry (missing mandatory input) or END
"""

import os
import sys

_AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)

from langgraph.graph import StateGraph, START, END

from state import BettingState
from agents import (
    planner_node,
    historical_agent_node,
    projection_agent_node,
    market_agent_node,
    scoring_node,
    critic_node,
    synthesizer_node,
)

# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------

def _should_retry(state: dict) -> str:
    """Conditional edge after synthesizer: retry only if mandatory data is missing."""
    final = state.get("final_decision", {})
    iteration = state.get("iteration", 0)
    if final.get("needs_retry") and iteration < 3:
        return "retry"
    return "done"


def build_graph() -> StateGraph:
    g = StateGraph(BettingState)

    # Nodes
    g.add_node("planner", planner_node)
    g.add_node("historical_agent", historical_agent_node)
    g.add_node("projection_agent", projection_agent_node)
    g.add_node("market_agent", market_agent_node)
    g.add_node("scoring", scoring_node)
    g.add_node("critic", critic_node)
    g.add_node("synthesizer", synthesizer_node)

    # Edges: START -> planner
    g.add_edge(START, "planner")

    # Planner -> parallel fan-out to 3 analysis agents
    g.add_edge("planner", "historical_agent")
    g.add_edge("planner", "projection_agent")
    g.add_edge("planner", "market_agent")

    # Fan-in: all 3 analysis agents -> scoring
    g.add_edge("historical_agent", "scoring")
    g.add_edge("projection_agent", "scoring")
    g.add_edge("market_agent", "scoring")

    # Scoring -> Critic -> Synthesizer
    g.add_edge("scoring", "critic")
    g.add_edge("critic", "synthesizer")

    # Conditional: synthesizer -> retry (planner) or END
    g.add_conditional_edges(
        "synthesizer",
        _should_retry,
        {"retry": "planner", "done": END},
    )

    return g


def compile_graph():
    """Build and compile the graph, ready to invoke."""
    return build_graph().compile()


def export_mermaid() -> str:
    """Export Mermaid diagram of the compiled graph."""
    app = compile_graph()
    return app.get_graph().draw_mermaid()


if __name__ == "__main__":
    print(export_mermaid())
