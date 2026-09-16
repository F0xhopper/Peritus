"""Build pipeline coordinator — orchestrates all 5 stages with progress callbacks.

Stages:
  0. PLAN    — Claude produces a research brief: per-fetcher queries + budget
               weights, key concepts the corpus must cover, must-have works
  1-2. DISCOVER — an iterating loop, not a single pass. Each round runs:
       search: planned fetchers over-search (~3× budget) for cheap candidates
       dedup:  identity → URL → (after fetch) content fingerprint
       triage: Haiku ranks candidates against the brief; junk and near-dups drop
       fetch:  top candidates get full content, refilling from lower ranks on failure
       validate: Claude scores each source and tags the key concepts it covers
       coverage: measure the corpus against the tier's per-concept targets
     Round 0's queries come from the plan. Later rounds read the corpus that
     exists — the concepts furthest from target become feedback queries in the
     field's own vocabulary, and the accepted scholarly sources are snowballed
     forwards and backwards through their citations. The loop stops when the
     targets are met, the rounds run out, the discovery budget is spent, a round
     finds nothing new, or acceptance collapses — and it says which.
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

**Budget.** Discovery is bounded twice: by a count of sources (a ceiling that
rarely binds) and by an estimate of what the sources it has committed to will
cost to ingest, against the tier's discovery budget. The count is a safety rail;
the money is the real limit, because cost scales with characters and a corpus of
sixty mixed sources and a corpus of a hundred and fifty open-access papers can
cost the same.
"""

import asyncio
import contextlib
import json
import math
import time
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import asyncpg
from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam

