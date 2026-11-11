from fastapi import APIRouter, HTTPException

from app.api.agent_deadline import run_agent_chat
from app.models.agent_chat import AgentChatRequest, AgentChatResponse


router = APIRouter(
    prefix="/api/nba/agent",
    tags=["agent"],
)


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    summary="Run the betting agent against current page context",
)
async def chat_with_agent(request: AgentChatRequest) -> AgentChatResponse:
    try:
        return await run_agent_chat(request)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent chat failed: {exc}") from exc
