"""Primary texts for the topic and for each concept, cut to their named sections.

Nothing here is specific to one subject: the fixtures cover a treatise with
numbered questions, a book with chapters inside books, a paper, a standard, and a
non-English text. No network, no models.
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from peritus.core.config import settings
from peritus.experts.builder import (
    OUTCOME_FETCHED,
    OUTCOME_NOT_ENGLISH,
    ExpertBuilder,
    _fetcher_for,
    _graph_chunk_limit,
    _normalise_plan,
)
from peritus.experts.coverage import ConceptCoverage
from peritus.experts.domain import ExpertConfig, ExpertTier
from peritus.sources import canonical as canonical_module
from peritus.sources.canonical import (
    EXTENT_PARTIAL,
    EXTENT_WHOLE,
    FOUND_PARTIAL,
    FOUND_SECTIONS,
    FOUND_WHOLE,
    ROUTE_ARCHIVE,
    ROUTE_ARXIV,
    ROUTE_EXA,
    ROUTE_EXA_PRIMARY,
    ROUTE_GUTENBERG,
    ROUTE_OPENALEX,
    SCOPE_CONCEPT,
    SCOPE_OVERALL,
    ArchiveTextFetcher,
    MustHaveWork,
    _routes_for,
    archive_identifier,
    archive_item_is_reusable,
    as_archive_candidate,
    merge_works,
    must_have_outcomes,
    order_by_sections,
    resolve_works,
)
from peritus.sources.domain import RawSource, SourceCandidate, SourceType
from peritus.sources.language import english_share, is_expected_language
from peritus.sources.sections import apply_sections, parse_hint, select_sections
from peritus.sources.triage import TriagedCandidate, domain_adjustment

# ── fixtures ─────────────────────────────────────────────────────────────────


def _prose(tag: str, words: int = 120) -> str:
    return " ".join(f"the {tag} of this is what it was and it is" for _ in range(words // 10))


def _treatise(questions: range, toc: bool = True) -> str:
    front = "A TREATISE\nTranslated by someone\n\n"
    contents = "".join(f"QUESTION {n}\n" for n in questions) if toc else ""
    body = "".join(f"\nQUESTION {n}\n{_prose(f'q{n}')}\n" for n in questions)
    return front + contents + body


def _candidate(title: str, url: str = "", st: SourceType = SourceType.WEB, **meta) -> SourceCandidate:
    return SourceCandidate(st, url or f"https://x.test/{title.replace(' ', '-')}", title, None, "", dict(meta))


# ── sections ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("I-II qq. 90–97; q. 2", {"question": [(90, 97), (2, 2)]}),
        ("Book II, chapters 1–10", {"book": [(2, 2)], "chapter": [(1, 10)]}),
        ("sections 2, 4 and 7", {"section": [(2, 2), (4, 4), (7, 7)]}),
        ("Lectures 4-6", {"lecture": [(4, 6)]}),
        ("chapter XIII", {"chapter": [(13, 13)]}),
        ("§§ 3–5", {"section": [(3, 5)]}),
        ("the whole work, 1848 edition", {}),
    ],
)
def test_hints_become_numbered_ranges_only_after_a_kind_word(hint, expected):
    assert parse_hint(hint) == expected


def test_named_questions_are_kept_and_a_table_of_contents_is_not_mistaken_for_them():
    text = _treatise(range(1, 31))
    selection = select_sections(text, "qq. 20–22", max_chars=100_000)
    assert selection.matched
    assert selection.sections_kept == 3
    assert "the q21 of" in selection.text
    assert "the q1 of" not in selection.text and "the q23 of" not in selection.text
    assert selection.text.startswith("A TREATISE"), "front matter says what the text is"


def test_chapters_inside_a_named_book_only():
    text = "Title\n\n" + "".join(
        f"BOOK {b}\n\n" + "".join(f"CHAPTER {c}\n{_prose(f'b{b}c{c}')}\n" for c in range(1, 5))
        for b in ("I", "II", "III")
    )
    selection = select_sections(text, "Book II, chapters 2-3", 100_000)
    assert "the bIIc2 of" in selection.text and "the bIIc3 of" in selection.text
    assert "the bIc2 of" not in selection.text and "the bIIIc2 of" not in selection.text


def test_the_ceiling_is_a_ceiling_not_a_target():
    text = _treatise(range(1, 11), toc=False)
    selection = select_sections(text, "q. 5", max_chars=100_000)
    assert len(selection.text) < 2_000, "nothing is added to fill the ceiling"


def test_no_match_falls_back_to_a_prefix_and_says_why():
    selection = select_sections("x" * 5_000, "qq. 1-3", max_chars=1_000)
    assert not selection.matched
    assert len(selection.text) == 1_000
    assert "no heading matched" in selection.reason


def test_apply_sections_records_what_happened():
    text, recorded = apply_sections(
        _treatise(range(1, 6), toc=False), {"must_have_sections": "q. 3", "text_max_chars": 50_000}, 200_000
    )
    assert recorded["sections_matched"] is True
    assert recorded["truncated"] is True
    plain, recorded = apply_sections("y" * 300, {}, 100)
    assert plain == "y" * 100 and recorded == {"truncated": True}


# ── works: scope, merging, routes, priority ─────────────────────────────────


def test_each_concept_passage_is_its_own_lookup_and_the_overall_entry_joins_them():
    """A whole-work hint merged into the concept hints made the cut keep the
    work's opening again, and gave every concept one volume."""
    works = merge_works([
        MustHaveWork("Principia (Mathematical Principles)", "Isaac Newton", "text", True,
                     "Books I-III", SCOPE_OVERALL),
        MustHaveWork("Principia", "Newton", "text", True, "Book III", SCOPE_CONCEPT, ["gravitation"]),
        MustHaveWork("Principia", "Newton", "text", True, "Book I, sections 2-3", SCOPE_CONCEPT, ["orbits"]),
        MustHaveWork("Principia", "Newton", "text", True, "Book III", SCOPE_CONCEPT, ["tides"]),
        MustHaveWork("Opticks", "Newton", "text", True, "", SCOPE_OVERALL),
    ])
    lookups = {(w.title, w.sections): (w.scope, w.concepts) for w in works}
    assert lookups == {
        ("Principia", "Book III"): (SCOPE_OVERALL, ["gravitation", "tides"]),
        ("Principia", "Book I, sections 2-3"): (SCOPE_OVERALL, ["orbits"]),
        ("Opticks", ""): (SCOPE_OVERALL, []),
    }


