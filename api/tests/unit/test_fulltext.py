"""The full-text resolution chain.

The chain is ordered by quality first and cost second, and the order is the
whole point: a biomedical paper found through OpenAlex should get Europe PMC's
free structured JATS rather than an OCR bill for the publisher's PDF. These
tests assert which step ran, not merely that some text came back.
"""

from unittest.mock import patch

import pytest

from peritus.core.config import settings
from peritus.sources import fulltext
from peritus.sources.domain import Identifiers
from peritus.sources.fulltext import (
    METHOD_AR5IV,
    METHOD_ARXIV_PDF,
    METHOD_EUROPE_PMC,
    METHOD_LANDING,
    METHOD_OA_PDF,
    MIN_FULL_TEXT,
    FullTextHints,
    expected_method,
    is_paid_path,
    resolve_full_text,
)

_LONG = "Full text of the paper. " * 400
assert len(_LONG) >= MIN_FULL_TEXT


class _Recorder:
    """Records which steps ran, so the test can assert the chain's order."""

    def __init__(self) -> None:
        self.calls: list[str] = []


def _chain(recorder: _Recorder, **results):
    """Patch every step. Each keyword is a step name → the text it returns."""

    async def _ar5iv(client, arxiv_id):
        recorder.calls.append("ar5iv")
        return results.get("ar5iv", "")

    async def _jats(client, pmcid):
        recorder.calls.append("europepmc")
        return results.get("europepmc", "")

    async def _pmcid_for_pmid(pmid):
        recorder.calls.append("id_converter")
        return results.get("pmcid_for_pmid")

    async def _ocr(url):
        recorder.calls.append(f"ocr:{url}")
        return results.get("ocr", "")

    async def _page(url, max_chars=0):
        recorder.calls.append("landing")
        return results.get("landing", "")

    async def _by_doi(doi):
        recorder.calls.append("openalex_by_doi")
        return results.get("by_doi")

    return (
        patch("peritus.sources.fetchers.arxiv.fetch_ar5iv", _ar5iv),
        patch("peritus.sources.fetchers.pubmed.fetch_full_text", _jats),
        patch("peritus.sources.fetchers.pubmed.pmcid_for_pmid", _pmcid_for_pmid),
        patch("peritus.infrastructure.pdf_parser.parse_pdf_url", _ocr),
        patch("peritus.sources.fetchers.web.fetch_page_text", _page),
        patch("peritus.sources.fetchers.openalex.fetch_by_doi", _by_doi),
    )


async def _resolve(recorder, ids, hints=None, **results):
    patches = _chain(recorder, **results)
    for p in patches:
        p.start()
    try:
        return await resolve_full_text(ids, hints)
    finally:
        for p in patches:
            p.stop()


# ── the order ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ar5iv_is_tried_first_for_an_arxiv_paper():
    rec = _Recorder()
    result = await _resolve(rec, Identifiers.build(arxiv_id="2001.01234"), ar5iv=_LONG)
    assert result.method == METHOD_AR5IV
    assert rec.calls == ["ar5iv"], "nothing else should have been asked"


@pytest.mark.asyncio
async def test_a_failed_ar5iv_render_falls_back_to_the_pdf(monkeypatch):
    """ar5iv cannot render every paper, and a render failure used to cost the
    whole body when the PDF was one request away."""
    monkeypatch.setattr(settings, "MISTRAL_API_KEY", "set")
    rec = _Recorder()
    result = await _resolve(
        rec, Identifiers.build(arxiv_id="2001.01234"), ar5iv="", ocr=_LONG
    )
    assert result.method == METHOD_ARXIV_PDF
    assert rec.calls == ["ar5iv", "ocr:https://arxiv.org/pdf/2001.01234"]


@pytest.mark.asyncio
async def test_europe_pmc_beats_ocr_for_a_paper_that_has_both(monkeypatch):
    """The single largest waste the old per-fetcher ladders produced: paying
    per page to OCR a publisher PDF of an article Europe PMC serves free, as
    structured XML, already split into sections."""
    monkeypatch.setattr(settings, "MISTRAL_API_KEY", "set")
    rec = _Recorder()
    result = await _resolve(
        rec,
        Identifiers.build(pmcid="PMC123", doi="10.1234/x"),
        FullTextHints(oa_pdf_url="https://publisher.test/paper.pdf"),
        europepmc=_LONG,
        ocr=_LONG,
    )
    assert result.method == METHOD_EUROPE_PMC
    assert not any(c.startswith("ocr:") for c in rec.calls), "no OCR should be paid for"


@pytest.mark.asyncio
async def test_a_bare_pmid_is_converted_before_europe_pmc_is_asked():
    """Plenty of sources arrive with a PMID and nothing else — an OpenAlex work,
    a Semantic Scholar citation. One cheap lookup is the difference between free
    structured full text and an abstract."""
    rec = _Recorder()
    result = await _resolve(
        rec,
        Identifiers.build(pmid="42343087"),
        pmcid_for_pmid="PMC999",
        europepmc=_LONG,
    )
    assert result.method == METHOD_EUROPE_PMC
    assert rec.calls == ["id_converter", "europepmc"]


