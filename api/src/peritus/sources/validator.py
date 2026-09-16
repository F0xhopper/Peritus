"""Claude source validator — a cheap first pass over everything, a careful
second pass over the sources whose verdict is actually in doubt.

**Why two passes.** The bulk of a candidate set is obviously in or obviously
out, and a fast model reading a structured preview settles those correctly and
for very little money. The sources that decide whether a corpus is good are the
ones near the threshold, and those were being settled by the same glance. So the
first pass runs unchanged in shape — batches of five on ``FAST_MODEL`` — and
anything landing in the borderline band is asked again, one source per call, on
the strong model with a much larger preview. Expected volume is 15–25% of
sources; the second pass costs a fraction of what ingesting them costs.

**Whose verdict stands.** Whichever model judged the source last. That model id
is written onto the result (and from there onto ``sources.validator_model``)
rather than read from configuration at persist time — with two models judging
different sources in one build, a column filled in from settings would attribute
both to whichever model the config happened to name.

**Errors fail open, not closed.** An unparseable batch used to drop all five of
its sources as ``validation error`` — a fifth of a lite corpus lost to one bad
response. Those sources now go through the single-source path instead, and only
drop if that fails too.
"""

from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_batch import gather_claude_calls
from peritus.infrastructure.anthropic_client import tool_input
from peritus.sources.domain import (
    COUNTING_DEPTHS,
    DEPTH_TREATS,
    DEPTHS,
    DroppedSource,
    RawSource,
    ValidatedSource,
)
from peritus.sources.preview import build_preview, build_review_preview
from peritus.sources.substance import substance_of

logger = get_logger(__name__)

# Quality is a floor (junk filter); relevance is held to a higher bar so the
# corpus stays on-topic and the credential means something.
_PASS_THRESHOLD_Q = 5.0
_PASS_THRESHOLD_R = 6.0

# The borderline band: either side of each threshold. A source inside it is one
# the first pass could plausibly have got wrong in either direction, which is
# exactly where a second opinion is worth its price — and outside it, where the
# tails are cheap and right, asking again buys nothing.
REVIEW_BAND_Q = (4.0, 6.0)
REVIEW_BAND_R = (5.0, 7.0)

# Bumped from v4-tiered-q5r6 when the preview became a structured record
# (sources/preview.py) rather than three fixed windows of raw text. The rubric's
# thresholds did not move, but what the model is shown did, and screening runs
# must be able to tell the two apart — the version is stamped on every source.
#
# v6: the rubric names the two failure cases the Thomism build (job 53) passed —
# catalogue records and publisher blurbs scored as scholarship, and overview
# sites scored on how well their title matched — and every source now carries a
# substance (full / partial / abstract) that decides whether it counts toward
# coverage. See docs/plans/source-selection.md §8.
#
# v7: the research plan's own definition of a primary source for the topic is
# shown with every batch. "Primary" means the Summa for Thomism, a trial report
# for a drug, a standard for a protocol; a generic definition let a secondary
# paper on mental causation be tagged primary on a live rebuild.
#
# v8: concept tags are graded — sets_out / treats / mentions — and a source that
# treats more than three concepts gives its three deepest. Tags used to be free,
# so three long texts met a target meant to need three sources per concept
# (docs/plans/syllabus.md, 4.A). And a page *about* an expected author is
# tertiary, however well it presents their work (3.D).
RUBRIC_VERSION = "v8-graded-tags-q5r6"
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

# How deeply a source treats a concept (the depths are in sources/domain.py;
# coverage counts sets_out and treats and never mentions).
_DEPTH_DESCRIPTION = (
    "sets_out = this source is where the concept is set out or argued at length (a "
    "chapter, a section, the paper's subject); treats = a substantial discussion, "
    "more than a passing page; mentions = referred to in passing. A source that "
    "sets out or treats more than three of the listed concepts is probably a "
    "survey: give its three deepest as sets_out or treats and the rest as mentions."
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
        "pass if the abstract substantively states the finding — a bare citation or a "
        "one-line summary cannot."
    ),
    "openalex": (
        "This source is a scholarly work. Apply rigorous standards: look for clear methodology "
        "or argument, evidence quality, and citation depth. An abstract-only record can still "
        "pass if the abstract substantively states the finding or argument. A publisher's "
        "blurb, a table of contents or a library catalogue entry is not an abstract: it "
        "describes a book without stating its argument."
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
    "still secondary, and a mediocre original paper is still primary.\n\n"
    "Each source is presented as a record: stated facts about the document "
    "(length, how its text was obtained, whether it has a reference list, where "
    "it was found), its abstract when one exists, its section headings, and "
    "samples of its body. Treat the stated facts as true — they come from the "
    "pipeline, not from the text — and use the samples to judge what the "
    "document actually argues. A short text is not automatically weak and a "
    "long one is not automatically strong; judge the substance.\n\n"
    "Two kinds of source pass a title match and must not pass on it. A library "
    "catalogue record, a table of contents, a publisher's blurb or a short book "
    "review is tertiary and scores at most 3 for quality, however important the "
    "work it describes — it contains none of that work. A study guide, "
    "encyclopedia-style overview or explainer site is tertiary, and its "
    "relevance score should reflect the depth of what it actually says about "
    "the topic, not how closely its title matches it.\n\n"
    "Tag concepts by depth, and be sparing with sets_out: it means the concept is "
    f"this source's subject or one of its chapters. {_DEPTH_DESCRIPTION}"
)

