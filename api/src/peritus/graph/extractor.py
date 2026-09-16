"""Claude graph extractor — reads batches of chunks and extracts nodes + index edges.

One batch is ten consecutive chunks, which almost always sit inside a single
source. That is why this pass no longer asserts relationships *between claims*:
whether two claims support, contradict or qualify each other is a question about
two sources, and a window that can only see one of them was answering it by
guessing. Extraction produces claims, the concepts they are about, and the
hierarchy between concepts; :mod:`peritus.graph.reconciler` runs afterwards,
once per concept, with the claims from every source in front of it.
"""

from collections.abc import Callable, Coroutine
from typing import Any

from anthropic.types import Message

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_batch import gather_claude_calls
from peritus.infrastructure.anthropic_client import tool_input
from peritus.ingestion.chunker import TextChunk

logger = get_logger(__name__)

_TOOL: dict[str, Any] = {
    "name": "extract_graph",
    "description": (
        "Extract the claims a source makes, the concepts they are about, and the "
        "hierarchy between those concepts."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": (
                                "For a concept, a short canonical name (2–5 words). For a "
                                "claim, the proposition itself, stated as one short sentence "
                                "that can be true or false."
                            ),
                        },
                        "node_type": {"type": "string", "enum": ["concept", "claim"]},
                        "description": {"type": "string"},
                        "difficulty": {"type": "integer", "description": "1–5"},
                        "content_type": {
                            "type": "string",
                            "enum": [
                                "definition",
                                "theorem",
                                "example",
                                "argument",
                                "counterargument",
                            ],
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
                            "enum": ["about", "part_of"],
                            "description": (
                                "about: from a claim to a concept the claim is about. "
                                "part_of: from a narrower concept to the broader concept "
                                "that contains it."
                            ),
                        },
                    },
                    "required": ["from_label", "to_label", "edge_type"],
                },
            },
        },
        "required": ["nodes", "edges"],
    },
}

_SYSTEM = (
    "You are a knowledge graph extractor. Given text chunks from a source, extract two "
    "kinds of node.\n\n"
    "A CLAIM is a proposition the source asserts — something that could be true or false, "
    "and that another source could disagree with. Label it with the proposition itself, in "
    "one short sentence ('Varroa suppresses host immune response'), never as a topic.\n\n"
    "A CONCEPT is a thing claims are about: a term, an entity, a mechanism. Label it with a "
    "canonical noun phrase of 2–5 words.\n\n"
    "Then connect them. Every claim gets at least one `about` edge to a concept it concerns. "
    "Use `part_of` only where one concept is genuinely contained by a broader one.\n\n"
    "Do not assert whether claims agree or disagree — you are reading one source and cannot "
    "see the others. Extract only what this text supports, and prefer fewer, sharper nodes "
    "over many vague ones."
)


BatchCallback = Callable[[list[str], int], Coroutine[Any, Any, None]]


#: Concepts an orphaned claim is attached to, at most — the ones sharing the most
#: chunks with it. Enough to put the claim in its concept's reconciliation group
#: without turning every chunk's concept list into a claim's subject.
_MAX_INFERRED_ABOUT = 3


