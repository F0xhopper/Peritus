"""Graph retriever — enrich search results with concept neighbor context."""

from dataclasses import dataclass, field

import asyncpg

from peritus.graph.repository import GraphRepository
from peritus.search.domain import SearchResult


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
        lines = [self.text]
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
        edge_list = [
            {
                "from_label": node_by_id.get(e["from_node_id"], {}).get("label", "?"),
                "to_label": node_by_id.get(e["to_node_id"], {}).get("label", "?"),
                "edge_type": e["edge_type"],
                "weight": e["weight"],
            }
            for e in edges
        ]

        has_contradiction = any(e["edge_type"] == "contradicts" for e in edge_list)

        enriched = []
        for result in results:
            matching_nodes = [
                n for n in anchor_nodes
                if result.chunk_id in (n.get("chunk_ids") or [])
            ]
            node_ids = {n["id"] for n in matching_nodes}
            local_edges = [
                e for e in edge_list
                if any(
                    n["id"] == e_raw["from_node_id"] or n["id"] == e_raw["to_node_id"]
                    for n in matching_nodes
                    for e_raw in edges
                    if e_raw["from_node_id"] in node_ids or e_raw["to_node_id"] in node_ids
                )
            ][:5]

            enriched.append(EnrichedResult(
                result=result,
                related_concepts=list(neighbour_nodes)[:8],
                relationships=local_edges[:5],
                has_contradiction=has_contradiction,
            ))

        return enriched
