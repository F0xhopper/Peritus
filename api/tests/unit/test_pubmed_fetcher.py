"""Unit tests for the PubMed (Europe PMC) fetcher.

Every test is offline: the Europe PMC REST calls are served by a stub
`httpx.AsyncClient`, so the suite never touches the network in CI.
"""

from unittest.mock import patch

import httpx
import pytest

from peritus.sources.domain import SourceCandidate
from peritus.sources.fetchers import pubmed
from peritus.sources.fetchers.pubmed import (
    MIN_ABSTRACT,
    PubmedFetcher,
    _authors,
    _strip_markup,
    _to_candidate,
    fetch_full_text,
)

LONG_ABSTRACT = "Interleukin-6 drives the acute phase response. " * 8
assert len(LONG_ABSTRACT) >= MIN_ABSTRACT


def _result(**overrides) -> dict:
    """A Europe PMC `resultType=core` record, trimmed to the fields we read."""
    base = {
        "id": "42343087",
        "source": "MED",
        "pmid": "42343087",
        "pmcid": "PMC13294356",
        "doi": "10.1038/s41586-000-0000-0",
        "title": "Programmable enhancement of endogenous mRNA translation",
        "abstractText": LONG_ABSTRACT,
        "authorString": "Zhang X, Shi H, Yang J, Du L.",
        "authorList": {
            "author": [
                {"fullName": "Zhang X"},
                {"fullName": "Shi H"},
                {"fullName": "Yang J"},
                {"fullName": "Du L"},
            ]
        },
        "journalInfo": {"journal": {"title": "Nature"}},
        "pubYear": "2026",
        "citedByCount": 12,
        "isOpenAccess": "Y",
        "inEPMC": "Y",
    }
    base.update(overrides)
    return base


# ── stub transport ────────────────────────────────────────────────────────────

class _StubResponse:
    def __init__(self, *, json_data=None, text="", status_code=200):
        self._json = json_data
        self.text = text
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
    return patch.object(pubmed.httpx, "AsyncClient", client)


# ── search ────────────────────────────────────────────────────────────────────

async def test_search_maps_a_core_result_onto_a_candidate():
    client = _StubClient(_StubResponse(json_data={"resultList": {"result": [_result()]}}))
    with _patch_http(client):
        candidates = await PubmedFetcher().search("mRNA translation")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_type is pubmed.SOURCE_TYPE
    assert candidate.url == "https://europepmc.org/article/MED/42343087"
    assert candidate.title == "Programmable enhancement of endogenous mRNA translation"
    assert candidate.author == "Zhang X, Shi H, Yang J"
    assert candidate.snippet.startswith("Interleukin-6")
    assert candidate.metadata["pmid"] == "42343087"
    assert candidate.metadata["pmcid"] == "PMC13294356"
    assert candidate.metadata["doi"] == "10.1038/s41586-000-0000-0"
    assert candidate.metadata["journal"] == "Nature"
    assert candidate.metadata["year"] == "2026"
    assert candidate.metadata["cited_by_count"] == 12
    assert candidate.metadata["open_access"] is True


async def test_search_requests_only_records_that_have_an_abstract():
    client = _StubClient(_StubResponse(json_data={"resultList": {"result": []}}))
    with _patch_http(client):
        await PubmedFetcher().search("p53 OR MDM2", max_results=500)

    params = client.calls[0]["params"]
    assert params["query"] == "(p53 OR MDM2) AND (HAS_ABSTRACT:Y)"
    assert params["format"] == "json"
    assert params["resultType"] == "core"
    # Clamped to Europe PMC's practical page size rather than passed through.
    assert params["pageSize"] == pubmed.MAX_PAGE_SIZE


async def test_search_truncates_to_max_results():
    payload = {"resultList": {"result": [_result(id=str(i)) for i in range(5)]}}
    client = _StubClient(_StubResponse(json_data=payload))
    with _patch_http(client):
        candidates = await PubmedFetcher().search("crispr", max_results=2)

    assert len(candidates) == 2


async def test_search_drops_records_with_no_usable_abstract():
    payload = {
        "resultList": {
            "result": [
                _result(abstractText="<h4>Background</h4>"),
                _result(id="2", title=""),
                _result(id="3"),
            ]
        }
    }
    client = _StubClient(_StubResponse(json_data=payload))
    with _patch_http(client):
        candidates = await PubmedFetcher().search("crispr")

    assert [c.metadata["pmid"] for c in candidates] == ["42343087"]
    assert candidates[0].url.endswith("/3")


async def test_search_returns_empty_on_transport_error():
    client = _StubClient(error=httpx.ConnectError("no route to host"))
    with _patch_http(client):
        assert await PubmedFetcher().search("crispr") == []


async def test_search_returns_empty_on_http_error_status():
    client = _StubClient(_StubResponse(status_code=503))
    with _patch_http(client):
        assert await PubmedFetcher().search("crispr") == []


# ── result mapping helpers ────────────────────────────────────────────────────

def test_open_access_requires_deposit_in_europe_pmc():
    """Licensed-as-OA is not the same as retrievable: full text needs inEPMC."""
    licensed_only = _to_candidate(_result(isOpenAccess="Y", inEPMC="N"))
    assert licensed_only is not None
    assert licensed_only.metadata["open_access"] is False

    deposited = _to_candidate(_result(isOpenAccess="Y", inEPMC="Y"))
    assert deposited is not None
    assert deposited.metadata["open_access"] is True


def test_strip_markup_removes_structured_abstract_headings():
    cleaned = _strip_markup("<h4>Background</h4>Cells divide.<i>In vitro</i>")
    assert "<" not in cleaned
    assert cleaned.startswith("Background")
    assert "Cells divide." in cleaned


