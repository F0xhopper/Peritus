"""Post-generation faithfulness check.

Verifies the generated answer is actually entailed by the retrieved passages,
turning "looks cited" into a measurable groundedness score. Cheap by design — one
Haiku call — and fails open (returns ``None``) so a checker error never blocks an
answer that has already been streamed to the user.
"""

from typing import Any

from peritus.chat.grounding import Passage
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client

logger = get_logger(__name__)

_TOOL: dict[str, Any] = {
    "name": "report_faithfulness",
    "description": "Report how well the answer is supported by the passages.",
    "input_schema": {
        "type": "object",
        "properties": {
            "groundedness": {
                "type": "number",
                "description": (
                    "0.0–1.0. Fraction of the answer's factual claims that are "
                    "directly supported by at least one passage."
                ),
            },
            "unsupported_claims": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Short quotes of claims not supported by any passage.",
            },
        },
        "required": ["groundedness", "unsupported_claims"],
    },
}

_SYSTEM = (
    "You are a strict faithfulness auditor for a retrieval-grounded answer. "
    "Compare the answer against the numbered passages. A claim is supported only if "
    "a passage directly states or clearly implies it. General knowledge does not "
    "count as support. Be conservative: when in doubt, mark a claim unsupported."
)


async def assess_faithfulness(
    question: str,
    answer_text: str,
    passages: list[Passage],
) -> dict | None:
    """Return ``{"groundedness": float, "unsupported_claims": [str]}`` or ``None``.

    The auditor sees exactly the evidence the answer was meant to draw from.
    """
    if not answer_text.strip() or not passages or not settings.ANTHROPIC_API_KEY:
        return None
    try:
        passage_block = "\n\n".join(
            f"[{p.index}] {p.citation}\n{p.text[:800]}"
            for p in passages
        )
        client = get_anthropic_client()
        resp = await client.messages.create(  # type: ignore[call-overload]
            model=settings.FAST_MODEL,
            max_tokens=512,
            system=_SYSTEM,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "report_faithfulness"},
            messages=[{
                "role": "user",
                "content": (
                    f"Question: {question}\n\n"
                    f"Answer to audit:\n{answer_text}\n\n"
                    f"Passages:\n\n{passage_block}"
                ),
            }],
        )
        block = next(
            (b for b in resp.content if getattr(b, "type", None) == "tool_use"),
            None,
        )
        if block is None:
            return None
        data = dict(block.input)
        score = data.get("groundedness")
        if not isinstance(score, (int, float)):
            return None
        return {
            "groundedness": max(0.0, min(1.0, float(score))),
            "unsupported_claims": list(data.get("unsupported_claims", [])),
        }
    except Exception as exc:
        logger.warning("Faithfulness assessment failed: %s", exc)
        return None
