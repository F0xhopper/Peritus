"""OpenAI embeddings, with the interactive and bulk paths kept apart.

**Two semaphores, deliberately.** A chat turn embeds four to six subqueries and
a user is watching the spinner; a build embeds hundreds of chunk batches and
nobody is. When the API runs a build worker in-process
(``RUN_WORKER_IN_PROCESS``, which is what ``just dev-solo`` and any single-node
deployment does) a single shared semaphore lets the build's backlog queue ahead
of every interactive request — chat latency then tracks the build's remaining
work, unbounded and invisible in any per-request timing.

:func:`embed_query` and :func:`embed_batch` therefore draw on separate budgets.
Nothing else changes: both still bound how many requests are in flight so a
large corpus cannot open hundreds of concurrent connections to OpenAI.
"""

import asyncio

from openai import AsyncOpenAI

from peritus.core.config import settings
from peritus.core.exceptions import EmbeddingError
from peritus.core.logging import get_logger

logger = get_logger(__name__)

_client: AsyncOpenAI | None = None

# Created lazily so the configured sizes are read at first use, and so importing
# this module never binds a semaphore to whichever event loop happened to exist.
_query_sem: asyncio.Semaphore | None = None
_batch_sem: asyncio.Semaphore | None = None


def _get_query_sem() -> asyncio.Semaphore:
    global _query_sem
    if _query_sem is None:
        _query_sem = asyncio.Semaphore(max(1, settings.EMBED_QUERY_CONCURRENCY))
    return _query_sem


def _get_batch_sem() -> asyncio.Semaphore:
    global _batch_sem
    if _batch_sem is None:
        _batch_sem = asyncio.Semaphore(max(1, settings.EMBED_BATCH_CONCURRENCY))
    return _batch_sem


def get_embeddings_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            # The SDK's default timeout is minutes long. A query embedding sits
            # in front of a user waiting on a chat answer, so bound it and let
            # the SDK retry transient failures rather than hanging on one.
            timeout=settings.OPENAI_TIMEOUT,
            max_retries=settings.OPENAI_MAX_RETRIES,
        )
    return _client


async def embed_query(text: str) -> list[float]:
    """Embed one text on the interactive budget. Use this on the request path."""
    client = get_embeddings_client()
    async with _get_query_sem():
        try:
            resp = await client.embeddings.create(
                model=settings.EMBED_MODEL,
                input=text.replace("\n", " "),
            )
            return resp.data[0].embedding
        except Exception as exc:
            logger.error("Embedding failed: %s", exc)
            raise EmbeddingError(str(exc)) from exc


# Historical name for the single-text call. Kept so build-side callers and the
# CLI keep working; it draws on the same interactive budget, which is correct —
# the bulk path is embed_batch, and that is where a build's volume actually is.
embed_text = embed_query


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed many texts in one request, on the bulk budget."""
    client = get_embeddings_client()
    cleaned = [t.replace("\n", " ") for t in texts]
    async with _get_batch_sem():
        try:
            resp = await client.embeddings.create(
                model=settings.EMBED_MODEL,
                input=cleaned,
            )
            resp.data.sort(key=lambda x: x.index)
            return [item.embedding for item in resp.data]
        except Exception as exc:
            logger.error("Batch embedding failed: %s", exc)
            raise EmbeddingError(str(exc)) from exc


# Safe request size for text-embedding-3-large: keeps each call well under the
# API's per-request input and token ceilings so a large corpus doesn't blow up
# a single embed call.
EMBED_BATCH_SIZE = 20


async def embed_in_batches(
    texts: list[str], batch_size: int = EMBED_BATCH_SIZE
) -> list[list[float]]:
    """Embed an arbitrarily long list of texts in fixed-size sub-batches.

    :func:`embed_batch` sends everything in one request; use this whenever the
    input count is unbounded (chunks of a source, all graph nodes) so a big set
    can't overflow the embedding API's per-request limit.
    """
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        all_embeddings.extend(await embed_batch(texts[i: i + batch_size]))
    return all_embeddings
