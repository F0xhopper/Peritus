import asyncio
import json

import asyncpg

from peritus.core.config import settings
from peritus.infrastructure.database import halfvec_supported
from peritus.infrastructure.embeddings import embed_query
from peritus.infrastructure.reranker import rerank
from peritus.search.domain import SearchResponse, SearchResult, SourceRef


def _distance_expr() -> tuple[str, str]:
    """The cosine-distance expression for ORDER BY, as ``(column, parameter)``.

    pgvector cannot build an HNSW or IVFFlat index on a ``vector`` wider than
    2000 dimensions, and the corpus is embedded at 3072. ``halfvec`` (pgvector
    ≥ 0.7) raises that ceiling to 4000, so migration 019 indexes the *expression*
    ``embedding::halfvec(n)`` — and the query has to order by the identical
    expression or the planner will not use it.

    Half precision costs nothing that matters here: it is a candidate-generation
    ranking that a cross-encoder reranks afterwards, and both the indexed and
    unindexed paths use the same expression, so results do not shift depending on
    whether the index happens to exist.
    """
    dim = settings.EMBED_DIM
    if halfvec_supported():
        # The parameter stays a `vector` — that is the codec registered on the
        # connection — and Postgres narrows it once, not per row.
        return f"sc.embedding::halfvec({dim})", f"$1::vector({dim})::halfvec({dim})"
    return "sc.embedding", "$1"


