import asyncio
import json
from collections.abc import Iterable

import asyncpg

from peritus.core.config import settings
from peritus.infrastructure.database import halfvec_supported, iterative_scan_sql
from peritus.infrastructure.embeddings import embed_query
from peritus.infrastructure.reranker import RERANKER_NONE, rerank, rerank_with_provider
from peritus.search.domain import SearchResponse, SearchResult, SourceRef

_ITERATIVE_SCAN_SQL = iterative_scan_sql(local=True)


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


# The text the keyword arm matches on: the chunk plus its contextual prefix.
# The prefix is generated and paid for per chunk at ingestion and is already part
# of what the semantic arm embeds, so excluding it here made half the retrieval
# pipeline blind to it. Must stay byte-identical to the index expression in
# migration 022 — a mismatch silently costs the index, not correctness.
_FTS_EXPR = "coalesce(sc.context_text, '') || ' ' || sc.text"

# The keyword arm's query: any of the terms, not all of them. `plainto_tsquery`
# ANDs every lexeme, and the planner writes four-to-seven-word subqueries, so a
# chunk had to contain every word of one to match at all — measured on real
# planner subqueries, 0 hits for 5 of 6 against 300–900 with OR. The lexemes
# still come from `plainto_tsquery` (stemming, stop words and punctuation are
# Postgres's job, and no user text is ever parsed as tsquery syntax); only the
# operator is swapped. `ts_rank_cd` still ranks a chunk matching four of six
# terms above one matching two.
_FTS_QUERY = "replace(plainto_tsquery('english', $4)::text, '&', '|')::tsquery"


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
            results, scored = _apply_ranking(
                results, await rerank(query, [rerank_document(r) for r in results], top_n=top_k)
            )
        else:
            results, scored = results[:top_k], False

        return SearchResponse(query=query, results=results, total=len(results), reranked=scored)

    async def batch_search(
        self,
        expert_id: int,
        question: str,
        queries: list[str],
        top_k: int = 10,
        include_question: bool = True,
        topic: str | None = None,
    ) -> SearchResponse:
        """Hybrid-search every query, fuse, and rerank against ``question``.

        ``include_question`` searches the question itself as one more query.
        The planner's subqueries are retrieval phrasings of it, and a short
        factual question often matches its own wording better than any
        paraphrase; RRF-summing already rewards a chunk that the question and a
        subquery both find. It costs one embedding. A follow-up pass over the
        same question turns it off — the primary pass already searched it.

        ``topic`` is the expert's subject, prefixed to the question the
        reranker scores against (``RERANK_TOPIC_PREFIX``): "What will happen at
        the moment of death?" says nothing about Aquinas, and the reranker
        reads the question and nothing else.

        The reranker scores every candidate, not only the ``top_k`` returned:
        ``candidates`` carries the whole scored list and ``per_query`` each
        query's own hits, so a caller can give a subquery that won nothing a
        seat of its own. Each query's two best hits are always among the
        candidates, however the fusion ranked them.
        """
        rerank_on = settings.RERANK_ENABLED and bool(settings.ANTHROPIC_API_KEY)
        fetch_k = max(settings.RERANK_CANDIDATES, top_k) if rerank_on else top_k
        candidate_k = max(fetch_k * 4, 100)
        if include_question:
            queries = _with_question(question, queries)

        embeddings = await asyncio.gather(*[embed_query(q) for q in queries])

        all_hits = await asyncio.gather(
            *[
                self._hybrid_search(
                    expert_id=expert_id,
                    query_embedding=emb,
                    query_text=q,
                    candidate_k=candidate_k,
                    top_k=fetch_k,
                )
                for q, emb in zip(queries, embeddings, strict=True)
            ]
        )

        per_query_hits = [[_row_to_result(r) for r in hits] for hits in all_hits]
        per_query = {
            q: [h.chunk_id for h in hits] for q, hits in zip(queries, per_query_hits, strict=True)
        }
        merged = _merge_hits(per_query_hits)
        merged = _with_each_querys_best(
            merged[: max(fetch_k, top_k)], merged, per_query.values(), per_query_best=2
        )

        reranker = RERANKER_NONE
        if rerank_on and len(merged) > 1:
            ranking, reranker = await rerank_with_provider(
                rerank_query(question, topic),
                [rerank_document(r) for r in merged],
                top_n=len(merged),
            )
            candidates, scored = _apply_ranking(merged, ranking)
        else:
            candidates, scored = merged, False

        return SearchResponse(
            query=question,
            results=candidates[:top_k],
            total=min(len(candidates), top_k),
            reranked=scored,
            reranker=reranker if scored else RERANKER_NONE,
            candidates=candidates,
            per_query=per_query,
            query_embeddings=dict(zip(queries, embeddings, strict=True)),
        )

    async def fetch_by_position(
        self,
        expert_id: int,
        positions: list[tuple[int, int]],
    ) -> list[SearchResult]:
        """The chunks at these ``(source_id, sequence_n)`` positions, unscored.

        Not a search: this is how a retrieved passage gets the text either side
        of it (``chat/neighbours.py``). Nothing ranked these, so the score is 0.0
        and a caller must not hold them to a relevance floor. A position that
        does not exist — the start or end of a source, a chunk hygiene removed —
        is simply absent from the result.
        """
        if not positions:
            return []
        sql = """
            SELECT sc.id, sc.expert_id, sc.source_id, sc.text, sc.context_text,
                   sc.sequence_n, sc.chunk_meta,
                   s.title AS source_title, s.source_type, s.quality_score,
                   0.0 AS rrf_score
            FROM unnest($2::int[], $3::int[]) AS wanted(source_id, sequence_n)
            JOIN source_chunks sc
              ON sc.source_id = wanted.source_id AND sc.sequence_n = wanted.sequence_n
            JOIN sources s ON s.id = sc.source_id
            WHERE sc.expert_id = $1
        """
        async with self._pool.acquire(timeout=settings.DB_ACQUIRE_TIMEOUT) as conn:
            rows = await conn.fetch(
                sql, expert_id, [p[0] for p in positions], [p[1] for p in positions]
            )
        return [_row_to_result(r) for r in rows]

    async def best_in_spans(
        self,
        expert_id: int,
        spans: list[tuple[int, int, int]],
        query_embedding: list[float],
        per_span: int,
    ) -> list[list[SearchResult]]:
        """The ``per_span`` chunks nearest the query inside each ``(source, lo, hi)``.

        How a routed section contributes its passages: the section was found by
        its summary, and the chunks in it are ranked by the question itself.
        Unscored (0.0) like neighbours — nothing reranked them.
        """
        if not spans:
            return []
        dist_col, dist_param = _distance_expr()
        sql = f"""
            SELECT * FROM (
                SELECT sc.id, sc.expert_id, sc.source_id, sc.text, sc.context_text,
                       sc.sequence_n, sc.chunk_meta,
                       s.title AS source_title, s.source_type, s.quality_score,
                       0.0 AS rrf_score, span.i AS span_i,
                       ROW_NUMBER() OVER (
                           PARTITION BY span.i ORDER BY {dist_col} <=> {dist_param}
                       ) AS rn
                FROM unnest($3::int[], $4::int[], $5::int[]) WITH ORDINALITY
                         AS span(source_id, lo, hi, i)
                JOIN source_chunks sc
                  ON sc.source_id = span.source_id
                 AND sc.sequence_n BETWEEN span.lo AND span.hi
                JOIN sources s ON s.id = sc.source_id
                WHERE sc.expert_id = $2 AND sc.embedding IS NOT NULL
            ) ranked
            WHERE rn <= $6
            ORDER BY span_i, rn
        """
        async with self._pool.acquire(timeout=settings.DB_ACQUIRE_TIMEOUT) as conn:
            rows = await conn.fetch(
                sql,
                query_embedding,
                expert_id,
                [s[0] for s in spans],
                [s[1] for s in spans],
                [s[2] for s in spans],
                per_span,
            )
        out: list[list[SearchResult]] = [[] for _ in spans]
        for r in rows:
            out[int(r["span_i"]) - 1].append(_row_to_result(r))
        return out

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
                               to_tsvector('english', {_FTS_EXPR}),
                               {_FTS_QUERY}
                           ) AS rank
                    FROM source_chunks sc
                    WHERE sc.expert_id = $2
                      AND to_tsvector('english', {_FTS_EXPR})
                          @@ {_FTS_QUERY}
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
            if halfvec_supported():
                # Correctness, not tuning — and it has to be SET LOCAL inside an
                # explicit transaction. An HNSW index cannot carry the expert_id
                # filter, so the scan finds globally-nearest vectors and Postgres
                # discards other experts' rows afterwards; with the default
                # `hnsw.iterative_scan = off` it stops after one ef_search pass
                # and quietly returns however few survived (measured: 40 rows of
                # a 184-chunk expert). Setting it per-connection does not work
                # here — DATABASE_URL points at Supabase's transaction pooler,
                # which hands each transaction a different backend and resets
                # session state between them, and the durable ALTER
                # DATABASE/ROLE form is refused to non-superusers.
                async with conn.transaction():
                    await conn.execute(_ITERATIVE_SCAN_SQL)
                    return await conn.fetch(
                        sql, query_embedding, expert_id, candidate_k, query_text, top_k
                    )
            return await conn.fetch(sql, query_embedding, expert_id, candidate_k, query_text, top_k)


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


