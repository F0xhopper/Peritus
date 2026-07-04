"""Candidate triage — ranks cheap search hits before paying full-fetch costs.

Discovery over-searches (~3× the fetch budget), then a fast Claude pass scores
every candidate's expected value against the research brief. Only the ranked
winners get fully downloaded/OCR'd, so the pipeline considers far more
candidates than it fetches.
"""

import difflib
from dataclasses import dataclass
from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_batch import gather_claude_calls
from peritus.sources.domain import SourceCandidate

logger = get_logger(__name__)

_TRIAGE_BATCH_SIZE = 20
_SNIPPET_CHARS = 400
# Below this expected value a candidate isn't worth a full fetch at all.
MIN_TRIAGE_SCORE = 3.0
# Neutral score assumed when a triage batch fails — keeps candidates usable
# without letting an outage promote junk above genuinely scored items.
_FALLBACK_SCORE = 5.0
_NEAR_DUP_TITLE_RATIO = 0.85

_TRIAGE_TOOL: dict[str, Any] = {
    "name": "triage_candidates",
    "description": "Score each candidate source's expected value for the expert corpus.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "description": "One entry per candidate, in the same order as the input.",
                "items": {
                    "type": "object",
                    "properties": {
                        "expected_value": {
                            "type": "number",
                            "description": (
                                "0–10. How valuable this source is likely to be: "
                                "relevance to the topic and key concepts, depth, "
                                "authority, and whether it adds something the other "
                                "candidates don't."
                            ),
                        },
                    },
                    "required": ["expected_value"],
                },
            }
        },
        "required": ["scores"],
    },
}

_SYSTEM = (
    "You triage search results for a research corpus. Only titles and snippets are "
    "available — judge expected value, not final quality. Prefer primary and "
    "authoritative material and depth over introductions; score generic, off-topic "
    "or thin-looking results low."
)


@dataclass
class TriagedCandidate:
    candidate: SourceCandidate
    score: float


async def triage_candidates(
    topic: str,
    key_concepts: list[str],
    must_have_titles: list[str],
    candidates: list[SourceCandidate],
) -> list[TriagedCandidate]:
    """Score all candidates in batched Haiku calls. Order is preserved.

    Calls run through the Message Batches API (half price) when enabled, else
    as concurrent live calls.
    """
    if not candidates:
        return []

    batches = [
        candidates[i: i + _TRIAGE_BATCH_SIZE]
        for i in range(0, len(candidates), _TRIAGE_BATCH_SIZE)
    ]

    responses = await gather_claude_calls(
        [_triage_params(topic, key_concepts, b) for b in batches],
        live_concurrency=settings.VALIDATE_CONCURRENCY,
        description="triage",
    )

    batch_scores: list[list[float]] = []
    for batch, resp in zip(batches, responses, strict=True):
        if resp is None:
            logger.warning("Triage batch failed (%d candidates)", len(batch))
            batch_scores.append([_FALLBACK_SCORE] * len(batch))
            continue
        try:
            batch_scores.append(_parse_triage_response(resp, len(batch)))
        except Exception as exc:
            logger.warning("Triage batch unparseable (%d candidates): %s", len(batch), exc)
            batch_scores.append([_FALLBACK_SCORE] * len(batch))

    triaged: list[TriagedCandidate] = []
    for batch, scores in zip(batches, batch_scores, strict=True):
        for candidate, score in zip(batch, scores, strict=True):
            # A must-have work found by search should never lose the triage.
            if _matches_must_have(candidate.title, must_have_titles):
                score = max(score, 9.0)
            triaged.append(TriagedCandidate(candidate=candidate, score=score))
    return triaged


def rank_candidates(
    triaged: list[TriagedCandidate],
    min_score: float = MIN_TRIAGE_SCORE,
) -> list[TriagedCandidate]:
    """Rank by score, drop junk, and drop near-duplicate titles.

    Returns the full ranked list (not cut to budget) so the fetch stage can
    refill from lower ranks when a download fails.
    """
    ranked = sorted(triaged, key=lambda t: t.score, reverse=True)
    kept: list[TriagedCandidate] = []
    kept_titles: list[str] = []
    for item in ranked:
        if item.score < min_score:
            continue
        title = item.candidate.title.casefold().strip()
        if any(
            difflib.SequenceMatcher(None, title, seen).ratio() >= _NEAR_DUP_TITLE_RATIO
            for seen in kept_titles
        ):
            continue
        kept.append(item)
        kept_titles.append(title)
    return kept


def _matches_must_have(title: str, must_have_titles: list[str]) -> bool:
    t = title.casefold().strip()
    for wanted in must_have_titles:
        w = wanted.casefold().strip()
        if not w:
            continue
        if w in t or difflib.SequenceMatcher(None, w, t).ratio() >= 0.7:
            return True
    return False


def _triage_params(
    topic: str,
    key_concepts: list[str],
    batch: list[SourceCandidate],
) -> dict[str, Any]:
    """Request params for one triage batch (consumed by gather_claude_calls)."""
    candidates_block = "\n\n".join(
        f"<candidate_{i}>\n"
        f"Type: {c.source_type.value}\n"
        f"Title: {c.title}\n"
        + (f"Author: {c.author}\n" if c.author else "")
        + f"Snippet: {c.snippet[:_SNIPPET_CHARS]}\n"
        f"</candidate_{i}>"
        for i, c in enumerate(batch)
    )
    concepts_block = (
        "Key concepts the corpus must cover:\n"
        + "\n".join(f"- {c}" for c in key_concepts)
        + "\n\n"
        if key_concepts else ""
    )
    return {
        "model": settings.FAST_MODEL,
        "max_tokens": 64 * len(batch) + 256,
        "system": _SYSTEM,
        "tools": [_TRIAGE_TOOL],
        "tool_choice": {"type": "tool", "name": "triage_candidates"},
        "messages": [{
            "role": "user",
            "content": (
                f"Topic: {topic}\n\n"
                f"{concepts_block}"
                f"{candidates_block}\n\n"
                f"Score all {len(batch)} candidates above."
            ),
        }],
    }


def _parse_triage_response(resp: Any, batch_len: int) -> list[float]:
    block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
    raw_scores = list(block.input.get("scores", []))
    scores: list[float] = []
    for entry in raw_scores[:batch_len]:
        try:
            value = float(entry.get("expected_value", _FALLBACK_SCORE))
        except (TypeError, ValueError, AttributeError):
            value = _FALLBACK_SCORE
        scores.append(min(max(value, 0.0), 10.0))
    while len(scores) < batch_len:
        scores.append(_FALLBACK_SCORE)
    return scores
