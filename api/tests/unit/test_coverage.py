"""Coverage targets — what "this concept is covered" means at each tier.

Coverage used to be a boolean at zero sources, which cannot tell a concept
resting on one blog post from one resting on three papers and a primary text.
These tests pin the difference, and the ordering the discovery loop searches in.
"""

from peritus.experts.coverage import CoverageTarget, compute_coverage
from peritus.experts.domain import ExpertConfig, ExpertTier
from peritus.sources.domain import RawSource, SourceType, ValidatedSource

_LITE = CoverageTarget(
    min_sources=1, min_source_types=1, require_non_tertiary=False, max_rounds=1
)
_STANDARD = CoverageTarget(
    min_sources=2, min_source_types=2, require_non_tertiary=True, max_rounds=2
)


def _source(
    concepts: list[str],
    source_type: SourceType = SourceType.WEB,
    tier: str | None = "secondary",
) -> ValidatedSource:
    return ValidatedSource(
        raw=RawSource(source_type, "https://x.test", "T", None, "text"),
        quality_score=7.0,
        relevance_score=7.0,
        content_type="paper",
        difficulty=3,
        key_claims=[],
        covered_concepts=concepts,
        source_tier=tier,
    )


def test_a_concept_with_nothing_is_never_met():
    report = compute_coverage(["analogy", "participation"], [], _LITE)
    assert not report.met
    assert report.uncovered == ("analogy", "participation")


def test_lite_is_satisfied_by_one_source_of_any_kind():
    """LITE must keep its old behaviour exactly — its cost profile depends on it."""
    report = compute_coverage(["analogy"], [_source(["analogy"], tier="tertiary")], _LITE)
    assert report.met


def test_standard_wants_breadth_and_at_least_one_non_tertiary_source():
    concepts = ["analogy"]

    two_of_a_kind = [_source(["analogy"]), _source(["analogy"])]
    assert not compute_coverage(concepts, two_of_a_kind, _STANDARD).met, (
        "two sources of one type is not two source types"
    )

    all_tertiary = [
        _source(["analogy"], SourceType.WEB, "tertiary"),
        _source(["analogy"], SourceType.WIKIPEDIA, "tertiary"),
    ]
    assert not compute_coverage(concepts, all_tertiary, _STANDARD).met, (
        "a concept supported only by summaries is covered second-hand"
    )

    mixed = [
        _source(["analogy"], SourceType.WEB, "tertiary"),
        _source(["analogy"], SourceType.OPENALEX, "primary"),
    ]
    assert compute_coverage(concepts, mixed, _STANDARD).met


def test_unknown_concepts_reported_by_a_source_are_ignored():
    """Only the plan's own concepts count. A validator that invents a tag must
    not be able to declare a concept covered that nobody asked for."""
    report = compute_coverage(
        ["analogy"], [_source(["analogy", "something else entirely"])], _LITE
    )
    assert report.counts() == {"analogy": 1}


def test_weakest_orders_holes_before_weaknesses():
    """A concept with nothing is a hole in the syllabus; one with two blog posts
    is a weakness. The loop has a round to spend and should close holes first."""
    passed = [
        _source(["analogy"], SourceType.WEB, "tertiary"),
        _source(["analogy"], SourceType.WIKIPEDIA, "tertiary"),
        _source(["esse"], SourceType.OPENALEX, "primary"),
        _source(["esse"], SourceType.ARXIV, "primary"),
    ]
    report = compute_coverage(["analogy", "esse", "participation"], passed, _STANDARD)

    assert report.counts()["esse"] == 2
    weakest = [c.concept for c in report.weakest(3)]
    assert weakest[0] == "participation", "the empty concept comes first"
    assert weakest[1] == "analogy", "covered but all-tertiary comes next"
    assert "esse" not in weakest, "a met concept is never re-searched"


def test_weakest_is_stable_for_equal_shortfalls():
    """A loop whose queries depend on dict ordering is not reproducible, and
    reproducibility is the point of writing the queries into the build log."""
    report = compute_coverage(["zeta", "alpha", "mu"], [], _STANDARD)
    assert [c.concept for c in report.weakest(3)] == ["alpha", "mu", "zeta"]