def _apply_ranking(
    hits: list[SearchResult], ranking: list[tuple[int, float]]
) -> tuple[list[SearchResult], bool]:
    """Reorder ``hits`` by the reranker's ranking and adopt its scores.

    Returns the ranked hits and whether the scores are real relevance scores.
    `rerank` degrades to an identity ranking with every score 0.0 when no
    reranker could run, and no real cross-encoder scores a whole candidate set
    at exactly zero — so all-zero means "not scored", and a relevance floor must
    not read it as "nothing relevant".
    """
    ranked = []
    for idx, score in ranking:
        hit = hits[idx]
        hit.score = round(float(score), 4)
        ranked.append(hit)
    return ranked, any(score > 0 for _, score in ranking)


def rerank_query(question: str, topic: str | None) -> str:
    """The question as the reranker reads it — see ``batch_search``."""
    if topic and settings.RERANK_TOPIC_PREFIX:
        return f"{topic}: {question}"
    return question


def rerank_document(result: SearchResult) -> str:
    """A candidate as the reranker reads it: its contextual note, then the chunk.

    The note is generated per chunk at ingestion, embedded, keyword-indexed and
    shown to the answering model, and was withheld from the one component that
    decides what the answering model sees. A chunk from the middle of an
    article carries no heading; the note says which article it is. The
    reranker cuts each document at 1,500 characters, so the note comes first.
    """
    note = " ".join((result.context_text or "").split())
    if note and settings.RERANK_WITH_CONTEXT:
        return f"{note}\n{result.text}"
    return result.text


