from fastapi import APIRouter, HTTPException

from app.models.agent_chat import AgentChatRequest, AgentChatResponse
from app.services.agent_chat import agent_chat_service


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
        return await agent_chat_service.handle_chat(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent chat failed: {exc}") from exc
