"""Build pipeline coordinator — orchestrates all 5 stages with progress callbacks.

Stages:
  0. PLAN    — Claude produces a research brief: per-fetcher queries + budget
               weights, key concepts the corpus must cover, must-have works
  1. DISCOVER — three phases:
       search: planned fetchers over-search (~3× budget) for cheap candidates
       triage: Haiku ranks candidates against the brief; junk and near-dups drop
       fetch:  top candidates get full content, refilling from lower ranks on failure
  2. VALIDATE — Claude validates each raw source and tags which key concepts it covers
  2b. GAP-FILL — key concepts no passing source covers get one targeted re-search
  3. CHUNK + EMBED — chunk, contextualise, embed, store each validated source
                     ── the expert becomes chat-ready here ──
  4. GRAPH EXTRACT — Claude reads chunks in batches, extracts concept graph
  4b. RESOLVE — merge semantically duplicate graph nodes via embedding similarity
  5. PERSONA — Claude generates expert persona from corpus digest

Two cross-cutting decisions live here rather than in the stages:

**Execution policy.** A build declares once, up front, whether its Claude calls
run live (fast, full price) or through the Message Batches API (half price, up
to ~1h of queueing per batched stage). Every stage inherits it — see
:mod:`peritus.infrastructure.anthropic_batch`.

**Readiness.** Retrieval needs chunks, not the concept graph, so the expert is
published as chat-ready at the end of stage 3 and upgraded to graph-ready after
stage 4b — see :mod:`peritus.search.readiness`.
"""

import asyncio
import json
import math
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import asyncpg
import httpx

from peritus.core.config import settings
from peritus.core.exceptions import BuildError
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.experts.repository import ExpertRepository
from peritus.graph.extractor import extract_graph_from_chunks
from peritus.graph.repository import GraphRepository, node_embedding_text
from peritus.infrastructure.anthropic_batch import BuildExecution, build_execution
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.infrastructure.embeddings import embed_in_batches
from peritus.ingestion.chunker import TextChunk
from peritus.ingestion.pipeline import ingest_sources
from peritus.search.readiness import Readiness, set_readiness
from peritus.sources.domain import (
    DroppedSource,
    RawSource,
    SourceCandidate,
    SourceType,
    ValidatedSource,
)
from peritus.sources.fetchers.arxiv import (
    HEADERS as ARXIV_HEADERS,
)
from peritus.sources.fetchers.arxiv import (
    MAX_FULL_TEXT,
    MIN_FULL_TEXT,
    ArxivFetcher,
    fetch_ar5iv,
)
from peritus.sources.fetchers.exa import ExaFetcher
from peritus.sources.fetchers.gutenberg import GutenbergFetcher
from peritus.sources.fetchers.pdf import PdfFetcher
from peritus.sources.fetchers.pubmed import PubmedFetcher
from peritus.sources.fetchers.reddit import RedditFetcher
from peritus.sources.fetchers.thought_leaders import ThoughtLeadersFetcher
from peritus.sources.fetchers.web import WebFetcher
from peritus.sources.fetchers.wikipedia import WikipediaFetcher
from peritus.sources.fetchers.youtube import YoutubeFetcher
from peritus.sources.triage import TriagedCandidate, rank_candidates, triage_candidates
from peritus.sources.validator import RUBRIC_VERSION, validate_sources

logger = get_logger(__name__)

EventCallback = Callable[[dict], Coroutine[Any, Any, None]]

# Gap-fill: query-driven fetchers only — the identify-then-fetch fetchers
# (gutenberg, thought_leaders) and noisy ones (reddit, youtube) don't take
# well to narrow concept queries.
_GAPFILL_FETCHERS = ("exa", "web", "wikipedia", "arxiv", "pdf", "pubmed")
_GAPFILL_MAX_CONCEPTS = 4
_GAPFILL_RESULTS_PER_QUERY = 2

# Two-phase discovery: the tier multiplier scales the final corpus budget;
# searching is cheap so candidates are gathered at _SEARCH_OVERFETCH× budget
# and triage picks which ones are worth full downloads. Per-type caps keep a
# single source type from flooding the corpus even if it triages well.
_BASE_FETCH_BUDGET = 30
_SEARCH_OVERFETCH = 3
_FETCH_CONCURRENCY = 6
_TYPE_CAP_FACTOR = 2

_FETCHER_SOURCE_TYPES: dict[str, SourceType] = {
    "wikipedia": SourceType.WIKIPEDIA,
    "gutenberg": SourceType.GUTENBERG,
    "arxiv": SourceType.ARXIV,
    "pdf": SourceType.PDF,
    "youtube": SourceType.YOUTUBE,
    "exa": SourceType.EXA,
    "web": SourceType.WEB,
    "reddit": SourceType.REDDIT,
    "thought_leaders": SourceType.THOUGHT_LEADER,
    "pubmed": SourceType.PUBMED,
}

_FETCHER_NAMES: tuple[str, ...] = (
    "wikipedia",
    "gutenberg",
    "arxiv",
    "pdf",
    "youtube",
    "exa",
    "web",
    "reddit",
    "thought_leaders",
    "pubmed",
)
_MAX_QUERIES_PER_FETCHER = 3

_FETCHER_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": _MAX_QUERIES_PER_FETCHER,
            "description": "1–3 search queries, together spanning different facets of the topic.",
        },
        "weight": {
            "type": "number",
            "description": (
                "Budget weight, 0–2. 0 = this source type would add noise for this "
                "topic and must be skipped; 1 = normal; 2 = this source type is "
                "especially valuable here."
            ),
        },
    },
    "required": ["queries", "weight"],
}

