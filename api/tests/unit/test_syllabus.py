"""docs/plans/syllabus.md — the planner reads before planning, the syllabus has
facets, the tradition's voices are looked for, and tags cost something.

Each section is one phase of the plan. Everything is offline: no model, no
search API, no database.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from peritus.experts.builder import (
    ExpertBuilder,
    _boosted_must_have_titles,
    _enforce_ceiling,
    _normalise_plan,
)
from peritus.experts.composition import corpus_composition
from peritus.experts.coverage import CoverageTarget, compute_coverage
from peritus.experts.domain import ExpertConfig, ExpertTier
from peritus.sources.canonical import (
    EXTENT_WHOLE,
    NOT_OBTAINABLE,
    SCOPE_CONCEPT,
    SCOPE_FIGURE,
    MustHaveWork,
    WorkResolution,
    _routes_for,
    concept_named_texts,
    figure_outcomes,
    matching_work,
    must_have_outcomes,
)
from peritus.sources.domain import (
    DEPTH_MENTIONS,
    DEPTH_SETS_OUT,
    DEPTH_TREATS,
    NAMED_FOUND,
    NAMED_MISSING,
    NAMED_PARTIAL,
    RawSource,
    SourceCandidate,
    SourceType,
    ValidatedSource,
)
from peritus.sources.fetchers.thought_leaders import ThoughtLeadersFetcher, people_search_calls
from peritus.sources.hosts import ABOUT_HOSTS, SUMMARY_SERVICE_HOSTS, is_about_page
from peritus.sources.orientation import (
    LEAD_MAX_CHARS,
    OrientationPack,
    Overview,
    parse_numbered_outline,
    parse_wiki_extract,
    select_hit,
)
from peritus.sources.triage import TriagedCandidate, rank_candidates
from peritus.sources.validator import _match_concepts, covered_names


def _candidate(
    title: str, url: str = "", source_type=SourceType.GUTENBERG, **meta
) -> SourceCandidate:
    return SourceCandidate(
        source_type,
        url or f"https://x.test/{abs(hash(title))}",
        title,
        None,
        "snippet",
        metadata=dict(meta),
    )


def _triaged(candidate: SourceCandidate, score: float = 8.0) -> TriagedCandidate:
    return TriagedCandidate(candidate, score, model_score=score)


def _validated(raw: RawSource, concepts=(), tier="primary", depths=None) -> ValidatedSource:
    return ValidatedSource(
        raw=raw,
        quality_score=8.0,
        relevance_score=8.0,
        content_type="paper",
        difficulty=3,
        key_claims=[],
        covered_concepts=list(concepts),
        source_tier=tier,
        concept_depths=dict(depths or {}),
    )


# ── Phase 0.A: resolver volumes are not near-duplicates of each other ────────


_SUMMA_VOLUMES = (
    "Summa Theologica, Part I (Prima Pars)",
    "Summa Theologica, Part I-II (Pars Prima Secundae)",
    "Summa Theologica, Part III (Tertia Pars)",
)


def test_the_volumes_of_one_work_are_all_kept():
    """Expert 60 dropped I-II and III as near-duplicates of I (0.93, 0.97)."""
    ranked = rank_candidates(
        [
            _triaged(
                _candidate(title, must_have_title="Summa Theologiae", must_have_sections=sections)
            )
            for title, sections in zip(
                _SUMMA_VOLUMES, ("I qq. 2-3", "I-II qq. 90-97", "III qq. 1-6"), strict=True
            )
        ]
    )
    assert [t.candidate.title for t in ranked] == list(_SUMMA_VOLUMES)


def test_volumes_from_one_lookup_differ_by_designator_and_are_kept():
    ranked = rank_candidates(
        [
            _triaged(_candidate(title, must_have_title="Summa Theologiae"))
            for title in _SUMMA_VOLUMES
        ]
    )
    assert len(ranked) == 3


def test_two_copies_of_one_volume_from_two_routes_still_collapse():
    ranked = rank_candidates(
        [
            _triaged(
                _candidate(
                    "Summa Theologica, Part I-II",
                    "https://gutenberg.org/ebooks/1",
                    must_have_title="Summa Theologiae",
                    must_have_sections="I-II qq. 90-97",
                )
            ),
            _triaged(
                _candidate(
                    "Summa Theologica Part I-II",
                    "https://archive.org/details/summa",
                    must_have_title="Summa Theologiae",
                    must_have_sections="I-II qq. 90-97",
                ),
                7.0,
            ),
        ]
    )
    assert len(ranked) == 1


def test_a_resolver_candidate_never_dedups_against_a_search_hit():
    ranked = rank_candidates(
        [
            _triaged(_candidate("Summa Theologica, Part I", must_have_title="Summa Theologiae")),
            _triaged(_candidate("Summa Theologica Part I", source_type=SourceType.WEB), 7.0),
        ]
    )
    assert len(ranked) == 2
    plain = rank_candidates(
        [
            _triaged(_candidate("An essay on analogy", source_type=SourceType.WEB)),
            _triaged(_candidate("An essay on analogy.", source_type=SourceType.WEB), 7.0),
        ]
    )
    assert len(plain) == 1, "ordinary near-duplicates still collapse"


# ── Phase 0.B: the must-have boost ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("title", "url"),
    [
        (
            "The Aristotelian context of the existence-essence distinction in De Ente et Essentia",
            "",
        ),
        ("De Ente et Essentia — Philopedia", ""),
        ("De Ente et Essentia", "https://iep.utm.edu/de-ente/"),
        ("Summa Theologiae | Encyclopedia.com", ""),
        ("A study of the Summa Theologiae", ""),
    ],
)
def test_pages_about_a_work_are_not_boosted_as_the_work(title, url):
    assert matching_work(title, ["De Ente et Essentia", "Summa Theologiae"], url) is None


@pytest.mark.parametrize(
    "title",
    [
        "Thomas Aquinas: De ente et essentia: English",
        "De Ente et Essentia",
        "The Summa Theologica of St. Thomas Aquinas",
    ],
)
def test_true_hits_still_match(title):
    assert matching_work(title, ["De Ente et Essentia", "Summa Theologiae"]) is not None


def _whole_resolution(title: str) -> WorkResolution:
    hit = _candidate(title, must_have_extent=EXTENT_WHOLE)
    return WorkResolution(MustHaveWork(title), [hit])


def test_round_0_does_not_boost_a_work_the_resolver_found_whole():
    titles = ["Summa Contra Gentiles", "De Veritate"]
    kept = _boosted_must_have_titles(titles, 0, [_whole_resolution("Summa Contra Gentiles")], [])
    assert kept == ["De Veritate"]


def test_later_rounds_stop_boosting_once_the_work_is_in_the_corpus():
    titles = ["Summa Contra Gentiles", "De Veritate"]
    resolution = _whole_resolution("Summa Contra Gentiles")
    assert _boosted_must_have_titles(titles, 1, [resolution], []) == titles, (
        "resolved whole but never accepted — a failed download keeps the boost"
    )
    raw = RawSource(
        SourceType.GUTENBERG,
        "https://gutenberg.org/ebooks/2",
        "Summa Contra Gentiles",
        None,
        "x",
        metadata={"must_have_title": "Summa Contra Gentiles", "must_have_extent": EXTENT_WHOLE},
    )
    kept = _boosted_must_have_titles(titles, 1, [resolution], [_validated(raw)])
    assert kept == ["De Veritate"]


# ── Phase 0.C: the ceiling at the fetch boundary ─────────────────────────────


def test_a_fetch_over_its_stamped_ceiling_is_cut_and_says_so():
    candidate = _candidate("Summa Theologica, Part I", text_max_chars=1_000)
    source = RawSource(SourceType.GUTENBERG, candidate.url, candidate.title, None, "x" * 5_000)
    _enforce_ceiling(candidate, source)
    assert len(source.text) == 1_000
    assert source.metadata["ceiling_enforced"] is True


def test_a_fetch_without_a_ceiling_is_left_alone():
    candidate = _candidate("An essay")
    source = RawSource(SourceType.WEB, candidate.url, candidate.title, None, "x" * 5_000)
    _enforce_ceiling(candidate, source)
    assert len(source.text) == 5_000


class _LongFetcher:
    async def fetch(self, candidate):
        return RawSource(
            candidate.source_type,
            candidate.url,
            candidate.title,
            None,
            ("the law of nature is what reason was " * 20_000),
            metadata=dict(candidate.metadata),
        )


@pytest.mark.asyncio
async def test_the_fetch_stage_enforces_the_ceiling_before_costing_the_source():
    builder = ExpertBuilder(MagicMock())
    builder._fetchers = {"gutenberg": (_LongFetcher(), 4)}
    candidate = _candidate("Summa Theologica, Part I", text_max_chars=200_000, fetch_priority=True)
    sources, _ = await builder._fetch_with_refill(
        [_triaged(candidate, 9.0)],
        5,
        {},
        budget_usd=Decimal(3),
    )
    assert len(sources[0].text) == 200_000


# ── Phase 1: the orientation pack ────────────────────────────────────────────


_THOMISM_EXTRACT = """Thomism is the philosophical and theological school that arose as a legacy of Thomas Aquinas.

