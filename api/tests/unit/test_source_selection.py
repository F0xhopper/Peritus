"""Source selection: triage that fails closed, a fetch floor, canonical works found
whole, substance, and the corpus composition a build reports.

Every case here is one the Thomism build (expert 55, job 53) got wrong — see
docs/plans/source-selection.md. No network, no models.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from peritus.core.config import settings
from peritus.experts.builder import (
    OUTCOME_BELOW_FLOOR,
    OUTCOME_CAPPED,
    OUTCOME_FAILED,
    OUTCOME_FETCHED,
    ExpertBuilder,
    _safe_search,
)
from peritus.experts.composition import (
    DROP_ABSTRACT_TOO_SHORT,
    DROP_TERTIARY_OVER_SHARE,
    apply_composition_caps,
    corpus_composition,
)
from peritus.experts.coverage import ConceptCoverage
from peritus.experts.feedback import weak_concepts_block
from peritus.infrastructure.gutenberg_catalogue import GutenbergCatalogue
from peritus.sources import canonical as canonical_module
from peritus.sources import triage as triage_module
from peritus.sources.canonical import (
    EXTENT_PARTIAL,
    EXTENT_WHOLE,
    FOUND_PARTIAL,
    FOUND_WHOLE,
    NOT_FOUND,
    ROUTE_ARCHIVE,
    ROUTE_EXA,
    ROUTE_EXA_PRIMARY,
    ROUTE_GUTENBERG,
    MustHaveWork,
    classify_extent,
    must_have_outcomes,
    resolve_works,
)
from peritus.sources.domain import (
    DroppedSource,
    RawSource,
    SourceCandidate,
    SourceType,
    ValidatedSource,
)
from peritus.sources.fetchers.base import (
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_RATE_LIMITED,
    STATUS_TIMEOUT,
    note_search_failure,
)
from peritus.sources.fetchers.openalex import prefer_readable
from peritus.sources.substance import (
    SUBSTANCE_ABSTRACT,
    SUBSTANCE_FULL,
    SUBSTANCE_PARTIAL,
    substance_of,
)
from peritus.sources.triage import (
    STATUS_MUST_HAVE,
    STATUS_PRIORITY,
    STATUS_REASKED,
    STATUS_SCORED,
    STATUS_UNSCORED,
    TriagedCandidate,
    _parse_triage_response,
    domain_adjustment,
    penalised_hosts,
    rank_candidates,
    triage_candidates,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _candidate(title: str, url: str = "", st: SourceType = SourceType.WEB, **meta) -> SourceCandidate:
    return SourceCandidate(
        source_type=st,
        url=url or f"https://x.test/{title.replace(' ', '-')}",
        title=title,
        author=None,
        snippet="",
        metadata=dict(meta),
    )


class _Block:
    type = "tool_use"

    def __init__(self, scores):
        self.input = {"scores": scores}


class _Response:
    def __init__(self, scores):
        self.content = [_Block(scores)]


def _scripted_triage(*scripts):
    """Serve successive gather_claude_calls from scripts of ``{title: score}``.

    A script entry of ``None`` fails that whole call. Scores are echoed back by
    the id each candidate was given in the prompt, as the model is asked to.
    """
    calls: list[list[str]] = []
    queue = list(scripts)

    async def _gather(params, live_concurrency=None, description="", on_result=None):
        script = queue.pop(0) if queue else {}
        responses = []
        for p in params:
            content = p["messages"][0]["content"]
            titles = [
                line.removeprefix("Title: ")
                for line in content.splitlines()
                if line.startswith("Title: ")
            ]
            calls.append(titles)
            if script is None:
                responses.append(None)
                continue
            responses.append(
                _Response(
                    [
                        {"id": f"candidate_{i}", "expected_value": script[t]}
                        for i, t in enumerate(titles)
                        if t in script
                    ]
                )
            )
        return responses

    return patch.object(triage_module, "gather_claude_calls", _gather), calls


# ── 2.A: scores by id ────────────────────────────────────────────────────────


def test_scores_map_by_id_not_position():
    """A response that skips one entry in the middle must not shift every later
    score onto the wrong candidate."""
    resp = _Response(
        [
            {"id": "candidate_0", "expected_value": 8},
            {"id": "candidate_2", "expected_value": 1},
            {"id": "<candidate_3>", "expected_value": 7},
        ]
    )
    assert _parse_triage_response(resp, 4) == {0: 8.0, 2: 1.0, 3: 7.0}


def test_unreadable_duplicate_and_out_of_range_entries_are_ignored():
    resp = _Response(
        [
            {"id": "candidate_0", "expected_value": 4},
            {"id": "candidate_0", "expected_value": 9},  # repeat: first wins
            {"id": "candidate_7", "expected_value": 9},  # outside the batch
            {"id": "nonsense", "expected_value": 9},
            {"id": "candidate_1", "expected_value": "high"},
            "not an object",
            {"id": "candidate_2", "expected_value": 42},  # clamped
        ]
    )
    assert _parse_triage_response(resp, 3) == {0: 4.0, 2: 10.0}


# ── 2.B: re-ask, then fail closed ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_failed_batch_never_scores_anything_at_five():
    """The fallback 5.0 outranked every honest 3 and 4 and fetched an actress."""
    candidates = [_candidate(f"c{i}") for i in range(4)]
    stub, calls = _scripted_triage(None, None, None)
    with stub:
        triaged = await triage_candidates("Thomism", [], [], candidates)

    assert len(calls) == 3, "the first pass, then one call at each re-ask size"
    assert all(len(c) == 4 for c in calls), "every candidate is re-asked each time"
    assert all(t.score == 0.0 for t in triaged)
    assert all(t.model_score is None for t in triaged)
    assert all(t.status == STATUS_UNSCORED for t in triaged)
    assert rank_candidates(triaged) == [], "unscored candidates are never fetched"


@pytest.mark.asyncio
async def test_a_partly_scored_batch_re_asks_only_the_missing():
    candidates = [_candidate("Summa"), _candidate("Tracie Thoms"), _candidate("Aeterni Patris")]
    stub, calls = _scripted_triage(
        {"Summa": 9, "Tracie Thoms": 0},  # skipped one
        {"Aeterni Patris": 7},
    )
    with stub:
        triaged = await triage_candidates("Thomism", [], [], candidates)

    assert calls[1] == ["Aeterni Patris"], "only the unscored candidate is re-asked"
    by_title = {t.candidate.title: t for t in triaged}
    assert by_title["Summa"].status == STATUS_SCORED
    assert by_title["Aeterni Patris"].status == STATUS_REASKED
    assert by_title["Aeterni Patris"].model_score == 7.0
    assert by_title["Tracie Thoms"].score == 0.0
    assert by_title["Tracie Thoms"].status == STATUS_SCORED


@pytest.mark.asyncio
async def test_an_unscored_must_have_is_still_fetched():
    stub, _ = _scripted_triage(None, None, None)
    candidates = [
        _candidate("Summa Theologica, Part I-II (Pars Prima Secundae)"),
        _candidate("A snowball find", fetch_priority=True),
        _candidate("Unrelated"),
    ]
    with stub:
        triaged = await triage_candidates("Thomism", [], ["Summa Theologica"], candidates)

    statuses = {t.candidate.title: t.status for t in triaged}
    assert statuses["Summa Theologica, Part I-II (Pars Prima Secundae)"] == STATUS_MUST_HAVE
    assert statuses["A snowball find"] == STATUS_PRIORITY
    ranked_titles = {t.candidate.title for t in rank_candidates(triaged)}
    assert ranked_titles == {
        "Summa Theologica, Part I-II (Pars Prima Secundae)",
        "A snowball find",
    }


@pytest.mark.asyncio
async def test_a_must_have_fragment_is_marked_partial_not_found():
    """One question of the Summa satisfied "Summa Theologiae" on job 53."""
    stub, _ = _scripted_triage({"SUMMA THEOLOGIAE: The natural law (Prima Secundae Partis, Q. 94)": 6})
    fragment = _candidate(
        "SUMMA THEOLOGIAE: The natural law (Prima Secundae Partis, Q. 94)",
        "https://www.newadvent.org/summa/2094.htm",
    )
    with stub:
        [item] = await triage_candidates("Thomism", [], ["Summa Theologiae"], [fragment])

    assert item.candidate.metadata["fetch_priority"] is True
    assert item.candidate.metadata["must_have_title"] == "Summa Theologiae"
    assert item.candidate.metadata["must_have_extent"] == EXTENT_PARTIAL


# ── 2.D: priors for what the model mis-scores ────────────────────────────────


def test_a_catalogue_page_on_a_government_host_nets_negative():
    assert domain_adjustment("https://www.loc.gov/catdir/toc/ecip0415/2004012345.html") == -2.5


def test_library_catalogue_hosts_are_penalised():
    for url in (
        "https://ci.nii.ac.jp/ncid/BA12345678",
        "https://catalog.loc.gov/vwebv/search?x=1",
        "https://www.worldcat.org/title/12345",
        "https://bvbr.bib-bvb.de/F?func=find",
    ):
        assert domain_adjustment(url) <= -4.0, url


def test_choice_reviews_lose_the_doi_boost():
    assert domain_adjustment("https://doi.org/10.5860/choice.42-1234") == pytest.approx(-1.5)
    assert domain_adjustment("https://doi.org/10.1017/abc") == 1.5


def test_wiki_mirrors_are_nudged_down_but_real_wikis_are_not():
    assert domain_adjustment("https://en.wikipedia.org/wiki/Thomism") == 0.0
    assert domain_adjustment("https://en.wikisource.org/wiki/Summa") == 0.0
    assert domain_adjustment("https://www.newworldencyclopedia.org/wiki/Thomism") == -1.0


def test_overview_mills_are_penalised():
    assert domain_adjustment("https://studyguides.com/thomism") == -3.0


def test_penalised_hosts_are_domains_only_and_hard_penalties_only():
    hosts = penalised_hosts()
    assert "goodreads.com" in hosts
    assert "worldcat.org" in hosts
    assert "medium.com" not in hosts, "a nudge is not an exclusion"
    assert all("/" not in h and not h.startswith(".") for h in hosts)


# ── 2.C: the fetch floor ─────────────────────────────────────────────────────


class _Fetcher:
    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        if candidate.metadata.get("fail"):
            return None
        return RawSource(candidate.source_type, candidate.url, candidate.title, None, "x" * 2000)


def _builder() -> ExpertBuilder:
    builder = ExpertBuilder.__new__(ExpertBuilder)
    builder._fetchers = {"web": (_Fetcher(), 3), "exa": (_Fetcher(), 3)}
    return builder


@pytest.mark.asyncio
async def test_the_floor_is_a_bar_beside_the_count_not_instead_of_it():
    ranked = [
        TriagedCandidate(_candidate("strong"), 8.0),
        TriagedCandidate(_candidate("weak"), 4.0),
        TriagedCandidate(_candidate("must-have", fetch_priority=True), 0.0),
    ]
    outcomes: dict = {}
    results, _ = await _builder()._fetch_with_refill(
        ranked, budget=10, caps={}, floor=6.0, outcomes=outcomes
    )
    assert {r.title for r in results} == {"strong", "must-have"}
    by_title = {t.candidate.title: outcomes[id(t.candidate)] for t in ranked}
    assert by_title["weak"] == (None, OUTCOME_BELOW_FLOOR)
    assert by_title["strong"][1] == OUTCOME_FETCHED
    assert by_title["must-have"] == (1, OUTCOME_FETCHED), "priority is fetched first"


@pytest.mark.asyncio
async def test_every_ranked_candidate_gets_an_outcome():
    ranked = [
        TriagedCandidate(_candidate("a"), 9.0),
        TriagedCandidate(_candidate("b", fail=True), 8.5),
        TriagedCandidate(_candidate("c", st=SourceType.EXA), 8.0),
        TriagedCandidate(_candidate("d", st=SourceType.EXA), 7.9),
    ]
    outcomes: dict = {}
    await _builder()._fetch_with_refill(
        ranked, budget=10, caps={SourceType.EXA: 1}, floor=6.0, outcomes=outcomes
    )
    assert [outcomes[id(t.candidate)][1] for t in ranked] == [
        OUTCOME_FETCHED, OUTCOME_FAILED, OUTCOME_FETCHED, OUTCOME_CAPPED,
    ]


@pytest.mark.asyncio
async def test_a_must_have_work_is_exempt_from_the_type_cap():
    ranked = [
        TriagedCandidate(_candidate("paper", st=SourceType.EXA), 9.0),
        TriagedCandidate(
            _candidate("Summa", st=SourceType.EXA, fetch_priority=True, must_have_title="Summa"),
            9.0,
        ),
    ]
    results, _ = await _builder()._fetch_with_refill(
        ranked, budget=10, caps={SourceType.EXA: 1}, floor=6.0
    )
    assert {r.title for r in results} == {"paper", "Summa"}


@pytest.mark.asyncio
async def test_fetched_sources_carry_their_triage_score_and_must_have_facts():
    candidate = _candidate(
        "Summa", fetch_priority=True, must_have_title="Summa", must_have_extent=EXTENT_WHOLE
    )
    [source], _ = await _builder()._fetch_with_refill(
        [TriagedCandidate(candidate, 9.0)], budget=1, caps={}
    )
    assert source.metadata["triage_score"] == 9.0
    assert source.metadata["must_have_title"] == "Summa"
    assert source.metadata["must_have_extent"] == EXTENT_WHOLE


# ── 0.C: search outcomes ─────────────────────────────────────────────────────


class _SearchStub:
    def __init__(self, results=None, note=None, raise_=None):
        self.results, self.note, self.raise_ = results or [], note, raise_

    async def search(self, query, max_results):
        if self.raise_:
            raise self.raise_
        if self.note:
            note_search_failure(*self.note)
        return self.results


@pytest.mark.asyncio
async def test_a_swallowed_failure_is_reported_as_itself_not_as_empty():
    outcome = await _safe_search(
        "gutenberg", _SearchStub(note=(STATUS_TIMEOUT, "Gutendex timed out after 10s")), "q", 5
    )
    assert outcome.status == STATUS_TIMEOUT
    assert "Gutendex" in outcome.error
    assert outcome.transient


@pytest.mark.asyncio
async def test_search_outcomes_distinguish_empty_ok_and_raised():
    assert (await _safe_search("wikipedia", _SearchStub(), "q", 5)).status == STATUS_EMPTY
    ok = await _safe_search("wikipedia", _SearchStub(results=[_candidate("x")]), "q", 5)
    assert ok.status == STATUS_OK
    raised = await _safe_search("pdf", _SearchStub(raise_=RuntimeError("HTTP 429 Too Many Requests")), "q", 5)
    assert raised.status == STATUS_RATE_LIMITED
    boom = await _safe_search("pdf", _SearchStub(raise_=ValueError("bad json")), "q", 5)
    assert boom.status == STATUS_ERROR


# ── 7.B: canonical works ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("title", "url", "extent"),
    [
        ("Summa Theologica", "", EXTENT_WHOLE),
        ("SUMMA THEOLOGIAE: The natural law (Prima Secundae Partis, Q. 94)", "", EXTENT_PARTIAL),
        ("Summa Theologica, Part I-II (Pars Prima Secundae)", "", EXTENT_PARTIAL),
        ("Summa Contra Gentiles, Book Three: Providence", "", EXTENT_PARTIAL),
        ("On Being and Essence, Chapter 4", "", EXTENT_PARTIAL),
        ("The Book of Job", "", EXTENT_WHOLE),
        ("Part and Whole in Aristotle", "", EXTENT_WHOLE),
        ("Question of the day", "https://www.newadvent.org/summa/1002.htm", EXTENT_PARTIAL),
    ],
)
def test_extent_classification(title, url, extent):
    assert classify_extent(title, url) == extent


@pytest.mark.parametrize(
    ("title", "wanted", "author", "expected"),
    [
        ("The Cambridge Companion To The Summa Theologiae", "Summa Theologiae", "", False),
        ("Elements of moral theology, based on the Summa Theologiae", "Summa Theologiae", "", False),
        ("Summa Theologica, Part I-II (Pars Prima Secundae)", "Summa Theologiae", "", True),
        ("St. Thomas Aquinas The Summa Contra Gentiles", "Summa Contra Gentiles", "Thomas Aquinas", True),
        ("Concerning being and essence = (De ente et essentia)", "De Ente et Essentia", "", True),
        ("The Meditations of Marcus Aurelius", "Meditations", "", True),
        ("A blog post about breakfast", "Meditations", "", False),
    ],
)
def test_a_title_about_a_work_is_not_the_work(title, wanted, author, expected):
    from peritus.sources.canonical import names_the_work

    assert names_the_work(title, wanted, author) is expected


def test_ocr_noise_is_not_prose():
    from peritus.sources.canonical import looks_like_prose

    assert looks_like_prose("The natural law is nothing else than the rational creature's participation. " * 200)
    assert not looks_like_prose('c    %  X^>    AkA^y    UA    flli*  n^.\'  0J"r    tyw^  I  /u"f ' * 300)


def test_an_archive_volume_is_partial_whatever_its_title():
    assert classify_extent("The Summa contra gentiles", volume="1") == EXTENT_PARTIAL


_CSV = """Text#,Type,Issued,Title,Language,Authors,Subjects,LoCC,Bookshelves
17611,Text,2006-01-01,"Summa Theologica, Part I (Prima Pars)
From the Complete American Edition",en,"Thomas, Aquinas, Saint, 1225?-1274",Theology,,
18755,Text,2006-01-01,"Summa Theologica, Part I-II (Pars Prima Secundae)",en,"Thomas, Aquinas, Saint",,,
2680,Text,2001-01-01,Meditations,en,"Marcus Aurelius, Emperor of Rome, 121-180",Stoics,,
9999,Text,2001-01-01,Meditations on the Summa,en,"Someone, Else",Commentary,,
5555,Text,2001-01-01,Meditationes,la,"Marcus Aurelius, Emperor of Rome, 121-180",Stoics,,
7777,Sound,2001-01-01,Meditations,en,"Marcus Aurelius, Emperor of Rome, 121-180",Stoics,,
"""


def test_the_catalogue_keeps_english_texts_and_resolves_close_spellings():
    catalogue = GutenbergCatalogue.from_csv_text(_CSV)
    assert len(catalogue) == 4, "Latin and audio records are dropped"

    ids = [b.id for b in catalogue.resolve("Summa Theologiae", "Thomas Aquinas", 5)]
    assert set(ids) == {17611, 18755}, "'Theologiae' finds 'Theologica'"

    [meditations] = catalogue.resolve("Meditations", "Marcus Aurelius")
    assert meditations.id == 2680
    assert meditations.text_url == "https://www.gutenberg.org/cache/epub/2680/pg2680.txt"


@pytest.mark.asyncio
async def test_the_resolver_stops_at_the_first_whole_hit():
    tried: list[str] = []

    async def gutenberg(work, _exa):
        tried.append(ROUTE_GUTENBERG)
        return [_candidate("Summa Theologica, Part I-II", must_have_extent=EXTENT_PARTIAL)]

    async def archive(work, _exa):
        tried.append(ROUTE_ARCHIVE)
        return [_candidate("The Summa Theologica", must_have_extent=EXTENT_WHOLE)]

    async def exa_primary(work, _exa):  # pragma: no cover — must not be reached
        tried.append(ROUTE_EXA_PRIMARY)
        return []

    with (
        patch.object(canonical_module, "_gutenberg_route", gutenberg),
        patch.object(canonical_module, "_archive_route", archive),
        patch.object(canonical_module, "_exa_primary_route", exa_primary),
    ):
        [resolution] = await resolve_works(
            [MustHaveWork("Summa Theologica", "Aquinas", "text", True, "Prima Secundae")],
            exa_search=object(),
        )

    assert tried == [ROUTE_GUTENBERG, ROUTE_ARCHIVE]
    assert resolution.whole
    priority = [c.title for c in resolution.candidates if c.metadata.get("fetch_priority")]
    assert priority == ["The Summa Theologica"], "only the best hit — the whole one — jumps the queue"
    assert {c.metadata["discovered_via"] for c in resolution.candidates} == {"canonical"}


@pytest.mark.asyncio
async def test_a_failed_route_is_recorded_and_the_next_one_tried():
    async def boom(work, _exa):
        raise TimeoutError("catalogue download timed out")

    async def exa_open(work, _exa):
        return [_candidate("Some Paper", must_have_extent=EXTENT_WHOLE)]

    async def nothing(work, _exa):
        return []

    with (
        patch.object(canonical_module, "_gutenberg_route", boom),
        patch.object(canonical_module, "_archive_route", nothing),
        patch.object(canonical_module, "_exa_primary_route", nothing),
        patch.object(canonical_module, "_exa_open_route", exa_open),
    ):
        [resolution] = await resolve_works(
            [MustHaveWork("Some Paper", public_domain=True)], exa_search=object()
        )
    assert resolution.routes_tried == [ROUTE_GUTENBERG, ROUTE_ARCHIVE, ROUTE_EXA_PRIMARY, ROUTE_EXA]
    assert ROUTE_GUTENBERG in resolution.route_errors
    assert resolution.whole


@pytest.mark.asyncio
async def test_a_non_public_domain_book_skips_the_public_domain_routes():
    with patch.object(canonical_module, "_exa_primary_route", lambda w, e: _async([])), \
         patch.object(canonical_module, "_exa_open_route", lambda w, e: _async([])):
        [resolution] = await resolve_works(
            [MustHaveWork("Aquinas", kind="book", open_text=True)], exa_search=object()
        )
    assert resolution.routes_tried == [ROUTE_EXA_PRIMARY, ROUTE_EXA]


async def _async(value):
    return value


def test_must_have_outcomes_are_judged_on_the_accepted_corpus():
    works = [
        MustHaveWork("Summa Theologiae", public_domain=True),
        MustHaveWork("Summa Contra Gentiles", public_domain=True),
        MustHaveWork("De Ente", public_domain=True),
    ]
    passed = [
        ("https://a", {"must_have_title": "Summa Theologiae", "must_have_extent": EXTENT_PARTIAL}),
        ("https://b", {"must_have_title": "Summa Contra Gentiles", "must_have_extent": EXTENT_WHOLE}),
        ("https://c", {"must_have_title": "Summa Contra Gentiles", "must_have_extent": EXTENT_PARTIAL}),
    ]
    outcomes = {o["title"]: o for o in must_have_outcomes(works, [], passed)}
    assert outcomes["Summa Theologiae"]["status"] == FOUND_PARTIAL
    assert outcomes["Summa Contra Gentiles"]["status"] == FOUND_WHOLE
    assert outcomes["Summa Contra Gentiles"]["source_urls"] == ["https://b"]
    assert outcomes["De Ente"]["status"] == NOT_FOUND


# ── 4.A: substance ───────────────────────────────────────────────────────────


def _raw(chars: int, **meta) -> RawSource:
    return RawSource(SourceType.OPENALEX, "https://x.test", "T", None, "x" * chars, metadata=meta)


def test_substance_of_a_source():
    assert substance_of(_raw(40_000, full_text_method="europepmc_jats")) == SUBSTANCE_FULL
    assert substance_of(_raw(40_000, full_text_method="abstract")) == SUBSTANCE_ABSTRACT
    assert substance_of(_raw(1_484)) == SUBSTANCE_ABSTRACT, "the LoC table of contents"
    assert substance_of(_raw(9_000, full_text_method="oa_landing_html")) == SUBSTANCE_PARTIAL
    assert substance_of(_raw(200_000, truncated=True)) == SUBSTANCE_PARTIAL


# ── 4.A/4.B: composition caps ────────────────────────────────────────────────


def _vs(title: str, tier: str = "secondary", substance: str = SUBSTANCE_FULL, q=8.0, r=8.0, abstract=900):
    return ValidatedSource(
        raw=RawSource(
            SourceType.OPENALEX, f"https://x.test/{title}", title, None, "x" * 2000,
            metadata={"abstract": "a" * abstract},
        ),
        quality_score=q,
        relevance_score=r,
        content_type="paper",
        difficulty=3,
        key_claims=[],
        covered_concepts=["natural law"],
        source_tier=tier,
        substance=substance,
    )


def test_abstract_stubs_are_dropped_but_shares_are_not_capped_by_default():
    """Primary texts must be present; overviews and abstracts beside them are fine."""
    passed = [_vs(f"full{i}") for i in range(4)] + [
        _vs(f"abstract{i}", substance=SUBSTANCE_ABSTRACT) for i in range(4)
    ] + [_vs(f"overview{i}", tier="tertiary") for i in range(4)] + [
        _vs("blurb", substance=SUBSTANCE_ABSTRACT, abstract=300),
    ]
    kept, dropped = apply_composition_caps(passed)
    assert [(d.raw.title, d.drop_reason) for d in dropped] == [("blurb", DROP_ABSTRACT_TOO_SHORT)]
    assert len(kept) == 12


def test_share_caps_still_work_when_switched_on(monkeypatch):
    monkeypatch.setattr(settings, "COMPOSITION_ABSTRACT_SHARE_CAP", 0.15)
    monkeypatch.setattr(settings, "COMPOSITION_TERTIARY_SHARE_CAP", 0.25)
    passed = [_vs(f"full{i}") for i in range(14)] + [
        _vs("stub-best", substance=SUBSTANCE_ABSTRACT, q=9, r=9),
        _vs("stub-mid", substance=SUBSTANCE_ABSTRACT, q=8, r=8),
        _vs("stub-worst", substance=SUBSTANCE_ABSTRACT, q=6, r=6),
    ] + [
        _vs("wikipedia", tier="tertiary", r=9),
        _vs("studyguides", tier="tertiary", r=7),
        _vs("guide2", tier="tertiary", r=7),
        _vs("guide3", tier="tertiary", r=6.5),
        _vs("guide4", tier="tertiary", r=6.2),
        _vs("listicle", tier="tertiary", r=6),
    ]
    _, dropped = apply_composition_caps(passed)
    reasons = {d.raw.title: d.drop_reason for d in dropped}
    # 23 accepted → 3 abstract-only and 5 tertiary allowed.
    assert reasons == {"listicle": DROP_TERTIARY_OVER_SHARE}


def test_a_small_round_keeps_its_one_overview():
    kept, dropped = apply_composition_caps([_vs("a"), _vs("b"), _vs("overview", tier="tertiary")])
    assert dropped == [] and len(kept) == 3


def test_corpus_composition_reports_the_numbers_the_plan_is_judged_by():
    passed = [
        _vs("primary", tier="primary"),
        _vs("stub", substance=SUBSTANCE_ABSTRACT),
        _vs("guide", tier="tertiary"),
        _vs("paper"),
    ]
    passed[0].covered_concepts = ["natural law", "metaphysics"]
    dropped = [
        DroppedSource(_raw(5000), 0.0, 0.0, "below threshold"),     # judged junk
        DroppedSource(_raw(5000), 0.0, 0.0, "duplicate of https://y"),  # not a verdict
        DroppedSource(_raw(5000), 0.0, 0.0, "validation error"),    # not a verdict
        DroppedSource(_raw(5000), 7.0, 5.0, "below threshold"),
    ]
    corpus = corpus_composition(
        passed, dropped, ["natural law", "metaphysics", "epistemology"],
        must_have=[{"title": "Summa", "status": FOUND_WHOLE}],
    )
    assert corpus["primary_share"] == 0.25
    assert corpus["tertiary_share"] == 0.25
    assert corpus["abstract_only_share"] == 0.25
    assert corpus["junk_fetched"] == 1
    assert corpus["concept_shares"]["natural law"] == 1.0
    assert corpus["concepts_without_primary"] == ["epistemology"]
    assert corpus["must_have"] == [{"title": "Summa", "status": FOUND_WHOLE}]


# ── 5.D: what the feedback round is told ─────────────────────────────────────


def test_the_feedback_round_is_told_what_lacks_a_primary_and_what_is_heavy():
    block = weak_concepts_block(
        [ConceptCoverage("metaphysics", sources=3, primary=0), ConceptCoverage("ethics", sources=2, primary=1)],
        [("natural law", 0.56)],
    )
    assert "metaphysics — 3 accepted source(s), primary: none" in block
    assert "ethics — 2 accepted source(s)\n" in block + "\n"
    assert "natural law: 56%" in block


# ── 6: OpenAlex prefers works with a route to text ───────────────────────────


def test_openalex_puts_readable_works_first_keeping_relevance_order():
    records = [
        _candidate("catalogue record", st=SourceType.OPENALEX),
        _candidate("oa paper", st=SourceType.OPENALEX, oa_pdf_url="https://x/p.pdf"),
        _candidate("another record", st=SourceType.OPENALEX),
        _candidate("pmc paper", st=SourceType.OPENALEX, pmcid="PMC1"),
    ]
    assert [c.title for c in prefer_readable(records)] == [
        "oa paper", "pmc paper", "catalogue record", "another record",
    ]


def test_the_floor_setting_defaults_are_what_the_plan_says():
    assert settings.FETCH_SCORE_FLOOR == 6.0
    assert settings.FETCH_SCORE_FLOOR_RELAXED == 5.0


def test_a_must_have_mark_survives_an_identity_merge():
    from peritus.sources.dedup import deduplicate_candidates
    from peritus.sources.domain import Identifiers

    plain = _candidate("Summa", "https://a.test/summa", st=SourceType.OPENALEX)
    plain.identifiers = Identifiers.build(doi="10.1234/summa")
    marked = _candidate(
        "Summa", "https://b.test/summa", st=SourceType.EXA,
        fetch_priority=True, must_have_title="Summa", must_have_extent=EXTENT_WHOLE,
    )
    marked.identifiers = Identifiers.build(doi="10.1234/summa")
    [kept], _ = deduplicate_candidates([plain, marked])
    assert kept.metadata["must_have_title"] == "Summa"
    assert kept.metadata["fetch_priority"] is True
