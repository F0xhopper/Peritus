"""Judged helpfulness of an answer — is it worth reading?

The counterpart to ``chat/faithfulness.py``. That module asks whether an answer
is *entailed* by its passages; this one asks whether it is any *use* to the
person who asked. Both are needed, and neither substitutes for the other: the
answer that prompted this work scored near-perfectly on grounding while being a
hedged tour of its own retrieval set.

Offline eval only. Nothing here runs on a live answer — it costs a second model
call and would add latency to a response the user is already reading. It follows
``faithfulness``'s shape otherwise: one fast-model call, tool-use for a typed
result, and fails open (returns ``None``) so a judge outage degrades a report
rather than breaking a run.
"""

from typing import Any

from peritus.chat.grounding import Passage
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client

logger = get_logger(__name__)

_TOOL: dict[str, Any] = {
    "name": "report_helpfulness",
    "description": "Score how useful this answer is to the person who asked.",
    "input_schema": {
        "type": "object",
        "properties": {
            "direct_answer": {
                "type": "number",
                "description": (
                    "0.0–1.0. Does the answer lead with the substance actually "
                    "asked for? 1.0 = the first sentence carries it. 0.0 = it "
                    "opens with preamble, restates the question, describes what "
                    "it is about to do, or never plainly answers at all."
                ),
            },
            "subject_organised": {
                "type": "number",
                "description": (
                    "0.0–1.0. Is the answer organised by the SUBJECT or by its "
                    "SOURCES? 1.0 = structured around ideas, and citations sit "
                    "at the end of claims about the topic. 0.0 = structured "
                    "around who said what ('one summary frames…', 'this guide "
                    "calls…'), a walk through the retrieval set. Judge the "
                    "structure and the prose register, not the citation count."
                ),
            },
            "terms_defined": {
                "type": "number",
                "description": (
                    "0.0–1.0. Are terms the stated asker would not know defined "
                    "inline on first use? Return 1.0 when the asker is an expert "
                    "or the answer uses no jargon — an answer is not penalised "
                    "for a question that needed no definitions."
                ),
            },
            "actionable": {
                "type": "number",
                "description": (
                    "0.0–1.0. Could the asker do or understand something "
                    "concrete afterwards? 1.0 = specific practices, figures, or "
                    "examples they can use. 0.0 = characterisations of ideas "
                    "without content, or hedging so uniform that nothing is "
                    "usable."
                ),
            },
            "no_corpus_meta": {
                "type": "number",
                "description": (
                    "0.0–1.0. Freedom from commentary about the answer's own "
                    "sources. 1.0 = none. 0.0 = a 'what's missing' section, an "
                    "audit of coverage, or remarks on whether the material is "
                    "primary or secondary.\n"
                    "Two things are REQUIRED behaviour and must score 1.0:\n"
                    "(a) briefly marking one point as general background ('my "
                    "sources don't cover this, but in general…');\n"
                    "(b) a SHORT refusal when the passages genuinely do not "
                    "address the question — naming in one or two sentences what "
                    "the sources do cover instead. A refusal cannot be written "
                    "without mentioning the sources, so mentioning them is not a "
                    "defect. Penalise only a refusal that runs long or itemises "
                    "the corpus."
                ),
            },
            "contradicts_passages": {
                "type": "boolean",
                "description": (
                    "True only if the answer states something a passage directly "
                    "contradicts. A claim merely absent from the passages is NOT "
                    "a contradiction — judge conflict, not coverage."
                ),
            },
            "notes": {
                "type": "string",
                "description": (
                    "One or two sentences on the weakest dimension, quoting the "
                    "phrase that earned the low score. Empty if the answer is good."
                ),
            },
        },
        "required": [
            "direct_answer", "subject_organised", "terms_defined",
            "actionable", "no_corpus_meta", "contradicts_passages", "notes",
        ],
    },
}

# The judge is told what the answer was *supposed* to do, because the same prose
# is good or bad depending on who asked. It is also told the rules the answer was
# written under — otherwise it reliably penalises uncited definitions and
# marked gap-fill, which the grounding contract explicitly requires.
_SYSTEM = (
    "You judge how useful an expert's answer is to the person who asked it. "
    "You are not checking whether it is well-sourced — a separate auditor does "
    "that. Judge it as the asker would.\n"
    "\n"
    "The answer was written under rules you must account for:\n"
    "- Substantive claims about the subject carry a bracketed citation [n]. "
    "That is correct behaviour, not padding.\n"
    "- Definitions, structure, worked examples, and connective reasoning are "
    "the expert's own and carry NO citation. An uncited definition is correct, "
    "not an unsupported claim.\n"
    "- Briefly marking a point as general background beyond the sources is "
    "correct. Auditing the corpus at length is not.\n"
    "\n"
    "Score honestly and use the whole range. A fluent answer that never quite "
    "says anything the asker can use is a low score, not a middling one."
)


async def assess_helpfulness(
    question: str,
    answer_text: str,
    passages: list[Passage],
    asker_level: str = "informed",
    question_type: str = "open_ended",
) -> dict | None:
    """Return the judged dimensions plus ``contradicts_passages`` and ``notes``.

    Returns ``None`` when there is nothing to judge or the call fails. Passages
    are included so the contradiction check has the evidence in front of it;
    they are truncated the same way the faithfulness auditor truncates them.
    """
    if not answer_text.strip() or not settings.ANTHROPIC_API_KEY:
        return None
    try:
        passage_block = "\n\n".join(
            f"[{p.index}] {p.citation}\n{p.text[:800]}" for p in passages
        ) or "(no passages were retrieved)"

        client = get_anthropic_client()
        resp = await client.messages.create(  # type: ignore[call-overload]
            model=settings.FAST_MODEL,
            max_tokens=768,
            system=_SYSTEM,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "report_helpfulness"},
            messages=[{
                "role": "user",
                "content": (
                    f"Question asked: {question}\n"
                    f"Who asked: a {asker_level} asker\n"
                    f"What kind of answer would satisfy them: {question_type}\n\n"
                    f"Answer to judge:\n{answer_text}\n\n"
                    f"Passages the answer had available:\n\n{passage_block}"
                ),
            }],
        )
        block = next(
            (b for b in resp.content if getattr(b, "type", None) == "tool_use"),
            None,
        )
        if block is None:
            return None
        return dict(block.input)
    except Exception as exc:
        logger.warning("Helpfulness assessment failed: %s", exc)
        return None
