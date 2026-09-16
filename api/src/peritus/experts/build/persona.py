"""Stage 5: the persona, and the warning that goes beside it.

The persona is the last thing a build produces and the first thing a user reads,
so it is generated from what the corpus *actually* contains rather than from the
topic string: the digest below is built from the sources that passed.

`corpus_tier_warning` lives here because it answers the same question from the
other side — what this corpus cannot be trusted to say — and the two are shown
together.
"""

from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client, tool_input
from peritus.sources.domain import ValidatedSource

logger = get_logger(__name__)


_PERSONA_TOOL: ToolParam = {
    "name": "generate_persona",
    "description": "Generate a named expert persona grounded in the corpus.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                # The UI titles any persona that comes back bare (see
                # web/lib/persona.ts), so an untitled name is not a broken
                # build — asking here just means the stored name and the
                # displayed one agree.
                "description": (
                    "Expert's full name, prefixed with the honorific 'Dr.' — "
                    "e.g. 'Dr. Elena Vasquez'."
                ),
            },
            "bio": {
                "type": "string",
                "description": (
                    "2-3 SHORT sentences, scannable in five seconds: what they "
                    "specialize in and their angle on it. Plain and concrete — "
                    "no compound sentences stacking multiple clauses, no "
                    "throat-clearing ('with a career spanning...', 'has spent "
                    "years...'), no restating the topic name back. Write it "
                    "the way a conference program blurbs a speaker, not the "
                    "way an academic CV opens."
                ),
            },
            "style": {
                "type": "string",
                "description": (
                    "A system-prompt block, in the second person, describing how "
                    "this expert TEACHES: how they open an explanation, the "
                    "framings and analogies they characteristically reach for, "
                    "the kind of worked example they use, what they insist "
                    "matters most and what they consider a distraction, and how "
                    "they talk to someone new to the subject. Positive voice "
                    "instructions only — write what they do, never a list of "
                    "rules about sourcing, citation, hedging, or uncertainty."
                ),
            },
        },
        "required": ["name", "bio", "style"],
    },
}


# The persona is the expert's teaching voice, and nothing else. It used to be
# asked for "how the expert cites, qualifies claims, and handles uncertainty",
# which reliably produced personas whose defining trait was hedging — a voice
# that then argued with the answer-shape rules on every turn. Sourcing
# discipline belongs to the grounding contract (chat/grounding.py), which is
# absolute and needs no help from the persona; what the persona is for is the
# thing a contract cannot supply, which is how a good teacher explains.
_PERSONA_SYSTEM = (
    "You are creating a named expert persona that will be the voice of a "
    "grounded AI tutor. The persona must reflect what this corpus actually "
    "contains — a specialist in these particular materials, not a generic "
    "authority. Name them as a doctor of the subject ('Dr. <given> <family>'), "
    "since every expert here is addressed by name and title.\n\n"
    "Write the style block as a teacher's profile: how they explain a hard idea "
    "to a newcomer, the analogies and framings they return to, the worked "
    "examples they favour, what they emphasise and what they cut. Make it "
    "concrete and specific to this corpus — a reader should be able to tell "
    "this expert from any other expert in the same field.\n\n"
    "Do not write anything about citation, sourcing, evidence quality, "
    "qualifying claims, or handling uncertainty. Separate absolute rules govern "
    "all of that, and duplicating them here produces a hedging, evasive voice "
    "instead of a teaching one.\n\n"
    "The bio and the style block have different jobs and should not read alike. "
    "The bio is what a reader skims in five seconds to decide if this is the "
    "right expert — keep it short and plain. The style block is what actually "
    "governs how the expert teaches, so it can be as thorough as that job "
    "requires; length there is not the problem the bio has."
)


def _persona_digest(sources: list[tuple[str, str, float | None, list[str]]]) -> str:
    """One line per source: title, kind, quality, and its leading claims.

    Takes plain tuples rather than ``ValidatedSource`` so a persona can be
    regenerated from the ``sources`` table long after the build that produced it.
    """
    lines = []
    for title, content_type, quality, claims in sources[:15]:
        q = f"Q:{quality:.1f}" if quality is not None else "Q:—"
        lines.append(f"- {title} ({content_type}, {q}): " + "; ".join(claims[:2]))
    return "\n".join(lines)