def test_authors_falls_back_to_author_string():
    assert _authors(_result(authorList={})) == "Zhang X, Shi H, Yang J, Du L"
    assert _authors(_result(authorList={}, authorString="")) is None


def test_authors_tolerates_malformed_entries():
    record = _result(authorList={"author": ["not-a-dict", {"lastName": "Curie"}]})
    assert _authors(record) == "Curie"


# ── full text ─────────────────────────────────────────────────────────────────

JATS = """<?xml version="1.0"?>
<article>
  <front><article-meta><abstract><p>Abstract text.</p></abstract></article-meta></front>
  <body>
    <sec><title>Introduction</title>
      <p>Cas13 systems alter transcript abundance<xref ref-type="bibr">4</xref>.</p>
    </sec>
    <fig><caption><p>Figure caption noise.</p></caption></fig>
    <table-wrap><caption><p>Table caption noise.</p></caption></table-wrap>
  </body>
  <back><ref-list><ref><label>4</label><p>Smith et al. Reference noise.</p></ref></ref-list></back>
</article>
"""


async def test_fetch_full_text_keeps_body_and_drops_citation_plumbing():
    client = _StubClient(_StubResponse(text=JATS))
    text = await fetch_full_text(client, "PMC13294356")

    assert "Cas13 systems alter transcript abundance" in text
    assert "Figure caption noise" not in text
    assert "Table caption noise" not in text
    assert "Reference noise" not in text
    # The bare superscript citation marker must not survive as a stray line.
    assert "\n4" not in text


async def test_fetch_full_text_returns_empty_when_not_open_access():
    client = _StubClient(_StubResponse(status_code=404))
    assert await fetch_full_text(client, "PMC404") == ""


async def test_fetch_full_text_returns_empty_when_body_missing():
    client = _StubClient(_StubResponse(text="<article><front/></article>"))
    assert await fetch_full_text(client, "PMC1") == ""


# ── fetch ─────────────────────────────────────────────────────────────────────

def _candidate(**metadata_overrides) -> SourceCandidate:
    metadata = {
        "pmcid": "PMC13294356",
        "open_access": True,
        "abstract": LONG_ABSTRACT,
        "pmid": "42343087",
    }
    metadata.update(metadata_overrides)
    return SourceCandidate(
        source_type=pubmed.SOURCE_TYPE,
        url="https://europepmc.org/article/MED/42343087",
        title="Programmable enhancement of endogenous mRNA translation",
        author="Zhang X",
        snippet=LONG_ABSTRACT,
        metadata=metadata,
    )


async def test_fetch_prepends_abstract_to_open_access_full_text():
    body = "Methods and results. " * 400
    with (
        _patch_http(_StubClient(_StubResponse(text="<article/>"))),
        patch.object(pubmed, "fetch_full_text", return_value=body),
    ):
        source = await PubmedFetcher().fetch(_candidate())

    assert source is not None
    assert source.text.startswith("Programmable enhancement")
    assert LONG_ABSTRACT.strip() in source.text
    assert "Methods and results." in source.text
    assert source.metadata["full_text"] is True
    # The abstract is not duplicated into metadata once it is inside the text.
    assert "abstract" not in source.metadata
    assert source.source_type is pubmed.SOURCE_TYPE


async def test_fetch_truncates_at_max_full_text():
    with (
        _patch_http(_StubClient(_StubResponse(text="<article/>"))),
        patch.object(pubmed, "fetch_full_text", return_value="x" * 500_000),
    ):
        source = await PubmedFetcher().fetch(_candidate())

    assert source is not None
    assert len(source.text) == pubmed.MAX_FULL_TEXT


async def test_fetch_falls_back_to_the_abstract_when_full_text_is_short():
    with (
        _patch_http(_StubClient(_StubResponse(text="<article/>"))),
        patch.object(pubmed, "fetch_full_text", return_value="too short"),
    ):
        source = await PubmedFetcher().fetch(_candidate())

    assert source is not None
    assert source.metadata["full_text"] is False
    assert source.text == f"Programmable enhancement of endogenous mRNA translation\n\n{LONG_ABSTRACT}"


async def test_fetch_skips_the_full_text_request_for_closed_access():
    client = _StubClient(_StubResponse(text=JATS))
    with _patch_http(client):
        source = await PubmedFetcher().fetch(_candidate(open_access=False))

    assert source is not None
    assert source.metadata["full_text"] is False
    assert client.calls == []


async def test_fetch_returns_none_when_there_is_nothing_but_a_citation_stub():
    with _patch_http(_StubClient(_StubResponse(status_code=404))):
        source = await PubmedFetcher().fetch(
            _candidate(open_access=False, abstract="Too thin.")
        )

    assert source is None


async def test_fetch_survives_a_full_text_transport_error():
    with patch.object(pubmed, "fetch_full_text", side_effect=httpx.ReadTimeout("slow")):
        source = await PubmedFetcher().fetch(_candidate())

    assert source is not None
    assert source.metadata["full_text"] is False


@pytest.mark.parametrize("snippet_only", [True, False])
async def test_fetch_uses_the_snippet_when_metadata_has_no_abstract(snippet_only):
    candidate = _candidate(open_access=False)
    if snippet_only:
        del candidate.metadata["abstract"]

    with _patch_http(_StubClient(_StubResponse(status_code=404))):
        source = await PubmedFetcher().fetch(candidate)

    assert source is not None
    assert LONG_ABSTRACT.strip() in source.text
