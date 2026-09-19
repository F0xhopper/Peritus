"""Stage 5: the persona, and the warning that goes beside it.

The persona is the last thing a build produces and the first thing a user reads,
so it is generated from what the corpus *actually* contains rather than from the
topic string: the digest below is built from the sources that passed.

`corpus_tier_warning` lives here because it answers the same question from the
other side — what this corpus cannot be trusted to say — and the two are shown
together.
"""

import re

from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client, tool_input
from peritus.sources.domain import ValidatedSource

logger = get_logger(__name__)


#: The longest a persona's style block may be. Stored personas ran to 3,300–
#: 3,400 characters, placed after the answer rules in the system prompt — the
#: position that weighs most — and one guard sentence did not stop them scripting
#: the opening of every answer ("Let's see what the chronicler says…" on the
#: production answer to the king question, with the guard in place).
PERSONA_MAX_CHARS = 1_500


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
                    "this expert TEACHES: the framings and analogies they "
                    "characteristically reach for, the kind of worked example "
                    "they use, what they insist matters most and what they "
                    "consider a distraction, and how they talk to someone new "
                    "to the subject. Positive voice instructions only — write "
                    "what they do, never a list of rules about sourcing, "
                    "citation, hedging, or uncertainty, and nothing about how "
                    "an answer opens or is structured. At most "
                    f"{PERSONA_MAX_CHARS} characters."
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
    "Do not script how answers open or are laid out either, and do not tell the "
    "expert to announce or narrate their own method ('tell students you are "
    "using…', 'name the step you are on'). Every answer opens with the direct "
    "answer, under rules of its own; an expert told to introduce their method "
    "first spends the opening of every answer on the method instead of the "
    "subject. Describe the method so it can be used, not performed.\n\n"
    "The bio and the style block have different jobs and should not read alike. "
    "The bio is what a reader skims in five seconds to decide if this is the "
    "right expert — keep it short and plain. The style block governs how the "
    "expert teaches: two or three tight paragraphs, at most "
    f"{PERSONA_MAX_CHARS} characters. It sits beside rules about how every "
    "answer opens and is laid out, and a longer persona outweighs them."
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
    # Asked for, not guaranteed: what scripts an opening is removed, and an
    # over-long block is condensed rather than shipped.
    persona["style"] = await condense_persona(persona["style"])
    return persona


# A sentence that scripts how an answer opens, or tells the expert to perform
# its method rather than use it. Written against the stored personas: "You open
# almost every explanation the same way: …", "you tell students you are using a
# 'ladder from creatures to Creator,' and you name the rung you're standing on",
# "you never start with God — you start with a chair".
_SCRIPTING = re.compile(
    r"\byou (?:almost )?(?:always |usually |typically |often )?"
    r"(?:open|begin|start|launch)\b(?! a (?:hive|frame|box))"
    r"|\b(?:open|begin|start)s? (?:almost )?every (?:answer|explanation|lesson|reply)"
    r"|\byou (?:tell|remind) (?:students|newcomers|them|the (?:asker|reader|student))\b"
    r"|\byou (?:are explicit about|announce|name the (?:rung|step|stage))"
    r"|\bsignature (?:phrase|line|opening|routine)"
    r"|[\"“'‘](?:let'?s|let me|now|first|so|here'?s)\b[^\"”’]{12,}[\"”’]",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"”’]))\s+(?=[A-Z\"“])")


def scripted_sentences(style: str) -> list[str]:
    """The sentences of a persona that script an opening or narrate a method."""
    return [s for p in style.split("\n") for s in _SENTENCE_SPLIT.split(p) if _SCRIPTING.search(s)]


def strip_scripted(style: str) -> str:
    """``style`` without its scripting sentences, paragraphs kept."""
    paragraphs = []
    for paragraph in (style or "").strip().split("\n"):
        kept = [s for s in _SENTENCE_SPLIT.split(paragraph) if not _SCRIPTING.search(s)]
        paragraphs.append(" ".join(kept).strip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(paragraphs)).strip()


_CONDENSE_SYSTEM = (
    "You condense a teaching persona for a grounded AI tutor. Keep what makes "
    "this teacher distinct: the framings, analogies and worked examples they "
    "reach for, what they emphasise and what they cut. Drop anything about how "
    "an answer opens or is laid out, any routine or catchphrase, and anything "
    "telling them to announce or narrate their method. Second person, positive "
    f"voice, two or three paragraphs, about {PERSONA_MAX_CHARS - 400} "
    "characters. Reply with the condensed persona only."
)


# The cap is "about", not exact: a model asked for a length lands within a few
# hundred characters of it, and a persona 10% over the cap is not the problem
# a persona twice the cap was.
_CAP_SLACK = 1.15


async def condense_persona(style: str) -> str:
    """``style`` cut to ``PERSONA_MAX_CHARS`` by the model, scripting removed.

    Deterministic stripping first; the model only runs when what is left is
    still too long, and its output is stripped again rather than trusted.
    """
    stripped = strip_scripted(style)
    if len(stripped) <= PERSONA_MAX_CHARS:
        return stripped
    client = get_anthropic_client()
    messages: list[MessageParam] = [MessageParam(role="user", content=stripped)]
    condensed = ""
    for _ in range(2):
        resp = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=1024,
            system=_CONDENSE_SYSTEM,
            messages=messages,
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        condensed = strip_scripted(text)
        if condensed and len(condensed) <= PERSONA_MAX_CHARS * _CAP_SLACK:
            return condensed
        # Models overshoot a character count; told by how much, they do not.
        messages += [
            MessageParam(role="assistant", content=text),
            MessageParam(
                role="user",
                content=(
                    f"That is {len(condensed)} characters. Cut it to under "
                    f"{PERSONA_MAX_CHARS - 200}, keeping the most distinctive parts."
                ),
            ),
        ]
    raise RuntimeError(f"Condensed persona is {len(condensed)} chars; expected under the cap")


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
