"""Graph retriever — enrich search results with concept neighbor context."""

from dataclasses import dataclass, field

import asyncpg

from peritus.graph.repository import GraphRepository
from peritus.search.domain import SearchResult

_MAX_CONCEPTS_PER_RESULT = 8
_MAX_EDGES_PER_RESULT = 5


@dataclass
class EnrichedResult:
    result: SearchResult
    related_concepts: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    has_contradiction: bool = False

    @property
    def text(self) -> str:
        return self.result.text

    @property
    def citation(self) -> str:
        return self.result.citation

    def context_block(self) -> str:
        """Formatted context for the chat agent prompt."""
        lines = [self.text[:800]]
        if self.related_concepts:
            lines.append("\nRelated concepts:")
            for c in self.related_concepts:
                lines.append(f"  • {c['label']}: {c.get('description', '')}")
        if self.relationships:
            lines.append("\nRelationships:")
            for e in self.relationships:
                lines.append(f"  {e['from_label']} --{e['edge_type']}--> {e['to_label']}")
        if self.has_contradiction:
            lines.append("\n[Note: a contradicts edge was traversed — surface this tension in your answer]")
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
        neighbour_nodes, edges = await self._repo.get_neighbours(expert_id, anchor_ids, hops)
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
            # Contradictions are the signal the product surfaces — keep them
            # ahead of the weight ranking so the cap never hides one.
            key=lambda e: (e["edge_type"] != "contradicts", -e["weight"]),
        )

        has_contradiction = any(e["edge_type"] == "contradicts" for e in local_edges)
        local_edges = local_edges[:_MAX_EDGES_PER_RESULT]

        # Concepts for this passage: its anchors first, then the neighbours its
        # strongest edges reach, in edge order.
        concept_ids: list[int] = sorted(local_anchor_ids)
        for e in local_edges:
            for nid in (e["from_node_id"], e["to_node_id"]):
                if nid not in concept_ids:
                    concept_ids.append(nid)
        related_concepts = [
            node_by_id[nid] for nid in concept_ids[:_MAX_CONCEPTS_PER_RESULT]
            if nid in node_by_id
        ]

        relationships = [
            {
                "from_label": node_by_id.get(e["from_node_id"], {}).get("label", "?"),
                "to_label": node_by_id.get(e["to_node_id"], {}).get("label", "?"),
                "edge_type": e["edge_type"],
                "weight": e["weight"],
            }
            for e in local_edges
        ]

        return EnrichedResult(
            result=result,
            related_concepts=related_concepts,
            relationships=relationships,
            has_contradiction=has_contradiction,
        )