_REVIEW_SYSTEM = (
    _SYSTEM + "\n\n"
    "This source was scored close to the accept/reject threshold on a first, "
    "fast pass, and you are being asked for a considered second opinion on it "
    "alone, with more of its text. Your verdict replaces the first one. Do not "
    "anchor on the fact that it was borderline: judge it on what you are shown, "
    "and be willing to place it clearly on either side."
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
                            "enum": [
                                "textbook",
                                "paper",
                                "tutorial",
                                "reference",
                                "opinion",
                                "transcript",
                                "other",
                            ],
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
                            "items": {
                                "type": "object",
                                "properties": {
                                    "concept": {
                                        "type": "string",
                                        "description": "Copied verbatim from the provided list.",
                                    },
                                    "depth": {"type": "string", "enum": list(DEPTHS)},
                                },
                                "required": ["concept", "depth"],
                            },
                            "description": (
                                "The listed key concepts this source deals with, each with how "
                                f"deeply. {_DEPTH_DESCRIPTION} Empty if none, or if no key "
                                "concepts were provided."
                            ),
                        },
                        "drop_reason": {
                            "type": ["string", "null"],
                            "description": "Short phrase if quality_score < 5 OR relevance_score < 6, else null.",
                        },
                    },
                    "required": [
                        "quality_score",
                        "relevance_score",
                        "content_type",
                        "source_tier",
                        "difficulty",
                        "key_claims",
                        "covered_concepts",
                        "drop_reason",
                    ],
                },
            }
        },
        "required": ["validations"],
    },
}

_ERROR_VALIDATION: dict[str, Any] = {
    "quality_score": 0.0,
    "relevance_score": 0.0,
    "content_type": "other",
    "source_tier": None,
    "difficulty": 1,
    "key_claims": [],
    "covered_concepts": [],
    "drop_reason": "validation error",
}


def review_model() -> str:
    """The model that gives the second opinion. Defaults to the strong model."""
    return settings.VALIDATE_REVIEW_MODEL or settings.CLAUDE_MODEL


def _match_concepts(raw: list, key_concepts: list[str]) -> dict[str, str]:
    """Map model-reported concept tags back onto the canonical concept list, with depths.

    Guards against paraphrased or invented tags: only concepts that casefold-match
    a provided key concept survive, and they come back in canonical spelling, in
    the order given. A tag given twice keeps its deeper depth. A bare string — the
    pre-v8 shape, still possible from an old batch result — reads as ``treats``,
    and so does an entry with no readable depth.
    """
    canonical = {c.casefold().strip(): c for c in key_concepts}
    matched: dict[str, str] = {}
    for item in raw or []:
        name: Any
        if isinstance(item, str):
            name, depth = item, DEPTH_TREATS
        elif isinstance(item, dict):
            name = item.get("concept")
            depth = str(item.get("depth") or "").strip().casefold()
            if depth not in DEPTHS:
                depth = DEPTH_TREATS
        else:
            continue
        if not isinstance(name, str):
            continue
        hit = canonical.get(name.casefold().strip())
        if not hit:
            continue
        if hit not in matched or DEPTHS.index(depth) < DEPTHS.index(matched[hit]):
            matched[hit] = depth
    return matched


def covered_names(depths: dict[str, str]) -> list[str]:
    """The concepts a source covers: its tags at ``treats`` or deeper."""
    return [concept for concept, depth in depths.items() if depth in COUNTING_DEPTHS]


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


