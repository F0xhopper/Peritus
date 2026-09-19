"""The three de-duplication passes.

The cases that matter are the ones that used to slip through all three of the
old checks: the same paper as an arXiv preprint, a journal DOI and a Semantic
Scholar OA PDF; and a preprint versus its published version, which share no
identifier at all. The false-positive guard matters as much — two different
books by the same author must survive.
"""

from peritus.sources.dedup import (
    SIMHASH_MAX_DISTANCE,
    DedupReport,
    SeenSet,
    deduplicate_candidates,
    deduplicate_sources_by_content,
    hamming,
    normalise_url,
    simhash,
)
from peritus.sources.domain import Identifiers, RawSource, SourceCandidate, SourceType


def _candidate(
    source_type: SourceType,
    url: str,
    title: str = "A paper",
    metadata: dict | None = None,
    **ids,
) -> SourceCandidate:
    return SourceCandidate(
        source_type=source_type,
        url=url,
        title=title,
        author=None,
        snippet="snippet",
        metadata=metadata or {},
        identifiers=Identifiers.build(**ids),
    )


# ── URL normalisation ────────────────────────────────────────────────────────


def test_url_normalisation_strips_the_things_that_do_not_identify_a_page():
    base = normalise_url("https://example.org/paper")
    assert normalise_url("https://www.example.org/paper/") == base
    assert normalise_url("https://EXAMPLE.org/paper#section-2") == base
    assert normalise_url("https://example.org/paper?utm_source=twitter") == base
    # A real query parameter is part of the address and must not be stripped.
    assert normalise_url("https://example.org/paper?id=7") != base


def test_every_arxiv_spelling_collapses_to_one_url_key():
    keys = {
        normalise_url(u)
        for u in (
            "https://arxiv.org/abs/2001.01234",
            "https://arxiv.org/abs/2001.01234v2",
            "https://arxiv.org/pdf/2001.01234",
            "https://ar5iv.labs.arxiv.org/html/2001.01234",
        )
    }
    assert len(keys) == 1


# ── identity dedup ───────────────────────────────────────────────────────────


def test_the_same_paper_from_three_fetchers_becomes_one_candidate():
    """The case the old URL-and-title checks all missed.

    An arXiv preprint, its journal DOI and a Semantic Scholar OA PDF have three
    different URLs and three different titles-as-rendered, and are one paper
    paid for three times.
    """
    candidates = [
        _candidate(SourceType.EXA, "https://doi.org/10.1234/abc", doi="10.1234/abc"),
        _candidate(
            SourceType.ARXIV,
            "https://arxiv.org/abs/2001.01234",
            arxiv_id="2001.01234",
            doi="10.1234/abc",
        ),
        _candidate(
            SourceType.PDF,
            "https://cdn.example.org/abc.pdf",
            doi="10.1234/abc",
            s2_id="ss-1",
        ),
    ]
    kept, report = deduplicate_candidates(candidates)

    assert len(kept) == 1
    assert report.identity_merged == 2
    # The survivor is the one whose fetcher yields the best full text…
    assert kept[0].source_type is SourceType.ARXIV
    # …carrying every identifier the losers contributed, so a later round can
    # still recognise this work however it is found next.
    assert kept[0].identifiers.doi == "10.1234/abc"
    assert kept[0].identifiers.arxiv_id == "2001.01234"
    assert kept[0].identifiers.s2_id == "ss-1"
    assert kept[0].metadata["merged_from"] == [
        "https://doi.org/10.1234/abc",
        "https://cdn.example.org/abc.pdf",
    ]


def test_identity_groups_transitively_through_a_shared_key():
    """A DOI-only record and an arXiv-only record are joined by the one that
    carries both — otherwise the group splits and one copy survives twice."""
    candidates = [
        _candidate(SourceType.WEB, "https://a.test", doi="10.1234/x"),
        _candidate(SourceType.WEB, "https://b.test", arxiv_id="2001.01234"),
        _candidate(SourceType.WEB, "https://c.test", doi="10.1234/x", arxiv_id="2001.01234"),
    ]
    kept, report = deduplicate_candidates(candidates)
    assert len(kept) == 1
    assert report.identity_merged == 2


