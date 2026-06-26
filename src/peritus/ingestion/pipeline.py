"""Ingestion pipeline — chunk → contextualise → embed → store for a single ValidatedSource."""

import asyncio
import json

import asyncpg

from peritus.core.exceptions import IngestionError
from peritus.core.logging import get_logger
from peritus.infrastructure.embeddings import embed_batch
from peritus.ingestion.chunker import chunk_text
from peritus.ingestion.contextualizer import contextualize_chunks
from peritus.sources.domain import ValidatedSource

logger = get_logger(__name__)

_EMBED_BATCH_SIZE = 20
_MAX_EMBED_CHARS = 30_000  # ~8 000 tokens for text-embedding-3-large


async def ingest_source(
    source: ValidatedSource,
    expert_id: int,
    source_db_id: int,
    pool: asyncpg.Pool,
) -> list[int]:
    """Chunk, contextualise, embed and store a validated source. Returns inserted chunk IDs."""
    try:
        chunks = chunk_text(source.text, source.title)
        if not chunks:
            logger.warning("No chunks produced for source %r", source.title)
            return []

        contexts = await contextualize_chunks(chunks, source.title, source.text)
        for chunk, ctx in zip(chunks, contexts):
            chunk.chunk_meta["context"] = ctx

        embed_inputs = [
            (f"{ctx}\n\n{chunk.text}" if ctx else chunk.text)[:_MAX_EMBED_CHARS]
            for chunk, ctx in zip(chunks, contexts)
        ]
        embeddings = await _embed_in_batches(embed_inputs)

        chunk_ids = await _bulk_insert(
            pool, expert_id, source_db_id, chunks, contexts, embeddings
        )
        logger.info(
            "Ingested %d chunks for source %r (expert %d)",
            len(chunk_ids), source.title, expert_id,
        )
        return chunk_ids

    except Exception as exc:
        logger.exception("Ingestion failed for source %r", source.title)
        raise IngestionError(str(exc)) from exc


async def _embed_in_batches(texts: list[str]) -> list[list[float]]:
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[i: i + _EMBED_BATCH_SIZE]
        batch_embs = await embed_batch(batch)
        all_embeddings.extend(batch_embs)
        if i + _EMBED_BATCH_SIZE < len(texts):
            await asyncio.sleep(1)
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
        for chunk, ctx, emb in zip(chunks, contexts, embeddings):
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
