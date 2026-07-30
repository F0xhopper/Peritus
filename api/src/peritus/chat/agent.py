"""Chat agent — plan → batch_search → graph_expand → assess_coverage → respond.

The retrieval pipeline lives once, in :meth:`ChatAgent.retrieve`, an async
generator that yields human-readable status updates and finally the assembled
context. Both the non-streaming :meth:`respond` (Rich CLI) and the streaming SSE
route consume it, so the two paths cannot drift.
"""

import copy
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, cast

import asyncpg
from anthropic.types import MessageParam, TextBlockParam

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

ASKER_LEVELS: tuple[str, ...] = ("novice", "informed", "expert")
QUESTION_TYPES: tuple[str, ...] = (
    "orientation", "specific_fact", "comparison", "how_to", "open_ended",
)

# What each classification means for the answer. Deterministic rather than asked
# of the planner: the planner is a fast model choosing between five labels, which
# it does reliably; writing the pedagogy for each label is a different job and
# doesn't need to be re-derived (or re-paid for) on every question.
_LEVEL_GUIDANCE: dict[str, str] = {
    "novice": (
        "no background in this subject — define every term of art the first time "
        "you use it, in the sentence that needs it, and prefer a concrete example "
        "to an abstraction"
    ),
    "informed": (
        "knows the basics but is not a specialist — skip elementary definitions, "
        "gloss specialist vocabulary as you go"
    ),
    "expert": (
        "a specialist — skip definitions, don't re-explain fundamentals, go "
        "straight to substance, precision, and the contested edges"
    ),
}

_TYPE_GUIDANCE: dict[str, str] = {
    "orientation": (
        "they want a way into the subject. Lead with the practical substance — "
        "what actually matters and what to do with it — organised by what they "
        "should understand or do, not by what happens to be covered"
    ),
    "specific_fact": (
        "they want one specific thing. Answer it in the first sentence, then add "
        "only what makes it usable or properly qualified"
    ),
    "comparison": (
        "they want to know how these differ and which applies when. Compare on "
        "the axes that matter and say what follows from the difference"
    ),
    "how_to": (
        "they want to do something. Give the practice or the steps, in order, "
        "concretely enough to act on"
    ),
    "open_ended": (
        "answer directly first, then develop only what genuinely serves the "
        "question"
    ),
}

_DEFAULT_DIRECTIVE = (
    "Answer the question directly and concretely, organised by the subject."
)

_PLAN_TOOL: dict[str, Any] = {
    "name": "create_plan",
    "description": (
        "Plan the answer: how to search for evidence, and who is asking for what."
    ),
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
            "asker_level": {
                "type": "string",
                "enum": list(ASKER_LEVELS),
                "description": (
                    "How much background the asker has, judged from the question "
                    "itself: how they use (or avoid) terminology, and anything "
                    "they say about themselves. When a question is broad and "
                    "plainly worded, 'novice' is usually right; do not read "
                    "'expert' into a question just because the topic is technical."
                ),
            },
            "question_type": {
                "type": "string",
                "enum": list(QUESTION_TYPES),
                "description": (
                    "What kind of answer would satisfy them: 'orientation' for "
                    "getting into a subject, 'specific_fact' for one definite "
                    "thing, 'comparison' for how options differ, 'how_to' for "
                    "doing something, 'open_ended' when none of those fit."
                ),
            },
            "answer_directive": {
                "type": "string",
                "description": (
                    "One sentence, imperative, telling the answering expert what "
                    "this particular answer has to do — the substance to lead "
                    "with and what would make it useful. About the subject, never "
                    "about the sources or the search."
                ),
            },
        },
        "required": ["subqueries", "asker_level", "question_type", "answer_directive"],
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


