import asyncio

from openai import AsyncOpenAI

from peritus.core.config import settings
from peritus.core.exceptions import EmbeddingError
from peritus.core.logging import get_logger

logger = get_logger(__name__)

_client: AsyncOpenAI | None = None
_embed_sem = asyncio.Semaphore(2)


def get_embeddings_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def embed_text(text: str) -> list[float]:
    client = get_embeddings_client()
    async with _embed_sem:
        try:
            resp = await client.embeddings.create(
                model=settings.EMBED_MODEL,
                input=text.replace("\n", " "),
            )
            return resp.data[0].embedding
        except Exception as exc:
            logger.error("Embedding failed: %s", exc)
            raise EmbeddingError(str(exc)) from exc


async def embed_batch(texts: list[str]) -> list[list[float]]:
    client = get_embeddings_client()
    cleaned = [t.replace("\n", " ") for t in texts]
    async with _embed_sem:
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
