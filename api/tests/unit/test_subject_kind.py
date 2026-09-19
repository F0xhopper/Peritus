"""The subject's kind, and what it changes (docs/plans/beating-closed-book.md, 3.5).

Expert 41 (Beekeeping) was two virology papers (61% of its chunks), Langstroth's
manual of 1853 and old editions of the ABC and XYZ, and it lost every how-to
question to a closed-book model. These tests pin the four levers the plan's
``subject_kind`` pulls — the plan field, the triage recency prior, the
current-material coverage target and the narrow-paper share cap — and, above
all, that a canon (the default, and every plan written before the field) is
built exactly as it was.
"""

from typing import Any
from unittest.mock import patch

import pytest

from peritus.experts.build.planning import _normalise_plan, _plan_tool
from peritus.experts.composition import (
    NARROW_SOURCE_MIN_CHARS,
    cap_narrow_source_shares,
    corpus_composition,
)
from peritus.experts.coverage import CoverageTarget, compute_coverage
from peritus.experts.domain import ExpertConfig, ExpertTier
from peritus.experts.feedback import weak_concepts_block
from peritus.sources import triage as triage_module
from peritus.sources.domain import RawSource, SourceCandidate, SourceType, ValidatedSource
from peritus.sources.subject import (
    SUBJECT_CANON,
    SUBJECT_PRACTICE,
    SUBJECT_RESEARCH_FRONT,
    is_current_material,
    is_narrow_paper,
    normalise_subject_kind,
    publication_year,
    recency_adjustment,
    subject_kind_of,
)
from peritus.sources.triage import triage_candidates
from tests.conftest import tool_use_response

TODAY = 2026


