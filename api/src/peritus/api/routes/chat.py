import json

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from peritus.api.auth import require_api_key
from peritus.api.schemas.chat import ChatRequest
from peritus.experts.domain import ExpertStatus
from peritus.experts.repository import ExpertRepository
from peritus.infrastructure.database import get_pool

router = APIRouter(prefix="/experts", tags=["chat"], dependencies=[Depends(require_api_key)])


@router.post("/{slug}/chat")
async def chat_stream(slug: str, req: ChatRequest):
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_by_name(slug)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    if expert.status != ExpertStatus.READY:
        raise HTTPException(status_code=409, detail=f"Expert status is {expert.status.value}, not ready")

    history = [{"role": m.role, "content": m.content} for m in req.history]
    cfg = expert.config

    def _status(msg: str) -> dict:
        return {"data": json.dumps({"type": "status", "message": msg})}

    async def stream_generator():
        try:
            from peritus.chat.agent import ChatAgent, _build_context
            agent = ChatAgent(pool)

            # Plan subqueries
            yield _status("Planning search queries…")
            subqueries = await agent._plan(req.question, expert.topic, cfg.max_subqueries)

            # Parallel hybrid search
            yield _status(f"Searching knowledge base across {len(subqueries)} queries…")
            search_resp = await agent._search.batch_search(
                expert_id=expert.id,
                question=req.question,
                queries=subqueries,
                top_k=cfg.retrieval_top_k,
            )

            # Graph expansion
            yield _status("Expanding knowledge graph…")
            enriched = await agent._graph.expand(search_resp.results, expert.id, hops=cfg.graph_hops)

            # Coverage check
            yield _status("Assessing coverage…")
            passages = [{"text": e.text, "citation": e.citation} for e in enriched]
            coverage = await agent._assess_coverage(req.question, passages, cfg.max_context_passages)
            if not coverage["satisfied"] and coverage.get("suggested_queries"):
                yield _status("Retrieving additional context…")
                extra_resp = await agent._search.batch_search(
                    expert_id=expert.id,
                    question=req.question,
                    queries=coverage["suggested_queries"][:cfg.max_subqueries // 2],
                    top_k=cfg.coverage_extra_k,
                )
                extra_enriched = await agent._graph.expand(extra_resp.results, expert.id, hops=cfg.graph_hops)
                enriched = enriched + extra_enriched

            # Build context block
            yield _status("Composing response…")
            context_block = _build_context(enriched, cfg.max_context_passages)

            # Stream the Anthropic response token by token
            from peritus.infrastructure.anthropic_client import get_anthropic_client
            from peritus.core.config import settings

            messages = list(history) + [{
                "role": "user",
                "content": (
                    f"Question: {req.question}\n\n"
                    f"Retrieved context (cite inline as [Source — Type · Q:score]):\n\n"
                    f"{context_block}"
                ),
            }]

            client = get_anthropic_client()
            async with client.messages.stream(
                model=settings.CLAUDE_MODEL,
                max_tokens=cfg.max_response_tokens,
                system=expert.persona_style or f"You are a subject-matter expert in {expert.topic}.",
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield {"data": json.dumps({"type": "token", "text": text})}

            sources = list({e.citation for e in enriched})
            yield {"data": json.dumps({"type": "sources", "citations": sources})}
            yield {"data": json.dumps({"type": "done"})}

        except Exception as exc:
            yield {"data": json.dumps({"type": "error", "message": str(exc)})}

    return EventSourceResponse(stream_generator())