def _with_each_querys_best(
    head: list[SearchResult],
    merged: list[SearchResult],
    per_query: Iterable[list[int]],
    per_query_best: int,
) -> list[SearchResult]:
    """``head``, plus each query's best ``per_query_best`` hits that it lacks.

    ``merged`` is cut to the reranker's candidate budget before reranking, and
    a subquery whose hits all fused below the cut would reach the reranker with
    nothing — so the part of the question it covers could never win a seat.
    """
    by_id = {r.chunk_id: r for r in merged}
    held = {r.chunk_id for r in head}
    out = list(head)
    for ids in per_query:
        for chunk_id in ids[:per_query_best]:
            if chunk_id not in held and chunk_id in by_id:
                held.add(chunk_id)
                out.append(by_id[chunk_id])
    return out


def _with_question(question: str, queries: list[str]) -> list[str]:
    """``queries`` plus the question, unless one of them already is it."""
    wanted = question.strip()
    if not wanted or any(q.strip().casefold() == wanted.casefold() for q in queries):
        return list(queries)
    return [*queries, wanted]


def _merge_hits(all_hits: list[list[SearchResult]]) -> list[SearchResult]:
    """Fuse the per-subquery hit lists into one ranked list.

    Scores **sum** across subqueries rather than taking the maximum. Each arm
    already carries an RRF score, and summing is what makes RRF worth using: a
    chunk that several independently-planned subqueries all retrieved outranks
    one that only a single subquery found. Taking the max threw that away —
    a chunk ranked first by one subquery and a chunk ranked first by all four
    scored identically, so agreement across subqueries (the strongest relevance
    signal the system has) had no effect on the ordering.

    The first-seen ``SearchResult`` for a chunk is kept and its score
    accumulated; the arms build fresh objects per subquery, so no caller's list
    is aliased.
    """
    fused: dict[int, SearchResult] = {}
    for hits in all_hits:
        for hit in hits:
            existing = fused.get(hit.chunk_id)
            if existing is None:
                fused[hit.chunk_id] = hit
            else:
                existing.score += hit.score
    merged = list(fused.values())
    merged.sort(key=lambda x: x.score, reverse=True)
    return merged
