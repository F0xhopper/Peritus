"""Citation snowballing: ranking, thresholds, and what it refuses to propose.

Offline — the Semantic Scholar calls are served by a stub client, so the ranking
rules are what is under test rather than the API.
"""

from unittest.mock import patch

import pytest

from peritus.sources import snowball as snowball_module
from peritus.sources.dedup import SeenSet
from peritus.sources.domain import Identifiers, RawSource, SourceType, ValidatedSource
from peritus.sources.snowball import (
    DISCOVERED_BACKWARD,
    DISCOVERED_FORWARD,
    seed_ids,
    snowball,
)


def _seed(url: str, **ids) -> ValidatedSource:
    return ValidatedSource(
        raw=RawSource(
            SourceType.OPENALEX,
            url,
            "Seed",
            None,
            "text",
            identifiers=Identifiers.build(**ids),
        ),
        quality_score=8.0,
        relevance_score=8.0,
        content_type="paper",
        difficulty=4,
        key_claims=[],
        source_tier="secondary",
    )


_ABSTRACT = (
    "A substantive abstract, long enough that the openalex fetcher these "
    "candidates are routed to will accept it as a source in its own right "
    "rather than returning None for want of anything to ingest. It has to "
    "clear two hundred characters to do that."
)
assert len(_ABSTRACT) >= 200


def _paper(title: str, citations: int, doi: str, abstract: str = _ABSTRACT, **extra) -> dict:
    return {
        "title": title,
        "abstract": abstract,
        "citationCount": citations,
        "year": 2019,
        "paperId": f"s2-{doi}",
        "authors": [{"name": "A. Author"}],
        "externalIds": {"DOI": doi},
        **extra,
    }


def _tail(prefix: str, n: int = 9) -> list[dict]:
    """A realistic reference list's long tail: papers nobody singled out.

    Every test needs one. A percentile has no meaning in a list of one, and a
    reference list of one is not a case the ranking should have an opinion
    about — real lists have tens of entries and most of them are background.
    """
    return [_paper(f"{prefix} tail {i}", 1, f"10.9999/{prefix}{i}") for i in range(n)]


class _Response:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


def _stub_http(by_edge: dict[str, dict[str, list[dict]]]):
    """Serve /references and /citations per seed key.

    ``by_edge[edge][seed_key]`` is the list of papers that edge returns.
    """

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            _, _, tail = url.partition("/paper/")
            seed_key, _, edge = tail.rpartition("/")
            field = "citedPaper" if edge == "references" else "citingPaper"
            papers = by_edge.get(edge, {}).get(seed_key, [])
            return _Response({"data": [{field: p} for p in papers]})

    # See test_pubmed_fetcher: patch the `shared_client` seam, not httpx.
    return patch.object(snowball_module, "shared_client", lambda **kw: _Client())


# ── seeds ────────────────────────────────────────────────────────────────────


def test_seeds_come_only_from_sources_semantic_scholar_can_resolve():
    """A junk paper's references never enter, because only *accepted* sources
    are passed in — and one with no identifier at all cannot be looked up."""
    seeds = seed_ids(
        [
            _seed("https://a.test", arxiv_id="2001.01234"),
            _seed("https://b.test", doi="10.1234/x"),
            _seed("https://c.test", pmid="99"),
            _seed("https://d.test"),  # no identifiers — not resolvable
        ]
    )
    assert [key for key, _ in seeds] == ["arXiv:2001.01234", "DOI:10.1234/x", "PMID:99"]


def test_seeds_are_deduplicated_so_one_work_is_not_expanded_twice():
    seeds = seed_ids(
        [
            _seed("https://a.test", doi="10.1234/x"),
            _seed("https://b.test", doi="10.1234/x"),
        ]
    )
    assert len(seeds) == 1


