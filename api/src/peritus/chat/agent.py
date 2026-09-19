"""Chat agent — plan → batch_search → graph_expand → relevance gate → respond.

The retrieval pipeline lives once, in :meth:`ChatAgent.retrieve`, an async
generator that yields human-readable status updates and finally the assembled
context. Both the non-streaming :meth:`respond` (Rich CLI) and the streaming SSE
route consume it, so the two paths cannot drift.
"""

import asyncio
import math
import re
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, cast

import anthropic
import asyncpg
from anthropic.types import MessageParam, TextBlockParam, ToolChoiceToolParam, ToolParam

from peritus.chat.grounding import (
    Passage,
    build_grounded_context,
    build_system_prompt,
    parse_cited_indices,
    used_citation_labels,
)
from peritus.chat.neighbours import position, reading_order, wanted_positions
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.graph.retriever import EnrichedResult, GraphRetriever
from peritus.infrastructure.anthropic_client import get_anthropic_client, tool_input
from peritus.ingestion.quality import is_prose, near_duplicate, shingles
from peritus.ingestion.summaries import search_sections
from peritus.search.service import SearchService

logger = get_logger(__name__)

ASKER_LEVELS: tuple[str, ...] = ("novice", "informed", "expert")
QUESTION_TYPES: tuple[str, ...] = (
    "orientation",
    "explanation",
    "specific_fact",
    "comparison",
    "how_to",
    "open_ended",
)

# What each classification means for the answer. Deterministic rather than asked
# of the planner: the planner is a fast model choosing between six labels, which
# it does reliably; writing the pedagogy for each label is a different job and
# doesn't need to be re-derived (or re-paid for) on every question.
#
# "explanation" was missing, and its absence is why answers ran short. Most of
# what anyone asks an expert — what is X, why is it so, what is the best
# argument for it — had nowhere to go but "specific_fact": "What is the most
# tangible proof for God?" was filed there eight times out of eight, and the
# answerer was duly told to give one thing and "add only what makes it usable".
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
    "explanation": (
        "they want to understand something — an idea, an argument, or why a thing "
        "is so. State it plainly first, then give the reasoning itself rather "
        "than a description of it: each step in order and how it leads to the "
        "next, and one example that makes it concrete. Where the idea faces a "
        "serious, well-known objection, take it on. Depth is the point here"
    ),
    "specific_fact": (
        "they want one definite thing — a date, a name, a figure, a yes or no. "
        "Answer it in the first sentence, then add only what makes it usable or "
        "properly qualified"
    ),
    "comparison": (
        "they want to know how these differ and which applies when. Compare on "
        "the axes that matter and say what follows from the difference"
    ),
    "how_to": (
        "they want to do something. Give the practice or the steps, in order, "
        "concretely enough to act on"
    ),
    "open_ended": ("answer directly first, then develop only what genuinely serves the question"),
}

_DEFAULT_DIRECTIVE = "Answer the question directly and concretely, organised by the subject."


def _plan_tool(max_subqueries: int) -> ToolParam:
    """The planner's tool, with the subquery bounds this turn allows.

    A builder rather than a module constant that gets `deepcopy`'d and poked:
    the bounds are the only thing that varies, and reaching four levels into a
    schema by string key to set them is not something a type can check — mypy
    says so, and it is right.

    A **strict** tool: the input is constrained to the schema as it is decoded,
    not hoped to match it. Unconstrained, the fast model returned ``subqueries``
    as a string with its own tool-call markup in it (``'<item>Thomistic
    arguments…'``) on 7 of 24 calls; strict, 0 of 24. Strict schemas take no
    array-size constraints, so the bounds live in the descriptions and are
    enforced by ``_query_list`` — which stays, because a guarantee from the
    provider is still not a reason to iterate a string.
    """
    return {
        "name": "create_plan",
        "description": ("Plan the answer: how to search for evidence, and who is asking for what."),
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "subqueries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        f"{min(2, max_subqueries)}–{max_subqueries} declarative "
                        "retrieval-phrased subqueries, never more."
                    ),
                },
                "fallback_queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "One or two broader or differently-angled retrieval phrasings, "
                        "used only if the subqueries find little. Not paraphrases of "
                        "the subqueries: approach the question from a wider concept, "
                        "a neighbouring term of art, or the underlying mechanism."
                    ),
                },
                "standalone_question": {
                    "type": "string",
                    "description": (
                        "The question rewritten to stand on its own, with every "
                        "reference to the conversation ('the second one', 'he', "
                        "'that method') replaced by what it refers to. Identical to "
                        "the question when it already stands alone."
                    ),
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
                        "getting into a subject; 'explanation' for understanding an "
                        "idea, an argument, or why something is so — most 'what is "
                        "X', 'why', 'how does X work' and 'what is the best case for "
                        "X' questions; 'specific_fact' only for one definite datum "
                        "(a date, a name, a figure, a yes or no); 'comparison' for "
                        "how options differ; 'how_to' for doing something; "
                        "'open_ended' when none of those fit."
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
            # All six. `fallback_queries` and `standalone_question` were optional
            # and the fast model mostly left them out: one of the last 14 audited
            # plans carried fallback queries, so the second pass — the recovery
            # for weak retrieval — had nothing to search on the turns it existed
            # for.
            "required": [
                "subqueries",
                "fallback_queries",
                "standalone_question",
                "asker_level",
                "question_type",
                "answer_directive",
            ],
        },
    }


# Tool-call markup the fast model occasionally leaks into a string value.
_MARKUP_RE = re.compile(r"<[^>]*>")


