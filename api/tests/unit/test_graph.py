"""Unit tests for the knowledge-graph pieces that are pure or fakeable:

- the vocabulary's endpoint rules — which relation is well-formed between which
  kinds of node, the constraint the whole redesign rests on
- merge_node_extractions — cross-batch node dedup policy, and type enforcement
- attach_chunk_db_ids — model chunk-index → DB id mapping guard
- reconciler.parse_relations / _select_claims — the cross-source pass
- GraphRetriever.expand — per-passage enrichment (concepts, disputes and the
  contradiction flag are local to each passage, not global)
"""

from types import SimpleNamespace

from peritus.graph.domain import EdgeType, NodeType, edge_is_valid
from peritus.graph.extractor import attach_chunk_db_ids
from peritus.graph.reconciler import ClaimRow, _select_claims, parse_relations
from peritus.graph.repository import merge_node_extractions, node_embedding_text
from peritus.graph.retriever import GraphRetriever
from peritus.search.domain import SearchResult, SourceRef

# --- the vocabulary ---------------------------------------------------------


def test_claim_relations_require_two_claims():
    """The rule the redesign exists for: two concepts cannot contradict, only
    two propositions can. 45% of the old graph's contradictions were exactly
    this shape."""
    for edge_type in (EdgeType.CONTRADICTS, EdgeType.SUPPORTS, EdgeType.QUALIFIES):
        assert edge_is_valid(edge_type, NodeType.CLAIM, NodeType.CLAIM)
        assert not edge_is_valid(edge_type, NodeType.CONCEPT, NodeType.CONCEPT)
        assert not edge_is_valid(edge_type, NodeType.CLAIM, NodeType.CONCEPT)


def test_about_and_part_of_are_directional():
    assert edge_is_valid(EdgeType.ABOUT, NodeType.CLAIM, NodeType.CONCEPT)
    assert not edge_is_valid(EdgeType.ABOUT, NodeType.CONCEPT, NodeType.CLAIM)
    assert edge_is_valid(EdgeType.PART_OF, NodeType.CONCEPT, NodeType.CONCEPT)
    assert not edge_is_valid(EdgeType.PART_OF, NodeType.CLAIM, NodeType.CONCEPT)


# --- merge_node_extractions -------------------------------------------------


def _node(label, description="", chunk_db_ids=None, node_type="concept", **props):
    return {
        "label": label,
        "description": description,
        "node_type": node_type,
        "chunk_db_ids": chunk_db_ids or [],
        **props,
    }


def test_merge_dedupes_by_normalised_label():
    merged = merge_node_extractions(
        [
            {"nodes": [_node("Stoicism", chunk_db_ids=[1])]},
            {"nodes": [_node("  stoicism ", chunk_db_ids=[2])]},
        ]
    )
    assert list(merged) == ["stoicism"]
    assert sorted(merged["stoicism"]["chunk_ids"]) == [1, 2]


def test_merge_keeps_longest_description():
    merged = merge_node_extractions(
        [
            {"nodes": [_node("Virtue", description="short")]},
            {"nodes": [_node("virtue", description="a much longer description")]},
            {"nodes": [_node("virtue", description="")]},
        ]
    )
    assert merged["virtue"]["description"] == "a much longer description"


def test_merge_keeps_first_non_null_properties():
    merged = merge_node_extractions(
        [
            {"nodes": [_node("Logos", difficulty=None, confidence=0.9)]},
            {"nodes": [_node("logos", difficulty=3, confidence=0.2)]},
        ]
    )
    props = merged["logos"]["properties"]
    assert props["difficulty"] == 3
    assert props["confidence"] == 0.9


def test_merge_drops_nodes_typed_outside_the_enum():
    """The tool schema always declared the enum and nothing enforced it, which
    is how the graph filled up with nodes typed `definition` and `argument`."""
    merged = merge_node_extractions(
        [
            {
                "nodes": [
                    _node("Virtue"),
                    _node("Eudaimonia", node_type="definition"),
                    _node("Akrasia", node_type=None),
                ]
            },
        ]
    )
    assert list(merged) == ["virtue"]


def test_merge_drops_content_type_outside_the_enum():
    """`content_type` picked up edge type names in the same exchange that put
    edge types into `node_type`."""
    merged = merge_node_extractions(
        [
            {"nodes": [_node("Virtue", content_type="supports")]},
            {"nodes": [_node("virtue", content_type="definition")]},
        ]
    )
    assert merged["virtue"]["properties"]["content_type"] == "definition"


def test_node_embedding_text_includes_description():
    assert node_embedding_text("Java", "programming language") == "Java: programming language"
    assert node_embedding_text("Java", None) == "Java"
    assert node_embedding_text("Java", "") == "Java"