class SearchService:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def search(
        self,
        expert_id: int,
        query: str,
        top_k: int = 10,
    ) -> SearchResponse:
        query_embedding = await embed_query(query)

        rerank_on = settings.RERANK_ENABLED and bool(settings.ANTHROPIC_API_KEY)
        fetch_k = max(settings.RERANK_CANDIDATES, top_k) if rerank_on else top_k

        hits = await self._hybrid_search(
            expert_id=expert_id,
            query_embedding=query_embedding,
            query_text=query,
            candidate_k=max(fetch_k * 4, 100),
            top_k=fetch_k,
        )

        results = [_row_to_result(r) for r in hits]

        if rerank_on and len(results) > 1:
            ranking = await rerank(query, [r.text for r in results], top_n=top_k)
            reranked = []
            for idx, score in ranking:
                hit = results[idx]
                hit.score = round(float(score), 4)
                reranked.append(hit)
            results = reranked
        else:
            results = results[:top_k]

        return SearchResponse(query=query, results=results, total=len(results))

    async def batch_search(
        self,
        expert_id: int,
        question: str,
        queries: list[str],
        top_k: int = 10,
    ) -> SearchResponse:
        rerank_on = settings.RERANK_ENABLED and bool(settings.ANTHROPIC_API_KEY)
        fetch_k = max(settings.RERANK_CANDIDATES, top_k) if rerank_on else top_k
        candidate_k = max(fetch_k * 4, 100)

        embeddings = await asyncio.gather(*[embed_query(q) for q in queries])

        all_hits = await asyncio.gather(*[
            self._hybrid_search(
                expert_id=expert_id,
                query_embedding=emb,
                query_text=q,
                candidate_k=candidate_k,
                top_k=fetch_k,
            )
            for q, emb in zip(queries, embeddings, strict=True)
        ])

        merged = _merge_hits([[_row_to_result(r) for r in hits] for hits in all_hits])
        merged = merged[:max(fetch_k, top_k)]

        if rerank_on and len(merged) > 1:
            ranking = await rerank(question, [r.text for r in merged], top_n=top_k)
            reranked = []
            for idx, score in ranking:
                hit = merged[idx]
                hit.score = round(float(score), 4)
                reranked.append(hit)
            merged = reranked
        else:
            merged = merged[:top_k]

        return SearchResponse(query=question, results=merged, total=len(merged))

    async def _hybrid_search(
        self,
        expert_id: int,
        query_embedding: list[float],
        query_text: str,
        candidate_k: int,
        top_k: int,
    ):
        """Semantic ⊕ keyword candidates, fused by reciprocal rank.

        Both arms rank in a wrapper over an already-limited subquery rather than
        ranking and limiting in one level. That is not cosmetic: a window
        function is evaluated *before* ``LIMIT``, so in ``ROW_NUMBER() OVER
        (ORDER BY <distance>) … LIMIT k`` the ``WindowAgg`` sits between the
        limit and the scan and has to consume every chunk the expert owns.
        The index is still used, but it cannot stop at k — which is most of what
        an ANN index is for. Ranking outside the limit makes ``Limit`` the direct
        parent of the index scan, so it terminates after k rows (verified on
        Postgres 17 / pgvector 0.8).

        The candidate arms select ``id`` only. Chunk text is fetched once, at the
        end, for the fused set — the previous shape hauled full text for every
        semantic candidate and then discarded it to re-fetch the same columns.
        """
        dist_col, dist_param = _distance_expr()
        sql = f"""
            WITH semantic AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY distance) AS sem_rank
                FROM (
                    SELECT sc.id, {dist_col} <=> {dist_param} AS distance
                    FROM source_chunks sc
                    WHERE sc.expert_id = $2 AND sc.embedding IS NOT NULL
                    ORDER BY {dist_col} <=> {dist_param}
                    LIMIT $3
                ) ranked
            ),
            keyword AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY rank DESC) AS kw_rank
                FROM (
                    SELECT sc.id,
                           ts_rank_cd(
                               to_tsvector('english', sc.text),
                               plainto_tsquery('english', $4)
                           ) AS rank
                    FROM source_chunks sc
                    WHERE sc.expert_id = $2
                      AND to_tsvector('english', sc.text) @@ plainto_tsquery('english', $4)
                    ORDER BY rank DESC
                    LIMIT $3
                ) matched
            ),
            fused AS (
                SELECT
                    COALESCE(s.id, k.id) AS id,
                    COALESCE(1.0 / (60 + s.sem_rank), 0) +
                    COALESCE(1.0 / (60 + k.kw_rank), 0) AS rrf_score
                FROM semantic s
                FULL OUTER JOIN keyword k ON k.id = s.id
            )
            -- Fetch columns for EVERY fused id (semantic OR keyword-only) so
            -- keyword matches outside the vector top-N still surface as results.
            SELECT sc.id, sc.expert_id, sc.source_id, sc.text, sc.context_text,
                   sc.sequence_n, sc.chunk_meta,
                   s.title AS source_title, s.source_type, s.quality_score,
                   fused.rrf_score
            FROM fused
            JOIN source_chunks sc ON sc.id = fused.id
            JOIN sources s ON s.id = sc.source_id
            ORDER BY fused.rrf_score DESC
            LIMIT $5
        """
        async with self._pool.acquire(timeout=settings.DB_ACQUIRE_TIMEOUT) as conn:
            rows = await conn.fetch(
                sql, query_embedding, expert_id, candidate_k, query_text, top_k
            )
        return rows


def _row_to_result(row) -> SearchResult:
    meta = row["chunk_meta"] or {}
    if isinstance(meta, str):
        meta = json.loads(meta)
    return SearchResult(
        chunk_id=row["id"],
        expert_id=row["expert_id"],
        source_id=row["source_id"],
        text=row["text"],
        context_text=row["context_text"],
        score=float(row["rrf_score"]),
        sequence_n=row["sequence_n"],
        chunk_meta=meta,
        source_ref=SourceRef(
            source_id=row["source_id"],
            title=row["source_title"],
            source_type=row["source_type"],
            quality_score=row["quality_score"],
        ),
    )


def _merge_hits(all_hits: list[list[SearchResult]]) -> list[SearchResult]:
    best: dict[int, SearchResult] = {}
    for hits in all_hits:
        for hit in hits:
            if hit.chunk_id not in best or hit.score > best[hit.chunk_id].score:
                best[hit.chunk_id] = hit
    merged = list(best.values())
    merged.sort(key=lambda x: x.score, reverse=True)
    return merged
