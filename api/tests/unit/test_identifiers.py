"""Identifier normalisation and the identity it produces.

These are the rules that decide whether two records are the same work. They run
over strings scraped from arbitrary web pages, so every function has to be total
— an unparseable input is an absence of evidence, never an exception.
"""

import pytest

from peritus.sources.domain import Identifiers
from peritus.sources.identifiers import (
    arxiv_id_from_url,
    doi_from_url,
    normalise_arxiv_id,
    normalise_doi,
    normalise_openalex_id,
    normalise_pmcid,
    normalise_pmid,
)

# ── DOI ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "10.1234/AbC.def",
        "https://doi.org/10.1234/AbC.def",
        "http://dx.doi.org/10.1234/AbC.def",
        "doi:10.1234/AbC.def",
        "  10.1234/AbC.def  ",
    ],
)
def test_every_spelling_of_one_doi_normalises_to_the_same_key(raw):
    """The whole point: three fetchers writing a DOI three ways is one work."""
    assert normalise_doi(raw) == "10.1234/abc.def"


def test_doi_drops_trailing_prose_punctuation():
    # DOIs are routinely quoted mid-sentence, and the full stop is the sentence's.
    assert normalise_doi("see 10.1234/abc.") == "10.1234/abc"
    assert normalise_doi("(10.1234/abc)") == "10.1234/abc"


def test_doi_rejects_things_that_are_not_dois():
    for raw in ("", None, "not a doi", "11.1234/abc", "10.12/x"):
        assert normalise_doi(raw) is None


def test_doi_from_url_only_trusts_a_resolver_or_a_doi_path():
    assert doi_from_url("https://doi.org/10.1234/abc") == "10.1234/abc"
    assert doi_from_url("https://onlinelibrary.wiley.com/doi/10.1234/abc") == "10.1234/abc"
    # A bare number-shaped path segment on an unrelated host is not a DOI, and
    # treating it as one would merge two unrelated pages into one "work".
    assert doi_from_url("https://example.org/10.1234/abc") is None
    assert doi_from_url("https://example.org/article?ref=10.1234/abc") is None


# ── arXiv ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "2001.01234",
        "2001.01234v3",
        "arXiv:2001.01234",
        "https://arxiv.org/abs/2001.01234v2",
        "https://arxiv.org/pdf/2001.01234",
        "https://ar5iv.labs.arxiv.org/html/2001.01234",
    ],
)
def test_arxiv_id_normalises_across_spellings_and_versions(raw):
    """v1 and v3 of a preprint are the same work; keeping both defeats identity."""
    assert normalise_arxiv_id(raw) == "2001.01234"


def test_arxiv_handles_the_pre_2007_scheme():
    assert normalise_arxiv_id("math.GT/0309136") == "math.gt/0309136"
    assert arxiv_id_from_url("https://arxiv.org/abs/math.GT/0309136") == "math.gt/0309136"


def test_arxiv_id_from_url_ignores_other_hosts():
    assert arxiv_id_from_url("https://example.org/abs/2001.01234") is None
    assert arxiv_id_from_url("") is None


# ── the other registries ─────────────────────────────────────────────────────


def test_pmid_and_pmcid_normalisation():
    assert normalise_pmid("PMID:12345") == "12345"
    assert normalise_pmid(12345) == "12345"
    assert normalise_pmid("PMC12345") is None
    assert normalise_pmcid("pmc12345") == "PMC12345"
    assert normalise_pmcid("12345") == "PMC12345"
    assert normalise_pmcid("nonsense") is None


def test_openalex_id_is_read_out_of_its_resolver_url():
    assert normalise_openalex_id("https://openalex.org/W2741809807") == "W2741809807"
    assert normalise_openalex_id("w2741809807") == "W2741809807"
    assert normalise_openalex_id("") is None


# ── identity ─────────────────────────────────────────────────────────────────


def test_canonical_key_follows_the_documented_precedence():
    ids = Identifiers.build(doi="10.1234/x", arxiv_id="2001.01234", pmid="99")
    assert ids.canonical_key() == "doi:10.1234/x"
    assert Identifiers.build(arxiv_id="2001.01234", pmid="99").canonical_key() == (
        "arxiv_id:2001.01234"
    )
    assert Identifiers().canonical_key() is None


def test_keys_expose_every_scheme_so_partial_records_still_match():
    """Identity is not transitive through canonical_key alone.

    A record with only a DOI and a record with the same DOI *plus* an arXiv id
    have different canonical keys; matching on any shared key is what merges
    them, and that is what ``keys()`` is for.
    """
    full = Identifiers.build(doi="10.1234/x", arxiv_id="2001.01234")
    partial = Identifiers.build(arxiv_id="2001.01234")
    assert full.canonical_key() != partial.canonical_key()
    assert full.keys() & partial.keys()


def test_merge_unions_and_prefers_the_receiver():
    a = Identifiers.build(doi="10.1234/x")
    b = Identifiers.build(doi="10.5678/y", arxiv_id="2001.01234")
    merged = a.merge(b)
    assert merged.doi == "10.1234/x"
    assert merged.arxiv_id == "2001.01234"


def test_dict_round_trip_drops_absent_schemes():
    ids = Identifiers.build(doi="10.1234/X", pmcid="PMC7")
    assert ids.to_dict() == {"doi": "10.1234/x", "pmcid": "PMC7"}
    assert Identifiers.from_dict(ids.to_dict()) == ids


def test_from_metadata_reads_the_legacy_spellings():
    """Every fetcher still writes metadata, so it is the fallback for identity.

    A candidate built by hand — by a test, or by a caller outside the search
    path — must still resolve to full text rather than silently degrading to its
    abstract.
    """
    ids = Identifiers.from_metadata(
        {"pmcid": "PMC13294356", "pmid": "42343087", "doi": "10.1234/X", "irrelevant": 1}
    )
    assert ids.pmcid == "PMC13294356"
    assert ids.pmid == "42343087"
    assert ids.doi == "10.1234/x"
    assert Identifiers.from_metadata(None).is_empty()
