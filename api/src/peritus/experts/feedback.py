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


def fallback_queries(topic: str, weakest: list[ConceptCoverage]) -> dict[str, list[str]]:
    """What the loop searches when the feedback call is unavailable."""
    return {c.concept: [f"{topic} {c.concept}"] for c in weakest}


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
) -> dict[str, list[str]]:
    """Follow-up queries per weak concept. Never raises; falls back on failure.

    The returned mapping always has an entry for every concept in ``weakest``,
    so the caller can build a round's query plan without checking for holes.
    """
    if not weakest:
        return {}
    fallback = fallback_queries(topic, weakest)
    if not accepted:
        return fallback

    weak_block = "\n".join(
        f"- {c.concept} — {c.sources} accepted source(s)"
        + (f", types: {', '.join(sorted(t.value for t in c.source_types))}" if c.source_types else "")
        + (f", tiers: {', '.join(sorted(c.tiers))}" if c.tiers else "")
        for c in weakest
    )

    try:
        client = get_anthropic_client()
        resp = await client.messages.create(  # type: ignore[call-overload]
            model=settings.FAST_MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            tools=[_FEEDBACK_TOOL],
            tool_choice={"type": "tool", "name": "write_followup_queries"},
            messages=[{
                "role": "user",
                "content": (
                    f"Topic: {topic}\n\n"
                    f"Concepts covered least well:\n{weak_block}\n\n"
                    f"Sources already accepted:\n{_digest(accepted)}\n\n"
                    "Write follow-up queries for each weak concept."
                ),
            }],
        )
        block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
        payload = dict(block.input)
    except Exception as exc:
        logger.warning(
            "Feedback query generation failed (%s: %s) — falling back to "
            "topic+concept queries for this round",
            type(exc).__name__, exc,
        )
        return fallback

    return _normalise(payload, weakest, fallback)


def _normalise(
    payload: dict,
    weakest: list[ConceptCoverage],
    fallback: dict[str, list[str]],
) -> dict[str, list[str]]:
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
            q.strip()
            for q in entry.get("queries") or []
            if isinstance(q, str) and q.strip()
        ][:_MAX_QUERIES_PER_CONCEPT]
        if queries:
            out[name] = queries

    authors = [
        a.strip() for a in payload.get("authors") or [] if isinstance(a, str) and a.strip()
    ][:5]
    if authors and out:
        # Author searches belong to a concept so they inherit a home in the
        # query plan; the weakest concept is the one they are most likely to
        # help. They are additional to its own queries, never a replacement.
        first = weakest[0].concept
        out.setdefault(first, [])
        out[first] = out[first] + authors

    for concept, queries in fallback.items():
        out.setdefault(concept, queries)
    return out
