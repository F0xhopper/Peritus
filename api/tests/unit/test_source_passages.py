"""The cited passage in context.

Two things are worth testing here and neither needs a database: the overlap the
chunker adds has to come *back off* when consecutive chunks are read as running
prose, and the decision about whether a source may be reproduced whole has to be
made from what is recorded rather than from what the client asked for.
"""

import json

import pytest

from peritus.api.routes.sources import _passage, _whole_text_allowed


def _row(chunk_id: int, sequence_n: int, text: str, **meta) -> dict:
    return {
        "id": chunk_id,
        "sequence_n": sequence_n,
        "text": text,
        "chunk_meta": json.dumps(meta) if meta else None,
    }


# ── the overlap comes back off ──────────────────────────────────────────────


def test_a_repeated_opening_sentence_is_dropped_from_the_later_chunk():
    first = _row(1, 0, "The mite feeds on fat body. It overwinters in the cluster.")
    second = _row(2, 1, "It overwinters in the cluster. Brood rearing resumes in February.")
    out = _passage(second, previous=first)
    assert out.text == "Brood rearing resumes in February."


def test_the_first_chunk_of_a_window_is_never_trimmed():
    first = _row(1, 0, "The mite feeds on fat body. It overwinters in the cluster.")
    assert _passage(first, previous=None).text == first["text"]


def test_a_one_sentence_paragraph_is_not_treated_as_overlap():
    # The chunker's own rule: a single sentence carried whole is a repeated
    # paragraph, not overlap, so it is never added — and never removed.
    first = _row(1, 0, "A single sentence stands alone.")
    second = _row(2, 1, "A single sentence stands alone. And then some more.")
    assert _passage(second, previous=first).text == second["text"]


def test_a_chunk_that_merely_starts_similarly_is_left_alone():
    first = _row(1, 0, "Varroa is a mite. Treatment is seasonal.")
    second = _row(2, 1, "Treatment is seasonal in temperate climates.")
    assert _passage(second, previous=first).text == second["text"]


def test_section_and_paragraph_come_through_when_the_chunker_recorded_them():
    out = _passage(_row(7, 3, "Some text.", section="Chapter 4", paragraph_n=12), previous=None)
    assert (out.chunk_id, out.sequence_n, out.section, out.paragraph_n) == (7, 3, "Chapter 4", 12)


def test_a_chunk_with_no_meta_reports_no_position_rather_than_guessing():
    out = _passage(_row(7, 3, "Some text."), previous=None)
    assert out.section is None and out.paragraph_n is None


# ── what may be reproduced whole ────────────────────────────────────────────


@pytest.mark.parametrize("source_type", ["gutenberg", "wikipedia", "arxiv"])
def test_the_open_kinds_may_be_read_whole(source_type):
    assert _whole_text_allowed({"source_type": source_type}, is_owner=False)


@pytest.mark.parametrize(
    "source_type", ["exa", "web", "thought_leader", "reddit", "youtube", "pdf"]
)
def test_everything_else_gets_a_window(source_type):
    assert not _whole_text_allowed({"source_type": source_type}, is_owner=True)


def test_an_open_access_copy_may_be_read_whole_whatever_found_it():
    # `oa_` means an open-access copy was resolved and read — the one licence
    # fact the pipeline actually records.
    assert _whole_text_allowed(
        {"source_type": "openalex", "full_text_method": "oa_pdf_url"}, is_owner=False
    )
    assert not _whole_text_allowed(
        {"source_type": "openalex", "full_text_method": "landing_page_url"}, is_owner=False
    )


def test_an_upload_is_whole_for_its_owner_and_a_window_for_a_guest():
    # The rights warning at upload was shown to the uploader, not to whoever
    # they later share the expert with.
    upload = {"source_type": "upload"}
    assert _whole_text_allowed(upload, is_owner=True)
    assert not _whole_text_allowed(upload, is_owner=False)


def test_an_abstract_only_source_has_nothing_more_to_read():
    assert not _whole_text_allowed(
        {"source_type": "arxiv", "full_text_method": "abstract"}, is_owner=True
    )
