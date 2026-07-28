"""The process-wide asyncpg pool, and the pgvector facts that depend on it.

**Codecs are registered once per connection, not once per query.**
``pgvector.asyncpg.register_vector`` issues up to three ``set_type_codec`` calls,
each of which is a type-introspection round trip. Calling it inside a request
handler put three extra round trips on every hybrid search — and a chat turn
runs four to six searches in parallel. It belongs in the pool's ``init``
callback, which runs once when a physical connection is opened.

**Timeouts are set, not defaulted.** ``command_timeout`` bounds how long one
statement may pin a connection, and callers acquire with a deadline, so an
exhausted pool degrades to fast failures instead of an unbounded queue.

**Vector capability is probed once at startup.** Whether this server can index
3072-dimension embeddings depends on the pgvector version (``halfvec``, and with
it HNSW above 2000 dimensions, arrived in 0.7.0). The retrieval layer has to
know, so the probe happens here — at pool init, against a connection we already
hold — and is read back through :func:`halfvec_supported`.
"""

import asyncpg

from peritus.core.config import settings
from peritus.core.logging import get_logger

logger = get_logger(__name__)

_pool: asyncpg.Pool | None = None
_halfvec_supported: bool = False


async def init_pool() -> None:
    global _pool
    if _pool is not None:
        return
    ssl = "require" if settings.DATABASE_SSL else None
    _pool = await asyncpg.create_pool(
        settings.DATABASE_URL,
        min_size=settings.DB_POOL_MIN_SIZE,
        max_size=settings.DB_POOL_MAX_SIZE,
        ssl=ssl,
        init=_init_connection,
        # Supabase's transaction pooler cannot see server-side prepared
        # statements across checkouts, so the cache has to stay off.
        statement_cache_size=0,
        command_timeout=settings.DB_COMMAND_TIMEOUT,
    )
    await _probe_vector_capabilities(_pool)


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # Install the vector/halfvec/sparsevec codecs for the lifetime of this
    # connection. Every query that passes or reads an embedding depends on it.
    from pgvector.asyncpg import register_vector  # type: ignore

    await register_vector(conn)


async def _probe_vector_capabilities(pool: asyncpg.Pool) -> None:
    """Record whether this server has the ``halfvec`` type (pgvector ≥ 0.7)."""
    global _halfvec_supported
    try:
        async with pool.acquire() as conn:
            _halfvec_supported = bool(
                await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'halfvec')")
            )
    except Exception as exc:
        _halfvec_supported = False
        logger.warning("Could not probe pgvector capabilities: %s", exc)

    if _halfvec_supported:
        logger.info("pgvector halfvec available — semantic search uses the HNSW-indexable path")
    else:
        logger.warning(
            "pgvector predates halfvec (0.7.0) — embeddings of %d dimensions cannot be "
            "HNSW-indexed, so every semantic search is an exact scan. Upgrade pgvector "
            "and apply migration 019 to fix retrieval latency.",
            settings.EMBED_DIM,
        )


def halfvec_supported() -> bool:
    """Whether ``embedding::halfvec(n)`` is available for indexed distance ordering."""
    return _halfvec_supported


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
    # Drop the reference too: leaving a closed pool behind makes get_pool()
    # hand out something that fails at query time instead of saying it is gone,
    # and it breaks re-entering the lifespan (tests, --reload).
    _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialised.")
    return _pool
