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

from peritus.sources.domain import SourceType, ValidatedSource

# Tiers that count as evidence rather than restatement. A concept whose only
# support is tertiary is covered by material *about* the subject, which is the
# corpus failure the source-tier rubric exists to detect.
NON_TERTIARY: frozenset[str] = frozenset({"primary", "secondary"})


@dataclass(frozen=True)
class CoverageTarget:
    """What a tier requires before it considers a concept covered."""

    min_sources: int
    min_source_types: int
    require_non_tertiary: bool
    # Discovery rounds *after* the first. 1 keeps today's shape: round 0, then
    # one targeted round for whatever it missed.
    max_rounds: int

    def as_dict(self) -> dict:
        return {
            "min_sources": self.min_sources,
            "min_source_types": self.min_source_types,
            "require_non_tertiary": self.require_non_tertiary,
            "max_rounds": self.max_rounds,
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

    def as_dict(self) -> dict:
        return {
            "concept": self.concept,
            "sources": self.sources,
            "source_types": sorted(t.value for t in self.source_types),
            "tiers": sorted(self.tiers),
            "met": self.met,
            "shortfall": self.shortfall,
        }


@dataclass(frozen=True)
class CoverageReport:
    target: CoverageTarget
    concepts: tuple[ConceptCoverage, ...] = ()

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

    def as_dict(self) -> dict:
        return {
            "target": self.target.as_dict(),
            "met": self.met,
            "concepts": [c.as_dict() for c in self.concepts],
        }

    def counts(self) -> dict[str, int]:
        """Legacy shape: concept → accepted source count."""
        return {c.concept: c.sources for c in self.concepts}


@dataclass
class _Tally:
    sources: int = 0
    types: set[SourceType] = field(default_factory=set)
    tiers: set[str] = field(default_factory=set)


def compute_coverage(
    key_concepts: list[str],
    passed: list[ValidatedSource],
    target: CoverageTarget,
) -> CoverageReport:
    """Measure the accepted corpus against the target, concept by concept."""
    tallies: dict[str, _Tally] = {c: _Tally() for c in key_concepts}
    for source in passed:
        for concept in source.covered_concepts:
            tally = tallies.get(concept)
            if tally is None:
                continue
            tally.sources += 1
            tally.types.add(source.source_type)
            if source.source_tier:
                tally.tiers.add(source.source_tier)

    concepts = tuple(
        _score(concept, tallies[concept], target) for concept in key_concepts
    )
    return CoverageReport(target=target, concepts=concepts)


def _score(concept: str, tally: _Tally, target: CoverageTarget) -> ConceptCoverage:
    missing_sources = max(0, target.min_sources - tally.sources)
    missing_types = max(0, target.min_source_types - len(tally.types))
    missing_tier = (
        1
        if target.require_non_tertiary and not (tally.tiers & NON_TERTIARY)
        else 0
    )
    # Weighted so "no sources at all" always outranks "has sources, wrong mix".
    # A concept with nothing is a hole in the syllabus; one with two blog posts
    # is a weakness, and the loop should close holes first.
    shortfall = missing_sources * 10 + missing_types * 3 + missing_tier * 2
    return ConceptCoverage(
        concept=concept,
        sources=tally.sources,
        source_types=frozenset(tally.types),
        tiers=frozenset(tally.tiers),
        met=shortfall == 0,
        shortfall=shortfall,
    )
