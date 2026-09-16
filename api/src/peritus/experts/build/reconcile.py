"""Stage 4b: making one thing out of several records of it.

Two different merges, at two different levels, and confusing them is the trap.

`_resolve_entities` merges *graph nodes*: "Stoicism", "stoicism" and "the Stoic
school" are one concept, and an unmerged graph shows a corpus as more fragmented
than it is. It works on embedding similarity, so it can only run after the graph
stage.

`_merge_same_volume` merges *sources*: Gutenberg's plain text and the Archive's
scan of the same book are one volume, and keeping both double-counts the corpus
and double-charges the reader.

`_reconcile_claims` is neither — it is what happens when two sources the corpus
kept disagree, and the answer is to record the disagreement rather than pick.
"""

import asyncio
from typing import Any

from peritus.core.logging import get_logger
from peritus.experts.build.events import EventCallback, _emit_event
from peritus.graph.reconciler import ReconcileStats, reconcile_claims
from peritus.graph.repository import GraphRepository, node_embedding_text
from peritus.graph.resolution import (
    RESOLVE_THRESHOLD,
    RESOLVE_THRESHOLD_SAME_HEAD,
    canonical_merge_plan,
    pair_threshold,
)
from peritus.infrastructure.anthropic_batch import (
    provider_error_message,
    terminal_provider_error,
)
from peritus.infrastructure.embeddings import embed_in_batches
from peritus.sources.domain import SourceCandidate

logger = get_logger(__name__)


async def _reconcile_claims(
    topic: str,
    expert_id: int,
    graph_repo: GraphRepository,
    on_event: EventCallback | None = None,
) -> int:
    """Relate the claims different sources make about the same concept.

    Best-effort inside a stage that is itself best-effort: a graph with claims,
    concepts and an index between them is already useful, so a failure here
    leaves that standing rather than degrading the whole stage and sending the
    build back through the worker's retry loop.

    ``claims_reconciled`` is emitted on every run, including the ones that
    insert nothing. It used to fire only when a relation was inserted, and
    production reconciliation has never inserted one: the church-fathers build
    spent 23 seconds in this stage — too short for ~120 model calls to have
    run, and four seconds before the API refused its persona call — and the
    log could not say whether the calls failed, returned nothing, or returned
    relations that were all rejected. The event now says which.
    """
    stats = ReconcileStats()
    groups: list = []
    inserted = 0
    error: str | None = None
    try:
        groups = await graph_repo.claims_by_concept(expert_id)
        if groups:
            relations = await reconcile_claims(topic, groups, stats=stats)
            inserted = await graph_repo.insert_relations(expert_id, relations)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("Claim reconciliation failed for expert %d: %s", expert_id, exc)

    parsed = stats.relations_returned - sum(stats.rejected.values())
    event: dict[str, Any] = {
        "type": "claims_reconciled",
        "concepts": len(groups),
        "relations": inserted,
        **stats.as_event(),
        # Parsed but refused at insert (endpoint types, missing property).
        "relations_refused_at_insert": max(0, parsed - inserted),
    }
    if error:
        event["error"] = error
    await _emit_event(on_event, event)

    if stats.concepts_examined and stats.calls_failed == stats.concepts_examined:
        provider = terminal_provider_error()
        logger.error(
            "Reconciliation for expert %d: every one of %d call(s) failed%s",
            expert_id,
            stats.calls_failed,
            f" — {provider_error_message(provider)}" if provider else "",
        )
    logger.info(
        "Reconciliation for expert %d: %d concept group(s), %d eligible, %d examined, "
        "%d call(s) failed, %d relation(s) returned, %d rejected %s, %d inserted",
        expert_id,
        len(groups),
        stats.concepts_eligible,
        stats.concepts_examined,
        stats.calls_failed,
        stats.relations_returned,
        sum(stats.rejected.values()),
        dict(stats.rejected),
        inserted,
    )
    return inserted


