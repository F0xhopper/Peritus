"""Coverage: how well the corpus covers the syllabus the plan set for it.

Coverage used to be a boolean — a concept was a gap only at *zero* accepted
sources — and a boolean cannot express the difference between a concept resting
on one blog post and one resting on three peer-reviewed papers and a primary
text. Both read as covered, and the build stopped looking.

A target says what "covered" means for a tier: how many sources, from how many
different kinds of source, and whether at least one of them must be something
other than a summary. That turns coverage from a check the build performs once
into a condition the discovery loop iterates against, and it turns "the build
stopped" into a sentence with a reason in it.

Pure functions over validated sources, so every threshold is testable without a
build.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from peritus.sources.domain import (
    COUNTING_DEPTHS,
    DEPTH_SETS_OUT,
    DEPTH_TREATS,
    DEPTHS,
    NAMED_FOUND,
    NAMED_MISSING,
    NAMED_NONE,
    NAMED_PARTIAL,
    SourceType,
    ValidatedSource,
)

# Tiers that count as evidence rather than restatement. A concept whose only
# support is tertiary is covered by material *about* the subject, which is the
# corpus failure the source-tier rubric exists to detect.
NON_TERTIARY: frozenset[str] = frozenset({"primary", "secondary"})

# A source whose whole text is an abstract (or under the stub length) ships to
# the corpus but never counts toward coverage. A catalogue record with a
# publisher's blurb can say a concept is "covered" and cannot teach it; twelve of
# those sat in the Thomism corpus (job 53) as secondary sources, each one a
# reason for the loop to stop looking.
NON_COUNTING_SUBSTANCE: frozenset[str] = frozenset({"abstract"})

# Concept tags are graded (the depths live in sources/domain.py). A tag used to
# be free: a 200,000-character volume "covered" four concepts at once, each
# gaining a source, a type and a primary from one fetch, and a target meant to
# need three sources per concept was met by three long texts.
#
# At most this many of one source's tags count, deepest first. A source that
# treats more than three concepts is a survey; it counts for its three deepest.
MAX_COUNTING_TAGS = 3


def counting_tags(source: ValidatedSource) -> list[tuple[str, str]]:
    """``(concept, depth)`` for the tags this source may count toward coverage.

    A work whose named sections were cut out for particular concepts counts for
    exactly those concepts: nothing else is in the text (4.B). Anything else
    counts by its graded tags, at most :data:`MAX_COUNTING_TAGS`, deepest first.
    A source validated before graded tags reads its flat tags as ``treats``.
    """
    meta = source.raw.metadata or {}
    cut_for = meta.get("must_have_concepts") if meta.get("sections_matched") else None
    if cut_for:
        return [(str(c), DEPTH_SETS_OUT) for c in dict.fromkeys(cut_for)]
    depths = source.concept_depths or {c: DEPTH_TREATS for c in source.covered_concepts}
    tags = [(c, d) for c, d in depths.items() if d in COUNTING_DEPTHS]
    tags.sort(key=lambda tag: DEPTHS.index(tag[1]))
    return tags[:MAX_COUNTING_TAGS]


@dataclass(frozen=True)
class CoverageTarget:
    """What a tier requires before it considers a concept covered."""

    min_sources: int
    min_source_types: int
    require_non_tertiary: bool
    # Discovery rounds *after* the first. 1 keeps today's shape: round 0, then
    # one targeted round for whatever it missed.
    max_rounds: int
    # Depth, not only breadth: every concept needs a primary source. A breadth
    # floor alone was met by the Thomism corpus after round 0 while metaphysics
    # had no primary text at all, so the loop never ran the round that could
    # have found one.
    require_primary: bool = False
    # Rounds after round 0 that must *run* before `targets_met` may stop the
    # loop. The feedback round is the only stage that reads the corpus and
    # searches in the field's own vocabulary.
    min_rounds: int = 0

    def as_dict(self) -> dict:
        return {
            "min_sources": self.min_sources,
            "min_source_types": self.min_source_types,
            "require_non_tertiary": self.require_non_tertiary,
            "require_primary": self.require_primary,
            "max_rounds": self.max_rounds,
            "min_rounds": self.min_rounds,
        }


@dataclass(frozen=True)
class ConceptCoverage:
    concept: str
    sources: int
    source_types: frozenset[SourceType] = frozenset()
    tiers: frozenset[str] = frozenset()
    met: bool = False
    # How far from the target, as a sortable tuple. The loop searches for the
    # concepts with the largest shortfall first.
    shortfall: int = 0
    # Counting sources that are primary texts.
    primary: int = 0
    # Accepted sources tagged with this concept that did not count, because
    # their text is only an abstract.
    abstract_only: int = 0
    # The status of the concept's named primary text: found | partial | missing
    # | none_named. It gates "has primary" (4.C).
    named_text: str = NAMED_NONE
    # Counting tags by depth: {"sets_out": n, "treats": n}.
    depth_counts: dict[str, int] = field(default_factory=dict)
    # Whether the concept has its primary source by the named-text gate, as
    # opposed to a primary-tier source merely being tagged with it.
    has_primary: bool = False

    def as_dict(self) -> dict:
        return {
            "concept": self.concept,
            "sources": self.sources,
            "source_types": sorted(t.value for t in self.source_types),
            "tiers": sorted(self.tiers),
            "primary": self.primary,
            "has_primary": self.has_primary,
            "named_text": self.named_text,
            "depth_counts": dict(self.depth_counts),
            "abstract_only": self.abstract_only,
            "met": self.met,
            "shortfall": self.shortfall,
        }


@dataclass(frozen=True)
class FacetCoverage:
    """A facet of the syllabus and how its concepts stand (docs/plans/syllabus.md, phase 2)."""

    name: str
    concepts: tuple[str, ...]
    # Every concept in the facet met.
    met: bool
    # Any concept in the facet has a primary source.
    primary: bool

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "concepts": list(self.concepts),
            "met": self.met,
            "primary": self.primary,
        }


@dataclass(frozen=True)
class CoverageReport:
    target: CoverageTarget
    concepts: tuple[ConceptCoverage, ...] = ()
    facets: tuple[FacetCoverage, ...] = ()

    @property
    def met(self) -> bool:
        """Whether every concept reaches its target. Vacuously true with no concepts."""
        return all(c.met for c in self.concepts)

    @property
    def unmet(self) -> tuple[ConceptCoverage, ...]:
        return tuple(c for c in self.concepts if not c.met)

    @property
    def uncovered(self) -> tuple[str, ...]:
        """Concepts with no accepted source at all — the old definition of a gap."""
        return tuple(c.concept for c in self.concepts if c.sources == 0)

    def weakest(self, n: int) -> list[ConceptCoverage]:
        """The ``n`` concepts furthest from target, largest shortfall first.

        Ties break on the concept name so a re-run of the same corpus searches
        for the same things — a loop whose queries depend on dict ordering is
        not reproducible, and reproducibility is the point of writing the
        queries into the build log at all.
        """
        return sorted(self.unmet, key=lambda c: (-c.shortfall, c.concept))[:n]

    def thinnest(self, n: int) -> list[ConceptCoverage]:
        """The ``n`` concepts with the least depth, whether or not they are met.

        What a guaranteed round searches for once every target is met: concepts
        with no primary source first, then the fewest counting sources. Without
        it a round that must run would have nothing to ask about.
        """
        return sorted(self.concepts, key=_thinness)[:n]

    def weakest_by_facet(self, n: int) -> list[ConceptCoverage]:
        """Unmet concepts, one facet at a time: each facet's largest shortfall in turn.

        Shortfall is a per-concept number, so when a corpus is heavy in one area
        the concepts furthest from target were often that area's neighbours: a
        live Thomism round searched four concepts of one facet, two of them
        already the corpus's largest shares. Facets are cycled in order of how
        many unmet concepts they hold, ties in the plan's order.
        """
        groups = [
            sorted((c for c in group if not c.met), key=lambda c: (-c.shortfall, c.concept))
            for group in self._facet_groups()
        ]
        groups = sorted((g for g in groups if g), key=len, reverse=True)
        return _round_robin(groups, n)

    def thinnest_by_facet(self, n: int) -> list[ConceptCoverage]:
        """The least-deep concepts, one facet at a time, thinnest facet first."""
        groups = [sorted(group, key=_thinness) for group in self._facet_groups()]
        groups = sorted((g for g in groups if g), key=lambda g: _thinness(g[0]))
        return _round_robin(groups, n)

    def _facet_groups(self) -> list[list[ConceptCoverage]]:
        """Concepts grouped by facet, in the plan's order; one group without facets."""
        by_name = {c.concept: c for c in self.concepts}
        groups: list[list[ConceptCoverage]] = []
        placed: set[str] = set()
        for facet in self.facets:
            group = [by_name[c] for c in facet.concepts if c in by_name and c not in placed]
            placed.update(c.concept for c in group)
            if group:
                groups.append(group)
        rest = [c for c in self.concepts if c.concept not in placed]
        if rest:
            groups.append(rest)
        return groups

    def as_dict(self) -> dict:
        return {
            "target": self.target.as_dict(),
            "met": self.met,
            "concepts": [c.as_dict() for c in self.concepts],
            "facets": [f.as_dict() for f in self.facets],
        }

    def counts(self) -> dict[str, int]:
        """Legacy shape: concept → accepted source count."""
        return {c.concept: c.sources for c in self.concepts}