def _finalise(raw: dict, model: str) -> dict:
    """Coerce one raw validation into the shape the rest of the module relies on."""
    q = raw["quality_score"] = _coerce_score(raw.get("quality_score", 0), "quality_score")
    r = raw["relevance_score"] = _coerce_score(raw.get("relevance_score", 0), "relevance_score")
    raw["drop"] = q < _PASS_THRESHOLD_Q or r < _PASS_THRESHOLD_R
    raw["model"] = model
    return raw


def _in_band(value: float, band: tuple[float, float]) -> bool:
    low, high = band
    return low <= value < high


def needs_second_opinion(result: dict) -> bool:
    """Whether this first-pass verdict is close enough to the line to re-examine.

    A source that was never judged at all (an errored batch) also qualifies:
    routing it here is what turns a provider blip into one extra call instead of
    a silently discarded source.
    """
    if result.get("drop_reason") in ("validation error", "missing validation"):
        # The model did not judge this source — it errored, or returned
        # something that was not a verdict. Either way that is a fact about the
        # response, not about the source, and dropping on it would discard a
        # fetched source over a formatting failure.
        return True
    return _in_band(result["quality_score"], REVIEW_BAND_Q) or _in_band(
        result["relevance_score"], REVIEW_BAND_R
    )


async def validate_sources(
    topic: str,
    sources: list[RawSource],
    key_concepts: list[str] | None = None,
    on_result=None,
    on_reviewed=None,
    primary_definition: str | None = None,
) -> tuple[list[ValidatedSource], list[DroppedSource]]:
    key_concepts = key_concepts or []
    batches = [
        sources[i : i + _VALIDATE_BATCH_SIZE] for i in range(0, len(sources), _VALIDATE_BATCH_SIZE)
    ]

    # Pairs per batch index — batches complete out of order on the live path,
    # and the returned lists must keep the input's source order.
    batch_pairs: dict[int, list[tuple[RawSource, dict]]] = {}

    # Batches that took the _ERROR_VALIDATION path — i.e. the model never
    # judged them. Counted so the summary below can say whether a wipeout was
    # the validator's verdict or the validator's absence.
    errored_batches: set[int] = set()

    async def _on_batch_result(i: int, resp: Any) -> None:
        batch = batches[i]
        if resp is None:
            errored_batches.add(i)
            logger.warning(
                "Validation batch %d/%d: no response after retries — its %d source(s) "
                "go to the single-source review path rather than being dropped. This "
                "is NOT a judgement about the sources; see the Claude call errors above.",
                i + 1,
                len(batches),
                len(batch),
            )
            raw_validations = [dict(_ERROR_VALIDATION) for _ in batch]
        else:
            try:
                raw_validations = _parse_validate_response(resp, len(batch))
            except Exception as exc:
                errored_batches.add(i)
                logger.warning(
                    "Validation batch %d/%d: response unparseable (%s: %s) — its %d "
                    "source(s) go to the single-source review path",
                    i + 1,
                    len(batches),
                    type(exc).__name__,
                    exc,
                    len(batch),
                    exc_info=True,
                )
                raw_validations = [dict(_ERROR_VALIDATION) for _ in batch]

        raw_validations = [_finalise(raw, settings.FAST_MODEL) for raw in raw_validations]
        # All pairs are recorded before any progress emission: a failing
        # on_result may cost progress events, never validation results.
        batch_pairs[i] = list(zip(batch, raw_validations, strict=True))
        if on_result:
            for source, raw in batch_pairs[i]:
                await on_result(
                    {
                        "title": source.title,
                        "source_type": source.source_type.value,
                        "q": raw["quality_score"],
                        "r": raw["relevance_score"],
                        "passed": not raw["drop"],
                        "drop_reason": raw.get("drop_reason"),
                    }
                )

    # One Claude call per batch — routed through the Message Batches API
    # (half price) when enabled, else concurrent live calls. Results are parsed
    # (and per-source progress emitted) as each batch lands, not after the set.
    await gather_claude_calls(
        [
            _validate_params(topic, b, key_concepts, primary_definition=primary_definition)
            for b in batches
        ],
        live_concurrency=settings.VALIDATE_CONCURRENCY,
        description="validate",
        on_result=_on_batch_result,
    )

    all_pairs = [pair for i in sorted(batch_pairs) for pair in batch_pairs[i]]
    reviewed = await _second_opinion(
        topic, all_pairs, key_concepts, on_reviewed, primary_definition
    )

    passed: list[ValidatedSource] = []
    dropped: list[DroppedSource] = []
    for source, result in all_pairs:
        first = result.get("first_pass") or {}
        if result["drop"]:
            dropped.append(
                DroppedSource(
                    raw=source,
                    quality_score=result["quality_score"],
                    relevance_score=result["relevance_score"],
                    drop_reason=result["drop_reason"] or "below threshold",
                    validator_model=result.get("model"),
                    review_model=result.get("review_model"),
                    first_pass_quality=first.get("quality_score"),
                    first_pass_relevance=first.get("relevance_score"),
                )
            )
        else:
            depths = _match_concepts(result.get("covered_concepts", []), key_concepts)
            passed.append(
                ValidatedSource(
                    raw=source,
                    quality_score=result["quality_score"],
                    relevance_score=result["relevance_score"],
                    content_type=result["content_type"],
                    difficulty=result["difficulty"],
                    key_claims=result["key_claims"],
                    covered_concepts=covered_names(depths),
                    concept_depths=depths,
                    source_tier=_normalise_tier(result.get("source_tier")),
                    validator_model=result.get("model"),
                    review_model=result.get("review_model"),
                    first_pass_quality=first.get("quality_score"),
                    first_pass_relevance=first.get("relevance_score"),
                    substance=substance_of(source),
                )
            )

    unjudged = sum(1 for d in dropped if d.drop_reason == "validation error")
    if not passed and unjudged:
        # The distinction the caller's error message could not make. "Everything
        # scored below threshold" and "the validator never ran" both arrive here
        # as an empty `passed`, and only one of them is about the sources.
        logger.error(
            "Validation produced NO passing sources for %r: %d/%d were never judged "
            "(%d/%d batches errored, and the review pass could not rescue them). This "
            "is a provider/infrastructure failure, not a verdict on the corpus — the "
            "sources were fetched fine.",
            topic,
            unjudged,
            len(all_pairs),
            len(errored_batches),
            len(batches),
        )
    else:
        logger.info(
            "Validation for %r: %d passed, %d dropped (%d never judged, %d/%d batches "
            "errored, %d reviewed on %s)",
            topic,
            len(passed),
            len(dropped),
            unjudged,
            len(errored_batches),
            len(batches),
            reviewed,
            review_model(),
        )
    return passed, dropped


