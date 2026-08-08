"""Unit tests for the OpenAlex fetcher.

Every test is offline: the OpenAlex REST calls are served by a stub
`httpx.AsyncClient`, so the suite never touches the network in CI.
"""

from unittest.mock import patch

import httpx
import pytest

from peritus.sources.domain import SourceCandidate
from peritus.sources.fetchers import openalex
from peritus.sources.fetchers.openalex import (
    MIN_ABSTRACT,
    MIN_FULL_TEXT,
    OpenAlexFetcher,
    _authors,
    _bare_doi,
    _reconstruct_abstract,
    _to_candidate,
    fetch_by_doi,
)

_WORDS = "the ottoman land code reshaped provincial property relations and taxation".split()
LONG_INVERTED = {
    word: list(range(i, MIN_ABSTRACT, len(_WORDS)))
    for i, word in enumerate(_WORDS)
}
assert len(_reconstruct_abstract(LONG_INVERTED)) >= MIN_ABSTRACT


def _work(**overrides) -> dict:
    """An OpenAlex work record, trimmed to the fields we read."""
    base = {
        "id": "https://openalex.org/W2000000000",
        "display_name": "The Ottoman Land Code of 1858 and provincial society",
        "doi": "https://doi.org/10.1017/S0020743800000000",
        "publication_year": 1984,
        "cited_by_count": 312,
        "type": "article",
        "abstract_inverted_index": LONG_INVERTED,
        "primary_location": {
            "landing_page_url": "https://www.cambridge.org/core/article/abc",
            "source": {"display_name": "International Journal of Middle East Studies"},
        },
        "best_oa_location": {
            "pdf_url": "https://example.org/paper.pdf",
            "landing_page_url": "https://example.org/paper",
        },
        "authorships": [
            {"author": {"display_name": "Huri İslamoğlu"}},
            {"author": {"display_name": "Çağlar Keyder"}},
            {"author": {"display_name": "A Third"}},
            {"author": {"display_name": "A Fourth"}},
        ],
    }
    base.update(overrides)
    return base


# ── stub transport ────────────────────────────────────────────────────────────

class _StubResponse:
    def __init__(self, *, json_data=None, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=httpx.Request("GET", "https://x.test"), response=None  # type: ignore[arg-type]
            )

    def json(self):
        return self._json


class _StubClient:
    """Minimal stand-in for `httpx.AsyncClient` used as an async context manager."""

    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):  # instantiated as httpx.AsyncClient(...)
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        if self._error is not None:
            raise self._error
        return self._response


def _patch_http(client: _StubClient):
    return patch.object(openalex.httpx, "AsyncClient", client)


# ── abstract reconstruction ───────────────────────────────────────────────────

def test_reconstruct_abstract_orders_words_by_position():
    inverted = {"beta": [1], "alpha": [0], "alpha,": [2]}
    assert _reconstruct_abstract(inverted) == "alpha beta alpha,"


def test_reconstruct_abstract_handles_missing_and_malformed():
    assert _reconstruct_abstract(None) == ""
    assert _reconstruct_abstract({}) == ""
    assert _reconstruct_abstract({"word": "not-a-list"}) == ""


# ── candidate mapping ─────────────────────────────────────────────────────────

def test_to_candidate_maps_work_fields():
    candidate = _to_candidate(_work())
    assert candidate is not None
    assert candidate.source_type is openalex.SOURCE_TYPE
    assert candidate.url == "https://www.cambridge.org/core/article/abc"
    assert candidate.title.startswith("The Ottoman Land Code")
    assert candidate.author == "Huri İslamoğlu, Çağlar Keyder, A Third"
    assert len(candidate.snippet) >= MIN_ABSTRACT
    assert candidate.metadata["doi"] == "10.1017/S0020743800000000"
    assert candidate.metadata["cited_by_count"] == 312
    assert candidate.metadata["venue"] == "International Journal of Middle East Studies"
    assert candidate.metadata["oa_pdf_url"] == "https://example.org/paper.pdf"


