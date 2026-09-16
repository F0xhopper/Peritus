"""Unit tests for the research-brief planning, weighted discovery and coverage helpers."""

from unittest.mock import patch

from peritus.experts.build.constants import (
    _MAX_QUERIES_PER_FETCHER,
    _MIN_RESULTS_PER_QUERY,
)
from peritus.experts.build.planning import (
    _normalise_plan,
    _route_must_have_works,
)
from peritus.experts.builder import (
    ExpertBuilder,
    _search_breadth,
    _type_caps,
)
from peritus.experts.coverage import CoverageTarget, compute_coverage
from peritus.sources.domain import RawSource, SourceType, ValidatedSource
from peritus.sources.fetchers.gutenberg import _title_matches
from peritus.sources.fetchers.thought_leaders import _mentions_leader
from peritus.sources.validator import _match_concepts


def _validated(covered: list[str]) -> ValidatedSource:
    raw = RawSource(
        source_type=SourceType.WEB,
        url="https://x.test",
        title="t",
        author=None,
        text="",
    )
    return ValidatedSource(
        raw=raw,
        quality_score=7.0,
        relevance_score=7.0,
        content_type="reference",
        difficulty=2,
        key_claims=[],
        covered_concepts=covered,
    )


# ── plan normalisation ────────────────────────────────────────────────────────


def test_normalise_plan_fills_defaults_for_missing_fetchers():
    plan = _normalise_plan({}, "stoicism")
    assert set(plan["fetcher_plans"]) == {
        "wikipedia",
        "gutenberg",
        "arxiv",
        "pdf",
        "youtube",
        "exa",
        "web",
        "reddit",
        "thought_leaders",
        "pubmed",
        "openalex",
    }
    for fetcher_plan in plan["fetcher_plans"].values():
        assert fetcher_plan["queries"] == ["stoicism"]
        assert fetcher_plan["weight"] == 1.0
    assert plan["key_concepts"] == []
    assert plan["must_have_works"] == []


def test_normalise_plan_clamps_weights_and_dedupes_queries():
    plan = _normalise_plan(
        {
            "fetcher_plans": {
                "exa": {"queries": ["a", "A ", "b", "c", "d"], "weight": 9},
                "reddit": {"queries": ["x"], "weight": -3},
                "web": {"queries": [], "weight": "not-a-number"},
            },
            "key_concepts": ["virtue", "  ", "logos", 42],
            "must_have_works": [
                {"title": "Meditations", "author": "Marcus Aurelius"},
                {"title": "  "},
                "not-a-dict",
            ],
        },
        "stoicism",
    )

    exa = plan["fetcher_plans"]["exa"]
    assert exa["queries"] == ["a", "b", "c"][:_MAX_QUERIES_PER_FETCHER]
    assert exa["weight"] == 2.0
    assert plan["fetcher_plans"]["reddit"]["weight"] == 0.0
    assert plan["fetcher_plans"]["web"] == {"queries": ["stoicism"], "weight": 1.0}
    assert plan["key_concepts"] == ["virtue", "logos"]
    assert plan["must_have_works"] == [
        {
            "title": "Meditations",
            "author": "Marcus Aurelius",
            # Absent from the model's output → the safe reading: a book, not
            # known to be public domain, no sections singled out.
            "kind": "book",
            "public_domain": False,
            "sections": "",
            "open_text": False,
        },
    ]
    # A model that ignores facets gets one facet named after the topic.
    assert plan["facets"] == [{"name": "stoicism", "concepts": ["virtue", "logos"]}]


def test_route_must_have_works_appends_quoted_queries():
    plan = _normalise_plan(
        {
            "fetcher_plans": {"web": {"queries": ["stoicism basics"], "weight": 0}},
            "key_concepts": [],
            "must_have_works": [{"title": "Meditations", "author": "Marcus Aurelius"}],
        },
        "stoicism",
    )

    # `_route_must_have_works` reads `settings` from its own module, so that is
    # where the substitution has to happen.
    with patch("peritus.experts.build.planning.settings") as mock_settings:
        mock_settings.EXA_API_KEY = ""
        _route_must_have_works(plan)

    web = plan["fetcher_plans"]["web"]
    assert '"Meditations" Marcus Aurelius' in web["queries"]
    # Hosting must-have queries revives a zero-weighted fetcher.
    assert web["weight"] == 1.0


# ── weighted fetcher build ────────────────────────────────────────────────────


def test_build_fetchers_zero_weight_skips_fetcher():
    builder = ExpertBuilder.__new__(ExpertBuilder)
    fetchers = builder._build_fetchers(1.0, None, weights={"gutenberg": 0.0})
    assert "gutenberg" not in fetchers
    assert "wikipedia" in fetchers


def test_build_fetchers_weight_scales_quota():
    builder = ExpertBuilder.__new__(ExpertBuilder)
    fetchers = builder._build_fetchers(1.0, None, weights={"exa": 2.0})
    _, exa_quota = fetchers["exa"]
    assert exa_quota == 10  # base 5 × weight 2


def test_build_fetchers_source_filter_overrides_zero_weight():
    builder = ExpertBuilder.__new__(ExpertBuilder)
    fetchers = builder._build_fetchers(
        1.0,
        ["gutenberg"],
        weights={"gutenberg": 0.0},
    )
    assert list(fetchers) == ["gutenberg"]
    _, quota = fetchers["gutenberg"]
    assert quota == 4  # weight floored to 1 for explicitly requested fetchers