from peritus.billing.domain import discovery_budget_usd
from peritus.billing.metering import current_meter
from peritus.core.config import settings
from peritus.core.exceptions import BuildError, IncompleteBuildError
from peritus.core.logging import get_logger
from peritus.experts.build.constants import (
    _ACCEPTANCE_COLLAPSE,
    _ACCEPTANCE_MIN_SAMPLE,
    _BASE_FETCH_BUDGET,
    _FETCH_CONCURRENCY,
    _FETCHER_NAMES,
    _FETCHER_SOURCE_TYPES,
    _FLOOR_RELAX_MIN,
    _LOOP_FETCHERS,
    _LOOP_MAX_CONCEPTS,
    _LOOP_ROUND_BUDGET_SHARE,
    _PERSONA_ATTEMPTS,
    _PLAN_QUERY_FETCHERS,
    _PRIORITY_BUDGET_SHARE,
    _ROUND0_BUDGET_SHARE,
    OUTCOME_BELOW_FLOOR,
    OUTCOME_BUDGET,
    OUTCOME_CAPPED,
    OUTCOME_CONTENT_DUPLICATE,
    OUTCOME_FAILED,
    OUTCOME_FETCHED,
    OUTCOME_NEAR_DUPLICATE,
    OUTCOME_NOT_ENGLISH,
    OUTCOME_NOT_REACHED,
    STOP_ACCEPTANCE_COLLAPSED,
    STOP_BUDGET_EXHAUSTED,
    STOP_LOOP_DISABLED,
    STOP_MAX_ROUNDS,
    STOP_NO_NEW_CANDIDATES,
    STOP_SOURCE_LIMIT,
    STOP_TARGETS_MET,
)
from peritus.experts.build.planning import (
    _plan_research,
    _route_must_have_works,
)
from peritus.experts.build.policy import (
    _fetch_sort_key,
    _graph_chunk_limit,
    _ingest_estimate,
    _log_previous_build,
    _metered_spend,
    _primary_text_ceilings,
    _priority_reservation,
    _search_breadth,
    _type_caps,
    discovery_loop_enabled,
    resolve_execution,
)
from peritus.experts.build.reconcile import (
    _merge_same_volume,
    _reconcile_claims,
    _resolve_entities,
)
from peritus.experts.build.selection import (
    DiscoveryOutcome,
    _as_score,
    _boosted_must_have_titles,
    _carry_candidate_metadata,
    _count_outcomes,
    _enforce_ceiling,
    _fetcher_for,
    _is_skipped,
    _outcome_metadata,
    _planned_works,
    _quietly,
    _raise_if_provider_down,
    _safe_fetch_candidate,
    _safe_search,
)
from peritus.experts.composition import (
    apply_composition_caps,
    corpus_composition,
    top_concept_shares,
)
from peritus.experts.coverage import ConceptCoverage, CoverageReport, compute_coverage
from peritus.experts.domain import Expert
from peritus.experts.feedback import feedback_queries, suggest_primary_texts
from peritus.experts.picture import PictureSkipped, find_picture
from peritus.experts.picture_repository import ExpertPictureRepository
from peritus.experts.repository import ExpertRepository
from peritus.graph.extractor import extract_graph_from_chunks
from peritus.graph.repository import GraphRepository
from peritus.infrastructure.anthropic_batch import (
    BuildExecution,
    build_execution,
    current_execution,
    record_provider_error,
)
from peritus.infrastructure.anthropic_client import get_anthropic_client, tool_input
from peritus.infrastructure.embeddings import embed_in_batches
from peritus.infrastructure.wikimedia import WikimediaClient
from peritus.ingestion.chunker import TextChunk
from peritus.ingestion.pipeline import ingest_sources
from peritus.search.readiness import Readiness, set_readiness
from peritus.sources.canonical import (
    FOUND_SECTIONS,
    FOUND_WHOLE,
    SCOPE_CONCEPT,
    SCOPE_OVERALL,
    MustHaveWork,
    WorkResolution,
    concept_named_texts,
    figure_outcomes,
    must_have_outcomes,
    resolve_works,
)
from peritus.sources.capture import capture_for_screening
from peritus.sources.dedup import (
    SeenSet,
    deduplicate_by_url,
    deduplicate_candidates,
    deduplicate_sources_by_content,
    normalise_url,
)
from peritus.sources.domain import (
    FIGURE_OWN_VOICE,
    NAMED_MISSING,
    DroppedSource,
    RawSource,
    SourceCandidate,
    SourceType,
    ValidatedSource,
)
from peritus.sources.fetchers.arxiv import ArxivFetcher
from peritus.sources.fetchers.base import (
    HEALTHY_STATUSES,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_SKIPPED,
    TRANSIENT_STATUSES,
    SearchOutcome,
    worst_status,
)
from peritus.sources.fetchers.exa import ExaFetcher
from peritus.sources.fetchers.gutenberg import GutenbergFetcher
from peritus.sources.fetchers.openalex import OpenAlexFetcher
from peritus.sources.fetchers.pdf import PdfFetcher
from peritus.sources.fetchers.pubmed import PubmedFetcher
from peritus.sources.fetchers.reddit import RedditFetcher
from peritus.sources.fetchers.thought_leaders import ThoughtLeadersFetcher
from peritus.sources.fetchers.web import WebFetcher
from peritus.sources.fetchers.wikipedia import WikipediaFetcher
from peritus.sources.fetchers.youtube import YoutubeFetcher
from peritus.sources.language import is_expected_language
from peritus.sources.snowball import snowball
from peritus.sources.substance import substance_of
from peritus.sources.triage import (
    MIN_TRIAGE_SCORE,
    TRIAGE_SNIPPET_CHARS,
    TriagedCandidate,
    rank_candidates,
    triage_candidates,
)
from peritus.sources.validator import RUBRIC_VERSION, validate_sources

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
        source_filter: list[str] | None = None,
        execution: BuildExecution | None = None,
        job_id: int | None = None,
    ) -> None:
        """``execution=None`` resolves per build (see :func:`resolve_execution`);
        pass a mode explicitly to force one — e.g. a scheduled refresh that should
        always take the half-price path regardless of what the expert looks like.

        ``job_id`` is only used to name screening capture files (see
        :mod:`peritus.sources.capture`); the builder does not otherwise know or
        care that it is running under a job."""
        self._pool = pool
        self._repo = ExpertRepository(pool)
        self._graph_repo = GraphRepository(pool)
        self._source_filter = source_filter
        self._execution = execution
        self._job_id = job_id
        # Sources dropped by content fingerprinting rather than by the
        # validator. Held here so they reach the ledger as explicit drops with a
        # reason instead of disappearing between fetching and validation.
        self._content_duplicates: list[DroppedSource] = []
        # The picture finder, started off `plan_ready` and awaited before the
        # persona stage. Held on the instance so the `finally` in `build` can
        # cancel it when the build is cancelled or fails.
        self._picture_task: asyncio.Task | None = None
        # Discovery's working state, reset at the start of every discovery run:
        # each fetcher's last search outcome, what the canonical-work resolver
        # found, and the expert the screening ledger is being written for.
        self._fetcher_status: dict[str, str] = {}
        self._canonical: list[WorkResolution] = []
        self._ledger_expert_id: int | None = None
        # From the research plan: what counts as primary for this topic (handed
        # to the validator), and the text ceilings for resolved works.
        self._primary_definition: str = ""
        self._text_ceilings: dict[str, int] = {}
        # Works looked for beyond the plan's own: primary texts a later round
        # suggested, and substitutes for works that cannot be had. And the URLs
        # triage ranked, so a work whose every hit was dropped can be retried.
        self._suggested_works: list[MustHaveWork] = []
        self._queued_substitutes: list[MustHaveWork] = []
        self._ranked_urls: set[str] = set()
        self._fetchers: dict[str, tuple[Any, int]] = {}

    def _build_fetchers(
        self,
        multiplier: float,
        source_filter: list[str] | None,
        weights: dict[str, float] | None = None,
        figures: list[dict] | None = None,
        topic: str = "",
    ):
        """The active fetchers and their fetch quotas.

        ``figures`` are the plan's named figures: the thought-leader channel
        searches for them in their own voice rather than asking a second, blind
        model call who matters for the topic.
        """
        weights = weights or {}
        all_fetchers = {
            "wikipedia": (WikipediaFetcher(), 3),
            "gutenberg": (GutenbergFetcher(), 4),
            "arxiv": (ArxivFetcher(), 2),
            "pdf": (PdfFetcher(), 3),
            "youtube": (YoutubeFetcher(), 3),
            "exa": (ExaFetcher(), 5),
            "web": (WebFetcher(), 3),
            # 2, not 5: forum threads are not as valuable as curated web results
            # by default. The planner can still weight it up for a practitioner
            # topic.
            "reddit": (RedditFetcher(), 2),
            "thought_leaders": (ThoughtLeadersFetcher(figures, topic), 3),
            "pubmed": (PubmedFetcher(), 2),
            "openalex": (OpenAlexFetcher(), 3),
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
        await set_readiness(self._pool, expert.id, Readiness.PENDING)
        return await self._run(expert, on_event, lambda: self._build(expert, on_event))

    async def resume(
        self,
        expert: Expert,
        from_readiness: Readiness,
        on_event: EventCallback | None = None,
    ) -> BuildResult:
        """Finish a build whose corpus an earlier attempt already paid for.

        A retry used to start from nothing: the worker wiped the corpus before
        every attempt, so a persona call that failed four seconds into its stage
        destroyed a finished PRO build (66 sources, 2,921 graph nodes) and then
        re-ran planning into the same provider refusal. Readiness is recorded
        as each stage lands, so a retry can start where the last attempt got to:

        - ``graph_ready`` — only the persona is missing; run that and the gate.
        - ``chat_ready``  — chunks are embedded; rebuild the graph from them
          (whatever part of it the failed attempt wrote is discarded first),
          then the persona.

        Readiness is *not* reset to pending here: the corpus stays chattable
        for the whole resumed attempt, which is the point.
        """
        if from_readiness is Readiness.PENDING:
            return await self.build(expert, on_event)
        await _emit_event(
            on_event, {"type": "build_resumed", "from_readiness": from_readiness.value}
        )
        return await self._run(
            expert, on_event, lambda: self._resume(expert, from_readiness, on_event)
        )

    async def _run(
        self,
        expert: Expert,
        on_event: EventCallback | None,
        body: Callable[[], Coroutine[Any, Any, BuildResult]],
    ) -> BuildResult:
        """The execution policy, fixed for the whole run, around a build body."""
        execution = self._execution or resolve_execution(expert)
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
        try:
            with build_execution(execution):
                return await body()
        finally:
            # A cancelled or failed build must not leave an HTTP client and a
            # pending write behind it. Cancelling a task that already finished
            # is a no-op, which is the common case.
            task = self._picture_task
            self._picture_task = None
            if task is not None and not task.done():
                task.cancel()

    async def _build(
        self,
        expert: Expert,
        on_event: EventCallback | None = None,
    ) -> BuildResult:
        topic = expert.topic

        # Stage 0: Research planning
        await _emit_event(on_event, {"type": "stage", "stage": 0, "name": "plan"})
        plan = await _plan_research(topic, expert.config.max_key_concepts)
        _route_must_have_works(plan)
        key_concepts = plan["key_concepts"]
        if not key_concepts:
            # Stop here rather than proceeding on the raw-topic fallback. The
            # concepts are the syllabus: triage scores against them, validation
            # scores against them, and gap-fill exists to close holes in them.
            # A build without them cannot produce a ready expert, so running the
            # rest is spending money on a foregone conclusion — one such attempt
            # reached the graph stage and $1.70 before failing.
            _raise_if_provider_down("Research planning")
            raise IncompleteBuildError(["key concepts (research planning failed)"])
        await self._repo.update_key_concepts(expert.id, key_concepts)
        await _quietly("store the research plan", self._repo.update_research_plan(expert.id, plan))
        # The whole plan, not only the concepts: the queries, the weights and the
        # must-have works used to exist only in a worker log line, so a build's
        # search could not be reproduced or argued with afterwards. Clients read
        # `key_concepts` and ignore the rest.
        await _emit_event(
            on_event,
            {
                "type": "plan_ready",
                "key_concepts": key_concepts,
                "facets": plan.get("facets", []),
                "fetcher_plans": plan["fetcher_plans"],
                "must_have_works": plan["must_have_works"],
                "concept_primary_texts": plan.get("concept_primary_texts", []),
                "primary_source_definition": plan.get("primary_source_definition", ""),
                "figures": plan.get("figures", []),
                "orientation": plan.get("orientation") or {"overviews": [], "note": ""},
            },
        )

        # The expert's picture. Started here, the moment the topic and the key
        # concepts both exist, so the rail's tile stops being a monogram within
        # seconds rather than at the end of a build that takes minutes. It runs
        # beside discovery, never blocks it, and cannot fail it — see
        # `_find_and_store_picture`.
        self._picture_task = asyncio.create_task(
            self._find_and_store_picture(expert, topic, key_concepts, on_event)
        )

        weights = {name: p["weight"] for name, p in plan["fetcher_plans"].items()}
        self._fetchers = self._build_fetchers(
            expert.config.source_multiplier,
            self._source_filter,
            weights,
            plan.get("figures"),
            topic,
        )

        # Stages 1–2: the discovery loop (search → dedup → triage → fetch →
        # validate → coverage, repeated until the targets are met or the money
        # or the rounds run out).
        outcome = await self._run_discovery(expert, topic, plan, on_event)
        passed, dropped = outcome.passed, outcome.dropped
        await self._repo.update_build_summary(expert.id, outcome.summary())

        if not passed:
            # Before blaming the corpus, check whether the validator ever ran.
            # An empty `passed` means either "the model judged everything below
            # threshold" or "the model was unreachable", and only the first is
            # about the topic. Telling someone with an empty credit balance to
            # pick a different topic sends them to debug the wrong thing.
            _raise_if_provider_down("Source validation")
            raise BuildError("All sources failed validation. Try a different topic or sources.")

        # Corpus composition, while the user is still watching the build. A
        # weak-but-passing corpus is not a build failure, so this is a warning
        # event rather than a raise — but it has to arrive before they start
        # trusting the expert's answers.
        warning = corpus_tier_warning(passed)
        if warning:
            logger.warning(
                "Expert %d corpus is %d/%d tertiary",
                expert.id,
                warning["tertiary"],
                warning["classified"],
            )
            await _emit_event(on_event, warning)

        source_db_ids = await self._persist_sources(expert.id, passed, dropped)
        await _quietly(
            "link the screening ledger to its sources",
            self._repo.link_candidate_screenings(expert.id, self._job_id),
        )
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
        graph_skipped = 0
        for chunk_ids, raw_chunks in ingested:
            all_chunk_ids.extend(chunk_ids)
            # Everything is embedded; only the first chunks of a very long source
            # go to graph extraction — see GRAPH_MAX_CHUNKS_PER_SOURCE.
            kept = _graph_chunk_limit(len(chunk_ids))
            graph_skipped += len(chunk_ids) - kept
            all_chunks_for_graph.extend(zip(raw_chunks[:kept], chunk_ids[:kept], strict=True))
        if graph_skipped:
            logger.info(
                "Graph extraction skips %d chunk(s) past %d per source; they are embedded "
                "and retrievable, and not read for concepts",
                graph_skipped,
                settings.GRAPH_MAX_CHUNKS_PER_SOURCE,
            )

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

        return await self._enrich_and_finish(
            expert,
            chunks_for_graph=all_chunks_for_graph,
            persona_sources=[
                (vs.title, vs.content_type, vs.quality_score, vs.key_claims) for vs in passed
            ],
            total_sources=total_sources,
            total_chunks=total_chunks,
            avg_quality=avg_quality,
            dropped_count=len(dropped),
            on_event=on_event,
        )

    async def _resume(
        self,
        expert: Expert,
        from_readiness: Readiness,
        on_event: EventCallback | None,
    ) -> BuildResult:
        """The enrichment stages only, off the corpus already in the database."""
        current = await self._repo.get_by_id(expert.id) or expert
        persona_sources = await self._repo.passed_source_digest(expert.id)
        if not persona_sources:
            raise IncompleteBuildError(["a corpus (nothing to resume from)"])

        chunks_for_graph: list[tuple[TextChunk, int]] | None = None
        if from_readiness is Readiness.CHAT_READY:
            # A graph stage that died part-way may have written some of its
            # nodes. The graph is built whole, so it is cleared whole.
            await self._graph_repo.delete_graph(expert.id)
            chunks_for_graph = await self._load_chunks(expert.id)
            if not chunks_for_graph:
                raise IncompleteBuildError(["chunks (nothing to resume from)"])

        logger.info(
            "Resuming expert %d from %s: %d source(s), %d chunk(s)",
            expert.id,
            from_readiness.value,
            current.source_count,
            current.chunk_count,
        )
        return await self._enrich_and_finish(
            expert,
            chunks_for_graph=chunks_for_graph,
            persona_sources=persona_sources,
            total_sources=current.source_count,
            total_chunks=current.chunk_count,
            avg_quality=current.avg_quality,
            dropped_count=0,
            on_event=on_event,
            existing_graph=(current.node_count, current.edge_count),
        )

    async def _enrich_and_finish(
        self,
        expert: Expert,
        *,
        chunks_for_graph: list[tuple[TextChunk, int]] | None,
        persona_sources: list[tuple[str, str, float | None, list[str]]],
        total_sources: int,
        total_chunks: int,
        avg_quality: float | None,
        dropped_count: int,
        on_event: EventCallback | None,
        existing_graph: tuple[int, int] = (0, 0),
    ) -> BuildResult:
        """Graph, persona and the completeness gate, for a chat-ready corpus.

        ``chunks_for_graph=None`` means the graph already exists (a resume from
        ``graph_ready``) and ``existing_graph`` carries its counts.
        """
        topic = expert.topic

        # ── Enrichment ───────────────────────────────────────────────────────
        # From here on the expert already answers questions. Each stage below
        # degrades rather than raising, so the corpus keeps the readiness it has
        # reached; the completeness gate at the end decides whether the build
        # succeeded. A retry of a build that fails the gate resumes from that
        # readiness (see `resume`) rather than refetching the corpus.

        node_count, edge_count = existing_graph
        graph_built = chunks_for_graph is None
        if chunks_for_graph is not None:
            node_count, edge_count, graph_built = await self._graph_stage(
                expert, chunks_for_graph, on_event
            )

        await self._repo.update_counts(
            expert.id,
            source_count=total_sources,
            chunk_count=total_chunks,
            node_count=node_count,
            edge_count=edge_count,
            avg_quality=avg_quality,
        )

        if graph_built and chunks_for_graph is not None:
            # ── Graph-ready ──────────────────────────────────────────────────
            # Retrieval transparently upgrades from here: the same chat request
            # now finds anchor nodes for its hits, so passages arrive with
            # neighbouring concepts, relationships, and contradiction flags. On
            # a degraded graph the expert simply stays chat-ready.
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

        # In any real build this finished minutes ago, during discovery. The
        # await exists so `picture_ready` is in the durable log before `done`,
        # which is what a client replaying the log from seq 0 depends on.
        await self._await_picture()

        await _emit_event(on_event, {"type": "stage", "stage": 5, "name": "persona"})
        persona_name: str | None = None
        # Retried in place. The persona is one cheap call, and it is now required
        # for the expert to be ready — so letting a single blip here condemn a
        # finished corpus to a full rebuild would be absurdly expensive. The
        # graph stage above is not retried this way: its calls already retry
        # individually inside gather_claude_calls, and re-running all of it costs
        # more than re-running the build.
        for attempt in range(1, _PERSONA_ATTEMPTS + 1):
            try:
                top_nodes = await self._graph_repo.get_top_nodes(expert.id, 20)
                persona = await _generate_persona(topic, persona_sources, top_nodes)
                await self._repo.update_persona(
                    expert.id,
                    persona_name=persona["name"],
                    persona_bio=persona["bio"],
                    persona_style=persona["style"],
                )
                persona_name = persona["name"]
                await _emit_event(on_event, {"type": "persona_ready", "name": persona_name})
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                record_provider_error(exc)
                logger.warning(
                    "Persona generation attempt %d/%d failed for expert %d (%s: %s)",
                    attempt,
                    _PERSONA_ATTEMPTS,
                    expert.id,
                    type(exc).__name__,
                    exc,
                    exc_info=attempt == _PERSONA_ATTEMPTS,
                )
                if attempt < _PERSONA_ATTEMPTS:
                    await asyncio.sleep(2 ** (attempt - 1))

        # ── Completeness gate ────────────────────────────────────────────────
        # An expert is "ready" only with all three: concepts, a concept graph,
        # and a persona. Short of that the job does not report success, so the
        # expert is never advertised as ready on a half-finished build. The
        # corpus survives the raise only because the worker's retry resumes from
        # the recorded readiness instead of resetting — it used to reset, and a
        # four-second persona failure wiped a finished PRO build that way.
        #
        # A persona that failed because the provider refused every request is
        # not worth a retry at all: the retry meets the same refusal. That
        # raises BuildError, which the worker does not retry, and says why.
        missing: list[str] = []
        if not graph_built or node_count <= 0:
            missing.append("a concept graph")
        if not persona_name:
            missing.append("a persona/description")
        if missing:
            logger.error(
                "Expert %d built %d source(s) and %d chunk(s) but is INCOMPLETE: "
                "missing %s — not marking ready",
                expert.id,
                total_sources,
                total_chunks,
                " and ".join(missing),
            )
            if not persona_name:
                _raise_if_provider_down("Persona generation")
            raise IncompleteBuildError(missing)

        return BuildResult(
            expert_id=expert.id,
            source_count=total_sources,
            dropped_count=dropped_count,
            chunk_count=total_chunks,
            node_count=node_count,
            edge_count=edge_count,
            avg_quality=avg_quality,
            persona_name=persona_name,
        )

    async def _graph_stage(
        self,
        expert: Expert,
        chunks_for_graph: list[tuple[TextChunk, int]],
        on_event: EventCallback | None,
    ) -> tuple[int, int, bool]:
        """Extract, resolve and reconcile the concept graph.

        Returns ``(node_count, edge_count, built)``. Degrades rather than
        raising: a graph failure leaves a chat-ready corpus standing, and the
        completeness gate decides what that means for the build.
        """
        # Stage 4: Graph extraction
        total_batches = math.ceil(len(chunks_for_graph) / settings.GRAPH_BATCH_SIZE)
        await _emit_event(
            on_event, {"type": "stage", "stage": 4, "name": "graph", "total_batches": total_batches}
        )

        chunks_only = [c for c, _ in chunks_for_graph]
        ids_only = [i for _, i in chunks_for_graph]

        async def _on_graph_batch(labels: list[str], edge_count: int) -> None:
            await _emit_event(
                on_event, {"type": "graph_batch_done", "labels": labels, "edges": edge_count}
            )

        node_count = edge_count = 0
        try:
            extractions = await extract_graph_from_chunks(
                expert.topic, chunks_only, ids_only, on_batch=_on_graph_batch
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

            # Reconciliation: which claims support, contradict or qualify which.
            # Deliberately after entity resolution — it groups claims by the
            # concept they are `about`, and before the merge that concept is
            # still several near-duplicate nodes, each holding one source's view
            # of it. It is also the only pass that sees more than one source at
            # a time, which is why the per-batch extractor no longer guesses at
            # these relations at all.
            await _emit_event(on_event, {"type": "stage", "stage": 4, "name": "reconcile"})
            relation_count = await _reconcile_claims(
                expert.topic, expert.id, self._graph_repo, on_event
            )
            edge_count += relation_count

            # Edge ordering is evidence counted off the corpus, not a weight the
            # model asserted, so it is computed here once the graph is final.
            await self._graph_repo.recompute_edge_evidence(expert.id)
            return node_count, edge_count, True
        except asyncio.CancelledError:
            raise  # cancellation/shutdown is the worker's business, not a degrade
        except Exception as exc:
            logger.warning("Graph extraction failed for expert %d: %s", expert.id, exc)
            await _emit_event(
                on_event,
                {
                    "type": "stage_degraded",
                    "stage": "graph",
                    "message": (
                        "Concept-graph extraction failed. The corpus is retrievable, "
                        "but an expert is not ready without its graph — this build "
                        f"will be retried. ({exc})"
                    ),
                },
            )
        return node_count, edge_count, False

    # ── the expert's picture ────────────────────────────────────────────────

    async def _find_and_store_picture(
        self,
        expert: Expert,
        topic: str,
        key_concepts: list[str],
        on_event: EventCallback | None,
    ) -> None:
        """Find a licensed picture of the subject and store it. Never raises.

        Everything about this is deliberately outside the build's contract. It
        is not a stage, it does not participate in the completeness gate, and
        the only trace it leaves either way is one durable event — so the build
        log says which picture was chosen and why, or why there is none, and an
        expert with no picture is simply an expert that still shows its
        monogram.

        The one exception re-raised is ``CancelledError``: cancellation is the
        worker shutting the build down, and swallowing it would leave this
        coroutine running after the build it belongs to has gone.
        """
        if not settings.PICTURE_ENABLED:
            await _emit_event(on_event, {"type": "picture_skipped", "reason": "disabled"})
            return

        pictures = ExpertPictureRepository(self._pool)
        try:
            # A rebuild does not re-find: the topic has not changed, and the
            # owner may have chosen this one. Only an explicit refresh does.
            if await pictures.exists(expert.id):
                return

            async with WikimediaClient() as client:
                found = await find_picture(client, topic, key_concepts)
            await pictures.upsert(expert.id, found, chosen_by="build")
        except asyncio.CancelledError:
            raise
        except PictureSkipped as skip:
            await _emit_event(on_event, {"type": "picture_skipped", "reason": skip.reason})
            return
        except Exception as exc:
            logger.warning(
                "Picture search failed for expert %d (%s: %s)",
                expert.id,
                type(exc).__name__,
                exc,
            )
            await _emit_event(
                on_event, {"type": "picture_skipped", "reason": "provider_unavailable"}
            )
            return

        logger.info(
            "Picture for expert %d (%r): %s from %s (%s)",
            expert.id,
            expert.name,
            found.file_name,
            found.page_title,
            found.license,
        )
        await _emit_event(
            on_event,
            {
                "type": "picture_ready",
                "provider": found.provider,
                "title": found.page_title,
                "page_url": found.page_url,
                "license": found.license,
                "version": found.version,
            },
        )

    async def _await_picture(self) -> None:
        """Let the picture task finish, but never wait on it indefinitely.

        ``find_picture`` already carries its own deadline, so this second bound
        only covers the write and exists so a wedged task cannot hold a finished
        build open. A timeout here abandons the task; the `finally` in `build`
        cancels it.
        """
        task = self._picture_task
        if task is None or task.done():
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(task), timeout=settings.PICTURE_TIMEOUT)

    # ── the discovery loop ──────────────────────────────────────────────────

    async def _run_discovery(
        self,
        expert: Expert,
        topic: str,
        plan: dict,
        on_event: EventCallback | None,
    ) -> "DiscoveryOutcome":
        """Search, screen and validate until the corpus meets its targets.

        Round 0 is the plan's own queries over every active fetcher, plus the
        canonical works the plan named, looked for by title. Every round after it
        reads the corpus that exists: the concepts furthest from target become
        feedback queries in the field's own vocabulary, and the round's accepted
        scholarly sources are snowballed through their citations.

        The loop never re-plans. Round 0's brief — its key concepts and
        must-have works — is the standard the corpus is held to, and later
        rounds may only add queries against it. A loop allowed to rewrite its
        own syllabus can always declare itself finished.
        """
        config = expert.config
        target = config.coverage_target()
        key_concepts: list[str] = plan["key_concepts"]
        facets: list[dict] = plan.get("facets") or []
        figures: list[dict] = plan.get("figures") or []
        must_have_titles = [w["title"] for w in plan["must_have_works"]]
        works = _planned_works(plan, config)
        self._primary_definition = plan.get("primary_source_definition") or ""
        self._suggested_works = []
        self._text_ceilings = _primary_text_ceilings(expert.tier)
        self._ranked_urls = set()

        def _measure() -> CoverageReport:
            named = concept_named_texts(self._all_works(plan, config), _outcome_metadata(passed))
            return compute_coverage(
                key_concepts,
                passed,
                target,
                facets,
                {concept: entry["status"] for concept, entry in named.items()},
            )

        base_budget = max(5, round(_BASE_FETCH_BUDGET * config.source_multiplier))
        budget_usd = Decimal(str(discovery_budget_usd(expert.tier, cap_usd=self._cap_usd())))
        batched = (
            current_execution() is BuildExecution.BACKGROUND and settings.ANTHROPIC_BATCH_ENABLED
        )
        loop_enabled = discovery_loop_enabled()
        max_rounds = target.max_rounds if loop_enabled else 0
        min_rounds = min(target.min_rounds, max_rounds)

        _log_previous_build(expert, batched)
        await _quietly(
            "clear the previous attempt's screening ledger",
            self._repo.clear_candidate_screenings(expert.id, self._job_id),
        )
        self._ledger_expert_id = expert.id
        self._fetcher_status = {}
        self._canonical = []
        self._queued_substitutes = []

        # Caps are computed once, from the whole build's ceiling, and their counts
        # persist across rounds — a cap applied per round would let a type take
        # its full share again in every one of them, which is the flooding the
        # cap exists to prevent.
        caps = _type_caps(self._fetchers, base_budget)
        type_counts: dict[SourceType, int] = {}

        seen = SeenSet()
        passed: list[ValidatedSource] = []
        dropped: list[DroppedSource] = []
        coverage = _measure()
        committed_usd = Decimal(0)
        remaining_count = base_budget
        stop_reason = STOP_MAX_ROUNDS if max_rounds else STOP_LOOP_DISABLED
        round_n = 0
        # Rounds that actually fetched and validated something. Distinct from
        # ``round_n``, which is the index of the round being *set up* — a round
        # that finds no new candidates and breaks before running must not be
        # reported as a round that ran.
        rounds_run = 0

        while True:
            round_budget_usd = budget_usd - committed_usd
            if round_n == 0:
                queries_by_fetcher = {
                    name: list(plan["fetcher_plans"].get(name, {}).get("queries") or [topic])
                    for name in self._fetchers
                }
                extra_candidates = await self._resolve_canonical(works, on_event, round_n)
                round_budget = base_budget
                weakest: list[ConceptCoverage] = []
                if min_rounds:
                    # Money for the guaranteed round: see _ROUND0_BUDGET_SHARE.
                    round_budget_usd = min(round_budget_usd, budget_usd * _ROUND0_BUDGET_SHARE)
            else:
                # Every target met, and the round runs anyway because the tier
                # guarantees it: it searches for depth where the corpus is
                # thinnest instead of for targets it has already reached. Either
                # way the concepts are taken a facet at a time, so one heavy
                # facet's neighbours cannot take the whole round.
                weakest = coverage.weakest_by_facet(
                    _LOOP_MAX_CONCEPTS
                ) or coverage.thinnest_by_facet(_LOOP_MAX_CONCEPTS)
                queries_by_fetcher, extra_candidates = await self._plan_round(
                    topic, weakest, passed, seen, config, on_event, round_n, plan, key_concepts
                )
                if round_n == 1:
                    extra_candidates += await self._retry_canonical(works, passed, on_event)
                round_budget = min(
                    remaining_count,
                    math.ceil(_LOOP_ROUND_BUDGET_SHARE * base_budget),
                )
                if not queries_by_fetcher and not extra_candidates:
                    stop_reason = STOP_NO_NEW_CANDIDATES
                    break

            # A stage event per round, not once for the whole loop: the meter
            # attributes spend to whichever stage was last announced, and
            # round N's triage happens after round N-1's `validate`.
            await _emit_event(
                on_event, {"type": "stage", "stage": 1, "name": "discover", "round": round_n}
            )
            await _emit_event(
                on_event,
                {
                    "type": "round_started",
                    "round": round_n,
                    "budget": round_budget,
                    "budget_usd": float(budget_usd),
                    "round_budget_usd": float(round_budget_usd),
                    "targets": target.as_dict(),
                    "weakest": [c.concept for c in weakest],
                },
            )

            raw_sources, round_cost = await self._discovery_round(
                topic,
                plan,
                queries_by_fetcher,
                _boosted_must_have_titles(must_have_titles, round_n, self._canonical, passed),
                round_budget,
                round_budget_usd,
                seen,
                extra_candidates,
                caps,
                type_counts,
                on_event,
                round_n,
                batched,
            )
            committed_usd += round_cost
            remaining_count -= len(raw_sources)

            if not raw_sources:
                stop_reason = STOP_NO_NEW_CANDIDATES if round_n else stop_reason
                if round_n == 0:
                    raise BuildError("No sources discovered. Check API keys and network access.")
                break

            round_passed, round_dropped = await self._validate_round(
                expert, topic, raw_sources, key_concepts, on_event, round_n
            )
            unjudged = sum(
                1
                for d in round_dropped
                if d.drop_reason in ("validation error", "missing validation")
            )
            if unjudged and not round_passed:
                _raise_if_provider_down("Source validation")
            passed.extend(round_passed)
            dropped.extend(round_dropped)
            for source in raw_sources:
                seen.add_source(source)

            # Give back the budget reserved for sources validation rejected.
            # The estimate is made at fetch time, when nothing is known about
            # which sources will survive, so it necessarily covers everything
            # fetched — but only the accepted ones are ever ingested. Holding
            # the rejected ones' cost against the budget stops the loop about a
            # rejection-rate early: on a live STANDARD build it reserved $3.04
            # of a $3.00 budget for 60 fetched sources when the 48 that passed
            # were the only ones that would ever cost anything to ingest.
            ingested_cost = sum(_ingest_estimate(vs.raw, batched) for vs in round_passed)
            committed_usd -= round_cost - ingested_cost

            rounds_run += 1
            coverage = _measure()
            spent_usd = _metered_spend()
            await _emit_event(
                on_event,
                {
                    "type": "coverage_report",
                    "round": round_n,
                    "spent_usd": float(spent_usd),
                    "committed_usd": float(committed_usd),
                    "budget_usd": float(budget_usd),
                    **coverage.as_dict(),
                },
            )

            # ── stop conditions, in the order they become knowable ───────────
            # Over the sources the validator actually judged: an errored batch
            # says nothing about whether the search space is exhausted.
            judged = len(raw_sources) - unjudged
            acceptance = len(round_passed) / judged if judged else 1.0
            if coverage.met and key_concepts and round_n >= min_rounds:
                stop_reason = STOP_TARGETS_MET
                break
            if round_n >= max_rounds:
                stop_reason = STOP_LOOP_DISABLED if max_rounds == 0 else STOP_MAX_ROUNDS
                break
            if spent_usd + committed_usd >= budget_usd:
                stop_reason = STOP_BUDGET_EXHAUSTED
                break
            if remaining_count <= 0:
                stop_reason = STOP_SOURCE_LIMIT
                break
            if judged >= _ACCEPTANCE_MIN_SAMPLE and acceptance < _ACCEPTANCE_COLLAPSE:
                # The search space is exhausted: this round fetched real
                # sources and validation wanted almost none of them. Another
                # round buys more of the same.
                stop_reason = STOP_ACCEPTANCE_COLLAPSED
                break
            round_n += 1

        all_dropped = dropped + self._content_duplicates
        all_works = self._all_works(plan, config)
        accepted_metadata = _outcome_metadata(passed)
        must_have = must_have_outcomes(all_works, self._canonical, accepted_metadata)
        outcome = DiscoveryOutcome(
            passed=passed,
            dropped=all_dropped,
            coverage=coverage,
            rounds=rounds_run,
            stop_reason=stop_reason,
            spent_usd=float(_metered_spend()),
            committed_usd=float(committed_usd),
            budget_usd=float(budget_usd),
            corpus=corpus_composition(
                passed,
                all_dropped,
                key_concepts,
                must_have,
                named_texts=concept_named_texts(all_works, accepted_metadata),
                figures=figure_outcomes(figures, all_works, accepted_metadata),
            ),
            channels={
                name: status
                for name, status in self._fetcher_status.items()
                if status not in HEALTHY_STATUSES
            },
        )
        await _emit_event(on_event, {"type": "discovery_done", **outcome.summary()})
        return outcome

    async def _resolve_canonical(
        self,
        works: list[MustHaveWork],
        on_event: EventCallback | None,
        round_n: int,
    ) -> list[SourceCandidate]:
        """Look for the plan's must-have works by title. Never raises.

        The candidates it returns enter triage like any other, already marked
        ``fetch_priority`` — they do not depend on a score — and carry whether
        each one is the whole work or a section of it.
        """
        if not works:
            return []
        exa = ExaFetcher() if settings.EXA_API_KEY else None
        try:
            resolutions = await resolve_works(
                works,
                exa_search=exa.search if exa is not None else None,
                max_chars=self._text_ceilings,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Canonical work resolution failed: %s", exc, exc_info=True)
            return []
        by_key = {r.work.key: r for r in self._canonical}
        for resolution in resolutions:
            by_key[resolution.work.key] = resolution
        self._canonical = list(by_key.values())
        await _emit_event(
            on_event,
            {
                "type": "canonical_resolved",
                "round": round_n,
                "works": [r.as_dict() for r in resolutions],
            },
        )
        candidates = [c for r in resolutions for c in r.candidates]

        # A work that cannot legally be had, and was not found whole: its
        # substitute is looked for as a work of its own (docs/plans/syllabus.md,
        # 3.B). Resolved after, not beside, so a substitute is only paid for
        # when the work it stands in for is out of reach.
        queued = {w.key for w in self._queued_substitutes}
        substitutes = [
            r.work.substitute
            for r in resolutions
            if r.work.substitute is not None
            and not r.work.obtainable
            and not r.whole
            and r.work.substitute.key not in queued
        ]
        if substitutes:
            self._queued_substitutes += substitutes
            candidates += await self._resolve_canonical(substitutes, on_event, round_n)

        return _merge_same_volume(candidates, self._text_ceilings.get(SCOPE_OVERALL))

    async def _retry_canonical(
        self,
        works: list[MustHaveWork],
        passed: list[ValidatedSource],
        on_event: EventCallback | None,
    ) -> list[SourceCandidate]:
        """Round 1 looks again for works round 0 could not find whole.

        Two reasons qualify. A route that timed out or errored — one that
        answered "nothing" is not asked again; that is the canonical-work half
        of retrying failed channels in later rounds. And a work whose every hit
        was dropped before fetch: before triage stopped treating a work's
        volumes as near-duplicates of each other, the Summa's second part was
        found and dropped that way, and nothing looked for it again. Dropped hits
        never entered the seen set, so looking again finds them again.
        """
        failed = {r.work.title for r in self._canonical if r.route_errors} | {
            r.work.title
            for r in self._canonical
            if r.candidates
            and not any(normalise_url(c.url) in self._ranked_urls for c in r.candidates)
        }
        if not failed:
            return []
        found = {
            o["title"]
            for o in must_have_outcomes(works, self._canonical, _outcome_metadata(passed))
            if o["status"] in (FOUND_WHOLE, FOUND_SECTIONS)
        }
        retry = [w for w in works if w.title in failed and w.title not in found]
        return await self._resolve_canonical(retry, on_event, 1) if retry else []

    def _cap_usd(self) -> float | None:
        """The hard spend cap this build is running under, if the meter knows it."""
        meter = current_meter()
        if meter is None or meter.cap_usd is None:
            return None
        return float(meter.cap_usd)

    async def _plan_round(
        self,
        topic: str,
        weakest: list[ConceptCoverage],
        passed: list[ValidatedSource],
        seen: SeenSet,
        config,
        on_event: EventCallback | None,
        round_n: int,
        plan: dict,
        key_concepts: list[str],
    ) -> tuple[dict[str, list[str]], list[SourceCandidate]]:
        """Queries and citation candidates for a follow-up round."""
        queries_by_fetcher: dict[str, list[str]] = {}
        author_candidates: list[SourceCandidate] = []
        if weakest:
            works = self._all_works(plan, config)
            accepted_metadata = _outcome_metadata(passed)
            named = concept_named_texts(works, accepted_metadata)
            feedback = await feedback_queries(
                topic,
                weakest,
                passed,
                top_concept_shares(passed, key_concepts) if key_concepts else None,
                facet_of={
                    concept: facet["name"]
                    for facet in plan.get("facets") or []
                    for concept in facet.get("concepts") or []
                },
                missing_texts={
                    concept: entry["texts"]
                    for concept, entry in named.items()
                    if entry["status"] == NAMED_MISSING
                },
                voiceless_figures=[
                    f["name"]
                    for f in figure_outcomes(plan.get("figures") or [], works, accepted_metadata)
                    if f["status"] != FIGURE_OWN_VOICE
                ],
            )
            per_concept, authors = feedback.queries, feedback.authors
            if authors:
                author_candidates = await self._search_authors(authors, topic, on_event, round_n)
            flat: list[str] = []
            for concept in weakest:
                for query in per_concept.get(concept.concept, []):
                    if query not in flat:
                        flat.append(query)
            status = self._fetcher_status
            loop_fetchers = [
                n
                for n in self._fetchers
                if n in _LOOP_FETCHERS or status.get(n) in TRANSIENT_STATUSES | {STATUS_ERROR}
            ]
            retried = [n for n in loop_fetchers if n not in _LOOP_FETCHERS]
            queries_by_fetcher = {
                name: (
                    list(plan.get("fetcher_plans", {}).get(name, {}).get("queries") or [topic])
                    if name in _PLAN_QUERY_FETCHERS
                    else list(flat)
                )
                for name in loop_fetchers
            }
            await _emit_event(
                on_event,
                {
                    "type": "feedback_queries",
                    "round": round_n,
                    "concepts": [c.concept for c in weakest],
                    "without_primary": [c.concept for c in weakest if not c.has_primary],
                    "authors": authors,
                    "queries": flat,
                    "fetchers": loop_fetchers,
                    "retried_fetchers": retried,
                },
            )

        # Primary texts for the concepts that still have none, looked up by
        # title. The queries above go to search engines, which answer with
        # scholarship about a subject far more readily than with its own texts.
        primary_candidates: list[SourceCandidate] = []
        lacking = [c.concept for c in weakest if not c.has_primary]
        limit = config.concept_primary_texts
        if lacking and limit > 0 and config.coverage_require_primary:
            tried = [r.work.title for r in self._canonical]
            suggestions = await suggest_primary_texts(
                topic, self._primary_definition, lacking, tried
            )
            new_works = [MustHaveWork.from_plan(t, SCOPE_CONCEPT) for t in suggestions][:limit]
            if new_works:
                await _emit_event(
                    on_event,
                    {
                        "type": "primary_texts_suggested",
                        "round": round_n,
                        "concepts": lacking,
                        "texts": suggestions[: len(new_works)],
                    },
                )
                self._suggested_works += new_works
                primary_candidates = await self._resolve_canonical(new_works, on_event, round_n)

        # Snowball from what the corpus has already accepted. Seeded from every
        # accepted scholarly source, not just this round's, so a two-hop tier
        # reaches the references of references without extra machinery.
        candidates: list[SourceCandidate] = []
        if config.snowball_max_per_round > 0 and round_n <= config.snowball_hops:
            try:
                candidates = await snowball(
                    passed, seen, max_candidates=config.snowball_max_per_round
                )
            except Exception as exc:
                logger.warning("Snowball failed in round %d: %s", round_n, exc)
                candidates = []
            if candidates:
                await _emit_event(
                    on_event,
                    {
                        "type": "snowball_done",
                        "round": round_n,
                        "added": len(candidates),
                        "backward": sum(
                            1
                            for c in candidates
                            if c.metadata.get("discovered_via") == "snowball:backward"
                        ),
                        "forward": sum(
                            1
                            for c in candidates
                            if c.metadata.get("discovered_via") == "snowball:forward"
                        ),
                    },
                )
        return queries_by_fetcher, primary_candidates + author_candidates + candidates

    def _all_works(self, plan: dict, config) -> list[MustHaveWork]:
        """Every work this discovery run has looked for: planned, suggested, substituted."""
        return _planned_works(plan, config) + self._suggested_works + self._queued_substitutes

    async def _search_authors(
        self,
        authors: list[str],
        topic: str,
        on_event: EventCallback | None,
        round_n: int,
    ) -> list[SourceCandidate]:
        """Writing *by* the authors the corpus cites and does not contain. Never raises.

        Through the thought-leader search, which excludes the encyclopedias and
        summary services and drops pages titled as entries about a person — raw
        web search answered an author's name with exactly those pages.
        """
        if "thought_leaders" not in self._fetchers:
            return []
        try:
            found = await ThoughtLeadersFetcher.search_people(
                [{"name": name, "why": "cited by the corpus, not yet in it"} for name in authors],
                topic,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Author search failed in round %d: %s", round_n, exc)
            return []
        for candidate in found:
            candidate.metadata.setdefault("discovered_via", "feedback:author")
        await _emit_event(
            on_event,
            {"type": "authors_searched", "round": round_n, "authors": authors, "added": len(found)},
        )
        return found

    async def _discovery_round(
        self,
        topic: str,
        plan: dict,
        queries_by_fetcher: dict[str, list[str]],
        must_have_titles: list[str],
        budget: int,
        budget_usd: Decimal,
        seen: SeenSet,
        extra_candidates: list[SourceCandidate],
        caps: dict[SourceType, int],
        type_counts: dict[SourceType, int],
        on_event: EventCallback | None,
        round_n: int,
        batched: bool,
    ) -> tuple[list[RawSource], Decimal]:
        """One round: search → dedup → triage → budgeted fetch → content dedup.

        Returns the fetched sources and the estimated ingest cost the round
        committed to, which is what the loop spends against its budget. Writes
        the round's screening ledger on the way out.
        """
        active = set(queries_by_fetcher)
        if round_n == 0:
            await _emit_event(
                on_event,
                {
                    "type": "discovery_started",
                    "fetchers": list(_FETCHER_NAMES),
                    "active": list(active),
                },
            )

        # One query for the identify-then-fetch fetchers: each query is a model
        # call that names books or people, and three of them per build asked the
        # same question three ways.
        _SINGLE_QUERY_FETCHERS = {"thought_leaders", "gutenberg"}
        status_by_fetcher = self._fetcher_status

        async def _search_one(
            name: str, fetcher, quota: int, attempt: int = 0
        ) -> tuple[str, SearchOutcome]:
            queries = queries_by_fetcher.get(name) or [topic]
            if name in _SINGLE_QUERY_FETCHERS:
                queries = queries[:1]
            per_query = _search_breadth(quota, len(queries))
            started = time.monotonic()
            outcomes = await asyncio.gather(
                *[_safe_search(name, fetcher, query, per_query) for query in queries]
            )
            candidates = deduplicate_by_url([c for o in outcomes for c in o.candidates])
            skipped, reason = _is_skipped(name, candidates)
            if candidates:
                status, error = STATUS_OK, ""
            elif skipped:
                status, error = STATUS_SKIPPED, reason
            else:
                status = worst_status([o.status for o in outcomes])
                error = next((o.error for o in outcomes if o.status == status and o.error), "")
            status_by_fetcher[name] = status
            await _emit_event(
                on_event,
                {
                    "type": "fetcher_done",
                    "round": round_n,
                    "name": name,
                    "count": len(candidates),
                    "skipped": skipped,
                    "reason": reason or error,
                    "status": status,
                    "error": error,
                    "attempt": attempt,
                    "elapsed": round(time.monotonic() - started, 1),
                    "queries": len(queries),
                },
            )
            return name, SearchOutcome(candidates, status, error)

        searched = dict(
            await asyncio.gather(
                *[
                    _search_one(name, fetcher, quota)
                    for name, (fetcher, quota) in self._fetchers.items()
                    if name in active
                ]
            )
        )
        # A channel that timed out or was rate-limited gets one more try, one at
        # a time so a retry is not itself another burst against a rate limit.
        # Gutendex timing out twice is then a status the loop can act on rather
        # than a coincidence.
        for name, outcome in list(searched.items()):
            if not outcome.transient:
                continue
            fetcher, quota = self._fetchers[name]
            await _emit_event(
                on_event,
                {
                    "type": "fetcher_retried",
                    "round": round_n,
                    "name": name,
                    "after": outcome.status,
                },
            )
            _, searched[name] = await _search_one(name, fetcher, quota, attempt=1)

        # Extra candidates first: URL de-duplication keeps the first copy it
        # sees, and a canonical work's or a co-cited snowball find's copy
        # carries what the plain search hit for the same URL does not — that it
        # is a must-have, whether it is the whole work, that it is a priority.
        pooled = list(extra_candidates) + [c for o in searched.values() for c in o.candidates]
        if not pooled:
            return [], Decimal(0)

        # Identity → URL, against everything the build has already considered.
        # This is where the same paper found as an arXiv preprint, a journal DOI
        # and a Semantic Scholar OA PDF becomes one candidate rather than three.
        candidates, dedup = deduplicate_candidates(pooled, seen)
        await _emit_event(on_event, {"type": "dedup_done", "round": round_n, **dedup.as_event()})
        if not candidates:
            return [], Decimal(0)

        # Triage — the same brief every round; only the queries change.
        triaged = await triage_candidates(
            topic,
            plan["key_concepts"],
            must_have_titles,
            candidates,
        )
        if triaged and all(t.model_score is None for t in triaged):
            # Nothing scored at all. If the provider refused the calls (an empty
            # credit balance, a revoked key) that is not a finding about the
            # candidates, and carrying on would build a corpus from priority
            # candidates alone and report it as a quality collapse.
            _raise_if_provider_down("Source triage")
        ranked = rank_candidates(triaged)
        for item in ranked:
            seen.add_candidate(item.candidate)
            self._ranked_urls.add(normalise_url(item.candidate.url))

        floor = settings.FETCH_SCORE_FLOOR
        reaching = sum(
            1 for t in ranked if t.score >= floor or t.candidate.metadata.get("fetch_priority")
        )
        needed = max(_FLOOR_RELAX_MIN, budget // 4)
        if round_n == 0 and reaching < needed and floor > settings.FETCH_SCORE_FLOOR_RELAXED:
            # A thin topic must not produce an empty round 0. Later rounds never
            # relax: by then the corpus exists, and an empty round is an answer.
            await _emit_event(
                on_event,
                {
                    "type": "floor_relaxed",
                    "round": round_n,
                    "floor": floor,
                    "relaxed_to": settings.FETCH_SCORE_FLOOR_RELAXED,
                    "reaching": reaching,
                    "needed": needed,
                },
            )
            floor = settings.FETCH_SCORE_FLOOR_RELAXED

        await _emit_event(
            on_event,
            {
                "type": "triage_done",
                "round": round_n,
                "candidates": len(candidates),
                "ranked": len(ranked),
                "budget": budget,
                "floor": floor,
                "above_floor": sum(
                    1
                    for t in ranked
                    if t.score >= floor or t.candidate.metadata.get("fetch_priority")
                ),
                "unscored": sum(1 for t in triaged if t.model_score is None),
            },
        )

        outcomes: dict[int, tuple[int | None, str]] = {}
        sources, committed = await self._fetch_with_refill(
            ranked,
            budget,
            caps,
            type_counts,
            budget_usd,
            batched,
            on_event,
            round_n,
            floor=floor,
            outcomes=outcomes,
        )

        # Content fingerprinting, on text that now exists. This is the
        # preprint-versus-published case that identity misses when one side has
        # no DOI: two records, no shared id, the same document.
        sources, duplicates = deduplicate_sources_by_content(sources, seen)
        duplicate_urls = {source.url for source, _ in duplicates}
        for source, of_url in duplicates:
            # Visible as a drop with a reason, not silently gone. A source that
            # disappears between fetching and validation is exactly the kind of
            # hole the screening ledger exists to close.
            self._content_duplicates.append(
                DroppedSource(
                    raw=source,
                    quality_score=0.0,
                    relevance_score=0.0,
                    drop_reason=f"duplicate of {of_url}",
                )
            )
        await _emit_event(
            on_event,
            {
                "type": "fetch_done",
                "round": round_n,
                "fetched": len(sources),
                "content_duplicates": len(duplicates),
                "budget": budget,
                "estimated_ingest_usd": float(committed),
                "outcomes": _count_outcomes(outcomes.values()),
            },
        )

        ranked_ids = {id(t.candidate) for t in ranked}
        rows = []
        for item in triaged:
            c = item.candidate
            if id(c) in outcomes:
                rank, fetch_outcome = outcomes[id(c)]
            elif id(c) in ranked_ids:
                rank, fetch_outcome = None, OUTCOME_NOT_REACHED
            elif item.score < MIN_TRIAGE_SCORE:
                rank, fetch_outcome = None, OUTCOME_BELOW_FLOOR
            else:
                rank, fetch_outcome = None, OUTCOME_NEAR_DUPLICATE
            if fetch_outcome == OUTCOME_FETCHED and c.url in duplicate_urls:
                fetch_outcome = OUTCOME_CONTENT_DUPLICATE
            rows.append(
                {
                    "round": round_n,
                    "source_type": c.source_type.value,
                    "url": c.url,
                    "title": c.title or c.url,
                    "author": c.author,
                    "snippet": (c.snippet or "")[:TRIAGE_SNIPPET_CHARS],
                    "discovered_via": c.metadata.get("discovered_via")
                    or ("plan" if round_n == 0 else "feedback"),
                    "model_score": item.model_score,
                    "domain_adjustment": item.domain_adjustment,
                    "triage_score": item.score,
                    "triage_status": item.status,
                    "fetch_rank": rank,
                    "fetch_outcome": fetch_outcome,
                }
            )
        expert_id = self._ledger_expert_id
        if expert_id is not None:
            await _quietly(
                "write the screening ledger",
                self._repo.insert_candidate_screenings(expert_id, self._job_id, rows),
            )
        return sources, committed

    async def _validate_round(
        self,
        expert: Expert,
        topic: str,
        raw_sources: list[RawSource],
        key_concepts: list[str],
        on_event: EventCallback | None,
        round_n: int,
    ) -> tuple[list[ValidatedSource], list[DroppedSource]]:
        """Validate one round's sources, capturing them first when asked to.

        The capture wraps the call rather than living inside the validator, so
        every path that validates — round 0, a later round, a future re-screen —
        is captured by construction.

        The composition caps apply here, per round, after the validator's
        verdict: abstract-only and tertiary sources beyond their share are
        dropped with a reason (see experts/composition.py).
        """
        await _emit_event(
            on_event,
            {
                "type": "stage",
                "stage": 2,
                "name": "validate",
                "round": round_n,
                "total": len(raw_sources),
            },
        )
        capture_for_screening(expert, self._job_id, raw_sources, topic, key_concepts, round_n)
        passed, dropped = await validate_sources(
            topic,
            raw_sources,
            key_concepts,
            primary_definition=self._primary_definition or None,
            on_result=lambda r: _emit_event(
                on_event, {"type": "source_validated", "round": round_n, **r}
            ),
            on_reviewed=lambda r: _emit_event(
                on_event, {"type": "source_reviewed", "round": round_n, **r}
            ),
        )
        passed, capped = apply_composition_caps(passed)
        if capped:
            dropped = dropped + capped
            await _emit_event(
                on_event,
                {
                    "type": "composition_capped",
                    "round": round_n,
                    "dropped": [{"title": d.raw.title, "reason": d.drop_reason} for d in capped],
                },
            )
        await _emit_event(
            on_event,
            {
                "type": "validate_done",
                "round": round_n,
                "passed": len(passed),
                "dropped": len(dropped),
                "capped": len(capped),
            },
        )
        return passed, dropped

    async def _load_upload_chunks(self, expert_id: int) -> list[tuple[TextChunk, int]]:
        """Chunks belonging to user-supplied sources that survived the reset."""
        return await self._load_chunks(expert_id, uploads_only=True)

    async def _load_chunks(
        self, expert_id: int, uploads_only: bool = False
    ) -> list[tuple[TextChunk, int]]:
        """Stored chunks, as ``(TextChunk, chunk_db_id)`` pairs for the graph stage.

        ``context_text`` is not needed — graph extraction reads the chunk text —
        so it is not selected.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id, c.source_id, c.text, c.sequence_n, c.chunk_meta
                FROM source_chunks c
                JOIN sources s ON s.id = c.source_id
                WHERE c.expert_id = $1
                  AND (NOT $2 OR s.discovered_via = 'upload')
                ORDER BY c.source_id, c.sequence_n
                """,
                expert_id,
                uploads_only,
            )
        out: list[tuple[TextChunk, int]] = []
        per_source: dict[int, int] = {}
        for r in rows:
            seen_for_source = per_source.get(r["source_id"], 0)
            per_source[r["source_id"]] = seen_for_source + 1
            if seen_for_source >= _graph_chunk_limit(seen_for_source + 1):
                continue
            meta = r["chunk_meta"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            out.append(
                (
                    TextChunk(
                        text=r["text"],
                        sequence_n=r["sequence_n"],
                        chunk_meta=meta or {},
                    ),
                    r["id"],
                )
            )
        return out

    async def _count_upload_sources(self, expert_id: int) -> int:
        async with self._pool.acquire() as conn:
            return (
                await conn.fetchval(
                    """
                SELECT COUNT(*) FROM sources
                WHERE expert_id = $1 AND passed = true AND discovered_via = 'upload'
                """,
                    expert_id,
                )
                or 0
            )

    async def _fetch_with_refill(
        self,
        ranked: list[TriagedCandidate],
        budget: int,
        caps: dict[SourceType, int],
        counts: dict[SourceType, int] | None = None,
        budget_usd: Decimal = Decimal(0),
        batched: bool = False,
        on_event: EventCallback | None = None,
        round_n: int = 0,
        *,
        floor: float = 0.0,
        outcomes: dict[int, tuple[int | None, str]] | None = None,
    ) -> tuple[list[RawSource], Decimal]:
        """Fetch full content for ranked candidates until a budget is met.

        Two budgets bind here, and the money one is the real one. The count is a
        ceiling that keeps a pathological round from running forever; the
        estimated ingest cost of what has been fetched is what actually stops
        the wave, because a 120,000-character monograph and a 2,000-character
        blog post are one unit each to a count and two orders of magnitude apart
        in what they cost to ingest.

        Beside both sits a quality bar: a candidate scored under ``floor`` is not
        fetched, however much count and money are left, unless something other
        than its score vouches for it (``fetch_priority``). Without the bar the
        queue walked down the ranked tail once the good types capped out and
        filled the last third of the Thomism corpus from it.

        Order is by triage score, with estimated cost as the tiebreaker and a
        reserved front rank for works the pipeline has independent evidence
        about — see :func:`_fetch_sort_key`, which explains why ordering by
        value per dollar emptied a Thomism corpus of Aquinas.

        Works down the ordered list in concurrent waves; failed fetches free
        their slot so lower-ranked candidates get a chance. Per-type caps are
        enforced on successful fetches; a must-have work is exempt from them.

        ``outcomes``, when passed, is filled with ``id(candidate) → (fetch rank,
        outcome)`` for the screening ledger.

        A ``fetch_progress`` event goes out after every wave. This used to be the
        build's one long silence — dozens of network fetches between
        ``triage_done`` and ``fetch_done``, with nothing in between — which made
        a dead worker and a working one look identical for as long as anyone
        cared to watch. One event per wave bounds that silence to a single wave,
        which SOURCE_FETCH_TIMEOUT in turn bounds in wall-clock time.
        """
        fetcher_by_type = {
            _FETCHER_SOURCE_TYPES[name]: fetcher for name, (fetcher, _) in self._fetchers.items()
        }
        ordered = sorted(ranked, key=lambda t: _fetch_sort_key(t, batched))
        record = outcomes if outcomes is not None else {}
        results: list[RawSource] = []
        # Shared with the caller across rounds when one is passed; a lone caller
        # (a test) gets a fresh tally.
        counts = {} if counts is None else counts
        committed = Decimal(0)
        idx = 0
        attempted = 0
        rank = 0
        stopped_on_money = False
        priority_committed = Decimal(0)
        reserved: dict[int, Decimal] = {}
        priority_ceiling = budget_usd * _PRIORITY_BUDGET_SHARE if budget_usd > 0 else None

        def _is_priority(candidate: SourceCandidate) -> bool:
            if not candidate.metadata.get("fetch_priority"):
                return False
            return priority_ceiling is None or priority_committed < priority_ceiling

        while len(results) < budget and idx < len(ordered):
            if budget_usd > 0 and committed >= budget_usd:
                stopped_on_money = True
                logger.info(
                    "Round %d stopped fetching at %d source(s): committed $%.3f of a "
                    "$%.3f estimated-ingest budget",
                    round_n,
                    len(results),
                    float(committed),
                    float(budget_usd),
                )
                break
            wave: list[TriagedCandidate] = []
            while idx < len(ordered) and len(wave) < min(_FETCH_CONCURRENCY, budget - len(results)):
                item = ordered[idx]
                candidate = item.candidate
                idx += 1
                priority = _is_priority(candidate)
                if item.score < floor and not priority:
                    record[id(candidate)] = (None, OUTCOME_BELOW_FLOOR)
                    continue
                rank += 1
                # A must-have work neither needs a slot in its type's share nor
                # takes one: the plan named it, and a Gutenberg volume must not
                # crowd out the Gutenberg texts triage chose.
                capped_type = not candidate.metadata.get("must_have_title")
                if capped_type:
                    cap = caps.get(candidate.source_type, budget)
                    if counts.get(candidate.source_type, 0) >= cap:
                        record[id(candidate)] = (rank, OUTCOME_CAPPED)
                        continue
                    counts[candidate.source_type] = counts.get(candidate.source_type, 0) + 1
                if priority:
                    # Reserved at admission, not at completion: a wave admits up
                    # to six candidates before any of them has a length.
                    reserved[id(candidate)] = _priority_reservation(candidate, batched)
                    priority_committed += reserved[id(candidate)]
                record[id(candidate)] = (rank, OUTCOME_NOT_REACHED)
                wave.append(item)
            if not wave:
                break
            fetched = await asyncio.gather(
                *[
                    _safe_fetch_candidate(_fetcher_for(t.candidate, fetcher_by_type), t.candidate)
                    for t in wave
                ]
            )
            attempted += len(wave)
            for item, source in zip(wave, fetched, strict=True):
                candidate = item.candidate
                position = record[id(candidate)][0]
                held = reserved.pop(id(candidate), Decimal(0))
                priority_committed -= held
                if source is None:
                    if not candidate.metadata.get("must_have_title"):
                        counts[candidate.source_type] -= 1
                    record[id(candidate)] = (position, OUTCOME_FAILED)
                elif not is_expected_language(source.text):
                    if not candidate.metadata.get("must_have_title"):
                        counts[candidate.source_type] -= 1
                    logger.info(
                        "Not %s: %r (%s) — dropped before validation",
                        settings.CORPUS_LANGUAGE,
                        candidate.title,
                        candidate.url,
                    )
                    record[id(candidate)] = (position, OUTCOME_NOT_ENGLISH)
                else:
                    _carry_candidate_metadata(candidate, source, item.score)
                    _enforce_ceiling(candidate, source)
                    results.append(source)
                    cost = _ingest_estimate(source, batched)
                    committed += cost
                    if held:
                        priority_committed += cost
                    record[id(candidate)] = (position, OUTCOME_FETCHED)
            await _emit_event(
                on_event,
                {
                    "type": "fetch_progress",
                    "round": round_n,
                    "fetched": len(results),
                    "attempted": attempted,
                    "budget": budget,
                    "estimated_ingest_usd": float(committed),
                },
            )
        for item in ordered[idx:]:
            candidate = item.candidate
            if id(candidate) in record:
                continue
            if item.score < floor and not _is_priority(candidate):
                record[id(candidate)] = (None, OUTCOME_BELOW_FLOOR)
            else:
                record[id(candidate)] = (
                    None,
                    OUTCOME_BUDGET if stopped_on_money else OUTCOME_NOT_REACHED,
                )
        return results, committed

    async def _persist_sources(
        self,
        expert_id: int,
        passed: list[ValidatedSource],
        dropped: list[DroppedSource],
    ) -> list[int]:
        """Write all sources to DB. Returns DB IDs for passed sources only.

        ``validator_model`` comes off each row's own verdict rather than from
        settings: with a borderline-band reviewer running, two models judge
        different sources in one build, and a column filled in from
        configuration would attribute both to whichever model the config names.
        """
        passed_ids: list[int] = []
        async with self._pool.acquire() as conn, conn.transaction():
            for vs in passed:
                ids = vs.identifiers
                meta = vs.raw.metadata
                row = await conn.fetchrow(
                    """
                        INSERT INTO sources
                            (expert_id, source_type, url, title, author,
                             quality_score, relevance_score, content_type,
                             difficulty, key_claims, passed,
                             validator_model, rubric_version,
                             covered_concepts, discovered_via, source_tier,
                             doi, arxiv_id, identifiers,
                             full_text_method, text_chars,
                             review_model, first_pass_quality, first_pass_relevance,
                             snowball_seed_urls, triage_score, substance, concept_depths)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,true,$11,$12,$13::jsonb,
                                $14,$15,$16,$17,$18::jsonb,$19,$20,$21,$22,$23,$24::jsonb,
                                $25,$26,$27::jsonb)
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
                    vs.validator_model or settings.FAST_MODEL,
                    RUBRIC_VERSION,
                    json.dumps(vs.covered_concepts),
                    meta.get("discovered_via", "plan"),
                    # NULL when the validator didn't classify it — see migration 020.
                    vs.source_tier,
                    ids.doi,
                    ids.arxiv_id,
                    json.dumps(ids.to_dict()) if not ids.is_empty() else None,
                    meta.get("full_text_method"),
                    len(vs.text),
                    vs.review_model,
                    vs.first_pass_quality,
                    vs.first_pass_relevance,
                    json.dumps(meta["snowball_seed_urls"])
                    if meta.get("snowball_seed_urls")
                    else None,
                    _as_score(meta.get("triage_score")),
                    vs.substance or substance_of(vs.raw),
                    json.dumps(vs.concept_depths) if vs.concept_depths else None,
                )
                passed_ids.append(row["id"])

            for ds in dropped:
                ids = ds.identifiers
                meta = ds.raw.metadata
                await conn.execute(
                    """
                        INSERT INTO sources
                            (expert_id, source_type, url, title, author,
                             quality_score, relevance_score, passed, drop_reason,
                             validator_model, rubric_version, discovered_via,
                             doi, arxiv_id, identifiers,
                             full_text_method, text_chars,
                             review_model, first_pass_quality, first_pass_relevance,
                             triage_score, substance)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,false,$8,$9,$10,$11,
                                $12,$13,$14::jsonb,$15,$16,$17,$18,$19,$20,$21)
                        """,
                    expert_id,
                    ds.raw.source_type.value,
                    ds.raw.url,
                    ds.raw.title,
                    ds.raw.author,
                    ds.quality_score,
                    ds.relevance_score,
                    ds.drop_reason,
                    ds.validator_model or settings.FAST_MODEL,
                    RUBRIC_VERSION,
                    meta.get("discovered_via", "plan"),
                    ids.doi,
                    ids.arxiv_id,
                    json.dumps(ids.to_dict()) if not ids.is_empty() else None,
                    meta.get("full_text_method"),
                    len(ds.raw.text),
                    ds.review_model,
                    ds.first_pass_quality,
                    ds.first_pass_relevance,
                    _as_score(meta.get("triage_score")),
                    substance_of(ds.raw),
                )

        return passed_ids


_PERSONA_TOOL: ToolParam = {
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
    resp = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        # 1024 was enough when `style` was a sentence about how the expert cites.
        # A teaching profile is several paragraphs, and `style` is the last field
        # in the schema — too small a budget truncates the tool call and returns
        # {name, bio} with no style at all, which is a KeyError at the call site
        # rather than a degraded persona.
        max_tokens=3072,
        system=_PERSONA_SYSTEM,
        tools=[_PERSONA_TOOL],
        tool_choice=ToolChoiceToolParam(type="tool", name="generate_persona"),
        messages=[
            MessageParam(
                role="user",
                content=(
                    f"Topic: {topic}\n\n"
                    f"Sources ingested:\n{_persona_digest(sources)}\n\n"
                    f"Top concepts extracted: {concept_list}"
                ),
            )
        ],
    )
    block = tool_input(resp) or {}
    persona = dict(block)

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
    sources: list[tuple[str, str, float | None, list[str]]],
    top_nodes: list[dict],
) -> dict:
    """The build's persona call — a seam tests patch."""
    return await generate_persona(topic, sources, top_nodes)


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
    counts = dict.fromkeys(("primary", "secondary", "tertiary"), 0)
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


def _avg_quality(passed: list[ValidatedSource]) -> float | None:
    if not passed:
        return None
    scores = [vs.quality_score for vs in passed if vs.quality_score is not None]
    return round(sum(scores) / len(scores), 2) if scores else None


async def _emit_event(cb: EventCallback | None, event: dict) -> None:
    _log_event(event)
    if cb:
        await cb(event)


# Wall-clock of the stage currently running, so each stage boundary can report
# how long the previous one took. A module-level single slot is enough: a build
# runs its stages in sequence, and concurrent builds each get their own copy
# through the same contextvar machinery the execution policy uses.
_stage_started: ContextVar[tuple[str, float] | None] = ContextVar(
    "peritus_stage_started", default=None
)

# Events worth a log line of their own. The rest (per-source validation, per-batch
# graph progress) are high-volume and already visible in the durable event log —
# logging those too would bury the ones that matter.
_LOGGED_EVENTS = frozenset(
    {
        "stage",
        "plan_ready",
        "picture_ready",
        "picture_skipped",
        "discovery_started",
        "round_started",
        "canonical_resolved",
        "fetcher_retried",
        "floor_relaxed",
        "composition_capped",
        "feedback_queries",
        "dedup_done",
        "triage_done",
        "fetch_done",
        "validate_done",
        "coverage_report",
        "discovery_done",
        "snowball_done",
        "corpus_warning",
        "chat_ready",
        "graph_ready",
        "entities_resolved",
        "claims_reconciled",
        "build_resumed",
        "persona_ready",
        "stage_degraded",
        "error",
        "cancelled",
        "done",
    }
)


def _clip(value: Any, limit: int = 160) -> str:
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}…(+{len(text) - limit} chars)"


def _log_event(event: dict) -> None:
    """Mirror significant build events into the process log.

    The durable event log is per-job and only readable through the API, which is
    exactly the wrong place to look when the question is "what was this worker
    doing when it died". These lines put the build's shape into the same stream
    as the errors, so a worker log alone tells the story.
    """
    kind = event.get("type")
    if kind not in _LOGGED_EVENTS:
        return

    if kind == "stage":
        now = time.monotonic()
        previous = _stage_started.get()
        if previous:
            logger.info("Stage %r finished in %.1fs", previous[0], now - previous[1])
        name = str(event.get("name", "?"))
        _stage_started.set((name, now))
        logger.info("── Stage %d: %s ──", event.get("stage", -1), name)
        return

    # Values are model output (concept lists, warning prose) and can run to
    # hundreds of characters. Truncated per field so one verbose event cannot
    # push a whole build's worth of real log lines off the screen.
    detail = ", ".join(f"{k}={_clip(v)}" for k, v in event.items() if k != "type")
    if kind in ("error", "cancelled"):
        logger.error("Build event %s: %s", kind, detail)
    elif kind in ("stage_degraded", "corpus_warning"):
        logger.warning("Build event %s: %s", kind, detail)
    else:
        logger.info("Build event %s: %s", kind, detail)
