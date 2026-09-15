"""Graph retriever — enrich search results with the concepts and disputes local to them."""

from dataclasses import dataclass, field

import asyncpg

from peritus.graph.domain import EdgeType
from peritus.graph.repository import GraphRepository
from peritus.search.domain import SearchResult

# Four labels. Chunks anchor 2.2 concepts on average (p90 5), and before entity
# resolution normalised labels the list of eight was often the same concept in
# four spellings; no eval has shown the list changes an answer.
_MAX_CONCEPTS_PER_RESULT = 4
_MAX_EDGES_PER_RESULT = 5

# The two relations a passage's annotation is worth spending lines on. Both say
# something about the state of the evidence; `supports`, `about` and `part_of`
# are the index the graph is built on, not news about this passage.
_REPORTABLE = (EdgeType.CONTRADICTS, EdgeType.QUALIFIES)


@dataclass
class EnrichedResult:
    result: SearchResult
    related_concepts: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    has_contradiction: bool = False
    #: The stated point of each contradiction touching this passage's claims,
    #: in the subject's terms. Carried separately from the context block so the
    #: prompt can say what is disputed rather than only that something is.
    contradiction_points: list[str] = field(default_factory=list)
    #: The condition each `qualifies` edge attaches to a claim here.
    qualifications: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.result.text

    @property
    def citation(self) -> str:
        return self.result.citation

    def context_block(self) -> str:
        """Formatted context for the chat agent prompt — evidence only.

        Nothing here may instruct the model. The grounding contract tells it the
        passages are reference data and that anything directive inside them is to
        be ignored; an earlier version appended "[Note: a contradicts edge was
        traversed — surface this tension in your answer]" to the passage text,
        which is exactly the thing the contract forbids, and the model obeyed it
        by editorialising about disagreements between its own sources.
        ``has_contradiction`` still propagates — it is handled at the prompt
        level in ``chat/agent.py``, in the subject's terms rather than the
        bibliography's.

        What the graph contributes here is what it can defend: the concepts this
        passage is about, and — where the corpus disputes or narrows one of its
        claims — the point or condition, written as a sentence about the
        subject. The old annotation was graph notation (``A --supports--> B``)
        that the model had to interpret and that no eval ever showed it read.

        The passage is shown whole. It used to be cut at 800 characters while
        the ``[n]`` citation resolved to the full chunk, so the model cited text
        it had never been shown — 39% of retrieved text per answer.

        Concepts are labels only, unless the corpus disputes or qualifies a claim
        here: then the descriptions are what let the model say which sense of a
        term the dispute is about.
        """
        lines = [self.text]
        if self.related_concepts:
            if self.contradiction_points or self.qualifications:
                lines.append("\nAbout:")
                for c in self.related_concepts:
                    desc = (c.get("description") or "").strip()
                    lines.append(f"  • {c['label']}: {desc}" if desc else f"  • {c['label']}")
            else:
                lines.append("\nAbout: " + "; ".join(c["label"] for c in self.related_concepts))
        if self.contradiction_points:
            lines.append("\nDisputed in this corpus:")
            lines.extend(f"  • {point}" for point in self.contradiction_points)
        if self.qualifications:
            lines.append("\nQualified elsewhere in this corpus:")
            lines.extend(f"  • {condition}" for condition in self.qualifications)
        return "\n".join(lines)


class GraphRetriever:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._repo = GraphRepository(pool)

    async def expand(
        self,
        results: list[SearchResult],
        expert_id: int,
        hops: int = 1,
    ) -> list[EnrichedResult]:
        if not results:
            return []

        chunk_ids = [r.chunk_id for r in results]
        anchor_nodes = await self._repo.get_nodes_for_chunks(expert_id, chunk_ids)

        if not anchor_nodes:
            return [EnrichedResult(result=r) for r in results]

        anchor_ids = [n["id"] for n in anchor_nodes]
        # One hop, whatever the tier asks for. `_enrich_one` keeps only edges
        # touching a passage's own anchors, so a second hop was fetched and then
        # discarded on every PRO turn. `hops` stays in the signature because
        # expert configs snapshotted before this still carry `graph_hops=2`.
        neighbour_nodes, edges = await self._repo.get_neighbours(
            expert_id, anchor_ids, min(hops, 1)
        )
        node_by_id = {n["id"]: n for n in neighbour_nodes}

        return [
            self._enrich_one(result, anchor_nodes, edges, node_by_id)
            for result in results
        ]

    def _enrich_one(
        self,
        result: SearchResult,
        anchor_nodes: list[dict],
        edges: list[dict],
        node_by_id: dict[int, dict],
    ) -> EnrichedResult:
        """Enrich a single passage with the concepts and relations local to it,
        rather than one global neighbour list shared by every passage."""
        local_anchor_ids = {
            n["id"] for n in anchor_nodes
            if result.chunk_id in (n.get("chunk_ids") or [])
        }
        local_edges = sorted(
            (
                e for e in edges
                if e["from_node_id"] in local_anchor_ids or e["to_node_id"] in local_anchor_ids
            ),
            # Contradictions and qualifications are what the product surfaces —
            # keep them ahead of the evidence ranking so the cap never hides one.
            key=lambda e: (e["edge_type"] not in _REPORTABLE, -(e["evidence"] or 0)),
        )

        has_contradiction = any(
            e["edge_type"] == EdgeType.CONTRADICTS for e in local_edges
        )
        local_edges = local_edges[:_MAX_EDGES_PER_RESULT]

        # Concepts for this passage: its anchors first, then the neighbours its
        # best-evidenced edges reach, in edge order.
        concept_ids: list[int] = sorted(local_anchor_ids)
        for e in local_edges:
            for nid in (e["from_node_id"], e["to_node_id"]):
                if nid not in concept_ids:
                    concept_ids.append(nid)
        related_concepts = [
            node
            for nid in concept_ids[:_MAX_CONCEPTS_PER_RESULT]
            if (node := node_by_id.get(nid)) is not None
            and node.get("node_type") != "claim"
        ]

        relationships = [
            {
                "from_label": node_by_id.get(e["from_node_id"], {}).get("label", "?"),
                "to_label": node_by_id.get(e["to_node_id"], {}).get("label", "?"),
                "edge_type": e["edge_type"],
                "evidence": e.get("evidence") or 0,
                "properties": e.get("properties") or {},
            }
            for e in local_edges
        ]

        return EnrichedResult(
            result=result,
            related_concepts=related_concepts,
            relationships=relationships,
            has_contradiction=has_contradiction,
            contradiction_points=_stated(local_edges, EdgeType.CONTRADICTS, "point"),
            qualifications=_stated(local_edges, EdgeType.QUALIFIES, "condition"),
        )


def _stated(edges: list[dict], edge_type: EdgeType, key: str) -> list[str]:
    """The point or condition each edge of this type states, deduplicated.

    An edge of either type is rejected at ingest without one, so anything
    reaching here has a sentence to show; the guard is for graphs built before
    that rule existed.
    """
    seen: list[str] = []
    for e in edges:
        if e["edge_type"] != edge_type:
            continue
        stated = (e.get("properties") or {}).get(key)
        if isinstance(stated, str) and stated.strip() and stated.strip() not in seen:
            seen.append(stated.strip())
    return seen
