"""What the validator is shown.

The preview used to be three fixed windows of raw text, which asked the model to
infer from prose what the pipeline already knew for certain. These tests pin the
facts that are now stated rather than guessed, and the budget that keeps a batch
of five affordable.
"""

from peritus.sources.domain import Identifiers, RawSource, SourceType
from peritus.sources.preview import (
    PREVIEW_MAX_CHARS,
    REVIEW_PREVIEW_MAX_CHARS,
    build_preview,
    build_review_preview,
    references_offset,
)

_ABSTRACT = (
    "This paper argues that the analogical predication of being is neither a "
    "logical device nor a metaphysical hedge but the only coherent account of "
    "how finite language can name an infinite subject. "
)
_BODY_PARAGRAPH = (
    "Section text elaborating the argument in detail, with examples drawn from "
    "the commentary tradition and objections considered in turn. "
)
_REFERENCES = "\n".join(f"[{i}] Some Author, A Title, 1970." for i in range(40))


def _source(text: str | None = None, **metadata) -> RawSource:
    meta = {
        "abstract": _ABSTRACT,
        "year": 1993,
        "venue": "The Thomist",
        "cited_by_count": 214,
        "full_text_method": "europepmc_jats",
        "discovered_via": "snowball:backward",
        **metadata,
    }
    return RawSource(
        source_type=SourceType.OPENALEX,
        url="https://doi.org/10.1234/analogy",
        title="Analogy and the Naming of God",
        author="R. McInerny",
        text=text if text is not None else _BODY_PARAGRAPH * 200,
        metadata=meta,
        identifiers=Identifiers.build(doi="10.1234/analogy"),
    )


def test_the_preview_states_facts_instead_of_asking_the_model_to_infer_them():
    preview = build_preview(_source())

    assert "Analogy and the Naming of God" in preview
    assert "R. McInerny" in preview
    assert "1993" in preview
    assert "The Thomist" in preview
    assert "214" in preview, "citation count is a fact, not something to infer from prose"
    assert "10.1234/analogy" in preview
    assert "europepmc_jats" in preview, "how the text was obtained changes how to read it"
    assert "snowball:backward" in preview
    assert "characters" in preview, "length is a fact the model would otherwise guess"


def test_the_abstract_leads_because_it_is_the_densest_statement_of_the_claim():
    preview = build_preview(_source())
    assert _ABSTRACT[:60] in preview
    assert preview.index("Abstract") < preview.index("Body sample")


def test_section_headings_show_the_shape_of_the_document():
    """Methods/Results/Discussion versus one undifferentiated block is one of the
    strongest cheap signals of what a document is."""
    structured = "\n\n".join(
        f"{heading}\n\n{_BODY_PARAGRAPH * 12}"
        for heading in ("1. Introduction", "2. The Analogy of Proper Proportionality", "3. Conclusion")
    )
    preview = build_preview(_source(structured))
    assert "Section headings:" in preview
    assert "Introduction" in preview


def test_a_reference_list_is_detected_and_reported_rather_than_sampled():
    """Sampling inside a bibliography spends a window on citation strings that
    are the same in every paper in the field."""
    text = _BODY_PARAGRAPH * 200 + "\n\nReferences\n\n" + _REFERENCES
    assert references_offset(text) is not None

    preview = build_preview(_source(text))
    assert "Reference list: yes" in preview
    assert "[39] Some Author" not in preview


def test_the_word_references_in_the_middle_of_a_paper_is_not_a_bibliography():
    """Papers discuss "references" in their own prose. A false positive here
    would throw away most of the body."""
    text = "References\n\n" + _BODY_PARAGRAPH * 200
    assert references_offset(text) is None


def test_a_source_with_no_reference_list_says_so():
    assert "Reference list: not detected" in build_preview(_source())


def test_the_preview_stays_inside_its_budget():
    """A batch of five has to stay affordable on the fast model."""
    huge = _source(_BODY_PARAGRAPH * 5000)
    assert len(build_preview(huge)) <= PREVIEW_MAX_CHARS


def test_the_review_preview_is_larger_but_still_bounded():
    """Only borderline sources reach it, one per call, so it can afford to show
    a real cross-section — but not an unbounded one."""
    huge = _source(_BODY_PARAGRAPH * 5000)
    first, second = build_preview(huge), build_review_preview(huge)
    assert len(second) > len(first)
    assert len(second) <= REVIEW_PREVIEW_MAX_CHARS
    assert second.count("Body sample") == 4


def test_a_short_source_is_shown_whole_rather_than_windowed():
    short = _source("A brief note on analogy. " * 20)
    preview = build_preview(short)
    assert "Body sample:" in preview
    assert "1/2" not in preview


def test_an_empty_body_still_produces_a_usable_record():
    """A source whose text is only its abstract is common (a paywalled paper),
    and the validator still has to be able to judge it."""
    preview = build_preview(_source(""))
    assert "Analogy and the Naming of God" in preview
    assert _ABSTRACT[:40] in preview


def test_the_retrieval_method_is_never_guessed_from_a_flag():
    """The old fallback read `abstract` for any source without a `full_text`
    flag — telling the model that a 72,000-character Exa article was an
    abstract, which is a claim about depth made to the one caller judging
    depth. Every source type now has a named retrieval method."""
    from peritus.sources.domain import SourceType

    exa = _source(_BODY_PARAGRAPH * 300)
    exa.source_type = SourceType.EXA
    del exa.metadata["full_text_method"]

    preview = build_preview(exa)
    assert "Text obtained by: exa_contents" in preview
    assert "Text obtained by: abstract" not in preview