async def _second_opinion(
    topic: str,
    pairs: list[tuple[RawSource, dict]],
    key_concepts: list[str],
    on_reviewed=None,
    primary_definition: str | None = None,
) -> int:
    """Re-judge the borderline (and never-judged) sources in place.

    Mutates the result dicts in ``pairs``: the reviewer's verdict replaces the
    first pass's, and the first pass's scores are kept under ``first_pass`` so
    the ledger can show that a decision was re-examined and what changed.
    Returns how many were reviewed.
    """
    if not settings.VALIDATE_SECOND_OPINION:
        return 0
    candidates = [(i, s, r) for i, (s, r) in enumerate(pairs) if needs_second_opinion(r)]
    if not candidates:
        return 0

    model = review_model()
    logger.info(
        "Second opinion on %d/%d borderline source(s) using %s",
        len(candidates),
        len(pairs),
        model,
    )

    reviewed = 0
    results: dict[int, dict] = {}

    async def _on_review(n: int, resp: Any) -> None:
        index, source, _first = candidates[n]
        if resp is None:
            return
        try:
            raw = _parse_validate_response(resp, 1)[0]
        except Exception as exc:
            logger.warning(
                "Second-opinion response unparseable for %r (%s: %s) — keeping the "
                "first pass's verdict",
                source.title,
                type(exc).__name__,
                exc,
            )
            return
        results[index] = _finalise(raw, model)

    await gather_claude_calls(
        [
            _validate_params(
                topic, [source], key_concepts, review=True, primary_definition=primary_definition
            )
            for _index, source, _first in candidates
        ],
        live_concurrency=settings.VALIDATE_CONCURRENCY,
        description="validate-review",
        on_result=_on_review,
    )

    for index, source, first in candidates:
        verdict = results.get(index)
        if verdict is None:
            continue
        was_error = first.get("drop_reason") == "validation error"
        verdict["review_model"] = model
        verdict["first_pass"] = (
            None
            if was_error
            else {
                "quality_score": first["quality_score"],
                "relevance_score": first["relevance_score"],
            }
        )
        reversed_ = (not was_error) and first["drop"] != verdict["drop"]
        pairs[index] = (source, verdict)
        reviewed += 1
        if reversed_:
            logger.info(
                "Second opinion reversed %r: q %.1f→%.1f, r %.1f→%.1f (%s → %s)",
                source.title,
                first["quality_score"],
                verdict["quality_score"],
                first["relevance_score"],
                verdict["relevance_score"],
                "drop" if first["drop"] else "keep",
                "drop" if verdict["drop"] else "keep",
            )
        if on_reviewed:
            await on_reviewed(
                {
                    "title": source.title,
                    "source_type": source.source_type.value,
                    "first_q": None if was_error else first["quality_score"],
                    "first_r": None if was_error else first["relevance_score"],
                    "q": verdict["quality_score"],
                    "r": verdict["relevance_score"],
                    "passed": not verdict["drop"],
                    "reversed": reversed_,
                    "review_model": model,
                }
            )
    return reviewed


