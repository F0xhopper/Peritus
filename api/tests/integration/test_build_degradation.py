"""Failures after chat-ready degrade the build instead of failing it.

Once the corpus is fetched, validated and embedded, the expert answers
questions — so a graph-extraction or persona failure must not raise out of the
builder, where the worker's retry loop would reset and re-run (and re-pay for)
the whole pipeline. Each enrichment stage degrades independently and says so
with a `stage_degraded` event.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from peritus.experts.builder import ExpertBuilder
from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier
from peritus.ingestion.chunker import TextChunk
from peritus.search.readiness import Readiness
from peritus.sources.domain import RawSource, SourceType, ValidatedSource


def _expert() -> Expert:
    return Expert(
        id=1,
        name="stoicism",
        topic="stoicism",
        status=ExpertStatus.BUILDING,
        tier=ExpertTier.STANDARD,
        config=ExpertConfig.from_tier(ExpertTier.STANDARD),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _validated() -> ValidatedSource:
    return ValidatedSource(
        raw=RawSource(
            source_type=SourceType.WIKIPEDIA,
            url="https://example.org/stoicism",
            title="Stoicism",
            author=None,
            text="Virtue is the sole good.",
        ),
        quality_score=8.0,
        relevance_score=9.0,
        content_type="reference",
        difficulty=2,
        key_claims=["Virtue is the sole good"],
        covered_concepts=["virtue"],
    )


async def _run_build(
    builder: ExpertBuilder,
    readiness_log: list,
    *,
    graph_mock: AsyncMock | None = None,
    persona_mock: AsyncMock | None = None,
    upload_chunks: list | None = None,
):
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    passed = [_validated()]
    chunks = [TextChunk(text="Virtue is the sole good.", sequence_n=0, chunk_meta={})]

    builder._build_fetchers = lambda *a, **k: {}
    builder._stage_discover = AsyncMock(return_value=[passed[0].raw])
    builder._fill_coverage_gaps = AsyncMock(return_value=(passed, []))
    builder._persist_sources = AsyncMock(return_value=[101])
    builder._load_upload_chunks = AsyncMock(return_value=upload_chunks or [])
    builder._count_upload_sources = AsyncMock(return_value=len(upload_chunks or []))
    builder._repo.update_key_concepts = AsyncMock()
    builder._repo.update_counts = AsyncMock()
    builder._repo.update_persona = AsyncMock()
    builder._graph_repo.bulk_insert_from_extractions = AsyncMock(return_value=(4, 3))
    builder._graph_repo.get_top_nodes = AsyncMock(return_value=[])

    async def _record(_pool, expert_id, readiness):
        readiness_log.append(readiness)

    graph = graph_mock or AsyncMock(return_value=[{"nodes": [], "edges": []}])
    persona = persona_mock or AsyncMock(
        return_value={"name": "Dr. Aurelia Vance", "bio": "b", "style": "s"}
    )
    with (
        patch("peritus.experts.builder._plan_research", AsyncMock(return_value={
            "fetcher_plans": {},
            "key_concepts": ["virtue"],
            "must_have_works": [],
        })),
        patch("peritus.experts.builder._route_must_have_works"),
        patch("peritus.experts.builder._snowball_citations", AsyncMock(return_value=[])),
        patch("peritus.experts.builder.validate_sources", AsyncMock(return_value=(passed, []))),
        patch(
            "peritus.experts.builder.ingest_sources",
            AsyncMock(return_value=[([201], chunks)]),
        ),
        patch("peritus.experts.builder.extract_graph_from_chunks", graph),
        patch("peritus.experts.builder._resolve_entities", AsyncMock(return_value=0)),
        patch("peritus.experts.builder._generate_persona", persona),
        patch("peritus.experts.builder.set_readiness", _record),
    ):
        result = await builder.build(expert=_expert(), on_event=on_event)
    return result, events


@pytest.mark.asyncio
async def test_graph_failure_degrades_to_a_chat_ready_expert():
    readiness_log: list[Readiness] = []
    result, events = await _run_build(
        ExpertBuilder(MagicMock()),
        readiness_log,
        graph_mock=AsyncMock(side_effect=RuntimeError("model unavailable")),
    )

    degraded = [e for e in events if e["type"] == "stage_degraded"]
    assert [d["stage"] for d in degraded] == ["graph"]
    # No graph → the expert stays chat-ready; it never claims graph expansion.
    assert readiness_log == [Readiness.PENDING, Readiness.CHAT_READY]
    assert not any(e["type"] == "graph_ready" for e in events)
    assert (result.node_count, result.edge_count) == (0, 0)
    # The persona stage still ran — one degraded stage doesn't cancel the next.
    assert result.persona_name == "Dr. Aurelia Vance"


@pytest.mark.asyncio
async def test_persona_failure_leaves_a_nameless_working_expert():
    readiness_log: list[Readiness] = []
    builder = ExpertBuilder(MagicMock())
    result, events = await _run_build(
        builder,
        readiness_log,
        persona_mock=AsyncMock(side_effect=RuntimeError("truncated tool call")),
    )

    degraded = [e for e in events if e["type"] == "stage_degraded"]
    assert [d["stage"] for d in degraded] == ["persona"]
    assert result.persona_name is None
    builder._repo.update_persona.assert_not_awaited()
    # Everything before the persona survived untouched.
    assert readiness_log[-1] == Readiness.GRAPH_READY
    assert (result.node_count, result.edge_count) == (4, 3)


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed_as_a_degrade():
    import asyncio

    with pytest.raises(asyncio.CancelledError):
        await _run_build(
            ExpertBuilder(MagicMock()),
            [],
            graph_mock=AsyncMock(side_effect=asyncio.CancelledError()),
        )


@pytest.mark.asyncio
async def test_final_counts_keep_preserved_upload_chunks():
    """A rebuild preserves user-uploaded sources; the counts written after the
    graph stage must include them, not regress to discovery-only totals."""
    builder = ExpertBuilder(MagicMock())
    upload = [(TextChunk(text="my book", sequence_n=0, chunk_meta={}), 999)]
    result, _ = await _run_build(builder, [], upload_chunks=upload)

    final = builder._repo.update_counts.await_args_list[-1].kwargs
    assert final["source_count"] == 2  # 1 discovered + 1 uploaded
    assert final["chunk_count"] == 2
    assert (result.source_count, result.chunk_count) == (2, 2)
