"""Turn one answered question into its retrieval audit trail.

The trail answers three questions about an answer that has just been given:
how many passages were retrieved and considered, how many the answer actually
cited, and what happened to each individual passage.

**It is not a quality score.** Nothing here grades the answer, and nothing here
should be rendered as a confidence figure. A groundedness percentage lives in
``chat/faithfulness.py`` for offline evaluation only, and is deliberately absent
from anything a reader sees — a number invites people to trust the summary
instead of checking the citations, which is the opposite of the point.

Pure functions over the retrieval trail, so the mapping from retrieval to
disposition is testable without a model call or a database.
"""

from __future__ import annotations

from typing import Any

from peritus.audit.domain import (
    DISPOSITION_CITED,
    DISPOSITION_IN_CONTEXT_UNCITED,
    DISPOSITION_NOT_IN_CONTEXT,
)
from peritus.chat.agent import RetrievalTrail
from peritus.chat.grounding import Passage


def build_audit_payload(
    trail: RetrievalTrail | None,
    passages: list[Passage],
    cited: set[int],
    answer_text: str,
    has_contradiction: bool,
    graph_ready: bool,
) -> dict[str, Any]:
    """Assemble the ``retrieval_audit`` payload for one answer.

    ``graph_ready`` distinguishes "the graph found no contradiction here" from
    "the graph has not been built yet". Without it a half-built expert would
    report every answer as contradiction-free, which reads as a finding and is
    not one.
    """
    steps = list(trail.steps) if trail else []

    # Passages, in order, are the first N unique retrieved chunks, so the nth
    # retrieval step maps to the nth numbered passage. Guard on length rather
    # than assuming, so a future change to context assembly degrades to
    # "not_in_context" instead of mislabelling a citation.
    dispositions: list[dict[str, Any]] = []
    in_context_sources: set[int] = set()
    cited_sources: set[int] = set()

    for i, step in enumerate(steps):
        n = passages[i].index if i < len(passages) else None
        if n is None:
            disposition = DISPOSITION_NOT_IN_CONTEXT
        elif n in cited:
            disposition = DISPOSITION_CITED
            cited_sources.add(step.source_id)
            in_context_sources.add(step.source_id)
        else:
            disposition = DISPOSITION_IN_CONTEXT_UNCITED
            in_context_sources.add(step.source_id)

        dispositions.append(
            {
                "n": n,
                "chunk_id": step.chunk_id,
                "source_id": step.source_id,
                "source_title": step.source_title,
                "source_type": step.source_type,
                "quality_score": (
                    round(step.quality_score, 2) if step.quality_score is not None else None
                ),
                "retrieval_rank": step.rank,
                "retrieval_score": round(float(step.score), 4),
                "retrieved_via": step.via,
                "disposition": disposition,
            }
        )

    unique = len(steps)
    in_context = len(passages)
    return {
        "subqueries": list(trail.subqueries) if trail else [],
        "followup_queries": list(trail.followup_queries) if trail else [],
        "coverage": {
            "satisfied": trail.coverage_satisfied if trail else None,
            "second_pass": bool(trail.second_pass) if trail else False,
        },
        "passages": {
            "retrieved": unique + (trail.duplicate_hits if trail else 0),
            "duplicate_hits": trail.duplicate_hits if trail else 0,
            "unique": unique,
            "in_context": in_context,
            "cited": len(cited),
            "not_in_context": max(0, unique - in_context),
            "context_cap": trail.context_cap if trail else None,
        },
        "sources": {
            "in_context": len(in_context_sources),
            "cited": len(cited_sources),
        },
        "graph": {
            "expanded": bool(trail.graph_expanded) if trail else False,
            # None means "not analysed yet", which is not the same as False.
            "contradiction_traversed": has_contradiction if graph_ready else None,
            "unavailable_reason": (
                None
                if graph_ready
                else (
                    "The concept graph for this expert has not been extracted yet, "
                    "so contradictions between its sources have not been looked "
                    "for. This is not a finding that none exist."
                )
            ),
        },
        "answer_chars": len(answer_text),
        "dispositions": dispositions,
        "note": (
            "An audit trail of how evidence reached this answer, not a score of "
            "the answer. 'in_context_uncited' records what the model could see; it "
            "is not a judgement that the passage was irrelevant."
        ),
    }


def audit_db_rows(
    payload: dict[str, Any],
    expert_id: int,
    conversation_id: str | None,
    question: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Split an audit payload into the header row and passage rows for persistence."""
    passages = payload["passages"]
    header = {
        "expert_id": expert_id,
        "conversation_id": conversation_id,
        "question": question,
        "subqueries": payload["subqueries"],
        "followup_queries": payload["followup_queries"],
        "coverage_satisfied": payload["coverage"]["satisfied"],
        "second_pass": payload["coverage"]["second_pass"],
        "retrieved_passages": passages["retrieved"],
        "duplicate_hits": passages["duplicate_hits"],
        "unique_passages": passages["unique"],
        "context_passages": passages["in_context"],
        "cited_passages": passages["cited"],
        "context_cap": passages["context_cap"],
        "sources_in_context": payload["sources"]["in_context"],
        "sources_cited": payload["sources"]["cited"],
        # Persisted as a boolean column; an un-analysed graph stores false and is
        # distinguished at read time by the expert's readiness.
        "contradiction_traversed": bool(payload["graph"]["contradiction_traversed"]),
        "answer_chars": payload["answer_chars"],
    }
    rows = [
        {
            "passage_n": d["n"],
            "chunk_id": d["chunk_id"],
            "source_id": d["source_id"],
            "source_title": d["source_title"],
            "source_type": d["source_type"],
            "quality_score": d["quality_score"],
            "retrieval_rank": d["retrieval_rank"],
            "retrieval_score": d["retrieval_score"],
            "retrieved_via": d["retrieved_via"],
            "disposition": d["disposition"],
        }
        for d in payload["dispositions"]
    ]
    return header, rows