def test_two_concepts_on_one_volume_share_one_fetch_with_both_sections():
    from peritus.experts.builder import _merge_same_volume

    a = _candidate("Vol I", "https://g.test/1", must_have_sections="q. 2", must_have_concepts=["proofs"],
                   fetch_priority=True, priority_rank=1, text_max_chars=60_000)
    b = _candidate("Vol I", "https://g.test/1/", must_have_sections="qq. 75-89", must_have_concepts=["soul"],
                   fetch_priority=True, priority_rank=0, text_max_chars=60_000)
    c = _candidate("Vol III", "https://g.test/3", must_have_sections="qq. 60-83")
    merged = _merge_same_volume([a, b, c], ceiling=200_000)
    assert [m.title for m in merged] == ["Vol I", "Vol III"]
    meta = merged[0].metadata
    assert meta["must_have_sections"] == "q. 2; qq. 75-89"
    assert meta["must_have_concepts"] == ["proofs", "soul"]
    assert meta["priority_rank"] == 0
    assert meta["text_max_chars"] == 120_000

    big = [
        _candidate("Vol I", "https://g.test/1", must_have_sections=f"q. {n}", text_max_chars=200_000)
        for n in (2, 13, 75)
    ]
    [one] = _merge_same_volume(big, ceiling=200_000)
    assert one.metadata["text_max_chars"] == 200_000, "never past one canonical work's ceiling"


