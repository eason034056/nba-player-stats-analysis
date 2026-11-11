"""Stop agent chat before the 120s proxy in front of this API gives up."""

import asyncio

from fastapi import HTTPException

from app.models.agent_chat import AgentChatRequest, AgentChatResponse
from app.services.agent_chat import agent_chat_service
from app.settings import settings


def agent_chat_timeout_detail(seconds: float) -> str:
    """Error text for a chat that did not finish inside the server deadline."""
    shown = int(seconds) if seconds == int(seconds) else seconds
    return (
        f"Agent chat exceeded the server time limit ({shown}s) and was stopped. "
        "The proxy in front of this API closes the connection at 120s, so this "
        "request ended before that. Try one pick instead of a full slip or board review."
    )


async def run_agent_chat(request: AgentChatRequest) -> AgentChatResponse:
    """Run one chat and return 504 when it exceeds agent_chat_timeout_seconds."""
    seconds = settings.agent_chat_timeout_seconds
    try:
        return await asyncio.wait_for(
            agent_chat_service.handle_chat(request),
            timeout=seconds,
        )
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=agent_chat_timeout_detail(seconds),
        ) from None
