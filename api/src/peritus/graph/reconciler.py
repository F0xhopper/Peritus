"""Cross-source reconciliation — where the relationships between claims are found.

Extraction reads ten consecutive chunks at a time, which is almost always ten
chunks of one source. A disagreement between two sources is invisible from
inside that window, so the pass that ran there could only find one by accident:
seven out of ten `contradicts` edges in the old graph were a source in tension
with itself, or with a node whose provenance could not be determined.

This pass inverts the unit of work. After entity resolution, the claims about a
concept are gathered from every source that made one, and the model is asked, in
one call per concept, which pairs support, contradict or qualify each other —
with the evidence for both sides in front of it, and the source title and type
alongside each claim so a preprint can be weighed against a review. It is
bounded by claims-per-concept rather than chunks-squared, and it is the only
place in the pipeline where a cross-source relationship can be seen at all.
"""

from dataclasses import dataclass, field
from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.graph.domain import (
    CLAIM_RELATIONS,
    EDGE_REQUIRED_PROPERTY,
    coerce_edge_type,
)
from peritus.infrastructure.anthropic_batch import gather_claude_calls

logger = get_logger(__name__)

#: Claims shown per concept. Caps the prompt for a hub concept without capping
#: the pass: the selection below spreads the budget across sources first, so a
#: concept with 200 claims still gets its cross-source pairs looked at.
MAX_CLAIMS_PER_CONCEPT = 24

#: A concept whose claims all come from one source has no cross-source pair to
#: find. Within-source qualification exists, but it is the weakest thing this
#: pass could spend a call on, so the call goes to concepts that span sources.
MIN_SOURCES_PER_CONCEPT = 2

#: Concepts reconciled per build. One model call each, so this is what keeps a
#: 900-concept corpus from turning a bounded pass into an unbounded bill. The
#: budget goes to the concepts whose claims span the most sources, because that
#: is where a disagreement between sources can actually be found.
MAX_CONCEPTS_PER_BUILD = 120


@dataclass
class ClaimRow:
    """One claim, with the source that made it."""
    node_id: int
    label: str
    description: str | None = None
    source_id: int | None = None
    source_title: str | None = None
    source_type: str | None = None

    def render(self, index: int) -> str:
        origin = self.source_title or "unattributed"
        if self.source_type:
            origin = f"{origin}, {self.source_type}"
        body = f"[{index}] {self.label} ({origin})"
        if self.description and self.description.strip() != self.label.strip():
            body += f"\n    {self.description}"
        return body


@dataclass
class ConceptClaims:
    """Every claim the corpus makes about one concept."""
    concept_id: int
    concept_label: str
    claims: list[ClaimRow] = field(default_factory=list)

    @property
    def source_count(self) -> int:
        return len({c.source_id for c in self.claims if c.source_id is not None})


_TOOL: dict[str, Any] = {
    "name": "relate_claims",
    "description": (
        "Record the relationships between claims that different sources make about "
        "the same concept."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_claim": {
                            "type": "integer",
                            "description": "Index of the first claim, as numbered in the list.",
                        },
                        "to_claim": {"type": "integer"},
                        "relation": {
                            "type": "string",
                            "enum": ["contradicts", "supports", "qualifies"],
                            "description": (
                                "contradicts: the two propositions cannot both be true. "
                                "supports: the from-claim asserts the same proposition, or "
                                "reports evidence for it. qualifies: the from-claim narrows "
                                "the to-claim to a condition, population, dose, period or "
                                "scope the to-claim omits."
                            ),
                        },
                        "point": {
                            "type": "string",
                            "description": (
                                "For contradicts only. One sentence naming what is in "
                                "dispute, in the subject's own terms — 'whether Varroa alone "
                                "causes collapse without viral co-infection' — never which "
                                "sources disagree."
                            ),
                        },
                        "condition": {
                            "type": "string",
                            "description": (
                                "For qualifies only. One sentence stating the condition the "
                                "narrower claim adds — 'only in participants with baseline "
                                "LDL above 130'."
                            ),
                        },
                    },
                    "required": ["from_claim", "to_claim", "relation"],
                },
            },
        },
        "required": ["relations"],
    },
}

_SYSTEM = (
    "You compare claims that different sources make about the same concept, and record "
    "only the relationships you can defend from the claims as written.\n\n"
    "contradicts is the strong one: the two propositions cannot both be true. Two claims "
    "that differ in emphasis, scope or subject matter do not contradict — most apparent "
    "disagreement in a literature is qualification, so reach for `qualifies` first and "
    "state the condition. Say what is in dispute, in the subject's terms.\n\n"
    "Two claims from the same source rarely relate in any of these ways; pairs across "
    "sources are what you are here for. Report nothing where nothing holds — an empty "
    "list is a good answer, and a guess is worse than a gap."
)