def test_a_bracketed_alternate_title_matches_either_name():
    from peritus.sources.canonical import names_the_work, title_key, title_variants

    wanted = "De Ente et Essentia (On Being and Essence)"
    assert title_variants(wanted) == [wanted, "De Ente et Essentia", "On Being and Essence"]
    assert names_the_work("Thomas Aquinas: De ente et essentia: English", wanted, "Thomas Aquinas")
    assert names_the_work("On Being and Essence", wanted)
    assert title_key(wanted) == title_key("De Ente et Essentia")
    assert MustHaveWork(wanted).search_title == "De Ente et Essentia"


def test_only_a_primary_source_counts_as_the_work_found():
    works = [
        MustHaveWork("Summa Theologica", public_domain=True),
        MustHaveWork("De Ente et Essentia (On Being and Essence)", public_domain=True),
    ]
    passed = [
        ("https://en.wikipedia.org/wiki/Summa_Theologica",
         {"must_have_title": "Summa Theologica", "must_have_extent": EXTENT_WHOLE, "source_tier": "tertiary"}),
        ("https://dhspriory.test/deente",
         {"must_have_title": "De Ente et Essentia", "must_have_extent": EXTENT_WHOLE, "source_tier": "primary"}),
    ]
    status = {o["title"]: o["status"] for o in must_have_outcomes(works, [], passed)}
    assert status == {
        "Summa Theologica": "not_found",
        "De Ente et Essentia (On Being and Essence)": FOUND_WHOLE,
    }


@pytest.mark.asyncio
async def test_an_encyclopedia_article_with_a_works_title_is_not_a_must_have_hit():
    from peritus.sources import triage as triage_module
    from peritus.sources.triage import triage_candidates

    async def _gather(params, **_kwargs):
        return [None for _ in params]

    wiki = _candidate("Summa Theologica", "https://en.wikipedia.org/wiki/Summa", SourceType.WIKIPEDIA)
    text = _candidate("Summa Theologica, Part I", "https://www.gutenberg.org/ebooks/17611", SourceType.GUTENBERG)
    with patch.object(triage_module, "gather_claude_calls", _gather):
        triaged = await triage_candidates("t", [], ["Summa Theologica"], [wiki, text])
    assert not triaged[0].candidate.metadata.get("must_have_title")
    assert triaged[1].candidate.metadata["must_have_title"] == "Summa Theologica"


@pytest.mark.parametrize(
    ("kind", "public_domain", "routes"),
    [
        ("text", True, [ROUTE_GUTENBERG, ROUTE_ARCHIVE, ROUTE_EXA_PRIMARY, ROUTE_EXA]),
        # In copyright with no free text: one open search (docs/plans/syllabus.md, 3.B).
        ("book", False, [ROUTE_EXA]),
        ("paper", False, [ROUTE_ARXIV, ROUTE_OPENALEX, ROUTE_EXA]),
        ("standard", False, [ROUTE_EXA]),
    ],
)
def test_routes_depend_on_the_kind_of_work(kind, public_domain, routes):
    work = MustHaveWork("A Work", kind=kind, public_domain=public_domain)
    assert [name for name, _ in _routes_for(work, exa_search=object())] == routes


def test_without_exa_a_paper_still_has_openalex():
    assert [n for n, _ in _routes_for(MustHaveWork("P", kind="paper"), None)] == [ROUTE_ARXIV, ROUTE_OPENALEX]