def _source(
    title: str = "T",
    source_type: SourceType = SourceType.WEB,
    content_type: str = "tutorial",
    concepts: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    chars: int = 1_000,
    tier: str = "secondary",
) -> ValidatedSource:
    return ValidatedSource(
        raw=RawSource(
            source_type,
            f"https://x.test/{title}",
            title,
            None,
            ("word " * (chars // 5))[:chars],
            dict(metadata or {}),
        ),
        quality_score=7.0,
        relevance_score=7.0,
        content_type=content_type,
        difficulty=3,
        key_claims=[],
        covered_concepts=concepts or [],
        source_tier=tier,
    )


# ── the plan field ───────────────────────────────────────────────────────────


def test_the_plan_tool_asks_for_the_kind_and_names_all_three():
    schema = _plan_tool(8)["input_schema"]
    assert "subject_kind" in schema["required"]
    assert schema["properties"]["subject_kind"]["enum"] == [
        SUBJECT_CANON,
        SUBJECT_PRACTICE,
        SUBJECT_RESEARCH_FRONT,
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({}, SUBJECT_CANON),
        ({"subject_kind": "practice"}, SUBJECT_PRACTICE),
        ({"subject_kind": " Research_Front "}, SUBJECT_RESEARCH_FRONT),
        ({"subject_kind": "craft"}, SUBJECT_CANON),
        ({"subject_kind": 3}, SUBJECT_CANON),
    ],
)
def test_a_missing_or_invalid_kind_is_a_canon(raw, expected):
    """Canon is today's behaviour: a failed field, or a failed plan, changes nothing."""
    assert _normalise_plan(raw, "Beekeeping")["subject_kind"] == expected


def test_a_stored_plan_from_before_the_field_reads_as_canon():
    assert subject_kind_of({"key_concepts": ["x"]}) == SUBJECT_CANON
    assert subject_kind_of(None) == SUBJECT_CANON
    assert subject_kind_of({"subject_kind": "practice"}) == SUBJECT_PRACTICE
    assert normalise_subject_kind(None) == SUBJECT_CANON


# ── publication year ─────────────────────────────────────────────────────────


def test_the_year_is_read_where_a_fetcher_recorded_one_and_never_guessed():
    assert publication_year({"year": 2019}, TODAY) == 2019  # openalex, pubmed, pdf
    assert publication_year({"year": "2019"}, TODAY) == 2019
    assert publication_year({"published": "2021-03-04 00:00:00+00:00"}, TODAY) == 2021  # arxiv
    assert publication_year({}, TODAY) is None  # web, exa, gutenberg: nothing recorded
    assert publication_year({"year": None}, TODAY) is None
    assert publication_year({"year": True}, TODAY) is None
    assert publication_year({"year": 3020}, TODAY) is None


# ── triage ───────────────────────────────────────────────────────────────────


def test_a_canon_has_no_recency_prior():
    assert recency_adjustment(SourceType.GUTENBERG, {}, SUBJECT_CANON, TODAY) == 0.0
    assert recency_adjustment(SourceType.OPENALEX, {"year": 2025}, SUBJECT_CANON, TODAY) == 0.0


def test_the_recency_prior_is_modest_and_needs_evidence_of_age():
    # A Gutenberg text is public domain, so old, without a date.
    assert recency_adjustment(SourceType.GUTENBERG, {}, SUBJECT_PRACTICE, TODAY) == -1.0
    assert recency_adjustment(SourceType.OPENALEX, {"year": 1950}, SUBJECT_PRACTICE, TODAY) == -1.0
    # A recent paper is the front for a research front, less so for a practice.
    assert (
        recency_adjustment(SourceType.OPENALEX, {"year": 2022}, SUBJECT_RESEARCH_FRONT, TODAY)
        == 1.0
    )
    assert recency_adjustment(SourceType.OPENALEX, {"year": 2022}, SUBJECT_PRACTICE, TODAY) == 0.5
    # Middle-aged, or undated: no opinion.
    assert recency_adjustment(SourceType.OPENALEX, {"year": 2005}, SUBJECT_PRACTICE, TODAY) == 0.0
    assert recency_adjustment(SourceType.WEB, {}, SUBJECT_PRACTICE, TODAY) == 0.0


def _stub_triage(score: float, prompts: list[str]):
    async def _gather(params, live_concurrency=None, description="", on_result=None):
        responses = []
        for p in params:
            prompts.append(p["messages"][0]["content"])
            count = p["messages"][0]["content"].count("<candidate_")
            responses.append(
                tool_use_response(
                    {
                        "scores": [
                            {"id": f"candidate_{i}", "expected_value": score} for i in range(count)
                        ]
                    }
                )
            )
        return responses

    return patch.object(triage_module, "gather_claude_calls", _gather)


def _candidates() -> list[SourceCandidate]:
    return [
        SourceCandidate(
            SourceType.GUTENBERG,
            "https://www.gutenberg.org/ebooks/24583",
            "Langstroth on the Hive and the Honey-Bee",
            "L. L. Langstroth",
            "A bee keeper's manual",
        ),
        SourceCandidate(
            SourceType.WEB,
            "https://extension.example.test/varroa",
            "Varroa mite management for beekeepers",
            None,
            "Monitoring and treatment thresholds",
        ),
    ]


async def test_triage_for_a_canon_is_what_it_was():
    prompts: list[str] = []
    with _stub_triage(6.0, prompts):
        triaged = await triage_candidates("Beekeeping", ["varroa"], [], _candidates())
    assert [t.recency_adjustment for t in triaged] == [0.0, 0.0]
    assert triaged[1].score == 6.0
    assert "This subject is" not in prompts[0]


async def test_triage_for_a_practice_moves_old_material_down_without_dropping_it():
    prompts: list[str] = []
    with _stub_triage(6.0, prompts):
        triaged = await triage_candidates(
            "Beekeeping", ["varroa"], [], _candidates(), subject_kind=SUBJECT_PRACTICE
        )
    old, current = triaged
    assert old.recency_adjustment == -1.0
    assert old.score == old.model_score + old.domain_adjustment - 1.0
    assert current.score == 6.0
    assert "This subject is a practice" in prompts[0]
    # Reordered, not excluded: the manual still clears the junk floor.
    assert old in triage_module.rank_candidates(triaged)


async def test_a_named_work_is_lifted_past_the_recency_prior():
    prompts: list[str] = []
    with _stub_triage(4.0, prompts):
        triaged = await triage_candidates(
            "Beekeeping",
            [],
            ["Langstroth on the Hive and the Honey-Bee"],
            _candidates()[:1],
            subject_kind=SUBJECT_PRACTICE,
        )
    assert triaged[0].score >= 9.0


# ── what counts as current ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("source", "kind", "expected"),
    [
        # An extension leaflet, undated because the web records no date.
        (_source(content_type="tutorial"), SUBJECT_PRACTICE, True),
        (_source(source_type=SourceType.EXA, content_type="textbook"), SUBJECT_PRACTICE, True),
        # An essay or a forum thread or an encyclopedia is not practitioner guidance.
        (_source(content_type="opinion"), SUBJECT_PRACTICE, False),
        (_source(source_type=SourceType.REDDIT), SUBJECT_PRACTICE, False),
        (
            _source(source_type=SourceType.WIKIPEDIA, content_type="reference"),
            SUBJECT_PRACTICE,
            False,
        ),
        # Langstroth, 1853.
        (
            _source(source_type=SourceType.GUTENBERG, content_type="textbook"),
            SUBJECT_PRACTICE,
            False,
        ),
        # One recent virology paper: a finding, not practice — but it is the front.
        (
            _source("Deformed wing virus", SourceType.OPENALEX, "paper", metadata={"year": 2022}),
            SUBJECT_PRACTICE,
            False,
        ),
        (
            _source("Deformed wing virus", SourceType.OPENALEX, "paper", metadata={"year": 2022}),
            SUBJECT_RESEARCH_FRONT,
            True,
        ),
        # A recent review is current for either.
        (
            _source(
                "Varroa control: a review", SourceType.PUBMED, "paper", metadata={"year": 2021}
            ),
            SUBJECT_PRACTICE,
            True,
        ),
        (
            _source(
                "Colony losses",
                SourceType.OPENALEX,
                "paper",
                metadata={"year": 2023, "work_type": "review"},
            ),
            SUBJECT_PRACTICE,
            True,
        ),
        # An old review, or an undated paper, is not.
        (
            _source(
                "Varroa control: a review", SourceType.PUBMED, "paper", metadata={"year": 1999}
            ),
            SUBJECT_PRACTICE,
            False,
        ),
        (_source("A paper", SourceType.PDF, "paper"), SUBJECT_RESEARCH_FRONT, False),
        # Never, for a canon.
        (_source(content_type="tutorial"), SUBJECT_CANON, False),
    ],
)
def test_current_material_is_recognised_from_what_is_recorded(source, kind, expected):
    assert is_current_material(source, kind, TODAY) is expected