# ── search breadth ────────────────────────────────────────────────────────────


def test_search_breadth_floors_small_quotas():
    # A lite-tier quota of 1 across 3 queries used to mean 1 result per query;
    # the floor keeps the triage pool wide regardless of tier.
    assert _search_breadth(1, 3) == _MIN_RESULTS_PER_QUERY
    assert _search_breadth(2, 1) == _MIN_RESULTS_PER_QUERY


def test_search_breadth_scales_with_quota():
    # Overfetch still scales for big quotas: 20 × 3 ÷ 2 queries = 30 per query.
    assert _search_breadth(20, 2) == 30


def test_search_breadth_tolerates_zero_queries():
    assert _search_breadth(5, 0) == max(_MIN_RESULTS_PER_QUERY, 15)


# ── coverage ──────────────────────────────────────────────────────────────────

_TARGET = CoverageTarget(
    min_sources=1, min_source_types=1, require_non_tertiary=False, max_rounds=1
)


def test_compute_coverage_counts_only_known_concepts():
    passed = [
        _validated(["virtue", "logos"]),
        _validated(["virtue"]),
        _validated(["hallucinated concept"]),
    ]
    coverage = compute_coverage(["virtue", "logos", "apatheia"], passed, _TARGET).counts()
    assert coverage == {"virtue": 2, "logos": 1, "apatheia": 0}


def test_match_concepts_normalises_case_and_rejects_inventions():
    canonical = ["Virtue Ethics", "Logos"]
    matched = _match_concepts(
        [" virtue ethics ", "LOGOS", "logos", "made-up", 42, None],
        canonical,
    )
    # Bare strings are the pre-graded shape, and read as `treats`.
    assert matched == {"Virtue Ethics": "treats", "Logos": "treats"}


def test_match_concepts_empty_inputs():
    assert _match_concepts([], ["a"]) == {}
    assert _match_concepts(None, ["a"]) == {}
    assert _match_concepts(["a"], []) == {}


# ── gutenberg title matching ──────────────────────────────────────────────────


def test_title_matches_exact_and_subtitle():
    assert _title_matches("Meditations", "Meditations")
    assert _title_matches("Meditations", "The Meditations of Marcus Aurelius")
    assert _title_matches(
        "The Origin of Species",
        "On the Origin of Species by Means of Natural Selection",
    )


def test_title_matches_rejects_different_book_by_same_author():
    assert not _title_matches("Meditations", "A Treatise of Human Nature")
    assert not _title_matches("The Republic", "Symposium")


# ── thought-leader mention filter ─────────────────────────────────────────────


def test_mentions_leader_found_in_title_or_text():
    assert _mentions_leader("Marcus Aurelius", "Aurelius on virtue", "some text")
    assert _mentions_leader("Marcus Aurelius", "On virtue", "as aurelius wrote…")
    assert not _mentions_leader("Marcus Aurelius", "On virtue", "unrelated page")


def test_mentions_leader_short_surname_passes_through():
    # Too short to test meaningfully — defer to the validator.
    assert _mentions_leader("Xi", "anything", "anything")


# ── per-type caps ────────────────────────────────────────────────────────────
#
# The cap's job is to stop one source type dominating the corpus. It is NOT
# meant to decide how large the corpus is — that is the discovery budget's job,
# and a cap that does not scale with the budget silently takes the decision
# away from it. On a live STANDARD build four of six productive types capped out
# at 43 sources while the count ceiling (60) and the money ($1.58 of $3.00) were
# both untouched.


def _fetchers(**weights):
    from peritus.experts.builder import ExpertBuilder

    return ExpertBuilder.__new__(ExpertBuilder)._build_fetchers(1.0, None, weights)


def test_caps_shape_the_mix_and_never_the_size():
    """Summing to more than the budget is the property that matters: the caps
    can constrain what the corpus is made of, and can never be what stops it
    growing."""
    for budget in (15, 30, 60, 120):
        caps = _type_caps(_fetchers(), budget)
        assert sum(caps.values()) > budget


def test_a_cap_scales_with_the_budget():
    small = _type_caps(_fetchers(), 30)
    large = _type_caps(_fetchers(), 120)
    assert all(large[t] > small[t] for t in small), (
        "a fixed cap becomes the real limit as soon as the budget grows past it"
    )


def test_a_heavily_weighted_fetcher_gets_a_larger_share():
    """The plan's weights decide how much of the search each type gets; the cap
    follows the same weighting rather than contradicting it."""
    caps = _type_caps(_fetchers(openalex=2.0), 60)
    assert caps[SourceType.OPENALEX] > caps[SourceType.WIKIPEDIA]


def test_no_type_may_take_the_whole_corpus():
    caps = _type_caps(_fetchers(), 60)
    assert all(cap < 60 for cap in caps.values())


def test_a_small_build_still_lets_a_small_fetcher_contribute():
    """Without a floor, a low-quota fetcher on a lite build is capped at one or
    two sources, which is indistinguishable from switching it off."""
    caps = _type_caps(_fetchers(), 15)
    assert min(caps.values()) >= 4