@pytest.mark.asyncio
async def test_only_the_best_hit_per_work_jumps_the_queue_and_carries_the_ceiling():
    async def exa_open(work, _exa):
        return [
            _candidate("Guidelines, Section 4", must_have_extent=EXTENT_PARTIAL),
            _candidate("Guidelines", must_have_extent=EXTENT_WHOLE),
        ]

    with patch.object(canonical_module, "_exa_open_route", exa_open):
        [resolution] = await resolve_works(
            [MustHaveWork("Guidelines", kind="standard", scope=SCOPE_CONCEPT, concepts=["dosing"])],
            exa_search=object(),
            max_chars={SCOPE_CONCEPT: 60_000},
        )
    flags = {c.title: c.metadata.get("fetch_priority", False) for c in resolution.candidates}
    assert flags == {"Guidelines, Section 4": False, "Guidelines": True}
    whole = next(c for c in resolution.candidates if c.title == "Guidelines")
    assert whole.metadata["priority_rank"] == 1, "concept texts queue after canonical works"
    assert whole.metadata["text_max_chars"] == 60_000
    assert whole.metadata["must_have_concepts"] == ["dosing"]


def test_volume_designators_are_matched_as_pairs_not_loose_numerals():
    volumes = [
        _candidate("Collected Works, Part I-II (Pars Prima Secundae)", must_have_extent=EXTENT_PARTIAL),
        _candidate("Collected Works, Part I (Prima Pars)", must_have_extent=EXTENT_PARTIAL),
    ]
    assert order_by_sections(list(volumes), "Prima Pars q. 2")[0].title.endswith("(Prima Pars)")
    assert "I-II" in order_by_sections(list(volumes), "I-II qq. 90-97")[0].title


def test_a_volume_the_hint_points_at_is_enough_to_stop_looking():
    from peritus.sources.canonical import WorkResolution

    work = MustHaveWork("Collected Works", sections="I-II qq. 90-97")
    hit = _candidate("Collected Works, Part I-II", must_have_extent=EXTENT_PARTIAL, sections_expected=True)
    assert WorkResolution(work, [hit]).sufficient
    assert not WorkResolution(MustHaveWork("Collected Works"), [hit]).sufficient


def test_outcomes_distinguish_whole_named_sections_and_fragments():
    works = [
        MustHaveWork("A"), MustHaveWork("B", sections="ch. 3"), MustHaveWork("C"),
        MustHaveWork("D", public_domain=True), MustHaveWork("E"),
    ]
    passed = [
        ("u1", {"must_have_title": "A", "must_have_extent": EXTENT_WHOLE}),
        ("u2", {"must_have_title": "B", "must_have_extent": EXTENT_WHOLE, "sections_matched": True}),
        ("u3", {"must_have_title": "C", "must_have_extent": EXTENT_PARTIAL}),
    ]
    status = {o["title"]: o["status"] for o in must_have_outcomes(works, [], passed)}
    assert status == {
        "A": FOUND_WHOLE, "B": FOUND_SECTIONS, "C": FOUND_PARTIAL, "D": "not_found",
        # An in-copyright book with no free text is not a failed search.
        "E": "not_obtainable",
    }


# ── the Internet Archive: routing and reuse ─────────────────────────────────


def test_any_archive_page_routes_to_the_items_text():
    for url in (
        "https://archive.org/details/someitem00auth",
        "https://archive.org/stream/in.ernet.dli.2015.76179/2015.76179.Some-Book_djvu.txt",
    ):
        candidate = as_archive_candidate(_candidate("X", url, SourceType.EXA))
        assert candidate is not None and candidate.metadata["canonical_fetcher"] == "archive"
    assert archive_identifier("https://archive.org/stream/in.ernet.dli.2015.76179/x.txt") == "in.ernet.dli.2015.76179"
    assert isinstance(_fetcher_for(_candidate("X", "https://archive.org/details/abc"), {}), ArchiveTextFetcher)
    assert as_archive_candidate(_candidate("X", "https://example.org/details/abc")) is None


@pytest.mark.parametrize(
    ("metadata", "reusable"),
    [
        ({"licenseurl": "http://creativecommons.org/publicdomain/mark/1.0/"}, True),
        ({"licenseurl": "https://creativecommons.org/licenses/by/4.0/"}, True),
        ({"date": "1911"}, True),
        ({"year": "1930"}, True),
        ({"year": "1931"}, False),
        ({"date": "2014-03-01"}, False),
        ({"possible-copyright-status": "NOT_IN_COPYRIGHT"}, False),
        ({}, False),
    ],
)
def test_archive_items_are_used_only_when_their_metadata_allows_it(metadata, reusable):
    assert archive_item_is_reusable(metadata, today=2026)[0] is reusable


