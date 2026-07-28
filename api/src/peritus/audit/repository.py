"""All SQL for the audit surface.

Every query is scoped to a single ``expert_id`` that the route has already
resolved through the owner-scoped expert lookup, so nothing here re-implements
authorisation — but nothing here is reachable without it either.

Query notes:

* Anything unbounded takes ``limit``/``offset``. The only deliberately
  unbounded reads are over rows whose cardinality the build pipeline caps: one
  build produces tens of sources and at most eight key concepts.
* Aggregates are computed in Postgres over the FULL row set, never over the
  page, so a paginated corpus report still reports true totals.
* JSONB columns come back as ``str`` on this pool (no codec is registered), so
  callers decode through ``domain.decode_json_field`` rather than assuming.
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg

# Ordering options for the corpus report. A whitelist mapping, never client
# text interpolated into SQL: the key is validated by the request schema and
# only these fixed fragments can reach the query.
SOURCE_SORTS: dict[str, str] = {
    "decision": "s.passed DESC, s.quality_score DESC NULLS LAST, s.id",
    "quality": "s.quality_score DESC NULLS LAST, s.id",
    "relevance": "s.relevance_score DESC NULLS LAST, s.id",
    "title": "lower(s.title), s.id",
    "type": "s.source_type, s.quality_score DESC NULLS LAST, s.id",
    "discovered_via": "s.discovered_via NULLS LAST, s.quality_score DESC NULLS LAST, s.id",
    "added": "s.id",
}

# Build events the screening funnel reads. Filtering in SQL keeps a chatty
# build (one event per validated source, one per graph batch) from being pulled
# into memory just to find the dozen stage markers that matter.
FUNNEL_EVENT_TYPES: tuple[str, ...] = (
    "build_started",
    "stage",
    "discovery_started",
    "fetcher_done",
    "triage_done",
    "fetch_done",
    "snowball_done",
    "validate_done",
    "coverage_gaps",
    "gapfill_done",
    "retry",
    "done",
    "error",
    "cancelled",
)

# Per-source passage count, shared by several queries.
_CHUNK_COUNT_LATERAL = """
    LEFT JOIN LATERAL (
        SELECT count(*)::int AS chunk_count
        FROM source_chunks sc
        WHERE sc.source_id = s.id
    ) c ON true
"""

_SOURCE_COLUMNS = """
    s.id, s.passed, s.source_type, s.url, s.title, s.author,
    s.quality_score, s.relevance_score, s.content_type, s.difficulty,
    s.key_claims, s.drop_reason, s.validator_model, s.rubric_version,
    s.discovered_via, s.covered_concepts, s.created_at,
    COALESCE(c.chunk_count, 0) AS chunk_count
