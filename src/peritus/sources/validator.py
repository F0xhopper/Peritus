"""Claude source validator — one call per raw source, concurrency-limited."""

import asyncio
import json

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.sources.domain import DroppedSource, RawSource, ValidatedSource

logger = get_logger(__name__)

_PASS_THRESHOLD_Q = 5.0
_PASS_THRESHOLD_R = 5.0
_PREVIEW_CHARS = 2000

_TOOL = {
    "name": "validate_source",
    "description": "Score and classify a source for quality and topic relevance.",
    "input_schema": {
        "type": "object",
        "properties": {
            "quality_score": {
                "type": "number",
                "description": "0–10. Accuracy, depth, credibility, writing quality.",
            },
            "relevance_score": {
                "type": "number",
                "description": "0–10. How directly this source addresses the topic.",
            },
            "content_type": {
                "type": "string",
                "enum": ["textbook", "paper", "tutorial", "reference", "opinion", "transcript", "other"],
            },
            "difficulty": {
                "type": "integer",
                "description": "1 (introductory) to 5 (expert).",
            },
            "key_claims": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Up to 5 central claims or arguments from this source.",
            },
            "drop_reason": {
                "type": ["string", "null"],
                "description": "Short phrase if quality_score < 5 OR relevance_score < 5, else null.",
            },
        },
        "required": ["quality_score", "relevance_score", "content_type", "difficulty", "key_claims", "drop_reason"],
    },
}


async def validate_sources(
    topic: str,
    sources: list[RawSource],
    on_result=None,
) -> tuple[list[ValidatedSource], list[DroppedSource]]:
    sem = asyncio.Semaphore(settings.VALIDATE_CONCURRENCY)

    async def _one(source: RawSource):
        try:
            result = await _validate_one(topic, source, sem)
        except Exception as exc:
            logger.warning("Validation error for %r: %s", source.title, exc)
            result = {
                "quality_score": 0.0, "relevance_score": 0.0,
                "content_type": "other", "difficulty": 1,
                "key_claims": [], "drop_reason": "validation error", "drop": True,
            }
        if on_result:
            await on_result({
                "title": source.title,
                "source_type": source.source_type.value,
                "q": result["quality_score"],
                "r": result["relevance_score"],
                "passed": not result["drop"],
                "drop_reason": result.get("drop_reason"),
            })
        return source, result

    pairs = await asyncio.gather(*[_one(s) for s in sources])

    passed: list[ValidatedSource] = []
    dropped: list[DroppedSource] = []
    for source, result in pairs:
        if result["drop"]:
            dropped.append(DroppedSource(
                raw=source,
                quality_score=result["quality_score"],
                relevance_score=result["relevance_score"],
                drop_reason=result["drop_reason"] or "below threshold",
            ))
        else:
            passed.append(ValidatedSource(
                raw=source,
                quality_score=result["quality_score"],
                relevance_score=result["relevance_score"],
                content_type=result["content_type"],
                difficulty=result["difficulty"],
                key_claims=result["key_claims"],
            ))
    return passed, dropped


async def _validate_one(topic: str, source: RawSource, sem: asyncio.Semaphore) -> dict:
    async with sem:
        client = get_anthropic_client()
        preview = source.text[:_PREVIEW_CHARS]
        resp = await client.messages.create(
            model=settings.FAST_MODEL,
            max_tokens=512,
            system=(
                "You are a rigorous source quality evaluator. "
                "Score sources honestly — a score of 5 or above means the source "
                "genuinely addresses the topic with credible content."
            ),
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "validate_source"},
            messages=[{
                "role": "user",
                "content": (
                    f"Topic: {topic}\n\n"
                    f"Source title: {source.title}\n\n"
                    f"Source text (first {_PREVIEW_CHARS} chars):\n{preview}"
                ),
            }],
        )
        block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
        data = dict(block.input)
        q = float(data.get("quality_score", 0))
        r = float(data.get("relevance_score", 0))
        data["drop"] = q < _PASS_THRESHOLD_Q or r < _PASS_THRESHOLD_R
        return data
