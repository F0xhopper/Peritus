"""Contextual retrieval — situate each chunk within its source before indexing."""

import asyncio

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

_BATCH_TOOL = {
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


async def contextualize_chunks(
    chunks: list[TextChunk],
    source_title: str,
    source_text: str,
) -> list[str]:
    if not chunks or not settings.CONTEXT_ENABLED or not settings.ANTHROPIC_API_KEY:
        return ["" for _ in chunks]

    surrounding = source_text[: settings.CONTEXT_MAX_CHARS]
    client = get_anthropic_client()
    sem = asyncio.Semaphore(settings.CONTEXT_CONCURRENCY)

    batches = [
        chunks[i: i + _CONTEXT_BATCH_SIZE]
        for i in range(0, len(chunks), _CONTEXT_BATCH_SIZE)
    ]

    async def one_batch(batch: list[TextChunk]) -> list[str]:
        prefix = (
            f"<source_title>{source_title}</source_title>\n"
            f"<surrounding_text>\n{surrounding}\n</surrounding_text>"
        )
        chunks_block = "\n\n".join(
            f"<chunk_{i}>\n{c.text}\n</chunk_{i}>" for i, c in enumerate(batch)
        )
        try:
            async with sem:
                resp = await client.messages.create(
                    model=settings.FAST_MODEL,
                    max_tokens=150 * len(batch),
                    system=_SYSTEM,
                    tools=[_BATCH_TOOL],
                    tool_choice={"type": "tool", "name": "contextualize_chunks"},
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prefix,
                             "cache_control": {"type": "ephemeral"}},
                            {"type": "text",
                             "text": f"{chunks_block}\n\n{_INSTRUCTION}"},
                        ],
                    }],
                )
            block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
            contexts = list(block.input.get("contexts", []))
            while len(contexts) < len(batch):
                contexts.append("")
            return contexts[: len(batch)]
        except Exception as exc:
            logger.warning("Contextualisation batch failed (%d chunks): %s", len(batch), exc)
            return ["" for _ in batch]

    batch_results = await asyncio.gather(*(one_batch(b) for b in batches))
    contexts = [ctx for batch_ctxs in batch_results for ctx in batch_ctxs]
    filled = sum(1 for c in contexts if c)
    logger.info("Contextualised %d/%d chunks for %r", filled, len(chunks), source_title)
    return contexts