def test_to_candidate_falls_back_to_doi_url_then_openalex_id():
    by_doi = _to_candidate(_work(primary_location=None))
    assert by_doi is not None
    assert by_doi.url == "https://doi.org/10.1017/S0020743800000000"

    by_id = _to_candidate(_work(primary_location=None, doi=None))
    assert by_id is not None
    assert by_id.url == "https://openalex.org/W2000000000"


def test_to_candidate_rejects_thin_records():
    assert _to_candidate(_work(display_name="")) is None
    assert _to_candidate(_work(abstract_inverted_index={"too": [0], "short": [1]})) is None


def test_bare_doi_and_authors_helpers():
    assert _bare_doi("https://doi.org/10.1/x") == "10.1/x"
    assert _bare_doi(None) is None
    assert _authors({"authorships": []}) is None


# ── search ────────────────────────────────────────────────────────────────────

async def test_search_maps_results_and_filters_thin_ones():
    client = _StubClient(_StubResponse(json_data={
        "results": [_work(), _work(display_name="", id="https://openalex.org/W2")],
    }))
    with _patch_http(client):
        candidates = await OpenAlexFetcher().search("ottoman land tenure")

    assert len(candidates) == 1
    assert candidates[0].title.startswith("The Ottoman Land Code")
    params = client.calls[0]["params"]
    assert params["search"] == "ottoman land tenure"
    assert "has_abstract:true" in params["filter"]


async def test_search_returns_empty_on_error():
    client = _StubClient(error=httpx.ConnectError("boom"))
    with _patch_http(client):
        assert await OpenAlexFetcher().search("anything") == []


# ── fetch ─────────────────────────────────────────────────────────────────────

async def test_fetch_falls_back_to_abstract_when_no_full_text():
    candidate = _to_candidate(_work(best_oa_location=None))
    assert candidate is not None
    source = await OpenAlexFetcher().fetch(candidate)

    assert source is not None
    assert source.text.startswith(candidate.title)
    assert source.metadata["full_text"] is False
    assert "abstract" not in source.metadata


async def test_fetch_uses_landing_page_text_when_long_enough():
    candidate = _to_candidate(_work(
        best_oa_location={"pdf_url": None, "landing_page_url": "https://example.org/paper"},
    ))
    assert candidate is not None
    long_text = "A full scholarly argument. " * 200
    assert len(long_text) >= MIN_FULL_TEXT

    async def _fake_oa_text(cand):
        return long_text

    with patch.object(openalex, "_fetch_open_access_text", _fake_oa_text):
        source = await OpenAlexFetcher().fetch(candidate)

    assert source is not None
    assert source.metadata["full_text"] is True
    assert long_text[:50] in source.text
    # The abstract is prepended ahead of the body.
    assert source.text.index(candidate.metadata["abstract"][:40]) < source.text.index(long_text[:40])


async def test_fetch_returns_none_for_stub_abstract():
    candidate = SourceCandidate(
        source_type=openalex.SOURCE_TYPE,
        url="https://doi.org/10.1/x",
        title="t",
        author=None,
        snippet="too short",
        metadata={"abstract": "too short"},
    )
    source = await OpenAlexFetcher().fetch(candidate)
    assert source is None


# ── DOI lookup (snowballing) ──────────────────────────────────────────────────

async def test_fetch_by_doi_resolves_to_candidate():
    client = _StubClient(_StubResponse(json_data=_work()))
    with _patch_http(client):
        candidate = await fetch_by_doi("10.1017/S0020743800000000")

    assert candidate is not None
    assert candidate.metadata["doi"] == "10.1017/S0020743800000000"
    assert client.calls[0]["url"].endswith("/https://doi.org/10.1017/S0020743800000000")


async def test_fetch_by_doi_returns_none_on_404():
    client = _StubClient(_StubResponse(json_data={"error": "not found"}, status_code=404))
    with _patch_http(client):
        assert await fetch_by_doi("10.1/nope") is None
