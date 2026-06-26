"""Build pipeline coordinator — orchestrates all 5 stages with progress callbacks.

Stages:
  0. PLAN    — Claude generates per-fetcher search queries and key concepts
  1. DISCOVER — run all fetchers concurrently using planned queries
  2. VALIDATE — Claude validates each raw source (concurrency-limited)
  3. CHUNK + EMBED — chunk, contextualise, embed, store each validated source
  4. GRAPH EXTRACT — Claude reads chunks in batches, extracts concept graph
  4b. RESOLVE — merge semantically duplicate graph nodes via embedding similarity
  5. PERSONA — Claude generates expert persona from corpus digest
"""

import asyncio
import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import httpx

from peritus.core.config import settings
from peritus.core.exceptions import BuildError
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.experts.repository import ExpertRepository
from peritus.graph.extractor import extract_graph_from_chunks
from peritus.graph.repository import GraphRepository
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.infrastructure.embeddings import embed_batch
from peritus.ingestion.chunker import TextChunk, chunk_text
from peritus.ingestion.pipeline import ingest_source
from peritus.sources.domain import DroppedSource, RawSource, SourceType, ValidatedSource
from peritus.sources.fetchers.arxiv import (
    ArxivFetcher,
    _HEADERS as _ARXIV_HEADERS,
    _MAX_FULL_TEXT,
    _MIN_FULL_TEXT,
    _fetch_ar5iv,
)
from peritus.sources.fetchers.exa import ExaFetcher
from peritus.sources.fetchers.gutenberg import GutenbergFetcher
from peritus.sources.fetchers.pdf import PdfFetcher
from peritus.sources.fetchers.reddit import RedditFetcher
from peritus.sources.fetchers.thought_leaders import ThoughtLeadersFetcher
from peritus.sources.fetchers.web import WebFetcher
from peritus.sources.fetchers.wikipedia import WikipediaFetcher
from peritus.sources.fetchers.youtube import YoutubeFetcher
from peritus.sources.validator import validate_sources

logger = get_logger(__name__)

EventCallback = Callable[[dict], Coroutine[Any, Any, None]]

_PLAN_TOOL = {
    "name": "create_research_plan",
    "description": "Generate targeted search queries for each source fetcher.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fetcher_queries": {
                "type": "object",
                "description": (
                    "A specific search query for each fetcher, tuned to what that source "
                    "type does best. If a fetcher is irrelevant for the topic, use the "
                    "original topic string as the query."
                ),
                "properties": {
                    "wikipedia":      {"type": "string"},
                    "arxiv":          {"type": "string"},
                    "youtube":        {"type": "string"},
                    "exa":            {"type": "string"},
                    "web":            {"type": "string"},
                    "gutenberg":      {"type": "string"},
                    "pdf":            {"type": "string"},
                    "reddit":         {"type": "string"},
                    "thought_leaders": {"type": "string"},
                },
            },
            "key_concepts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "5–8 core concepts this corpus must cover.",
                "maxItems": 8,
            },
        },
        "required": ["fetcher_queries", "key_concepts"],
    },
}


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
            "wikipedia":      (WikipediaFetcher(),      3 * multiplier),
            "gutenberg":      (GutenbergFetcher(),      4 * multiplier),
            "arxiv":          (ArxivFetcher(),          2 * multiplier),
            "pdf":            (PdfFetcher(),            3 * multiplier),
            "youtube":        (YoutubeFetcher(),        3 * multiplier),
            "exa":            (ExaFetcher(),            5 * multiplier),
            "web":            (WebFetcher(),            3 * multiplier),
            "reddit":         (RedditFetcher(),         5 * multiplier),
            "thought_leaders": (ThoughtLeadersFetcher(), 3 * multiplier),
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

        # Stage 0: Research planning
        await _emit_event(on_event, {"type": "stage", "stage": 0, "name": "plan"})
        plan = await _plan_research(topic)
        await _emit_event(on_event, {
            "type": "plan_ready",
            "key_concepts": plan.get("key_concepts", []),
        })

        # Stage 1: Discover
        await _emit_event(on_event, {"type": "stage", "stage": 1, "name": "discover"})
        raw_sources = await self._stage_discover(topic, plan, on_event)

        # Citation snowballing: follow high-citation references from ArXiv sources
        extra = await _snowball_citations(raw_sources)
        if extra:
            await _emit_event(on_event, {"type": "snowball_done", "added": len(extra)})
            raw_sources.extend(extra)

        # Dedup by URL before paying validation costs
        raw_sources = _dedup_by_url(raw_sources)

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

        # Entity resolution: merge semantically duplicate graph nodes
        await _emit_event(on_event, {"type": "stage", "stage": 4, "name": "resolve"})
        merged_count = await _resolve_entities(expert.id, self._graph_repo)
        if merged_count:
            await _emit_event(on_event, {"type": "entities_resolved", "merged": merged_count})
            node_count = max(0, node_count - merged_count)

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

    async def _stage_discover(
        self,
        topic: str,
        plan: dict,
        on_event: EventCallback | None,
    ) -> list[RawSource]:
        all_fetcher_names = [
            "wikipedia", "gutenberg", "arxiv", "pdf",
            "youtube", "exa", "web", "reddit", "thought_leaders",
        ]
        fetcher_queries = plan.get("fetcher_queries", {})
        active = set(self._fetchers.keys())

        # Expand into subtopic queries for broader coverage
        queries = await _expand_topic(topic)

        await _emit_event(on_event, {
            "type": "discovery_started",
            "fetchers": all_fetcher_names,
            "active": list(active),
            "queries": queries,
        })

        # thought_leaders already does its own internal expansion; run it once
        _SINGLE_QUERY_FETCHERS = {"thought_leaders"}

        async def _fetch_one(name: str, fetcher, max_results: int) -> list[RawSource]:
            query = fetcher_queries.get(name) or topic
            results = await _safe_fetch(name, fetcher, query, max_results)
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
        all_sources = [src for sources in results_list for src in sources]
        return _deduplicate_sources(all_sources)

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


