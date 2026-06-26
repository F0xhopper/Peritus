"""Build pipeline coordinator — orchestrates all 5 stages with progress callbacks.

Stages:
  1. DISCOVER — run all fetchers concurrently
  2. VALIDATE — Claude validates each raw source (concurrency-limited)
  3. CHUNK + EMBED — chunk, contextualise, embed, store each validated source
  4. GRAPH EXTRACT — Claude reads chunks in batches, extracts concept graph
  5. PERSONA — Claude generates expert persona from corpus digest
"""

import asyncio
import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import asyncpg

from peritus.core.config import settings
from peritus.core.exceptions import BuildError
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.experts.repository import ExpertRepository
from peritus.graph.extractor import extract_graph_from_chunks
from peritus.graph.repository import GraphRepository
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.ingestion.chunker import TextChunk, chunk_text
from peritus.ingestion.pipeline import ingest_source
from peritus.sources.domain import DroppedSource, RawSource, SourceType, ValidatedSource
from peritus.sources.fetchers.arxiv import ArxivFetcher
from peritus.sources.fetchers.exa import ExaFetcher
from peritus.sources.fetchers.gutenberg import GutenbergFetcher
from peritus.sources.fetchers.pdf import PdfFetcher
from peritus.sources.fetchers.web import WebFetcher
from peritus.sources.fetchers.wikipedia import WikipediaFetcher
from peritus.sources.fetchers.youtube import YoutubeFetcher
from peritus.sources.validator import validate_sources

logger = get_logger(__name__)

EventCallback = Callable[[dict], Coroutine[Any, Any, None]]


@dataclass
class BuildResult:
    expert_id: int
    source_count: int
    dropped_count: int
    chunk_count: int
    node_count: int
    edge_count: int
    avg_quality: float | None
    persona_name: str | None