# ── coverage ─────────────────────────────────────────────────────────────────


def _expert_41(concept: str = "overwintering") -> list[ValidatedSource]:
    return [
        _source(
            "Langstroth on the Hive",
            SourceType.GUTENBERG,
            "textbook",
            [concept],
            tier="primary",
        ),
        _source(
            "Deformed wing virus in Apis mellifera",
            SourceType.OPENALEX,
            "paper",
            [concept],
            {"year": 2020},
            tier="primary",
        ),
    ]


def test_a_canon_target_is_unchanged():
    target = ExpertConfig.from_tier(ExpertTier.LITE).coverage_target()
    assert target.subject_kind == SUBJECT_CANON
    assert not target.require_current
    report = compute_coverage(["overwintering"], _expert_41(), target, today=TODAY)
    assert report.met
    assert report.concepts[0].current == 0
    assert not report.concepts[0].lacks_current


def test_a_practice_needs_current_material_per_concept():
    target = ExpertConfig.from_tier(ExpertTier.LITE).coverage_target(SUBJECT_PRACTICE)
    assert target.require_current
    report = compute_coverage(["overwintering"], _expert_41(), target, today=TODAY)
    assert not report.met, "an 1853 manual and a virology paper are not how it is done now"
    concept = report.concepts[0]
    assert concept.lacks_current and concept.current == 0
    assert concept.shortfall == 4

    guide = _source("Wintering your colony", SourceType.WEB, "tutorial", ["overwintering"])
    report = compute_coverage(["overwintering"], [*_expert_41(), guide], target, today=TODAY)
    assert report.met
    assert report.concepts[0].current == 1


def test_a_missing_current_source_ranks_below_a_missing_primary():
    target = CoverageTarget(
        min_sources=1,
        min_source_types=1,
        require_non_tertiary=False,
        max_rounds=1,
        require_primary=True,
        subject_kind=SUBJECT_PRACTICE,
    )
    no_primary = compute_coverage(
        ["a"], [_source(concepts=["a"], tier="secondary")], target, today=TODAY
    ).concepts[0]
    no_current = compute_coverage(["a"], _expert_41("a"), target, today=TODAY).concepts[0]
    assert no_primary.shortfall == 5 and no_current.shortfall == 4


