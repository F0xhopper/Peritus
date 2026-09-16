"""Queries for a later discovery round, written by reading the corpus so far.

Round 0's queries come from the planner, which has read nothing but the topic
string. That is the right way to start and the wrong way to continue: when a
concept comes back empty it is usually because the planner guessed at the
field's vocabulary and guessed wrong — searching "stoic emotional regulation"
where the literature says "apatheia", or "monastic study habits" where it says
"lectio divina". Repeating a blind query in round 1 repeats the miss.

This is pseudo-relevance feedback, the cheapest large gain available in the
loop: take the material the corpus *did* accept, read the terms it actually
uses, and search again in the field's own words. One fast-model call per round.

The fallback when the call fails is the old behaviour — ``f"{topic} {concept}"``
— so a feedback outage costs query quality, never a round.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.coverage import ConceptCoverage
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.sources.domain import ValidatedSource

logger = get_logger(__name__)

# How many accepted sources the model reads before writing queries. Enough to
# see the field's vocabulary, few enough to stay one cheap call.
_DIGEST_SOURCES = 12
_MAX_QUERIES_PER_CONCEPT = 2
_CLAIM_CHARS = 180

_FEEDBACK_TOOL: dict[str, Any] = {
    "name": "write_followup_queries",
    "description": (
        "Write follow-up search queries for the concepts this corpus covers "
        "least well, using the field's own vocabulary as it appears in the "
        "material already accepted."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "concepts": {
                "type": "array",
                "description": "One entry per weak concept, in the order given.",
                "items": {
                    "type": "object",
                    "properties": {
                        "concept": {
                            "type": "string",
                            "description": "The weak concept, copied verbatim from the list.",
                        },
                        "queries": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": _MAX_QUERIES_PER_CONCEPT,
                            "description": (
                                "1–2 search queries for this concept. Use the "
                                "technical terms, named theories, author names "
                                "and venues that the accepted sources actually "
                                "use — not a paraphrase of the concept label. A "
                                "query naming a specific author, work or method "
                                "is worth more than a general one."
                            ),
                        },
                    },
                    "required": ["concept", "queries"],
                },
            },
            "authors": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": (
                    "Names of authors or schools this corpus keeps citing but "
                    "whose own work it does not yet contain. Searched directly."
                ),
            },
        },
        "required": ["concepts"],
    },
}

_SYSTEM = (
    "You are extending the search for a research corpus that is already partly "
    "built. You will be shown the topic, the concepts the corpus covers least "
    "well, and the material it has already accepted.\n\n"
    "Your job is to write better queries than a planner working from the topic "
    "alone could write — because you can see what the field actually calls "
    "things. Read the accepted titles and claims for technical vocabulary, "
    "named theories and frameworks, canonical authors, and the venues this "
    "literature publishes in, and put those terms into the queries.\n\n"
    "Do not restate the concept label as a query. Do not broaden to the topic "
    "in general: these concepts are weak precisely because general queries "
    "already ran and missed them. Prefer a specific, technical, unambiguous "
    "query over a readable one — this is going to a search API, not a person."
)


@dataclass
class Feedback:
    """Queries per weak concept, and the authors the corpus cites and lacks.

    ``authors`` go to the thought-leader search for writing *by* those people,
    not into the concept queries, where raw web search answered an author's name
    with pages about them.
    """

    queries: dict[str, list[str]] = field(default_factory=dict)
    authors: list[str] = field(default_factory=list)


def fallback_queries(topic: str, weakest: list[ConceptCoverage]) -> dict[str, list[str]]:
    """What the loop searches when the feedback call is unavailable."""
    return {c.concept: [f"{topic} {c.concept}"] for c in weakest}


def weak_concepts_block(
    weakest: list[ConceptCoverage],
    concept_shares: list[tuple[str, float]] | None = None,
    *,
    facet_of: dict[str, str] | None = None,
    missing_texts: dict[str, list[str]] | None = None,
    voiceless_figures: list[str] | None = None,
) -> str:
    """The weak concepts as the model reads them, with what each one lacks.

    "primary: none" is said in so many words, and so is where the corpus is
    already heavy. Without both, the round asked for more on a weak concept and
    got a twenty-fifth natural-law paper rather than a primary text on
    metaphysics. The named text a concept is missing is named, the concepts are
    grouped under their facets, and the figures with no work in their own voice
    are listed beside them (docs/plans/syllabus.md, phases 2–4).
    """
    facet_of = facet_of or {}
    missing_texts = missing_texts or {}
    lines = ["Concepts covered least well:"]
    groups: dict[str, list[ConceptCoverage]] = {}
    for c in weakest:
        groups.setdefault(facet_of.get(c.concept, ""), []).append(c)
    for facet, members in groups.items():
        indent = ""
        if facet:
            lines.append(f"Facet: {facet}")
            indent = "  "
        for c in members:
            lines.append(
                f"{indent}- {c.concept} — {c.sources} accepted source(s)"
                + (
                    f", types: {', '.join(sorted(t.value for t in c.source_types))}"
                    if c.source_types
                    else ""
                )
                + (f", tiers: {', '.join(sorted(c.tiers))}" if c.tiers else "")
                + (
                    ", primary: none — find the primary texts themselves"
                    if not c.has_primary
                    else ""
                )
                + (
                    f", named text missing: {'; '.join(missing_texts[c.concept])}"
                    if missing_texts.get(c.concept)
                    else ""
                )
            )
    if voiceless_figures:
        lines.append("")
        lines.append(
            "Figures with no work in their own voice — find writing by them, not about them:"
        )
        lines.extend(f"- {name}" for name in voiceless_figures)
    if concept_shares:
        lines.append("")
        lines.append(
            "Already well represented (share of the corpus) — do not search for more of these:"
        )
        lines.extend(f"- {concept}: {share:.0%}" for concept, share in concept_shares)
    return "\n".join(lines)


def _digest(accepted: list[ValidatedSource]) -> str:
    """The corpus in the model's field of view: titles, claims, concepts covered.

    Ordered by quality so the vocabulary the model reads comes from the corpus's
    best material rather than whatever validated first.
    """
    ranked = sorted(
        accepted,
        key=lambda s: (s.quality_score or 0) + (s.relevance_score or 0),
        reverse=True,
    )[:_DIGEST_SOURCES]
    lines = []
    for source in ranked:
        claims = "; ".join(c[:_CLAIM_CHARS] for c in source.key_claims[:2])
        covered = ", ".join(source.covered_concepts[:4])
        lines.append(
            f"- {source.title} [{source.source_type.value}"
            + (f", covers: {covered}" if covered else "")
            + f"]: {claims}"
        )
    return "\n".join(lines)


async def feedback_queries(
    topic: str,
    weakest: list[ConceptCoverage],
    accepted: list[ValidatedSource],
    concept_shares: list[tuple[str, float]] | None = None,
    *,
    facet_of: dict[str, str] | None = None,
    missing_texts: dict[str, list[str]] | None = None,
    voiceless_figures: list[str] | None = None,
) -> Feedback:
    """Follow-up queries per weak concept. Never raises; falls back on failure.

    ``queries`` always has an entry for every concept in ``weakest``,
    so the caller can build a round's query plan without checking for holes.
    """
    if not weakest:
        return Feedback()
    fallback = fallback_queries(topic, weakest)
    if not accepted:
        return Feedback(fallback)

    weak_block = weak_concepts_block(
        weakest,
        concept_shares,
        facet_of=facet_of,
        missing_texts=missing_texts,
        voiceless_figures=voiceless_figures,
    )

    try:
        client = get_anthropic_client()
        resp = await client.messages.create(  # type: ignore[call-overload]
            model=settings.FAST_MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            tools=[_FEEDBACK_TOOL],
            tool_choice={"type": "tool", "name": "write_followup_queries"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Topic: {topic}\n\n"
                        f"{weak_block}\n\n"
                        f"Sources already accepted:\n{_digest(accepted)}\n\n"
                        "Write follow-up queries for each weak concept."
                    ),
                }
            ],
        )
        block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
        payload = dict(block.input)
    except Exception as exc:
        logger.warning(
            "Feedback query generation failed (%s: %s) — falling back to "
            "topic+concept queries for this round",
            type(exc).__name__,
            exc,
        )
        return Feedback(fallback)

    return _normalise(payload, weakest, fallback)


def _normalise(
    payload: dict,
    weakest: list[ConceptCoverage],
    fallback: dict[str, list[str]],
) -> Feedback:
    """Coerce model output onto the concept list, keeping the fallback for holes.

    Concept names are matched casefold against the canonical list — a model that
    re-spells a concept must not silently create a query for a concept that does
    not exist, since the round's whole purpose is to close *these* gaps.
    """
    canonical = {c.concept.casefold(): c.concept for c in weakest}
    out: dict[str, list[str]] = {}
    for entry in payload.get("concepts") or []:
        if not isinstance(entry, dict):
            continue
        name = canonical.get(str(entry.get("concept", "")).casefold().strip())
        if not name:
            continue
        queries = [
            q.strip() for q in entry.get("queries") or [] if isinstance(q, str) and q.strip()
        ][:_MAX_QUERIES_PER_CONCEPT]
        if queries:
            out[name] = queries

    authors = [a.strip() for a in payload.get("authors") or [] if isinstance(a, str) and a.strip()][
        :5
    ]

    for concept, queries in fallback.items():
        out.setdefault(concept, queries)
    return Feedback(out, authors)


# ── primary texts for concepts that have none ────────────────────────────────

_PRIMARY_TOOL: dict[str, Any] = {
    "name": "name_primary_texts",
    "description": (
        "Name the primary texts in which each listed concept is actually set out, so "
        "they can be looked up by title."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "texts": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "concept": {"type": "string", "description": "Copied verbatim."},
                        "title": {"type": "string"},
                        "author": {"type": "string"},
                        "kind": {"type": "string", "enum": ["text", "book", "paper", "standard"]},
                        "public_domain": {"type": "boolean"},
                        "sections": {
                            "type": "string",
                            "description": (
                                "The numbered parts that set out the concept, in the "
                                "work's own numbering. Empty if short or relevant whole."
                            ),
                        },
                    },
                    "required": ["concept", "title", "kind", "public_domain"],
                },
            }
        },
        "required": ["texts"],
    },
}

_PRIMARY_SYSTEM = (
    "You are finding primary sources for a research corpus. For each concept listed, "
    "name the one or two primary texts — as the definition given defines primary for "
    "this topic — in which the concept is actually set out, and the numbered sections "
    "that set it out when the text is long. Name only works you are confident exist "
    "under that title. The corpus is in English: give the title an English translation "
    "or edition is published under, or the original title when that is how English "
    "editions cite it. Do not name commentaries, textbooks or overviews, and do not "
    "repeat titles already tried. Leave a concept out rather than guess."
)


async def suggest_primary_texts(
    topic: str,
    primary_definition: str,
    concepts: list[str],
    already_tried: list[str],
) -> list[dict]:
    """Primary texts for concepts the corpus has no primary source for. Never raises.

    The feedback round's queries go to search engines, and search engines return
    scholarship *about* a subject far more readily than the subject's own texts:
    a live rebuild's round 1 targeted exactly the concepts lacking a primary
    source and came back with secondary papers. A title can be looked up whole
    and cut to its sections, which a query cannot.
    """
    if not concepts:
        return []
    try:
        client = get_anthropic_client()
        resp = await client.messages.create(  # type: ignore[call-overload]
            model=settings.PLAN_MODEL,
            max_tokens=1500,
            system=_PRIMARY_SYSTEM,
            tools=[_PRIMARY_TOOL],
            tool_choice={"type": "tool", "name": "name_primary_texts"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Topic: {topic}\n\n"
                        "Primary sources for this topic are: "
                        f"{primary_definition or 'the original works, not analysis of them'}\n\n"
                        "Concepts without a primary source:\n"
                        + "\n".join(f"- {c}" for c in concepts)
                        + (
                            "\n\nAlready tried (do not repeat):\n"
                            + "\n".join(f"- {t}" for t in already_tried)
                            if already_tried
                            else ""
                        )
                    ),
                }
            ],
        )
        block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
        raw = block.input.get("texts") or []
    except Exception as exc:
        logger.warning(
            "Primary-text suggestion failed (%s: %s) — the round searches without it",
            type(exc).__name__,
            exc,
        )
        return []

    canonical = {c.casefold(): c for c in concepts}
    tried = {t.casefold() for t in already_tried}
    per_concept: dict[str, int] = {}
    out: list[dict] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        concept = canonical.get(str(entry.get("concept") or "").strip().casefold())
        title = str(entry.get("title") or "").strip()
        if not concept or not title or title.casefold() in tried:
            continue
        per_concept[concept] = per_concept.get(concept, 0) + 1
        if per_concept[concept] > 2:
            continue
        out.append(
            {
                "concept": concept,
                "title": title,
                "author": str(entry.get("author") or "").strip(),
                "kind": entry.get("kind")
                if entry.get("kind") in ("text", "book", "paper", "standard")
                else "book",
                "public_domain": entry.get("public_domain") is True,
                "sections": str(entry.get("sections") or "").strip(),
            }
        )
    return out