class ExpertBuilder:
    def __init__(
        self,
        pool: asyncpg.Pool,
        depth: str = "normal",
        source_filter: list[str] | None = None,
    ) -> None:
        self._pool = pool
        self._repo = ExpertRepository(pool)
        self._graph_repo = GraphRepository(pool)
        self._depth = depth
        self._source_filter = source_filter

        multiplier = 2 if depth == "deep" else 1
        self._fetchers = self._build_fetchers(multiplier, source_filter)

    def _build_fetchers(self, multiplier: int, source_filter: list[str] | None):
        all_fetchers = {
            "wikipedia":  (WikipediaFetcher(),  4 * multiplier),
            "gutenberg":  (GutenbergFetcher(),  3 * multiplier),
            "arxiv":      (ArxivFetcher(),       3 * multiplier),
            "pdf":        (PdfFetcher(),          4 * multiplier),
            "youtube":    (YoutubeFetcher(),      5 * multiplier),
            "exa":        (ExaFetcher(),          8 * multiplier),
            "web":        (WebFetcher(),          4 * multiplier),
        }
        if source_filter:
            return {k: v for k, v in all_fetchers.items() if k in source_filter}
        return all_fetchers

    async def build(
        self,
        expert: Expert,
        on_event: EventCallback | None = None,
    ) -> BuildResult:
        topic = expert.topic

        # Stage 1: Discover
        await _emit_event(on_event, {"type": "stage", "stage": 1, "name": "discover"})
        raw_sources = await self._stage_discover(topic, on_event)

        if not raw_sources:
            raise BuildError("No sources discovered. Check API keys and network access.")

        # Stage 2: Validate
        await _emit_event(on_event, {"type": "stage", "stage": 2, "name": "validate", "total": len(raw_sources)})
        passed, dropped = await validate_sources(
            topic, raw_sources,
            on_result=lambda r: _emit_event(on_event, {"type": "source_validated", **r}),
        )
        await _emit_event(on_event, {"type": "validate_done", "passed": len(passed), "dropped": len(dropped)})

        if not passed:
            raise BuildError("All sources failed validation. Try a different topic or sources.")

        source_db_ids = await self._persist_sources(expert.id, passed, dropped)
        avg_quality = _avg_quality(passed)

        # Stage 3: Chunk + Embed
        await _emit_event(on_event, {"type": "stage", "stage": 3, "name": "chunk", "total": len(passed)})
        all_chunk_ids: list[int] = []
        all_chunks_for_graph: list[tuple[TextChunk, int]] = []

        for vsource, src_db_id in zip(passed, source_db_ids):
            try:
                chunk_ids = await ingest_source(vsource, expert.id, src_db_id, self._pool)
                all_chunk_ids.extend(chunk_ids)
                raw_chunks = chunk_text(vsource.text, vsource.title)
                all_chunks_for_graph.extend(zip(raw_chunks, chunk_ids))
                await _emit_event(on_event, {
                    "type": "source_ingested",
                    "title": vsource.title,
                    "chunks": len(chunk_ids),
                    "total_chunks": len(all_chunk_ids),
                })
            except Exception as exc:
                logger.warning("Ingestion failed for %r: %s", vsource.title, exc)
                await _emit_event(on_event, {"type": "source_ingested", "title": vsource.title, "chunks": 0, "total_chunks": len(all_chunk_ids)})

        if not all_chunk_ids:
            raise BuildError("No chunks were embedded — ingestion failed for all sources.")

        # Stage 4: Graph extraction
        import math
        total_batches = math.ceil(len(all_chunks_for_graph) / settings.GRAPH_BATCH_SIZE)
        await _emit_event(on_event, {"type": "stage", "stage": 4, "name": "graph", "total_batches": total_batches})

        chunks_only = [c for c, _ in all_chunks_for_graph]
        ids_only = [i for _, i in all_chunks_for_graph]

        async def _on_graph_batch(labels: list[str], edge_count: int) -> None:
            await _emit_event(on_event, {"type": "graph_batch_done", "labels": labels, "edges": edge_count})

        extractions = await extract_graph_from_chunks(topic, chunks_only, ids_only, on_batch=_on_graph_batch)
        node_count, edge_count = await self._graph_repo.bulk_insert_from_extractions(expert.id, extractions)

        await self._repo.update_counts(
            expert.id,
            source_count=len(passed),
            chunk_count=len(all_chunk_ids),
            node_count=node_count,
            edge_count=edge_count,
            avg_quality=avg_quality,
        )

        # Stage 5: Persona generation
        await _emit_event(on_event, {"type": "stage", "stage": 5, "name": "persona"})
        top_nodes = await self._graph_repo.get_top_nodes(expert.id, 20)
        persona = await _generate_persona(topic, passed, top_nodes)
        await self._repo.update_persona(
            expert.id,
            persona_name=persona["name"],
            persona_bio=persona["bio"],
            persona_style=persona["style"],
        )
        await _emit_event(on_event, {"type": "persona_ready", "name": persona["name"]})

        return BuildResult(
            expert_id=expert.id,
            source_count=len(passed),
            dropped_count=len(dropped),
            chunk_count=len(all_chunk_ids),
            node_count=node_count,
            edge_count=edge_count,
            avg_quality=avg_quality,
            persona_name=persona["name"],
        )

    async def _stage_discover(self, topic: str, on_event: EventCallback | None) -> list[RawSource]:
        all_fetcher_names = ["wikipedia", "arxiv", "youtube", "exa", "web"]
        active = set(self._fetchers.keys())
        await _emit_event(on_event, {
            "type": "discovery_started",
            "fetchers": all_fetcher_names,
            "active": list(active),
        })

        async def _fetch_one(name: str, fetcher, max_results: int) -> list[RawSource]:
            results = await _safe_fetch(name, fetcher, topic, max_results)
            skipped, reason = _is_skipped(name, results)
            await _emit_event(on_event, {
                "type": "fetcher_done",
                "name": name,
                "count": len(results),
                "skipped": skipped,
                "reason": reason,
            })
            return results

        results_list = await asyncio.gather(*[
            _fetch_one(name, fetcher, max_results)
            for name, (fetcher, max_results) in self._fetchers.items()
        ])
        return [src for sources in results_list for src in sources]

    async def _persist_sources(
        self,
        expert_id: int,
        passed: list[ValidatedSource],
        dropped: list[DroppedSource],
    ) -> list[int]:
        """Write all sources to DB. Returns DB IDs for passed sources only."""
        passed_ids: list[int] = []
        async with self._pool.acquire() as conn:
            for vs in passed:
                row = await conn.fetchrow(
                    """
                    INSERT INTO sources
                        (expert_id, source_type, url, title, author,
                         quality_score, relevance_score, content_type,
                         difficulty, key_claims, passed)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,true)
                    RETURNING id
                    """,
                    expert_id,
                    vs.source_type.value,
                    vs.url,
                    vs.title,
                    vs.author,
                    vs.quality_score,
                    vs.relevance_score,
                    vs.content_type,
                    vs.difficulty,
                    json.dumps(vs.key_claims),
                )
                passed_ids.append(row["id"])

            for ds in dropped:
                await conn.execute(
                    """
                    INSERT INTO sources
                        (expert_id, source_type, url, title, author,
                         quality_score, relevance_score, passed, drop_reason)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,false,$8)
                    """,
                    expert_id,
                    ds.raw.source_type.value,
                    ds.raw.url,
                    ds.raw.title,
                    ds.raw.author,
                    ds.quality_score,
                    ds.relevance_score,
                    ds.drop_reason,
                )

        return passed_ids


