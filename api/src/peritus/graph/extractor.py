"""Claude graph extractor — reads batches of chunks and extracts concept nodes + typed edges."""

import asyncio
import json
from collections.abc import Callable, Coroutine
from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.ingestion.chunker import TextChunk

logger = get_logger(__name__)

_TOOL = {
    "name": "extract_graph",
    "description": "Extract concept nodes and typed relationships from source chunks.",
    "input_schema": {
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "Short canonical name."},
                        "node_type": {"type": "string", "enum": ["concept", "claim"]},
                        "description": {"type": "string"},
                        "difficulty": {"type": "integer", "description": "1–5"},
                        "content_type": {
                            "type": "string",
                            "enum": ["definition", "theorem", "example", "argument", "counterargument"],
                        },
                        "confidence": {
                            "type": ["number", "null"],
                            "description": "0.0–1.0, for claims only.",
                        },
                        "chunk_indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Indices into the provided chunk list (0-based).",
                        },
                    },
                    "required": ["label", "node_type", "description", "chunk_indices"],
                },
            },
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_label": {"type": "string"},
                        "to_label": {"type": "string"},
                        "edge_type": {
                            "type": "string",
                            "enum": ["supports", "contradicts", "builds_on", "defines", "exemplifies", "cites"],
                        },
                        "weight": {"type": "number", "description": "0.0–1.0 strength."},
                    },
                    "required": ["from_label", "to_label", "edge_type"],
                },
            },
        },
        "required": ["nodes", "edges"],
    },
}

_SYSTEM = (
    "You are a knowledge graph extractor. Given text chunks from a source, identify the key "
    "concepts and claims, then describe the typed relationships between them. "
    "Be specific and precise — extract only nodes clearly supported by the text. "
    "Use canonical, concise labels (2–5 words). Prefer fewer, high-quality nodes over many vague ones."
)


BatchCallback = Callable[[list[str], int], Coroutine[Any, Any, None]]


async def extract_graph_from_chunks(
    topic: str,
    chunks: list[TextChunk],
    chunk_db_ids: list[int],
    batch_size: int | None = None,
    on_batch: BatchCallback | None = None,
) -> list[dict]:
    """Extract graph data from chunks in batches. Returns raw extraction dicts."""
    size = batch_size or settings.GRAPH_BATCH_SIZE
    client = get_anthropic_client()
    sem = asyncio.Semaphore(3)

    batches = [
        (chunks[i: i + size], chunk_db_ids[i: i + size])
        for i in range(0, len(chunks), size)
    ]

    results = await asyncio.gather(
        *[_extract_batch(client, topic, batch_chunks, batch_ids, sem, on_batch)
          for batch_chunks, batch_ids in batches],
        return_exceptions=True,
    )

    extractions = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("Graph extraction failed for batch %d: %s", i, result)
        else:
            extractions.append(result)
    return extractions


async def _extract_batch(
    client,
    topic: str,
    chunks: list[TextChunk],
    chunk_db_ids: list[int],
    sem: asyncio.Semaphore,
    on_batch: BatchCallback | None = None,
) -> dict:
    chunk_block = "\n\n".join(
        f"[{i}] {c.text[:600]}" for i, c in enumerate(chunks)
    )
    async with sem:
        resp = await client.messages.create(
            model=settings.GRAPH_MODEL,
            max_tokens=2048,
            system=_SYSTEM,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "extract_graph"},
            messages=[{
                "role": "user",
                "content": (
                    f"Topic: {topic}\n\n"
                    f"Chunks ({len(chunks)} total):\n\n{chunk_block}"
                ),
            }],
        )
    block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
    data = dict(block.input)
    for node in data.get("nodes", []):
        node["chunk_db_ids"] = [
            chunk_db_ids[idx]
            for idx in node.get("chunk_indices", [])
            if idx < len(chunk_db_ids)
        ]
    if on_batch:
        labels = [n["label"] for n in data.get("nodes", []) if n.get("label")]
        await on_batch(labels, len(data.get("edges", [])))
    return data
