from __future__ import annotations

from pinecone import Pinecone, ServerlessSpec
from llama_index.vector_stores.pinecone import PineconeVectorStore

from core.config import get_settings
from core.logger import get_logger

logger = get_logger(__name__)

EMBEDDING_DIMENSION = 1024


def _get_pinecone_client() -> Pinecone:
    settings = get_settings()
    return Pinecone(api_key=settings.pinecone_api_key)


def ensure_index_exists() -> None:
    settings = get_settings()
    pc = _get_pinecone_client()
    existing = [idx.name for idx in pc.list_indexes()]
    if settings.pinecone_index_name not in existing:
        logger.info("creating_pinecone_index", index=settings.pinecone_index_name)
        pc.create_index(
            name=settings.pinecone_index_name,
            dimension=EMBEDDING_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region=settings.pinecone_environment),
        )
    else:
        logger.info("pinecone_index_exists", index=settings.pinecone_index_name)


def get_vector_store(namespace: str) -> PineconeVectorStore:
    ensure_index_exists()
    settings = get_settings()
    pc = _get_pinecone_client()
    pinecone_index = pc.Index(settings.pinecone_index_name)
    logger.info("pinecone_vector_store_ready", namespace=namespace)
    return PineconeVectorStore(
        pinecone_index=pinecone_index,
        namespace=namespace,
    )