async def _plan_research(topic: str) -> dict:
    """One Haiku call: returns per-fetcher queries + key concepts."""
    try:
        client = get_anthropic_client()
        resp = await client.messages.create(
            model=settings.FAST_MODEL,
            max_tokens=400,
            system=(
                "Generate targeted search queries for different source types to build a "
                "comprehensive knowledge base. Each query should be specific to what that "
                "source type does best — e.g. arxiv gets academic/theoretical angles, "
                "gutenberg gets classic primary texts, reddit gets practitioner discussion."
            ),
            tools=[_PLAN_TOOL],
            tool_choice={"type": "tool", "name": "create_research_plan"},
            messages=[{"role": "user", "content": f"Topic: {topic}"}],
        )
        block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
        plan = dict(block.input)
        logger.info(
            "Research plan for %r: concepts=%s",
            topic,
            ", ".join(plan.get("key_concepts", [])),
        )
        return plan
    except Exception as exc:
        logger.warning("Research planning failed, falling back to raw topic: %s", exc)
        return {"fetcher_queries": {}, "key_concepts": []}


async def _snowball_citations(
    raw_sources: list[RawSource],
    max_extra: int = 3,
) -> list[RawSource]:
    """Follow high-citation references from discovered ArXiv papers via Semantic Scholar."""
    import arxiv as arxiv_lib  # type: ignore

    arxiv_ids = [
        s.metadata["arxiv_id"]
        for s in raw_sources
        if s.source_type == SourceType.ARXIV and s.metadata.get("arxiv_id")
    ]
    if not arxiv_ids:
        return []

    seen_ids = set(arxiv_ids)
    seen_urls = {s.url for s in raw_sources}
    candidates: list[dict] = []

    _HEADERS = {"User-Agent": "Peritus/2.0 (educational; foxhopper16@gmail.com)"}
    async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as client:
        for arxiv_id in arxiv_ids[:3]:
            try:
                resp = await client.get(
                    f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}/references",
                    params={
                        "fields": "title,citationCount,openAccessPdf,externalIds",
                        "limit": 20,
                    },
                )
                if resp.status_code != 200:
                    continue
                for ref in resp.json().get("data", []):
                    cited = ref.get("citedPaper") or {}
                    ext_ids = cited.get("externalIds") or {}
                    ref_arxiv_id = ext_ids.get("ArXiv")
                    citation_count = cited.get("citationCount") or 0
                    if (
                        ref_arxiv_id
                        and ref_arxiv_id not in seen_ids
                        and citation_count >= 50
                    ):
                        candidates.append({
                            "arxiv_id": ref_arxiv_id,
                            "title": cited.get("title", ""),
                            "citations": citation_count,
                        })
                        seen_ids.add(ref_arxiv_id)
            except Exception as exc:
                logger.debug("Semantic Scholar references failed for %s: %s", arxiv_id, exc)

    if not candidates:
        return []

    candidates.sort(key=lambda x: x["citations"], reverse=True)
    extra: list[RawSource] = []

    async with httpx.AsyncClient(
        timeout=30, headers=_ARXIV_HEADERS, follow_redirects=True
    ) as http:
        for cand in candidates[:max_extra]:
            aid = cand["arxiv_id"]
            try:
                lib_client = arxiv_lib.Client()
                papers = list(lib_client.results(arxiv_lib.Search(id_list=[aid])))
                if not papers:
                    continue
                paper = papers[0]
                url = paper.entry_id
                if url in seen_urls:
                    continue
                full_text = await _fetch_ar5iv(http, aid)
                text = full_text[:_MAX_FULL_TEXT] if len(full_text) >= _MIN_FULL_TEXT \
                    else f"{paper.title}\n\n{paper.summary}"
                extra.append(RawSource(
                    source_type=SourceType.ARXIV,
                    url=url,
                    title=paper.title,
                    author=", ".join(str(a) for a in paper.authors[:3]),
                    text=text,
                    metadata={
                        "arxiv_id": aid,
                        "published": str(paper.published),
                        "categories": paper.categories,
                        "full_text": len(full_text) >= _MIN_FULL_TEXT,
                        "snowballed": True,
                        "citations": cand["citations"],
                    },
                ))
                seen_urls.add(url)
                logger.info("Snowballed: %r (%d citations)", paper.title, cand["citations"])
            except Exception as exc:
                logger.debug("Snowball fetch failed for arXiv:%s: %s", aid, exc)

    return extra


