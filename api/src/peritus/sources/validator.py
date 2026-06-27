"""Claude source validator — validates sources in batches of 5, one API call per batch."""

import asyncio

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.sources.domain import DroppedSource, RawSource, ValidatedSource

logger = get_logger(__name__)

_PASS_THRESHOLD_Q = 5.0
_PASS_THRESHOLD_R = 5.0
_PREVIEW_CHARS = 2_500
_VALIDATE_BATCH_SIZE = 5

_SOURCE_TYPE_HINTS: dict[str, str] = {
    "reddit": (
        "This source is a Reddit thread. Calibrate quality for informal discussion: "
        "depth of insight and factual accuracy matter more than formal prose. "
        "A 6/10 quality score is appropriate for a genuinely informative community discussion."
    ),
    "youtube": (
        "This source is a video transcript. Spoken content naturally contains filler words and "
        "repetition — evaluate on information density and accuracy, not writing polish."
    ),
    "arxiv": (
        "This source is an academic paper. Apply rigorous standards: look for clear methodology, "
        "evidence quality, and citation depth."
    ),
    "gutenberg": (
        "This source is a classic or historical text. Evaluate relevance and historical "
        "significance rather than expecting modern academic style."
    ),
    "thought_leader": (
        "This source is content by a domain expert or practitioner. Weight depth of their "
        "specific claims and track record over formal credentials."
    ),
}

_SYSTEM = (
    "You are a rigorous source quality evaluator. "
    "Score sources honestly — a score of 5 or above means the source "
    "genuinely addresses the topic with credible content."
)

_BATCH_TOOL = {
    "name": "validate_sources",
    "description": "Score and classify each source for quality and topic relevance.",
    "input_schema": {
        "type": "object",
        "properties": {
            "validations": {
                "type": "array",
                "description": "One entry per source, in the same order as the input.",
                "items": {
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
                    "required": [
                        "quality_score", "relevance_score", "content_type",
                        "difficulty", "key_claims", "drop_reason",
                    ],
                },
            }
        },
        "required": ["validations"],
    },
}


def _build_preview(text: str) -> str:
    """Composite sample: head + tail capped at _PREVIEW_CHARS total."""
    if len(text) <= _PREVIEW_CHARS:
        return text
    head = _PREVIEW_CHARS * 2 // 3
    tail = _PREVIEW_CHARS - head
    return text[:head] + "\n\n[...]\n\n" + text[-tail:]


async def validate_sources(
    topic: str,
    sources: list[RawSource],
    on_result=None,
) -> tuple[list[ValidatedSource], list[DroppedSource]]:
    sem = asyncio.Semaphore(settings.VALIDATE_CONCURRENCY)
    batches = [
        sources[i: i + _VALIDATE_BATCH_SIZE]
        for i in range(0, len(sources), _VALIDATE_BATCH_SIZE)
    ]

    async def _process_batch(batch: list[RawSource]) -> list[tuple[RawSource, dict]]:
        try:
            raw_validations = await _validate_batch(topic, batch, sem)
        except Exception as exc:
            logger.warning("Batch validation failed (%d sources): %s", len(batch), exc)
            raw_validations = [
                {
                    "quality_score": 0.0, "relevance_score": 0.0,
                    "content_type": "other", "difficulty": 1,
                    "key_claims": [], "drop_reason": "validation error",
                }
                for _ in batch
            ]

        pairs: list[tuple[RawSource, dict]] = []
        for source, raw in zip(batch, raw_validations):
            q = float(raw.get("quality_score", 0))
            r = float(raw.get("relevance_score", 0))
            raw["drop"] = q < _PASS_THRESHOLD_Q or r < _PASS_THRESHOLD_R
            if on_result:
                await on_result({
                    "title": source.title,
                    "source_type": source.source_type.value,
                    "q": q,
                    "r": r,
                    "passed": not raw["drop"],
                    "drop_reason": raw.get("drop_reason"),
                })
            pairs.append((source, raw))
        return pairs

    batch_results = await asyncio.gather(*[_process_batch(b) for b in batches])

    passed: list[ValidatedSource] = []
    dropped: list[DroppedSource] = []
    for pairs in batch_results:
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


async def _validate_batch(topic: str, batch: list[RawSource], sem: asyncio.Semaphore) -> list[dict]:
    """Validate up to _VALIDATE_BATCH_SIZE sources in a single Claude call."""
    async with sem:
        client = get_anthropic_client()
        sources_block = "\n\n".join(
            "<source_{i}>\n"
            "Type: {stype}\n"
            "Title: {title}\n"
            "{hint}"
            "\n{preview}\n"
            "</source_{i}>".format(
                i=i,
                stype=s.source_type.value,
                title=s.title,
                hint=(f"Note: {_SOURCE_TYPE_HINTS[s.source_type.value]}\n"
                      if s.source_type.value in _SOURCE_TYPE_HINTS else ""),
                preview=_build_preview(s.text),
            )
            for i, s in enumerate(batch)
        )
        resp = await client.messages.create(
            model=settings.FAST_MODEL,
            max_tokens=512 * len(batch),
            system=_SYSTEM,
            tools=[_BATCH_TOOL],
            tool_choice={"type": "tool", "name": "validate_sources"},
            messages=[{
                "role": "user",
                "content": (
                    f"Topic: {topic}\n\n"
                    f"{sources_block}\n\n"
                    f"Validate all {len(batch)} sources above."
                ),
            }],
        )
        block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
        validations = list(block.input.get("validations", []))
        while len(validations) < len(batch):
            validations.append({
                "quality_score": 0.0, "relevance_score": 0.0,
                "content_type": "other", "difficulty": 1,
                "key_claims": [], "drop_reason": "missing validation",
            })
        return validations[: len(batch)]