"""


class AuditRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── corpus report ───────────────────────────────────────────────────────

    async def list_sources(
        self,
        expert_id: int,
        passed: bool | None,
        sort: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        order = SOURCE_SORTS.get(sort) or SOURCE_SORTS["decision"]
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {_SOURCE_COLUMNS}
                FROM sources s
                {_CHUNK_COUNT_LATERAL}
                WHERE s.expert_id = $1
                  AND ($2::boolean IS NULL OR s.passed = $2::boolean)
                ORDER BY {order}
                LIMIT $3 OFFSET $4
                """,
                expert_id, passed, limit, offset,
            )
        return [dict(r) for r in rows]

    async def source_totals(self, expert_id: int) -> dict[str, Any]:
        """Counts and score summary over every source, accepted and rejected.

        Ordered-set aggregates (``percentile_cont``) give medians alongside the
        means; a corpus with one 10.0 and five 5.0s reads very differently on
        the two, and a reviewer should see both.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    count(*)::int AS total,
                    (count(*) FILTER (WHERE s.passed))::int AS accepted,
                    (count(*) FILTER (WHERE NOT s.passed))::int AS rejected,
                    avg(s.quality_score) FILTER (WHERE s.passed) AS accepted_mean_quality,
                    avg(s.relevance_score) FILTER (WHERE s.passed) AS accepted_mean_relevance,
                    avg(s.quality_score) FILTER (WHERE NOT s.passed) AS rejected_mean_quality,
                    avg(s.relevance_score) FILTER (WHERE NOT s.passed) AS rejected_mean_relevance,
                    percentile_cont(0.5) WITHIN GROUP (
                        ORDER BY s.quality_score::double precision
                    ) FILTER (WHERE s.passed) AS accepted_median_quality,
                    percentile_cont(0.5) WITHIN GROUP (
                        ORDER BY s.relevance_score::double precision
                    ) FILTER (WHERE s.passed) AS accepted_median_relevance,
                    min(s.quality_score) FILTER (WHERE s.passed) AS accepted_min_quality,
                    max(s.quality_score) FILTER (WHERE s.passed) AS accepted_max_quality,
                    min(s.relevance_score) FILTER (WHERE s.passed) AS accepted_min_relevance,
                    max(s.relevance_score) FILTER (WHERE s.passed) AS accepted_max_relevance
                FROM sources s
                WHERE s.expert_id = $1
                """,
                expert_id,
            )
        return dict(row) if row else {}

    async def score_distribution(self, expert_id: int) -> list[dict[str, Any]]:
        """Integer-bin histogram of both scores, split by decision.

        Bins are the ten unit-wide buckets of the validator's 0–10 scale; a
        perfect 10 folds into the 9–10 bin so the axis stays ten buckets wide.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT m.metric,
                       s.passed,
                       LEAST(9, GREATEST(0, floor(m.score)::int)) AS bucket,
                       count(*)::int AS n
                FROM sources s
                CROSS JOIN LATERAL (
                    VALUES ('quality', s.quality_score), ('relevance', s.relevance_score)
                ) AS m(metric, score)
                WHERE s.expert_id = $1 AND m.score IS NOT NULL
                GROUP BY m.metric, s.passed, bucket
                """,
                expert_id,
            )
        return [dict(r) for r in rows]

    async def provenance_gaps(self, expert_id: int) -> dict[str, Any]:
        """How much provenance is missing, column by column.

        Older experts predate ``validator_model``/``rubric_version`` (migration
        009) and ``covered_concepts``/``discovered_via`` (migration 012). A
        corpus report over one of those must say so rather than render blanks
        that look like the pipeline forgot.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    count(*)::int AS total,
                    (count(*) FILTER (WHERE validator_model IS NULL))::int
                        AS missing_validator_model,
                    (count(*) FILTER (WHERE rubric_version IS NULL))::int
                        AS missing_rubric_version,
                    (count(*) FILTER (WHERE discovered_via IS NULL))::int
                        AS missing_discovered_via,
                    (count(*) FILTER (WHERE passed AND covered_concepts IS NULL))::int
                        AS missing_covered_concepts,
                    (count(*) FILTER (WHERE quality_score IS NULL))::int
                        AS missing_quality_score,
                    (count(*) FILTER (WHERE relevance_score IS NULL))::int
                        AS missing_relevance_score,
                    (count(*) FILTER (
                        WHERE NOT passed AND coalesce(btrim(drop_reason), '') = ''
                    ))::int AS missing_drop_reason,
                    (count(*) FILTER (WHERE url IS NULL OR btrim(url) = ''))::int
                        AS missing_url
                FROM sources
                WHERE expert_id = $1
                """,
                expert_id,
            )
        return dict(row) if row else {}

    async def rubric_versions(self, expert_id: int) -> list[dict[str, Any]]:
        """Which rubric/model actually judged these rows.

        More than one row here means the corpus was scored under more than one
        rubric — the accept/reject line is not comparable across those sources,
        and a reviewer needs to know before quoting a pass rate.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT rubric_version, validator_model,
                       count(*)::int AS n,
                       (count(*) FILTER (WHERE passed))::int AS accepted,
                       min(created_at) AS first_seen,
                       max(created_at) AS last_seen
                FROM sources
                WHERE expert_id = $1
                GROUP BY rubric_version, validator_model
                ORDER BY n DESC, rubric_version NULLS LAST
                """,
                expert_id,
            )
        return [dict(r) for r in rows]

    async def source_type_breakdown(self, expert_id: int) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.source_type,
                       count(*)::int AS considered,
                       (count(*) FILTER (WHERE s.passed))::int AS accepted,
                       (count(*) FILTER (WHERE NOT s.passed))::int AS rejected,
                       avg(s.quality_score) FILTER (WHERE s.passed) AS accepted_mean_quality,
                       avg(s.relevance_score) FILTER (WHERE s.passed) AS accepted_mean_relevance
                FROM sources s
                WHERE s.expert_id = $1
                GROUP BY s.source_type
                ORDER BY accepted DESC, considered DESC, s.source_type
                """,
                expert_id,
            )
        return [dict(r) for r in rows]

    async def discovery_breakdown(self, expert_id: int) -> list[dict[str, Any]]:
        """Accept rate and mean quality per discovery path.

        Answers "did the sources we had to go hunting for hold up as well as the
        ones the plan found?" — split on the part of ``discovered_via`` before
        the colon, so every ``gapfill:<concept>`` folds into one ``gapfill`` row.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT COALESCE(NULLIF(split_part(s.discovered_via, ':', 1), ''), 'unknown')
                           AS method,
                       count(*)::int AS considered,
                       (count(*) FILTER (WHERE s.passed))::int AS accepted,
                       (count(*) FILTER (WHERE NOT s.passed))::int AS rejected,
                       avg(s.quality_score) FILTER (WHERE s.passed) AS accepted_mean_quality
                FROM sources s
                WHERE s.expert_id = $1
                GROUP BY method
                ORDER BY considered DESC, method
                """,
                expert_id,
            )
        return [dict(r) for r in rows]

    async def drop_reasons(self, expert_id: int, limit: int = 200) -> list[dict[str, Any]]:
        """Verbatim exclusion reasons with counts.

        The reason is a short phrase the validating model wrote, so this
        histogram has a long tail by nature. It is reported exactly as stored —
        clustering free text into tidier categories would be the API inventing
        an exclusion taxonomy the pipeline never applied.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT COALESCE(NULLIF(btrim(drop_reason), ''), '(no reason recorded)')
                           AS reason,
                       count(*)::int AS n,
                       avg(quality_score) AS mean_quality,
                       avg(relevance_score) AS mean_relevance
                FROM sources
                WHERE expert_id = $1 AND NOT passed
                GROUP BY reason
                ORDER BY n DESC, reason
                LIMIT $2
                """,
                expert_id, limit,
            )
        return [dict(r) for r in rows]

    async def rejection_buckets(
        self, expert_id: int, quality_threshold: float, relevance_threshold: float
    ) -> dict[str, Any]:
        """Rejections bucketed by which threshold the PERSISTED SCORES missed.

        Derived from numbers, not from the model's prose, so it is reproducible
        by anyone holding the same rows. ``above_both_thresholds`` is the
        interesting bucket: a rejected source that clears today's floors was
        judged under a different rubric or hit a validation error.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    (count(*) FILTER (
                        WHERE quality_score IS NULL OR relevance_score IS NULL
                    ))::int AS unscored,
                    (count(*) FILTER (
                        WHERE quality_score < $2 AND relevance_score < $3
                    ))::int AS both_below_threshold,
                    (count(*) FILTER (
                        WHERE quality_score < $2 AND relevance_score >= $3
                    ))::int AS quality_below_threshold,
                    (count(*) FILTER (
                        WHERE quality_score >= $2 AND relevance_score < $3
                    ))::int AS relevance_below_threshold,
                    (count(*) FILTER (
                        WHERE quality_score >= $2 AND relevance_score >= $3
                    ))::int AS above_both_thresholds
                FROM sources
                WHERE expert_id = $1 AND NOT passed
                """,
                expert_id, quality_threshold, relevance_threshold,
            )
        return dict(row) if row else {}

    async def ingestion_stats(self, expert_id: int) -> dict[str, Any]:
        """Did every accepted source actually make it into the searchable corpus?

        An accepted source with zero passages contributed nothing to any answer,
        however good its scores were. Chunking or embedding failed for it and
        the build carried on. Nothing else in the product surfaces that.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT
                    (count(*) FILTER (WHERE s.passed))::int AS accepted,
                    (count(*) FILTER (WHERE s.passed AND COALESCE(c.chunk_count, 0) > 0))::int
                        AS accepted_with_passages,
                    (count(*) FILTER (WHERE s.passed AND COALESCE(c.chunk_count, 0) = 0))::int
                        AS accepted_without_passages,
                    COALESCE(sum(c.chunk_count) FILTER (WHERE s.passed), 0)::int
                        AS passages_total
                FROM sources s
                {_CHUNK_COUNT_LATERAL}
                WHERE s.expert_id = $1
                """,
                expert_id,
            )
        return dict(row) if row else {}

    async def export_sources(
        self, expert_id: int, passed: bool | None, limit: int
    ) -> list[dict[str, Any]]:
        """Every source, unpaginated, for CSV/RIS export.

        An export that silently stopped at a page boundary would be worse than
        no export at all — a reviewer would cite an incomplete ledger without
        knowing it. ``limit`` is a runaway guard well above any real build; the
        caller compares the row count against it and refuses to emit a file it
        knows is truncated.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {_SOURCE_COLUMNS}
                FROM sources s
                {_CHUNK_COUNT_LATERAL}
                WHERE s.expert_id = $1
                  AND ($2::boolean IS NULL OR s.passed = $2::boolean)
                ORDER BY s.passed DESC, s.quality_score DESC NULLS LAST, s.id
                LIMIT $3
                """,
                expert_id, passed, limit,
            )
        return [dict(r) for r in rows]

    async def search_provenance(self, expert_id: int) -> list[dict[str, Any]]:
        """The corpus grouped by the SEARCH that produced each source.

        Not the same cut as ``discovery_breakdown``: this keeps every distinct
        ``discovered_via`` value intact, so each ``gapfill:<concept>`` round is
        its own row rather than being folded into one 'gapfill' total. That is
        the search-provenance view — which search produced which sources — and
        it is the half of the record that bibliographic-database tools have no
        equivalent for.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT COALESCE(s.discovered_via, '(not recorded)') AS discovered_via,
                       count(*)::int AS considered,
                       (count(*) FILTER (WHERE s.passed))::int AS accepted,
                       (count(*) FILTER (WHERE NOT s.passed))::int AS rejected,
                       avg(s.quality_score) FILTER (WHERE s.passed) AS accepted_mean_quality,
                       avg(s.relevance_score) FILTER (WHERE s.passed)
                           AS accepted_mean_relevance,
                       array_agg(DISTINCT s.source_type ORDER BY s.source_type)
                           AS source_types
                FROM sources s
                WHERE s.expert_id = $1
                GROUP BY s.discovered_via
                ORDER BY considered DESC, discovered_via
                """,
                expert_id,
            )
        return [dict(r) for r in rows]

    async def gapfill_sources(self, expert_id: int) -> list[dict[str, Any]]:
        """Every source a gap-fill search returned, with its concept and outcome.

        Drives the narrative "this concept was uncovered, so this search ran, and
        it returned these sources" — including the ones the search returned and
        validation then rejected, which is the part that shows the search was
        real rather than decorative.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT NULLIF(split_part(s.discovered_via, ':', 2), '') AS concept,
                       s.id, s.title, s.url, s.source_type, s.author,
                       s.quality_score, s.relevance_score, s.passed, s.drop_reason
                FROM sources s
                WHERE s.expert_id = $1 AND s.discovered_via LIKE 'gapfill:%'
                ORDER BY concept, s.passed DESC, s.quality_score DESC NULLS LAST, s.id
                """,
                expert_id,
            )
        return [dict(r) for r in rows]

    async def count_sources(self, expert_id: int, passed: bool | None) -> int:
        async with self._pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT count(*)::int FROM sources
                WHERE expert_id = $1 AND ($2::boolean IS NULL OR passed = $2::boolean)
                """,
                expert_id, passed,
            )
        return int(n or 0)

    # ── coverage ────────────────────────────────────────────────────────────

    async def concept_coverage_rows(self, expert_id: int) -> list[dict[str, Any]]:
        """One row per (concept, accepted source that covers it).

        Unnesting the JSONB tag array is cheaper and more honest than probing
        per concept: it also surfaces any tag that is NOT on the expert's key
        concept list, which would mean the validator's tags drifted from the
        plan. Bounded by (accepted sources x tags per source) — tens of rows.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT concept.value AS concept,
                       s.id, s.title, s.url, s.source_type, s.author,
                       s.quality_score, s.relevance_score, s.discovered_via,
                       s.content_type, s.difficulty,
                       COALESCE(c.chunk_count, 0) AS chunk_count
                FROM sources s
                {_CHUNK_COUNT_LATERAL}
                CROSS JOIN LATERAL jsonb_array_elements_text(
                    CASE WHEN jsonb_typeof(s.covered_concepts) = 'array'
                         THEN s.covered_concepts
                         ELSE '[]'::jsonb END
                ) AS concept(value)
                WHERE s.expert_id = $1 AND s.passed
                ORDER BY concept.value, s.quality_score DESC NULLS LAST, s.id
                """,
                expert_id,
            )
        return [dict(r) for r in rows]

    async def concept_tagging_stats(self, expert_id: int) -> dict[str, Any]:
        """Accepted sources split by whether concept tagging ran on them at all."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    (count(*) FILTER (WHERE covered_concepts IS NULL))::int AS untagged_legacy,
                    (count(*) FILTER (
                        WHERE jsonb_typeof(covered_concepts) = 'array'
                          AND jsonb_array_length(covered_concepts) = 0
                    ))::int AS tagged_no_concepts,
                    (count(*) FILTER (
                        WHERE jsonb_typeof(covered_concepts) = 'array'
                          AND jsonb_array_length(covered_concepts) > 0
                    ))::int AS tagged_with_concepts
                FROM sources
                WHERE expert_id = $1 AND passed
                """,
                expert_id,
            )
        return dict(row) if row else {}

    async def gapfill_concepts(self, expert_id: int) -> list[dict[str, Any]]:
        """Concepts that triggered a targeted re-search, from `discovered_via`.

        A concept appearing here is one the first discovery pass missed
        entirely — a real weakness signal, independent of how the gap-fill went.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT NULLIF(split_part(discovered_via, ':', 2), '') AS concept,
                       count(*)::int AS sources_found,
                       (count(*) FILTER (WHERE passed))::int AS accepted
                FROM sources
                WHERE expert_id = $1 AND discovered_via LIKE 'gapfill:%'
                GROUP BY concept
                HAVING NULLIF(split_part(discovered_via, ':', 2), '') IS NOT NULL
                ORDER BY concept
                """,
                expert_id,
            )
        return [dict(r) for r in rows]

    # ── contradictions ──────────────────────────────────────────────────────

    async def contradiction_summary(self, expert_id: int) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT count(DISTINCT e.id)::int AS total,
                       count(DISTINCT v.node_id)::int AS concepts_involved
                FROM expert_edges e
                CROSS JOIN LATERAL (
                    VALUES (e.from_node_id), (e.to_node_id)
                ) AS v(node_id)
                WHERE e.expert_id = $1 AND e.edge_type = 'contradicts'
                """,
                expert_id,
            )
        return dict(row) if row else {"total": 0, "concepts_involved": 0}

    async def edge_type_breakdown(self, expert_id: int) -> list[dict[str, Any]]:
        """Relationship mix, so `contradicts` has a denominator to sit against."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT edge_type, count(*)::int AS n, avg(weight) AS mean_weight
                FROM expert_edges
                WHERE expert_id = $1
                GROUP BY edge_type
                ORDER BY n DESC, edge_type
                """,
                expert_id,
            )
        return [dict(r) for r in rows]

    async def contradiction_edges(
        self, expert_id: int, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        """Contradiction edges with both concept nodes resolved.

        Uses the partial index added in migration 017; without it this is a scan
        of every relationship in the graph to find the few that disagree.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT e.id AS edge_id, e.weight, e.properties,
                       fn.id AS from_id, fn.label AS from_label,
                       fn.node_type AS from_node_type, fn.description AS from_description,
                       fn.chunk_ids AS from_chunk_ids,
                       tn.id AS to_id, tn.label AS to_label,
                       tn.node_type AS to_node_type, tn.description AS to_description,
                       tn.chunk_ids AS to_chunk_ids
                FROM expert_edges e
                JOIN expert_nodes fn ON fn.id = e.from_node_id
                JOIN expert_nodes tn ON tn.id = e.to_node_id
                WHERE e.expert_id = $1 AND e.edge_type = 'contradicts'
                ORDER BY e.weight DESC, e.id
                LIMIT $2 OFFSET $3
                """,
                expert_id, limit, offset,
            )
        return [dict(r) for r in rows]

    async def chunks_with_sources(
        self, chunk_ids: list[int], excerpt_chars: int
    ) -> dict[int, dict[str, Any]]:
        """Resolve chunk ids to passage text plus the source citation behind them.

        One round trip for every passage on both sides of every contradiction on
        the page, so rendering "Source A claims X / Source B claims Y" never
        needs a second request.
        """
        if not chunk_ids:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT sc.id AS chunk_id, sc.source_id, sc.sequence_n,
                       left(sc.text, $2) AS excerpt,
                       length(sc.text) AS text_length,
                       sc.context_text,
                       s.title AS source_title, s.source_type, s.url, s.author,
                       s.quality_score, s.relevance_score, s.passed
                FROM source_chunks sc
                JOIN sources s ON s.id = sc.source_id
                WHERE sc.id = ANY($1::int[])
                """,
                chunk_ids, excerpt_chars,
            )
        return {r["chunk_id"]: dict(r) for r in rows}

    # ── build event log ─────────────────────────────────────────────────────

    async def latest_build_job(self, expert_id: int) -> dict[str, Any] | None:
        """The most recent build job for an expert.

        Deliberately the LATEST job, not the latest *successful* one: the worker
        wipes all derived corpus state at the start of every attempt, so the
        rows in `sources` always belong to the newest attempt. Pointing the
        funnel at an older successful job would describe a corpus that no longer
        exists.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, status, tier, attempts, max_attempts, last_error,
                       created_at, updated_at
                FROM build_jobs
                WHERE expert_id = $1
                ORDER BY id DESC
                LIMIT 1
                """,
                expert_id,
            )
        return dict(row) if row else None

    async def funnel_events(self, job_id: int) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT seq, job_id, type, payload, created_at
                FROM build_events
                WHERE job_id = $1 AND type = ANY($2::text[])
                ORDER BY seq
                """,
                job_id, list(FUNNEL_EVENT_TYPES),
            )
        return [dict(r) for r in rows]

    # ── answer-level retrieval audit ────────────────────────────────────────

    async def insert_answer_audit(
        self, header: dict[str, Any], passages: list[dict[str, Any]]
    ) -> str:
        """Persist one answer's retrieval trail. Returns the new audit id."""
        async with self._pool.acquire() as conn, conn.transaction():
            audit_id = await conn.fetchval(
                """
                INSERT INTO answer_audits (
                    expert_id, conversation_id, question, subqueries, followup_queries,
                    coverage_satisfied, second_pass, retrieved_passages, duplicate_hits,
                    unique_passages, context_passages, cited_passages, context_cap,
                    sources_in_context, sources_cited, contradiction_traversed, answer_chars
                ) VALUES (
                    $1, $2::uuid, $3, $4::jsonb, $5::jsonb,
                    $6, $7, $8, $9,
                    $10, $11, $12, $13,
                    $14, $15, $16, $17
                )
                RETURNING id
                """,
                header["expert_id"],
                header.get("conversation_id"),
                header["question"],
                json.dumps(header.get("subqueries") or []),
                json.dumps(header.get("followup_queries") or []),
                header.get("coverage_satisfied"),
                bool(header.get("second_pass")),
                int(header.get("retrieved_passages") or 0),
                int(header.get("duplicate_hits") or 0),
                int(header.get("unique_passages") or 0),
                int(header.get("context_passages") or 0),
                int(header.get("cited_passages") or 0),
                header.get("context_cap"),
                int(header.get("sources_in_context") or 0),
                int(header.get("sources_cited") or 0),
                bool(header.get("contradiction_traversed")),
                int(header.get("answer_chars") or 0),
            )
            if passages:
                await conn.executemany(
                    """
                    INSERT INTO answer_audit_passages (
                        audit_id, passage_n, chunk_id, source_id, source_title,
                        source_type, quality_score, retrieval_rank, retrieval_score,
                        retrieved_via, disposition
                    ) VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """,
                    [
                        (
                            audit_id,
                            p.get("passage_n"),
                            p.get("chunk_id"),
                            p.get("source_id"),
                            p.get("source_title"),
                            p.get("source_type"),
                            p.get("quality_score"),
                            p["retrieval_rank"],
                            p.get("retrieval_score"),
                            p.get("retrieved_via") or "primary",
                            p["disposition"],
                        )
                        for p in passages
                    ],
                )
        return str(audit_id)

    async def list_answer_audits(
        self,
        expert_id: int,
        limit: int,
        offset: int,
        conversation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, expert_id, conversation_id, question, subqueries,
                       followup_queries, coverage_satisfied, second_pass,
                       retrieved_passages, duplicate_hits, unique_passages,
                       context_passages, cited_passages, context_cap,
                       sources_in_context, sources_cited, contradiction_traversed,
                       answer_chars, created_at
                FROM answer_audits
                WHERE expert_id = $1
                  AND ($2::uuid IS NULL OR conversation_id = $2::uuid)
                ORDER BY created_at DESC, id
                LIMIT $3 OFFSET $4
                """,
                expert_id, conversation_id, limit, offset,
            )
        return [dict(r) for r in rows]

    async def count_answer_audits(
        self, expert_id: int, conversation_id: str | None = None
    ) -> int:
        async with self._pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT count(*)::int FROM answer_audits
                WHERE expert_id = $1
                  AND ($2::uuid IS NULL OR conversation_id = $2::uuid)
                """,
                expert_id, conversation_id,
            )
        return int(n or 0)

    async def get_answer_audit(
        self, expert_id: int, audit_id: str
    ) -> dict[str, Any] | None:
        """Fetch one trail, scoped to the expert the caller already resolved."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, expert_id, conversation_id, question, subqueries,
                       followup_queries, coverage_satisfied, second_pass,
                       retrieved_passages, duplicate_hits, unique_passages,
                       context_passages, cited_passages, context_cap,
                       sources_in_context, sources_cited, contradiction_traversed,
                       answer_chars, created_at
                FROM answer_audits
                WHERE expert_id = $1 AND id = $2::uuid
                """,
                expert_id, audit_id,
            )
        return dict(row) if row else None

    async def answer_audit_passages(self, audit_id: str) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT passage_n, chunk_id, source_id, source_title, source_type,
                       quality_score, retrieval_rank, retrieval_score,
                       retrieved_via, disposition
                FROM answer_audit_passages
                WHERE audit_id = $1::uuid
                ORDER BY retrieval_rank
                """,
                audit_id,
            )
        return [dict(r) for r in rows]