def test_no_concepts_is_vacuously_met():
    """A plan with no concepts has nothing to fail, and the loop's stop
    condition guards separately against treating that as success."""
    assert compute_coverage([], [], _STANDARD).met


def test_every_tier_config_produces_its_documented_target():
    """The table in docs/plans/source-selection.md §9 (5.A)."""
    assert ExpertConfig.from_tier(ExpertTier.LITE).coverage_target() == _LITE
    std = ExpertConfig.from_tier(ExpertTier.STANDARD).coverage_target()
    assert std == CoverageTarget(
        min_sources=3, min_source_types=2, require_non_tertiary=True,
        max_rounds=2, require_primary=True, min_rounds=1,
    )
    pro = ExpertConfig.from_tier(ExpertTier.PRO).coverage_target()
    assert (pro.min_sources, pro.max_rounds, pro.require_primary, pro.min_rounds) == (
        4, 3, True, 1,
    )


def test_a_config_snapshotted_before_depth_targets_is_not_regraded():
    """Rows written before require_primary/min_rounds existed deserialise to the
    old behaviour, not the new tier defaults."""
    import dataclasses

    old = dataclasses.asdict(ExpertConfig.from_tier(ExpertTier.STANDARD))
    old.pop("coverage_require_primary")
    old.pop("discovery_min_rounds")
    target = ExpertConfig(**old).coverage_target()
    assert target.require_primary is False
    assert target.min_rounds == 0


_DEEP = CoverageTarget(
    min_sources=1, min_source_types=1, require_non_tertiary=False,
    max_rounds=2, require_primary=True,
)


def test_a_concept_without_a_primary_source_is_not_met_when_depth_is_required():
    report = compute_coverage(["metaphysics"], [_source(["metaphysics"])], _DEEP)
    assert not report.met
    concept = report.concepts[0]
    assert concept.primary == 0
    assert concept.shortfall == 5

    report = compute_coverage(
        ["metaphysics"], [_source(["metaphysics"], tier="primary")], _DEEP
    )
    assert report.met


def test_missing_primary_ranks_between_a_hole_and_a_wrong_mix():
    target = CoverageTarget(
        min_sources=1, min_source_types=2, require_non_tertiary=False,
        max_rounds=2, require_primary=True,
    )
    report = compute_coverage(
        ["hole", "no-primary", "one-type"],
        [
            _source(["no-primary"], SourceType.WEB),
            _source(["no-primary"], SourceType.ARXIV),
            _source(["one-type"], SourceType.WEB, tier="primary"),
        ],
        target,
    )
    shortfalls = {c.concept: c.shortfall for c in report.concepts}
    assert shortfalls["hole"] > shortfalls["no-primary"] > shortfalls["one-type"]


def test_abstract_only_sources_never_count_toward_coverage():
    """A catalogue record with a blurb can say a concept is covered and cannot
    teach it — twelve of those let the Thomism loop stop after round 0."""
    stub = _source(["analogy"], tier="primary")
    stub.substance = "abstract"
    report = compute_coverage(["analogy"], [stub], _LITE)
    assert not report.met
    assert report.concepts[0].sources == 0
    assert report.concepts[0].abstract_only == 1


def test_thinnest_orders_by_missing_primary_then_fewest_sources():
    report = compute_coverage(
        ["a", "b", "c"],
        [
            _source(["a"], tier="primary"),
            _source(["b"]),
            _source(["b"]),
            _source(["c"]),
        ],
        _LITE,
    )
    assert report.met, "every concept is met, so weakest() has nothing to offer"
    assert report.weakest(3) == []
    assert [c.concept for c in report.thinnest(3)] == ["c", "b", "a"]


def test_report_serialises_for_the_event_log():
    report = compute_coverage(["analogy"], [_source(["analogy"])], _STANDARD)
    payload = report.as_dict()
    assert payload["target"]["min_sources"] == 2
    assert payload["concepts"][0]["source_types"] == ["web"]
    assert payload["concepts"][0]["met"] is False
