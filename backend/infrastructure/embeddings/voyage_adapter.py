"""VoyageAI embedding adapter for LlamaIndex."""

from __future__ import annotations

from llama_index.embeddings.voyageai import VoyageEmbedding

from core.config import get_settings
from core.logger import get_logger

logger = get_logger(__name__)


def get_voyage_embedding() -> VoyageEmbedding:
    """
    Return a LlamaIndex-compatible VoyageAI embedding model.

    Uses the voyage-3 model which provides 1024-dimensional embeddings
    optimised for retrieval tasks.
    """
    settings = get_settings()
    logger.info("initialising_voyage_embeddings", model=settings.voyage_model)
    return VoyageEmbedding(
        model_name=settings.voyage_model,
        voyage_api_key=settings.voyage_api_key,
        embed_batch_size=32,
    )
