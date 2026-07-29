"""Chat-ready before graph-ready: retrieval has no structural graph dependency.

These tests pin the property the "chat-ready" readiness state is built on — that
a grounded, cited answer is producible from chunks alone — so a future change
that quietly makes retrieval require the concept graph fails here rather than in
production, where it would show up as empty answers on half-built experts.
"""

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from peritus.chat.grounding import build_grounded_context, build_system_prompt
from peritus.graph.retriever import GraphRetriever
from peritus.search.domain import SearchResult, SourceRef
from peritus.search.readiness import Readiness
from peritus.search.service import SearchService


def _hit(chunk_id: int, text: str, title: str) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        expert_id=1,
        source_id=chunk_id * 10,
        text=text,
        context_text=None,
        score=0.5,
        sequence_n=0,
        source_ref=SourceRef(
            source_id=chunk_id * 10,
            title=title,
            source_type="arxiv",
            quality_score=8.2,
        ),
    )


# ── readiness state machine ──────────────────────────────────────────────────

def test_pending_cannot_chat():
    assert Readiness.PENDING.can_chat is False
    assert Readiness.PENDING.graph_expanded is False


def test_chat_ready_can_chat_without_graph():
    assert Readiness.CHAT_READY.can_chat is True
    assert Readiness.CHAT_READY.graph_expanded is False


def test_graph_ready_is_fully_capable():
    assert Readiness.GRAPH_READY.can_chat is True
    assert Readiness.GRAPH_READY.graph_expanded is True


# ── the structural claim ─────────────────────────────────────────────────────

def test_hybrid_search_sql_touches_no_graph_tables():
    """Semantic ⊕ keyword ⊕ RRF reads source_chunks and sources, nothing else."""
    sql = inspect.getsource(SearchService._hybrid_search)
    assert "source_chunks" in sql
    assert "expert_nodes" not in sql
    assert "expert_edges" not in sql


@pytest.mark.asyncio
async def test_expansion_is_a_noop_on_an_empty_graph():
    retriever = GraphRetriever(MagicMock())
    retriever._repo.get_nodes_for_chunks = AsyncMock(return_value=[])
    neighbours = AsyncMock(return_value=([], []))
    retriever._repo.get_neighbours = neighbours

    hits = [_hit(1, "Virtue is the sole good.", "Discourses")]
    enriched = await retriever.expand(hits, expert_id=1, hops=1)

    assert [e.result for e in enriched] == hits
    assert enriched[0].related_concepts == []
    assert enriched[0].has_contradiction is False
    # No graph, no neighbour query — the empty-graph path short-circuits.
    neighbours.assert_not_awaited()


@pytest.mark.asyncio
async def test_grounded_cited_context_without_a_graph():
    """The chat-ready promise: numbered passages a model can cite [n] against."""
    retriever = GraphRetriever(MagicMock())
    retriever._repo.get_nodes_for_chunks = AsyncMock(return_value=[])

    hits = [
        _hit(1, "Virtue is the sole good.", "Discourses"),
        _hit(2, "Externals are indifferent.", "Enchiridion"),
    ]
    enriched = await retriever.expand(hits, expert_id=1, hops=1)
    block, passages = build_grounded_context(enriched, max_passages=15)

    assert [p.index for p in passages] == [1, 2]
    assert [p.source_id for p in passages] == [10, 20]
    assert "[1] Discourses — Arxiv" in block
    assert "[2] Enchiridion — Arxiv" in block
    assert "Virtue is the sole good." in block
    # Nothing graph-shaped leaks into the prompt while the graph is missing.
    assert "Related concepts" not in block
    assert "Relationships" not in block


@pytest.mark.asyncio
async def test_graph_upgrade_is_transparent_to_the_same_call():
    """Same retrieval call, graph now present: passages gain concepts + relations."""
    retriever = GraphRetriever(MagicMock())
    retriever._repo.get_nodes_for_chunks = AsyncMock(
        return_value=[{"id": 7, "label": "Virtue", "description": "The sole good", "chunk_ids": [1]}]
    )
    retriever._repo.get_neighbours = AsyncMock(
        return_value=(
            [
                {"id": 7, "label": "Virtue", "description": "The sole good"},
                {"id": 8, "label": "Indifferents", "description": "Neither good nor bad"},
            ],
            [
                {
                    "from_node_id": 7,
                    "to_node_id": 8,
                    "edge_type": "contradicts",
                    "weight": 0.9,
                }
            ],
        )
    )

    enriched = await retriever.expand([_hit(1, "Virtue is the sole good.", "Discourses")], 1, 1)
    block, passages = build_grounded_context(enriched, max_passages=15)

    assert len(passages) == 1  # same passage, same number — citations don't shift
    assert "Related concepts" in block
    assert "Virtue --contradicts--> Indifferents" in block
    assert enriched[0].has_contradiction is True


def test_persona_is_not_required_for_a_grounded_prompt():
    """Persona is the last build stage; chat-ready precedes it."""
    prompt = build_system_prompt(None, "stoicism")
    assert "subject-matter expert in stoicism" in prompt
    # The grounding rules do not depend on the persona having been generated.
    assert "must carry the bracketed number" in prompt
