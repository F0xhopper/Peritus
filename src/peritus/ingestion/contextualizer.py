"""Contextual retrieval — situate each chunk within its source before indexing."""

import asyncio

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.ingestion.chunker import TextChunk

logger = get_logger(__name__)

_SYSTEM = (
    "You situate text excerpts within their source document so they can be accurately "
    "retrieved by a search engine. Reply with one or two sentences of context only — "
    "no preamble, no quotation, no commentary."
)

_INSTRUCTION = (
    "Write a short context (1–2 sentences) that situates this chunk within the source, "
    "so a search engine can retrieve it accurately. Name the source and the specific "
    "topic where relevant. Answer with the context only."
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

    async def one(idx: int, chunk: TextChunk) -> str:
        prefix = (
            f"<source_title>{source_title}</source_title>\n"
            f"<surrounding_text>\n{surrounding}\n</surrounding_text>"
        )
        try:
            async with sem:
                resp = await client.messages.create(
                    model=settings.FAST_MODEL,
                    max_tokens=150,
                    system=_SYSTEM,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prefix,
                             "cache_control": {"type": "ephemeral"}},
                            {"type": "text",
                             "text": f"<chunk>\n{chunk.text}\n</chunk>\n\n{_INSTRUCTION}"},
                        ],
                    }],
                )
            return "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        except Exception as exc:
            logger.warning("Contextualisation failed for chunk %d: %s", idx, exc)
            return ""

    contexts = await asyncio.gather(*(one(i, c) for i, c in enumerate(chunks)))
    filled = sum(1 for c in contexts if c)
    logger.info("Contextualised %d/%d chunks for %r", filled, len(chunks), source_title)
    return list(contexts)
