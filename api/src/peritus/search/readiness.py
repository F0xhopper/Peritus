"""Retrieval readiness — what an expert can answer with *right now*.

``experts.status`` tracks the build **job** (queued → building → ready/failed).
That is a poor proxy for whether the expert can be talked to, because the corpus
becomes retrievable long before the job finishes: hybrid search (pgvector
semantic ⊕ Postgres full-text, fused by RRF in
:meth:`peritus.search.service.SearchService._hybrid_search`) reads only
``source_chunks``/``sources``. It has no dependency on the concept graph, and
:meth:`peritus.graph.retriever.GraphRetriever.expand` already returns bare
passages when an expert has no nodes yet. So the moment the embed stage lands,
a grounded, cited answer is possible — the graph-extraction and persona stages
that follow only improve it.

``experts.readiness`` records that separately from job status:

    pending      no retrievable corpus yet (planning / discovery / validation)
    chat_ready   chunks embedded — hybrid search + citations work, no graph
                 expansion and possibly no persona voice yet
    graph_ready  concept graph extracted and resolved — full retrieval

The state only ever moves forward within a build, and a rebuild resets it to
``pending`` (see :meth:`peritus.experts.builder.ExpertBuilder.build`) so an
expert whose corpus has just been deleted for a rebuild is never advertised as
chattable.

This lives in ``search/`` rather than ``experts/`` deliberately: the question it
answers is "which retrieval capabilities exist for this expert", which is the
retrieval layer's to own. Callers outside retrieval (API routes) read it through
:func:`get_readiness`.
"""

from enum import StrEnum

import asyncpg

from peritus.core.logging import get_logger

logger = get_logger(__name__)


class Readiness(StrEnum):
    PENDING = "pending"
    CHAT_READY = "chat_ready"
    GRAPH_READY = "graph_ready"

    @property
    def can_chat(self) -> bool:
        """Whether retrieval can produce a grounded, cited answer."""
        return self is not Readiness.PENDING

    @property
    def graph_expanded(self) -> bool:
        """Whether retrieved passages carry concept-graph context and contradiction flags."""
        return self is Readiness.GRAPH_READY

    @property
    def label(self) -> str:
        """Short human-readable description, for clients and error bodies."""
        return _LABELS[self]


_LABELS: dict[Readiness, str] = {
    Readiness.PENDING: "still gathering and validating sources",
    Readiness.CHAT_READY: "answering from its corpus; concept graph still building",
    Readiness.GRAPH_READY: "fully built",
}

# Migration 018 adds the column. Until it is applied, fall back to deriving the
# state from experts.status so a lagging migration degrades to the old
# all-or-nothing behaviour instead of failing builds and chats.
_COLUMN_MISSING_LOGGED = False


def _column_missing() -> None:
    global _COLUMN_MISSING_LOGGED
    if not _COLUMN_MISSING_LOGGED:
        _COLUMN_MISSING_LOGGED = True
        logger.warning(
            "experts.readiness column is missing — apply migration "
            "018_expert_readiness.sql to enable early chat availability"
        )


async def get_readiness(pool: asyncpg.Pool, expert_id: int) -> Readiness:
    """The expert's current retrieval readiness. Unknown experts read as PENDING."""
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                "SELECT readiness, status FROM experts WHERE id = $1", expert_id
            )
        except asyncpg.UndefinedColumnError:
            _column_missing()
            row = await conn.fetchrow("SELECT status FROM experts WHERE id = $1", expert_id)
            return Readiness.GRAPH_READY if row and row["status"] == "ready" else Readiness.PENDING
    if row is None:
        return Readiness.PENDING
    try:
        return Readiness(row["readiness"])
    except ValueError:
        return Readiness.PENDING


async def set_readiness(pool: asyncpg.Pool, expert_id: int, readiness: Readiness) -> None:
    """Record a readiness transition. Never raises — readiness is an optimisation."""
    timestamp_col = {
        Readiness.CHAT_READY: "chat_ready_at",
        Readiness.GRAPH_READY: "graph_ready_at",
    }.get(readiness)
    stamp = f", {timestamp_col} = NOW()" if timestamp_col else ""
    reset = (
        ", chat_ready_at = NULL, graph_ready_at = NULL"
        if readiness is Readiness.PENDING
        else ""
    )
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE experts SET readiness = $1{stamp}{reset}, updated_at = NOW() "
                "WHERE id = $2",
                readiness.value,
                expert_id,
            )
    except asyncpg.UndefinedColumnError:
        _column_missing()
    except Exception as exc:
        logger.warning("Could not record readiness=%s for expert %d: %s", readiness, expert_id, exc)
