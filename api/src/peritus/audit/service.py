"""Assembles the audit responses from persisted rows.

The service is where "what does the database know" becomes "what can a
researcher defend". Its jobs are to join the pieces, apply the published
classification rules from :mod:`peritus.audit.domain`, and — the part that
matters most — mark every number it cannot support as ``None`` with a reason.

Nothing in here estimates, back-fills, or interpolates a count.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from peritus.audit.domain import (
    COVERAGE_RULE,
    DISPOSITION_MEANINGS,
    REJECTION_BUCKETS,
    CoverageStrength,
    classify_coverage,
    decode_json_field,
    parse_discovery_method,
    round_or_none,
    safe_mean,
)
from peritus.audit.repository import AuditRepository
from peritus.audit.screening import UNPERSISTED, DiscoveryFunnel, derive_discovery_funnel
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.jobs.domain import BuildEventRow
from peritus.search.readiness import Readiness

# The validator's pass floors and rubric id. Imported from the module that
# applies them rather than restated here: a copy would silently drift the day
# someone retunes the rubric, and this API's whole value is that its numbers
# match the ones the pipeline actually used.
from peritus.sources.validator import (  # noqa: PLC2701
    _PASS_THRESHOLD_Q,
    _PASS_THRESHOLD_R,
    RUBRIC_VERSION,
)

logger = get_logger(__name__)

# Passages returned per side of a contradiction unless the caller asks for more.
DEFAULT_PASSAGES_PER_SIDE = 3
MAX_PASSAGES_PER_SIDE = 10
DEFAULT_EXCERPT_CHARS = 700
MAX_EXCERPT_CHARS = 4000

# Contributing sources listed inline per concept. A build plans at most eight
# key concepts and tens of sources, so the full list is small; the cap only
# guards against a pathological corpus.
MAX_CONCEPT_SOURCES = 50

# What this surface is and is not. Returned on every response so a caller
# cannot render these numbers as something they aren't.
METHOD_STATEMENT = (
    "First-pass automated screening with a complete audit trail. Every source "
    "was scored by a language model against a versioned rubric; the scores, the "
    "model, the rubric version, the discovery path and the exclusion reason are "
    "recorded for each one. This is not a systematic review: no two independent "
    "human reviewers screened these records, and no reconciliation step took "
    "place. Treat it as a reviewable first pass that a human must check."
)


class AuditService:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._repo = AuditRepository(pool)

    # ── corpus report ───────────────────────────────────────────────────────

    async def corpus_report(
        self,
        expert: Expert,
        decision: str = "all",
        sort: str = "decision",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Every source considered for this corpus, kept and dropped alike.

        The rejected half is the differentiating half: it is the only evidence
        that the accepted half was selected rather than merely collected, so it
        is returned through the same shape, with the same fields, as the
        accepted half — not as an appendix.
        """
        passed = {"accepted": True, "rejected": False}.get(decision)

        rows = await self._repo.list_sources(expert.id, passed, sort, limit, offset)
        total_matching = await self._repo.count_sources(expert.id, passed)
        totals = await self._repo.source_totals(expert.id)
        distribution = await self._repo.score_distribution(expert.id)
        provenance = await self._repo.provenance_gaps(expert.id)
        rubrics = await self._repo.rubric_versions(expert.id)
        by_type = await self._repo.source_type_breakdown(expert.id)
        by_discovery = await self._repo.discovery_breakdown(expert.id)
        by_search = await self._repo.search_provenance(expert.id)
        drop_reasons = await self._repo.drop_reasons(expert.id)
        buckets = await self._repo.rejection_buckets(
            expert.id, _PASS_THRESHOLD_Q, _PASS_THRESHOLD_R
        )
        ingestion = await self._repo.ingestion_stats(expert.id)

        considered = int(totals.get("total") or 0)
        accepted = int(totals.get("accepted") or 0)

        return {
            "expert": _expert_stub(expert),
            "method_statement": METHOD_STATEMENT,
            "totals": {
                "considered": considered,
                "accepted": accepted,
                "rejected": int(totals.get("rejected") or 0),
                "acceptance_rate": (
                    round(accepted / considered, 4) if considered else None
                ),
                "accepted_with_passages": ingestion.get("accepted_with_passages"),
                "accepted_without_passages": ingestion.get("accepted_without_passages"),
                "passages_total": ingestion.get("passages_total"),
            },
            "scores": {
                "accepted": _score_summary(totals, "accepted"),
                "rejected": {
                    "mean_quality": round_or_none(totals.get("rejected_mean_quality")),
                    "mean_relevance": round_or_none(totals.get("rejected_mean_relevance")),
                },
                "distribution": _distribution(distribution),
                "bin_edges": [[i, i + 1] for i in range(10)],
            },
            "thresholds": {
                "quality_min": _PASS_THRESHOLD_Q,
                "relevance_min": _PASS_THRESHOLD_R,
                "current_rubric_version": RUBRIC_VERSION,
                "note": (
                    "These are the floors the CURRENT code applies. Rows stamped "
                    "with a different rubric_version were judged under different "
                    "rules — compare against rubric_versions before quoting a "
                    "single acceptance rate for the whole corpus."
                ),
            },
            "rubric_versions": [
                {
                    "rubric_version": r["rubric_version"],
                    "validator_model": r["validator_model"],
                    "sources": r["n"],
                    "accepted": r["accepted"],
                    "first_seen": r["first_seen"],
                    "last_seen": r["last_seen"],
                }
                for r in rubrics
            ],
            "provenance": _provenance_block(provenance),
            "by_source_type": [
                {
                    "source_type": r["source_type"],
                    "considered": r["considered"],
                    "accepted": r["accepted"],
                    "rejected": r["rejected"],
                    "accepted_mean_quality": round_or_none(r["accepted_mean_quality"]),
                    "accepted_mean_relevance": round_or_none(r["accepted_mean_relevance"]),
                }
                for r in by_type
            ],
            "by_discovery_method": [
                {
                    "method": r["method"],
                    "considered": r["considered"],
                    "accepted": r["accepted"],
                    "rejected": r["rejected"],
                    "accepted_mean_quality": round_or_none(r["accepted_mean_quality"]),
                }
                for r in by_discovery
            ],
            "by_search": _search_provenance_block(by_search),
            "exclusions": {
                "by_reason": [
                    {
                        "reason": r["reason"],
                        "count": r["n"],
                        "mean_quality": round_or_none(r["mean_quality"]),
                        "mean_relevance": round_or_none(r["mean_relevance"]),
                    }
                    for r in drop_reasons
                ],
                "by_threshold": {
                    "quality_below_threshold": buckets.get("quality_below_threshold", 0),
                    "relevance_below_threshold": buckets.get("relevance_below_threshold", 0),
                    "both_below_threshold": buckets.get("both_below_threshold", 0),
                    "above_both_thresholds": buckets.get("above_both_thresholds", 0),
                    "unscored": buckets.get("unscored", 0),
                },
                "by_threshold_meanings": REJECTION_BUCKETS,
            },
            "page": {
                "decision": decision,
                "sort": sort,
                "limit": limit,
                "offset": offset,
                "returned": len(rows),
                "total_matching": total_matching,
                "has_more": offset + len(rows) < total_matching,
            },
            "sources": [_source_row(r) for r in rows],
        }

    # ── screening flow ──────────────────────────────────────────────────────

    async def screening_flow(self, expert: Expert) -> dict[str, Any]:
        """Counts through the funnel: identified → screened → assessed → included.

        Two sources of truth, deliberately kept apart. Pre-validation stages can
        only come from the build event log, which is a record of a run and may
        be absent. Validation onward comes from the `sources` table, which is
        the corpus itself and is authoritative. Where the two disagree the
        response shows both rather than reconciling them silently.
        """
        job = await self._repo.latest_build_job(expert.id)
        funnel: DiscoveryFunnel | None = None
        events_available = False
        if job is not None:
            raw_events = await self._repo.funnel_events(job["id"])
            events = [
                BuildEventRow(
                    seq=e["seq"],
                    job_id=e["job_id"],
                    type=e["type"],
                    payload=decode_json_field(e["payload"], {}),
                    created_at=e["created_at"],
                )
                for e in raw_events
            ]
            events_available = bool(events)
            funnel = derive_discovery_funnel(events)

        totals = await self._repo.source_totals(expert.id)
        drop_reasons = await self._repo.drop_reasons(expert.id)
        buckets = await self._repo.rejection_buckets(
            expert.id, _PASS_THRESHOLD_Q, _PASS_THRESHOLD_R
        )
        ingestion = await self._repo.ingestion_stats(expert.id)
        by_search = await self._repo.search_provenance(expert.id)
        gapfill_rows = await self._repo.gapfill_sources(expert.id)

        assessed = int(totals.get("total") or 0)
        included = int(totals.get("accepted") or 0)
        excluded = int(totals.get("rejected") or 0)

        if funnel is None:
            identify = _unavailable(
                "No retained build event log for this expert's most recent build. "
                "Discovery counts are written to build_events by the durable job "
                "worker (migration 010); experts built before that, or whose job "
                "rows have been deleted, have no pre-validation record. This is a "
                "missing record, not a build that found nothing."
            )
            screen = _unavailable(
                "Triage counts come from the same build event log, which is not "
                "retained for this expert."
            )
            retrieve = _unavailable(
                "Full-fetch counts come from the same build event log, which is "
                "not retained for this expert."
            )
        else:
            identify = _identify_stage(funnel)
            screen = _screen_stage(funnel)
            retrieve = _retrieve_stage(funnel)

        return {
            "expert": _expert_stub(expert),
            "method_statement": METHOD_STATEMENT,
            "build": _build_block(job, events_available),
            "search_strategy": _search_strategy_block(funnel, by_search),
            "stages": {
                "identified": identify,
                "screened_at_triage": screen,
                "retrieved_full_text": retrieve,
                "assessed_at_validation": {
                    "count": assessed,
                    "source": "sources table",
                    "note": (
                        "Every source the validator scored, including any added by "
                        "the gap-fill round. Authoritative: these are the rows the "
                        "corpus is made of."
                    ),
                    "reported_by_build_log": (
                        None
                        if funnel is None
                        or funnel.reported_validated_passed is None
                        or funnel.reported_validated_dropped is None
                        else funnel.reported_validated_passed
                        + funnel.reported_validated_dropped
                    ),
                    "build_log_note": (
                        "The build log's validate_done event covers the first "
                        "validation round only; gap-fill sources are validated "
                        "afterwards. A higher table count is expected when "
                        "gap-fill ran."
                    ),
                },
                "excluded_at_validation": {
                    "count": excluded,
                    "by_reason": [
                        {"reason": r["reason"], "count": r["n"]} for r in drop_reasons
                    ],
                    "by_threshold": {
                        "quality_below_threshold": buckets.get("quality_below_threshold", 0),
                        "relevance_below_threshold": buckets.get(
                            "relevance_below_threshold", 0
                        ),
                        "both_below_threshold": buckets.get("both_below_threshold", 0),
                        "above_both_thresholds": buckets.get("above_both_thresholds", 0),
                        "unscored": buckets.get("unscored", 0),
                    },
                    "by_threshold_meanings": REJECTION_BUCKETS,
                    "note": (
                        "by_reason is the validating model's own free-text phrase, "
                        "reported verbatim. by_threshold is arithmetic on the "
                        "persisted scores and is reproducible from the same rows."
                    ),
                },
                "included": {
                    "count": included,
                    "with_passages": ingestion.get("accepted_with_passages"),
                    "without_passages": ingestion.get("accepted_without_passages"),
                    "passages_embedded": ingestion.get("passages_total"),
                    "note": (
                        "An included source with zero passages was accepted by the "
                        "validator but failed to chunk or embed, so it contributed "
                        "nothing to any answer."
                    ),
                },
            },
            "gap_fill": {
                **_gapfill_block(funnel),
                "rounds": _gapfill_rounds(gapfill_rows),
            },
            "not_persisted": UNPERSISTED,
        }

    # ── export ──────────────────────────────────────────────────────────────

    async def export_rows(
        self, expert: Expert, decision: str, limit: int
    ) -> tuple[list[dict[str, Any]], bool]:
        """Rows for a CSV/RIS export, plus whether the runaway guard clipped them."""
        passed = {"accepted": True, "rejected": False}.get(decision)
        rows = await self._repo.export_sources(expert.id, passed, limit + 1)
        truncated = len(rows) > limit
        return rows[:limit], truncated

    # ── coverage ────────────────────────────────────────────────────────────

    async def coverage(self, expert: Expert) -> dict[str, Any]:
        """Per key concept: how much evidence backs it, and how good it is.

        This is the endpoint that tells a researcher where their evidence base
        is weak. Concepts come from the expert's own research plan, so an
        "absent" row is the corpus failing its own syllabus — not an arbitrary
        external checklist.
        """
        rows = await self._repo.concept_coverage_rows(expert.id)
        tagging = await self._repo.concept_tagging_stats(expert.id)
        gapfill_rows = await self._repo.gapfill_concepts(expert.id)

        gapfill_by_concept = {
            r["concept"]: {"sources_found": r["sources_found"], "accepted": r["accepted"]}
            for r in gapfill_rows
            if r["concept"]
        }

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["concept"], []).append(row)

        key_concepts = list(expert.key_concepts or [])
        # Any tag the validator emitted that is not on the plan. The validator
        # maps tags back onto the canonical list, so this should always be
        # empty; if it is not, the corpus is tagged against a stale plan and a
        # reviewer needs to see that rather than have it quietly dropped.
        off_plan = [c for c in grouped if c not in key_concepts]

        concepts = [
            _concept_block(c, grouped.get(c, []), gapfill_by_concept.get(c))
            for c in key_concepts
        ]
        concepts += [
            {**_concept_block(c, grouped[c], gapfill_by_concept.get(c)), "on_plan": False}
            for c in sorted(off_plan)
        ]

        strengths = [c["strength"] for c in concepts]
        return {
            "expert": _expert_stub(expert),
            "method_statement": METHOD_STATEMENT,
            "key_concepts_planned": key_concepts,
            "key_concepts_unavailable_reason": (
                None
                if key_concepts
                else (
                    "This expert has no planned key concepts recorded. The column "
                    "arrived in migration 007 and is written by the research-plan "
                    "stage; an expert built before it, or whose planning call fell "
                    "back to the raw topic, has none. Per-concept coverage cannot "
                    "be computed without them."
                )
            ),
            "classification_rule": COVERAGE_RULE,
            "summary": {
                "concepts": len(concepts),
                "absent": strengths.count(CoverageStrength.ABSENT.value),
                "thin": strengths.count(CoverageStrength.THIN.value),
                "adequate": strengths.count(CoverageStrength.ADEQUATE.value),
                "strong": strengths.count(CoverageStrength.STRONG.value),
                "concepts_needing_gap_fill": sum(
                    1 for c in concepts if c["needed_gap_fill"]
                ),
                "off_plan_concepts": len(off_plan),
            },
            "tagging": {
                "accepted_tagged_with_concepts": tagging.get("tagged_with_concepts", 0),
                "accepted_tagged_no_concepts": tagging.get("tagged_no_concepts", 0),
                "accepted_untagged_legacy": tagging.get("untagged_legacy", 0),
                "note": (
                    "untagged_legacy sources predate concept tagging (migration "
                    "012) and are invisible to every per-concept count below. "
                    "tagged_no_concepts sources were tagged and matched no key "
                    "concept — they are in the corpus but off-syllabus."
                ),
            },
            "concepts": concepts,
        }

    # ── contradictions ──────────────────────────────────────────────────────

    async def contradictions(
        self,
        expert: Expert,
        readiness: Readiness,
        limit: int = 25,
        offset: int = 0,
        passages_per_side: int = DEFAULT_PASSAGES_PER_SIDE,
        excerpt_chars: int = DEFAULT_EXCERPT_CHARS,
    ) -> dict[str, Any]:
        """`contradicts` edges resolved all the way down to passages and citations.

        Rich enough to render "Source A claims X / Source B claims Y" with no
        second round trip: both concept nodes, and for each side the passages
        that carry it plus the source behind each passage.

        ``computed`` is load-bearing. Contradictions come from the concept graph,
        which is extracted a whole stage after the corpus becomes searchable, so
        an expert can be answering questions while its graph is still empty. An
        empty list from that state means "not looked for yet" and must never be
        rendered as "none found" — for a product whose claim is that it shows
        where sources disagree, reporting an unanalysed corpus as a clean one is
        the worst failure available.
        """
        if not readiness.graph_expanded:
            return _contradictions_not_computed(expert, readiness, limit, offset)

        summary = await self._repo.contradiction_summary(expert.id)
        edge_mix = await self._repo.edge_type_breakdown(expert.id)
        edges = await self._repo.contradiction_edges(expert.id, limit, offset)

        # Choose which chunks to show for each side before fetching, so exactly
        # one query resolves every passage on the page.
        plans: list[tuple[dict[str, Any], list[int], list[int]]] = []
        wanted: set[int] = set()
        for edge in edges:
            from_ids = list(edge["from_chunk_ids"] or [])
            to_ids = list(edge["to_chunk_ids"] or [])
            a = _pick_side_chunks(from_ids, to_ids, passages_per_side)
            b = _pick_side_chunks(to_ids, from_ids, passages_per_side)
            plans.append((edge, a, b))
            wanted.update(a)
            wanted.update(b)

        chunks = await self._repo.chunks_with_sources(sorted(wanted), excerpt_chars)

        items = [
            _contradiction_item(edge, a_ids, b_ids, chunks, passages_per_side)
            for edge, a_ids, b_ids in plans
        ]

        total = int(summary.get("total") or 0)
        total_edges = sum(int(r["n"]) for r in edge_mix)
        return {
            "expert": _expert_stub(expert),
            "method_statement": METHOD_STATEMENT,
            "computed": True,
            "readiness": readiness.value,
            "summary": {
                "contradictions": total,
                "concepts_involved": int(summary.get("concepts_involved") or 0),
                "relationships_total": total_edges,
                "share_of_relationships": (
                    round(total / total_edges, 4) if total_edges else None
                ),
                "cross_source_on_page": sum(
                    1 for i in items if i["kind"] == "cross_source"
                ),
                "within_source_on_page": sum(
                    1 for i in items if i["kind"] == "within_source"
                ),
                "undetermined_on_page": sum(
                    1 for i in items if i["kind"] == "undetermined"
                ),
            },
            "relationship_mix": [
                {
                    "edge_type": r["edge_type"],
                    "count": r["n"],
                    "mean_weight": round_or_none(r["mean_weight"], 3),
                }
                for r in edge_mix
            ],
            "note": (
                "A contradiction is an edge a language model extracted while "
                "reading the corpus, between two concept nodes. The passages on "
                "each side are the passages those concepts were extracted from — "
                "they are the evidence to check, not a proof that the two sources "
                "disagree. Read both sides before citing one."
            ),
            "page": {
                "limit": limit,
                "offset": offset,
                "returned": len(items),
                "total_matching": total,
                "has_more": offset + len(items) < total,
                "passages_per_side": passages_per_side,
                "excerpt_chars": excerpt_chars,
            },
            "contradictions": items,
        }

    # ── answer-level retrieval trail ────────────────────────────────────────

    async def record_answer_audit(
        self, header: dict[str, Any], passages: list[dict[str, Any]]
    ) -> str | None:
        """Persist one answer's retrieval trail. Never raises.

        Called from the chat stream after the answer has already reached the
        user. A failure here must not turn a delivered answer into an error, so
        it degrades to "not persisted" and the SSE event says so.
        """
        try:
            return await self._repo.insert_answer_audit(header, passages)
        except Exception as exc:
            logger.warning("Answer audit not persisted: %s", exc)
            return None

    async def list_answer_audits(
        self,
        expert: Expert,
        limit: int = 25,
        offset: int = 0,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        rows = await self._repo.list_answer_audits(
            expert.id, limit, offset, conversation_id
        )
        total = await self._repo.count_answer_audits(expert.id, conversation_id)
        return {
            "expert": _expert_stub(expert),
            "disposition_meanings": DISPOSITION_MEANINGS,
            "page": {
                "limit": limit,
                "offset": offset,
                "returned": len(rows),
                "total_matching": total,
                "has_more": offset + len(rows) < total,
            },
            "audits": [_audit_header(r) for r in rows],
        }

    async def get_answer_audit(
        self, expert: Expert, audit_id: str
    ) -> dict[str, Any] | None:
        row = await self._repo.get_answer_audit(expert.id, audit_id)
        if row is None:
            return None
        passages = await self._repo.answer_audit_passages(str(row["id"]))
        return {
            "expert": _expert_stub(expert),
            "disposition_meanings": DISPOSITION_MEANINGS,
            **_audit_header(row),
            "passages": [
                {
                    "n": p["passage_n"],
                    "chunk_id": p["chunk_id"],
                    "source_id": p["source_id"],
                    "source_title": p["source_title"],
                    "source_type": p["source_type"],
                    "quality_score": round_or_none(p["quality_score"]),
                    "retrieval_rank": p["retrieval_rank"],
                    "retrieval_score": round_or_none(p["retrieval_score"], 4),
                    "retrieved_via": p["retrieved_via"],
                    "disposition": p["disposition"],
                }
                for p in passages
            ],
        }


# ── response fragment builders ──────────────────────────────────────────────


def _expert_stub(expert: Expert) -> dict[str, Any]:
    return {
        "id": expert.id,
        "slug": expert.name,
        "topic": expert.topic,
        "tier": expert.tier.value if hasattr(expert.tier, "value") else expert.tier,
        "status": expert.status.value if hasattr(expert.status, "value") else expert.status,
    }


def _unavailable(reason: str) -> dict[str, Any]:
    """A funnel stage whose counts are not persisted. Never a zero, never a guess."""
    return {"count": None, "unavailable_reason": reason}


def _score_summary(totals: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {
        "mean_quality": round_or_none(totals.get(f"{prefix}_mean_quality")),
        "median_quality": round_or_none(totals.get(f"{prefix}_median_quality")),
        "min_quality": round_or_none(totals.get(f"{prefix}_min_quality")),
        "max_quality": round_or_none(totals.get(f"{prefix}_max_quality")),
        "mean_relevance": round_or_none(totals.get(f"{prefix}_mean_relevance")),
        "median_relevance": round_or_none(totals.get(f"{prefix}_median_relevance")),
        "min_relevance": round_or_none(totals.get(f"{prefix}_min_relevance")),
        "max_relevance": round_or_none(totals.get(f"{prefix}_max_relevance")),
    }


def _distribution(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[int]]]:
    """Ten-bin histograms keyed metric -> decision -> counts, always length 10."""
    out = {
        "quality": {"accepted": [0] * 10, "rejected": [0] * 10},
        "relevance": {"accepted": [0] * 10, "rejected": [0] * 10},
    }
    for row in rows:
        metric = out.get(row["metric"])
        if metric is None:
            continue
        bucket = int(row["bucket"])
        if 0 <= bucket <= 9:
            metric["accepted" if row["passed"] else "rejected"][bucket] += int(row["n"])
    return out


def _provenance_block(gaps: dict[str, Any]) -> dict[str, Any]:
    total = int(gaps.get("total") or 0)
    missing = {
        k.removeprefix("missing_"): int(v or 0)
        for k, v in gaps.items()
        if k.startswith("missing_")
    }
    incomplete = {k: v for k, v in missing.items() if v}
    return {
        "sources": total,
        "complete": not incomplete,
        "missing": missing,
        "note": (
            "Columns arrived over time: validator_model and rubric_version in "
            "migration 009, covered_concepts and discovered_via in migration 012. "
            "Sources ingested before those exist with the field null. A non-zero "
            "count here means part of this corpus cannot be audited on that "
            "field — rebuild the expert to regenerate full provenance."
        )
        if incomplete
        else "Every source carries full validation and discovery provenance.",
    }


def _source_row(row: dict[str, Any]) -> dict[str, Any]:
    method, gapfill_concept = parse_discovery_method(row.get("discovered_via"))
    return {
        "id": row["id"],
        "decision": "accepted" if row["passed"] else "rejected",
        "title": row["title"],
        "url": row["url"],
        "author": row["author"],
        "source_type": row["source_type"],
        "content_type": row["content_type"],
        "difficulty": row["difficulty"],
        "quality_score": round_or_none(row["quality_score"]),
        "relevance_score": round_or_none(row["relevance_score"]),
        "drop_reason": row["drop_reason"] if not row["passed"] else None,
        "validator_model": row["validator_model"],
        "rubric_version": row["rubric_version"],
        "discovered_via": row["discovered_via"],
        "discovery_method": method,
        "gap_filled_for_concept": gapfill_concept,
        "covered_concepts": decode_json_field(row.get("covered_concepts"), []),
        "key_claims": decode_json_field(row.get("key_claims"), []),
        "passage_count": int(row.get("chunk_count") or 0),
        "created_at": row["created_at"],
    }


def _build_block(job: dict[str, Any] | None, events_available: bool) -> dict[str, Any]:
    if job is None:
        return {
            "job_id": None,
            "status": None,
            "unavailable_reason": (
                "No build job row exists for this expert. It predates the durable "
                "job queue (migration 010) or its job history has been deleted."
            ),
        }
    return {
        "job_id": job["id"],
        "status": job["status"],
        "tier": job["tier"],
        "attempts": job["attempts"],
        "max_attempts": job["max_attempts"],
        "last_error": job["last_error"],
        "started_at": job["created_at"],
        "finished_at": job["updated_at"],
        "event_log_retained": events_available,
        "note": (
            "This is the most recent build job, successful or not. Every attempt "
            "wipes the previous corpus before it starts, so the rows in the "
            "corpus always belong to this job's latest attempt."
        ),
    }


def _identify_stage(funnel: DiscoveryFunnel) -> dict[str, Any]:
    return {
        "count": funnel.identified_total,
        "source": "build event log",
        "by_fetcher": [
            {
                "fetcher": f.name,
                "candidates": f.candidates,
                "queries_run": f.queries,
                "skipped": f.skipped,
                "skip_reason": f.skip_reason,
            }
            for f in funnel.identified_by_fetcher
        ],
        "fetchers_available": funnel.fetchers_planned,
        "fetchers_run": funnel.fetchers_active,
        "duplicates_removed_before_triage": funnel.duplicates_removed_before_triage,
        "note": (
            "Candidates are search hits (title + snippet), before any content is "
            "downloaded. Counts are per fetcher after that fetcher removed its own "
            "duplicate URLs; duplicates_removed_before_triage is the further "
            "overlap removed when the fetchers' lists were pooled."
        ),
        "unattributable": UNPERSISTED["per_fetcher_attribution_after_triage"],
    }


def _screen_stage(funnel: DiscoveryFunnel) -> dict[str, Any]:
    return {
        "count": funnel.screened_at_triage,
        "source": "build event log",
        "passed": funnel.passed_triage,
        "excluded": funnel.excluded_at_triage,
        "excluded_by_reason": None,
        "excluded_by_reason_unavailable_reason": UNPERSISTED["triage_exclusion_reasons"],
        "note": (
            "Triage scores every pooled candidate on title and snippet alone and "
            "keeps those above a minimum expected value, dropping near-duplicate "
            "titles. It is a cheap pre-screen that decides what is worth "
            "downloading — not the validation decision."
        ),
    }


def _retrieve_stage(funnel: DiscoveryFunnel) -> dict[str, Any]:
    return {
        "count": funnel.fetched_full_text,
        "source": "build event log",
        "fetch_budget": funnel.fetch_budget,
        "ranked_not_fetched": funnel.ranked_not_fetched,
        "snowballed_added": funnel.snowballed_added,
        "fetch_failures": None,
        "fetch_failures_unavailable_reason": UNPERSISTED["fetch_failures"],
        "note": (
            "Full text was downloaded for the highest-ranked candidates until the "
            "tier's budget was met. ranked_not_fetched is dominated by candidates "
            "the budget never reached — it is NOT an exclusion for cause, and it "
            "cannot be separated from per-type caps or failed downloads."
        ),
        "stage_timings": funnel.stage_timings,
    }


def _gapfill_block(funnel: DiscoveryFunnel | None) -> dict[str, Any]:
    if funnel is None or funnel.gapfill_attempted is None:
        return {
            "attempted": None,
            "unavailable_reason": (
                "Gap-fill is recorded in the build event log, which is not "
                "retained for this expert. Whether a concept was gap-filled is "
                "still visible per source via discovered_via = 'gapfill:<concept>'."
            ),
        }
    return {
        "attempted": funnel.gapfill_attempted,
        "concepts_re_searched": funnel.gapfill_concepts,
        "sources_accepted": funnel.gapfill_accepted,
        "still_uncovered_after": funnel.gapfill_still_uncovered,
        "candidates_identified": None,
        "candidates_identified_unavailable_reason": UNPERSISTED[
            "gapfill_candidates_identified"
        ],
        "note": (
            "After validation, any key concept no accepted source covered gets one "
            "targeted re-search. Concepts still listed in still_uncovered_after "
            "have no accepted source at all."
        ),
    }


def _concept_block(
    concept: str,
    rows: list[dict[str, Any]],
    gapfill: dict[str, Any] | None,
) -> dict[str, Any]:
    qualities = [float(r["quality_score"]) for r in rows if r["quality_score"] is not None]
    relevances = [
        float(r["relevance_score"]) for r in rows if r["relevance_score"] is not None
    ]
    types = sorted({r["source_type"] for r in rows})
    mean_quality = safe_mean(qualities)
    gap_filled_here = [
        r for r in rows if (r.get("discovered_via") or "").startswith("gapfill:")
    ]
    strength = classify_coverage(len(rows), mean_quality, len(types))

    return {
        "concept": concept,
        "on_plan": True,
        "source_count": len(rows),
        "passage_count": sum(int(r.get("chunk_count") or 0) for r in rows),
        "mean_quality": mean_quality,
        "mean_relevance": safe_mean(relevances),
        "min_quality": round_or_none(min(qualities)) if qualities else None,
        "max_quality": round_or_none(max(qualities)) if qualities else None,
        "distinct_source_types": len(types),
        "source_types": types,
        "strength": strength.value,
        # True when the first discovery pass missed this concept entirely and
        # the pipeline had to run a targeted re-search for it.
        "needed_gap_fill": bool(gapfill) or bool(gap_filled_here),
        "gap_fill": (
            {
                "sources_found": gapfill["sources_found"],
                "sources_accepted": gapfill["accepted"],
            }
            if gapfill
            else None
        ),
        "sources": [
            {
                "id": r["id"],
                "title": r["title"],
                "url": r["url"],
                "author": r["author"],
                "source_type": r["source_type"],
                "content_type": r["content_type"],
                "difficulty": r["difficulty"],
                "quality_score": round_or_none(r["quality_score"]),
                "relevance_score": round_or_none(r["relevance_score"]),
                "discovered_via": r["discovered_via"],
                "discovery_method": parse_discovery_method(r.get("discovered_via"))[0],
                "passage_count": int(r.get("chunk_count") or 0),
            }
            for r in rows[:MAX_CONCEPT_SOURCES]
        ],
        "sources_truncated": len(rows) > MAX_CONCEPT_SOURCES,
    }


def _search_provenance_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The corpus grouped by which search produced it.

    Search provenance is the part of the record that bibliographic-database
    tools cannot have: they begin from an export, so every record arrived the
    same way. Here each row is a distinct search path, and a
    ``gapfill:<concept>`` row is a search that exists only because that concept
    was uncovered.
    """
    searches = []
    for r in rows:
        method, concept = parse_discovery_method(
            None if r["discovered_via"] == "(not recorded)" else r["discovered_via"]
        )
        searches.append(
            {
                "discovered_via": r["discovered_via"],
                "method": method,
                "concept": concept,
                "considered": r["considered"],
                "accepted": r["accepted"],
                "rejected": r["rejected"],
                "accepted_mean_quality": round_or_none(r["accepted_mean_quality"]),
                "accepted_mean_relevance": round_or_none(r["accepted_mean_relevance"]),
                "source_types": list(r["source_types"] or []),
            }
        )
    return {
        "searches": searches,
        "distinct_searches": len(searches),
        "note": (
            "One row per distinct search path recorded on the sources. 'plan' is "
            "the planned first pass, 'snowball' followed high-citation references "
            "out of discovered preprints, and each 'gapfill:<concept>' is a "
            "targeted re-search run because that concept had no accepted source. "
            "'(not recorded)' marks sources ingested before discovery provenance "
            "was persisted (migration 012)."
        ),
    }


def _search_strategy_block(
    funnel: DiscoveryFunnel | None, by_search: list[dict[str, Any]]
) -> dict[str, Any]:
    """How the search was executed — the "records identified" half of the record.

    Reports how many queries each fetcher ran and which fetchers were skipped
    and why. The query STRINGS are not persisted anywhere, so they are reported
    as unavailable rather than reconstructed: the research plan that produced
    them is built per run and never written down.
    """
    fetchers = (
        [
            {
                "fetcher": f.name,
                "queries_run": f.queries,
                "candidates_identified": f.candidates,
                "skipped": f.skipped,
                "skip_reason": f.skip_reason,
            }
            for f in funnel.identified_by_fetcher
        ]
        if funnel
        else []
    )
    return {
        "fetchers": fetchers,
        "fetchers_available": funnel.fetchers_planned if funnel else [],
        "fetchers_run": funnel.fetchers_active if funnel else [],
        "queries_issued": (
            sum(f["queries_run"] for f in fetchers if f["queries_run"] is not None)
            if fetchers
            else None
        ),
        "query_text": None,
        "query_text_unavailable_reason": (
            "The per-fetcher search queries are generated by the planning stage at "
            "the start of each build and are not persisted — only how many were "
            "issued per fetcher. The exact query strings therefore cannot be "
            "reported or re-run."
        ),
        "searches_recorded_on_sources": len(by_search),
        "note": (
            "Peritus searches open sources — web pages, PDFs with OCR, video "
            "transcripts, books, preprints, practitioner discussion — rather than "
            "importing a bibliographic database export. Every source it kept or "
            "dropped records which of these searches produced it; see by_search on "
            "the corpus report."
        ),
    }


def _gapfill_rounds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """"This concept was uncovered, so this search ran, and it returned these."

    Grouped from ``discovered_via = 'gapfill:<concept>'`` on the sources
    themselves, so it survives even when the build event log does not. Rejected
    results are listed alongside accepted ones — a re-search that returned four
    sources and kept none is a stronger statement about the evidence base than
    one that simply found nothing.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        concept = row.get("concept")
        if concept:
            grouped.setdefault(concept, []).append(row)

    rounds = []
    for concept, items in sorted(grouped.items()):
        accepted = [i for i in items if i["passed"]]
        rounds.append(
            {
                "concept": concept,
                "trigger": (
                    f"No accepted source covered {concept!r} after the first "
                    "validation round, so a targeted re-search was run for it."
                ),
                "sources_returned": len(items),
                "sources_accepted": len(accepted),
                "sources_rejected": len(items) - len(accepted),
                "outcome": (
                    "covered after gap-fill" if accepted else "still uncovered after gap-fill"
                ),
                "sources": [
                    {
                        "id": i["id"],
                        "title": i["title"],
                        "url": i["url"],
                        "source_type": i["source_type"],
                        "author": i["author"],
                        "decision": "accepted" if i["passed"] else "rejected",
                        "quality_score": round_or_none(i["quality_score"]),
                        "relevance_score": round_or_none(i["relevance_score"]),
                        "drop_reason": None if i["passed"] else i["drop_reason"],
                    }
                    for i in items
                ],
            }
        )
    return rounds


def _contradictions_not_computed(
    expert: Expert, readiness: Readiness, limit: int, offset: int
) -> dict[str, Any]:
    """The "not analysed yet" response — explicitly not "no contradictions found"."""
    return {
        "expert": _expert_stub(expert),
        "method_statement": METHOD_STATEMENT,
        "computed": False,
        "readiness": readiness.value,
        "unavailable_reason": (
            "Contradictions are read from the concept graph, which has not been "
            f"extracted for this expert yet (it is {readiness.label}). An empty "
            "list here would mean 'not looked for', not 'none found' — so none is "
            "returned. Re-request once the expert reaches graph_ready."
        ),
        "summary": {
            "contradictions": None,
            "concepts_involved": None,
            "relationships_total": None,
            "share_of_relationships": None,
            "cross_source_on_page": None,
            "within_source_on_page": None,
            "undetermined_on_page": None,
        },
        "relationship_mix": [],
        "note": (
            "A contradiction is an edge a language model extracted while reading "
            "the corpus, between two concept nodes."
        ),
        "page": {
            "limit": limit,
            "offset": offset,
            "returned": 0,
            "total_matching": None,
            "has_more": False,
            "passages_per_side": None,
            "excerpt_chars": None,
        },
        "contradictions": [],
    }


def _pick_side_chunks(own: list[int], other: list[int], want: int) -> list[int]:
    """Choose the passages that best represent one side of a contradiction.

    Chunks unique to this side come first: a chunk both concepts were extracted
    from cannot show what distinguishes them. Shared chunks fill any remainder
    rather than leaving a side blank.
    """
    other_set = set(other)
    exclusive = [c for c in own if c not in other_set]
    shared = [c for c in own if c in other_set]
    return (exclusive + shared)[:want]


def _contradiction_item(
    edge: dict[str, Any],
    a_ids: list[int],
    b_ids: list[int],
    chunks: dict[int, dict[str, Any]],
    passages_per_side: int,
) -> dict[str, Any]:
    a = _side(edge, "from", a_ids, chunks, passages_per_side)
    b = _side(edge, "to", b_ids, chunks, passages_per_side)

    a_sources = {p["source_id"] for p in a["passages"]}
    b_sources = {p["source_id"] for p in b["passages"]}
    shared = sorted(a_sources & b_sources)
    if not a_sources or not b_sources:
        kind = "undetermined"
    elif a_sources == b_sources:
        kind = "within_source"
    else:
        kind = "cross_source"

    return {
        "edge_id": edge["edge_id"],
        "weight": round_or_none(edge["weight"], 3),
        "properties": decode_json_field(edge.get("properties"), None),
        "kind": kind,
        "shared_source_ids": shared,
        "side_a": a,
        "side_b": b,
    }


def _side(
    edge: dict[str, Any],
    prefix: str,
    chunk_ids: list[int],
    chunks: dict[int, dict[str, Any]],
    passages_per_side: int,
) -> dict[str, Any]:
    all_ids = list(edge[f"{prefix}_chunk_ids"] or [])
    passages = [
        _passage(chunks[cid]) for cid in chunk_ids if cid in chunks
    ]
    return {
        "node": {
            "id": edge[f"{prefix}_id"],
            "label": edge[f"{prefix}_label"],
            "node_type": edge[f"{prefix}_node_type"],
            "description": edge[f"{prefix}_description"],
        },
        "passage_count": len(all_ids),
        "passages": passages,
        "passages_truncated": len(all_ids) > len(passages),
        "missing_passages": len(chunk_ids) - len(passages),
    }


def _passage(chunk: dict[str, Any]) -> dict[str, Any]:
    title = chunk["source_title"]
    stype = (chunk["source_type"] or "").title()
    quality = chunk["quality_score"]
    citation = f"{title} — {stype}" + (f" · Q:{quality:.1f}" if quality else "")
    return {
        "chunk_id": chunk["chunk_id"],
        "sequence_n": chunk["sequence_n"],
        "excerpt": chunk["excerpt"],
        "truncated": int(chunk["text_length"] or 0) > len(chunk["excerpt"] or ""),
        "context": chunk["context_text"],
        "source_id": chunk["source_id"],
        "source_title": title,
        "source_type": chunk["source_type"],
        "source_url": chunk["url"],
        "source_author": chunk["author"],
        "quality_score": round_or_none(quality),
        "relevance_score": round_or_none(chunk["relevance_score"]),
        "citation": citation,
    }


def _audit_header(row: dict[str, Any]) -> dict[str, Any]:
    retrieved = int(row["retrieved_passages"] or 0)
    in_context = int(row["context_passages"] or 0)
    return {
        "audit_id": str(row["id"]),
        "conversation_id": str(row["conversation_id"]) if row["conversation_id"] else None,
        "question": row["question"],
        "subqueries": decode_json_field(row["subqueries"], []),
        "followup_queries": decode_json_field(row["followup_queries"], []),
        "coverage_satisfied": row["coverage_satisfied"],
        "second_pass": row["second_pass"],
        "passages": {
            "retrieved": retrieved,
            "duplicate_hits": int(row["duplicate_hits"] or 0),
            "unique": int(row["unique_passages"] or 0),
            "in_context": in_context,
            "cited": int(row["cited_passages"] or 0),
            "not_in_context": max(0, int(row["unique_passages"] or 0) - in_context),
            "context_cap": row["context_cap"],
        },
        "sources": {
            "in_context": int(row["sources_in_context"] or 0),
            "cited": int(row["sources_cited"] or 0),
        },
        "contradiction_traversed": row["contradiction_traversed"],
        "answer_chars": int(row["answer_chars"] or 0),
        "created_at": row["created_at"],
    }