# ── language ─────────────────────────────────────────────────────────────────


def test_english_is_recognised_and_other_languages_are_not():
    assert english_share(_prose("law", 400)) > 0.3
    spanish = "La distinción real entre la esencia y la existencia es el núcleo de la metafísica. " * 30
    german = "Die Unterscheidung zwischen Wesen und Dasein ist der Kern der Metaphysik und bleibt. " * 30
    assert not is_expected_language(spanish)
    assert not is_expected_language(german)
    assert is_expected_language("too short to judge")


def test_the_language_check_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "CORPUS_LANGUAGE", "any")
    assert is_expected_language("La distinción real entre la esencia y la existencia. " * 40)


# ── the fetch stage ─────────────────────────────────────────────────────────


class _Fetcher:
    def __init__(self, texts: dict[str, str]):
        self.texts = texts

    async def fetch(self, candidate):
        return RawSource(candidate.source_type, candidate.url, candidate.title, None, self.texts[candidate.title])


def _builder(texts: dict[str, str]) -> ExpertBuilder:
    builder = ExpertBuilder.__new__(ExpertBuilder)
    builder._fetchers = {"web": (_Fetcher(texts), 3)}
    return builder


@pytest.mark.asyncio
async def test_a_non_english_text_is_dropped_before_validation():
    spanish = "La distinción real entre la esencia y la existencia es el núcleo de la metafísica. " * 30
    ranked = [TriagedCandidate(_candidate("es"), 8.0), TriagedCandidate(_candidate("en"), 8.0)]
    outcomes: dict = {}
    results, _ = await _builder({"es": spanish, "en": _prose("en", 400)})._fetch_with_refill(
        ranked, budget=5, caps={}, outcomes=outcomes
    )
    assert [r.title for r in results] == ["en"]
    assert outcomes[id(ranked[0].candidate)][1] == OUTCOME_NOT_ENGLISH
    assert outcomes[id(ranked[1].candidate)][1] == OUTCOME_FETCHED


@pytest.mark.asyncio
async def test_priority_stops_jumping_the_queue_past_its_share_of_the_money():
    long_text = _prose("long", 60_000)
    ranked = [
        TriagedCandidate(
            _candidate(f"p{i}", fetch_priority=True, priority_rank=1, text_max_chars=60_000), 2.0
        )
        for i in range(6)
    ]
    texts = {f"p{i}": long_text for i in range(6)}
    outcomes: dict = {}
    results, committed = await _builder(texts)._fetch_with_refill(
        ranked, budget=10, caps={}, budget_usd=Decimal("0.5"), floor=6.0, outcomes=outcomes
    )
    assert 0 < len(results) < 6, "priority texts may use about half the round's money, not all of it"
    assert any(o == "below_floor" for _, o in outcomes.values())


@pytest.mark.asyncio
async def test_canonical_works_are_fetched_before_concept_texts():
    ranked = [
        TriagedCandidate(_candidate("concept", fetch_priority=True, priority_rank=1), 9.0),
        TriagedCandidate(_candidate("overall", fetch_priority=True, priority_rank=0), 9.0),
    ]
    outcomes: dict = {}
    await _builder({"concept": _prose("c", 300), "overall": _prose("o", 300)})._fetch_with_refill(
        ranked, budget=5, caps={}, outcomes=outcomes
    )
    assert outcomes[id(ranked[1].candidate)][0] == 1
    assert outcomes[id(ranked[0].candidate)][0] == 2


# ── the plan ─────────────────────────────────────────────────────────────────


