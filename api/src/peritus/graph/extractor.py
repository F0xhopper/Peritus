"""Claude graph extractor — reads batches of chunks and extracts concept nodes + typed edges."""

from collections.abc import Callable, Coroutine
from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_batch import gather_claude_calls
from peritus.ingestion.chunker import TextChunk

logger = get_logger(__name__)

_TOOL: dict[str, Any] = {
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


def attach_chunk_db_ids(data: dict, chunk_db_ids: list[int]) -> dict:
    """Map model-reported chunk indices to database ids, dropping out-of-range ones."""
    for node in data.get("nodes", []):
        node["chunk_db_ids"] = [
            chunk_db_ids[idx]
            for idx in node.get("chunk_indices", [])
            if isinstance(idx, int) and 0 <= idx < len(chunk_db_ids)
        ]
    return data


async def extract_graph_from_chunks(
    topic: str,
    chunks: list[TextChunk],
    chunk_db_ids: list[int],
    batch_size: int | None = None,
    on_batch: BatchCallback | None = None,
) -> list[dict]:
    """Extract graph data from chunks in batches. Returns raw extraction dicts.

    Calls run through the Message Batches API (half price) when enabled, else
    as concurrent live calls.
    """
    size = batch_size or settings.GRAPH_BATCH_SIZE

    batches = [
        (chunks[i: i + size], chunk_db_ids[i: i + size])
        for i in range(0, len(chunks), size)
    ]

    responses = await gather_claude_calls(
        [_extract_params(topic, batch_chunks) for batch_chunks, _ in batches],
        live_concurrency=3,
        description="graph-extract",
    )

    extractions = []
    for i, ((_, batch_ids), resp) in enumerate(zip(batches, responses, strict=True)):
        if resp is None:
            logger.warning("Graph extraction failed for batch %d", i)
            continue
        try:
            data = _parse_extract_response(resp, batch_ids)
        except Exception as exc:
            logger.warning("Graph extraction failed for batch %d: %s", i, exc)
            continue
        if on_batch:
            labels = [n["label"] for n in data.get("nodes", []) if n.get("label")]
            await on_batch(labels, len(data.get("edges", [])))
        extractions.append(data)
    return extractions


def _extract_params(topic: str, chunks: list[TextChunk]) -> dict[str, Any]:
    """Request params for one extraction batch (consumed by gather_claude_calls)."""
    chunk_block = "\n\n".join(
        f"[{i}] {c.text}" for i, c in enumerate(chunks)
    )
    return {
        "model": settings.GRAPH_MODEL,
        "max_tokens": 4096,
        "system": _SYSTEM,
        "tools": [_TOOL],
        "tool_choice": {"type": "tool", "name": "extract_graph"},
        "messages": [{
            "role": "user",
            "content": (
                f"Topic: {topic}\n\n"
                f"Chunks ({len(chunks)} total):\n\n{chunk_block}"
            ),
        }],
    }


def _parse_extract_response(resp: Any, chunk_db_ids: list[int]) -> dict:
    if resp.stop_reason == "max_tokens":
        logger.warning(
            "Graph extraction batch hit max_tokens — output truncated, some nodes/edges lost"
        )
    block = next((b for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
    if block is None:
        raise ValueError("Graph extraction response contained no tool_use block")
    return attach_chunk_db_ids(dict(block.input), chunk_db_ids)