def _query_list(value: object, limit: int) -> list[str]:
    """The planner's queries as a clean list, whatever shape they arrived in.

    The schema says array and nothing enforces it: the fast model has returned
    ``subqueries`` as one string with its own tool-call markup leaked into it
    (``'<parameter name="item">cosmological argument…'``). Iterating that gave 72
    one-character "subqueries", each embedded and searched, and their rankings
    outvoted the one real query in the fusion — the answer was written from
    three passages of a table of contents while the article it needed sat in the
    corpus. So a string is read as the queries it contains, markup is dropped,
    and the count is capped here rather than trusted to ``maxItems``.
    """
    if isinstance(value, str):
        logger.warning("Planner returned a query list as a string: %.120r", value)
        value = [value]
    if not isinstance(value, list):
        return []
    queries: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        for part in _MARKUP_RE.split(item):
            text = " ".join(part.split())
            if text and text not in queries:
                queries.append(text)
    return queries[:limit]


# How much of a previous turn the planner sees. Enough to resolve "the second
# one" or "and how does Fisher differ?"; not so much that planning a follow-up
# costs more than planning a first question by a meaningful margin.
_PLAN_HISTORY_CHARS = 400


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
    #: Broader phrasings for the follow-up pass, asked for in the same call so
    #: a weak first pass does not need a second planning step.
    fallback_queries: list[str] = field(default_factory=list)
    #: The question with its references to the conversation resolved. What the
    #: question itself is searched and reranked as; None means "as asked".
    standalone_question: str | None = None

    @classmethod
    def fallback(cls, question: str) -> "QueryPlan":
        """The plan for a question the planner could not decompose: search the
        question verbatim and shape the answer on neutral defaults."""
        return cls(subqueries=[question])

    @classmethod
    def from_tool_input(cls, data: dict, question: str, max_subqueries: int = 4) -> "QueryPlan":
        """Build a plan from the planner's tool output, normalising as we go.

        The enum values are the contract with ``_LEVEL_GUIDANCE`` /
        ``_TYPE_GUIDANCE``; anything unrecognised falls back to the neutral
        label rather than producing a prompt with a blank guidance clause.
        """
        subqueries = _query_list(data.get("subqueries"), max_subqueries)

        level = data.get("asker_level")
        qtype = data.get("question_type")
        directive = data.get("answer_directive")
        fallbacks = _query_list(data.get("fallback_queries"), 2)
        standalone = data.get("standalone_question")

        return cls(
            fallback_queries=fallbacks,
            standalone_question=(
                standalone.strip() if isinstance(standalone, str) and standalone.strip() else None
            ),
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
    rank: int  # 1-based, in the order retrieval produced it
    score: float  # fused RRF score, or the reranker's score when reranking ran
    #: "primary" | "coverage_followup" (the fallback-query pass) | "neighbour"
    #: (not searched for: the chunk beside one that was — chat/neighbours.py)
    #: | "subquery_seat" (a part of the question that won nothing on the fused
    #: ranking, given its own best passages) | "section_route" (a broad
    #: question's section, found by its summary) | "source_diversity" (seated
    #: in place of a dominant source's weakest passage)
    via: str


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
    #: Whether the first pass cleared the relevance gate. None when the scores
    #: were not a reranker's, so there was nothing to judge by.
    coverage_satisfied: bool | None = None
    second_pass: bool = False
    context_cap: int = 0
    duplicate_hits: int = 0
    graph_expanded: bool = False
    steps: list[RetrievalStep] = field(default_factory=list)
    #: Which reranker scored the passages ("cohere", "llm_window", "none"). The
    #: two score on different scales and one threshold is applied to both.
    reranker: str | None = None


@dataclass
class RetrievedContext:
    """Everything the composition step needs, produced by the retrieval pipeline."""

    context_block: str
    passages: list[Passage]
    has_contradiction: bool
    # What the corpus disputes, one sentence per disagreement, in the subject's
    # terms. Defaulted so every existing constructor call stays valid.
    contradiction_points: list[str] = field(default_factory=list)
    # Optional so every existing constructor call stays valid; the streaming
    # path always populates it.
    trail: RetrievalTrail | None = None
    # The planner's read of the question, carried through to composition so the
    # answer is shaped for the person who asked. Optional for the same reason as
    # `trail`; composition falls back to neutral shaping when it is absent.
    plan: QueryPlan | None = None
    # How much the passages support an answer: "strong", "partial" or "thin"
    # (see `evidence_strength`). None when nothing scored relevance.
    evidence: str | None = None


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


def _contradiction_block(points: list[str]) -> str:
    """The heads-up, with what is actually in dispute where the graph knows it.

    A bare flag tells the model that something is contested and leaves it to
    guess what — which is how an answer ends up hedging the wrong sentence. Each
    point is one sentence about the subject, written at extraction time under
    the same rule the note restates: name the dispute, never the bibliography.
    """
    stated = "\n".join(f"  • {p}" for p in points[:3])
    return (
        f"{_CONTRADICTION_NOTE}\n\nWhat is disputed:\n{stated}" if stated else _CONTRADICTION_NOTE
    )


EVIDENCE_STRONG = "strong"
EVIDENCE_PARTIAL = "partial"
EVIDENCE_THIN = "thin"

# Reranker scores at which evidence reads as thin or strong. From the 2026-09-19
# head-to-head: every answer whose best passage scored under 0.2 (death 0.14,
# king 0.15, first winter 0.15) lost, written to full length from three to six
# tangential passages; every answer at 0.6 or above had the text in hand.
_EVIDENCE_THIN_TOP = 0.2
_EVIDENCE_STRONG_TOP = 0.45
# Passages near the best one that make the evidence more than a single hit.
_EVIDENCE_STRONG_MIN = 3


def evidence_strength(scores: list[float], part_uncovered: bool = False) -> str:
    """How far the searched passages in the prompt support an answer.

    ``scores`` are the reranker's, for the passages the prompt carries (not
    neighbours, which nothing scored). ``part_uncovered`` means a subquery won
    nothing on its own and was seated regardless — a part of the question the
    evidence reaches only through its best leftovers.
    """
    top = max(scores, default=0.0)
    if top < _EVIDENCE_THIN_TOP:
        return EVIDENCE_THIN
    near = sum(1 for s in scores if s >= relevance_threshold(scores))
    if top < _EVIDENCE_STRONG_TOP or near < _EVIDENCE_STRONG_MIN or part_uncovered:
        return EVIDENCE_PARTIAL
    return EVIDENCE_STRONG


# What the model is told about the evidence. Nothing for strong evidence: the
# contract already says what to do with passages that answer the question. The
# other two exist because the contract had two settings — answer from the
# passages, or say they hold nothing — and most weak retrieval is neither:
# three tangential passages are not nothing, so the model answered, and nothing
# told it the evidence was thin, so it wrote 5,000 characters from them.
# Worded as conditions, not phrases: any quotable line in a prompt comes back
# as a heading.
_EVIDENCE_NOTES: dict[str, str] = {
    EVIDENCE_PARTIAL: (
        "Evidence: partial. These passages establish some of what a full answer "
        "to this question covers, not all of it. Answer from what they establish, "
        "citing it. Where a part of a full answer is beyond them, say so in one "
        "plain sentence at the point it arises, give brief general background if "
        "it genuinely helps (marked as such, uncited), and move on — never stretch "
        "a passage to cover a part it does not address."
    ),
    EVIDENCE_THIN: (
        "Evidence: thin. These passages only touch the edges of this question. "
        "Keep the answer short. First say what the passages do establish that "
        "bears on the question, cited, and no more than they say. Then add one "
        "brief paragraph of general background that answers the question as "
        "asked, opening with a plain statement that it is general background "
        "rather than something this expert's sources establish, and carrying no "
        "citations. Length follows evidence: a few short paragraphs at most."
    ),
}


def build_user_message(
    question: str,
    context_block: str,
    plan: QueryPlan | None = None,
    has_contradiction: bool = False,
    contradiction_points: list[str] | None = None,
    evidence: str | None = None,
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
    contradiction = (
        f"{_contradiction_block(contradiction_points or [])}\n\n" if has_contradiction else ""
    )
    note = _EVIDENCE_NOTES.get(evidence or "")
    strength = f"{note}\n\n" if note else ""
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
            f"{strength}"
            f"Question: {question}\n\n"
            f"{plan.shaping_block()}"
        ),
    }


