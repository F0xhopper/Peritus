"""What a corpus is made of, and the one rule that drops a source for it.

The goal is that the primary texts are *there* — every concept resting on the
work itself — not that they are a large share. Secondary, tertiary and
abstract-only sources that pass validation all stay: an overview, a review
article and a good abstract are useful beside the primary text. Two things
enforce presence rather than share, elsewhere: coverage requires a primary
source per concept and does not count abstract-only sources toward it
(experts/coverage.py), and the plan names a primary text per concept that the
build looks up by title (sources/canonical.py).

What is dropped here is a stub: an abstract-only source resting on under 800
characters, which is a publisher's blurb or a catalogue line rather than an
abstract. The share caps (abstract-only ≤ 15%, tertiary ≤ 25%) that this module
first shipped with are kept as settings, off by default
(``COMPOSITION_ABSTRACT_SHARE_CAP``, ``COMPOSITION_TERTIARY_SHARE_CAP``): they
removed sources that were fine, to move a percentage nobody needed moved.

Whatever is dropped is dropped *with a reason* and stays in ``sources`` as
``passed = false``.

:func:`corpus_composition` is the summary a build stores under
``build_summary.corpus`` — the numbers docs/plans/source-selection.md is judged
by, and the first thing the corpus report shows.
"""

from __future__ import annotations

import math
from typing import Any

from peritus.core.config import settings
from peritus.experts.coverage import CoverageReport, CoverageTarget, compute_coverage
from peritus.sources.domain import NAMED_MISSING, DroppedSource, ValidatedSource
from peritus.sources.substance import SUBSTANCE_ABSTRACT, abstract_chars

MIN_ABSTRACT_CHARS = 800
# A fetched source the validator scored this low on relevance should never have
# been fetched. The count is the triage stage's report card.
JUNK_RELEVANCE = 3.0

DROP_ABSTRACT_TOO_SHORT = "abstract only (under 800 characters)"
DROP_ABSTRACT_OVER_SHARE = "abstract only (over share)"
DROP_TERTIARY_OVER_SHARE = "tertiary (over share)"

# Drops that are not a verdict on the source's content, and so say nothing
# about whether it was worth fetching.
_UNJUDGED_PREFIXES = ("duplicate of", "validation error", "missing validation")


def apply_composition_caps(
    passed: list[ValidatedSource],
) -> tuple[list[ValidatedSource], list[DroppedSource]]:
    """Drop abstract stubs, and apply any share caps that are switched on."""
    if not passed:
        return [], []
    accepted = len(passed)
    kept = list(passed)
    dropped: list[DroppedSource] = []

    too_short = [
        vs
        for vs in kept
        if vs.substance == SUBSTANCE_ABSTRACT and abstract_chars(vs.raw) < MIN_ABSTRACT_CHARS
    ]
    for vs in too_short:
        kept.remove(vs)
        dropped.append(_drop(vs, DROP_ABSTRACT_TOO_SHORT))

    abstract_cap = settings.COMPOSITION_ABSTRACT_SHARE_CAP
    tertiary_cap = settings.COMPOSITION_TERTIARY_SHARE_CAP

    over = (
        []
        if abstract_cap <= 0
        else _over_share(
            [vs for vs in kept if vs.substance == SUBSTANCE_ABSTRACT],
            abstract_cap,
            accepted,
            key=lambda vs: (vs.quality_score + vs.relevance_score, vs.relevance_score),
        )
    )
    for vs in over:
        kept.remove(vs)
        dropped.append(_drop(vs, DROP_ABSTRACT_OVER_SHARE))

    over = (
        []
        if tertiary_cap <= 0
        else _over_share(
            [vs for vs in kept if vs.source_tier == "tertiary"],
            tertiary_cap,
            accepted,
            key=lambda vs: (vs.relevance_score, vs.quality_score),
        )
    )
    for vs in over:
        kept.remove(vs)
        dropped.append(_drop(vs, DROP_TERTIARY_OVER_SHARE))

    return kept, dropped


