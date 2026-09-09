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
    assert ExpertConfig.from_tier(ExpertTier.LITE).coverage_target() == _LITE
    assert ExpertConfig.from_tier(ExpertTier.STANDARD).coverage_target() == _STANDARD
    pro = ExpertConfig.from_tier(ExpertTier.PRO).coverage_target()
    assert (pro.min_sources, pro.max_rounds) == (3, 3)


def test_report_serialises_for_the_event_log():
    report = compute_coverage(["analogy"], [_source(["analogy"])], _STANDARD)
    payload = report.as_dict()
    assert payload["target"]["min_sources"] == 2
    assert payload["concepts"][0]["source_types"] == ["web"]
    assert payload["concepts"][0]["met"] is False