def _thinness(c: ConceptCoverage) -> tuple:
    return (c.has_primary, c.sources, c.concept)


def _round_robin(groups: list[list[ConceptCoverage]], n: int) -> list[ConceptCoverage]:
    picked: list[ConceptCoverage] = []
    depth = 0
    while len(picked) < n and any(depth < len(g) for g in groups):
        for group in groups:
            if depth < len(group) and len(picked) < n:
                picked.append(group[depth])
        depth += 1
    return picked


@dataclass
class _Tally:
    sources: int = 0
    primary: int = 0
    # Primary sources that set the concept out, as opposed to treating it.
    primary_sets_out: int = 0
    abstract_only: int = 0
    types: set[SourceType] = field(default_factory=set)
    tiers: set[str] = field(default_factory=set)
    depths: dict[str, int] = field(default_factory=dict)


def compute_coverage(
    key_concepts: list[str],
    passed: list[ValidatedSource],
    target: CoverageTarget,
    facets: list[dict] | None = None,
    named_texts: dict[str, str] | None = None,
) -> CoverageReport:
    """Measure the accepted corpus against the target, concept by concept.

    ``facets`` is the plan's ``[{name, concepts}]``; ``named_texts`` maps a
    concept to the status of its named primary text (``found`` / ``partial`` /
    ``missing``; absent means ``none_named``). Both are optional so a build
    planned before either existed is measured as it was.
    """
    tallies: dict[str, _Tally] = {c: _Tally() for c in key_concepts}
    for source in passed:
        for concept, depth in counting_tags(source):
            tally = tallies.get(concept)
            if tally is None:
                continue
            if source.substance in NON_COUNTING_SUBSTANCE:
                tally.abstract_only += 1
                continue
            tally.sources += 1
            tally.depths[depth] = tally.depths.get(depth, 0) + 1
            if source.source_tier == "primary":
                tally.primary += 1
                if depth == DEPTH_SETS_OUT:
                    tally.primary_sets_out += 1
            tally.types.add(source.source_type)
            if source.source_tier:
                tally.tiers.add(source.source_tier)

    named_texts = named_texts or {}
    concepts = tuple(
        _score(concept, tallies[concept], target, named_texts.get(concept, NAMED_NONE))
        for concept in key_concepts
    )
    by_name = {c.concept: c for c in concepts}
    facet_reports = tuple(
        FacetCoverage(
            name=str(facet.get("name") or ""),
            concepts=tuple(members),
            met=all(by_name[c].met for c in members),
            primary=any(by_name[c].has_primary for c in members),
        )
        for facet in facets or []
        if (members := [c for c in facet.get("concepts") or [] if c in by_name])
    )
    return CoverageReport(target=target, concepts=concepts, facets=facet_reports)


