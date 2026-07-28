"""The build publishes a usable expert one stage early.

Drives the whole pipeline with every external call mocked and asserts the
ordering that time-to-value depends on: `chat_ready` must land before graph
extraction starts, not after the build finishes.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from peritus.core.config import settings
from peritus.experts.builder import ExpertBuilder
from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier
from peritus.infrastructure.anthropic_batch import BuildExecution
from peritus.ingestion.chunker import TextChunk
from peritus.search.readiness import Readiness
from peritus.sources.domain import RawSource, SourceType, ValidatedSource


def _expert(persona_name: str | None = None) -> Expert:
    return Expert(
        id=1,
        name="stoicism",
        topic="stoicism",
        status=ExpertStatus.BUILDING,
        tier=ExpertTier.STANDARD,
        config=ExpertConfig.from_tier(ExpertTier.STANDARD),
        persona_name=persona_name,
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


async def _run_build(builder: ExpertBuilder, expert: Expert, readiness_log: list):
    """Drive ExpertBuilder.build with every stage's external work stubbed out."""
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    passed = [_validated()]
    chunks = [TextChunk(text="Virtue is the sole good.", sequence_n=0, chunk_meta={})]

    builder._build_fetchers = lambda *a, **k: {}
    builder._stage_discover = AsyncMock(return_value=[passed[0].raw])
    builder._fill_coverage_gaps = AsyncMock(return_value=(passed, []))
    builder._persist_sources = AsyncMock(return_value=[101])
    builder._repo.update_key_concepts = AsyncMock()
    builder._repo.update_counts = AsyncMock()
    builder._repo.update_persona = AsyncMock()
    builder._graph_repo.bulk_insert_from_extractions = AsyncMock(return_value=(4, 3))
    builder._graph_repo.get_top_nodes = AsyncMock(return_value=[])

    async def _record(_pool, expert_id, readiness):
        readiness_log.append(readiness)
        events.append({"type": "_readiness", "readiness": readiness})

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
        patch(
            "peritus.experts.builder.extract_graph_from_chunks",
            AsyncMock(return_value=[{"nodes": [], "edges": []}]),
        ),
        patch("peritus.experts.builder._resolve_entities", AsyncMock(return_value=0)),
        patch("peritus.experts.builder._generate_persona", AsyncMock(return_value={
            "name": "Dr. Aurelia Vance", "bio": "b", "style": "s",
        })),
        patch("peritus.experts.builder.set_readiness", _record),
    ):
        result = await builder.build(expert, on_event=on_event)
    return result, events


def _types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


@pytest.mark.asyncio
async def test_chat_ready_is_published_before_graph_extraction():
    readiness_log: list[Readiness] = []
    builder = ExpertBuilder(MagicMock())
    result, events = await _run_build(builder, _expert(), readiness_log)

    types = _types(events)
    chat_ready = types.index("chat_ready")
    graph_stage = next(
        i for i, e in enumerate(events)
        if e["type"] == "stage" and e.get("name") == "graph"
    )
    graph_ready = types.index("graph_ready")

    assert chat_ready < graph_stage < graph_ready
    assert result.persona_name == "Dr. Aurelia Vance"


@pytest.mark.asyncio
async def test_readiness_transitions_in_order():
    readiness_log: list[Readiness] = []
    await _run_build(ExpertBuilder(MagicMock()), _expert(), readiness_log)
    assert readiness_log == [
        Readiness.PENDING,      # rebuild has just wiped the old corpus
        Readiness.CHAT_READY,   # chunks embedded — answerable
        Readiness.GRAPH_READY,  # graph extracted + resolved
    ]


@pytest.mark.asyncio
async def test_counts_are_written_at_chat_ready_so_the_expert_is_not_empty():
    builder = ExpertBuilder(MagicMock())
    await _run_build(builder, _expert(), [])

    first = builder._repo.update_counts.await_args_list[0].kwargs
    assert first["chunk_count"] == 1
    assert first["source_count"] == 1
    assert first["node_count"] == 0  # graph not extracted yet — honest, not stale


@pytest.mark.asyncio
async def test_chat_ready_event_reports_no_graph_expansion():
    _, events = await _run_build(ExpertBuilder(MagicMock()), _expert(), [])
    chat_ready = next(e for e in events if e["type"] == "chat_ready")
    graph_ready = next(e for e in events if e["type"] == "graph_ready")
    assert chat_ready["graph_expanded"] is False
    assert chat_ready["chunks"] == 1
    assert graph_ready["graph_expanded"] is True
    assert (graph_ready["nodes"], graph_ready["edges"]) == (4, 3)


# ── execution policy end to end ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_first_build_announces_interactive_execution(monkeypatch):
    monkeypatch.setattr(settings, "BUILD_EXECUTION_DEFAULT", "auto")
    _, events = await _run_build(ExpertBuilder(MagicMock()), _expert(), [])
    mode = next(e for e in events if e["type"] == "execution_mode")
    assert mode["mode"] == BuildExecution.INTERACTIVE.value
    assert mode["batched"] is False


@pytest.mark.asyncio
async def test_rebuild_announces_background_execution(monkeypatch):
    monkeypatch.setattr(settings, "BUILD_EXECUTION_DEFAULT", "auto")
    monkeypatch.setattr(settings, "ANTHROPIC_BATCH_ENABLED", True)
    _, events = await _run_build(
        ExpertBuilder(MagicMock()), _expert(persona_name="Dr. Aurelia Vance"), []
    )
    mode = next(e for e in events if e["type"] == "execution_mode")
    assert mode["mode"] == BuildExecution.BACKGROUND.value
    assert mode["batched"] is True


@pytest.mark.asyncio
async def test_explicit_execution_beats_the_heuristic(monkeypatch):
    monkeypatch.setattr(settings, "BUILD_EXECUTION_DEFAULT", "auto")
    monkeypatch.setattr(settings, "ANTHROPIC_BATCH_ENABLED", True)
    builder = ExpertBuilder(MagicMock(), execution=BuildExecution.BACKGROUND)
    _, events = await _run_build(builder, _expert(persona_name=None), [])
    mode = next(e for e in events if e["type"] == "execution_mode")
    assert mode["mode"] == BuildExecution.BACKGROUND.value
