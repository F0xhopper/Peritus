import asyncio

import asyncpg

from peritus.core.config import settings
from peritus.infrastructure.embeddings import embed_text
from peritus.infrastructure.reranker import rerank
from peritus.search.domain import SearchResponse, SearchResult, SourceRef


class SearchService:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def search(
        self,
        expert_id: int,
        query: str,
        top_k: int = 10,
    ) -> SearchResponse:
        query_embedding = await embed_text(query)

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

        embeddings = await asyncio.gather(*[embed_text(q) for q in queries])

        all_hits = await asyncio.gather(*[
            self._hybrid_search(
                expert_id=expert_id,
                query_embedding=emb,
                query_text=q,
                candidate_k=candidate_k,
                top_k=fetch_k,
            )
            for q, emb in zip(queries, embeddings)
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
        from pgvector.asyncpg import register_vector  # type: ignore
        async with self._pool.acquire() as conn:
            await register_vector(conn)
            rows = await conn.fetch(
                """
                WITH semantic AS (
                    SELECT sc.id, sc.expert_id, sc.source_id, sc.text, sc.context_text,
                           sc.sequence_n, sc.chunk_meta,
                           s.title AS source_title, s.source_type, s.quality_score,
                           1 - (sc.embedding <=> $1) AS sem_score,
                           ROW_NUMBER() OVER (ORDER BY sc.embedding <=> $1) AS sem_rank
                    FROM source_chunks sc
                    JOIN sources s ON s.id = sc.source_id
                    WHERE sc.expert_id = $2
                    ORDER BY sc.embedding <=> $1
                    LIMIT $3
                ),
                keyword AS (
                    SELECT sc.id,
                           ts_rank_cd(
                               to_tsvector('english', sc.text),
                               plainto_tsquery('english', $4)
                           ) AS kw_score,
                           ROW_NUMBER() OVER (
                               ORDER BY ts_rank_cd(
                                   to_tsvector('english', sc.text),
                                   plainto_tsquery('english', $4)
                               ) DESC
                           ) AS kw_rank
                    FROM source_chunks sc
                    WHERE sc.expert_id = $2
                      AND to_tsvector('english', sc.text) @@ plainto_tsquery('english', $4)
                    LIMIT $3
                ),
                fused AS (
                    SELECT
                        COALESCE(s.id, k.id) AS id,
                        COALESCE(1.0 / (60 + s.sem_rank), 0) +
                        COALESCE(1.0 / (60 + k.kw_rank), 0) AS rrf_score
                    FROM semantic s
                    FULL OUTER JOIN keyword k ON k.id = s.id
                )
                SELECT sem.*, fused.rrf_score
                FROM fused
                JOIN semantic sem ON sem.id = fused.id
                ORDER BY fused.rrf_score DESC
                LIMIT $5
                """,
                query_embedding, expert_id, candidate_k, query_text, top_k,
            )
        return rows


def _row_to_result(row) -> SearchResult:
    import json as _json
    meta = row["chunk_meta"] or {}
    if isinstance(meta, str):
        meta = _json.loads(meta)
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
