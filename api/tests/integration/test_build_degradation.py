"""An expert is ready only when it is complete.

Completeness means all three of: key concepts, a concept graph, and a persona.
Anything less and the build does not report success, so the expert is never
advertised as ready — see the completeness gate at the end of
`ExpertBuilder._build`.

The enrichment stages still degrade rather than raising where they fail: each
emits its `stage_degraded` event, and the corpus keeps whatever readiness it had
reached, so nothing already paid for is discarded and chat keeps working. What
changed is the *ending* — the gate then raises `IncompleteBuildError`, which the
worker retries (unlike `BuildError`), and only a run that produces everything
returns a `BuildResult`.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from peritus.core.exceptions import BuildError, IncompleteBuildError
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
    key_concepts: list[str] | None = None,
    collect_events_into: list | None = None,
):
    # Callers that expect a raise pass their own list, since the return value
    # never arrives but the events emitted before the raise still matter.
    events: list[dict] = collect_events_into if collect_events_into is not None else []

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
            "key_concepts": ["virtue"] if key_concepts is None else key_concepts,
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
async def test_graph_failure_is_incomplete_not_ready():
    """No graph → not ready, however good the corpus is.

    The corpus is still worth keeping: readiness reaches chat_ready and stays
    there, so the chunks are retrievable and a retry is not starting from zero.
    But the build does not succeed, so nothing marks the expert ready.
    """
    readiness_log: list[Readiness] = []
    events: list[dict] = []

    with pytest.raises(IncompleteBuildError) as excinfo:
        _, events = await _run_build(
            ExpertBuilder(MagicMock()),
            readiness_log,
            graph_mock=AsyncMock(side_effect=RuntimeError("model unavailable")),
            collect_events_into=events,
        )

    assert excinfo.value.missing == ["a concept graph"]
    # Retryable: a missing graph is usually one failed call, not a dead end.
    assert not isinstance(excinfo.value, BuildError)

    degraded = [e for e in events if e["type"] == "stage_degraded"]
    assert [d["stage"] for d in degraded] == ["graph"]
    # The corpus is preserved and retrievable; it just never claims graph expansion.
    assert readiness_log == [Readiness.PENDING, Readiness.CHAT_READY]
    assert not any(e["type"] == "graph_ready" for e in events)


@pytest.mark.asyncio
async def test_persona_failure_is_incomplete_not_ready():
    """No persona/description → not ready either, after in-stage retries."""
    readiness_log: list[Readiness] = []
    builder = ExpertBuilder(MagicMock())
    persona = AsyncMock(side_effect=RuntimeError("truncated tool call"))

    with (
        patch("peritus.experts.builder._PERSONA_ATTEMPTS", 1),
        pytest.raises(IncompleteBuildError) as excinfo,
    ):
        await _run_build(builder, readiness_log, persona_mock=persona)

    assert excinfo.value.missing == ["a persona/description"]
    builder._repo.update_persona.assert_not_awaited()
    # Everything before the persona survived untouched — a retry keeps the graph.
    assert readiness_log[-1] == Readiness.GRAPH_READY


@pytest.mark.asyncio
async def test_persona_is_retried_in_place_before_giving_up():
    """One blip must not cost a whole rebuild.

    The persona is a single cheap call, and it now gates readiness — so failing
    the build (and re-fetching, re-validating, re-embedding, re-extracting)
    over one transient error would be wildly disproportionate.
    """
    builder = ExpertBuilder(MagicMock())
    persona = AsyncMock(side_effect=[
        RuntimeError("truncated tool call"),
        {"name": "Dr. Aurelia Vance", "bio": "b", "style": "s"},
    ])

    with patch("peritus.experts.builder._PERSONA_ATTEMPTS", 2):
        result, events = await _run_build(builder, [], persona_mock=persona)

    assert persona.await_count == 2
    assert result.persona_name == "Dr. Aurelia Vance"
    assert not any(e["type"] == "stage_degraded" for e in events)


@pytest.mark.asyncio
async def test_empty_key_concepts_fails_before_spending_anything():
    """Planning failure stops the build at stage 0.

    Without concepts, triage, validation and gap-fill all score against nothing,
    and the gate at the end would reject the result anyway — so discovering and
    fetching first only spends money to reach the same place. One real build
    reached the graph stage and $1.70 this way.
    """
    builder = ExpertBuilder(MagicMock())
    builder._stage_discover = AsyncMock()

    with pytest.raises(IncompleteBuildError) as excinfo:
        await _run_build(builder, [], key_concepts=[])

    assert "key concepts" in excinfo.value.missing[0]
    builder._stage_discover.assert_not_awaited()


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
