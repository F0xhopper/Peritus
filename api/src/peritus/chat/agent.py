"""Chat agent — plan → batch_search → graph_expand → assess_coverage → respond.

The retrieval pipeline lives once, in :meth:`ChatAgent.retrieve`, an async
generator that yields human-readable status updates and finally the assembled
context. Both the non-streaming :meth:`respond` (Rich CLI) and the streaming SSE
route consume it, so the two paths cannot drift.
"""

import copy
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import asyncpg

from peritus.chat.grounding import (
    Passage,
    build_grounded_context,
    build_system_prompt,
    parse_cited_indices,
    used_citation_labels,
)
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.graph.retriever import GraphRetriever
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.search.service import SearchService

logger = get_logger(__name__)

_PLAN_TOOL: dict[str, Any] = {
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

_COVERAGE_TOOL: dict[str, Any] = {
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
class RetrievedContext:
    """Everything the composition step needs, produced by the retrieval pipeline."""
    context_block: str
    passages: list[Passage]
    has_contradiction: bool


@dataclass
class Answer:
    text: str
    sources_used: list[str] = field(default_factory=list)
    has_contradiction: bool = False


def build_user_message(question: str, context_block: str) -> dict:
    """The single grounded-prompt shape sent to Claude for composition."""
    return {
        "role": "user",
        "content": (
            f"Question: {question}\n\n"
            "Numbered passages — answer only from these and cite each claim "
            "with its [number]:\n\n"
            f"{context_block}"
        ),
    }


# Yielded items: ("status", str) progress updates, then exactly one
# ("context", RetrievedContext) as the final item.
RetrieveEvent = tuple[str, "str | RetrievedContext"]


class ChatAgent:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._search = SearchService(pool)
        self._graph = GraphRetriever(pool)

    async def retrieve(
        self,
        expert: Expert,
        question: str,
    ) -> AsyncIterator[RetrieveEvent]:
        """Run the full retrieval pipeline, yielding status updates along the way.

        The final yielded item is always ``("context", RetrievedContext)``.
        """
        cfg = expert.config

        # 1. Plan subqueries
        yield ("status", "Planning search queries…")
        subqueries = await self._plan(question, expert.topic, cfg.max_subqueries)

        # 2. Parallel hybrid search
        yield ("status", f"Searching knowledge base across {len(subqueries)} queries…")
        search_resp = await self._search.batch_search(
            expert_id=expert.id,
            question=question,
            queries=subqueries,
            top_k=cfg.retrieval_top_k,
        )

        # 3. Graph expansion
        yield ("status", "Expanding knowledge graph…")
        enriched = await self._graph.expand(search_resp.results, expert.id, hops=cfg.graph_hops)

        # 4. Coverage assessment, with one follow-up retrieval pass if unsatisfied
        yield ("status", "Assessing coverage…")
        passages = [{"text": e.text, "citation": e.citation} for e in enriched]
        coverage = await self._assess_coverage(question, passages, cfg.max_context_passages)

        if not coverage["satisfied"] and coverage.get("suggested_queries"):
            yield ("status", "Retrieving additional context…")
            extra_resp = await self._search.batch_search(
                expert_id=expert.id,
                question=question,
                queries=coverage["suggested_queries"][:cfg.max_subqueries // 2],
                top_k=cfg.coverage_extra_k,
            )
            extra_enriched = await self._graph.expand(
                extra_resp.results, expert.id, hops=cfg.graph_hops
            )
            enriched = enriched + extra_enriched

        # 5. Numbered, deduplicated context block
        yield ("status", "Composing response…")
        context_block, indexed = build_grounded_context(enriched, cfg.max_context_passages)
        yield ("context", RetrievedContext(
            context_block=context_block,
            passages=indexed,
            has_contradiction=any(e.has_contradiction for e in enriched),
        ))

    async def gather_context(self, expert: Expert, question: str) -> RetrievedContext:
        """Run :meth:`retrieve` discarding status updates."""
        async for kind, payload in self.retrieve(expert, question):
            if kind == "context":
                assert isinstance(payload, RetrievedContext)
                return payload
        raise RuntimeError("retrieve() ended without yielding context")

    async def respond(
        self,
        expert: Expert,
        question: str,
        history: list[dict],
    ) -> Answer:
        """Non-streaming answer (used by the Rich CLI)."""
        ctx = await self.gather_context(expert, question)

        client = get_anthropic_client()
        messages: list[Any] = list(history) + [build_user_message(question, ctx.context_block)]
        resp = await client.messages.create(  # type: ignore[call-overload]
            model=settings.CLAUDE_MODEL,
            max_tokens=expert.config.max_response_tokens,
            system=build_system_prompt(expert.persona_style, expert.topic),
            messages=messages,
        )
        answer_text = "".join(b.text for b in resp.content if hasattr(b, "text"))

        # Only the passages the answer actually cited count as sources used.
        cited = parse_cited_indices(answer_text, len(ctx.passages))
        sources_used = used_citation_labels(ctx.passages, cited)

        return Answer(
            text=answer_text,
            sources_used=sources_used,
            has_contradiction=ctx.has_contradiction,
        )

    async def _plan(self, question: str, topic: str, max_subqueries: int = 4) -> list[str]:
        try:
            tool = copy.deepcopy(_PLAN_TOOL)
            tool["input_schema"]["properties"]["subqueries"]["maxItems"] = max_subqueries
            tool["input_schema"]["properties"]["subqueries"]["minItems"] = min(2, max_subqueries)

            client = get_anthropic_client()
            resp = await client.messages.create(  # type: ignore[call-overload]
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
            resp = await client.messages.create(  # type: ignore[call-overload]
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