@pytest.mark.asyncio
async def test_a_landing_page_is_the_last_resort_before_the_abstract():
    rec = _Recorder()
    result = await _resolve(
        rec,
        Identifiers.build(doi="10.1234/x"),
        FullTextHints(oa_landing_url="https://journal.test/paper"),
        landing=_LONG,
    )
    assert result.method == METHOD_LANDING


@pytest.mark.asyncio
async def test_nothing_available_returns_none_so_the_caller_uses_the_abstract():
    rec = _Recorder()
    assert await _resolve(rec, Identifiers.build(doi="10.1234/x")) is None


# ── what it declines to do ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_closed_access_record_never_costs_a_full_text_request():
    """Only the open-access subset has retrievable full text; asking for the
    rest is a guaranteed 404."""
    rec = _Recorder()
    await _resolve(
        rec,
        Identifiers.build(pmcid="PMC123"),
        FullTextHints(open_access=False),
        europepmc=_LONG,
    )
    assert "europepmc" not in rec.calls


@pytest.mark.asyncio
async def test_an_unstated_open_access_flag_is_still_worth_trying():
    """`None` is "nobody has said", which is the normal case for a work reached
    through a citation. Collapsing it to False would strand those on abstracts."""
    rec = _Recorder()
    result = await _resolve(rec, Identifiers.build(pmcid="PMC123"), europepmc=_LONG)
    assert result.method == METHOD_EUROPE_PMC


@pytest.mark.asyncio
async def test_openalex_is_not_re_asked_about_a_work_it_already_described():
    """An OpenAlex record came *from* OpenAlex; a DOI lookup back to it is a
    round trip that cannot return anything new."""
    rec = _Recorder()
    await _resolve(rec, Identifiers.build(doi="10.1234/x", openalex_id="W1"))
    assert "openalex_by_doi" not in rec.calls


@pytest.mark.asyncio
async def test_a_bare_doi_is_enriched_before_giving_up():
    """A DOI-only citation is the snowball case, and OpenAlex is what turns it
    into an open-access location."""
    rec = _Recorder()
    from peritus.sources.domain import SourceCandidate, SourceType

    enriched = SourceCandidate(
        source_type=SourceType.OPENALEX,
        url="https://journal.test/paper",
        title="t",
        author=None,
        snippet="s",
        metadata={"oa_landing_url": "https://journal.test/paper"},
        identifiers=Identifiers.build(doi="10.1234/x", openalex_id="W1"),
    )
    result = await _resolve(
        rec, Identifiers.build(doi="10.1234/x"), by_doi=enriched, landing=_LONG
    )
    assert result.method == METHOD_LANDING
    assert "openalex_by_doi" in rec.calls


@pytest.mark.asyncio
async def test_short_text_is_not_accepted_as_full_text():
    """A paywall notice or a cookie banner is not worth preferring over the
    abstract the fetcher already has."""
    rec = _Recorder()
    assert await _resolve(rec, Identifiers.build(arxiv_id="2001.01234"), ar5iv="stub") is None


# ── the pre-flight guess ─────────────────────────────────────────────────────


def test_expected_method_predicts_the_step_without_taking_it(monkeypatch):
    """Used to sort the fetch queue and to estimate cost, both of which happen
    before any network call. A wrong guess costs nothing — the recorded method
    always comes from what actually ran."""
    monkeypatch.setattr(settings, "MISTRAL_API_KEY", "set")
    assert expected_method(Identifiers.build(arxiv_id="2001.01234")) == METHOD_AR5IV
    assert expected_method(Identifiers.build(pmcid="PMC1")) == METHOD_EUROPE_PMC
    assert expected_method(
        Identifiers.build(doi="10.1234/x"), FullTextHints(oa_pdf_url="https://x.test/p.pdf")
    ) == METHOD_OA_PDF
    assert expected_method(Identifiers()) == "abstract"


def test_only_ocr_paths_count_as_paid(monkeypatch):
    """OCR is the one step that bills per page, and the fetch queue sorts free
    paths ahead of it so a fixed budget buys text before it buys OCR."""
    monkeypatch.setattr(settings, "MISTRAL_API_KEY", "set")
    assert not is_paid_path(Identifiers.build(arxiv_id="2001.01234"))
    assert not is_paid_path(Identifiers.build(pmcid="PMC1"))
    assert is_paid_path(
        Identifiers.build(doi="10.1234/x"), FullTextHints(oa_pdf_url="https://x.test/p.pdf")
    )


def test_hints_read_both_spellings_of_the_open_access_flag():
    """Europe PMC calls it `open_access`; OpenAlex and the PDF fetcher call it
    `is_open_access`. A fetcher whose flag was not read would lose full text."""
    assert FullTextHints.from_metadata({"open_access": True}).open_access is True
    assert FullTextHints.from_metadata({"is_open_access": False}).open_access is False
    assert FullTextHints.from_metadata({}).open_access is None


def test_the_module_exposes_a_stable_method_vocabulary():
    """These strings are persisted on `sources.full_text_method` and read by the
    audit surface, so they are an interface, not an implementation detail."""
    assert frozenset({METHOD_ARXIV_PDF, METHOD_OA_PDF}) == fulltext.PAID_METHODS