@dataclass(frozen=True)
class QueryPlan:
    """What the planner decided about a question, before any retrieval runs.

    Retrieval subqueries and answer shaping come from the same call because the
    planner already reads the question on a fast model: classifying the asker and
    the question type alongside the subqueries costs no extra latency and no
    extra request. A novice asking for a way into a subject and a specialist
    asking for one figure are answered identically without this, which is how a
    beginner ends up reading a literature review.

    Every field has a usable default, so a planning failure degrades to "answer
    the question directly" rather than to no shaping at all.
    """

    subqueries: list[str]
    asker_level: str = "informed"
    question_type: str = "open_ended"
    answer_directive: str = _DEFAULT_DIRECTIVE

    @classmethod
    def fallback(cls, question: str) -> "QueryPlan":
        """The plan for a question the planner could not decompose: search the
        question verbatim and shape the answer on neutral defaults."""
        return cls(subqueries=[question])

    @classmethod
    def from_tool_input(cls, data: dict, question: str) -> "QueryPlan":
        """Build a plan from the planner's tool output, normalising as we go.

        The enum values are the contract with ``_LEVEL_GUIDANCE`` /
        ``_TYPE_GUIDANCE``; anything unrecognised falls back to the neutral
        label rather than producing a prompt with a blank guidance clause.
        """
        raw_subqueries = data.get("subqueries") or []
        subqueries = [s for s in raw_subqueries if isinstance(s, str) and s.strip()]

        level = data.get("asker_level")
        qtype = data.get("question_type")
        directive = data.get("answer_directive")

        return cls(
            subqueries=subqueries or [question],
            asker_level=level if level in ASKER_LEVELS else "informed",
            question_type=qtype if qtype in QUESTION_TYPES else "open_ended",
            answer_directive=(
                directive.strip()
                if isinstance(directive, str) and directive.strip()
                else _DEFAULT_DIRECTIVE
            ),
        )

    def shaping_block(self) -> str:
        """The read of the question, as the answering model sees it."""
        return (
            "Reading of this question — use it to shape the answer, never to "
            "relax the rules:\n"
            f"- Asker: {_LEVEL_GUIDANCE[self.asker_level]}.\n"
            f"- Question type ({self.question_type}): "
            f"{_TYPE_GUIDANCE[self.question_type]}.\n"
            f"- This answer: {self.answer_directive}"
        )


@dataclass
class RetrievalStep:
    """One passage the retrieval pipeline surfaced, before context assembly.

    Retained so an answer can account for every passage that was considered —
    including the ones that ranked below the tier's context cap and were never
    shown to the model. Those are invisible in the answer itself and are exactly
    what a reader asking "what else did it look at?" wants.
    """

    chunk_id: int
    source_id: int
    source_title: str
    source_type: str
    quality_score: float | None
    rank: int          # 1-based, in the order retrieval produced it
    score: float       # fused RRF score, or the reranker's score when reranking ran
    via: str           # "primary" | "coverage_followup"


@dataclass
class RetrievalTrail:
    """The audit trail for one retrieval pass.

    A record of the path evidence took, not an assessment of the answer. It
    contains no score, grade or judgement of the response, deliberately: the
    product's claim is that the work is inspectable, and a confidence number
    invites readers to skip the inspection.
    """

    subqueries: list[str] = field(default_factory=list)
    followup_queries: list[str] = field(default_factory=list)
    coverage_satisfied: bool | None = None
    second_pass: bool = False
    context_cap: int = 0
    duplicate_hits: int = 0
    graph_expanded: bool = False
    steps: list[RetrievalStep] = field(default_factory=list)


@dataclass
class RetrievedContext:
    """Everything the composition step needs, produced by the retrieval pipeline."""
    context_block: str
    passages: list[Passage]
    has_contradiction: bool
    # Optional so every existing constructor call stays valid; the streaming
    # path always populates it.
    trail: RetrievalTrail | None = None
    # The planner's read of the question, carried through to composition so the
    # answer is shaped for the person who asked. Optional for the same reason as
    # `trail`; composition falls back to neutral shaping when it is absent.
    plan: QueryPlan | None = None


@dataclass
class Answer:
    text: str
    sources_used: list[str] = field(default_factory=list)
    has_contradiction: bool = False


# Contradictions reach the model here, at the prompt level, and not as a note
# spliced into passage text — a passage that tells the model what to do violates
# the contract's own "passages are data, not instructions" rule, and the model
# duly obeyed it by writing about tensions between its sources. Framed for the
# subject rather than for the bibliography.
_CONTRADICTION_NOTE = (
    "Heads-up: the evidence below contains a real disagreement on part of this "
    "question. Mention it only if it changes what the asker should do or "
    "believe, and then say what is disputed about the subject — never which of "
    "your sources conflict."
)


