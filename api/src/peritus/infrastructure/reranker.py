"""Passage reranking.

A single LLM call asked to score 50 passages at once is unreliable — discrimination
collapses as the list grows and a truncated tool response silently drops everything.
This module prefers a purpose-built cross-encoder reranker (Cohere) when a key is
available, and otherwise scores passages in small windows and merges the results.
"""

import asyncio

from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client, tool_input
from peritus.infrastructure.http import shared_client

logger = get_logger(__name__)

_MAX_DOC_CHARS = 1500

_TOOL: ToolParam = {
    "name": "rank_passages",
    "description": "Score how well each passage answers the query.",
    "input_schema": {
        "type": "object",
        "properties": {
            "rankings": {
                "type": "array",
                "description": "One entry per passage, by its index.",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "The passage's index."},
                        "relevance": {
                            "type": "number",
                            "description": "0.0 (irrelevant) to 1.0 (directly answers the query).",
                        },
                    },
                    "required": ["index", "relevance"],
                },
            }
        },
        "required": ["rankings"],
    },
}


#: Which reranker scored a ranking. The two scale their scores differently,
#: and a relevance floor calibrated on one is applied to both — so an answer
#: records which it was (``answer_audits.reranker``).
RERANKER_COHERE = "cohere"
RERANKER_LLM = "llm_window"
RERANKER_NONE = "none"

#: How many rankings the windowed-LLM fallback has produced since the process
#: started. The fallback is silent by design — an answer still gets ranked —
#: which is exactly why it needs counting: production reranked on a Cohere
#: trial key (10 calls a minute), and past the limit every turn quietly moved
#: to a reranker on another scale.
fallback_count = 0


async def rerank(
    query: str,
    documents: list[str],
    top_n: int,
) -> list[tuple[int, float]]:
    """Return ``[(doc_index, score), ...]`` for the top ``top_n`` documents."""
    ranking, _ = await rerank_with_provider(query, documents, top_n)
    return ranking


async def rerank_with_provider(
    query: str,
    documents: list[str],
    top_n: int,
) -> tuple[list[tuple[int, float]], str]:
    """:func:`rerank`, plus which reranker produced the ranking."""
    global fallback_count
    n = len(documents)
    identity = [(i, 0.0) for i in range(min(n, top_n))]
    if not settings.RERANK_ENABLED or n <= 1:
        return identity, RERANKER_NONE

    if settings.COHERE_API_KEY:
        cohere = await _cohere_rerank(query, documents, top_n)
        if cohere is not None:
            return cohere, RERANKER_COHERE

    if settings.ANTHROPIC_API_KEY:
        fallback_count += 1
        if settings.COHERE_API_KEY:
            # Every time, not once: a key that has stopped working (a trial
            # limit, a revoked key) must be visible in the logs of each turn it
            # affects, not only in the first.
            logger.warning(
                "Cohere rerank unavailable; scored %d passages with the LLM fallback "
                "(fallback #%d since start). Its scores are on a different scale.",
                n,
                fallback_count,
            )
        ranking = await _llm_windowed_rerank(query, documents, top_n)
        scored = any(score > 0 for _, score in ranking)
        return ranking, RERANKER_LLM if scored else RERANKER_NONE

    return identity, RERANKER_NONE


async def _cohere_rerank(
    query: str, documents: list[str], top_n: int
) -> list[tuple[int, float]] | None:
    """Cross-encoder rerank via the Cohere API. Returns None on any failure."""
    docs = [d[:_MAX_DOC_CHARS] for d in documents]
    try:
        client = shared_client(timeout=30, follow_redirects=False)
        resp = await client.post(
            "https://api.cohere.com/v2/rerank",
            headers={
                "Authorization": f"Bearer {settings.COHERE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.COHERE_RERANK_MODEL,
                "query": query,
                "documents": docs,
                "top_n": min(top_n, len(docs)),
            },
        )
        if resp.status_code != 200:
            logger.warning("Cohere rerank HTTP %d: %s", resp.status_code, resp.text[:200])
            return None
        results = resp.json().get("results", [])
        scored = [
            (int(r["index"]), float(r["relevance_score"]))
            for r in results
            if isinstance(r.get("index"), int) and 0 <= r["index"] < len(docs)
        ]
        return scored[:top_n] if scored else None
    except Exception as exc:
        logger.warning("Cohere rerank failed: %s", exc)
        return None


_warned_llm_fallback = False


async def _llm_windowed_rerank(
    query: str, documents: list[str], top_n: int
) -> list[tuple[int, float]]:
    """Score passages in small windows (concurrently) and merge by score."""
    n = len(documents)
    window = max(2, settings.RERANK_WINDOW)

    global _warned_llm_fallback
    if not _warned_llm_fallback:
        _warned_llm_fallback = True
        logger.warning(
            "%s — reranking falls back to ~%d windowed LLM calls per query. Cohere "
            "rerank is cheaper (~$2 per 1K searches) and higher quality.",
            "Cohere rerank failed" if settings.COHERE_API_KEY else "COHERE_API_KEY not set",
            -(-n // window),
        )
    sem = asyncio.Semaphore(4)

    windows = [list(range(i, min(i + window, n))) for i in range(0, n, window)]

    async def score_window(indices: list[int]) -> list[tuple[int, float]]:
        async with sem:
            return await _score_one_window(query, documents, indices)

    window_results = await asyncio.gather(*(score_window(w) for w in windows))

    scored: list[tuple[int, float]] = [pair for w in window_results for pair in w]
    seen = {idx for idx, _ in scored}
    if not scored:
        return [(i, 0.0) for i in range(min(n, top_n))]

    scored.sort(key=lambda x: x[1], reverse=True)
    scored.extend((i, 0.0) for i in range(n) if i not in seen)
    return scored[:top_n]


async def _score_one_window(
    query: str, documents: list[str], indices: list[int]
) -> list[tuple[int, float]]:
    """Score a small window; returns global-index scores. Empty list on failure."""
    try:
        client = get_anthropic_client()
        # Present passages 0..k locally, then map back to global indices.
        passages = "\n\n".join(
            f"[{local}]\n{documents[g][:_MAX_DOC_CHARS]}" for local, g in enumerate(indices)
        )
        resp = await client.messages.create(
            model=settings.FAST_MODEL,
            max_tokens=512,
            system=(
                "You are a search reranker. Score how directly each passage answers "
                "the query. Score every passage exactly once, by its index."
            ),
            tools=[_TOOL],
            tool_choice=ToolChoiceToolParam(type="tool", name="rank_passages"),
            messages=[
                MessageParam(role="user", content=f"Query: {query}\n\nPassages:\n\n{passages}")
            ],
        )
        block = tool_input(resp)
        if block is None:
            return []
        out: list[tuple[int, float]] = []
        seen_local: set[int] = set()
        for r in block.get("rankings", []):
            local, score = r.get("index"), r.get("relevance")
            if (
                isinstance(local, int)
                and 0 <= local < len(indices)
                and local not in seen_local
                and isinstance(score, (int, float))
            ):
                seen_local.add(local)
                out.append((indices[local], float(score)))
        return out
    except Exception as exc:
        logger.warning("Window rerank failed: %s", exc)
        return []