def has_primary(tally_primary: int, primary_sets_out: int, named_text: str) -> bool:
    """Whether a concept has its primary source, by the named-text gate (4.C).

    - Its named text is in the corpus, whole, cut to its sections, or in part:
      yes — that is the primary source the plan asked for.
    - Its named text is missing: only a primary source that *sets the concept
      out* stands in for it. A primary text that merely treats the concept does
      not — which is natural law on expert 60 exactly: two primary sources tagged
      with it, and the treatise on law nowhere in the corpus.
    - No text was named: any primary source tagged with the concept, as before.
      There is nothing to gate on, and demanding ``sets_out`` there would re-grade
      topics whose primary material is many papers rather than one named work.
    """
    if named_text in (NAMED_FOUND, NAMED_PARTIAL):
        return True
    if named_text == NAMED_MISSING:
        return primary_sets_out > 0
    return tally_primary > 0


def _score(
    concept: str, tally: _Tally, target: CoverageTarget, named_text: str = NAMED_NONE
) -> ConceptCoverage:
    missing_sources = max(0, target.min_sources - tally.sources)
    missing_types = max(0, target.min_source_types - len(tally.types))
    missing_tier = (
        1
        if target.require_non_tertiary and not (tally.tiers & NON_TERTIARY)
        else 0
    )
    primary_met = has_primary(tally.primary, tally.primary_sets_out, named_text)
    missing_primary = 1 if target.require_primary and not primary_met else 0
    # Weighted so "no sources at all" always outranks "has sources, wrong mix".
    # A concept with nothing is a hole in the syllabus; one with two blog posts
    # is a weakness, and the loop should close holes first. A missing primary
    # source sits between the two: it is a gap in depth, not in breadth.
    shortfall = (
        missing_sources * 10 + missing_primary * 5 + missing_types * 3 + missing_tier * 2
    )
    return ConceptCoverage(
        concept=concept,
        sources=tally.sources,
        source_types=frozenset(tally.types),
        tiers=frozenset(tally.tiers),
        met=shortfall == 0,
        shortfall=shortfall,
        primary=tally.primary,
        abstract_only=tally.abstract_only,
        named_text=named_text,
        depth_counts=dict(tally.depths),
        has_primary=primary_met,
    )
