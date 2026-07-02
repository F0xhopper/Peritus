import json

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from peritus.api.auth import AuthUser, require_user
from peritus.api.schemas.chat import ChatRequest
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.domain import ExpertStatus
from peritus.experts.repository import ExpertRepository
from peritus.infrastructure.database import get_pool

logger = get_logger(__name__)

router = APIRouter(prefix="/experts", tags=["chat"])


@router.post("/{slug}/chat")
async def chat_stream(slug: str, req: ChatRequest, user: AuthUser = Depends(require_user)):
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
            from peritus.chat.agent import ChatAgent, RetrievedContext, build_user_message
            from peritus.chat.grounding import (
                build_system_prompt,
                parse_cited_indices,
                used_citations,
            )
            from peritus.infrastructure.anthropic_client import get_anthropic_client

            # Retrieval pipeline (shared with ChatAgent.respond), statuses streamed.
            agent = ChatAgent(pool)
            ctx: RetrievedContext | None = None
            async for kind, payload in agent.retrieve(expert, req.question):
                if kind == "status":
                    yield {"data": json.dumps({"type": "status", "message": payload})}
                elif isinstance(payload, RetrievedContext):
                    ctx = payload
            assert ctx is not None

            # Stream the Anthropic response token by token.
            messages = list(history) + [build_user_message(req.question, ctx.context_block)]
            client = get_anthropic_client()
            answer_parts: list[str] = []
            async with client.messages.stream(
                model=settings.CLAUDE_MODEL,
                max_tokens=expert.config.max_response_tokens,
                system=build_system_prompt(expert.persona_style, expert.topic),
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    answer_parts.append(text)
                    yield {"data": json.dumps({"type": "token", "text": text})}

            # Resolve citations: only passages the answer actually cited, with the
            # passage numbers preserved so inline [n] matches the rendered list.
            answer_text = "".join(answer_parts)
            cited = parse_cited_indices(answer_text, len(ctx.passages))
            sources = used_citations(ctx.passages, cited)
            yield {"data": json.dumps({
                "type": "sources",
                "citations": sources,
                "has_contradiction": ctx.has_contradiction,
            })}

            yield {"data": json.dumps({"type": "done"})}

        except Exception:
            logger.exception("Chat stream failed for %r", slug)
            yield {"data": json.dumps({
                "type": "error",
                "message": "The expert hit an internal error while answering.",
            })}

    return EventSourceResponse(stream_generator())