# Models that think adaptively — and, for Sonnet 5 and later, by default when
# the request says nothing. Everything else takes the plain request.
_ADAPTIVE_THINKING_PREFIXES = (
    "claude-sonnet-5",
    "claude-opus-5",
    "claude-fable",
    "claude-mythos",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
)


#: Question types that ask for synthesis rather than one thing explained.
BROAD_QUESTION_TYPES = frozenset({"comparison", "orientation", "open_ended"})


def composition_params(
    model: str, max_answer_tokens: int, question_type: str | None = None
) -> dict[str, Any]:
    """``max_tokens``, ``thinking`` and ``output_config`` for composing an answer.

    ``max_answer_tokens`` is the tier's answer length. It used to be sent as the
    request's whole ``max_tokens``, which was right when the model did not think.
    Claude Sonnet 5 thinks unless told otherwise, the thinking is hidden, and
    thinking tokens count against ``max_tokens``: a question like "What is the end
    of man?" spent all 2,048 tokens of a STANDARD answer thinking, produced no
    text at all, and the conversation stored the question with no answer — every
    first question, on every expert, looked like a dropped connection.

    So the thinking is stated rather than defaulted: adaptive, at the effort
    ``CHAT_EFFORT`` names (a grounded answer from retrieved passages does not
    need deep reasoning, and a long silence before the first token is the
    visible cost of it), with ``CHAT_THINKING_HEADROOM_TOKENS`` added on top of
    the answer's own length so thinking can never consume it.
    """
    if not model.startswith(_ADAPTIVE_THINKING_PREFIXES):
        return {"max_tokens": max_answer_tokens}
    return {
        "max_tokens": max_answer_tokens + max(0, settings.CHAT_THINKING_HEADROOM_TOKENS),
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": _effort(question_type)},
    }


def _effort(question_type: str | None) -> str:
    if settings.CHAT_BROAD_EFFORT and question_type in BROAD_QUESTION_TYPES:
        return settings.CHAT_BROAD_EFFORT
    return settings.CHAT_EFFORT


