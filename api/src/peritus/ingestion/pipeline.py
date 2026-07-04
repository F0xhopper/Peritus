"""Ingestion pipeline — chunk → contextualise → embed → store validated sources.

:func:`ingest_sources` handles a whole build stage at once: it chunks every
source first, contextualises all chunks in a single pass (one Message Batch at
half price when enabled), then embeds and stores per source. The single-source
:func:`ingest_source` remains as a convenience wrapper.
"""

import json
from collections.abc import Awaitable, Callable

import asyncpg

from peritus.core.exceptions import IngestionError
from peritus.core.logging import get_logger
from peritus.infrastructure.embeddings import embed_batch
from peritus.ingestion.chunker import TextChunk, chunk_text
from peritus.ingestion.contextualizer import ContextJob, contextualize_sources
from peritus.sources.domain import ValidatedSource

logger = get_logger(__name__)

_EMBED_BATCH_SIZE = 20
_MAX_EMBED_CHARS = 30_000  # ~8 000 tokens for text-embedding-3-large

# Called after each source is stored: (source, chunk_ids)
IngestedCallback = Callable[[ValidatedSource, list[int]], Awaitable[None]]


async def ingest_sources(
    sources: list[ValidatedSource],
    expert_id: int,
    source_db_ids: list[int],
    pool: asyncpg.Pool,
    on_ingested: IngestedCallback | None = None,
) -> list[tuple[list[int], list[TextChunk]]]:
    """Chunk, contextualise, embed and store every validated source.

    Returns one ``(inserted_chunk_ids, text_chunks)`` pair per source, in
    order. A source that fails at any step yields ``([], [])`` — ingestion of
    the other sources continues.
    """
    # 1. Chunk everything up front (pure, cheap).
    per_source_chunks: list[list[TextChunk]] = []
    for source in sources:
        try:
            chunks = chunk_text(source.text, source.title)
        except Exception as exc:
            logger.warning("Chunking failed for %r: %s", source.title, exc)
            chunks = []
        if not chunks:
            logger.warning("No chunks produced for source %r", source.title)
        per_source_chunks.append(chunks)

    # 2. Contextualise all sources in one pass — a single Message Batch when
    #    enabled, so the whole stage is billed at 50%.
    jobs = [
        ContextJob(chunks=chunks, source_title=s.title, source_text=s.text)
        for s, chunks in zip(sources, per_source_chunks, strict=True)
        if chunks
    ]
    job_contexts = iter(await contextualize_sources(jobs))

    # 3. Embed + store per source.
    results: list[tuple[list[int], list[TextChunk]]] = []
    for source, src_db_id, chunks in zip(
        sources, source_db_ids, per_source_chunks, strict=True,
    ):
        if not chunks:
            results.append(([], []))
            if on_ingested:
                await on_ingested(source, [])
            continue
        contexts = next(job_contexts)
        try:
            chunk_ids = await _embed_and_store(
                pool, expert_id, src_db_id, chunks, contexts,
            )
            logger.info(
                "Ingested %d chunks for source %r (expert %d)",
                len(chunk_ids), source.title, expert_id,
            )
            results.append((chunk_ids, chunks))
            if on_ingested:
                await on_ingested(source, chunk_ids)
        except Exception:
            logger.exception("Ingestion failed for source %r", source.title)
            results.append(([], []))
            if on_ingested:
                await on_ingested(source, [])
    return results


async def ingest_source(
    source: ValidatedSource,
    expert_id: int,
    source_db_id: int,
    pool: asyncpg.Pool,
) -> tuple[list[int], list[TextChunk]]:
    """Chunk, contextualise, embed and store a single validated source.

    Unlike :func:`ingest_sources`, failures raise :class:`IngestionError`.
    """
    try:
        chunks = chunk_text(source.text, source.title)
        if not chunks:
            logger.warning("No chunks produced for source %r", source.title)
            return [], []

        [contexts] = await contextualize_sources(
            [ContextJob(chunks=chunks, source_title=source.title, source_text=source.text)]
        )
        chunk_ids = await _embed_and_store(pool, expert_id, source_db_id, chunks, contexts)
        logger.info(
            "Ingested %d chunks for source %r (expert %d)",
            len(chunk_ids), source.title, expert_id,
        )
        return chunk_ids, chunks

    except Exception as exc:
        logger.exception("Ingestion failed for source %r", source.title)
        raise IngestionError(str(exc)) from exc


async def _embed_and_store(
    pool: asyncpg.Pool,
    expert_id: int,
    source_db_id: int,
    chunks: list[TextChunk],
    contexts: list[str],
) -> list[int]:
    for chunk, ctx in zip(chunks, contexts, strict=True):
        chunk.chunk_meta["context"] = ctx

    embed_inputs = [
        (f"{ctx}\n\n{chunk.text}" if ctx else chunk.text)[:_MAX_EMBED_CHARS]
        for chunk, ctx in zip(chunks, contexts, strict=True)
    ]
    embeddings = await _embed_in_batches(embed_inputs)

    return await _bulk_insert(
        pool, expert_id, source_db_id, chunks, contexts, embeddings
    )


async def _embed_in_batches(texts: list[str]) -> list[list[float]]:
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[i: i + _EMBED_BATCH_SIZE]
        batch_embs = await embed_batch(batch)
        all_embeddings.extend(batch_embs)
    return all_embeddings


async def _bulk_insert(
    pool: asyncpg.Pool,
    expert_id: int,
    source_id: int,
    chunks,
    contexts: list[str],
    embeddings: list[list[float]],
) -> list[int]:
    from pgvector.asyncpg import register_vector  # type: ignore

    ids: list[int] = []
    async with pool.acquire() as conn:
        await register_vector(conn)
        for chunk, ctx, emb in zip(chunks, contexts, embeddings, strict=True):
            row = await conn.fetchrow(
                """
                INSERT INTO source_chunks
                    (expert_id, source_id, sequence_n, text, context_text, embedding, chunk_meta)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                RETURNING id
                """,
                expert_id,
                source_id,
                chunk.sequence_n,
                chunk.text,
                ctx or None,
                emb,
                json.dumps(chunk.chunk_meta),
            )
            ids.append(row["id"])
    return ids
