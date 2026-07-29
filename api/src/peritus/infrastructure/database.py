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

# The values pgvector accepts for hnsw.iterative_scan. "off" is excluded
# deliberately — it is the setting that truncates filtered results.
_ITERATIVE_SCAN_MODES = frozenset({"relaxed_order", "strict_order"})


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
    await _enable_iterative_scan(conn)


def iterative_scan_sql(*, local: bool) -> str:
    """``SET [LOCAL] hnsw.iterative_scan = …`` — a correctness setting, not tuning.

    Every semantic search filters by ``expert_id``, and an HNSW index cannot
    carry that filter: it walks the graph for the globally nearest vectors and
    Postgres discards other experts' rows afterwards. With the default
    ``hnsw.iterative_scan = off`` the scan stops after one pass of ``ef_search``
    candidates and quietly returns however few survived the filter.

    Measured on this corpus (pgvector 0.8, an expert owning 184 of 1850 chunks):
    ``off`` returned **40** rows where ``relaxed_order`` returned all **184**.
    Three quarters of that expert's corpus invisible to retrieval — no error, no
    warning, just a thinner answer and an audit trail that under-reports what was
    considered. For a product whose claim is that the evidence is inspectable,
    that is the worst failure mode available.

    ``relaxed_order`` over ``strict_order``: results are re-sorted by reciprocal
    rank and then cross-encoder reranked, so exact ordering out of the index buys
    nothing and relaxed scanning is markedly cheaper.

    **Scope matters.** ``local=True`` (inside an explicit transaction) is the only
    form that survives a transaction pooler — which is what ``DATABASE_URL``
    points at in this deployment. Session-level ``SET`` on a pooled connection is
    reset between transactions, and the durable ``ALTER DATABASE/ROLE … SET``
    form is refused to non-superusers on managed Postgres. The session-level call
    below is still made at connection init, because it is correct and free for
    deployments that connect directly.
    """
    mode = settings.HNSW_ITERATIVE_SCAN.strip().lower()
    if mode not in _ITERATIVE_SCAN_MODES:
        # A GUC name cannot be parameterised, so the value is interpolated —
        # validate against the allowlist rather than trusting the environment.
        logger.warning(
            "HNSW_ITERATIVE_SCAN=%r is not one of %s — using relaxed_order",
            settings.HNSW_ITERATIVE_SCAN, ", ".join(sorted(_ITERATIVE_SCAN_MODES)),
        )
        mode = "relaxed_order"
    return f"SET {'LOCAL ' if local else ''}hnsw.iterative_scan = {mode}"


async def _enable_iterative_scan(conn: asyncpg.Connection) -> None:
    """Best-effort session-level default. See :func:`iterative_scan_sql` on why
    the retrieval path cannot rely on this alone."""
    try:
        await conn.execute(iterative_scan_sql(local=False))
    except asyncpg.PostgresError as exc:
        logger.debug("hnsw.iterative_scan unavailable (pgvector < 0.8): %s", exc)


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