# --- attach_chunk_db_ids ----------------------------------------------------


def test_attach_chunk_db_ids_drops_out_of_range_indices():
    data = {"nodes": [{"label": "A", "chunk_indices": [0, 2, -1, 99, "x"]}]}
    attach_chunk_db_ids(data, [10, 11, 12])
    assert data["nodes"][0]["chunk_db_ids"] == [10, 12]


# --- reconciler --------------------------------------------------------------


def _claim(node_id: int, source_id: int) -> ClaimRow:
    return ClaimRow(node_id=node_id, label=f"claim {node_id}", source_id=source_id)


def _response(relations: list[dict]):
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input={"relations": relations})]
    )


def test_select_claims_spreads_the_budget_across_sources():
    """A concept dominated by one prolific source would otherwise fill the
    window with that source, which is the one shape guaranteed to find no
    cross-source relation."""
    claims = [_claim(i, source_id=1) for i in range(10)] + [_claim(99, source_id=2)]
    selected = _select_claims(claims, limit=4)
    assert {c.source_id for c in selected} == {1, 2}


def test_parse_relations_requires_a_stated_point():
    claims = [_claim(1, 1), _claim(2, 2)]
    parsed = parse_relations(
        _response(
            [
                {"from_claim": 0, "to_claim": 1, "relation": "contradicts"},
                {"from_claim": 0, "to_claim": 1, "relation": "contradicts", "point": "  "},
                {
                    "from_claim": 1,
                    "to_claim": 0,
                    "relation": "contradicts",
                    "point": "whether the effect survives co-infection",
                },
            ]
        ),
        claims,
    )

    assert len(parsed) == 1
    assert parsed[0]["from_node_id"] == 2
    assert parsed[0]["properties"]["point"] == "whether the effect survives co-infection"
    assert parsed[0]["properties"]["cross_source"] is True


def test_parse_relations_rejects_bad_indices_and_types():
    claims = [_claim(1, 1), _claim(2, 2)]
    parsed = parse_relations(
        _response(
            [
                {"from_claim": 0, "to_claim": 0, "relation": "supports"},
                {"from_claim": 0, "to_claim": 7, "relation": "supports"},
                {"from_claim": 0, "to_claim": 1, "relation": "builds_on"},
                {"from_claim": 0, "to_claim": 1, "relation": "about"},
            ]
        ),
        claims,
    )
    assert parsed == []