def build_cached_system(persona_style: str | None, topic: str) -> list[TextBlockParam]:
    """System prompt as a block list with a prompt-cache breakpoint.

    The persona prompt is byte-identical across every turn (and every
    conversation) with the same expert, so follow-up requests read it from the
    prompt cache at ~0.1× input price once it clears the model's minimum
    cacheable prefix.
    """
    return [
        {
            "type": "text",
            "text": build_system_prompt(persona_style, topic),
            "cache_control": {"type": "ephemeral"},
        }
    ]


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
    contradiction_points: list[str] | None = None,
    evidence: str | None = None,
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
    trimmed = list(history[_trim_start(len(history)) :])
    while trimmed and trimmed[0].get("role") != "user":
        trimmed.pop(0)

    # `history` arrives as untyped dicts (request body or Postgres), so its
    # role/content shape is validated at the API boundary, not by the type system.
    messages: list[MessageParam] = [cast(MessageParam, dict(m)) for m in trimmed]
    if messages:
        last = messages[-1]
        content = last.get("content")
        if isinstance(content, str) and content.strip():
            last["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
    messages.append(
        build_user_message(
            question, context_block, plan, has_contradiction, contradiction_points, evidence
        )
    )
    return messages


def _dedupe(values) -> list[str]:
    """Order-preserving dedupe — two passages often carry the same dispute."""
    seen: list[str] = []
    for v in values:
        if v not in seen:
            seen.append(v)
    return seen


def _build_trail(
    enriched: list,
    primary_count: int,
    subqueries: list[str],
    followup_queries: list[str],
    coverage_satisfied: bool | None,
    context_cap: int,
    neighbours: list | None = None,
    seats: list | None = None,
    reranker: str | None = None,
    routed: list | None = None,
    swapped: list | None = None,
) -> RetrievalTrail:
    """Record every retrieved passage once, in retrieval order.

    A chunk can be returned by both retrieval passes; ``build_grounded_context``
    de-duplicates it down to a single numbered passage, so the trail keeps the
    first occurrence and counts the rest as duplicate hits. Passages the
    relevance floor kept out of the prompt stay in the trail, in their retrieval
    position — the audit resolves each step to its passage number by chunk id.

    ``neighbours`` follow, marked as such: no query found them and no reranker
    scored them, and a reader asking how a passage reached the answer should be
    told it came along with the one beside it. A neighbour a search had already
    found keeps the step — and the score — it was found with.
    """
    steps: list[RetrievalStep] = []
    seen: set[int] = set()
    duplicates = 0
    graph_expanded = False

    searched = [
        (e, "primary" if i < primary_count else "coverage_followup") for i, e in enumerate(enriched)
    ]
    for e, via in [
        *searched,
        *((n, "subquery_seat") for n in seats or []),
        *((n, "section_route") for n in routed or []),
        *((n, "source_diversity") for n in swapped or []),
        *((n, "neighbour") for n in neighbours or []),
    ]:
        if e.related_concepts or e.relationships:
            graph_expanded = True
        chunk_id = e.result.chunk_id
        if chunk_id in seen:
            # The same chunk from a second query is a duplicate hit; a neighbour
            # a query had already found is not a hit at all.
            duplicates += via != "neighbour"
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
                via=via,
            )
        )

    return RetrievalTrail(
        subqueries=list(subqueries),
        followup_queries=list(followup_queries),
        coverage_satisfied=coverage_satisfied,
        second_pass=bool(followup_queries),
        context_cap=context_cap,
        duplicate_hits=duplicates,
        graph_expanded=graph_expanded,
        steps=steps,
        reranker=reranker,
    )


def relevance_threshold(scores: list[float]) -> float:
    """The score a passage must reach to be kept, relative to this question.

    ``RELEVANCE_RELATIVE`` × the best score, never under ``RELEVANCE_FLOOR``.
    Reranker scores are not comparable across questions — top scores in the
    audit trail run from 0.10 to 0.86, and an evaluative question ("who was
    the most impactful king?") has no passage that answers it, so everything
    it retrieves scores low. An absolute floor gave exactly those questions the
    fewest passages.
    """
    top = max(scores, default=0.0)
    return max(settings.RELEVANCE_FLOOR, settings.RELEVANCE_RELATIVE * top)


