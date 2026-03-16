"""Use case: create a Peritus Expert from a topic string."""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

from llama_index.core import Document
from python_slugify import slugify

from core.config import get_settings
from core.exceptions import ExpertAlreadyExistsError, IndexBuildError
from core.logger import get_logger
from domain.entities import Expert, ExpertStatus, SourceDocument
from infrastructure.graph.llama_graph_repo import build_graph_index, get_graph_stats
from infrastructure.llm.anthropic_adapter import complete
from infrastructure.sources.exa_discovery import discover_sources
from infrastructure.sources.firecrawl_ingest import enrich_sources
from infrastructure.sources.unstructured_parser import fetch_arxiv_papers

logger = get_logger(__name__)

_EXPERT_REGISTRY_FILE = Path("./storage/peritus/registry.json")


def _load_registry() -> dict[str, dict]:
    if _EXPERT_REGISTRY_FILE.exists():
        return json.loads(_EXPERT_REGISTRY_FILE.read_text())
    return {}


def _save_registry(registry: dict[str, dict]) -> None:
    _EXPERT_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _EXPERT_REGISTRY_FILE.write_text(json.dumps(registry, default=str, indent=2))


def get_expert(slug: str) -> Expert | None:
    """Load an Expert from the local registry by slug."""
    registry = _load_registry()
    data = registry.get(slug)
    if not data:
        return None
    return Expert.model_validate(data)


def list_experts() -> list[Expert]:
    """Return all registered experts."""
    registry = _load_registry()
    return [Expert.model_validate(v) for v in registry.values()]


def _save_expert(expert: Expert) -> None:
    registry = _load_registry()
    registry[expert.slug] = expert.model_dump()
    _save_registry(registry)


async def _generate_expert_description(topic: str, sources: list[SourceDocument]) -> str:
    """Use Claude to produce a short expert description based on ingested sources."""
    sample_titles = [s.title for s in sources[:8]]
    prompt = (
        f"You are writing a one-paragraph (3–5 sentence) description of an AI expert "
        f"specialised in '{topic}'. The expert's knowledge base was built from these sources:\n"
        + "\n".join(f"- {t}" for t in sample_titles)
        + "\n\nWrite the description in third person, focusing on depth and breadth of knowledge."
    )
    try:
        return await complete(
            system_prompt="You are a technical writer.",
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        logger.warning("description_generation_failed", error=str(exc))
        return f"A domain expert specialised in {topic} with a deep knowledge graph built from multiple authoritative sources."


async def create_expert_stream(topic: str) -> AsyncIterator[str]:
    """
    Stream progress events while building a Peritus Expert for a topic.

    Yields plain-text progress lines (newline-terminated) suitable for
    Server-Sent Events or streaming HTTP response.

    Args:
        topic: The domain topic string (e.g. "Quantum Computing").

    Yields:
        Progress lines, one per logical step.

    Raises:
        ExpertAlreadyExistsError: If an expert with this slug already exists.
        IndexBuildError: On graph build failure.
    """
    slug = slugify(topic)
    settings = get_settings()

    yield f"data: Starting research on '{topic}'...\n\n"

    existing = get_expert(slug)
    if existing and existing.status == ExpertStatus.READY:
        yield f"data: Expert '{slug}' already exists and is ready.\n\n"
        yield f"data: DONE slug={slug}\n\n"
        return

    # Register as building
    expert = Expert(
        slug=slug,
        topic=topic,
        persona_name=f"{topic} Expert",
        status=ExpertStatus.BUILDING,
        storage_path=str(Path(settings.storage_base_path) / slug),
        pinecone_namespace=f"peritus-{slug}",
    )
    _save_expert(expert)

    try:
        # --- Step 1: Discover sources via Exa ---
        yield f"data: [1/5] Discovering sources via Exa...\n\n"
        sources = await discover_sources(topic, max_results=settings.max_source_docs)
        yield f"data: [1/5] Found {len(sources)} web sources.\n\n"

        # --- Step 2: Enrich top sources with Firecrawl ---
        yield f"data: [2/5] Enriching sources with Firecrawl...\n\n"
        sources = await enrich_sources(sources, limit=5)
        yield f"data: [2/5] Enrichment complete.\n\n"

        # --- Step 3: Fetch ArXiv papers ---
        yield f"data: [3/5] Fetching ArXiv papers...\n\n"
        arxiv_docs = await fetch_arxiv_papers(topic, max_results=5)
        sources.extend(arxiv_docs)
        yield f"data: [3/5] Total sources: {len(sources)}.\n\n"

        # --- Step 4: Build PropertyGraphIndex ---
        yield f"data: [4/5] Building knowledge graph (this may take a few minutes)...\n\n"

        llama_docs = [
            Document(
                text=src.content,
                metadata={
                    "url": src.url,
                    "title": src.title,
                    "source_type": src.source_type,
                    **src.metadata,
                },
            )
            for src in sources
            if src.content.strip()
        ]

        index = await _async_build_index(slug, llama_docs)
        stats = get_graph_stats(index)
        yield f"data: [4/5] Graph built: {stats['node_count']} nodes, {stats['relation_count']} relations.\n\n"

        # --- Step 5: Generate expert description ---
        yield f"data: [5/5] Generating expert persona...\n\n"
        description = await _generate_expert_description(topic, sources)

        expert.description = description
        expert.mark_ready(
            source_count=len(sources),
            node_count=stats["node_count"],
            relation_count=stats["relation_count"],
        )
        _save_expert(expert)

        yield f"data: Expert '{slug}' is ready.\n\n"
        yield f"data: DONE slug={slug}\n\n"

    except Exception as exc:
        logger.error("create_expert_failed", slug=slug, error=str(exc))
        expert.mark_failed()
        _save_expert(expert)
        yield f"data: ERROR {exc}\n\n"
        raise IndexBuildError(f"Failed to build expert for '{topic}': {exc}") from exc


async def _async_build_index(slug: str, documents: list[Document]):
    """Run synchronous index build in thread pool to avoid blocking event loop."""
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, build_graph_index, slug, documents)
