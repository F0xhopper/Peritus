"""Unit tests for the research-brief planning, weighted discovery and coverage helpers."""

from unittest.mock import patch

from peritus.experts.builder import (
    _MAX_QUERIES_PER_FETCHER,
    ExpertBuilder,
    _compute_coverage,
    _normalise_plan,
    _route_must_have_works,
)
from peritus.sources.domain import RawSource, SourceType, ValidatedSource
from peritus.sources.fetchers.gutenberg import _title_matches
from peritus.sources.fetchers.thought_leaders import _mentions_leader
from peritus.sources.validator import _match_concepts


def _validated(covered: list[str]) -> ValidatedSource:
    raw = RawSource(
        source_type=SourceType.WEB, url="https://x.test", title="t",
        author=None, text="",
    )
    return ValidatedSource(
        raw=raw, quality_score=7.0, relevance_score=7.0,
        content_type="reference", difficulty=2, key_claims=[],
        covered_concepts=covered,
    )


# ── plan normalisation ────────────────────────────────────────────────────────

def test_normalise_plan_fills_defaults_for_missing_fetchers():
    plan = _normalise_plan({}, "stoicism")
    assert set(plan["fetcher_plans"]) == {
        "wikipedia", "gutenberg", "arxiv", "pdf",
        "youtube", "exa", "web", "reddit", "thought_leaders",
    }
    for fetcher_plan in plan["fetcher_plans"].values():
        assert fetcher_plan["queries"] == ["stoicism"]
        assert fetcher_plan["weight"] == 1.0
    assert plan["key_concepts"] == []
    assert plan["must_have_works"] == []


def test_normalise_plan_clamps_weights_and_dedupes_queries():
    plan = _normalise_plan({
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
    }, "stoicism")

    exa = plan["fetcher_plans"]["exa"]
    assert exa["queries"] == ["a", "b", "c"][:_MAX_QUERIES_PER_FETCHER]
    assert exa["weight"] == 2.0
    assert plan["fetcher_plans"]["reddit"]["weight"] == 0.0
    assert plan["fetcher_plans"]["web"] == {"queries": ["stoicism"], "weight": 1.0}
    assert plan["key_concepts"] == ["virtue", "logos"]
    assert plan["must_have_works"] == [
        {"title": "Meditations", "author": "Marcus Aurelius"},
    ]


def test_route_must_have_works_appends_quoted_queries():
    plan = _normalise_plan({
        "fetcher_plans": {"web": {"queries": ["stoicism basics"], "weight": 0}},
        "key_concepts": [],
        "must_have_works": [{"title": "Meditations", "author": "Marcus Aurelius"}],
    }, "stoicism")

    with patch("peritus.experts.builder.settings") as mock_settings:
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
        1.0, ["gutenberg"], weights={"gutenberg": 0.0},
    )
    assert list(fetchers) == ["gutenberg"]
    _, quota = fetchers["gutenberg"]
    assert quota == 4  # weight floored to 1 for explicitly requested fetchers


# ── coverage ──────────────────────────────────────────────────────────────────

def test_compute_coverage_counts_only_known_concepts():
    passed = [
        _validated(["virtue", "logos"]),
        _validated(["virtue"]),
        _validated(["hallucinated concept"]),
    ]
    coverage = _compute_coverage(["virtue", "logos", "apatheia"], passed)
    assert coverage == {"virtue": 2, "logos": 1, "apatheia": 0}


def test_match_concepts_normalises_case_and_rejects_inventions():
    canonical = ["Virtue Ethics", "Logos"]
    matched = _match_concepts(
        [" virtue ethics ", "LOGOS", "logos", "made-up", 42, None],
        canonical,
    )
    assert matched == ["Virtue Ethics", "Logos"]


def test_match_concepts_empty_inputs():
    assert _match_concepts([], ["a"]) == []
    assert _match_concepts(None, ["a"]) == []
    assert _match_concepts(["a"], []) == []


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
