from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from application.use_cases.converse_with_expert import (
    chat_stream,
    get_or_create_conversation,
    reset_conversation,
)
from application.use_cases.create_expert import get_expert
from core.exceptions import ConversationError, ExpertNotFoundError
from core.logger import get_logger
from domain.entities import ExpertStatus

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = get_logger(__name__)


class ChatRequest(BaseModel):
    message: str
    use_graph: bool = True


class ConversationHistoryItem(BaseModel):
    role: str
    content: str
    timestamp: str


@router.post("/{expert_slug}")
async def chat_with_expert(expert_slug: str, body: ChatRequest):
    expert = get_expert(expert_slug)
    if not expert:
        raise HTTPException(status_code=404, detail=f"Expert '{expert_slug}' not found.")

    if expert.status != ExpertStatus.READY:
        raise HTTPException(
            status_code=409,
            detail=f"Expert '{expert_slug}' is not ready (status: {expert.status.value}).",
        )

    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    async def _event_stream():
        try:
            async for chunk in chat_stream(
                expert=expert,
                user_message=body.message.strip(),
                use_graph=body.use_graph,
            ):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except (ConversationError, ExpertNotFoundError) as exc:
            yield f"data: [ERROR] {exc}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/{expert_slug}/history")
async def get_conversation_history(expert_slug: str):
    expert = get_expert(expert_slug)
    if not expert:
        raise HTTPException(status_code=404, detail=f"Expert '{expert_slug}' not found.")

    conversation = get_or_create_conversation(expert_slug)
    return {
        "expert_slug": expert_slug,
        "messages": [
            ConversationHistoryItem(
                role=msg.role,
                content=msg.content,
                timestamp=msg.timestamp.isoformat(),
            )
            for msg in conversation.messages
        ],
    }


@router.delete("/{expert_slug}/history")
async def clear_conversation_history(expert_slug: str):
    reset_conversation(expert_slug)
    return {"status": "cleared", "expert_slug": expert_slug}
