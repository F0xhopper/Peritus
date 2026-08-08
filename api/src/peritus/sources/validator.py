"""Claude source validator — validates sources in batches of 5, one API call per batch."""

from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_batch import gather_claude_calls
from peritus.sources.domain import DroppedSource, RawSource, ValidatedSource

logger = get_logger(__name__)

# Quality is a floor (junk filter); relevance is held to a higher bar so the
# corpus stays on-topic and the credential means something.
_PASS_THRESHOLD_Q = 5.0
_PASS_THRESHOLD_R = 6.0
# Sample multiple regions instead of judging a source by its opening (often front
# matter / abstract). Stamped on the credential as the rubric version.
_PREVIEW_WINDOW_CHARS = 800
# Bumped from v3-concepts-q5r6 when source_tier joined the rubric. The version is
# stamped on every validated source, so changing what the rubric asks for without
# bumping it would silently mix two rubrics under one label and corrupt the
# provenance record.
RUBRIC_VERSION = "v4-tiered-q5r6"
_VALIDATE_BATCH_SIZE = 5

# What a tier means, in the validator's words and the build's. A corpus can score
# well on quality and relevance while consisting entirely of material *about* the
# subject rather than *of* it, and nothing in the old rubric could see that.
SOURCE_TIERS: tuple[str, ...] = ("primary", "secondary", "tertiary")
_TIER_DESCRIPTION = (
    "primary = the work, text, dataset, standard, or original research itself, "
    "or a practitioner writing first-hand; "
    "secondary = substantive scholarly or expert analysis that makes its own "
    "argument about primary material; "
    "tertiary = summaries, reviews, study guides, listicles, encyclopedia-style "
    "overviews, and other material that mainly restates what others have said."
)

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
    "pubmed": (
        "This source is a biomedical research paper. Apply rigorous standards: look for clear "
        "methodology, evidence quality, and citation depth. An abstract-only record can still "
        "pass if the abstract substantively states the finding."
    ),
    "openalex": (
        "This source is a scholarly work. Apply rigorous standards: look for clear methodology "
        "or argument, evidence quality, and citation depth. An abstract-only record can still "
        "pass if the abstract substantively states the finding or argument."
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
    "and those concepts, and tag each source with the key concepts it covers. "
    "Also classify how close each source sits to the subject itself: "
    f"{_TIER_DESCRIPTION} "
    "Tier is a description, not a score — a first-rate literature review is "
    "still secondary, and a mediocre original paper is still primary."
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
                        "source_tier": {
                            "type": "string",
                            "enum": list(SOURCE_TIERS),
                            "description": (
                                "How close this source sits to the subject "
                                f"itself. {_TIER_DESCRIPTION}"
                            ),
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
                        "source_tier", "difficulty", "key_claims",
                        "covered_concepts", "drop_reason",
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


def _normalise_tier(raw) -> str | None:
    """Keep only the three rubric tiers; anything else is *unknown*, not a tier.

    ``None`` is meaningful downstream — a corpus-composition warning must not
    count a source it could not classify as if it were good news or bad.
    """
    if isinstance(raw, str) and raw.strip().casefold() in SOURCE_TIERS:
        return raw.strip().casefold()
    return None


def _coerce_score(raw, field: str) -> float:
    """Read one 0–10 score out of model output without trusting its type.

    The tool schema asks for a number, but this value decides whether a source is
    kept, and it is the last thing in the pipeline still able to fail a build
    *after* discovery and fetching have already been paid for. An unreadable
    score is treated as 0 — the same as an explicit rejection — so a malformed
    field drops one source instead of losing the whole run.
    """
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("Unreadable %s in validation output: %r — scoring 0", field, raw)
        return 0.0


async def validate_sources(
    topic: str,
    sources: list[RawSource],
    key_concepts: list[str] | None = None,
    on_result=None,
) -> tuple[list[ValidatedSource], list[DroppedSource]]:
    key_concepts = key_concepts or []
    batches = [
        sources[i: i + _VALIDATE_BATCH_SIZE]
        for i in range(0, len(sources), _VALIDATE_BATCH_SIZE)
    ]

    _ERROR_VALIDATION = {
        "quality_score": 0.0, "relevance_score": 0.0,
        "content_type": "other", "source_tier": None, "difficulty": 1,
        "key_claims": [], "drop_reason": "validation error",
    }

    # Pairs per batch index — batches complete out of order on the live path,
    # and the returned lists must keep the input's source order.
    batch_pairs: dict[int, list[tuple[RawSource, dict]]] = {}

    async def _on_batch_result(i: int, resp: Any) -> None:
        batch = batches[i]
        if resp is None:
            logger.warning("Batch validation failed (%d sources)", len(batch))
            raw_validations = [dict(_ERROR_VALIDATION) for _ in batch]
        else:
            try:
                raw_validations = _parse_validate_response(resp, len(batch))
            except Exception as exc:
                logger.warning("Batch validation unparseable (%d sources): %s", len(batch), exc)
                raw_validations = [dict(_ERROR_VALIDATION) for _ in batch]

        for raw in raw_validations:
            # Write the coerced floats back: everything downstream (the drop
            # decision, the persisted row, the audit export) must see the same
            # number, not whatever type the model happened to emit.
            q = raw["quality_score"] = _coerce_score(raw.get("quality_score", 0), "quality_score")
            r = raw["relevance_score"] = _coerce_score(
                raw.get("relevance_score", 0), "relevance_score"
            )
            raw["drop"] = q < _PASS_THRESHOLD_Q or r < _PASS_THRESHOLD_R
        # All pairs are recorded before any progress emission: a failing
        # on_result may cost progress events, never validation results.
        batch_pairs[i] = list(zip(batch, raw_validations, strict=True))
        if on_result:
            for source, raw in batch_pairs[i]:
                await on_result({
                    "title": source.title,
                    "source_type": source.source_type.value,
                    "q": raw["quality_score"],
                    "r": raw["relevance_score"],
                    "passed": not raw["drop"],
                    "drop_reason": raw.get("drop_reason"),
                })

    # One Claude call per batch — routed through the Message Batches API
    # (half price) when enabled, else concurrent live calls. Results are parsed
    # (and per-source progress emitted) as each batch lands, not after the set.
    await gather_claude_calls(
        [_validate_params(topic, b, key_concepts) for b in batches],
        live_concurrency=settings.VALIDATE_CONCURRENCY,
        description="validate",
        on_result=_on_batch_result,
    )

    all_pairs = [pair for i in sorted(batch_pairs) for pair in batch_pairs[i]]

    passed: list[ValidatedSource] = []
    dropped: list[DroppedSource] = []
    for source, result in all_pairs:
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
                source_tier=_normalise_tier(result.get("source_tier")),
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


def _validate_params(
    topic: str,
    batch: list[RawSource],
    key_concepts: list[str],
) -> dict[str, Any]:
    """Request params for one validation batch (consumed by gather_claude_calls)."""
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
    return {
        "model": settings.FAST_MODEL,
        "max_tokens": 512 * len(batch),
        "system": _SYSTEM,
        "tools": [_BATCH_TOOL],
        "tool_choice": {"type": "tool", "name": "validate_sources"},
        "messages": [{
            "role": "user",
            "content": (
                f"Topic: {topic}\n\n"
                f"{concepts_block}"
                f"{sources_block}\n\n"
                f"Validate all {len(batch)} sources above."
            ),
        }],
    }


def _parse_validate_response(resp: Any, batch_len: int) -> list[dict]:
    block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
    validations = list(block.input.get("validations", []))
    while len(validations) < batch_len:
        validations.append({
            "quality_score": 0.0, "relevance_score": 0.0,
            "content_type": "other", "source_tier": None, "difficulty": 1,
            "key_claims": [], "drop_reason": "missing validation",
        })
    return validations[:batch_len]