def attach_orphan_claims(data: dict) -> int:
    """Give every claim an ``about`` edge, from the chunks it was extracted from.

    The prompt says every claim gets one and nothing enforced it: 34% of claims
    in production had none, which makes them invisible to reconciliation — it
    groups claims by the concept they are about. A claim whose ``about`` edges
    all name something this batch did not emit as a concept (the insert would
    reject them as unresolved) is attached to the batch's concepts that share a
    chunk with it. Deterministic, no model call. Mutates ``data``; returns the
    number of edges added.
    """
    nodes = data.get("nodes", [])
    concepts = [
        n
        for n in nodes
        if str(n.get("node_type", "")).strip().lower() == "concept" and n.get("label")
    ]
    concept_keys = {c["label"].lower().strip() for c in concepts}
    about_from: set[str] = {
        e["from_label"].lower().strip()
        for e in data.get("edges", [])
        if str(e.get("edge_type", "")).strip().lower() == "about"
        and str(e.get("to_label", "")).lower().strip() in concept_keys
    }

    added = 0
    for claim in nodes:
        if str(claim.get("node_type", "")).strip().lower() != "claim" or not claim.get("label"):
            continue
        if claim["label"].lower().strip() in about_from:
            continue
        chunks = {i for i in claim.get("chunk_indices", []) if isinstance(i, int)}
        if not chunks:
            continue
        overlap = sorted(
            (
                (len(chunks & {i for i in c.get("chunk_indices", []) if isinstance(i, int)}), c)
                for c in concepts
            ),
            key=lambda pair: -pair[0],
        )
        for shared, concept in overlap[:_MAX_INFERRED_ABOUT]:
            if shared == 0:
                break
            data.setdefault("edges", []).append(
                {
                    "from_label": claim["label"],
                    "to_label": concept["label"],
                    "edge_type": "about",
                }
            )
            added += 1
    return added


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
    as concurrent live calls. ``on_batch`` fires per batch as its result lands —
    on the live path that is while the stage is still running, so progress
    (e.g. the TUI's per-batch ticker) streams instead of arriving in one lump
    at the end. Batch-API results all land together, so there it still lumps.
    """
    size = batch_size or settings.GRAPH_BATCH_SIZE

    batches = [
        (chunks[i : i + size], chunk_db_ids[i : i + size]) for i in range(0, len(chunks), size)
    ]

    parsed: dict[int, dict] = {}

    async def _on_result(i: int, resp: Message | None) -> None:
        if resp is None:
            logger.warning("Graph extraction failed for batch %d", i)
            return
        try:
            data = _parse_extract_response(resp, batches[i][1])
        except Exception as exc:
            logger.warning("Graph extraction failed for batch %d: %s", i, exc)
            return
        parsed[i] = data
        if on_batch:
            labels = [n["label"] for n in data.get("nodes", []) if n.get("label")]
            await on_batch(labels, len(data.get("edges", [])))

    await gather_claude_calls(
        [_extract_params(topic, batch_chunks) for batch_chunks, _ in batches],
        live_concurrency=3,
        description="graph-extract",
        on_result=_on_result,
    )

    return [parsed[i] for i in sorted(parsed)]


def _extract_params(topic: str, chunks: list[TextChunk]) -> dict[str, Any]:
    """Request params for one extraction batch (consumed by gather_claude_calls)."""
    chunk_block = "\n\n".join(f"[{i}] {c.text}" for i, c in enumerate(chunks))
    return {
        "model": settings.GRAPH_MODEL,
        "max_tokens": 8192,
        "system": _SYSTEM,
        "tools": [_TOOL],
        "tool_choice": {"type": "tool", "name": "extract_graph"},
        "messages": [
            {
                "role": "user",
                "content": (f"Topic: {topic}\n\nChunks ({len(chunks)} total):\n\n{chunk_block}"),
            }
        ],
    }


_REQUIRED_NODE_KEYS = ("label", "node_type", "description")
_REQUIRED_EDGE_KEYS = ("from_label", "to_label", "edge_type")


def _complete(entries: Any, required: tuple[str, ...] | list[str], kind: str) -> list[dict]:
    """Entries that are objects and carry every required key.

    A truncated tool call arrives missing its trailing fields; a malformed one
    arrives as something that is not an object at all. Both are unusable and
    neither should cost the batch, so both are dropped with a count.
    """
    if isinstance(entries, str):
        # The model sometimes serialises a long array into a JSON string inside
        # the tool call. Four of 144 batches on a live rebuild arrived that way
        # and were discarded whole — every node in ten chunks, for a formatting
        # choice. Decoded here, and repaired when the string was cut off.
        decoded = decode_json_list(entries)
        if decoded is None:
            logger.warning("Graph extraction returned %s as an undecodable string", kind)
            return []
        entries = decoded
    if not isinstance(entries, list):
        logger.warning(
            "Graph extraction returned %s as %s, not a list", kind, type(entries).__name__
        )
        return []
    valid = [e for e in entries if isinstance(e, dict) and all(e.get(k) for k in required)]
    if len(valid) != len(entries):
        logger.warning(
            "Dropped %d unusable %s(s) — truncated JSON or a non-object entry",
            len(entries) - len(valid),
            kind,
        )
    return valid


def decode_json_list(text: str) -> list | None:
    """A JSON array from a string, recovering the complete objects of a truncated one."""
    import json

    text = text.strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, list) else None
    except ValueError:
        pass
    if not text.startswith("["):
        return None
    # Truncated: keep everything up to the last complete top-level object.
    decoder = json.JSONDecoder()
    items: list = []
    index = 1
    while index < len(text):
        while index < len(text) and text[index] in " \t\r\n,":
            index += 1
        if index >= len(text) or text[index] == "]":
            break
        try:
            item, index = decoder.raw_decode(text, index)
        except ValueError:
            break
        items.append(item)
    return items or None


def _parse_extract_response(resp: Message | None, chunk_db_ids: list[int]) -> dict:
    if resp is not None and resp.stop_reason == "max_tokens":
        logger.warning(
            "Graph extraction batch hit max_tokens — output truncated, some nodes/edges lost"
        )
    block = tool_input(resp)
    if block is None:
        raise ValueError("Graph extraction response contained no tool_use block")
    data = dict(block)

    # Both lists are filtered rather than trusted. A truncated tool call arrives
    # missing its trailing fields, and a malformed one arrives with a bare
    # string where an object should be — the second was observed on a real build
    # and raised out of the batch, costing all ten of its chunks.
    data["nodes"] = _complete(data.get("nodes", []), _REQUIRED_NODE_KEYS, "node")
    data["edges"] = _complete(data.get("edges", []), _REQUIRED_EDGE_KEYS, "edge")
    inferred = attach_orphan_claims(data)
    if inferred:
        logger.debug("Attached %d orphaned claim(s) to concepts from their chunks", inferred)

    return attach_chunk_db_ids(data, chunk_db_ids)