def min_kept(max_context_passages: int) -> int:
    """How many passages are kept whatever they score — scaled to the tier."""
    return max(settings.RELEVANCE_MIN_PASSAGES, max_context_passages // 2)


def retrieval_is_weak(scores: list[float]) -> bool:
    """Whether retrieval found too little: what runs the second pass.

    Separate from what is kept. The best passage scoring under
    ``RELEVANCE_WEAK_TOP``, or fewer than ``RELEVANCE_MIN_STRONG`` passages
    clearing the relative floor, means the question was not answered by what
    the first search found.
    """
    if not scores:
        return True
    threshold = relevance_threshold(scores)
    strong = sum(1 for s in scores if s >= threshold)
    return max(scores) < settings.RELEVANCE_WEAK_TOP or strong < settings.RELEVANCE_MIN_STRONG


def apply_relevance_floor(
    enriched: list,
    scored: list[bool],
    floor: float,
    min_keep: int,
) -> list:
    """Drop passages a reranker judged irrelevant, keeping at least ``min_keep``.

    ``scored[i]`` says whether ``enriched[i]``'s score is a reranker's; an
    unscored passage is never dropped, since an RRF score says nothing about
    relevance. Retrieval order is preserved. When too few clear the floor, the
    best-ranked of the rest are kept to make up ``min_keep`` unique chunks — a
    hard question with weak evidence still gets something to reason from, and
    the evidence-strength note tells the model how little it is.

    ``floor`` is the question's own threshold (:func:`relevance_threshold`).
    """
    keep = [not s or e.result.score >= floor for e, s in zip(enriched, scored, strict=True)]
    kept_chunks = {e.result.chunk_id for e, k in zip(enriched, keep, strict=True) if k}
    if len(kept_chunks) < min_keep:
        # Best score first: a follow-up pass appends its passages after the
        # first pass's, so retrieval order is not rank order across passes.
        for i in sorted(range(len(enriched)), key=lambda i: -enriched[i].result.score):
            if len(kept_chunks) >= min_keep:
                break
            if not keep[i]:
                keep[i] = True
                kept_chunks.add(enriched[i].result.chunk_id)
    return [e for e, k in zip(enriched, keep, strict=True) if k]


def diversify(
    retrieved: list,
    neighbours: list,
    fixed: list,
    candidates: list,
    threshold: float,
    protected: set[int] | None = None,
) -> tuple[list, list, list]:
    """Swap a dominant source's weakest passages for other sources' good ones.

    While one source holds more than half of the prompt — neighbours counted
    toward the source they came from — and another source has a candidate
    scoring at least ``threshold`` that is not in the prompt, the dominant
    source gives up a seat: its last neighbour first (neighbours arrive best
    anchor first, so that is the text around its weakest anchor), then its
    lowest-scored retrieved passage. Seats and routed sections (``fixed``) and
    the chunk ids in ``protected`` are never given up.

    ``candidates`` are the reranker's scored ``SearchResult``s, best first.
    Returns ``(retrieved, neighbours, to_add)``; ``to_add`` still needs graph
    expansion.
    """
    retrieved, neighbours = list(retrieved), list(neighbours)
    keep = protected or set()
    in_prompt = {e.result.chunk_id for e in [*retrieved, *neighbours, *fixed]}
    held_shingles = [shingles(e.text) for e in [*retrieved, *fixed]]
    pool = [
        c
        for c in candidates
        if c.score >= threshold and c.chunk_id not in in_prompt and is_prose(c.text)
    ]
    to_add: list = []
    for _ in range(len(retrieved) + len(neighbours)):
        counts = Counter(e.result.source_id for e in [*retrieved, *neighbours, *fixed])
        counts.update(r.source_id for r in to_add)
        source, n = counts.most_common(1)[0] if counts else (None, 0)
        if n * 2 <= sum(counts.values()):
            break
        alternative = next(
            (
                c
                for c in pool
                if c.source_id != source
                and not any(near_duplicate(shingles(c.text), sh) for sh in held_shingles)
            ),
            None,
        )
        if alternative is None:
            break
        mine = [
            e for e in neighbours if e.result.source_id == source and e.result.chunk_id not in keep
        ]
        theirs = [
            e for e in retrieved if e.result.source_id == source and e.result.chunk_id not in keep
        ]
        if mine:
            neighbours.remove(mine[-1])
        elif theirs and sum(e.result.source_id == source for e in retrieved) > 1:
            retrieved.remove(min(theirs, key=lambda e: e.result.score))
        else:
            break
        pool.remove(alternative)
        to_add.append(alternative)
        held_shingles.append(shingles(alternative.text))
    return retrieved, neighbours, to_add


# A subquery counts as represented when one of its first five hits is in the
# context; its seats are the reranker's best of its first ten.
_SUBQUERY_COVERED_WITHIN = 5
_SUBQUERY_SEAT_POOL = 10


def uncovered_subquery_seats(
    subqueries: list[str],
    per_query: dict[str, list[int]],
    candidates: list,
    held: set[int],
    per_subquery: int = 2,
) -> list:
    """The best passages of each subquery that has none in the context.

    A two-part question — "why is God simple, and what is the strongest
    objection?" — was retrieved as one: fusion and a single rerank against the
    whole question gave all twenty seats to the first half, and Plantinga and
    modal collapse, both in the corpus, never reached the prompt. So a subquery
    whose hits won nothing gets its own best ``per_subquery``, in the
    reranker's order, exempt from the floor: it is the planner's statement
    that this part of the question exists.

    ``candidates`` is the reranker's scored list (best first); a subquery's
    hits are found in it by chunk id.
    """
    by_id = {c.chunk_id: c for c in candidates}
    rank = {c.chunk_id: i for i, c in enumerate(candidates)}
    seats: list = []
    taken = set(held)
    for query in subqueries:
        # What the subquery itself found first. Its full list runs to fifty and
        # always brushes the context somewhere; a part of the question is
        # covered when one of its own leading hits is there.
        own = per_query.get(query, [])
        if not own or any(c in held for c in own[:_SUBQUERY_COVERED_WITHIN]):
            continue
        hits = [c for c in own[:_SUBQUERY_SEAT_POOL] if c in by_id]
        best = sorted(hits, key=lambda c: rank[c])
        for chunk_id in [c for c in best if c not in taken][:per_subquery]:
            taken.add(chunk_id)
            seats.append(by_id[chunk_id])
    return seats


def _unique_chunks(enriched: list, cap: int) -> list:
    """The first ``cap`` distinct passages, in order.

    A chunk both retrieval passes returned is one passage. So is the same text
    held twice: expert 63 holds question 3 of the Prima Pars four times (the
    Gutenberg volume, New Advent, archive.org, quoted through the SEP) and *De
    ente et essentia* twice, and each copy took a seat. A later passage mostly
    contained in an earlier one from another source is dropped.
    """
    unique: list = []
    seen: set[int] = set()
    kept_shingles: list[tuple[int, set]] = []
    for e in enriched:
        if e.result.chunk_id in seen:
            continue
        seen.add(e.result.chunk_id)
        mine = shingles(e.text)
        if any(
            source != e.result.source_id and near_duplicate(mine, theirs)
            for source, theirs in kept_shingles
        ):
            continue
        kept_shingles.append((e.result.source_id, mine))
        unique.append(e)
        if len(unique) >= cap:
            break
    return unique


def _conversation_block(history: list[dict] | None) -> str:
    """The last exchange, trimmed, for the planner to resolve references against."""
    if not history:
        return ""
    lines: list[str] = []
    for message in history[-2:]:
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _message_text(message.get("content")).strip()
        if not text:
            continue
        if len(text) > _PLAN_HISTORY_CHARS:
            text = text[:_PLAN_HISTORY_CHARS].rsplit(" ", 1)[0] + " …"
        lines.append(f"{'User' if role == 'user' else 'Expert'}: {text}")
    return "\n".join(lines)


def _message_text(content: Any) -> str:
    """Text of a message whose content is a string or a list of blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


async def _plan_call(client: Any, request: dict[str, Any]) -> dict | None:
    """The planner's tool input, with one retry.

    The SDK already retries a 5xx, and a planner call still failed with a
    provider 500 in the head-to-head run — whereupon the turn ran on the
    one-query fallback plan, as a user's would have. One more attempt, after a
    pause, on a provider error or a response with no plan in it, is cheap next
    to answering a question on the question alone.
    """
    for attempt in range(2):
        try:
            resp = await client.messages.create(**request)
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            status = getattr(exc, "status_code", None)
            if attempt or (status is not None and status < 500):
                raise
            logger.warning("Planner call failed (%s); retrying once", exc)
            await asyncio.sleep(_PLAN_RETRY_DELAY)
            continue
        block = tool_input(resp)
        if block is not None or attempt:
            return block
        logger.warning("Planner returned no plan; retrying once")
    return None


_PLAN_RETRY_DELAY = 1.0


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
        history: list[dict] | None = None,
    ) -> AsyncIterator[RetrieveEvent]:
        """Run the full retrieval pipeline, yielding status updates along the way.

        ``history`` is the conversation so far; only its last exchange is used,
        to plan a follow-up question on what it refers to.

        The final yielded item is always ``("context", RetrievedContext)``.
        """
        cfg = expert.config

        # 1. Plan subqueries, and read who is asking for what
        yield ("status", "Planning search queries…")
        plan = await self._plan(
            question, expert.topic, cfg.max_subqueries, history, expert.key_concepts
        )
        subqueries = plan.subqueries
        # A follow-up is searched and reranked as the question it stands for.
        search_question = plan.standalone_question or question

        # 2. Parallel hybrid search (the subqueries plus the question itself)
        noun = "query" if len(subqueries) == 1 else "queries"
        yield ("status", f"Searching knowledge base across {len(subqueries)} {noun}…")
        search_resp = await self._search.batch_search(
            expert_id=expert.id,
            question=search_question,
            queries=subqueries,
            top_k=cfg.retrieval_top_k,
            topic=expert.topic,
        )

        # 3. Graph expansion
        yield ("status", "Expanding knowledge graph…")
        enriched = await self._graph.expand(search_resp.results, expert.id, hops=cfg.graph_hops)
        scored = [search_resp.reranked] * len(enriched)
        reranked = search_resp.reranked
        reranker = search_resp.reranker
        candidates = list(search_resp.candidates)
        per_query = dict(search_resp.per_query)

        # 4. Is retrieval weak? The reranker has scored every passage against
        # the question; a low best score, or too few passages near it, means
        # the first search missed — and only then does the second pass run, on
        # the planner's fallback phrasings, which come at the question from
        # another angle. This replaced an LLM judge that read 600-char previews
        # on every turn and whose follow-ups paraphrased the first set.
        #
        # Everything retrieved so far came from the planned subqueries; anything
        # appended below came from the follow-up. Tracking the boundary here is
        # what lets the trail say which pass produced each passage.
        primary_count = len(enriched)
        followup_queries: list[str] = []
        coverage_satisfied: bool | None = None
        if reranked:
            coverage_satisfied = not retrieval_is_weak([r.score for r in search_resp.results])

        if coverage_satisfied is False and plan.fallback_queries:
            yield ("status", "Retrieving additional context…")
            followup_queries = plan.fallback_queries[: max(1, cfg.max_subqueries // 2)]
            extra_resp = await self._search.batch_search(
                expert_id=expert.id,
                question=search_question,
                queries=followup_queries,
                top_k=cfg.coverage_extra_k,
                include_question=False,
                topic=expert.topic,
            )
            extra_enriched = await self._graph.expand(
                extra_resp.results, expert.id, hops=cfg.graph_hops
            )
            enriched = enriched + extra_enriched
            scored = scored + [extra_resp.reranked] * len(extra_enriched)
            candidates += extra_resp.candidates
            per_query.update(extra_resp.per_query)
            if not reranked and extra_resp.reranked:
                reranker = extra_resp.reranker

        # 5. What retrieval contributes to the prompt: passages under this
        # question's threshold removed, one entry per chunk, capped at the
        # tier's limit.
        scores = [e.result.score for e, s in zip(enriched, scored, strict=True) if s]
        threshold = relevance_threshold(scores) if scores else 0.0
        retrieved = _unique_chunks(
            apply_relevance_floor(enriched, scored, threshold, min_kept(cfg.max_context_passages)),
            cfg.max_context_passages,
        )

        # 5b. Every part of the question gets a seat: a subquery none of whose
        # own leading hits made it in brings its best two, floor or no floor.
        seats: list[EnrichedResult] = []
        if reranked and candidates:
            ranked_candidates = sorted(candidates, key=lambda r: r.score, reverse=True)
            seat_hits = uncovered_subquery_seats(
                subqueries,
                per_query,
                ranked_candidates,
                {e.result.chunk_id for e in retrieved},
            )
            if seat_hits:
                seats = await self._graph.expand(seat_hits, expert.id, hops=cfg.graph_hops)

        # 6. The best of those bring the text either side of them, so an
        # argument that runs across several chunks arrives as an argument.
        # Anchors are chosen by rank, not by clearing a floor: on a question
        # where everything scores low, the best passage still has context
        # worth reading. Neighbours fill what is left of the cap after the
        # retrieved passages and the subqueries' seats.
        anchor_count = min(settings.NEIGHBOUR_ANCHORS, cfg.retrieval_top_k // 2)
        neighbour_cap = max(0, anchor_count) * (
            settings.NEIGHBOUR_BEFORE + settings.NEIGHBOUR_AFTER
        )
        context_cap = cfg.max_context_passages + neighbour_cap

        # 5c. A broad question — who mattered most, how did this change, what
        # are the positions — is also routed through the section summaries
        # (ingestion/summaries.py): the best sections across distinct sources
        # each seat their passages nearest the question. The reranker scored
        # every chunk against a question no chunk answers; the summaries say
        # which parts of which works are about it.
        routed: list[EnrichedResult] = []
        if plan.question_type in BROAD_QUESTION_TYPES and search_resp.query_embeddings:
            routed = await self._route_sections(
                expert, search_resp.query_embeddings, search_question, retrieved + seats
            )

        held = retrieved + seats + routed
        room = max(0, context_cap - len(held))
        neighbours: list[EnrichedResult] = []
        if neighbour_cap and room:
            yield ("status", "Reading around the strongest passages…")
            by_rank = (
                sorted(retrieved, key=lambda e: e.result.score, reverse=True)
                if reranked
                else retrieved
            )
            neighbours = await self._neighbours(expert, by_rank[:anchor_count], held, room)

        # 6b. No source takes more than half the prompt while another source
        # has a passage near the best one. Retrieval measured 2.5 sources in
        # context and 1.4 cited per answer, for experts built from 18–33.
        swapped: list[EnrichedResult] = []
        by_rank = sorted(retrieved, key=lambda e: e.result.score, reverse=True)
        if reranked and candidates:
            top = by_rank[0] if by_rank else None
            reach = max(settings.NEIGHBOUR_BEFORE, settings.NEIGHBOUR_AFTER)
            retrieved, neighbours, swap_in = diversify(
                retrieved,
                neighbours,
                fixed=seats + routed,
                candidates=sorted(candidates, key=lambda r: r.score, reverse=True),
                threshold=threshold,
                # The best passage and its own run are never given up: seven
                # consecutive chunks of the First Way are why a held question
                # wins.
                protected={
                    e.result.chunk_id
                    for e in [*retrieved, *neighbours]
                    if top is not None
                    and e.result.source_id == top.result.source_id
                    and abs(e.result.sequence_n - top.result.sequence_n) <= reach
                },
            )
            if swap_in:
                swapped = await self._graph.expand(swap_in, expert.id, hops=cfg.graph_hops)
                retrieved = retrieved + swapped
            held = retrieved + seats + routed

        # 7. Numbered context block, in reading order
        yield ("status", "Composing response…")
        in_context = reading_order(held, neighbours)
        context_block, indexed = build_grounded_context(in_context, context_cap)
        trail = _build_trail(
            enriched=enriched,
            primary_count=primary_count,
            subqueries=subqueries,
            followup_queries=followup_queries,
            coverage_satisfied=coverage_satisfied,
            context_cap=context_cap,
            neighbours=neighbours,
            seats=seats,
            routed=routed,
            swapped=swapped,
            reranker=reranker,
        )
        shown = {p.chunk_id for p in indexed}
        searched_scores = [e.result.score for e in retrieved + seats if e.result.chunk_id in shown]
        yield (
            "context",
            RetrievedContext(
                context_block=context_block,
                passages=indexed,
                # What the prompt carries, so only the passages it carries count.
                has_contradiction=any(
                    e.has_contradiction for e in in_context if e.result.chunk_id in shown
                ),
                contradiction_points=_dedupe(
                    p
                    for e in in_context
                    if e.result.chunk_id in shown
                    for p in e.contradiction_points
                ),
                trail=trail,
                plan=plan,
                evidence=(evidence_strength(searched_scores, bool(seats)) if reranked else None),
            ),
        )

    async def _neighbours(
        self,
        expert: Expert,
        anchors: list[EnrichedResult],
        retrieved: list[EnrichedResult],
        limit: int | None = None,
    ) -> list[EnrichedResult]:
        """The chunks either side of ``anchors`` — see ``chat/neighbours.py``.

        At most ``limit``, nearest the best anchor first. A neighbour that is
        not prose (``ingestion/quality.py``) is dropped: two of the three that
        joined the king question's passages were a page of textual apparatus
        and a paragraph of Old English.

        Graph-expanded like any other passage: a neighbour is numbered and
        citable, so it carries its concepts and its disputes the same way. A
        failure here costs the answer nothing it had before, so it degrades to
        no neighbours rather than raising.
        """
        wanted = wanted_positions(
            anchors,
            {position(e) for e in retrieved},
            settings.NEIGHBOUR_BEFORE,
            settings.NEIGHBOUR_AFTER,
        )
        if limit is not None:
            wanted = wanted[:limit]
        if not wanted:
            return []
        try:
            found = await self._search.fetch_by_position(expert.id, wanted)
            # In the order asked for — best anchor first — which is the order
            # `diversify` gives neighbours up in reverse.
            order = {pos: i for i, pos in enumerate(wanted)}
            found.sort(key=lambda r: order.get((r.source_id, r.sequence_n), len(order)))
            held = [(e.result.source_id, shingles(e.text)) for e in retrieved]
            found = [
                r
                for r in found
                if is_prose(r.text)
                and not any(
                    source != r.source_id and near_duplicate(shingles(r.text), theirs)
                    for source, theirs in held
                )
            ]
            return await self._graph.expand(found, expert.id, hops=expert.config.graph_hops)
        except Exception as exc:
            logger.warning("Neighbour expansion failed: %s", exc)
            return []

    async def _route_sections(
        self,
        expert: Expert,
        query_embeddings: dict[str, list[float]],
        question: str,
        held: list[EnrichedResult],
    ) -> list[EnrichedResult]:
        """Passages from the sections whose summaries best match a broad question.

        One section per source, ``SECTION_ROUTE_K`` sources, skipping a section
        the prompt already draws on; each brings its ``SECTION_ROUTE_PASSAGES``
        chunks nearest the question. Best-effort: an expert built before the
        index existed, or any failure, routes nothing.
        """
        if not settings.SECTION_INDEX_ENABLED or settings.SECTION_ROUTE_K <= 0:
            return []
        try:
            hits = await search_sections(
                self._search._pool,
                expert.id,
                list(query_embeddings.values()),
                settings.SECTION_ROUTE_K * 2,
            )
            positions = {(e.result.source_id, e.result.sequence_n) for e in held}
            spans = [
                (h.source_id, h.seq_start, h.seq_end)
                for h in hits
                if not any(
                    source == h.source_id and h.seq_start <= seq <= h.seq_end
                    for source, seq in positions
                )
            ][: settings.SECTION_ROUTE_K]
            if not spans:
                return []
            anchor = query_embeddings.get(question) or next(iter(query_embeddings.values()))
            found = await self._search.best_in_spans(
                expert.id, spans, anchor, settings.SECTION_ROUTE_PASSAGES
            )
            held_shingles = [shingles(e.text) for e in held]
            chosen = [
                r
                for group in found
                for r in group
                if is_prose(r.text)
                and not any(near_duplicate(shingles(r.text), sh) for sh in held_shingles)
            ]
            return await self._graph.expand(chosen, expert.id, hops=expert.config.graph_hops)
        except Exception as exc:
            logger.warning("Section routing failed: %s", exc)
            return []

    async def gather_context(
        self, expert: Expert, question: str, history: list[dict] | None = None
    ) -> RetrievedContext:
        """Run :meth:`retrieve` discarding status updates."""
        async for kind, payload in self.retrieve(expert, question, history):
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
        ctx = await self.gather_context(expert, question, history)

        client = get_anthropic_client()
        messages = build_composition_messages(
            history,
            question,
            ctx.context_block,
            ctx.plan,
            ctx.has_contradiction,
            ctx.contradiction_points,
            ctx.evidence,
        )
        resp = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            system=build_cached_system(expert.persona_style, expert.topic),
            messages=messages,
            **composition_params(
                settings.CLAUDE_MODEL,
                expert.config.max_response_tokens,
                ctx.plan.question_type if ctx.plan else None,
            ),
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

    async def _plan(
        self,
        question: str,
        topic: str,
        max_subqueries: int = 4,
        history: list[dict] | None = None,
        key_concepts: list[str] | None = None,
    ) -> QueryPlan:
        """Decompose the question for retrieval and read who is asking for what.

        One call on the fast model does both. A failure here must not cost the
        answer, so it degrades to :meth:`QueryPlan.fallback` — the question
        searched verbatim, shaped on neutral defaults — rather than raising.

        The planner sees the last exchange of the conversation. Without it a
        follow-up ("what about the second one?") was decomposed with no idea
        what it referred to, and retrieval searched for the words of the
        reference rather than the thing.

        It also sees ``key_concepts``, what this expert's corpus was built
        around. Without them it plans in the asker's vocabulary, which is rarely
        the sources': asked for "the most tangible proof for God", it searched
        a corpus of Aquinas for "fine-tuning design argument" while "The Five
        Ways" sat in the expert's own concept list.
        """
        try:
            tool = _plan_tool(max_subqueries)
            vocabulary = (
                "\nThis expert's sources are built around these concepts: "
                + "; ".join(key_concepts)
                + ". Where the question touches one, phrase a subquery in that "
                "concept's own terms — the words its sources would use, which "
                "are often not the asker's. Ignore the list where it does not "
                "bear on the question."
                if key_concepts
                else ""
            )

            conversation = _conversation_block(history)
            content = (
                f"Conversation so far:\n{conversation}\n\nQuestion: {question}"
                if conversation
                else f"Question: {question}"
            )

            system = (
                f"You plan answers for a {topic} expert. Three jobs, one call.\n"
                "1. If there is a conversation, resolve what the question refers "
                "to in it, and write the question so it stands alone.\n"
                f"2. Decompose the question into 2–{max_subqueries} declarative "
                "retrieval subqueries — phrases a relevant passage would "
                "contain, not questions — each self-contained, never relying on "
                "the conversation for meaning. Always add one or two fallback "
                "queries that come at it from a broader or neighbouring angle.\n"
                "3. Read the question: how much background the asker has, what "
                "kind of answer would satisfy them, and one imperative sentence "
                "saying what this answer must do. Judge the asker from the "
                "question as written, not from how technical the field is."
                f"{vocabulary}"
            )
            client = get_anthropic_client()
            request: dict[str, Any] = {
                "model": settings.FAST_MODEL,
                "max_tokens": 768,
                "system": system,
                "tools": [tool],
                "tool_choice": ToolChoiceToolParam(type="tool", name="create_plan"),
                "messages": [MessageParam(role="user", content=content)],
            }
            block = await _plan_call(client, request)
            if block is None:
                return QueryPlan.fallback(question)
            return QueryPlan.from_tool_input(dict(block), question, max_subqueries)
        except Exception as exc:
            logger.warning("Planning failed: %s", exc)
            return QueryPlan.fallback(question)
