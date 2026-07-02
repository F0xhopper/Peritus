"""Contextual retrieval — situate each chunk within its source before indexing."""

import asyncio
from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.ingestion.chunker import TextChunk

logger = get_logger(__name__)

_CONTEXT_BATCH_SIZE = 5  # chunks per API call

_SYSTEM = (
    "You situate text excerpts within their source document so they can be accurately "
    "retrieved by a search engine. For each chunk, reply with one or two sentences only — "
    "no preamble, no quotation, no commentary."
)

_BATCH_TOOL: dict[str, Any] = {
    "name": "contextualize_chunks",
    "description": "Generate a short retrieval context for each chunk, in order.",
    "input_schema": {
        "type": "object",
        "properties": {
            "contexts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1–2 sentence retrieval context per chunk, same order as input.",
            }
        },
        "required": ["contexts"],
    },
}

_INSTRUCTION = (
    "For each numbered chunk above, write 1–2 sentences that situate it within the source "
    "so a search engine can retrieve it accurately. Name the source and specific topic "
    "where relevant. Return exactly one string per chunk in the contexts array."
)

# How much of the document to show as the local window around a batch, split
# between text before and after the batch's span.
_DOC_HEAD_CHARS = 800  # always-included framing so the model knows what the source is


def _locate_offsets(source_text: str, chunks: list[TextChunk]) -> list[int]:
    """Best-effort character offset of each chunk within the source, in order.

    Chunks are emitted in document order, so we scan forward from the previous
    match. Falls back to the running cursor when a chunk can't be located (e.g.
    whitespace normalisation), which keeps windows monotonic rather than correct
    to the character — good enough to situate a chunk in the right region.
    """
    offsets: list[int] = []
    cursor = 0
    for c in chunks:
        probe = c.text[:120]
        idx = source_text.find(probe, cursor) if probe else -1
        if idx == -1 and probe:
            idx = source_text.find(probe)
        if idx == -1:
            idx = cursor
        offsets.append(idx)
        cursor = max(cursor, idx + len(c.text))
    return offsets


async def contextualize_chunks(
    chunks: list[TextChunk],
    source_title: str,
    source_text: str,
) -> list[str]:
    if not chunks or not settings.CONTEXT_ENABLED or not settings.ANTHROPIC_API_KEY:
        return ["" for _ in chunks]

    offsets = _locate_offsets(source_text, chunks)
    doc_head = source_text[:_DOC_HEAD_CHARS]
    half_window = max(settings.CONTEXT_MAX_CHARS // 2, _DOC_HEAD_CHARS)

    client = get_anthropic_client()
    sem = asyncio.Semaphore(settings.CONTEXT_CONCURRENCY)

    batches = [
        (i, chunks[i: i + _CONTEXT_BATCH_SIZE])
        for i in range(0, len(chunks), _CONTEXT_BATCH_SIZE)
    ]

    def _window_for(start_idx: int, batch: list[TextChunk]) -> str:
        first_off = offsets[start_idx]
        last = start_idx + len(batch) - 1
        last_end = offsets[last] + len(batch[-1].text)
        win_start = max(0, first_off - half_window)
        win_end = min(len(source_text), last_end + half_window)
        window = source_text[win_start:win_end]
        # Prepend the document head when the window doesn't already include it, so
        # even late chunks are framed by what the source actually is.
        if win_start > _DOC_HEAD_CHARS:
            return f"{doc_head}\n…\n{window}"
        return window

    async def one_batch(start_idx: int, batch: list[TextChunk]) -> list[str]:
        surrounding = _window_for(start_idx, batch)
        prompt = (
            f"<source_title>{source_title}</source_title>\n"
            f"<surrounding_text>\n{surrounding}\n</surrounding_text>\n\n"
            + "\n\n".join(f"<chunk_{i}>\n{c.text}\n</chunk_{i}>" for i, c in enumerate(batch))
            + f"\n\n{_INSTRUCTION}"
        )
        try:
            async with sem:
                resp = await client.messages.create(  # type: ignore[call-overload]
                    model=settings.FAST_MODEL,
                    max_tokens=150 * len(batch),
                    system=_SYSTEM,
                    tools=[_BATCH_TOOL],
                    tool_choice={"type": "tool", "name": "contextualize_chunks"},
                    messages=[{"role": "user", "content": prompt}],
                )
            block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
            contexts = list(block.input.get("contexts", []))
            while len(contexts) < len(batch):
                contexts.append("")
            return contexts[: len(batch)]
        except Exception as exc:
            logger.warning("Contextualisation batch failed (%d chunks): %s", len(batch), exc)
            return ["" for _ in batch]

    batch_results = await asyncio.gather(*(one_batch(i, b) for i, b in batches))
    contexts = [ctx for batch_ctxs in batch_results for ctx in batch_ctxs]
    filled = sum(1 for c in contexts if c)
    logger.info("Contextualised %d/%d chunks for %r", filled, len(chunks), source_title)
    return contexts