async def generate_persona(
    topic: str,
    sources: list[tuple[str, str, float | None, list[str]]],
    top_nodes: list[dict],
) -> dict:
    """Generate ``{name, bio, style}`` from a corpus digest.

    Public because personas outlive the build that made them: an expert built
    under an older persona prompt can be re-voiced without re-fetching,
    re-validating and re-embedding its whole corpus. See
    ``ExpertService.regenerate_persona``.
    """
    concept_list = ", ".join(n["label"] for n in top_nodes[:20])

    client = get_anthropic_client()
    resp = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        # 1024 was enough when `style` was a sentence about how the expert cites.
        # A teaching profile is several paragraphs, and `style` is the last field
        # in the schema — too small a budget truncates the tool call and returns
        # {name, bio} with no style at all, which is a KeyError at the call site
        # rather than a degraded persona.
        max_tokens=3072,
        system=_PERSONA_SYSTEM,
        tools=[_PERSONA_TOOL],
        tool_choice=ToolChoiceToolParam(type="tool", name="generate_persona"),
        messages=[
            MessageParam(
                role="user",
                content=(
                    f"Topic: {topic}\n\n"
                    f"Sources ingested:\n{_persona_digest(sources)}\n\n"
                    f"Top concepts extracted: {concept_list}"
                ),
            )
        ],
    )
    block = tool_input(resp) or {}
    persona = dict(block)

    # A tool call cut off by the token budget still parses — it just arrives
    # missing its trailing fields. Catching it here names the cause; letting it
    # through surfaces as a KeyError three frames away, at whichever caller
    # happened to read `persona["style"]` first.
    missing = [k for k in ("name", "bio", "style") if not persona.get(k)]
    if missing:
        raise RuntimeError(
            f"Persona generation returned no {', '.join(missing)} "
            f"(stop_reason={resp.stop_reason!r}). Raise max_tokens if this is "
            "'max_tokens'."
        )
    return persona


async def _generate_persona(
    topic: str,
    sources: list[tuple[str, str, float | None, list[str]]],
    top_nodes: list[dict],
) -> dict:
    """The build's persona call — a seam tests patch."""
    return await generate_persona(topic, sources, top_nodes)


# A corpus that is overwhelmingly tertiary answers everything second-hand: it
# can tell you what people say about a subject and never what the subject is.
# Below this share of classified sources, the expert is worth building but the
# user should know what they are getting *before* they chat with it — the failure
# it produces is subtle, and reads as the model being evasive rather than as the
# corpus being thin.
_TERTIARY_WARN_SHARE = 0.7


# Under this many classified sources the share is noise, not a finding.
_TERTIARY_WARN_MIN_CLASSIFIED = 3


def corpus_tier_warning(passed: list[ValidatedSource]) -> dict | None:
    """A build warning if the passing corpus is overwhelmingly second-hand.

    Pure, so the threshold is testable without a build. Sources the validator
    could not classify are counted separately and never held against the corpus:
    an unclassified source is unknown, not tertiary.
    """
    counts = dict.fromkeys(("primary", "secondary", "tertiary"), 0)
    unclassified = 0
    for vs in passed:
        if vs.source_tier in counts:
            counts[vs.source_tier] += 1
        else:
            unclassified += 1

    classified = sum(counts.values())
    if classified < _TERTIARY_WARN_MIN_CLASSIFIED:
        return None
    if counts["tertiary"] / classified < _TERTIARY_WARN_SHARE:
        return None

    return {
        "type": "corpus_warning",
        "reason": "mostly_tertiary",
        "primary": counts["primary"],
        "secondary": counts["secondary"],
        "tertiary": counts["tertiary"],
        "unclassified": unclassified,
        "classified": classified,
        "message": (
            f"{counts['tertiary']} of {classified} classified sources are "
            "summaries, reviews or overviews rather than primary texts or "
            "substantive analysis. This expert will answer second-hand. "
            "Rebuilding with more specific sources — the works themselves, "
            "original papers, or practitioners' own writing — would help."
        ),
    }


def _avg_quality(passed: list[ValidatedSource]) -> float | None:
    if not passed:
        return None
    scores = [vs.quality_score for vs in passed if vs.quality_score is not None]
    return round(sum(scores) / len(scores), 2) if scores else None
