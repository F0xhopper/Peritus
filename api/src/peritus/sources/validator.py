"""Claude source validator — validates sources in batches of 5, one API call per batch."""

import asyncio
from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.sources.domain import DroppedSource, RawSource, ValidatedSource

logger = get_logger(__name__)

# Quality is a floor (junk filter); relevance is held to a higher bar so the
# corpus stays on-topic and the credential means something.
_PASS_THRESHOLD_Q = 5.0
_PASS_THRESHOLD_R = 6.0
# Sample multiple regions instead of judging a source by its opening (often front
# matter / abstract). Stamped on the credential as the rubric version.
_PREVIEW_WINDOW_CHARS = 800
RUBRIC_VERSION = "v3-concepts-q5r6"
_VALIDATE_BATCH_SIZE = 5

_SOURCE_TYPE_HINTS: dict[str, str] = {
    "reddit": (
        "This source is a Reddit thread. Judge it on the factual accuracy and depth "
        "of its insight, not its informal prose — but do not inflate the score for "
        "informality. Discussion without substantive, accurate content scores low."
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
    "genuinely addresses the topic with credible content. "
    "When a list of key concepts is provided, judge relevance against the topic "
    "and those concepts, and tag each source with the key concepts it covers."
)

_BATCH_TOOL: dict[str, Any] = {
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
                        "covered_concepts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Which of the listed key concepts this source substantively "
                                "covers — copied verbatim from the provided list. Empty if "
                                "none, or if no key concepts were provided."
                            ),
                        },
                        "drop_reason": {
                            "type": ["string", "null"],
                            "description": "Short phrase if quality_score < 5 OR relevance_score < 6, else null.",
                        },
                    },
                    "required": [
                        "quality_score", "relevance_score", "content_type",
                        "difficulty", "key_claims", "covered_concepts", "drop_reason",
                    ],
                },
            }
        },
        "required": ["validations"],
    },
}


def _build_preview(text: str) -> str:
    """Sample head, middle, and tail so a source is judged on more than its opening."""
    n = len(text)
    if n <= _PREVIEW_WINDOW_CHARS * 3:
        return text
    head = text[:_PREVIEW_WINDOW_CHARS]
    mid_start = (n // 2) - (_PREVIEW_WINDOW_CHARS // 2)
    middle = text[mid_start: mid_start + _PREVIEW_WINDOW_CHARS]
    tail = text[-_PREVIEW_WINDOW_CHARS:]
    return f"{head}\n\n[…]\n\n{middle}\n\n[…]\n\n{tail}"


def _match_concepts(raw: list, key_concepts: list[str]) -> list[str]:
    """Map model-reported concept tags back onto the canonical concept list.

    Guards against paraphrased or invented tags: only concepts that casefold-match
    a provided key concept survive, and they come back in canonical spelling.
    """
    canonical = {c.casefold().strip(): c for c in key_concepts}
    matched: list[str] = []
    for item in raw or []:
        if not isinstance(item, str):
            continue
        hit = canonical.get(item.casefold().strip())
        if hit and hit not in matched:
            matched.append(hit)
    return matched


async def validate_sources(
    topic: str,
    sources: list[RawSource],
    key_concepts: list[str] | None = None,
    on_result=None,
) -> tuple[list[ValidatedSource], list[DroppedSource]]:
    key_concepts = key_concepts or []
    sem = asyncio.Semaphore(settings.VALIDATE_CONCURRENCY)
    batches = [
        sources[i: i + _VALIDATE_BATCH_SIZE]
        for i in range(0, len(sources), _VALIDATE_BATCH_SIZE)
    ]

    async def _process_batch(batch: list[RawSource]) -> list[tuple[RawSource, dict]]:
        try:
            raw_validations = await _validate_batch(topic, batch, key_concepts, sem)
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
        for source, raw in zip(batch, raw_validations, strict=True):
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
                    covered_concepts=_match_concepts(
                        result.get("covered_concepts", []), key_concepts,
                    ),
                ))
    return passed, dropped


def _source_context(s: RawSource) -> str:
    """Extra per-source lines: author, plus expected-author check for leader content."""
    lines = []
    if s.author:
        lines.append(f"Author: {s.author}")
    hint = _SOURCE_TYPE_HINTS.get(s.source_type.value)
    if hint:
        lines.append(f"Note: {hint}")
    leader = s.metadata.get("leader")
    if leader:
        lines.append(
            f"Expected author: {leader}. If this content is not by {leader} or does not "
            "substantively present their work, score relevance low."
        )
    return ("\n".join(lines) + "\n") if lines else ""


async def _validate_batch(
    topic: str,
    batch: list[RawSource],
    key_concepts: list[str],
    sem: asyncio.Semaphore,
) -> list[dict]:
    """Validate up to _VALIDATE_BATCH_SIZE sources in a single Claude call."""
    async with sem:
        client = get_anthropic_client()
        sources_block = "\n\n".join(
            f"<source_{i}>\n"
            f"Type: {s.source_type.value}\n"
            f"Title: {s.title}\n"
            f"{_source_context(s)}"
            f"\n{_build_preview(s.text)}\n"
            f"</source_{i}>"
            for i, s in enumerate(batch)
        )
        concepts_block = (
            "Key concepts the corpus must cover:\n"
            + "\n".join(f"- {c}" for c in key_concepts)
            + "\n\n"
            if key_concepts else ""
        )
        resp = await client.messages.create(  # type: ignore[call-overload]
            model=settings.FAST_MODEL,
            max_tokens=512 * len(batch),
            system=_SYSTEM,
            tools=[_BATCH_TOOL],
            tool_choice={"type": "tool", "name": "validate_sources"},
            messages=[{
                "role": "user",
                "content": (
                    f"Topic: {topic}\n\n"
                    f"{concepts_block}"
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