async def _resolve_entities(
    expert_id: int,
    graph_repo: GraphRepository,
    on_event: EventCallback | None = None,
) -> int:
    """Merge duplicate graph nodes: by canonical label, then by embedding.

    See :mod:`peritus.graph.resolution` for the rules and why cosine alone was
    not enough.
    """
    try:
        import numpy as np
    except ImportError:
        logger.debug("numpy not available — skipping entity resolution")
        return 0

    nodes = await graph_repo.get_all_nodes(expert_id)
    if len(nodes) < 2:
        return 0

    merge_count = 0

    async def _merge(keep: dict, drop: dict, how: str) -> None:
        nonlocal merge_count
        await graph_repo.merge_nodes(expert_id, keep["id"], drop["id"])
        merge_count += 1
        logger.debug("Merged node %r → %r (%s)", drop["label"], keep["label"], how)
        if on_event and merge_count % 25 == 0:
            await _emit_event(on_event, {"type": "resolve_progress", "merged": merge_count})

    # 1. Same concept by label: "Varroa mites" / "Varroa mite",
    #    "Deformed Wing Virus (DWV)" / "DWV (Deformed Wing Virus)".
    label_merged: set[int] = set()
    for keep, drops in canonical_merge_plan(nodes):
        for drop in drops:
            await _merge(keep, drop, "canonical label")
            label_merged.add(drop["id"])
    by_label = merge_count
    nodes = [n for n in nodes if n["id"] not in label_merged]
    if len(nodes) < 2:
        return merge_count

    # 2. Same thing by meaning. Node embeddings are persisted at insert time;
    # only nodes that missed embedding (e.g. an API blip during insert) get
    # re-embedded here. Batched so a graph whose embeddings all failed at insert
    # can't overflow one call.
    missing = [i for i, n in enumerate(nodes) if n.get("embedding") is None]
    if missing:
        texts = [
            node_embedding_text(nodes[i]["label"], nodes[i].get("description")) for i in missing
        ]
        try:
            fresh = await embed_in_batches(texts)
        except Exception as exc:
            logger.warning("Entity resolution embedding failed: %s", exc)
            return merge_count
        for i, emb in zip(missing, fresh, strict=True):
            nodes[i]["embedding"] = emb

    matrix = np.array([np.asarray(n["embedding"], dtype=np.float32) for n in nodes])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    normalized = matrix / norms
    sim = normalized @ normalized.T  # (N, N)

    # Candidate pairs at C speed (upper triangle, i < j) at the lowest threshold
    # any pair could use; the per-pair rule then decides. The old pure-Python
    # O(N²) double loop had no ``await`` on the common no-merge path, so on a
    # large graph it blocked the event loop — starving the job heartbeat — for
    # the whole pass. np.where keeps row-major order (increasing i, then j).
    floor = min(RESOLVE_THRESHOLD, RESOLVE_THRESHOLD_SAME_HEAD)
    rows, cols = np.where(np.triu(sim >= floor, k=1))

    merged_away: set[int] = set()
    for i, j in zip(rows.tolist(), cols.tolist(), strict=True):
        keep, drop = nodes[i], nodes[j]
        if keep["id"] in merged_away or drop["id"] in merged_away:
            continue
        threshold = pair_threshold(keep, drop)
        if threshold is None or sim[i, j] < threshold:
            continue
        await _merge(keep, drop, f"sim={float(sim[i, j]):.3f}")
        merged_away.add(drop["id"])

    if merge_count:
        logger.info(
            "Entity resolution: merged %d duplicate nodes for expert %d "
            "(%d by label, %d by embedding)",
            merge_count,
            expert_id,
            by_label,
            merge_count - by_label,
        )
    return merge_count


def _merge_same_volume(
    candidates: list[SourceCandidate], ceiling: int | None = None
) -> list[SourceCandidate]:
    """One candidate per URL, carrying every concept's sections for it.

    Two concepts can point at one volume — the Five Ways and the soul are both in
    the first part of a long work — and URL de-duplication would keep only the
    first lookup's sections. Merged here, the fetch cuts both.
    """
    by_url: dict[str, SourceCandidate] = {}
    kept: list[SourceCandidate] = []
    for candidate in candidates:
        key = candidate.url.rstrip("/").lower()
        first = by_url.get(key)
        if first is None:
            by_url[key] = candidate
            kept.append(candidate)
            continue
        meta, other = first.metadata, candidate.metadata
        sections = [
            p for p in (meta.get("must_have_sections"), other.get("must_have_sections")) if p
        ]
        if sections:
            meta["must_have_sections"] = "; ".join(dict.fromkeys(sections))
        concepts = list(
            dict.fromkeys(
                [*meta.get("must_have_concepts", []), *other.get("must_have_concepts", [])]
            )
        )
        if concepts:
            meta["must_have_concepts"] = concepts
        if other.get("fetch_priority"):
            meta["fetch_priority"] = True
            meta["priority_rank"] = min(meta.get("priority_rank", 2), other.get("priority_rank", 2))
        ceilings = [c for c in (meta.get("text_max_chars"), other.get("text_max_chars")) if c]
        if ceilings:
            # Two concepts' passages from one volume share one fetch, so the
            # ceiling grows with them — but never past one canonical work's
            # ceiling. Uncapped, three concept lookups on one Summa volume
            # summed to 600,000 characters on a live build, and the reservation
            # for that one volume starved the natural-law volume out of the
            # round.
            grown = sum(ceilings)
            meta["text_max_chars"] = min(grown, ceiling) if ceiling else max(ceilings)
    return kept