# ── ranking ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_paper_two_seeds_agree_on_outranks_a_more_cited_one():
    """Co-citation is the field's own opinion, and it beats a raw count.

    'Cited 50 times' means canonical in a small humanities subfield and
    unremarkable in machine learning; two of your accepted sources both pointing
    at the same work means the same thing everywhere.
    """
    shared = _paper("Agreed upon", 20, "10.1111/shared")
    single = _paper("Highly cited", 5000, "10.2222/single")
    # Both sit at the top of their own lists; only one is agreed on by two seeds.
    seeds = [
        _seed("https://a.test", doi="10.1234/a"),
        _seed("https://b.test", doi="10.1234/b"),
    ]
    with _stub_http(
        {
            "references": {
                "DOI:10.1234/a": [shared, single, *_tail("a")],
                "DOI:10.1234/b": [shared, *_tail("b")],
            },
            "citations": {},
        }
    ):
        candidates = await snowball(seeds, max_candidates=5)

    assert candidates[0].title == "Agreed upon"
    assert candidates[0].metadata["co_citations"] == 2


@pytest.mark.asyncio
async def test_the_percentile_floor_travels_across_fields():
    """A flat citation floor is really a filter on discipline. The top of a
    seed's own reference list is what "endorsed" means, whatever the numbers."""
    top = _paper("Top of a low-count list", 4, "10.1111/top")
    tail = [_paper(f"Tail {i}", 1, f"10.1111/t{i}") for i in range(9)]
    with _stub_http(
        {
            "references": {"DOI:10.1234/a": [top, *tail]},
            "citations": {},
        }
    ):
        candidates = await snowball([_seed("https://a.test", doi="10.1234/a")], max_candidates=10)

    titles = [c.title for c in candidates]
    assert "Top of a low-count list" in titles, "4 citations would fail a flat floor of 50"
    assert len(titles) == 1, "the tail of the list is not endorsed by being in it"


@pytest.mark.asyncio
async def test_forward_citations_are_found_and_tagged():
    """Backward citation finds a seed's ancestors; forward citation finds the
    work that superseded it, which the planner cannot know about."""
    with _stub_http(
        {
            "references": {"DOI:10.1234/a": [_paper("Ancestor", 900, "10.1111/anc"), *_tail("b")]},
            "citations": {"DOI:10.1234/a": [_paper("Successor", 900, "10.2222/suc"), *_tail("f")]},
        }
    ):
        candidates = await snowball([_seed("https://a.test", doi="10.1234/a")], max_candidates=10)

    tagged = {c.title: c.metadata["discovered_via"] for c in candidates}
    assert tagged["Ancestor"] == DISCOVERED_BACKWARD
    assert tagged["Successor"] == DISCOVERED_FORWARD


@pytest.mark.asyncio
async def test_candidates_enter_triage_rather_than_bypassing_it():
    """Snowball results are ranked against the same brief as everything else —
    which is also the only way to compare their acceptance rate with the plan
    fetchers'."""
    with _stub_http(
        {
            "references": {"DOI:10.1234/a": [_paper("A reference", 900, "10.1111/r"), *_tail("b")]},
            "citations": {},
        }
    ):
        candidates = await snowball([_seed("https://a.test", doi="10.1234/a")], max_candidates=10)

    candidate = candidates[0]
    assert candidate.url == "https://doi.org/10.1111/r", "DOI resolver earns triage's prior"
    assert candidate.identifiers.doi == "10.1111/r"
    assert candidate.snippet == _ABSTRACT
    assert candidate.metadata["snowballed"] is True


# ── what it refuses ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_seed_is_never_proposed_back_to_itself():
    self_ref = _paper("The seed itself", 900, "10.1234/a")
    with _stub_http(
        {
            "references": {"DOI:10.1234/a": [self_ref, *_tail("b")]},
            "citations": {},
        }
    ):
        candidates = await snowball([_seed("https://a.test", doi="10.1234/a")], max_candidates=10)
    assert candidates == []


@pytest.mark.asyncio
async def test_the_seen_set_excludes_work_an_earlier_round_already_considered():
    seen = SeenSet()
    seen.identity_keys.add("doi:10.1111/known")

    with _stub_http(
        {
            "references": {
                "DOI:10.1234/a": [
                    _paper("Already seen", 900, "10.1111/known"),
                    _paper("New", 901, "10.1111/new"),
                    *_tail("b"),
                ]
            },
            "citations": {},
        }
    ):
        candidates = await snowball(
            [_seed("https://a.test", doi="10.1234/a")], seen, max_candidates=10
        )
    assert [c.title for c in candidates] == ["New"]