== Philosophy ==
=== Metaphysics ===
Being and essence.
=== Epistemology ===
==== Abstraction ====
Deeper than the outline keeps.
== Theology ==
== History ==
=== Neo-Thomism ===
=== Analytic Thomism ===
== See also ==
== References ==
=== Citations ===
== External links ==
"""


def test_the_outline_keeps_two_levels_and_drops_the_apparatus():
    lead, headings = parse_wiki_extract(_THOMISM_EXTRACT)
    assert lead.startswith("Thomism is the philosophical")
    assert headings == [
        (1, "Philosophy"),
        (2, "Metaphysics"),
        (2, "Epistemology"),
        (1, "Theology"),
        (1, "History"),
        (2, "Neo-Thomism"),
        (2, "Analytic Thomism"),
    ]


def test_a_page_with_no_headings_is_all_lead_and_a_long_lead_is_capped():
    lead, headings = parse_wiki_extract("word " * 2_000)
    assert headings == []
    assert len(lead) <= LEAD_MAX_CHARS + 2
    assert lead.endswith("…")


def test_a_reference_entry_s_numbered_contents_is_its_outline():
    text = (
        "Thomism is a school of thought.\n\n1. Life and works\n2. Metaphysics\n"
        "2.1 Act and potency\n2.1.1 Too deep\n3. Bibliography\n4. Legacy\n"
    )
    lead, headings = parse_numbered_outline(text)
    assert lead == "Thomism is a school of thought."
    assert headings == [
        (1, "Life and works"),
        (1, "Metaphysics"),
        (2, "Act and potency"),
        (1, "Legacy"),
    ]


def test_the_hit_is_the_article_titled_after_the_topic():
    hits = [
        {"title": "Thomas Aquinas", "snippet": "the founder of Thomism", "url": "a"},
        {"title": "Thomas the Tank Engine", "snippet": "a railway", "url": "b"},
        {"title": "Thomism", "snippet": "a school", "url": "c"},
    ]
    assert select_hit("Thomism", hits)["url"] == "c", "a title match beats an earlier snippet match"
    assert select_hit("Thomism", hits[:2])["url"] == "a", (
        "a snippet naming the topic is the fallback"
    )
    assert select_hit("Thomism", hits[1:2]) is None


def test_the_pack_renders_as_the_planner_reads_it():
    pack = OrientationPack(
        [
            Overview(
                "Wikipedia",
                "Thomism",
                "https://en.wikipedia.org/wiki/Thomism",
                "A school.",
                [(1, "History"), (2, "Neo-Thomism")],
            ),
        ]
    )
    rendered = pack.render()
    assert rendered.startswith('<overview source="Wikipedia" title="Thomism"')
    assert "Lead: A school." in rendered
    assert "- History\n  - Neo-Thomism" in rendered
    assert pack.record("note")["overviews"][0]["headings"] == ["History", "Neo-Thomism"]


class _PlanClient:
    def __init__(self, plan: dict):
        self.plan = plan
        self.calls: list[dict] = []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        block = MagicMock(type="tool_use", input=self.plan)
        return MagicMock(content=[block])


async def _plan_with(pack: OrientationPack, plan: dict, max_concepts: int = 10):
    from unittest.mock import AsyncMock, patch

    from peritus.experts.builder import _plan_research

    client = _PlanClient(plan)
    with (
        patch("peritus.experts.builder.build_orientation_pack", AsyncMock(return_value=pack)),
        patch("peritus.experts.builder.get_anthropic_client", lambda: client),
    ):
        return await _plan_research("Thomism", max_concepts), client.calls[0]


@pytest.mark.asyncio
async def test_the_planner_is_shown_the_pack_and_the_plan_records_what_was_read():
    pack = OrientationPack([Overview("Wikipedia", "Thomism", "u", "A school.", [(1, "History")])])
    plan, call = await _plan_with(
        pack,
        {
            "facets": [{"name": "History", "concepts": ["Neo-Thomism", "Analytic Thomism"]}],
            "orientation_note": "",
        },
    )
    message = call["messages"][0]["content"]
    assert message.startswith("Topic: Thomism\n\n<overview")
    assert "checklist of the topic's facets" in call["system"]
    assert call["tools"][0]["input_schema"]["properties"]["key_concepts"]["maxItems"] == 10
    assert plan["orientation"] == {
        "overviews": [
            {"source": "Wikipedia", "title": "Thomism", "url": "u", "headings": ["History"]}
        ],
        "note": "",
    }


@pytest.mark.asyncio
async def test_an_empty_pack_plans_from_the_topic_alone():
    plan, call = await _plan_with(OrientationPack(), {"key_concepts": ["analogy"]})
    assert call["messages"][0]["content"] == "Topic: Thomism"
    assert plan["orientation"] == {"overviews": [], "note": ""}
    assert plan["key_concepts"] == ["analogy"]


@pytest.mark.asyncio
async def test_the_pack_never_fails_the_build(monkeypatch):
    from peritus.sources import orientation

    async def _boom(topic):
        raise RuntimeError("network down")

    async def _slow(topic):
        import asyncio

        await asyncio.sleep(5)

    monkeypatch.setattr(orientation, "_wikipedia_overview", _boom)
    monkeypatch.setattr(orientation, "_reference_overview", _slow)
    pack = await orientation.build_orientation_pack("Thomism", timeout=0.05)
    assert pack.empty


# ── Phase 2: facets ──────────────────────────────────────────────────────────


def test_facets_flatten_into_key_concepts_deduplicated_across_facets():
    plan = _normalise_plan(
        {
            "facets": [
                {"name": "Metaphysics", "concepts": ["Act and potency", "Analogy of being"]},
                {"name": "History", "concepts": ["Neo-Thomism", "analogy of being", "  "]},
                {"name": "", "concepts": []},
            ],
            "key_concepts": ["Natural law", "Neo-Thomism"],
        },
        "Thomism",
    )
    assert plan["facets"] == [
        {"name": "Metaphysics", "concepts": ["Act and potency", "Analogy of being"]},
        {"name": "History", "concepts": ["Neo-Thomism"]},
        # A concept in key_concepts and in no facet joins a facet rather than vanishing.
        {"name": "Other", "concepts": ["Natural law"]},
    ]
    assert plan["key_concepts"] == [
        "Act and potency",
        "Analogy of being",
        "Neo-Thomism",
        "Natural law",
    ]


def test_the_cap_trims_the_largest_facet_first_and_never_empties_one():
    plan = _normalise_plan(
        {
            "facets": [
                {"name": "A", "concepts": ["a1", "a2", "a3", "a4"]},
                {"name": "B", "concepts": ["b1"]},
                {"name": "C", "concepts": ["c1", "c2"]},
            ],
        },
        "t",
        max_concepts=4,
    )
    assert [f["concepts"] for f in plan["facets"]] == [["a1", "a2"], ["b1"], ["c1"]]


def test_tiers_size_the_syllabus_and_old_snapshots_keep_eight():
    assert [ExpertConfig.from_tier(t).max_key_concepts for t in ExpertTier] == [8, 10, 14]
    assert [ExpertConfig.from_tier(t).figure_texts for t in ExpertTier] == [0, 3, 6]
    snapshot = ExpertConfig(1.0, 10, 4, 1, 5, 15, 2048)
    assert (snapshot.max_key_concepts, snapshot.figure_texts) == (8, 0)


_STANDARD_TARGET = CoverageTarget(
    min_sources=2,
    min_source_types=1,
    require_non_tertiary=False,
    max_rounds=2,
    require_primary=True,
)


def _src(
    concepts: dict[str, str], tier="primary", source_type=SourceType.WEB, **meta
) -> ValidatedSource:
    raw = RawSource(
        source_type, f"https://x.test/{abs(hash(str(concepts)))}", "T", None, "text", metadata=meta
    )
    return _validated(raw, [c for c, d in concepts.items() if d != DEPTH_MENTIONS], tier, concepts)


def test_the_loop_takes_the_weakest_concept_from_each_facet_in_turn():
    """Heavy in one facet: the four largest shortfalls are all its neighbours."""
    facets = [
        {"name": "Metaphysics", "concepts": ["act", "essence", "analogy", "five ways"]},
        {"name": "History", "concepts": ["neo-thomism", "analytic thomism"]},
    ]
    concepts = [c for f in facets for c in f["concepts"]]
    passed = [_src({"neo-thomism": DEPTH_SETS_OUT}), _src({"analytic thomism": DEPTH_SETS_OUT})]
    report = compute_coverage(concepts, passed, _STANDARD_TARGET, facets)

    flat = [c.concept for c in report.weakest(4)]
    assert set(flat) <= set(facets[0]["concepts"]), "the old selector never reaches the other facet"
    by_facet = [c.concept for c in report.weakest_by_facet(4)]
    assert by_facet[:2] == ["act", "analytic thomism"]
    assert {f.name: f.met for f in report.facets} == {"Metaphysics": False, "History": False}


def test_without_facets_the_facet_selectors_are_the_flat_ones():
    passed = [_src({"b": DEPTH_TREATS})]
    report = compute_coverage(["a", "b", "c"], passed, _STANDARD_TARGET)
    assert report.weakest_by_facet(3) == report.weakest(3)
    assert report.thinnest_by_facet(3) == report.thinnest(3)


def test_the_feedback_prompt_groups_weak_concepts_under_their_facets():
    from peritus.experts.feedback import weak_concepts_block

    report = compute_coverage(["neo-thomism", "natural law"], [], _STANDARD_TARGET)
    block = weak_concepts_block(
        list(report.concepts),
        facet_of={"neo-thomism": "History of the school", "natural law": "Ethics"},
        missing_texts={"natural law": ["Summa Theologiae I-II qq. 90–97"]},
        voiceless_figures=["Jacques Maritain"],
    )
    assert "Facet: History of the school\n  - neo-thomism — 0 accepted source(s)" in block
    assert "named text missing: Summa Theologiae I-II qq. 90–97" in block
    assert "Figures with no work in their own voice" in block and "- Jacques Maritain" in block


# ── Phase 3: voices and works that can be had ────────────────────────────────


def test_figures_are_normalised_with_one_obtainable_work_or_none():
    plan = _normalise_plan(
        {
            "facets": [{"name": "F", "concepts": ["c"]}],
            "figures": [
                {
                    "name": "Edward Feser",
                    "why": "analytic Thomism",
                    "obtainable": True,
                    "work": {
                        "title": "Five Proofs blog essays",
                        "kind": "text",
                        "public_domain": False,
                        "open_text": True,
                    },
                },
                {"name": "Étienne Gilson", "why": "historian", "obtainable": False},
                {"name": "edward feser", "why": "duplicate", "obtainable": False},
                {"name": "No Work", "why": "", "obtainable": True},
            ],
        },
        "Thomism",
    )
    assert [f["name"] for f in plan["figures"]] == ["Edward Feser", "Étienne Gilson", "No Work"]
    assert plan["figures"][0]["work"]["author"] == "Edward Feser"
    assert plan["figures"][2] == {"name": "No Work", "why": "", "work": None, "obtainable": False}


def test_the_channel_excludes_about_hosts_and_asks_for_personal_sites():
    (topic_query, topic_kwargs), (name_query, name_kwargs) = people_search_calls(
        "Edward Feser", "Thomism"
    )
    assert topic_query == "Edward Feser Thomism"
    assert set(ABOUT_HOSTS) <= set(topic_kwargs["exclude_domains"])
    assert "plato.stanford.edu" in topic_kwargs["exclude_domains"]
    assert name_query == "Edward Feser" and name_kwargs["category"] == "personal site"


@pytest.mark.parametrize(
    ("title", "url", "about"),
    [
        (
            "Jacques Maritain (Stanford Encyclopedia of Philosophy)",
            "https://plato.stanford.edu/entries/maritain/",
            True,
        ),
        (
            "Aquinas, Thomas | Internet Encyclopedia of Philosophy",
            "https://iep.utm.edu/aquinas/",
            True,
        ),
        ("Jacques Maritain - Wikipedia", "https://example.org/maritain", True),
        ("The Catholic Encyclopedia: Thomism", "https://www.newadvent.org/cathen/14698b.htm", True),
        (
            "Edward Feser: The road from atheism",
            "https://edwardfeser.blogspot.com/2012/the-road.html",
            False,
        ),
        ("SUMMA THEOLOGIAE: The natural law", "https://www.newadvent.org/summa/2094.htm", False),
    ],
)
def test_pages_about_a_person_are_dropped_and_their_own_writing_is_not(title, url, about):
    assert is_about_page(title, url) is about


def test_summary_services_are_penalised_by_the_triage_prior_too():
    from peritus.sources.triage import domain_adjustment

    assert all(domain_adjustment(f"https://{host}/x") < 0 for host in SUMMARY_SERVICE_HOSTS)


@pytest.mark.asyncio
async def test_plan_figures_replace_the_blind_identification_call(monkeypatch):
    from peritus.sources.fetchers import thought_leaders

    async def _never(topic):
        raise AssertionError("the plan named the figures; nobody should ask again")

    searched: list[str] = []

    async def _content(person, topic):
        searched.append(person["name"])
        return [
            SourceCandidate(
                SourceType.THOUGHT_LEADER,
                f"https://{person['name'][0]}.test/{i}",
                f"Essay {i}",
                person["name"],
                "s",
                metadata={"leader": person["name"]},
            )
            for i in range(3)
        ] + [
            SourceCandidate(
                SourceType.THOUGHT_LEADER,
                "https://plato.stanford.edu/entries/x/",
                "Entry",
                None,
                "s",
                metadata={"leader": person["name"]},
            )
        ]

    monkeypatch.setattr(thought_leaders, "_identify_leaders", _never)
    monkeypatch.setattr(thought_leaders, "_search_leader_content", _content)
    fetcher = ThoughtLeadersFetcher(
        [{"name": "Feser", "why": "x"}, {"name": "Maritain", "why": "y"}], "Thomism"
    )
    found = await fetcher.search("Thomism thinkers", 4)
    assert searched == ["Feser", "Maritain"]
    assert [c.metadata["leader"] for c in found] == ["Feser", "Maritain", "Feser", "Maritain"], (
        "interleaved person by person, about-pages dropped"
    )


def test_an_in_copyright_book_skips_the_public_domain_libraries():
    work = MustHaveWork(
        "The Elements of Christian Philosophy", "Étienne Gilson", "book", public_domain=False
    )
    assert not work.obtainable
    assert [name for name, _ in _routes_for(work, exa_search=object())] == ["exa"]
    assert _routes_for(work, exa_search=None) == []


def test_not_obtainable_is_reported_with_its_substitute():
    work = MustHaveWork.from_plan(
        {
            "title": "The Elements of Christian Philosophy",
            "author": "Gilson",
            "kind": "book",
            "public_domain": False,
            "substitute": {
                "title": "The Spirit of Mediaeval Philosophy",
                "kind": "book",
                "public_domain": True,
            },
        }
    )
    assert work.substitute is not None and work.substitute.substitute_for == work.title
    outcomes = {o["title"]: o for o in must_have_outcomes([work, work.substitute], [], [])}
    assert outcomes[work.title]["status"] == NOT_OBTAINABLE
    assert outcomes[work.title]["substitute"] == "The Spirit of Mediaeval Philosophy"
    assert outcomes["The Spirit of Mediaeval Philosophy"]["status"] == "not_found"
    assert outcomes["The Spirit of Mediaeval Philosophy"]["substitute_for"] == work.title


@pytest.mark.asyncio
async def test_a_substitute_is_looked_for_only_when_the_work_cannot_be_had(monkeypatch):
    from peritus.experts import builder as builder_module

    resolved: list[list[str]] = []

    async def _resolve(works, **_kwargs):
        resolved.append([w.title for w in works])
        return [WorkResolution(w) for w in works]

    monkeypatch.setattr(builder_module, "resolve_works", _resolve)
    builder = ExpertBuilder(MagicMock())
    gilson = MustHaveWork.from_plan(
        {
            "title": "Elements",
            "kind": "book",
            "public_domain": False,
            "substitute": {"title": "Spirit", "kind": "book", "public_domain": True},
        }
    )
    summa = MustHaveWork.from_plan(
        {
            "title": "Summa",
            "kind": "text",
            "public_domain": True,
            "substitute": {"title": "Never needed", "kind": "book", "public_domain": True},
        }
    )
    await builder._resolve_canonical([gilson, summa], None, 0)
    assert resolved == [["Elements", "Summa"], ["Spirit"]]
    assert [w.title for w in builder._queued_substitutes] == ["Spirit"]


def test_figure_statuses():
    figures = [
        {"name": "Feser", "obtainable": True},
        {"name": "Maritain", "obtainable": True},
        {"name": "Gilson", "obtainable": False},
        {"name": "Cajetan", "obtainable": True},
    ]
    works = [
        MustHaveWork(
            "Commentary on De Ente", "Cajetan", "text", True, scope=SCOPE_FIGURE, figure="Cajetan"
        ),
    ]
    passed = [
        ("https://feser.test", {"leader": "Feser", "source_tier": "secondary"}),
        ("https://sep.test", {"leader": "Maritain", "source_tier": "tertiary"}),
    ]
    statuses = {f["name"]: f["status"] for f in figure_outcomes(figures, works, passed)}
    assert statuses == {
        "Feser": "own_voice",
        "Maritain": "about_only",
        "Gilson": NOT_OBTAINABLE,
        "Cajetan": "not_found",
    }


def test_the_validator_calls_an_about_page_tertiary():
    from peritus.sources.validator import _source_context

    raw = RawSource(
        SourceType.THOUGHT_LEADER, "u", "t", None, "x", metadata={"leader": "Jacques Maritain"}
    )
    context = _source_context(raw)
    assert "If it is about Jacques Maritain" in context and "classify it tertiary" in context
    assert "substantively present their work" not in context


def test_feedback_authors_are_kept_apart_from_concept_queries():
    from peritus.experts.feedback import _normalise, fallback_queries

    report = compute_coverage(["analogy"], [], _STANDARD_TARGET)
    weakest = list(report.concepts)
    result = _normalise(
        {
            "concepts": [{"concept": "analogy", "queries": ["analogia entis Cajetan"]}],
            "authors": ["Cajetan"],
        },
        weakest,
        fallback_queries("Thomism", weakest),
    )
    assert result.queries == {"analogy": ["analogia entis Cajetan"]}
    assert result.authors == ["Cajetan"]


# ── Phase 4: graded tags and the named-text gate ─────────────────────────────


def test_tags_are_matched_with_their_depth_and_legacy_strings_read_as_treats():
    depths = _match_concepts(
        [
            {"concept": "natural law", "depth": "sets_out"},
            {"concept": "Analogy", "depth": "mentions"},
            "act and potency",
            {"concept": "natural law", "depth": "mentions"},
            {"concept": "invented", "depth": "sets_out"},
            {"concept": "essence", "depth": "deeply"},
        ],
        ["Natural law", "analogy", "Act and potency", "essence"],
    )
    assert depths == {
        "Natural law": "sets_out",
        "analogy": "mentions",
        "Act and potency": "treats",
        "essence": "treats",
    }
    assert covered_names(depths) == ["Natural law", "Act and potency", "essence"]


_LITE_TARGET = CoverageTarget(
    min_sources=1, min_source_types=1, require_non_tertiary=False, max_rounds=1
)


def test_mentions_never_count_and_a_survey_counts_for_its_three_deepest():
    survey = _src(
        {
            "a": DEPTH_TREATS,
            "b": DEPTH_SETS_OUT,
            "c": DEPTH_TREATS,
            "d": DEPTH_TREATS,
            "e": DEPTH_MENTIONS,
        }
    )
    report = compute_coverage(["a", "b", "c", "d", "e"], [survey], _LITE_TARGET)
    counts = report.counts()
    assert counts == {"a": 1, "b": 1, "c": 1, "d": 0, "e": 0}
    assert report.concepts[1].depth_counts == {"sets_out": 1}


def test_a_section_cut_work_counts_only_for_the_concepts_it_was_cut_for():
    tags = {"natural law": DEPTH_TREATS, "five ways": DEPTH_TREATS, "analogy": DEPTH_TREATS}
    cut = _src(tags, must_have_concepts=["natural law"], sections_matched=True)
    uncut = _src(tags, must_have_concepts=["natural law"], sections_matched=False)
    concepts = ["natural law", "five ways", "analogy"]
    cut_counts = compute_coverage(concepts, [cut], _LITE_TARGET).counts()
    assert cut_counts == {"natural law": 1, "five ways": 0, "analogy": 0}
    uncut_counts = compute_coverage(concepts, [uncut], _LITE_TARGET).counts()
    assert uncut_counts == {"natural law": 1, "five ways": 1, "analogy": 1}
    report = compute_coverage(concepts, [cut], _STANDARD_TARGET)
    assert report.concepts[0].depth_counts == {"sets_out": 1}


@pytest.mark.parametrize(
    ("named", "depth", "has_primary"),
    [
        (NAMED_FOUND, DEPTH_TREATS, True),
        (NAMED_PARTIAL, DEPTH_TREATS, True),
        (NAMED_MISSING, DEPTH_TREATS, False),
        (NAMED_MISSING, DEPTH_SETS_OUT, True),
        (None, DEPTH_TREATS, True),
    ],
)
def test_the_named_text_gates_has_primary(named, depth, has_primary):
    passed = [
        _src({"natural law": depth}),
        _src({"natural law": depth}, source_type=SourceType.GUTENBERG),
    ]
    named_texts = {"natural law": named} if named else None
    [concept] = compute_coverage(
        ["natural law"], passed, _STANDARD_TARGET, named_texts=named_texts
    ).concepts
    assert concept.has_primary is has_primary
    assert concept.met is has_primary
    assert concept.named_text == (named or "none_named")


def test_found_named_text_satisfies_primary_even_with_no_primary_tag():
    passed = [
        _src({"x": DEPTH_TREATS}, tier="secondary"),
        _src({"x": DEPTH_TREATS}, tier="secondary"),
    ]
    [concept] = compute_coverage(
        ["x"], passed, _STANDARD_TARGET, named_texts={"x": NAMED_FOUND}
    ).concepts
    assert concept.has_primary


def test_lite_is_unchanged_by_the_gate():
    lite = ExpertConfig.from_tier(ExpertTier.LITE).coverage_target()
    [concept] = compute_coverage(
        ["natural law"],
        [_src({"natural law": DEPTH_TREATS})],
        lite,
        named_texts={"natural law": NAMED_MISSING},
    ).concepts
    assert concept.met


def _meta(**meta) -> dict:
    return {"source_tier": "primary", **meta}


def test_the_named_text_is_judged_per_lookup_not_per_work():
    """Expert 60: Part I found whole did not find the treatise on law in I-II."""
    works = [
        MustHaveWork(
            "Summa Theologiae", "Aquinas", "text", True, "I qq. 2-3", SCOPE_CONCEPT, ["five ways"]
        ),
        MustHaveWork(
            "Summa Theologiae",
            "Aquinas",
            "text",
            True,
            "I-II qq. 90-97",
            SCOPE_CONCEPT,
            ["natural law"],
        ),
        MustHaveWork(
            "De Ente et Essentia", "Aquinas", "text", True, "", SCOPE_CONCEPT, ["real distinction"]
        ),
        MustHaveWork(
            "De Veritate", "Aquinas", "text", True, "q. 1", SCOPE_CONCEPT, ["transcendentals"]
        ),
    ]
    passed = [
        (
            "https://g/1",
            _meta(
                must_have_title="Summa Theologiae",
                must_have_extent="partial",
                must_have_concepts=["five ways"],
                sections_matched=True,
            ),
        ),
        (
            "https://d/1",
            _meta(must_have_title="De Ente et Essentia", must_have_extent=EXTENT_WHOLE),
        ),
        (
            "https://v/1",
            _meta(
                must_have_title="De Veritate",
                must_have_extent="partial",
                must_have_concepts=["transcendentals"],
            ),
        ),
    ]
    named = concept_named_texts(works, passed)
    assert {c: e["status"] for c, e in named.items()} == {
        "five ways": "found",
        "natural law": "missing",
        "real distinction": "found",
        "transcendentals": "partial",
    }
    assert named["natural law"]["texts"] == ["Summa Theologiae I-II qq. 90-97"]


def test_a_found_substitute_counts_for_the_concept():
    work = MustHaveWork.from_plan(
        {
            "concept": "being",
            "title": "Elements",
            "kind": "book",
            "public_domain": False,
            "substitute": {"title": "Spirit", "kind": "book", "public_domain": True},
        },
        SCOPE_CONCEPT,
    )
    passed = [("u", _meta(must_have_title="Spirit", must_have_extent=EXTENT_WHOLE))]
    assert concept_named_texts([work, work.substitute], passed)["being"]["status"] == "found"


def test_the_corpus_summary_reports_what_the_gate_sees():
    passed = [_src({"natural law": DEPTH_TREATS}), _src({"five ways": DEPTH_SETS_OUT})]
    corpus = corpus_composition(
        passed,
        [],
        ["natural law", "five ways"],
        named_texts={"natural law": {"status": "missing", "texts": ["Summa I-II qq. 90-97"]}},
        figures=[{"name": "Feser", "status": "own_voice", "source_urls": ["u"]}],
    )
    assert corpus["concepts_without_primary"] == ["natural law"]
    assert corpus["concepts_missing_named_text"] == [
        {"concept": "natural law", "texts": ["Summa I-II qq. 90-97"]}
    ]
    assert corpus["figures"][0]["status"] == "own_voice"