def test_a_record_with_a_free_full_text_route_wins_its_own_type():
    """Preference is about which copy yields the best text, not just which
    fetcher found it: a pubmed record with a PMCID beats one without."""
    without = _candidate(SourceType.PUBMED, "https://a.test", doi="10.1234/x", pmid="1")
    with_pmc = _candidate(
        SourceType.PUBMED, "https://b.test", doi="10.1234/x", pmid="1", pmcid="PMC9"
    )
    kept, _ = deduplicate_candidates([without, with_pmc])
    assert kept[0].url == "https://b.test"


def test_candidates_without_identifiers_are_never_merged_together():
    """No identifier is not evidence of sameness. Two web pages with no DOI are
    two pages, and the URL pass is what separates them."""
    candidates = [
        _candidate(SourceType.WEB, "https://a.test", title="Same title"),
        _candidate(SourceType.WEB, "https://b.test", title="Same title"),
    ]
    kept, report = deduplicate_candidates(candidates)
    assert len(kept) == 2
    assert report.identity_merged == 0


def test_url_pass_removes_the_same_page_found_by_two_fetchers():
    candidates = [
        _candidate(SourceType.EXA, "https://example.org/essay"),
        _candidate(SourceType.WEB, "https://www.example.org/essay/?utm_campaign=x"),
    ]
    kept, report = deduplicate_candidates(candidates)
    assert len(kept) == 1
    assert report.url_merged == 1


# ── the seen set ─────────────────────────────────────────────────────────────


def test_a_seen_set_keeps_later_rounds_off_ground_already_covered():
    seen = SeenSet()
    seen.add_candidate(_candidate(SourceType.WEB, "https://a.test", doi="10.1234/x"))

    kept, report = deduplicate_candidates(
        [
            # Same work, different URL — caught by identity.
            _candidate(SourceType.EXA, "https://elsewhere.test", doi="10.1234/x"),
            # Same URL, no identifiers — caught by URL.
            _candidate(SourceType.WEB, "https://a.test/"),
            _candidate(SourceType.WEB, "https://new.test"),
        ],
        seen,
    )
    assert [c.url for c in kept] == ["https://new.test"]
    assert report.seen_skipped == 2


# ── content fingerprinting ───────────────────────────────────────────────────


def _source(url: str, text: str) -> RawSource:
    return RawSource(SourceType.WEB, url, "A paper", None, text)


_BODY = (
    "The doctrine of analogy holds that terms predicated of God and creatures "
    "are neither univocal nor equivocal but proportional. This distinction "
    "governs the whole of natural theology, since a univocal predication would "
    "collapse the difference between creator and creature, while a purely "
    "equivocal one would make theological language empty. "
) * 8


def test_a_preprint_and_its_published_version_are_one_document():
    """The case identity cannot see: no shared DOI, the same text.

    The published version differs from the preprint by a title page and a few
    edits — a handful of bits of simhash, far inside the threshold.
    """
    preprint = _source("https://a.test/preprint", _BODY)
    published = _source("https://b.test/published", "Journal of Thomistic Studies\n\n" + _BODY)
    kept, duplicates = deduplicate_sources_by_content([preprint, published])

    assert len(kept) == 1
    # The longer text wins: two renderings of one paper differ mainly in how
    # much of it survived extraction.
    assert kept[0].url == "https://b.test/published"
    assert duplicates[0][0].url == "https://a.test/preprint"
    assert duplicates[0][1] == "https://b.test/published"


def test_two_different_papers_on_one_topic_are_not_duplicates():
    other = (
        "Participation is the metaphysical relation by which a creature has "
        "being derivatively rather than of itself. Where analogy concerns "
        "language, participation concerns the order of being, and conflating "
        "the two produces a theology that cannot say what it means. "
    ) * 8
    kept, duplicates = deduplicate_sources_by_content(
        [_source("https://a.test", _BODY), _source("https://b.test", other)]
    )
    assert len(kept) == 2
    assert duplicates == []


def test_short_texts_are_left_to_identity_and_url():
    """A simhash over a two-line abstract is noise, and two short abstracts on
    one topic collide easily. Below the floor, no fingerprint is claimed."""
    assert simhash("too short to fingerprint") is None
    kept, duplicates = deduplicate_sources_by_content(
        [_source("https://a.test", "short"), _source("https://b.test", "short")]
    )
    assert len(kept) == 2
    assert duplicates == []