_PLAN_TOOL: dict[str, Any] = {
    "name": "create_research_plan",
    "description": (
        "Create a research plan: targeted queries and a budget weight per source "
        "fetcher, the key concepts the corpus must cover, and must-have canonical works."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "fetcher_plans": {
                "type": "object",
                "description": (
                    "A plan for each fetcher, with queries tuned to what that source "
                    "type does best and a weight steering how much of the source budget "
                    "it deserves for this topic."
                ),
                "properties": {name: _FETCHER_PLAN_SCHEMA for name in _FETCHER_NAMES},
            },
            "key_concepts": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Concepts an expert on this topic must be able to teach. The corpus "
                    "is checked against these and gaps are re-searched. Count scales with "
                    "the topic's actual breadth — see the system prompt."
                ),
                "minItems": 5,
                "maxItems": 8,
            },
            "must_have_works": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "author": {"type": "string"},
                    },
                    "required": ["title"],
                },
                "maxItems": 4,
                "description": (
                    "Named canonical works (books, papers, essays) an expert corpus on "
                    "this topic should contain, if any exist."
                ),
            },
        },
        "required": ["fetcher_plans", "key_concepts"],
    },
}

_PLAN_SYSTEM = (
    "You are planning the research for building a grounded AI expert. The sources this "
    "plan discovers are the ONLY material the expert will ever know, so plan for breadth "
    "(every major facet of the topic gets searched) and depth (primary and advanced "
    "material, not just introductions). Tune queries to each source type: arxiv gets "
    "academic/theoretical angles, gutenberg gets classic public-domain primary texts, "
    "pdf gets published papers, reddit gets practitioner discussion, youtube gets "
    "lectures and talks, wikipedia gets encyclopedic overviews, exa and web get "
    "high-quality articles and essays. Give weight 0 to source types that would add "
    "noise for this topic (e.g. gutenberg for modern technology, arxiv for a "
    "non-academic craft) and weight 2 to the ones that carry it.\n\n"
    "key_concepts must scale with how much ground the topic actually covers — this is "
    "a judgment call, not a quota. A narrow or single-threaded topic (one thinker, one "
    "event, one narrow technique) genuinely has fewer than 8 concepts worth naming as "
    "separate teaching points; padding it out to 8 means inventing overlapping or "
    "trivial ones. A broad field (a whole discipline, a wide practice) earns more, up "
    "to 8. Default to the number the topic actually supports, not the maximum allowed."
)


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
        source_filter: list[str] | None = None,
        execution: BuildExecution | None = None,
    ) -> None:
        """``execution=None`` resolves per build (see :func:`resolve_execution`);
        pass a mode explicitly to force one — e.g. a scheduled refresh that should
        always take the half-price path regardless of what the expert looks like."""
        self._pool = pool
        self._repo = ExpertRepository(pool)
        self._graph_repo = GraphRepository(pool)
        self._source_filter = source_filter
        self._execution = execution

    def _build_fetchers(
        self,
        multiplier: float,
        source_filter: list[str] | None,
        weights: dict[str, float] | None = None,
    ):
        weights = weights or {}
        all_fetchers = {
            "wikipedia": (WikipediaFetcher(), 3),
            "gutenberg": (GutenbergFetcher(), 4),
            "arxiv": (ArxivFetcher(), 2),
            "pdf": (PdfFetcher(), 3),
            "youtube": (YoutubeFetcher(), 3),
            "exa": (ExaFetcher(), 5),
            "web": (WebFetcher(), 3),
            "reddit": (RedditFetcher(), 5),
            "thought_leaders": (ThoughtLeadersFetcher(), 3),
            "pubmed": (PubmedFetcher(), 2),
        }

        active: dict[str, tuple[Any, int]] = {}
        for name, (fetcher, base) in all_fetchers.items():
            weight = weights.get(name, 1.0)
            if source_filter:
                if name not in source_filter:
                    continue
                # An explicit source filter is a user decision — the planner may
                # tune the budget but not zero out a requested fetcher.
                weight = max(weight, 1.0)
            elif weight <= 0:
                continue
            active[name] = (fetcher, max(1, round(base * multiplier * weight)))
        return active

    async def build(
        self,
        expert: Expert,
        on_event: EventCallback | None = None,
    ) -> BuildResult:
        """Run the pipeline under this build's execution policy.

        The policy is fixed here, for the whole build, and every stage inherits
        it — a build cannot half-batch. Readiness is also reset here: the worker
        has just deleted the previous corpus, so an expert being rebuilt must
        stop advertising itself as chattable until its new chunks land.
        """
        execution = self._execution or resolve_execution(expert)
        await set_readiness(self._pool, expert.id, Readiness.PENDING)
        await _emit_event(
            on_event,
            {
                "type": "execution_mode",
                "mode": execution.value,
                "batched": execution is BuildExecution.BACKGROUND
                and settings.ANTHROPIC_BATCH_ENABLED,
            },
        )
        logger.info(
            "Building expert %d (%r) with execution=%s", expert.id, expert.name, execution.value
        )
        with build_execution(execution):
            return await self._build(expert, on_event)

    async def _build(
        self,
        expert: Expert,
        on_event: EventCallback | None = None,
    ) -> BuildResult:
        topic = expert.topic

        # Stage 0: Research planning
        await _emit_event(on_event, {"type": "stage", "stage": 0, "name": "plan"})
        plan = await _plan_research(topic)
        _route_must_have_works(plan)
        key_concepts = plan["key_concepts"]
        await self._repo.update_key_concepts(expert.id, key_concepts)
        await _emit_event(
            on_event,
            {
                "type": "plan_ready",
                "key_concepts": key_concepts,
            },
        )

        weights = {name: p["weight"] for name, p in plan["fetcher_plans"].items()}
        self._fetchers = self._build_fetchers(
            expert.config.source_multiplier,
            self._source_filter,
            weights,
        )

        # Stage 1: Discover (search → triage → budgeted fetch)
        fetch_budget = max(5, round(_BASE_FETCH_BUDGET * expert.config.source_multiplier))
        await _emit_event(on_event, {"type": "stage", "stage": 1, "name": "discover"})
        raw_sources = await self._stage_discover(topic, plan, fetch_budget, on_event)

        # Citation snowballing: follow high-citation references from ArXiv sources
        extra = await _snowball_citations(raw_sources)
        if extra:
            await _emit_event(on_event, {"type": "snowball_done", "added": len(extra)})
            raw_sources.extend(extra)

        # Dedup by normalised URL before paying validation costs
        raw_sources = _deduplicate_by_url(raw_sources)

        if not raw_sources:
            raise BuildError("No sources discovered. Check API keys and network access.")

        # Stage 2: Validate
        await _emit_event(
            on_event, {"type": "stage", "stage": 2, "name": "validate", "total": len(raw_sources)}
        )
        passed, dropped = await validate_sources(
            topic,
            raw_sources,
            key_concepts,
            on_result=lambda r: _emit_event(on_event, {"type": "source_validated", **r}),
        )
        await _emit_event(
            on_event, {"type": "validate_done", "passed": len(passed), "dropped": len(dropped)}
        )

        # Stage 2b: Gap-fill — re-search key concepts no passing source covers
        if passed and key_concepts:
            passed, dropped = await self._fill_coverage_gaps(
                topic,
                key_concepts,
                passed,
                dropped,
                on_event,
            )

        if not passed:
            raise BuildError("All sources failed validation. Try a different topic or sources.")

        # Corpus composition, while the user is still watching the build. A
        # weak-but-passing corpus is not a build failure, so this is a warning
        # event rather than a raise — but it has to arrive before they start
        # trusting the expert's answers.
        warning = corpus_tier_warning(passed)
        if warning:
            logger.warning(
                "Expert %d corpus is %d/%d tertiary",
                expert.id, warning["tertiary"], warning["classified"],
            )
            await _emit_event(on_event, warning)

        source_db_ids = await self._persist_sources(expert.id, passed, dropped)
        avg_quality = _avg_quality(passed)

        # Stage 3: Chunk + Embed. All sources are chunked up front so their
        # contextualisation runs as one Message Batch (half price) when enabled.
        await _emit_event(
            on_event, {"type": "stage", "stage": 3, "name": "chunk", "total": len(passed)}
        )
        all_chunk_ids: list[int] = []
        all_chunks_for_graph: list[tuple[TextChunk, int]] = []
        ingested_total = 0

        async def _on_ingested(vsource: ValidatedSource, chunk_ids: list[int]) -> None:
            nonlocal ingested_total
            ingested_total += len(chunk_ids)
            await _emit_event(
                on_event,
                {
                    "type": "source_ingested",
                    "title": vsource.title,
                    "chunks": len(chunk_ids),
                    "total_chunks": ingested_total,
                },
            )

        ingested = await ingest_sources(
            passed,
            expert.id,
            source_db_ids,
            self._pool,
            on_ingested=_on_ingested,
        )
        for chunk_ids, raw_chunks in ingested:
            all_chunk_ids.extend(chunk_ids)
            all_chunks_for_graph.extend(zip(raw_chunks, chunk_ids, strict=True))

        if not all_chunk_ids:
            raise BuildError("No chunks were embedded — ingestion failed for all sources.")

        # User-supplied sources survive `reset_build_state`, so on a rebuild their
        # chunks are already in the table and were never ingested by this run.
        # They still have to reach the graph stage: the graph was wiped whole and
        # is rebuilt whole, and leaving them out would quietly drop the owner's
        # own material out of the concept graph on every rebuild.
        preserved = await self._load_upload_chunks(expert.id)
        all_chunks_for_graph.extend(preserved)

        # ── Chat-ready ───────────────────────────────────────────────────────
        # Everything retrieval needs now exists. Hybrid search reads only
        # source_chunks + sources, and graph expansion is a no-op while the
        # graph is empty, so the expert can already give a grounded, cited
        # answer. Publish it now instead of after the graph and persona stages,
        # and write the counts so the expert doesn't read as empty in the UI.
        # Counts include the preserved uploads, which this run did not ingest but
        # which are part of the corpus the expert answers from.
        #
        # No preserved chunks means no upload sources to count: `ingest_upload`
        # deletes the sources row when nothing embeds, so an upload always has at
        # least one chunk. Skipping the query on that path keeps the common case
        # (an expert with no uploads) at zero extra round-trips.
        total_sources = len(passed)
        if preserved:
            total_sources += await self._count_upload_sources(expert.id)
        total_chunks = len(all_chunk_ids) + len(preserved)
        await self._repo.update_counts(
            expert.id,
            source_count=total_sources,
            chunk_count=total_chunks,
            node_count=0,
            edge_count=0,
            avg_quality=avg_quality,
        )
        await set_readiness(self._pool, expert.id, Readiness.CHAT_READY)
        await _emit_event(
            on_event,
            {
                "type": "chat_ready",
                "sources": total_sources,
                "chunks": total_chunks,
                "graph_expanded": False,
            },
        )

        # Stage 4: Graph extraction
        total_batches = math.ceil(len(all_chunks_for_graph) / settings.GRAPH_BATCH_SIZE)
        await _emit_event(
            on_event, {"type": "stage", "stage": 4, "name": "graph", "total_batches": total_batches}
        )

        chunks_only = [c for c, _ in all_chunks_for_graph]
        ids_only = [i for _, i in all_chunks_for_graph]

        async def _on_graph_batch(labels: list[str], edge_count: int) -> None:
            await _emit_event(
                on_event, {"type": "graph_batch_done", "labels": labels, "edges": edge_count}
            )

        extractions = await extract_graph_from_chunks(
            topic, chunks_only, ids_only, on_batch=_on_graph_batch
        )
        node_count, edge_count = await self._graph_repo.bulk_insert_from_extractions(
            expert.id, extractions, embedder=embed_in_batches
        )

        # Entity resolution: merge semantically duplicate graph nodes
        await _emit_event(on_event, {"type": "stage", "stage": 4, "name": "resolve"})
        merged_count = await _resolve_entities(expert.id, self._graph_repo, on_event)
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

        # ── Graph-ready ──────────────────────────────────────────────────────
        # Retrieval transparently upgrades from here: the same chat request now
        # finds anchor nodes for its hits, so passages arrive with neighbouring
        # concepts, relationships, and contradiction flags. No client action.
        await set_readiness(self._pool, expert.id, Readiness.GRAPH_READY)
        await _emit_event(
            on_event,
            {
                "type": "graph_ready",
                "nodes": node_count,
                "edges": edge_count,
                "graph_expanded": True,
            },
        )

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
        fetch_budget: int,
        on_event: EventCallback | None,
    ) -> list[RawSource]:
        fetcher_plans = plan["fetcher_plans"]
        active = set(self._fetchers.keys())

        await _emit_event(
            on_event,
            {
                "type": "discovery_started",
                "fetchers": list(_FETCHER_NAMES),
                "active": list(active),
            },
        )

        _SINGLE_QUERY_FETCHERS = {"thought_leaders"}

        async def _search_one(name: str, fetcher, quota: int) -> list[SourceCandidate]:
            queries = fetcher_plans.get(name, {}).get("queries") or [topic]
            if name in _SINGLE_QUERY_FETCHERS:
                queries = queries[:1]
            search_quota = quota * _SEARCH_OVERFETCH
            per_query = max(1, math.ceil(search_quota / len(queries)))
            nested = await asyncio.gather(
                *[_safe_search(name, fetcher, query, per_query) for query in queries]
            )
            candidates = _deduplicate_by_url([c for batch in nested for c in batch])
            skipped, reason = _is_skipped(name, candidates)
            await _emit_event(
                on_event,
                {
                    "type": "fetcher_done",
                    "name": name,
                    "count": len(candidates),
                    "skipped": skipped,
                    "reason": reason,
                    "queries": len(queries),
                },
            )
            return candidates

        candidate_lists = await asyncio.gather(
            *[
                _search_one(name, fetcher, quota)
                for name, (fetcher, quota) in self._fetchers.items()
            ]
        )
        candidates = _deduplicate_by_url([c for batch in candidate_lists for c in batch])
        if not candidates:
            return []

        # Phase 2: triage — rank all candidates against the research brief
        must_have_titles = [w["title"] for w in plan["must_have_works"]]
        triaged = await triage_candidates(
            topic,
            plan["key_concepts"],
            must_have_titles,
            candidates,
        )
        ranked = rank_candidates(triaged)
        await _emit_event(
            on_event,
            {
                "type": "triage_done",
                "candidates": len(candidates),
                "ranked": len(ranked),
                "budget": fetch_budget,
            },
        )

        # Phase 3: full fetch for the winners, refilling on failure
        caps = {
            _FETCHER_SOURCE_TYPES[name]: quota * _TYPE_CAP_FACTOR
            for name, (_, quota) in self._fetchers.items()
        }
        sources = await self._fetch_with_refill(ranked, fetch_budget, caps)
        await _emit_event(
            on_event,
            {
                "type": "fetch_done",
                "fetched": len(sources),
                "budget": fetch_budget,
            },
        )
        return sources

    async def _load_upload_chunks(
        self, expert_id: int
    ) -> list[tuple[TextChunk, int]]:
        """Chunks belonging to user-supplied sources that survived the reset.

        Returns ``(TextChunk, chunk_db_id)`` pairs in the shape the graph stage
        consumes. ``context_text`` is not needed — graph extraction reads the
        chunk text — so it is not selected.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id, c.text, c.sequence_n, c.chunk_meta
                FROM source_chunks c
                JOIN sources s ON s.id = c.source_id
                WHERE c.expert_id = $1 AND s.discovered_via = 'upload'
                ORDER BY c.source_id, c.sequence_n
                """,
                expert_id,
            )
        out: list[tuple[TextChunk, int]] = []
        for r in rows:
            meta = r["chunk_meta"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            out.append((
                TextChunk(
                    text=r["text"],
                    sequence_n=r["sequence_n"],
                    chunk_meta=meta or {},
                ),
                r["id"],
            ))
        return out

    async def _count_upload_sources(self, expert_id: int) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                """
                SELECT COUNT(*) FROM sources
                WHERE expert_id = $1 AND passed = true AND discovered_via = 'upload'
                """,
                expert_id,
            ) or 0

    async def _fetch_with_refill(
        self,
        ranked: list[TriagedCandidate],
        budget: int,
        caps: dict[SourceType, int],
    ) -> list[RawSource]:
        """Fetch full content for ranked candidates until the budget is met.

        Works down the ranked list in concurrent waves; failed fetches free
        their slot so lower-ranked candidates get a chance. Per-type caps are
        enforced on successful fetches.
        """
        fetcher_by_type = {
            _FETCHER_SOURCE_TYPES[name]: fetcher for name, (fetcher, _) in self._fetchers.items()
        }
        results: list[RawSource] = []
        counts: dict[SourceType, int] = {}
        idx = 0
        while len(results) < budget and idx < len(ranked):
            wave: list[SourceCandidate] = []
            while idx < len(ranked) and len(wave) < min(_FETCH_CONCURRENCY, budget - len(results)):
                candidate = ranked[idx].candidate
                idx += 1
                cap = caps.get(candidate.source_type, budget)
                if counts.get(candidate.source_type, 0) >= cap:
                    continue
                counts[candidate.source_type] = counts.get(candidate.source_type, 0) + 1
                wave.append(candidate)
            if not wave:
                break
            fetched = await asyncio.gather(
                *[_safe_fetch_candidate(fetcher_by_type.get(c.source_type), c) for c in wave]
            )
            for candidate, source in zip(wave, fetched, strict=True):
                if source is None:
                    counts[candidate.source_type] -= 1
                else:
                    results.append(source)
        return results

    async def _fill_coverage_gaps(
        self,
        topic: str,
        key_concepts: list[str],
        passed: list[ValidatedSource],
        dropped: list[DroppedSource],
        on_event: EventCallback | None,
    ) -> tuple[list[ValidatedSource], list[DroppedSource]]:
        """One targeted re-search for key concepts no passing source covers.

        Without this, a fetcher outage or an aggressive validation round silently
        produces an expert with blind spots on its own syllabus.
        """
        coverage = _compute_coverage(key_concepts, passed)
        gaps = [c for c in key_concepts if coverage[c] == 0][:_GAPFILL_MAX_CONCEPTS]
        if not gaps:
            return passed, dropped

        gap_fetchers = {
            name: fetcher
            for name, (fetcher, _) in self._fetchers.items()
            if name in _GAPFILL_FETCHERS
        }
        if not gap_fetchers:
            return passed, dropped

        await _emit_event(on_event, {"type": "coverage_gaps", "gaps": gaps})

        async def _gap_fetch(name: str, fetcher, concept: str) -> list[RawSource]:
            # Targeted and tiny — search and fetch directly, no triage round-trip.
            candidates = await _safe_search(
                name,
                fetcher,
                f"{topic} {concept}",
                _GAPFILL_RESULTS_PER_QUERY,
            )
            fetched = await asyncio.gather(
                *[
                    _safe_fetch_candidate(fetcher, c)
                    for c in candidates[:_GAPFILL_RESULTS_PER_QUERY]
                ]
            )
            results = [src for src in fetched if src is not None]
            for src in results:
                src.metadata.setdefault("discovered_via", f"gapfill:{concept}")
            return results

        nested = await asyncio.gather(
            *[
                _gap_fetch(name, fetcher, concept)
                for concept in gaps
                for name, fetcher in gap_fetchers.items()
            ]
        )

        seen_urls = {vs.url.rstrip("/").lower() for vs in passed}
        seen_urls |= {ds.raw.url.rstrip("/").lower() for ds in dropped}
        extra_raw = [
            src
            for src in _deduplicate_by_url([s for batch in nested for s in batch])
            if src.url.rstrip("/").lower() not in seen_urls
        ]

        added = 0
        if extra_raw:
            extra_passed, extra_dropped = await validate_sources(
                topic,
                extra_raw,
                key_concepts,
                on_result=lambda r: _emit_event(on_event, {"type": "source_validated", **r}),
            )
            passed = passed + extra_passed
            dropped = dropped + extra_dropped
            added = len(extra_passed)

        remaining = _compute_coverage(key_concepts, passed)
        still_uncovered = [c for c in gaps if remaining[c] == 0]
        await _emit_event(
            on_event,
            {
                "type": "gapfill_done",
                "added": added,
                "still_uncovered": still_uncovered,
            },
        )
        if still_uncovered:
            logger.info(
                "Coverage gaps remain after gap-fill for %r: %s",
                topic,
                ", ".join(still_uncovered),
            )
        return passed, dropped

    async def _persist_sources(
        self,
        expert_id: int,
        passed: list[ValidatedSource],
        dropped: list[DroppedSource],
    ) -> list[int]:
        """Write all sources to DB. Returns DB IDs for passed sources only."""
        passed_ids: list[int] = []
        validator_model = settings.FAST_MODEL
        async with self._pool.acquire() as conn, conn.transaction():
            for vs in passed:
                row = await conn.fetchrow(
                    """
                        INSERT INTO sources
                            (expert_id, source_type, url, title, author,
                             quality_score, relevance_score, content_type,
                             difficulty, key_claims, passed,
                             validator_model, rubric_version,
                             covered_concepts, discovered_via, source_tier)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,true,$11,$12,$13::jsonb,$14,$15)
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
                    validator_model,
                    RUBRIC_VERSION,
                    json.dumps(vs.covered_concepts),
                    vs.raw.metadata.get("discovered_via", "plan"),
                    # NULL when the validator didn't classify it — see migration 020.
                    vs.source_tier,
                )
                passed_ids.append(row["id"])

            for ds in dropped:
                await conn.execute(
                    """
                        INSERT INTO sources
                            (expert_id, source_type, url, title, author,
                             quality_score, relevance_score, passed, drop_reason,
                             validator_model, rubric_version, discovered_via)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,false,$8,$9,$10,$11)
                        """,
                    expert_id,
                    ds.raw.source_type.value,
                    ds.raw.url,
                    ds.raw.title,
                    ds.raw.author,
                    ds.quality_score,
                    ds.relevance_score,
                    ds.drop_reason,
                    validator_model,
                    RUBRIC_VERSION,
                    ds.raw.metadata.get("discovered_via", "plan"),
                )

        return passed_ids


def resolve_execution(expert: Expert) -> BuildExecution:
    """Pick the cost/latency policy for a build that didn't state one.

    ``BUILD_EXECUTION_DEFAULT=auto`` (the default) reads it off the expert: an
    expert that has never produced a persona has never finished a build, so
    somebody is sitting in front of the progress log waiting for their first
    expert — that build runs live. Anything else is a rebuild or a refresh of an
    expert that already works, which nobody is blocked on, so it takes the
    half-price batched path.

    ``reset_build_state`` deletes sources, chunks and the graph but leaves the
    persona, so this signal survives the reset the worker does immediately
    before calling us. A retry of a *failed* first build still reads as a first
    build, which is what we want: the user is still waiting.
    """
    configured = settings.BUILD_EXECUTION_DEFAULT
    if configured in (BuildExecution.INTERACTIVE, BuildExecution.BACKGROUND):
        return BuildExecution(configured)
    if configured != "auto":
        logger.warning(
            "Unknown BUILD_EXECUTION_DEFAULT=%r — falling back to 'auto'", configured
        )
    return BuildExecution.BACKGROUND if expert.persona_name else BuildExecution.INTERACTIVE


async def _plan_research(topic: str) -> dict:
    """One call on the strong model — the brief shapes the whole corpus.

    Always returns a normalised plan: every fetcher has non-empty queries and a
    clamped weight, even when the model call fails (fallback = raw topic, weight 1).
    """
    raw_plan: dict = {}
    try:
        client = get_anthropic_client()
        resp = await client.messages.create(  # type: ignore[call-overload]
            model=settings.PLAN_MODEL,
            max_tokens=1500,
            system=_PLAN_SYSTEM,
            tools=[_PLAN_TOOL],
            tool_choice={"type": "tool", "name": "create_research_plan"},
            messages=[{"role": "user", "content": f"Topic: {topic}"}],
        )
        block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
        raw_plan = dict(block.input)
    except Exception as exc:
        logger.warning("Research planning failed, falling back to raw topic: %s", exc)

    plan = _normalise_plan(raw_plan, topic)
    logger.info(
        "Research plan for %r: concepts=[%s] weights={%s} must_have=[%s]",
        topic,
        ", ".join(plan["key_concepts"]),
        ", ".join(f"{n}:{p['weight']:g}" for n, p in plan["fetcher_plans"].items()),
        "; ".join(w["title"] for w in plan["must_have_works"]),
    )
    return plan


def _normalise_plan(raw_plan: dict, topic: str) -> dict:
    """Coerce a model-produced plan into a safe, complete shape."""
    fetcher_plans: dict[str, dict] = {}
    raw_fetcher_plans = raw_plan.get("fetcher_plans") or {}
    for name in _FETCHER_NAMES:
        raw = raw_fetcher_plans.get(name) or {}
        queries: list[str] = []
        for q in raw.get("queries") or []:
            if (
                isinstance(q, str)
                and q.strip()
                and q.strip().casefold() not in {d.casefold() for d in queries}
            ):
                queries.append(q.strip())
        try:
            weight = float(raw.get("weight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        fetcher_plans[name] = {
            "queries": queries[:_MAX_QUERIES_PER_FETCHER] or [topic],
            "weight": min(max(weight, 0.0), 2.0),
        }

    key_concepts = [
        c.strip() for c in raw_plan.get("key_concepts") or [] if isinstance(c, str) and c.strip()
    ][:8]

    must_have_works = []
    for work in raw_plan.get("must_have_works") or []:
        if isinstance(work, dict) and isinstance(work.get("title"), str) and work["title"].strip():
            author = work.get("author")
            must_have_works.append(
                {
                    "title": work["title"].strip(),
                    "author": author.strip() if isinstance(author, str) else "",
                }
            )

    return {
        "fetcher_plans": fetcher_plans,
        "key_concepts": key_concepts,
        "must_have_works": must_have_works[:4],
    }


def _route_must_have_works(plan: dict) -> None:
    """Turn named canonical works into extra exact-title queries on a search fetcher.

    Each extra query gets at least one result slot in the fan-out, so a must-have
    work costs little budget but is actively looked for.
    """
    work_queries = [f'"{w["title"]}" {w["author"]}'.strip() for w in plan["must_have_works"]]
    if not work_queries:
        return
    target = "exa" if settings.EXA_API_KEY else "web"
    fetcher_plan = plan["fetcher_plans"][target]
    existing = {q.casefold() for q in fetcher_plan["queries"]}
    fetcher_plan["queries"] += [q for q in work_queries if q.casefold() not in existing]
    fetcher_plan["weight"] = max(fetcher_plan["weight"], 1.0)


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

    async with httpx.AsyncClient(timeout=15, headers=ARXIV_HEADERS) as client:
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
                    if ref_arxiv_id and ref_arxiv_id not in seen_ids and citation_count >= 50:
                        candidates.append(
                            {
                                "arxiv_id": ref_arxiv_id,
                                "title": cited.get("title", ""),
                                "citations": citation_count,
                            }
                        )
                        seen_ids.add(ref_arxiv_id)
            except Exception as exc:
                logger.debug("Semantic Scholar references failed for %s: %s", arxiv_id, exc)

    if not candidates:
        return []

    candidates.sort(key=lambda x: x["citations"], reverse=True)
    extra: list[RawSource] = []

    async with httpx.AsyncClient(timeout=30, headers=ARXIV_HEADERS, follow_redirects=True) as http:
        for cand in candidates[:max_extra]:
            aid = cand["arxiv_id"]
            try:

                def _lookup(a: str = aid) -> list:
                    return list(arxiv_lib.Client().results(arxiv_lib.Search(id_list=[a])))

                papers = await asyncio.to_thread(_lookup)
                if not papers:
                    continue
                paper = papers[0]
                url = paper.entry_id
                if url in seen_urls:
                    continue
                full_text = await fetch_ar5iv(http, aid)
                text = (
                    full_text[:MAX_FULL_TEXT]
                    if len(full_text) >= MIN_FULL_TEXT
                    else f"{paper.title}\n\n{paper.summary}"
                )
                extra.append(
                    RawSource(
                        source_type=SourceType.ARXIV,
                        url=url,
                        title=paper.title,
                        author=", ".join(str(a) for a in paper.authors[:3]),
                        text=text,
                        metadata={
                            "arxiv_id": aid,
                            "published": str(paper.published),
                            "categories": paper.categories,
                            "full_text": len(full_text) >= MIN_FULL_TEXT,
                            "snowballed": True,
                            "discovered_via": "snowball",
                            "citations": cand["citations"],
                        },
                    )
                )
                seen_urls.add(url)
                logger.info("Snowballed: %r (%d citations)", paper.title, cand["citations"])
            except Exception as exc:
                logger.debug("Snowball fetch failed for arXiv:%s: %s", aid, exc)

    return extra


_RESOLVE_THRESHOLD = 0.93


async def _resolve_entities(
    expert_id: int,
    graph_repo: GraphRepository,
    on_event: EventCallback | None = None,
) -> int:
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

    # Node embeddings are persisted at insert time; only nodes that missed
    # embedding (e.g. an API blip during insert) get re-embedded here. Batched
    # so a graph whose embeddings all failed at insert can't overflow one call.
    missing = [i for i, n in enumerate(nodes) if n.get("embedding") is None]
    if missing:
        texts = [
            node_embedding_text(nodes[i]["label"], nodes[i].get("description")) for i in missing
        ]
        try:
            fresh = await embed_in_batches(texts)
        except Exception as exc:
            logger.warning("Entity resolution embedding failed: %s", exc)
            return 0
        for i, emb in zip(missing, fresh, strict=True):
            nodes[i]["embedding"] = emb

    matrix = np.array([np.asarray(n["embedding"], dtype=np.float32) for n in nodes])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    normalized = matrix / norms
    sim = normalized @ normalized.T  # (N, N)

    # Find all above-threshold pairs at C speed (upper triangle, i < j). The old
    # pure-Python O(N²) double loop had no ``await`` on the common no-merge path,
    # so on a large graph it blocked the event loop — starving the job heartbeat
    # and freezing the process — for the whole pass. np.where keeps row-major
    # order (increasing i, then j), preserving the original merge semantics.
    rows, cols = np.where(np.triu(sim >= _RESOLVE_THRESHOLD, k=1))

    merged_away: set[int] = set()
    merge_count = 0

    for i, j in zip(rows.tolist(), cols.tolist(), strict=True):
        keep_id, drop_id = nodes[i]["id"], nodes[j]["id"]
        if keep_id in merged_away or drop_id in merged_away:
            continue
        await graph_repo.merge_nodes(expert_id, keep_id, drop_id)
        merged_away.add(drop_id)
        merge_count += 1
        logger.debug(
            "Merged node %r → %r (sim=%.3f)",
            labels[j],
            labels[i],
            float(sim[i, j]),
        )
        if on_event and merge_count % 25 == 0:
            await _emit_event(on_event, {"type": "resolve_progress", "merged": merge_count})

    if merge_count:
        logger.info(
            "Entity resolution: merged %d duplicate nodes for expert %d",
            merge_count,
            expert_id,
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


async def _safe_search(name: str, fetcher, query: str, max_results: int) -> list[SourceCandidate]:
    try:
        return await fetcher.search(query, max_results)
    except Exception as exc:
        logger.warning("Fetcher %r search failed: %s", name, exc)
        return []


async def _safe_fetch_candidate(fetcher, candidate: SourceCandidate) -> RawSource | None:
    if fetcher is None:
        return None
    try:
        return await fetcher.fetch(candidate)
    except Exception as exc:
        logger.warning("Full fetch failed for %r: %s", candidate.url, exc)
        return None


_PERSONA_TOOL: dict[str, Any] = {
    "name": "generate_persona",
    "description": "Generate a named expert persona grounded in the corpus.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                # The UI titles any persona that comes back bare (see
                # web/lib/persona.ts), so an untitled name is not a broken
                # build — asking here just means the stored name and the
                # displayed one agree.
                "description": (
                    "Expert's full name, prefixed with the honorific 'Dr.' — "
                    "e.g. 'Dr. Elena Vasquez'."
                ),
            },
            "bio": {
                "type": "string",
                "description": (
                    "2-3 SHORT sentences, scannable in five seconds: what they "
                    "specialize in and their angle on it. Plain and concrete — "
                    "no compound sentences stacking multiple clauses, no "
                    "throat-clearing ('with a career spanning...', 'has spent "
                    "years...'), no restating the topic name back. Write it "
                    "the way a conference program blurbs a speaker, not the "
                    "way an academic CV opens."
                ),
            },
            "style": {
                "type": "string",
                "description": (
                    "A system-prompt block, in the second person, describing how "
                    "this expert TEACHES: how they open an explanation, the "
                    "framings and analogies they characteristically reach for, "
                    "the kind of worked example they use, what they insist "
                    "matters most and what they consider a distraction, and how "
                    "they talk to someone new to the subject. Positive voice "
                    "instructions only — write what they do, never a list of "
                    "rules about sourcing, citation, hedging, or uncertainty."
                ),
            },
        },
        "required": ["name", "bio", "style"],
    },
}

# The persona is the expert's teaching voice, and nothing else. It used to be
# asked for "how the expert cites, qualifies claims, and handles uncertainty",
# which reliably produced personas whose defining trait was hedging — a voice
# that then argued with the answer-shape rules on every turn. Sourcing
# discipline belongs to the grounding contract (chat/grounding.py), which is
# absolute and needs no help from the persona; what the persona is for is the
# thing a contract cannot supply, which is how a good teacher explains.
_PERSONA_SYSTEM = (
    "You are creating a named expert persona that will be the voice of a "
    "grounded AI tutor. The persona must reflect what this corpus actually "
    "contains — a specialist in these particular materials, not a generic "
    "authority. Name them as a doctor of the subject ('Dr. <given> <family>'), "
    "since every expert here is addressed by name and title.\n\n"
    "Write the style block as a teacher's profile: how they explain a hard idea "
    "to a newcomer, the analogies and framings they return to, the worked "
    "examples they favour, what they emphasise and what they cut. Make it "
    "concrete and specific to this corpus — a reader should be able to tell "
    "this expert from any other expert in the same field.\n\n"
    "Do not write anything about citation, sourcing, evidence quality, "
    "qualifying claims, or handling uncertainty. Separate absolute rules govern "
    "all of that, and duplicating them here produces a hedging, evasive voice "
    "instead of a teaching one.\n\n"
    "The bio and the style block have different jobs and should not read alike. "
    "The bio is what a reader skims in five seconds to decide if this is the "
    "right expert — keep it short and plain. The style block is what actually "
    "governs how the expert teaches, so it can be as thorough as that job "
    "requires; length there is not the problem the bio has."
)


def _persona_digest(sources: list[tuple[str, str, float | None, list[str]]]) -> str:
    """One line per source: title, kind, quality, and its leading claims.

    Takes plain tuples rather than ``ValidatedSource`` so a persona can be
    regenerated from the ``sources`` table long after the build that produced it.
    """
    lines = []
    for title, content_type, quality, claims in sources[:15]:
        q = f"Q:{quality:.1f}" if quality is not None else "Q:—"
        lines.append(f"- {title} ({content_type}, {q}): " + "; ".join(claims[:2]))
    return "\n".join(lines)


async def generate_persona(
    topic: str,
    sources: list[tuple[str, str, float | None, list[str]]],
    top_nodes: list[dict],
) -> dict:
    """Generate ``{name, bio, style}`` from a corpus digest.

    Public because personas outlive the build that made them: an expert built
    under an older persona prompt can be re-voiced without re-fetching,
    re-validating and re-embedding its whole corpus. See
    ``ExpertService.regenerate_persona``.
    """
    concept_list = ", ".join(n["label"] for n in top_nodes[:20])

    client = get_anthropic_client()
    resp = await client.messages.create(  # type: ignore[call-overload]
        model=settings.CLAUDE_MODEL,
        # 1024 was enough when `style` was a sentence about how the expert cites.
        # A teaching profile is several paragraphs, and `style` is the last field
        # in the schema — too small a budget truncates the tool call and returns
        # {name, bio} with no style at all, which is a KeyError at the call site
        # rather than a degraded persona.
        max_tokens=3072,
        system=_PERSONA_SYSTEM,
        tools=[_PERSONA_TOOL],
        tool_choice={"type": "tool", "name": "generate_persona"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Topic: {topic}\n\n"
                    f"Sources ingested:\n{_persona_digest(sources)}\n\n"
                    f"Top concepts extracted: {concept_list}"
                ),
            }
        ],
    )
    block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
    persona = dict(block.input)

    # A tool call cut off by the token budget still parses — it just arrives
    # missing its trailing fields. Catching it here names the cause; letting it
    # through surfaces as a KeyError three frames away, at whichever caller
    # happened to read `persona["style"]` first.
    missing = [k for k in ("name", "bio", "style") if not persona.get(k)]
    if missing:
        raise RuntimeError(
            f"Persona generation returned no {', '.join(missing)} "
            f"(stop_reason={resp.stop_reason!r}). Raise max_tokens if this is "
            "'max_tokens'."
        )
    return persona


async def _generate_persona(
    topic: str,
    passed: list[ValidatedSource],
    top_nodes: list[dict],
) -> dict:
    """Persona for a build that has the validated sources in hand."""
    return await generate_persona(
        topic,
        [(vs.title, vs.content_type, vs.quality_score, vs.key_claims) for vs in passed],
        top_nodes,
    )


# A corpus that is overwhelmingly tertiary answers everything second-hand: it
# can tell you what people say about a subject and never what the subject is.
# Below this share of classified sources, the expert is worth building but the
# user should know what they are getting *before* they chat with it — the failure
# it produces is subtle, and reads as the model being evasive rather than as the
# corpus being thin.
_TERTIARY_WARN_SHARE = 0.7
# Under this many classified sources the share is noise, not a finding.
_TERTIARY_WARN_MIN_CLASSIFIED = 3


def corpus_tier_warning(passed: list[ValidatedSource]) -> dict | None:
    """A build warning if the passing corpus is overwhelmingly second-hand.

    Pure, so the threshold is testable without a build. Sources the validator
    could not classify are counted separately and never held against the corpus:
    an unclassified source is unknown, not tertiary.
    """
    counts = {tier: 0 for tier in ("primary", "secondary", "tertiary")}
    unclassified = 0
    for vs in passed:
        if vs.source_tier in counts:
            counts[vs.source_tier] += 1
        else:
            unclassified += 1

    classified = sum(counts.values())
    if classified < _TERTIARY_WARN_MIN_CLASSIFIED:
        return None
    if counts["tertiary"] / classified < _TERTIARY_WARN_SHARE:
        return None

    return {
        "type": "corpus_warning",
        "reason": "mostly_tertiary",
        "primary": counts["primary"],
        "secondary": counts["secondary"],
        "tertiary": counts["tertiary"],
        "unclassified": unclassified,
        "classified": classified,
        "message": (
            f"{counts['tertiary']} of {classified} classified sources are "
            "summaries, reviews or overviews rather than primary texts or "
            "substantive analysis. This expert will answer second-hand. "
            "Rebuilding with more specific sources — the works themselves, "
            "original papers, or practitioners' own writing — would help."
        ),
    }


def _compute_coverage(
    key_concepts: list[str],
    passed: list[ValidatedSource],
) -> dict[str, int]:
    """How many passing sources cover each key concept."""
    coverage = {c: 0 for c in key_concepts}
    for vs in passed:
        for concept in vs.covered_concepts:
            if concept in coverage:
                coverage[concept] += 1
    return coverage


def _avg_quality(passed: list[ValidatedSource]) -> float | None:
    if not passed:
        return None
    scores = [vs.quality_score for vs in passed if vs.quality_score is not None]
    return round(sum(scores) / len(scores), 2) if scores else None


def _deduplicate_by_url[T: (RawSource, SourceCandidate)](items: list[T]) -> list[T]:
    """Remove items with duplicate URLs, keeping the first occurrence."""
    seen: set[str] = set()
    unique: list[T] = []
    for item in items:
        key = item.url.rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


async def _emit_event(cb: EventCallback | None, event: dict) -> None:
    if cb:
        await cb(event)
