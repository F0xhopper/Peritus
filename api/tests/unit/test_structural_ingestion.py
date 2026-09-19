"""Structural ingestion and the prose gate: loci, notes, tail segments, choice.

Pure functions; no database, no embeddings.
"""

from peritus.ingestion.chunker import TextChunk
from peritus.ingestion.pipeline import prepare_chunks
from peritus.ingestion.quality import chunk_rejection
from peritus.ingestion.structural import (
    Segment,
    annotate_loci,
    choose_segments,
    segment_title,
    segments_of,
    structural_note,
    uncovered_spans,
)

_PROSE = (
    "It seems that the soul is a body, for the soul is the moving principle of the body, and "
    "nothing moves unless it is moved. But the contrary is true of the thing as it is. "
)


def _chunk(text: str, seq: int = 0) -> TextChunk:
    return TextChunk(text=text, sequence_n=seq, chunk_meta={})


def test_summa_articles_become_loci_with_their_titles():
    chunks = [
        _chunk("QUESTION 75\n\nOF MAN\n\n" + _PROSE),
        _chunk("FIRST ARTICLE [I, Q. 75, Art. 1]\n\nWhether the Soul Is a Body?\n\n" + _PROSE),
        _chunk(_PROSE * 2),
        _chunk(_PROSE + "\n\nSECOND ARTICLE [I, Q. 75, Art. 2]\n\nWhether the Soul Is Subsistent?"),
    ]
    annotate_loci(chunks)
    assert chunks[0].chunk_meta["locus"] == "Question 75"
    assert chunks[1].chunk_meta["locus"] == "I, q. 75, a. 1"
    assert chunks[1].chunk_meta["article"] == "Whether the Soul Is a Body?"
    assert chunks[2].chunk_meta["locus"] == "I, q. 75, a. 1"
    # Article 2 begins in the last half of chunk 3: the chunk is article 1's.
    assert chunks[3].chunk_meta["locus"] == "I, q. 75, a. 1"


def test_annals_and_chapters():
    annals = [_chunk("A.D. 878. This year the army stole into Chippenham."), _chunk(_PROSE)]
    annotate_loci(annals)
    assert [c.chunk_meta["locus"] for c in annals] == ["A.D. 878", "A.D. 878"]
    book = [_chunk("BOOK II\n\nCHAPTER 3\n\n" + _PROSE)]
    annotate_loci(book)
    assert book[0].chunk_meta["locus"] == "Book II, Chapter 3"
    plain = [_chunk(_PROSE)]
    annotate_loci(plain)
    assert "locus" not in plain[0].chunk_meta


def test_the_note_is_the_heading_path():
    meta = {
        "locus": "I, q. 75, a. 1",
        "heading": "Of Man",
        "article": "Whether the Soul Is a Body?",
    }
    title = "Summa Theologica, Part I (Prima Pars) — From the Complete American Edition"
    assert structural_note(title, meta) == (
        "From Summa Theologica, Part I (Prima Pars) › I, q. 75, a. 1 › Of Man › "
        "Whether the Soul Is a Body?"
    )
    assert structural_note("A Book", {}) == "From A Book."


def test_segment_titles():
    assert segment_title("QUESTION 79: OF THE INTELLECTUAL POWERS") == "Of the Intellectual Powers"
    long = (
        "QUESTION 75: OF MAN WHO IS COMPOSED OF A SPIRITUAL AND A CORPOREAL SUBSTANCE: AND "
        "IN THE FIRST PLACE, CONCERNING WHAT BELONGS TO THE ESSENCE OF THE SOUL"
    )
    assert segment_title(long) == "Of Man Who Is Composed of a Spiritual and a Corporeal Substance"


def test_uncovered_spans_are_what_the_close_read_left():
    assert uncovered_spans(100_000, [(0, 20_000)]) == [(20_000, 100_000)]
    assert uncovered_spans(100_000, [(0, 1_000), (50_000, 60_000)]) == [
        (1_000, 50_000),
        (60_000, 100_000),
    ]
    assert uncovered_spans(20_500, [(0, 20_000)]) == []  # too little to hold


def test_a_tail_is_cut_at_its_questions():
    body = "".join(f"\nQUESTION {n}\nTHE TITLE OF {n}\n{_PROSE * 20}\n" for n in range(1, 6))
    segments = segments_of("x" * 1000 + body, (1000, 1000 + len(body)))
    assert [s.heading for s in segments] == [f"QUESTION {n}: THE TITLE OF {n}" for n in range(1, 6)]
    windows = segments_of(_PROSE * 1000, (0, len(_PROSE) * 1000))
    assert all(s.length <= 60_000 for s in windows) and len(windows) > 1


def test_the_budget_is_spread_across_concepts():
    segs = [Segment(0, i * 10, i * 10 + 10, f"s{i}") for i in range(6)]
    # Concept 0 likes every segment more than concept 1 likes any; round-robin
    # still gives concept 1 its best.
    scores = [[0.9, 0.1], [0.8, 0.2], [0.7, 0.6], [0.6, 0.1], [0.5, 0.1], [0.4, 0.1]]
    chosen = choose_segments(segs, scores, budget_chars=20)
    assert [s.heading for s in chosen] == ["s0", "s2"]
    assert choose_segments(segs, scores, budget_chars=0) == []


def test_prepare_chunks_drops_what_is_not_prose_and_counts_it():
    from collections import Counter

    latin = (
        "Cum enim malignus spiritus peccatum suggerit in mente, si nulla peccati delectatio "
        "sequatur, peccatum omnimodo perpetratum non est; cum uero delectare caro coeperit, "
        "tunc peccatum incipit nasci; si autem etiam ex deliberatione consentit, tunc "
    )
    text = f"{_PROSE * 6}\n\n{latin * 5}\n\n{_PROSE * 6}"
    dropped: Counter = Counter()
    chunks = prepare_chunks(text, "Bede", dropped)
    assert dropped["not_prose"] >= 1
    assert all(chunk_rejection(c.text) is None for c in chunks)
    # The gap stays in the sequence: what follows the junk is not a continuation.
    seqs = [c.sequence_n for c in chunks]
    assert seqs != list(range(len(seqs)))


def test_prose_passes_the_gate():
    assert chunk_rejection(_PROSE * 3) is None
    assert chunk_rejection("## Results") == "fragment"
    refs = " ".join(
        f"{n}. Smith AB, Jones CD, et al. ({2000 + n}) A study of mites. J Apic 5: {n}–{n + 9}."
        for n in range(1, 8)
    )
    assert chunk_rejection(refs) in ("references", "not_prose")
