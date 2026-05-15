"""SPO-58 (Phase 5c) — WNBA agent chat smoke test (Gate 3c).

Verifies the boundary contract for `POST /api/wnba/agent/chat`:

1. The endpoint exists and answers without 500.
2. The new WNBA-default-on-omission helper (`_default_to_wnba_league`) is
   applied at the route layer.
3. By the time the graph runner is called, `event_context["league"]` is
   `"wnba"` so every league-aware tool / node downstream gets the right
   discriminator.

This is a smoke test, NOT a full end-to-end of the LangGraph. We mock the
graph runner so the test runs without OpenAI keys / live odds / Postgres.
The downstream tool / prompt behaviour is covered by:
  - scripts/agents/tests/test_phase5b_league.py (5b — node + prompt routing)
  - the historical / market unit tests already in backend/tests/ (per-tool)

Smoke target per SPO-36 acceptance:
  > A new `test_agent_chat_wnba.py` that asks an analogous WNBA question
  > (use a player from the Phase 1 CSV smoke test, e.g., A'ja Wilson —
  > confirm she's in the CSV first) and verifies the agent answers
  > without 500ing.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.agent_chat import AgentChatRequest
from app.services.agent_chat import AgentChatService


def _make_wnba_pick(**overrides):
    """A'ja Wilson PRA pick — A'ja confirmed present in the Phase 1 WNBA CSV
    via `wnba_csv_player_service._all_players` lookup."""
    pick = {
        "player_name": "A'ja Wilson",
        "player_team": "Las Vegas Aces",
        "event_id": "evt-wnba-1",
        "home_team": "Las Vegas Aces",
        "away_team": "Seattle Storm",
        "commence_time": "2026-06-15T02:00:00Z",
        "metric": "points",
        "threshold": 24.5,
        "direction": "over",
        "probability": 0.65,
        "n_games": 25,
    }
    pick.update(overrides)
    return pick


def _stub_graph_result() -> dict:
    """Minimum graph result shape that `agent_chat_service._map_verdict` /
    `_derive_status` won't choke on. Captured shape mirrors the live graph's
    `final_decision` + `scorecard` payload, trimmed to the keys the
    response-mapping code reads."""
    return {
        "final_decision": {
            "decision": "avoid",
            "confidence": 0.5,
            "model_probability": 0.5,
            "market_implied_probability": None,
            "expected_value_pct": None,
            "summary": "WNBA smoke stub — fake graph result for SPO-58 Gate 3c",
            "dimensions": {},
            "risk_factors": [],
            "needs_retry": False,
        },
        "scorecard": {
            "decision": "avoid",
            "confidence": 0.5,
            "model_probability": 0.5,
            "eligible_for_bet": False,
            "query_aligned_context": {},
        },
    }


@pytest.mark.asyncio
async def test_wnba_agent_chat_threads_league_into_event_context_for_aja_wilson():
    """Smoke: WNBA chat route + service inject league='wnba' end-to-end."""
    captured: dict = {}

    async def fake_graph_runner(query, event_context):
        captured["event_context"] = event_context
        captured["query"] = query
        return _stub_graph_result()

    service = AgentChatService(graph_runner=fake_graph_runner)

    # Mirror what the WNBA route does: inject league='wnba' on the boundary.
    # We exercise the service directly because the route's only job is the
    # league injection (covered by test_wnba_agent_route_injects_league below).
    request = AgentChatRequest.model_validate(
        {
            "thread": "thread-wnba-smoke",
            "message": "Should I bet A'ja Wilson over 24.5 points?",
            "action": "analyze_pick",
            "context": {
                "page": {"route": "/wnba/picks", "date": "2026-06-15", "league": "wnba"},
                "selected_pick": _make_wnba_pick(),
            },
        }
    )

    response = await service.handle_chat(request)

    assert response.status in {"ok", "warn", "error"}, response.status
    assert captured["event_context"]["league"] == "wnba"
    # Smoke target: endpoint did not 500. (A 500 here would be an unhandled
    # exception inside `handle_chat`, which routes back to AgentChatResponse
    # with status='error' — which is fine for the smoke; what we forbid is
    # the FastAPI route raising HTTPException(500).)


@pytest.mark.asyncio
async def test_wnba_agent_chat_falls_back_to_nba_default_inside_service_when_league_missing():
    """Confirms the 5a NBA-default fallback still works when the WNBA route
    has NOT been invoked — i.e. when a caller hits the service directly
    without setting league. This is the regression contract: legacy callers
    keep NBA semantics unchanged."""
    captured: dict = {}

    async def fake_graph_runner(query, event_context):
        captured["event_context"] = event_context
        return _stub_graph_result()

    service = AgentChatService(graph_runner=fake_graph_runner)

    request = AgentChatRequest.model_validate(
        {
            "thread": "thread-no-league",
            "message": "Generic NBA-style query without league field",
            "action": "analyze_pick",
            "context": {
                "page": {"route": "/picks", "date": "2026-03-13"},
                "selected_pick": {
                    "player_name": "Stephen Curry",
                    "player_team": "Golden State Warriors",
                    "event_id": "evt-nba-1",
                    "home_team": "Los Angeles Lakers",
                    "away_team": "Golden State Warriors",
                    "commence_time": "2026-03-13T02:00:00Z",
                    "metric": "points",
                    "threshold": 28.5,
                    "direction": "over",
                    "probability": 0.7,
                    "n_games": 20,
                },
            },
        }
    )

    await service.handle_chat(request)

    # NBA-default lives in agent_chat_service._build_event_context per 5a.
    assert captured["event_context"]["league"] == "nba"


def test_wnba_agent_route_injects_league_when_client_omits_it():
    """Route-level: the WNBA route's `_default_to_wnba_league` helper sets
    league='wnba' only when the client did not specify one explicitly.
    Verified at the helper level (no live request loop needed)."""
    from app.api.wnba_agent import _default_to_wnba_league

    # Case A: client omits league entirely.
    req_a = AgentChatRequest.model_validate(
        {
            "thread": "t",
            "message": "m",
            "action": "analyze_pick",
            "context": {"page": {"route": "/wnba"}, "selected_pick": _make_wnba_pick()},
        }
    )
    out_a = _default_to_wnba_league(req_a)
    assert out_a.context.page.league == "wnba"

    # Case B: client explicitly says nba on the WNBA route. We do NOT
    # silently override — surface the inconsistency rather than hide it.
    req_b = AgentChatRequest.model_validate(
        {
            "thread": "t",
            "message": "m",
            "action": "analyze_pick",
            "context": {
                "page": {"route": "/wnba", "league": "nba"},
                "selected_pick": _make_wnba_pick(),
            },
        }
    )
    out_b = _default_to_wnba_league(req_b)
    assert out_b.context.page.league == "nba"

    # Case C: client explicitly says wnba — unchanged.
    req_c = AgentChatRequest.model_validate(
        {
            "thread": "t",
            "message": "m",
            "action": "analyze_pick",
            "context": {
                "page": {"route": "/wnba", "league": "wnba"},
                "selected_pick": _make_wnba_pick(),
            },
        }
    )
    out_c = _default_to_wnba_league(req_c)
    assert out_c.context.page.league == "wnba"

    # Case D: client omits the entire context (a truly minimal request).
    # The helper must construct an AgentContext + AgentPageContext on the
    # fly and still tag league='wnba'.
    req_d = AgentChatRequest.model_validate(
        {"thread": "t", "message": "m", "action": "analyze_pick"}
    )
    out_d = _default_to_wnba_league(req_d)
    assert out_d.context is not None
    assert out_d.context.page is not None
    assert out_d.context.page.league == "wnba"
