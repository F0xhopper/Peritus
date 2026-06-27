"""Chat agent — plan → batch_search → graph_expand → assess_coverage → respond."""

import copy
from dataclasses import dataclass, field

import asyncpg

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.graph.retriever import EnrichedResult, GraphRetriever
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.search.service import SearchService

logger = get_logger(__name__)

_PLAN_TOOL = {
    "name": "create_plan",
    "description": "Decompose a question into retrieval subqueries.",
    "input_schema": {
        "type": "object",
        "properties": {
            "subqueries": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 4,
                "description": "2–4 declarative retrieval-phrased subqueries.",
            },
        },
        "required": ["subqueries"],
    },
}

_COVERAGE_TOOL = {
    "name": "coverage_assessment",
    "description": "Assess whether retrieved passages adequately answer the question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "satisfied": {"type": "boolean"},
            "suggested_queries": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["satisfied", "suggested_queries"],
    },
}


@dataclass
class Answer:
    text: str
    sources_used: list[str] = field(default_factory=list)
    has_contradiction: bool = False


class ChatAgent:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._search = SearchService(pool)
        self._graph = GraphRetriever(pool)

    async def respond(
        self,
        expert: Expert,
        question: str,
        history: list[dict],
    ) -> Answer:
        cfg = expert.config

        # 1. Plan subqueries
        subqueries = await self._plan(question, expert.topic, cfg.max_subqueries)

        # 2. Parallel hybrid search
        search_resp = await self._search.batch_search(
            expert_id=expert.id,
            question=question,
            queries=subqueries,
            top_k=cfg.retrieval_top_k,
        )

        # 3. Graph expansion
        enriched = await self._graph.expand(search_resp.results, expert.id, hops=cfg.graph_hops)

        # 4. Coverage assessment
        passages = [{"text": e.text, "citation": e.citation} for e in enriched]
        coverage = await self._assess_coverage(question, passages, cfg.max_context_passages)

        if not coverage["satisfied"] and coverage.get("suggested_queries"):
            extra_resp = await self._search.batch_search(
                expert_id=expert.id,
                question=question,
                queries=coverage["suggested_queries"][:cfg.max_subqueries // 2],
                top_k=cfg.coverage_extra_k,
            )
            extra_enriched = await self._graph.expand(extra_resp.results, expert.id, hops=cfg.graph_hops)
            enriched = enriched + extra_enriched

        # 5. Respond in persona
        context_block = _build_context(enriched, cfg.max_context_passages)
        has_contradiction = any(e.has_contradiction for e in enriched)

        client = get_anthropic_client()
        messages = list(history) + [{
            "role": "user",
            "content": (
                f"Question: {question}\n\n"
                f"Retrieved context (cite inline as [Source — Type · Q:score]):\n\n"
                f"{context_block}"
            ),
        }]

        resp = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=cfg.max_response_tokens,
            system=expert.persona_style or f"You are a subject-matter expert in {expert.topic}.",
            messages=messages,
        )
        answer_text = "".join(b.text for b in resp.content if hasattr(b, "text"))

        sources_used = list({e.citation for e in enriched})
        return Answer(
            text=answer_text,
            sources_used=sources_used,
            has_contradiction=has_contradiction,
        )

    async def _plan(self, question: str, topic: str, max_subqueries: int = 4) -> list[str]:
        try:
            tool = copy.deepcopy(_PLAN_TOOL)
            tool["input_schema"]["properties"]["subqueries"]["maxItems"] = max_subqueries
            tool["input_schema"]["properties"]["subqueries"]["minItems"] = min(2, max_subqueries)

            client = get_anthropic_client()
            resp = await client.messages.create(
                model=settings.FAST_MODEL,
                max_tokens=256,
                system=(
                    f"You are a retrieval planner for a {topic} expert. "
                    f"Decompose the question into 2–{max_subqueries} declarative retrieval subqueries — "
                    "phrases a relevant passage would contain, not questions."
                ),
                tools=[tool],
                tool_choice={"type": "tool", "name": "create_plan"},
                messages=[{"role": "user", "content": f"Question: {question}"}],
            )
            block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
            return block.input.get("subqueries", [question])
        except Exception as exc:
            logger.warning("Planning failed: %s", exc)
            return [question]

    async def _assess_coverage(
        self, question: str, passages: list[dict], max_passages: int = 15
    ) -> dict:
        try:
            client = get_anthropic_client()
            passage_block = "\n\n".join(
                f"[{i}] {p['citation']}\n{p['text'][:600]}"
                for i, p in enumerate(passages[:max_passages])
            )
            resp = await client.messages.create(
                model=settings.FAST_MODEL,
                max_tokens=256,
                system=(
                    "You assess retrieval coverage. Mark satisfied=true only when passages "
                    "provide direct substantive evidence. Suggest follow-up queries for gaps."
                ),
                tools=[_COVERAGE_TOOL],
                tool_choice={"type": "tool", "name": "coverage_assessment"},
                messages=[{
                    "role": "user",
                    "content": f"Question: {question}\n\nPassages:\n\n{passage_block}",
                }],
            )
            block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
            return dict(block.input)
        except Exception as exc:
            logger.warning("Coverage assessment failed: %s", exc)
            return {"satisfied": True, "suggested_queries": []}


def _build_context(enriched: list[EnrichedResult], max_passages: int = 15) -> str:
    parts = []
    for i, e in enumerate(enriched[:max_passages], 1):
        parts.append(f"[{i}] {e.citation}\n{e.context_block()}")
    return "\n\n".join(parts)