@pytest.mark.asyncio
async def test_the_per_round_cap_is_respected():
    papers = [_paper(f"P{i}", 900 - i, f"10.1111/p{i}") for i in range(20)]
    with _stub_http({"references": {"DOI:10.1234/a": papers}, "citations": {}}):
        candidates = await snowball([_seed("https://a.test", doi="10.1234/a")], max_candidates=3)
    assert len(candidates) == 3


@pytest.mark.asyncio
async def test_no_seeds_means_no_calls_and_no_candidates():
    assert await snowball([], max_candidates=10) == []
    assert await snowball([_seed("https://a.test")], max_candidates=10) == []


@pytest.mark.asyncio
async def test_a_co_cited_work_is_marked_to_be_fetched_ahead_of_everything():
    """The fetch queue orders by expected value per *dollar*, which ranks a long
    canonical paper below a cheap web page — on a live build that produced
    fifteen citation candidates and kept none of them. A work two accepted
    sources both cite is the strongest evidence the pipeline can get, so it
    skips the cost ordering entirely."""
    shared = _paper("Cited by two of ours", 30, "10.1111/shared")
    lone = _paper("Cited by one of ours", 900, "10.2222/lone")
    seeds = [
        _seed("https://a.test", doi="10.1234/a"),
        _seed("https://b.test", doi="10.1234/b"),
    ]
    with _stub_http(
        {
            "references": {
                "DOI:10.1234/a": [shared, lone, *_tail("a")],
                "DOI:10.1234/b": [shared, *_tail("b")],
            },
            "citations": {},
        }
    ):
        candidates = await snowball(seeds, max_candidates=5)

    by_title = {c.title: c for c in candidates}
    assert by_title["Cited by two of ours"].metadata["fetch_priority"] is True
    # One seed's endorsement is not agreement, however cited the work is.
    assert by_title["Cited by one of ours"].metadata["fetch_priority"] is False


# ── what it refuses to propose ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_work_with_no_route_to_its_text_is_not_proposed():
    """Measured on a real corpus: 16 of 20 proposals could not be fetched at
    all. Semantic Scholar has no abstract for most books and older canonical
    works, so the fetcher returned None and the slot silently refilled — and
    since these candidates are marked priority, they displaced ones that could
    actually be read."""
    no_text = _paper("Metaphors We Live By", 9000, "10.1111/book", abstract="")
    readable = _paper("A paper with an abstract", 900, "10.1111/paper")
    with _stub_http(
        {
            "references": {"DOI:10.1234/a": [no_text, readable, *_tail("b")]},
            "citations": {},
        }
    ):
        candidates = await snowball([_seed("https://a.test", doi="10.1234/a")], max_candidates=10)

    titles = [c.title for c in candidates]
    assert "A paper with an abstract" in titles
    assert "Metaphors We Live By" not in titles


@pytest.mark.asyncio
async def test_an_open_access_pdf_makes_an_abstractless_work_fetchable():
    """No abstract is not the same as no text. A PDF, an arXiv id or a PMCID is
    a route to the full document, and dropping those would throw away the best
    thing snowballing finds."""
    with _stub_http(
        {
            "references": {
                "DOI:10.1234/a": [
                    _paper(
                        "Has a PDF",
                        900,
                        "10.1111/pdf",
                        abstract="",
                        openAccessPdf={"url": "https://x.test/p.pdf"},
                    ),
                    *_tail("b"),
                ]
            },
            "citations": {},
        }
    ):
        candidates = await snowball([_seed("https://a.test", doi="10.1234/a")], max_candidates=10)
    assert [c.title for c in candidates] == ["Has a PDF"]
    assert candidates[0].metadata["oa_pdf_url"] == "https://x.test/p.pdf"


@pytest.mark.asyncio
async def test_an_arxiv_id_alone_is_a_route_to_full_text():
    with _stub_http(
        {
            "references": {
                "DOI:10.1234/a": [
                    {
                        **_paper("Preprint", 900, "10.1111/pre", abstract=""),
                        "externalIds": {"DOI": "10.1111/pre", "ArXiv": "2001.01234"},
                    },
                    *_tail("b"),
                ]
            },
            "citations": {},
        }
    ):
        candidates = await snowball([_seed("https://a.test", doi="10.1234/a")], max_candidates=10)
    assert [c.title for c in candidates] == ["Preprint"]
