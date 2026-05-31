"""SPO-76 — unit tests for scripts/agents/graph.py (LangGraph wiring).

`graph.py` is the assembly point for the *entire* product agent: it wires the
seven nodes together and owns `_should_retry`, the conditional edge that decides
whether the agent loops back to the planner or terminates. Both surfaces had
zero coverage. The hazards are concrete:

  * A regression in `_should_retry` either causes **runaway retry loops**
    (re-running the whole graph — compute/$$ — on every query) or **silently
    never retries** when mandatory inputs are missing, degrading every
    recommendation.
  * An accidentally dropped node or edge in `build_graph()` would ship silently
    — the graph still compiles, it just stops doing part of the work.

This file pins both. It is tests-only and does NOT modify `graph.py`.

Import style mirrors test_scoring.py / test_phase5b_league.py: conftest.py puts
``scripts/agents`` on sys.path, so ``graph`` is a top-level module and pulling
in its ``agents`` dependency works without a live ``OPENAI_API_KEY`` (the LLM
client is constructed lazily, not at import time).

The structural expectations below were captured from the real compiled graph,
not hand-authored — see the SPO-76 task summary for the verification command.
"""

import pytest

from graph import _should_retry, build_graph, compile_graph

# The canonical node set, per graph.py's `g.add_node(...)` calls. A compiled
# LangGraph also injects the synthetic ``__start__`` / ``__end__`` sentinels;
# those are filtered out before comparison so this asserts *our* nodes only.
EXPECTED_NODES = {
    "planner",
    "historical_agent",
    "projection_agent",
    "market_agent",
    "scoring",
    "critic",
    "synthesizer",
}


# ---------------------------------------------------------------------------
# _should_retry — the retry-loop guard (graph.py:37-43)
# ---------------------------------------------------------------------------
#
# Contract: return "retry" ONLY when final_decision.needs_retry is truthy AND
# iteration < 3; otherwise "done". `iteration == 3` is the cap boundary — the
# single most important case, because that is what stops a runaway loop.

@pytest.mark.parametrize(
    "state, expected",
    [
        # needs_retry=True, below the cap -> keep retrying
        ({"final_decision": {"needs_retry": True}, "iteration": 0}, "retry"),
        ({"final_decision": {"needs_retry": True}, "iteration": 1}, "retry"),
        ({"final_decision": {"needs_retry": True}, "iteration": 2}, "retry"),
        # ⚠️ cap boundary: iteration == 3 is NOT < 3, so the loop MUST stop here.
        # This is the guard against runaway retries — the regression that costs $$.
        ({"final_decision": {"needs_retry": True}, "iteration": 3}, "done"),
        # past the cap -> still done (defends against a `==` regression too)
        ({"final_decision": {"needs_retry": True}, "iteration": 4}, "done"),
        # explicitly no retry requested -> done regardless of iteration
        ({"final_decision": {"needs_retry": False}, "iteration": 0}, "done"),
        # missing final_decision key -> .get returns {} -> .get("needs_retry")
        # is falsy -> done (the safe default path)
        ({"iteration": 0}, "done"),
        # missing iteration key -> defaults to 0, so a real retry still fires
        ({"final_decision": {"needs_retry": True}}, "retry"),
        # fully empty state -> done (no retry, no crash)
        ({}, "done"),
    ],
)
def test_should_retry_decision(state, expected):
    assert _should_retry(state) == expected


def test_should_retry_returns_only_routing_literals():
    """The return value is a routing key consumed by add_conditional_edges; it
    must be exactly "retry" or "done" (the two mapped keys), never a bool or
    None — a typo here would route to a non-existent node at runtime."""
    assert _should_retry({"final_decision": {"needs_retry": True}, "iteration": 0}) == "retry"
    assert _should_retry({"final_decision": {"needs_retry": False}}) == "done"


# ---------------------------------------------------------------------------
# build_graph / compile_graph — structural smoke test
# ---------------------------------------------------------------------------

def test_compile_graph_compiles_without_error():
    """The whole point: a dropped/renamed node breaks compilation (dangling
    edge) — so a clean compile is itself a meaningful regression gate."""
    app = compile_graph()
    assert app is not None


def test_compile_graph_has_exactly_the_seven_expected_nodes():
    app = compile_graph()
    # Compiled graph adds the synthetic __start__/__end__ sentinels; strip them
    # so we compare against our own declared node set exactly (== not >=, to
    # also catch an *added* stray node).
    nodes = {n for n in app.get_graph().nodes if not n.startswith("__")}
    assert nodes == EXPECTED_NODES


def test_synthesizer_conditional_edge_exists():
    """The retry/END decision is the only conditional edge in the graph. Assert
    it on the uncompiled StateGraph, where conditional edges live in `branches`
    keyed by source node -> the _should_retry guard is registered there."""
    g = build_graph()
    assert "synthesizer" in g.branches, "synthesizer conditional edge was dropped"
    # _should_retry is the registered branch function for that edge.
    assert "_should_retry" in g.branches["synthesizer"]


def test_synthesizer_routes_to_both_planner_and_end():
    """End-to-end view of the conditional edge: in the compiled graph the
    synthesizer must fan out to BOTH targets — `planner` (the "retry" branch)
    and `__end__` (the "done" branch). Losing either silently breaks the loop
    in one direction."""
    app = compile_graph()
    targets = {e.target for e in app.get_graph().edges if e.source == "synthesizer"}
    assert "planner" in targets, "retry branch (synthesizer -> planner) missing"
    assert "__end__" in targets, "done branch (synthesizer -> END) missing"