def _over_share(group, cap: float, accepted: int, key) -> list[ValidatedSource]:
    """The members of ``group`` beyond ``cap × accepted``, lowest ``key`` first.

    At least one is always allowed, so a small round is not stripped of its only
    overview or its only abstract by rounding.
    """
    allowed = max(1, math.floor(cap * accepted + 1e-9))
    if len(group) <= allowed:
        return []
    ranked = sorted(group, key=key, reverse=True)
    return ranked[allowed:]


def _drop(vs: ValidatedSource, reason: str) -> DroppedSource:
    return DroppedSource(
        raw=vs.raw,
        quality_score=vs.quality_score,
        relevance_score=vs.relevance_score,
        drop_reason=reason,
        validator_model=vs.validator_model,
        review_model=vs.review_model,
        first_pass_quality=vs.first_pass_quality,
        first_pass_relevance=vs.first_pass_relevance,
    )


def corpus_composition(
    passed: list[ValidatedSource],
    dropped: list[DroppedSource],
    key_concepts: list[str],
    must_have: list[dict[str, Any]] | None = None,
    named_texts: dict[str, dict[str, Any]] | None = None,
    figures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The corpus by tier, substance and concept, for ``build_summary.corpus``.

    Concept shares and "without primary" are read off coverage itself
    (experts/coverage.py), so they count a source's tags exactly as coverage
    does — counting depths only, at most three per source, a section-cut work for
    the concepts it was cut for — and a concept is without primary by the
    named-text gate: one whose named text is missing is not reported as having a
    primary source because a long primary text was tagged with it.
    """

    total = len(passed)

    def share(count: int) -> float:
        return round(count / total, 3) if total else 0.0

    tiers = {tier: 0 for tier in ("primary", "secondary", "tertiary")}
    unclassified = 0
    for vs in passed:
        if vs.source_tier in tiers:
            tiers[vs.source_tier] += 1
        else:
            unclassified += 1
    abstract_only = sum(1 for vs in passed if vs.substance == SUBSTANCE_ABSTRACT)

    junk = sum(
        1
        for ds in dropped
        if ds.relevance_score <= JUNK_RELEVANCE
        and not ds.drop_reason.startswith(_UNJUDGED_PREFIXES)
    )

    named = named_texts or {}
    coverage = _measure(passed, key_concepts, named)

    return {
        "sources": total,
        "primary": tiers["primary"],
        "secondary": tiers["secondary"],
        "tertiary": tiers["tertiary"],
        "unclassified": unclassified,
        "abstract_only": abstract_only,
        "primary_share": share(tiers["primary"]),
        "secondary_share": share(tiers["secondary"]),
        "tertiary_share": share(tiers["tertiary"]),
        "abstract_only_share": share(abstract_only),
        "junk_fetched": junk,
        "concept_shares": {
            c.concept: share(c.sources + c.abstract_only) for c in coverage.concepts
        },
        "concepts_without_primary": [c.concept for c in coverage.concepts if not c.has_primary],
        "concepts_missing_named_text": [
            {"concept": c.concept, "texts": list(named[c.concept].get("texts") or [])}
            for c in coverage.concepts
            if c.named_text == NAMED_MISSING
        ],
        "must_have": list(must_have or []),
        "figures": list(figures or []),
    }


# Counts only — no concept is held to a target when describing the corpus.
_NO_TARGET = CoverageTarget(
    min_sources=0, min_source_types=0, require_non_tertiary=False, max_rounds=0
)


def _measure(
    passed: list[ValidatedSource], key_concepts: list[str], named: dict[str, dict[str, Any]]
) -> CoverageReport:
    statuses = {c: str(entry.get("status")) for c, entry in named.items() if entry.get("status")}
    return compute_coverage(key_concepts, passed, _NO_TARGET, named_texts=statuses)


def top_concept_shares(
    passed: list[ValidatedSource], key_concepts: list[str], n: int = 3
) -> list[tuple[str, float]]:
    """The ``n`` concepts taking the largest share of the corpus, largest first."""
    total = len(passed)
    shares = [
        (c.concept, round((c.sources + c.abstract_only) / total, 3) if total else 0.0)
        for c in _measure(passed, key_concepts, {}).concepts
    ]
    return sorted(shares, key=lambda item: (-item[1], item[0]))[:n]