def test_the_fingerprint_is_stable_across_processes():
    """Python's hash() is salted per process. If this used it, the same corpus
    would de-duplicate differently in every worker."""
    assert simhash(_BODY) == simhash(_BODY)
    assert hamming(simhash(_BODY), simhash(_BODY)) == 0
    near = simhash("Preface.\n\n" + _BODY)
    assert hamming(simhash(_BODY), near) <= SIMHASH_MAX_DISTANCE


def test_report_serialises_for_the_event_log():
    assert DedupReport(candidates=10, identity_merged=1, kept=9).as_event() == {
        "candidates": 10,
        "identity_merged": 1,
        "url_merged": 0,
        "seen_skipped": 0,
        "kept": 9,
    }


def _varied(subject: str, n: int = 90) -> str:
    """A document with distinct sentences, the way a real one has.

    Repetitive filler is not a stand-in: with the same paragraph repeated, a
    document has very few distinct shingles and an appended bibliography becomes
    a large share of them, so a fixture built that way fingerprints as more
    different than any real paper would.
    """
    return " ".join(
        f"On {subject}, consideration {i} observes that the {i}th distinction "
        f"bears on the question in a manner the preceding {i - 1} did not, and "
        f"the commentators differ about section {i} accordingly."
        for i in range(1, n + 1)
    )


def test_the_threshold_catches_a_realistically_different_rendering():
    """The case the plan built this pass for, and the one a distance of 3 could
    not see: the same paper with front matter and a reference list. Measured
    against the real corpus, distance 3 caught 9.3% of these — and never once
    fired on a live build."""
    body = _varied("analogy")
    published = (
        "The Thomist 58 (1994) 1-30\n\n"
        + body
        + "\n\nReferences\n"
        + "\n".join(f"[{i}] A. Author, A Title (1970)." for i in range(50))
    )

    kept, duplicates = deduplicate_sources_by_content(
        [_source("https://preprint.test", body), _source("https://journal.test", published)]
    )
    assert len(kept) == 1, "front matter and a bibliography are not a different paper"
    assert len(duplicates) == 1


def test_the_threshold_still_keeps_distinct_papers_on_one_topic_apart():
    """The error that matters. A missed duplicate costs money and is visible in
    the ledger; a false merge silently deletes a good source, and nobody ever
    sees the paper that was not kept. Distinct documents on one topic share most
    of their vocabulary, which is what makes this the hard direction — and it is
    why the threshold sits at the largest distance with no observed false merge
    rather than at the one with the best recall."""
    kept, duplicates = deduplicate_sources_by_content(
        [
            _source("https://a.test", _varied("the analogy of names")),
            _source("https://b.test", _varied("participation in being")),
        ]
    )
    assert len(kept) == 2
    assert duplicates == []


def test_one_edition_per_work():
    from peritus.sources.dedup import deduplicate_editions
    from peritus.sources.domain import RawSource, SourceType

    def src(title: str, text: str, url: str) -> RawSource:
        return RawSource(SourceType.WEB, url, title, None, text)

    article = " ".join(
        f"In article {n} it is argued that the simple being has no parts and no composition "
        f"of any kind, because whatever is composite is posterior to its parts {n}."
        for n in range(40)
    )
    whole = src("Summa Theologica, Part I", "Front matter. " + article * 3, "https://g/1")
    excerpt = src("SUMMA THEOLOGIAE: The simplicity of God", article, "https://newadvent/3")
    english = src(
        "Bede's ecclesiastical history of the English people",
        (
            "The king of the English was baptized by the bishop in the city of York, and "
            "the people of the kingdom were converted to the faith of the church. "
        )
        * 40,
        "https://a/eng",
    )
    latin = src(
        "The Old English version of Bede's Ecclesiastical history of the English people",
        (
            "Cum enim malignus spiritus peccatum suggerit in mente, si nulla peccati delectatio "
            "sequatur, peccatum omnimodo perpetratum non est; tunc peccatum incipit nasci. "
        )
        * 60,
        "https://a/oe",
    )
    kept, dropped = deduplicate_editions([excerpt, latin, whole, english])
    assert {s.url for s in kept} == {"https://g/1", "https://a/eng"}
    reasons = {s.url: why for s, why in dropped}
    assert reasons["https://newadvent/3"].startswith("an excerpt of https://g/1")
    assert reasons["https://a/oe"].startswith("another edition of https://a/eng")