def _source_context(s: RawSource) -> str:
    """Extra per-source lines the preview cannot carry: the type hint, and the
    expected-author check for thought-leader content."""
    lines = []
    hint = _SOURCE_TYPE_HINTS.get(s.source_type.value)
    if hint:
        lines.append(f"Note: {hint}")
    leader = s.metadata.get("leader")
    if leader:
        lines.append(
            f"Expected author: {leader}. If this is by {leader}, judge it as their own "
            f"work. If it is about {leader} — an encyclopedia entry, a profile, a review "
            "of their work — classify it tertiary; do not score relevance on how well it "
            "presents their work. If it is neither by nor about them, score relevance low."
        )
    return ("\n".join(lines) + "\n") if lines else ""


def _validate_params(
    topic: str,
    batch: list[RawSource],
    key_concepts: list[str],
    review: bool = False,
    primary_definition: str | None = None,
) -> dict[str, Any]:
    """Request params for one validation call (consumed by gather_claude_calls)."""
    preview = build_review_preview if review else build_preview
    sources_block = "\n\n".join(
        f"<source_{i}>\n{_source_context(s)}{preview(s)}\n</source_{i}>"
        for i, s in enumerate(batch)
    )
    concepts_block = (
        "Key concepts the corpus must cover:\n" + "\n".join(f"- {c}" for c in key_concepts) + "\n\n"
        if key_concepts
        else ""
    )
    definition_block = (
        "For this topic, a PRIMARY source is: "
        f"{primary_definition.strip()}\n"
        "Classify source_tier by that definition. A study, commentary or overview "
        "of such a source is secondary or tertiary, however closely it quotes it.\n\n"
        if primary_definition and primary_definition.strip()
        else ""
    )
    return {
        "model": review_model() if review else settings.FAST_MODEL,
        "max_tokens": 512 * len(batch) + (512 if review else 0),
        "system": _REVIEW_SYSTEM if review else _SYSTEM,
        "tools": [_BATCH_TOOL],
        "tool_choice": {"type": "tool", "name": "validate_sources"},
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Topic: {topic}\n\n"
                    f"{definition_block}"
                    f"{concepts_block}"
                    f"{sources_block}\n\n"
                    + (
                        "Give your considered verdict on this source."
                        if review
                        else f"Validate all {len(batch)} sources above."
                    )
                ),
            }
        ],
    }


_MISSING_VALIDATION: dict[str, Any] = {
    "quality_score": 0.0,
    "relevance_score": 0.0,
    "content_type": "other",
    "source_tier": None,
    "difficulty": 1,
    "key_claims": [],
    "covered_concepts": [],
    "drop_reason": "missing validation",
}


def _parse_validate_response(resp: Any, batch_len: int) -> list[dict]:
    """Exactly ``batch_len`` validation dicts, whatever the model returned.

    The tool schema asks for an array of objects and a model can still return an
    array containing a bare string — observed live, on a real build. Every entry
    is therefore checked rather than trusted: one malformed element used to
    raise out of the batch's result handler and cost all five of its sources,
    which is the same fail-closed behaviour the errored-batch path exists to
    prevent.

    A malformed entry becomes a "missing validation", which
    :func:`needs_second_opinion` treats as unjudged — so the source is re-asked
    properly instead of being dropped for the model's formatting.
    """
    block = tool_input(resp) or {}
    raw = block.get("validations", [])
    validations: list[dict] = []
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, dict):
            validations.append(entry)
        else:
            logger.warning(
                "Validation entry was %s, not an object: %r — treating it as missing",
                type(entry).__name__,
                str(entry)[:120],
            )
            validations.append(dict(_MISSING_VALIDATION))
    while len(validations) < batch_len:
        validations.append(dict(_MISSING_VALIDATION))
    return validations[:batch_len]
