"""Liveness and readiness.

The split is the one an orchestrator expects: ``/health`` says the process is
alive and should not be restarted, ``/ready`` says it can serve traffic and
should stay in the load-balancer pool.

``/ready`` is bounded. ``pool.acquire()`` waits indefinitely when every
connection is checked out, so an unbounded probe *hangs* on an overloaded
instance rather than failing it — and a hanging probe is generally read as
"still checking", so the balancer keeps sending it traffic it cannot serve.
A deadline turns that into a 503, which is the whole point of the endpoint.
"""

import asyncio

from fastapi import APIRouter, HTTPException

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.database import get_pool, halfvec_supported

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Liveness: the process is up. Deliberately touches nothing external."""
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    """Readiness: a database connection is obtainable within the acquire deadline."""
    try:
        pool = get_pool()
        async with asyncio.timeout(settings.DB_ACQUIRE_TIMEOUT):
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
    except TimeoutError as exc:
        logger.warning("Readiness probe timed out acquiring a database connection")
        raise HTTPException(
            status_code=503, detail="Database connection pool exhausted"
        ) from exc
    except Exception as exc:
        logger.warning("Readiness probe failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database not ready") from exc
    return {
        "db": True,
        "status": "ready",
        # Surfaces the one capability that silently changes retrieval cost: with
        # no halfvec support there is no vector index and every semantic search
        # is an exact scan. Visible on a probe rather than only in a startup log.
        "vector_index": "halfvec" if halfvec_supported() else "none",
    }
