import json

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from peritus.api.auth import AuthUser, require_user
from peritus.api.schemas.chat import ChatRequest
from peritus.core.logging import get_logger
from peritus.experts.domain import ExpertStatus
from peritus.experts.repository import ExpertRepository
from peritus.infrastructure.database import get_pool

logger = get_logger(__name__)

router = APIRouter(prefix="/experts", tags=["chat"])


@router.post("/{slug}/chat")
async def chat_stream(slug: str, req: ChatRequest, user: AuthUser = Depends(require_user)):
    """Stateless chat — the TUI/CLI contract. History arrives in the request
    body and nothing is persisted; the stateful web flow lives in
    ``routes/conversations.py``. Both share ``chat.streaming``."""
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    if expert.status != ExpertStatus.READY:
        raise HTTPException(status_code=409, detail=f"Expert status is {expert.status.value}, not ready")

    history = [{"role": m.role, "content": m.content} for m in req.history]

    async def stream_generator():
        try:
            from peritus.chat.streaming import stream_expert_answer

            async for event in stream_expert_answer(pool, expert, req.question, history):
                yield {"data": json.dumps(event)}
        except Exception:
            logger.exception("Chat stream failed for %r", slug)
            yield {"data": json.dumps({
                "type": "error",
                "message": "The expert hit an internal error while answering.",
            })}

    return EventSourceResponse(stream_generator())