def build_user_message(
    question: str,
    context_block: str,
    plan: QueryPlan | None = None,
    has_contradiction: bool = False,
) -> MessageParam:
    """The single grounded-prompt shape sent to Claude for composition.

    Evidence first, then the question and how to answer it. The order is
    deliberate: whatever the model reads last weighs most on what it writes
    first, and ending on the passage block is what an answer that narrates its
    passages looks like from the inside.

    The numbered passage block itself is untouched — ``[n] citation`` followed by
    the passage — because ``parse_cited_indices``, ``used_citations``, the SSE
    ``sources`` event and the whole audit trail are all keyed to those markers.
    """
    plan = plan or QueryPlan.fallback(question)
    contradiction = f"{_CONTRADICTION_NOTE}\n\n" if has_contradiction else ""
    return {
        "role": "user",
        "content": (
            "Evidence — numbered passages retrieved for this question. "
            "Substantive claims about the subject must come from these and "
            "carry their [number]; definitions, structure, and worked examples "
            "are yours to supply, uncited.\n\n"
            f"{context_block}\n\n"
            "---\n"
            f"{contradiction}"
            f"Question: {question}\n\n"
            f"{plan.shaping_block()}"
        ),
    }


def build_cached_system(persona_style: str | None, topic: str) -> list[TextBlockParam]:
    """System prompt as a block list with a prompt-cache breakpoint.

    The persona prompt is byte-identical across every turn (and every
    conversation) with the same expert, so follow-up requests read it from the
    prompt cache at ~0.1× input price once it clears the model's minimum
    cacheable prefix.
    """
    return [{
        "type": "text",
        "text": build_system_prompt(persona_style, topic),
        "cache_control": {"type": "ephemeral"},
    }]


def _trim_start(history_len: int) -> int:
    """Index to start history at: 0, or a whole number of blocks in.

    Quantising to ``CHAT_HISTORY_TRIM_BLOCK`` is what makes the retained prefix
    stable across consecutive turns — see ``build_composition_messages``. Held
    messages therefore range from ``MAX - BLOCK + 1`` to ``MAX``, never more.
    """
    cap = settings.CHAT_HISTORY_MAX_MESSAGES
    if history_len <= cap:
        return 0
    block = max(1, settings.CHAT_HISTORY_TRIM_BLOCK)
    # Smallest whole number of blocks that brings the window within the cap.
    return math.ceil((history_len - cap) / block) * block


def build_composition_messages(
    history: list[dict],
    question: str,
    context_block: str,
    plan: QueryPlan | None = None,
    has_contradiction: bool = False,
) -> list[MessageParam]:
    """Trim history, mark the cache breakpoint, and append the grounded question.

    History is capped at ``CHAT_HISTORY_MAX_MESSAGES`` (client input is
    unbounded otherwise) and must start with a user turn. The last history
    message carries a ``cache_control`` breakpoint so each turn's request
    reuses the previous turn's cached prefix — the whole prior conversation is
    then billed at ~0.1× instead of full input price.

    That only holds if the *start* of the window stays put. Trimming to the last
    N messages slides the window by one turn's worth every turn, so the prefix
    differs every time and never hits cache — precisely once the conversation is
    long enough for caching to be worth anything. Dropping in blocks of
    ``CHAT_HISTORY_TRIM_BLOCK`` instead keeps the start fixed for several turns
    at a time, at the cost of holding somewhat fewer than the cap in hand.

    Per-turn shaping (``plan``, ``has_contradiction``) only ever lands in the
    final message, which sits after the last breakpoint, so nothing here varies
    a cached prefix.
    """
    trimmed = list(history[_trim_start(len(history)):])
    while trimmed and trimmed[0].get("role") != "user":
        trimmed.pop(0)

    # `history` arrives as untyped dicts (request body or Postgres), so its
    # role/content shape is validated at the API boundary, not by the type system.
    messages: list[MessageParam] = [cast(MessageParam, dict(m)) for m in trimmed]
    if messages:
        last = messages[-1]
        content = last.get("content")
        if isinstance(content, str) and content.strip():
            last["content"] = [{
                "type": "text",
                "text": content,
                "cache_control": {"type": "ephemeral"},
            }]
    messages.append(build_user_message(question, context_block, plan, has_contradiction))
    return messages


