"""The expert's outline payload (audit/outline.py).

Pure functions over repository rows, so each rule the Outline view rests on is
pinned here: where one part ends and the next begins, that a line of body text
the chunker took for a heading does not become a part, that read-closely and
held never share one, where a section summary lands, and which key concepts a
part is allowed to claim.
"""

from datetime import UTC, datetime

from peritus.audit.outline import (
    MIN_PART,
    build_outline,
    build_outline_work,
    locus_group,
    summary_text,
)
from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier

KEY_CONCEPTS = ["The Five Ways", "Divine simplicity", "Natural law"]


def _expert(key_concepts=KEY_CONCEPTS) -> Expert:
    return Expert(
        id=1,
        name="thomism",
        topic="Thomism",
        status=ExpertStatus.READY,
        tier=ExpertTier.STANDARD,
        config=ExpertConfig.from_tier(ExpertTier.STANDARD),
        key_concepts=list(key_concepts),
        readiness="graph_ready",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _source(id, title="Summa Theologica, Part I", tier="primary"):
    return {
        "id": id,
        "title": title,
        "author": "Thomas Aquinas",
        "source_type": "gutenberg",
        "source_tier": tier,
    }


def _chunk(id, seq, section="", locus=None, held=False, source_id=10, heading=None):
    meta = {"section": section}
    if locus:
        meta["locus"] = locus
    if heading:
        meta["heading"] = heading
    if held:
        meta["ingest"] = "structural"
    return {"id": id, "source_id": source_id, "sequence_n": seq, "chunk_meta": meta, "chars": 900}


def _run(first_id, first_seq, n, section="", locus=None, **kwargs):
    """``n`` consecutive passages under one heading and locus."""
    return [_chunk(first_id + i, first_seq + i, section, locus, **kwargs) for i in range(n)]


def _outline(chunks, sections=(), hits=(), sources=None, expert=None):
    return build_outline(
        expert or _expert(), sources or [_source(10)], list(chunks), list(sections), list(hits)
    )


def test_a_locus_groups_only_when_it_is_a_place_within_something():
    assert locus_group("I, q. 2, a. 3") == "I, q. 2"
    assert locus_group("Book II, Chapter 3") == "Book II"
    # A place on its own: splitting on it would make a part of every annal.
    assert locus_group("A.D. 878") is None
    assert locus_group("Question 2") is None
    assert locus_group(None) is None


def test_a_new_heading_begins_a_part_and_the_range_is_its_loci():
    out = _outline(
        [
            _chunk(1, 0, "THE EXISTENCE OF GOD", "Question 2"),
            _chunk(2, 1, "THE EXISTENCE OF GOD", "I, q. 2, a. 1"),
            _chunk(3, 2, "THE EXISTENCE OF GOD", "I, q. 2, a. 3"),
            *_run(4, 3, 3, "OF THE SIMPLICITY OF GOD", "I, q. 3, a. 1"),
        ]
    )
    parts = out["works"][0]["parts"]
    assert [p["label"] for p in parts] == ["The Existence of God", "Of the Simplicity of God"]
    assert (parts[0]["locus_first"], parts[0]["locus_last"]) == ("Question 2", "I, q. 2, a. 3")
    assert parts[0]["passages"] == 3
    # The passage a reader opens the part at is its first.
    assert parts[1]["passage_id"] == 4


def test_body_text_taken_for_a_heading_does_not_become_a_part():
    """The chunker reads a line starting "part of…" as a heading. Real data:
    "part of some compound." sat between two runs of Prima Pars q. 3."""
    out = _outline(
        [
            _chunk(1, 0, "OF THE SIMPLICITY OF GOD", "I, q. 3, a. 7"),
            _chunk(2, 1, "part of some compound.", "I, q. 3, a. 8"),
            _chunk(3, 2, 'part with part."', "I, q. 3, a. 8"),
        ]
    )
    parts = out["works"][0]["parts"]
    assert len(parts) == 1
    assert parts[0]["label"] == "Of the Simplicity of God"
    assert parts[0]["locus_last"] == "I, q. 3, a. 8"


def test_unheaded_text_breaks_where_its_locus_moves_on():
    """A held stretch with no headings ("Full Text") ran from q. 35 to q. 66 of
    the Prima Pars. Labelled by whatever preceded it, it would have filed thirty
    questions under "Of the Image"."""
    out = _outline(
        [
            *_run(1, 0, 2, "OF THE IMAGE", "I, q. 35, a. 1", held=True),
            _chunk(3, 2, "Full Text", "I, q. 35, a. 2", held=True),
            *_run(4, 3, 3, "Full Text", "I, q. 36, a. 1", held=True),
        ]
    )
    parts = out["works"][0]["parts"]
    assert [(p["label"], p["locus_first"], p["locus_last"]) for p in parts] == [
        ("Of the Image", "I, q. 35, a. 1", "I, q. 35, a. 2"),
        (None, "I, q. 36, a. 1", "I, q. 36, a. 1"),
    ]


def test_annals_with_no_headings_are_one_part():
    out = _outline(
        [_chunk(i, i, "Full Text", f"A.D. {600 + i}") for i in range(6)],
        sources=[_source(10, title="The Anglo-Saxon Chronicle")],
    )
    (part,) = out["works"][0]["parts"]
    assert (part["locus_first"], part["locus_last"]) == ("A.D. 600", "A.D. 605")


def test_read_closely_and_held_never_share_a_part():
    out = _outline(
        [
            _chunk(1, 0, "THE ETERNITY OF GOD", "I, q. 10, a. 1"),
            _chunk(2, 1, "THE ETERNITY OF GOD", "I, q. 10, a. 2", held=True),
        ]
    )
    work = out["works"][0]
    assert [p["held"] for p in work["parts"]] == [False, True]
    assert (work["close"], work["held"], work["passages"]) == (1, 1, 2)
    assert out["totals"] == {
        "works": 1,
        "passages": 2,
        "close": 1,
        "held": 1,
        "parts": 2,
        "sections": 0,
    }


def test_holes_in_the_sequence_do_not_make_parts():
    """The prose gate dropped two passages in three of an edition of Bede that
    interleaves Old English; a part per island was 106 rows reading "Book I"."""
    out = _outline(
        [
            _chunk(1, 0, "Full Text", "Book I"),
            _chunk(2, 7, "Full Text", "Book I"),
            _chunk(3, 19, "Full Text", "Book I"),
            _chunk(4, 40, "Full Text", "Book I"),
        ]
    )
    (part,) = out["works"][0]["parts"]
    assert (part["passages"], part["seq_start"], part["seq_end"]) == (4, 0, 40)


def test_a_stray_heading_joins_the_part_before_it():
    """ "Truth", one passage long, between two chapters of the Contra Gentiles."""
    out = _outline(
        [
            *_run(1, 0, 5, "CHAPTER II", "Chapter II"),
            _chunk(6, 5, "TRUTH", "Chapter III"),
            *_run(7, 6, 4, "CHAPTER III", "Chapter III"),
        ]
    )
    parts = out["works"][0]["parts"]
    assert [(p["label"], p["passages"]) for p in parts] == [("Chapter II", 6), ("Chapter III", 4)]
    assert MIN_PART == 3


def test_a_short_opening_takes_the_name_of_the_longer_part_it_joins():
    out = _outline([_chunk(1, 0, "PREFACE"), *_run(2, 1, 6, "INTRODUCTION")])
    (part,) = out["works"][0]["parts"]
    assert (part["label"], part["passages"], part["passage_id"]) == ("Introduction", 7, 1)


def test_a_sentence_is_not_a_heading():
    """A held stretch of the Chronicle was titled by its first annal, a contents
    line titled a chapter, and a printer's colophon a part of Langstroth."""
    for raw in (
        "A.D. 1115. This year was the King Henry",
        "CII. That God's Happiness Is Perfect",
        "C. A. Mirick, Printer, Greenfield",
    ):
        (part,) = _outline(_run(1, 0, 3, raw))["works"][0]["parts"]
        assert part["label"] is None, raw
    (part,) = _outline(_run(1, 0, 3, "St. Thomas on Law"))["works"][0]["parts"]
    assert part["label"] == "St. Thomas on Law"


def test_a_structural_heading_names_a_held_part():
    out = _outline([_chunk(1, 0, "", "I, q. 25, a. 1", held=True, heading="THE POWER OF GOD")])
    assert out["works"][0]["parts"][0]["label"] == "The Power of God"


def test_a_section_lands_in_the_part_it_starts_in_clipped_to_it():
    chunks = [
        *_run(1, 0, 3, "THE EXISTENCE OF GOD", "I, q. 2, a. 3"),
        *_run(4, 3, 3, "OF THE SIMPLICITY OF GOD", "I, q. 3, a. 1"),
    ]
    sections = [
        # The summariser merged a short run across the heading: it still belongs
        # to the part it starts in, and is shown for the stretch inside it.
        {"source_id": 10, "seq_start": 0, "seq_end": 4, "summary": "  Five  proofs. "},
        {"source_id": 10, "seq_start": 40, "seq_end": 44, "summary": "Orphan."},
    ]
    work = build_outline_work(_expert(), _source(10), chunks, sections, [])
    assert work is not None
    first, second = work["parts"]
    assert first["sections"] == [
        {
            "seq_start": 0,
            "seq_end": 2,
            "passages": 3,
            "passage_id": 1,
            "locus_first": "I, q. 2, a. 3",
            "locus_last": "I, q. 2, a. 3",
            "summary": "Five proofs.",
        }
    ]
    assert (first["section_count"], second["section_count"], second["sections"]) == (1, 0, [])


def test_the_outline_counts_sections_and_one_work_carries_them():
    chunks = _run(1, 0, 4, "THE EXISTENCE OF GOD", "I, q. 2, a. 3")
    sections = [{"source_id": 10, "seq_start": 0, "seq_end": 3, "summary": None}]
    out = _outline(chunks, sections)
    (part,) = out["works"][0]["parts"]
    # Null is "not sent", never "none": the count beside it is the truth.
    assert (part["section_count"], part["sections"]) == (1, None)
    assert out["totals"]["sections"] == 1
    # The same parts, cut by the same function, so the view can match them.
    work = build_outline_work(_expert(), _source(10), chunks, sections, [])
    assert work is not None
    assert [p["seq_start"] for p in work["parts"]] == [part["seq_start"]]


def test_a_summary_loses_the_title_line_it_was_told_not_to_write():
    body = "Aquinas argues that sacred doctrine employs argument."
    assert summary_text(f"# Index Entry: Summa, Part I, Question 1\n\n{body}") == body
    assert (
        summary_text(f"**Summa, Part I, Question 3: Of the Simplicity of God**\n\n{body}") == body
    )
    assert summary_text(f"  {body}\nIt is  **one** science. ") == f"{body} It is one science."
    assert summary_text("Proceeds *a priori* or *a posteriori*.") == (
        "Proceeds a priori or a posteriori."
    )
    assert summary_text(None) == ""


def test_a_source_with_no_passages_is_not_a_work():
    assert build_outline_work(_expert(), _source(10), [], [], []) is None


def test_a_part_claims_a_key_concept_only_past_the_evidence_floor():
    chunks = [_chunk(i + 1, i, "THE EXISTENCE OF GOD", "I, q. 2, a. 3") for i in range(4)]
    hits = [
        {"source_id": 10, "sequence_n": 0, "idx": 0, "n": 5},
        {"source_id": 10, "sequence_n": 1, "idx": 0, "n": 3},
        {"source_id": 10, "sequence_n": 2, "idx": 1, "n": 3},
        # One stray node is not the part's subject…
        {"source_id": 10, "sequence_n": 3, "idx": 2, "n": 1},
        # …and an index the syllabus no longer has is never reported.
        {"source_id": 10, "sequence_n": 3, "idx": 9, "n": 8},
    ]
    out = _outline(chunks, hits=hits)
    assert out["works"][0]["parts"][0]["key_concepts"] == [0]
    assert out["key_concepts"] == KEY_CONCEPTS


def test_works_come_largest_first_and_a_source_with_no_passages_is_not_a_work():
    out = _outline(
        [
            _chunk(1, 0, "A", source_id=10),
            _chunk(2, 0, "B", source_id=11),
            _chunk(3, 1, "B", source_id=11),
        ],
        sources=[_source(10), _source(11, title="De ente et essentia"), _source(12)],
    )
    assert [w["source_id"] for w in out["works"]] == [11, 10]
    assert out["computed"] is True


def test_nothing_read_yet_is_not_computed():
    out = _outline([])
    assert out["computed"] is False
    assert out["works"] == []


def test_chunk_meta_may_arrive_as_a_json_string():
    row = _chunk(1, 0, "THE EXISTENCE OF GOD", "I, q. 2, a. 3")
    row["chunk_meta"] = '{"section": "THE EXISTENCE OF GOD", "locus": "I, q. 2, a. 3"}'
    assert _outline([row])["works"][0]["parts"][0]["locus_first"] == "I, q. 2, a. 3"
