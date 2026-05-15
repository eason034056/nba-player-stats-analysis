"""
WNBA agent chat route (SPO-58, Phase 5c).

Mirrors `app/api/agent.py` but injects `page.league = "wnba"` as the default
on the request boundary so the existing `agent_chat_service.handle_chat`
runs the SAME LangGraph with `state.league = "wnba"`.

Why a separate route file instead of widening the existing one:
  - keeps the FastAPI prefix `/api/wnba/agent` symmetric with `/api/nba/agent`
  - lets the WNBA prefix get independent middleware / rate limits later
    without touching the NBA route
  - the route is small enough that duplication beats abstraction
"""

from fastapi import APIRouter, HTTPException

from app.models.agent_chat import (
    AgentChatRequest,
    AgentChatResponse,
    AgentContext,
    AgentPageContext,
)
from app.services.agent_chat import agent_chat_service


router = APIRouter(
    prefix="/api/wnba/agent",
    tags=["agent"],
)


def _default_to_wnba_league(request: AgentChatRequest) -> AgentChatRequest:
    """Set ``context.page.league = "wnba"`` only when the client omitted it.

    The single LangGraph branches on ``state.league`` which the planner reads
    from ``event_context["league"]`` which ``agent_chat_service`` pulls from
    ``request.context.page.league``. The NBA-default fallback inside
    ``agent_chat_service._build_event_context`` would otherwise tag a missing
    league as ``"nba"`` even on this WNBA-only router — so we inject the
    boundary default here. An explicit ``"nba"`` from the client (e.g. a
    misrouted call) is preserved unchanged so the failure surfaces visibly
    rather than being silently overridden.
    """
    context = request.context or AgentContext()
    page = context.page or AgentPageContext()
    if page.league is None:
        page.league = "wnba"
    context.page = page
    request.context = context
    return request


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    summary="Run the betting agent against WNBA page context",
)
async def chat_with_wnba_agent(request: AgentChatRequest) -> AgentChatResponse:
    try:
        return await agent_chat_service.handle_chat(_default_to_wnba_league(request))
    except Exception as exc:  # noqa: BLE001 — mirrors NBA route behaviour
        raise HTTPException(status_code=500, detail=f"WNBA agent chat failed: {exc}") from exc