def _is_skipped(name: str, results: list) -> tuple[bool, str]:
    if results:
        return False, ""
    if name in ("youtube", "exa") and not settings.EXA_API_KEY:
        return True, "no EXA_API_KEY"
    if name == "pdf" and not settings.MISTRAL_API_KEY:
        return True, "no MISTRAL_API_KEY"
    return False, ""


async def _safe_fetch(name: str, fetcher, topic: str, max_results: int) -> list[RawSource]:
    try:
        return await fetcher.fetch(topic, max_results)
    except Exception as exc:
        logger.warning("Fetcher %r failed: %s", name, exc)
        return []


async def _generate_persona(
    topic: str,
    passed: list[ValidatedSource],
    top_nodes: list[dict],
) -> dict:
    _TOOL = {
        "name": "generate_persona",
        "description": "Generate a named expert persona grounded in the corpus.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Expert's full name with title."},
                "bio": {"type": "string", "description": "2–3 sentence biography."},
                "style": {
                    "type": "string",
                    "description": (
                        "Full system-prompt instruction block describing how this expert "
                        "speaks, what they emphasise, and how they cite sources."
                    ),
                },
            },
            "required": ["name", "bio", "style"],
        },
    }

    source_digest = "\n".join(
        f"- {vs.title} ({vs.content_type}, Q:{vs.quality_score:.1f}): "
        + "; ".join(vs.key_claims[:2])
        for vs in passed[:15]
    )
    concept_list = ", ".join(n["label"] for n in top_nodes[:20])

    client = get_anthropic_client()
    resp = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=1024,
        system=(
            "You are creating a named expert persona that will be used as the voice of a "
            "grounded AI tutor. The persona must reflect what the corpus actually contains — "
            "not a generic expert. The style instruction should be concrete, specific, and "
            "describe how the expert cites, qualifies claims, and handles uncertainty."
        ),
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "generate_persona"},
        messages=[{
            "role": "user",
            "content": (
                f"Topic: {topic}\n\n"
                f"Sources ingested:\n{source_digest}\n\n"
                f"Top concepts extracted: {concept_list}"
            ),
        }],
    )
    block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
    return dict(block.input)


def _avg_quality(passed: list[ValidatedSource]) -> float | None:
    if not passed:
        return None
    scores = [vs.quality_score for vs in passed if vs.quality_score is not None]
    return round(sum(scores) / len(scores), 2) if scores else None


async def _emit_event(cb: EventCallback | None, event: dict) -> None:
    if cb:
        await cb(event)
