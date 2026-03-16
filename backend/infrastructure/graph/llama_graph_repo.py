"""LlamaIndex PropertyGraphIndex repository."""

from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncIterator

from llama_index.core import (
    Document,
    PropertyGraphIndex,
    StorageContext,
    load_index_from_storage,
)
from llama_index.core.extractors import (
    EntityExtractor,
)
from llama_index.core.graph_stores.types import GraphStore
from llama_index.core.indices.property_graph import (
    ImplicitPathExtractor,
    SimpleLLMPathExtractor,
)
from llama_index.core.settings import Settings as LlamaSettings

from core.config import get_settings
from core.logger import get_logger
from infrastructure.embeddings.voyage_adapter import get_voyage_embedding
from infrastructure.llm.anthropic_adapter import get_llama_llm
from infrastructure.vector.pinecone_repo import get_vector_store

logger = get_logger(__name__)


def _configure_llama_settings() -> None:
    """Set global LlamaIndex LLM + embedding."""
    LlamaSettings.llm = get_llama_llm()
    LlamaSettings.embed_model = get_voyage_embedding()
    LlamaSettings.chunk_size = 512
    LlamaSettings.chunk_overlap = 64


def _storage_path(slug: str) -> Path:
    settings = get_settings()
    path = Path(settings.storage_base_path) / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_graph_index(
    slug: str,
    documents: list[Document],
) -> PropertyGraphIndex:
    """
    Build a PropertyGraphIndex from the given documents.

    Uses three extractors:
      - SimpleLLMPathExtractor (entity-relation triples via LLM)
      - ImplicitPathExtractor (keyword co-occurrence paths)
      - EntityExtractor (named entity recognition)

    Persists the graph to disk and upserts vectors to Pinecone.

    Args:
        slug: URL-safe expert identifier.
        documents: Ingested LlamaIndex Document objects.

    Returns:
        The built PropertyGraphIndex.
    """
    _configure_llama_settings()
    settings = get_settings()
    storage_path = _storage_path(slug)
    namespace = f"peritus-{slug}"

    logger.info("building_graph_index", slug=slug, doc_count=len(documents))

    vector_store = get_vector_store(namespace)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    kg_extractors = [
        SimpleLLMPathExtractor(
            llm=get_llama_llm(),
            max_paths_per_chunk=settings.max_paths_per_chunk,
        ),
        ImplicitPathExtractor(),
    ]

    index = PropertyGraphIndex.from_documents(
        documents,
        kg_extractors=kg_extractors,
        storage_context=storage_context,
        show_progress=True,
    )

    # Persist locally
    index.storage_context.persist(persist_dir=str(storage_path))
    logger.info("graph_index_persisted", path=str(storage_path))

    return index


def load_graph_index(slug: str) -> PropertyGraphIndex:
    """
    Load a previously-built PropertyGraphIndex from disk.

    Args:
        slug: Expert identifier.

    Returns:
        Loaded PropertyGraphIndex.

    Raises:
        FileNotFoundError: If storage directory does not exist.
    """
    _configure_llama_settings()
    storage_path = _storage_path(slug)
    namespace = f"peritus-{slug}"

    if not (storage_path / "docstore.json").exists():
        raise FileNotFoundError(
            f"No persisted index found at {storage_path}. "
            "Build the expert first."
        )

    logger.info("loading_graph_index", slug=slug)
    vector_store = get_vector_store(namespace)
    storage_context = StorageContext.from_defaults(
        persist_dir=str(storage_path),
        vector_store=vector_store,
    )
    index = load_index_from_storage(storage_context)
    return index


def get_graph_stats(index: PropertyGraphIndex) -> dict:
    """
    Extract node/relation counts from the graph store.

    Returns:
        Dict with node_count and relation_count.
    """
    try:
        graph_store = index.property_graph_store
        nodes = list(graph_store.get_all_nodes())
        relations = list(graph_store.get_all_relations())
        return {"node_count": len(nodes), "relation_count": len(relations)}
    except Exception as exc:
        logger.warning("graph_stats_unavailable", error=str(exc))
        return {"node_count": 0, "relation_count": 0}