def test_parse_relations_marks_within_source_pairs():
    claims = [_claim(1, 5), _claim(2, 5)]
    parsed = parse_relations(
        _response(
            [
                {"from_claim": 0, "to_claim": 1, "relation": "supports"},
            ]
        ),
        claims,
    )
    assert parsed[0]["properties"]["cross_source"] is False


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
    """Two claim anchors: node 1 (chunk 100) and node 2 (chunk 200). Node 3 is a
    third claim, contradicting node 1 and supported by node 2; node 4 is the
    concept both anchors are about."""

    def __init__(self):
        self.nodes = [
            {"id": 1, "label": "A", "node_type": "claim", "description": "a", "chunk_ids": [100]},
            {"id": 2, "label": "B", "node_type": "claim", "description": "b", "chunk_ids": [200]},
        ]
        self.all_nodes = self.nodes + [
            {"id": 3, "label": "C", "node_type": "claim", "description": "c"},
            {"id": 4, "label": "D", "node_type": "concept", "description": "d"},
        ]
        self.edges = [
            {
                "from_node_id": 1,
                "to_node_id": 3,
                "edge_type": "contradicts",
                "evidence": 1,
                "properties": {"point": "whether D holds without co-infection"},
            },
            {
                "from_node_id": 2,
                "to_node_id": 3,
                "edge_type": "supports",
                "evidence": 3,
                "properties": {},
            },
            {
                "from_node_id": 1,
                "to_node_id": 4,
                "edge_type": "about",
                "evidence": 2,
                "properties": {},
            },
            {
                "from_node_id": 2,
                "to_node_id": 4,
                "edge_type": "about",
                "evidence": 2,
                "properties": {},
            },
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


async def test_expand_lists_concepts_not_claims():
    """The annotation is "what this passage is about". A claim node reached
    through an edge is evidence, not an index entry."""
    enriched = await _retriever().expand([_result(100)], expert_id=1)
    assert [c["label"] for c in enriched[0].related_concepts] == ["D"]


async def test_expand_relationships_are_local():
    enriched = await _retriever().expand([_result(200)], expert_id=1)

    rels = enriched[0].relationships
    assert {r["edge_type"] for r in rels} == {"supports", "about"}
    assert all(r["from_label"] == "B" for r in rels)


async def test_expand_carries_the_stated_point_of_a_contradiction():
    """A bare flag tells the model something is contested and leaves it to guess
    what; the point is the sentence that says."""
    enriched = await _retriever().expand([_result(100), _result(200)], expert_id=1)

    by_chunk = {e.result.chunk_id: e for e in enriched}
    assert by_chunk[100].contradiction_points == ["whether D holds without co-infection"]
    assert by_chunk[200].contradiction_points == []
    assert "whether D holds without co-infection" in by_chunk[100].context_block()


async def test_expand_no_anchor_nodes_returns_bare_results():
    enriched = await _retriever().expand([_result(999)], expert_id=1)
    assert enriched[0].related_concepts == []
    assert enriched[0].has_contradiction is False


# ── malformed tool output ────────────────────────────────────────────────────
#
# Both of these were found on real builds, not by inspection. The tool schema
# asks for an array of objects and a model can still put a bare string in it;
# the code then called `.get` on a str and the exception took the whole batch
# with it — ten chunks' worth of graph, or five sources' worth of validation.


class _Block:
    type = "tool_use"

    def __init__(self, payload: dict) -> None:
        self.input = payload


class _Response:
    def __init__(self, payload: dict) -> None:
        self.content = [_Block(payload)]
        self.stop_reason = "tool_use"


def test_a_string_where_a_node_was_expected_does_not_take_the_batch_with_it():
    from peritus.graph.extractor import _parse_extract_response

    payload = {
        "nodes": [
            {"label": "Analogy", "node_type": "concept", "description": "d"},
            "Participation",  # the model wrote a bare string
            {"label": "Esse", "node_type": "concept", "description": "d"},
        ],
        "edges": [],
    }
    result = _parse_extract_response(_Response(payload), [1, 2])
    assert [n["label"] for n in result["nodes"]] == ["Analogy", "Esse"]


def test_a_string_where_an_edge_was_expected_is_dropped_the_same_way():
    from peritus.graph.extractor import _parse_extract_response

    payload = {
        "nodes": [],
        "edges": [
            {"from_label": "Analogy", "to_label": "Esse", "edge_type": "about"},
            "Analogy -> Esse",
        ],
    }
    result = _parse_extract_response(_Response(payload), [1])
    assert len(result["edges"]) == 1


def test_a_non_list_where_a_list_was_expected_yields_nothing_rather_than_raising():
    from peritus.graph.extractor import _parse_extract_response

    result = _parse_extract_response(_Response({"nodes": "none found", "edges": None}), [1])
    assert result["nodes"] == []
    assert result["edges"] == []


async def test_context_block_shows_the_whole_passage():
    """It used to show text[:800] while the citation resolved to the full chunk."""
    long = SearchResult(
        chunk_id=100,
        expert_id=1,
        source_id=1,
        text="x" * 1400,
        context_text=None,
        score=0.5,
        source_ref=SourceRef(source_id=1, title="T", source_type="web", quality_score=7.0),
    )
    enriched = await _retriever().expand([long], expert_id=1)
    assert "x" * 1400 in enriched[0].context_block()


async def test_concepts_are_labels_only_unless_something_is_disputed():
    enriched = await _retriever().expand([_result(100), _result(200)], expert_id=1)
    by_chunk = {e.result.chunk_id: e for e in enriched}
    # Chunk 200 carries no dispute: the concept is named, not described.
    assert "About: D" in by_chunk[200].context_block()
    assert "D: d" not in by_chunk[200].context_block()
    # Chunk 100's claim is contradicted, so the description is worth its tokens.
    assert "  • D: d" in by_chunk[100].context_block()


async def test_expand_fetches_one_hop_even_when_the_tier_asks_for_two():
    retriever = _retriever()
    seen: list[int] = []
    original = retriever._repo.get_neighbours

    async def spy(expert_id, node_ids, hops=1):
        seen.append(hops)
        return await original(expert_id, node_ids, hops)

    retriever._repo.get_neighbours = spy
    await retriever.expand([_result(100)], expert_id=1, hops=2)
    assert seen == [1]


# ── orphaned claims (R4) ──


def test_orphan_claim_is_attached_to_concepts_sharing_its_chunk():
    from peritus.graph.extractor import attach_orphan_claims

    data = {
        "nodes": [
            {"label": "Varroa suppresses immunity", "node_type": "claim", "chunk_indices": [0]},
            {"label": "Varroa destructor", "node_type": "concept", "chunk_indices": [0, 1]},
            {"label": "Immune response", "node_type": "concept", "chunk_indices": [0]},
            {"label": "Queen rearing", "node_type": "concept", "chunk_indices": [2]},
        ],
        # An `about` edge to a concept this batch never emitted resolves to nothing.
        "edges": [
            {"from_label": "Varroa suppresses immunity", "to_label": "Mites", "edge_type": "about"}
        ],
    }
    assert attach_orphan_claims(data) == 2
    inferred = {(e["from_label"], e["to_label"]) for e in data["edges"][1:]}
    assert inferred == {
        ("Varroa suppresses immunity", "Varroa destructor"),
        ("Varroa suppresses immunity", "Immune response"),
    }


def test_claim_with_a_resolvable_about_edge_is_left_alone():
    from peritus.graph.extractor import attach_orphan_claims

    data = {
        "nodes": [
            {"label": "Varroa suppresses immunity", "node_type": "claim", "chunk_indices": [0]},
            {"label": "varroa destructor", "node_type": "concept", "chunk_indices": [0]},
            {"label": "Immune response", "node_type": "concept", "chunk_indices": [0]},
        ],
        "edges": [
            {
                "from_label": "varroa suppresses immunity",
                "to_label": "Varroa Destructor",
                "edge_type": "about",
            }
        ],
    }
    assert attach_orphan_claims(data) == 0
    assert len(data["edges"]) == 1


def test_orphan_claim_with_no_shared_chunk_stays_orphaned():
    from peritus.graph.extractor import attach_orphan_claims

    data = {
        "nodes": [
            {"label": "A claim", "node_type": "claim", "chunk_indices": [3]},
            {"label": "A concept", "node_type": "concept", "chunk_indices": [0]},
        ],
        "edges": [],
    }
    assert attach_orphan_claims(data) == 0


# ── reconciliation stats (R4) ──


def test_parse_relations_counts_every_rejection_by_reason():
    from collections import Counter
    from types import SimpleNamespace

    from peritus.graph.reconciler import ClaimRow, parse_relations

    claims = [
        ClaimRow(node_id=1, label="a", source_id=1),
        ClaimRow(node_id=2, label="b", source_id=2),
    ]
    block = SimpleNamespace(
        type="tool_use",
        input={
            "relations": [
                {"from_claim": 0, "to_claim": 1, "relation": "contradicts"},  # no point
                {"from_claim": 0, "to_claim": 9, "relation": "supports"},  # out of range
                {"from_claim": 0, "to_claim": 1, "relation": "refines"},  # unknown type
                {
                    "from_claim": 1,
                    "to_claim": 0,
                    "relation": "qualifies",
                    "condition": "only in winter",
                },
            ]
        },
    )
    rejected: Counter = Counter()
    kept = parse_relations(SimpleNamespace(content=[block]), claims, rejected)

    assert [r["edge_type"] for r in kept] == ["qualifies"]
    assert rejected == Counter(
        {
            "missing_point": 1,
            "claim_index_out_of_range": 1,
            "relation:refines": 1,
        }
    )


async def test_reconcile_stats_distinguish_failed_calls_from_empty_answers():
    from unittest.mock import AsyncMock, patch

    from peritus.graph.reconciler import ClaimRow, ConceptClaims, ReconcileStats, reconcile_claims

    def group(cid):
        return ConceptClaims(
            concept_id=cid,
            concept_label=f"c{cid}",
            claims=[
                ClaimRow(node_id=cid * 10, label="x", source_id=1),
                ClaimRow(node_id=cid * 10 + 1, label="y", source_id=2),
            ],
        )

    stats = ReconcileStats()
    with patch(
        "peritus.graph.reconciler.gather_claude_calls", AsyncMock(return_value=[None, None])
    ):
        relations = await reconcile_claims("bees", [group(1), group(2)], stats=stats)

    assert relations == []
    assert (stats.concepts_eligible, stats.concepts_examined, stats.calls_failed) == (2, 2, 2)
    assert stats.as_event()["relations_returned"] == 0


async def test_reconcile_stage_reports_a_pass_that_inserted_nothing():
    """Silence used to look like success: the event fired only on inserts."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from peritus.experts.builder import _reconcile_claims
    from peritus.graph.reconciler import ClaimRow, ConceptClaims

    repo = MagicMock()
    repo.claims_by_concept = AsyncMock(
        return_value=[
            ConceptClaims(
                concept_id=1,
                concept_label="c",
                claims=[
                    ClaimRow(node_id=1, label="x", source_id=1),
                    ClaimRow(node_id=2, label="y", source_id=2),
                ],
            )
        ]
    )
    repo.insert_relations = AsyncMock(return_value=0)
    events: list[dict] = []

    async def on_event(e):
        events.append(e)

    with patch("peritus.graph.reconciler.gather_claude_calls", AsyncMock(return_value=[None])):
        assert await _reconcile_claims("bees", 7, repo, on_event) == 0

    [event] = [e for e in events if e["type"] == "claims_reconciled"]
    assert event["relations"] == 0
    assert event["concepts_examined"] == 1 and event["calls_failed"] == 1
