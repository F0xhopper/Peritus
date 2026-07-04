"""Unit tests for the knowledge-graph pieces that are pure or fakeable:

- merge_node_extractions — cross-batch node dedup policy
- attach_chunk_db_ids — model chunk-index → DB id mapping guard
- GraphRetriever.expand — per-passage enrichment (concepts, relations,
  contradiction flag are local to each passage, not global)
"""

from peritus.graph.extractor import attach_chunk_db_ids
from peritus.graph.repository import merge_node_extractions, node_embedding_text
from peritus.graph.retriever import GraphRetriever
from peritus.search.domain import SearchResult, SourceRef

# --- merge_node_extractions -------------------------------------------------

def _node(label, description="", chunk_db_ids=None, **props):
    return {"label": label, "description": description,
            "chunk_db_ids": chunk_db_ids or [], **props}


def test_merge_dedupes_by_normalised_label():
    merged = merge_node_extractions([
        {"nodes": [_node("Stoicism", chunk_db_ids=[1])]},
        {"nodes": [_node("  stoicism ", chunk_db_ids=[2])]},
    ])
    assert list(merged) == ["stoicism"]
    assert sorted(merged["stoicism"]["chunk_ids"]) == [1, 2]


def test_merge_keeps_longest_description():
    merged = merge_node_extractions([
        {"nodes": [_node("Virtue", description="short")]},
        {"nodes": [_node("virtue", description="a much longer description")]},
        {"nodes": [_node("virtue", description="")]},
    ])
    assert merged["virtue"]["description"] == "a much longer description"


def test_merge_keeps_first_non_null_properties():
    merged = merge_node_extractions([
        {"nodes": [_node("Logos", difficulty=None, confidence=0.9)]},
        {"nodes": [_node("logos", difficulty=3, confidence=0.2)]},
    ])
    props = merged["logos"]["properties"]
    assert props["difficulty"] == 3
    assert props["confidence"] == 0.9


def test_node_embedding_text_includes_description():
    assert node_embedding_text("Java", "programming language") == "Java: programming language"
    assert node_embedding_text("Java", None) == "Java"
    assert node_embedding_text("Java", "") == "Java"


# --- attach_chunk_db_ids ----------------------------------------------------

def test_attach_chunk_db_ids_drops_out_of_range_indices():
    data = {"nodes": [{"label": "A", "chunk_indices": [0, 2, -1, 99, "x"]}]}
    attach_chunk_db_ids(data, [10, 11, 12])
    assert data["nodes"][0]["chunk_db_ids"] == [10, 12]


# --- GraphRetriever.expand ---------------------------------------------------

def _result(chunk_id: int) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        expert_id=1,
        source_id=1,
        text=f"text for chunk {chunk_id}",
        context_text=None,
        score=0.5,
        source_ref=SourceRef(source_id=1, title="T", source_type="web", quality_score=7.0),
    )


class FakeRepo:
    """Two anchors: node 1 (chunk 100) and node 2 (chunk 200). Node 3 is a
    neighbour of node 1 via a contradicts edge; node 2's only edge supports."""

    def __init__(self):
        self.nodes = [
            {"id": 1, "label": "A", "node_type": "concept", "description": "a", "chunk_ids": [100]},
            {"id": 2, "label": "B", "node_type": "concept", "description": "b", "chunk_ids": [200]},
        ]
        self.all_nodes = self.nodes + [
            {"id": 3, "label": "C", "node_type": "claim", "description": "c"},
        ]
        self.edges = [
            {"from_node_id": 1, "to_node_id": 3, "edge_type": "contradicts", "weight": 0.4},
            {"from_node_id": 2, "to_node_id": 3, "edge_type": "supports", "weight": 0.9},
        ]

    async def get_nodes_for_chunks(self, expert_id, chunk_ids):
        return [n for n in self.nodes if set(n["chunk_ids"]) & set(chunk_ids)]

    async def get_neighbours(self, expert_id, node_ids, hops=1):
        return self.all_nodes, self.edges


def _retriever() -> GraphRetriever:
    r = GraphRetriever.__new__(GraphRetriever)
    r._repo = FakeRepo()
    return r


async def test_expand_contradiction_flag_is_per_passage():
    enriched = await _retriever().expand([_result(100), _result(200)], expert_id=1)

    by_chunk = {e.result.chunk_id: e for e in enriched}
    assert by_chunk[100].has_contradiction is True
    assert by_chunk[200].has_contradiction is False


async def test_expand_concepts_are_local_to_each_passage():
    enriched = await _retriever().expand([_result(100), _result(200)], expert_id=1)

    by_chunk = {e.result.chunk_id: e for e in enriched}
    labels_100 = [c["label"] for c in by_chunk[100].related_concepts]
    labels_200 = [c["label"] for c in by_chunk[200].related_concepts]
    # Each passage starts from its own anchor and reaches C via its own edge;
    # neither passage sees the other's anchor.
    assert labels_100 == ["A", "C"]
    assert labels_200 == ["B", "C"]


async def test_expand_relationships_are_local():
    enriched = await _retriever().expand([_result(200)], expert_id=1)

    rels = enriched[0].relationships
    assert len(rels) == 1
    assert rels[0]["from_label"] == "B"
    assert rels[0]["edge_type"] == "supports"


async def test_expand_no_anchor_nodes_returns_bare_results():
    enriched = await _retriever().expand([_result(999)], expert_id=1)
    assert enriched[0].related_concepts == []
    assert enriched[0].has_contradiction is False