def test_the_plan_keeps_concept_texts_for_real_concepts_two_at_most():
    plan = _normalise_plan(
        {
            "key_concepts": ["Gravitation", "Orbits"],
            "primary_source_definition": "  Newton's own writings.  ",
            "concept_primary_texts": [
                {"concept": "gravitation", "title": "Principia", "kind": "text", "public_domain": True,
                 "sections": "Book III"},
                {"concept": "Gravitation", "title": "Opticks", "kind": "text", "public_domain": True},
                {"concept": "Gravitation", "title": "A third", "kind": "text", "public_domain": True},
                {"concept": "Invented concept", "title": "Nope", "kind": "text", "public_domain": False},
                {"concept": "Orbits", "title": "", "kind": "text", "public_domain": False},
            ],
        },
        "Newtonian mechanics",
    )
    assert plan["primary_source_definition"] == "Newton's own writings."
    assert [(t["concept"], t["title"]) for t in plan["concept_primary_texts"]] == [
        ("Gravitation", "Principia"), ("Gravitation", "Opticks"),
    ]
    assert plan["concept_primary_texts"][0]["sections"] == "Book III"


def test_tiers_look_for_more_concept_texts_as_they_deepen():
    lite, std, pro = (ExpertConfig.from_tier(t).concept_primary_texts for t in ExpertTier)
    assert (lite, std, pro) == (3, 8, 16)


# ── the follow-up round asks for primary texts ──────────────────────────────


@pytest.mark.asyncio
async def test_concepts_without_a_primary_source_get_primary_texts_looked_up_by_title(monkeypatch):
    suggested = [{"concept": "orbits", "title": "Principia", "author": "Newton", "kind": "text",
                  "public_domain": True, "sections": "Book I"}]
    suggest = AsyncMock(return_value=suggested)
    monkeypatch.setattr("peritus.experts.builder.suggest_primary_texts", suggest)
    found = _candidate("Principia", fetch_priority=True)

    builder = ExpertBuilder(MagicMock())
    builder._fetchers = {"exa": (None, 5)}
    builder._canonical = []
    builder._primary_definition = "Newton's own writings"
    builder._resolve_canonical = AsyncMock(return_value=[found])
    events: list[dict] = []

    async def on_event(e):
        events.append(e)

    with (
        patch("peritus.experts.builder.feedback_queries", AsyncMock(return_value={"orbits": ["q"]})),
        patch("peritus.experts.builder.snowball", AsyncMock(return_value=[])),
    ):
        _, candidates = await builder._plan_round(
            "Newtonian mechanics",
            [ConceptCoverage("orbits", sources=3, primary=0)],
            [], MagicMock(), ExpertConfig.from_tier(ExpertTier.STANDARD), on_event, 1,
        )
    assert candidates == [found]
    suggest.assert_awaited_once()
    assert suggest.await_args.args[2] == ["orbits"]
    [work] = builder._resolve_canonical.await_args.args[0]
    assert (work.title, work.scope, work.sections) == ("Principia", SCOPE_CONCEPT, "Book I")
    assert any(e["type"] == "primary_texts_suggested" for e in events)


@pytest.mark.asyncio
async def test_suggestions_are_held_to_the_concepts_asked_about_and_not_repeated():
    from peritus.experts import feedback

    class _Client:
        class messages:  # noqa: N801 — mirrors the SDK's attribute
            @staticmethod
            async def create(**_kwargs):
                block = MagicMock(type="tool_use")
                block.input = {"texts": [
                    {"concept": "ORBITS", "title": "Principia", "kind": "text", "public_domain": True},
                    {"concept": "orbits", "title": "Already Tried", "kind": "text", "public_domain": True},
                    {"concept": "made up", "title": "X", "kind": "text", "public_domain": True},
                    {"concept": "orbits", "title": "Second", "kind": "weird", "public_domain": "yes"},
                    {"concept": "orbits", "title": "Third", "kind": "text", "public_domain": True},
                ]}
                return MagicMock(content=[block])

    with patch.object(feedback, "get_anthropic_client", lambda: _Client()):
        out = await feedback.suggest_primary_texts("t", "def", ["orbits"], ["already tried"])
    assert [(t["concept"], t["title"], t["kind"], t["public_domain"]) for t in out] == [
        ("orbits", "Principia", "text", True), ("orbits", "Second", "book", False),
    ]