def test_the_feedback_round_is_told_what_is_missing():
    target = ExpertConfig.from_tier(ExpertTier.LITE).coverage_target(SUBJECT_PRACTICE)
    report = compute_coverage(["overwintering"], _expert_41(), target, today=TODAY)
    block = weak_concepts_block(list(report.unmet))
    assert "current material: none" in block
    canon = compute_coverage(
        ["overwintering"],
        [],
        ExpertConfig.from_tier(ExpertTier.LITE).coverage_target(),
        today=TODAY,
    )
    assert "current material" not in weak_concepts_block(list(canon.unmet))


# ── the narrow-paper share cap ───────────────────────────────────────────────


def _beekeeping_corpus() -> list[ValidatedSource]:
    return [
        _source("DWV genomics", SourceType.OPENALEX, "paper", chars=300_000),
        _source("DWV transmission", SourceType.PUBMED, "paper", chars=250_000),
        _source("Langstroth on the Hive", SourceType.GUTENBERG, "textbook", chars=120_000),
        *[_source(f"Guide {i}", SourceType.WEB, "tutorial", chars=40_000) for i in range(6)],
    ]


def test_a_canon_is_never_cut():
    corpus = _beekeeping_corpus()
    assert cap_narrow_source_shares(corpus, SUBJECT_CANON) == []
    assert cap_narrow_source_shares(corpus) == []
    assert len(corpus[0].text) == 300_000


def test_no_narrow_paper_holds_more_than_its_share_of_a_practice():
    corpus = _beekeeping_corpus()
    cut = cap_narrow_source_shares(corpus, SUBJECT_PRACTICE)
    assert {c["title"] for c in cut} == {"DWV genomics", "DWV transmission"}
    total = sum(len(vs.text) for vs in corpus)
    for vs in corpus[:2]:
        assert len(vs.text) / total <= 0.10 + 1e-6
        assert vs.raw.metadata["share_capped"]["from_chars"] > len(vs.text)
        assert vs.raw.metadata["truncated"] is True
    # Cut, not dropped; nothing else touched.
    assert len(corpus) == 9
    assert len(corpus[2].text) == 120_000


def test_a_named_work_or_a_review_is_not_narrow():
    named = _source(
        "DWV genomics", SourceType.OPENALEX, "paper", metadata={"must_have_title": "DWV genomics"}
    )
    review = _source("Varroa and viruses: a review", SourceType.PUBMED, "paper")
    assert not is_narrow_paper(named)
    assert not is_narrow_paper(review)
    assert is_narrow_paper(_source("DWV transmission", SourceType.PUBMED, "paper"))


def test_the_cut_never_goes_below_the_floor():
    corpus = [_source(f"Paper {i}", SourceType.ARXIV, "paper", chars=100_000) for i in range(3)] + [
        _source("Guide", SourceType.WEB, "tutorial", chars=5_000)
    ]
    cap_narrow_source_shares(corpus, SUBJECT_RESEARCH_FRONT)
    assert all(len(vs.text) >= NARROW_SOURCE_MIN_CHARS - 5 for vs in corpus[:3])


def test_a_corpus_already_within_the_share_is_left_alone():
    corpus = [_source(f"Guide {i}", chars=10_000) for i in range(20)] + [
        _source("One paper", SourceType.OPENALEX, "paper", chars=20_000)
    ]
    assert cap_narrow_source_shares(corpus, SUBJECT_PRACTICE) == []


# ── the corpus summary ───────────────────────────────────────────────────────


def test_the_summary_names_the_kind_and_counts_current_material():
    passed = [*_expert_41(), _source("Wintering", concepts=["overwintering"])]
    canon = corpus_composition(passed, [], ["overwintering", "swarming"])
    assert canon["subject_kind"] == SUBJECT_CANON
    assert "current" not in canon

    practice = corpus_composition(
        passed, [], ["overwintering", "swarming"], subject_kind=SUBJECT_PRACTICE
    )
    assert practice["current"] == 1
    assert practice["current_share"] == round(1 / 3, 3)
    assert practice["concepts_without_current"] == ["swarming"]