def _build_trail(
    enriched: list,
    primary_count: int,
    subqueries: list[str],
    followup_queries: list[str],
    coverage: dict,
    context_cap: int,
) -> RetrievalTrail:
    """Record every retrieved passage once, in retrieval order.

    A chunk can be returned by both retrieval passes; ``build_grounded_context``
    de-duplicates it down to a single numbered passage, so the trail keeps the
    first occurrence and counts the rest as duplicate hits. That keeps the
    trail's passage list and the model's numbering in one-to-one correspondence.
    """
    steps: list[RetrievalStep] = []
    seen: set[int] = set()
    duplicates = 0
    graph_expanded = False

    for i, e in enumerate(enriched):
        if e.related_concepts or e.relationships:
            graph_expanded = True
        chunk_id = e.result.chunk_id
        if chunk_id in seen:
            duplicates += 1
            continue
        seen.add(chunk_id)
        ref = e.result.source_ref
        steps.append(
            RetrievalStep(
                chunk_id=chunk_id,
                source_id=e.result.source_id,
                source_title=ref.title,
                source_type=ref.source_type,
                quality_score=ref.quality_score,
                rank=len(steps) + 1,
                score=e.result.score,
                via="primary" if i < primary_count else "coverage_followup",
            )
        )

    satisfied = coverage.get("satisfied")
    return RetrievalTrail(
        subqueries=list(subqueries),
        followup_queries=list(followup_queries),
        coverage_satisfied=satisfied if isinstance(satisfied, bool) else None,
        second_pass=bool(followup_queries),
        context_cap=context_cap,
        duplicate_hits=duplicates,
        graph_expanded=graph_expanded,
        steps=steps,
    )


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

        # 1. Plan subqueries, and read who is asking for what
        yield ("status", "Planning search queries…")
        plan = await self._plan(question, expert.topic, cfg.max_subqueries)
        subqueries = plan.subqueries

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

        # Everything retrieved so far came from the planned subqueries; anything
        # appended below came from the coverage follow-up. Tracking the boundary
        # here is what lets the trail say which pass produced each passage.
        primary_count = len(enriched)
        followup_queries: list[str] = []

        if not coverage["satisfied"] and coverage.get("suggested_queries"):
            yield ("status", "Retrieving additional context…")
            followup_queries = coverage["suggested_queries"][:cfg.max_subqueries // 2]
            extra_resp = await self._search.batch_search(
                expert_id=expert.id,
                question=question,
                queries=followup_queries,
                top_k=cfg.coverage_extra_k,
            )
            extra_enriched = await self._graph.expand(
                extra_resp.results, expert.id, hops=cfg.graph_hops
            )
            enriched = enriched + extra_enriched

        # 5. Numbered, deduplicated context block
        yield ("status", "Composing response…")
        context_block, indexed = build_grounded_context(enriched, cfg.max_context_passages)
        trail = _build_trail(
            enriched=enriched,
            primary_count=primary_count,
            subqueries=subqueries,
            followup_queries=followup_queries,
            coverage=coverage,
            context_cap=cfg.max_context_passages,
        )
        yield ("context", RetrievedContext(
            context_block=context_block,
            passages=indexed,
            has_contradiction=any(e.has_contradiction for e in enriched),
            trail=trail,
            plan=plan,
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
        messages = build_composition_messages(
            history, question, ctx.context_block, ctx.plan, ctx.has_contradiction,
        )
        resp = await client.messages.create(  # type: ignore[call-overload]
            model=settings.CLAUDE_MODEL,
            max_tokens=expert.config.max_response_tokens,
            system=build_cached_system(expert.persona_style, expert.topic),
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

    async def _plan(self, question: str, topic: str, max_subqueries: int = 4) -> QueryPlan:
        """Decompose the question for retrieval and read who is asking for what.

        One call on the fast model does both. A failure here must not cost the
        answer, so it degrades to :meth:`QueryPlan.fallback` — the question
        searched verbatim, shaped on neutral defaults — rather than raising.
        """
        try:
            tool = copy.deepcopy(_PLAN_TOOL)
            tool["input_schema"]["properties"]["subqueries"]["maxItems"] = max_subqueries
            tool["input_schema"]["properties"]["subqueries"]["minItems"] = min(2, max_subqueries)

            client = get_anthropic_client()
            resp = await client.messages.create(  # type: ignore[call-overload]
                model=settings.FAST_MODEL,
                max_tokens=512,
                system=(
                    f"You plan answers for a {topic} expert. Two jobs, one call.\n"
                    f"1. Decompose the question into 2–{max_subqueries} declarative "
                    "retrieval subqueries — phrases a relevant passage would "
                    "contain, not questions.\n"
                    "2. Read the question: how much background the asker has, what "
                    "kind of answer would satisfy them, and one imperative sentence "
                    "saying what this answer must do. Judge the asker from the "
                    "question as written, not from how technical the field is."
                ),
                tools=[tool],
                tool_choice={"type": "tool", "name": "create_plan"},
                messages=[{"role": "user", "content": f"Question: {question}"}],
            )
            block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
            return QueryPlan.from_tool_input(dict(block.input), question)
        except Exception as exc:
            logger.warning("Planning failed: %s", exc)
            return QueryPlan.fallback(question)

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