# ── the validator is told what primary means ────────────────────────────────


def test_the_validator_is_shown_the_topics_definition_of_primary():
    from peritus.sources.validator import _validate_params

    params = _validate_params(
        "Clinical hypertension",
        [RawSource(SourceType.WEB, "https://x", "T", None, "body " * 200)],
        [],
        primary_definition="Randomised controlled trials and the guidelines themselves.",
    )
    content = params["messages"][0]["content"]
    assert "a PRIMARY source is: Randomised controlled trials" in content
    assert "PRIMARY source" not in _validate_params("t", [], [])["messages"][0]["content"]


# ── priors ───────────────────────────────────────────────────────────────────


def test_pirate_mirrors_are_penalised_hard():
    for url in ("https://docplayer.net/123-A-Book.html", "https://dokumen.pub/a-book.html", "https://ebin.pub/x.html"):
        assert domain_adjustment(url) <= -5.0


# ── the graph stage ─────────────────────────────────────────────────────────


def test_nodes_sent_as_a_json_string_are_decoded_not_discarded():
    from peritus.graph.extractor import _parse_extract_response

    class _Block:
        type = "tool_use"

        def __init__(self, payload):
            self.input = payload

    class _Response:
        stop_reason = "tool_use"

        def __init__(self, payload):
            self.content = [_Block(payload)]

    nodes = [{"label": "Inertia", "node_type": "concept", "description": "d", "chunk_indices": [0]}]
    result = _parse_extract_response(_Response({"nodes": json.dumps(nodes), "edges": "[]"}), [7])
    assert [n["label"] for n in result["nodes"]] == ["Inertia"]
    assert result["nodes"][0]["chunk_db_ids"] == [7]

    truncated = json.dumps(nodes + nodes)[:-20]
    result = _parse_extract_response(_Response({"nodes": truncated, "edges": []}), [7])
    assert [n["label"] for n in result["nodes"]] == ["Inertia"], "complete objects of a cut-off string survive"


def test_graph_extraction_reads_a_bounded_number_of_chunks_per_source(monkeypatch):
    monkeypatch.setattr(settings, "GRAPH_MAX_CHUNKS_PER_SOURCE", 80)
    assert _graph_chunk_limit(30) == 30
    assert _graph_chunk_limit(200) == 80
    monkeypatch.setattr(settings, "GRAPH_MAX_CHUNKS_PER_SOURCE", 0)
    assert _graph_chunk_limit(200) == 200


def test_a_specification_s_bare_numbered_headings_count_as_sections():
    spec = "Request for Comments\n\nTable of Contents\n" + "".join(
        f"\n{n}.  Title Number {n}\n\n{_prose(f's{n}', 200)}\n" for n in range(1, 12)
    ) + "\nSection 4 of the licence applies.\n"
    selection = select_sections(spec, "Section 9", 100_000)
    assert selection.matched
    assert "the s9 of" in selection.text and "the s10 of" not in selection.text
    markdown = spec.replace("\n9.  Title", "\n## 9. Title")
    assert "the s9 of" in select_sections(markdown, "Section 9", 100_000).text


def test_an_abstract_only_record_names_a_paper_but_does_not_stop_the_search():
    from peritus.sources.canonical import WorkResolution

    record = _candidate("A Paper", must_have_extent=EXTENT_WHOLE, abstract_only_hit=True)
    assert not WorkResolution(MustHaveWork("A Paper", kind="paper"), [record]).whole


def test_the_catalogue_route_rejects_a_different_book_with_the_title_inside_it():
    from peritus.sources.canonical import names_the_work

    assert not names_the_work(
        "The Foundations of the Origin of Species", "On the Origin of Species", "Charles Darwin"
    )