def _dedup_by_url(sources: list[RawSource]) -> list[RawSource]:
    seen: set[str] = set()
    out: list[RawSource] = []
    for s in sources:
        if not s.url or s.url not in seen:
            out.append(s)
            if s.url:
                seen.add(s.url)
    return out


async def _resolve_entities(expert_id: int, graph_repo: GraphRepository) -> int:
    """Merge semantically near-duplicate graph nodes using embedding cosine similarity."""
    try:
        import numpy as np
    except ImportError:
        logger.debug("numpy not available — skipping entity resolution")
        return 0

    nodes = await graph_repo.get_all_nodes(expert_id)
    if len(nodes) < 2:
        return 0

    labels = [n["label"] for n in nodes]
    try:
        embeddings = await embed_batch(labels)
    except Exception as exc:
        logger.warning("Entity resolution embedding failed: %s", exc)
        return 0

    matrix = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    normalized = matrix / norms
    sim = normalized @ normalized.T  # (N, N)

    _THRESHOLD = 0.93
    merged_away: set[int] = set()
    merge_count = 0

    for i in range(len(nodes)):
        if nodes[i]["id"] in merged_away:
            continue
        for j in range(i + 1, len(nodes)):
            if nodes[j]["id"] in merged_away:
                continue
            if float(sim[i, j]) >= _THRESHOLD:
                keep_id, drop_id = nodes[i]["id"], nodes[j]["id"]
                await graph_repo.merge_nodes(expert_id, keep_id, drop_id)
                merged_away.add(drop_id)
                merge_count += 1
                logger.debug(
                    "Merged node %r → %r (sim=%.3f)",
                    labels[j], labels[i], float(sim[i, j]),
                )

    if merge_count:
        logger.info(
            "Entity resolution: merged %d duplicate nodes for expert %d",
            merge_count, expert_id,
        )
    return merge_count


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


async def _expand_topic(topic: str) -> list[str]:
    """Return the topic plus up to 2 focused subtopic queries for broader discovery."""
    _TOOL = {
        "name": "expand_topic",
        "description": "Generate focused search queries to discover comprehensive content about a topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2 distinct search queries targeting different aspects of the topic.",
                    "maxItems": 2,
                },
            },
            "required": ["queries"],
        },
    }
    try:
        client = get_anthropic_client()
        resp = await client.messages.create(
            model=settings.FAST_MODEL,
            max_tokens=200,
            system=(
                "Generate focused search queries for discovering educational content. "
                "Each query should target a distinct angle: history/origins, practical application, "
                "key figures, or underlying theory. Keep queries short and search-engine-friendly."
            ),
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "expand_topic"},
            messages=[{
                "role": "user",
                "content": (
                    f"Topic: {topic}\n\n"
                    "Generate 2 additional search queries to find content about different aspects of this topic."
                ),
            }],
        )
        block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
        extras = [q for q in block.input.get("queries", []) if q and q != topic]
        return [topic] + extras[:2]
    except Exception as exc:
        logger.warning("Topic expansion failed: %s", exc)
        return [topic]


def _deduplicate_sources(sources: list[RawSource]) -> list[RawSource]:
    """Remove sources with duplicate URLs, keeping the first occurrence."""
    seen: set[str] = set()
    unique: list[RawSource] = []
    for src in sources:
        key = src.url.rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            unique.append(src)
    return unique


async def _emit_event(cb: EventCallback | None, event: dict) -> None:
    if cb:
        await cb(event)