def _select_claims(claims: list[ClaimRow], limit: int) -> list[ClaimRow]:
    """Take up to ``limit`` claims, spreading them across sources first.

    A concept dominated by one prolific source would otherwise fill the whole
    window with that source's claims, which is the one shape guaranteed to
    produce nothing this pass exists to find.
    """
    by_source: dict[Any, list[ClaimRow]] = {}
    for claim in claims:
        by_source.setdefault(claim.source_id, []).append(claim)

    selected: list[ClaimRow] = []
    round_n = 0
    while len(selected) < limit:
        added = False
        for bucket in by_source.values():
            if round_n < len(bucket):
                selected.append(bucket[round_n])
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        round_n += 1
    return selected


def _params(topic: str, group: ConceptClaims, claims: list[ClaimRow]) -> dict[str, Any]:
    listing = "\n".join(claim.render(i) for i, claim in enumerate(claims))
    return {
        "model": settings.GRAPH_MODEL,
        "max_tokens": 4096,
        "system": _SYSTEM,
        "tools": [_TOOL],
        "tool_choice": {"type": "tool", "name": "relate_claims"},
        "messages": [{
            "role": "user",
            "content": (
                f"Topic: {topic}\n"
                f"Concept: {group.concept_label}\n\n"
                f"Claims the corpus makes about it, one per line:\n\n{listing}"
            ),
        }],
    }


def parse_relations(resp: Any, claims: list[ClaimRow]) -> list[dict]:
    """Turn one model response into relation dicts, dropping what cannot stand.

    Rejected: indices outside the list, a claim related to itself, a relation
    type outside the three, and — the one that matters — a `contradicts` or
    `qualifies` with no stated point or condition. An unstated disagreement is
    the thing this whole surface exists to avoid publishing.
    """
    if resp is None:
        return []
    block = next((b for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
    if block is None:
        return []

    relations: list[dict] = []
    for raw in dict(block.input).get("relations", []):
        edge_type = coerce_edge_type(raw.get("relation"))
        if edge_type not in CLAIM_RELATIONS:
            continue
        try:
            from_i, to_i = int(raw["from_claim"]), int(raw["to_claim"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= from_i < len(claims) and 0 <= to_i < len(claims)) or from_i == to_i:
            continue

        properties: dict[str, Any] = {}
        key = EDGE_REQUIRED_PROPERTY.get(edge_type)
        if key is not None:
            stated = raw.get(key)
            if not isinstance(stated, str) or not stated.strip():
                continue
            properties[key] = stated.strip()

        from_claim, to_claim = claims[from_i], claims[to_i]
        properties["cross_source"] = (
            from_claim.source_id is not None
            and to_claim.source_id is not None
            and from_claim.source_id != to_claim.source_id
        )
        relations.append({
            "from_node_id": from_claim.node_id,
            "to_node_id": to_claim.node_id,
            "edge_type": str(edge_type),
            "properties": properties,
        })
    return relations


async def reconcile_claims(
    topic: str,
    groups: list[ConceptClaims],
    max_claims: int = MAX_CLAIMS_PER_CONCEPT,
    min_sources: int = MIN_SOURCES_PER_CONCEPT,
    max_concepts: int = MAX_CONCEPTS_PER_BUILD,
) -> list[dict]:
    """One call per concept; returns claim-to-claim relations ready to insert."""
    eligible = sorted(
        (g for g in groups if len(g.claims) >= 2 and g.source_count >= min_sources),
        key=lambda g: (-g.source_count, -len(g.claims), g.concept_label),
    )
    if len(eligible) > max_concepts:
        logger.info(
            "Reconciling the %d concepts spanning the most sources, of %d eligible",
            max_concepts, len(eligible),
        )
    planned = [
        (group, _select_claims(group.claims, max_claims))
        for group in eligible[:max_concepts]
    ]
    if not planned:
        return []

    responses = await gather_claude_calls(
        [_params(topic, group, claims) for group, claims in planned],
        live_concurrency=3,
        description="graph-reconcile",
    )

    relations: list[dict] = []
    for (group, claims), resp in zip(planned, responses, strict=True):
        if resp is None:
            logger.warning("Reconciliation failed for concept %r", group.concept_label)
            continue
        try:
            relations.extend(parse_relations(resp, claims))
        except Exception as exc:
            logger.warning(
                "Reconciliation parse failed for concept %r: %s", group.concept_label, exc
            )
    return relations
