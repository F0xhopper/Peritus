"""Tests for the semantic chunker."""

from peritus.ingestion.chunker import _hard_split, _split_paragraphs, chunk_text


def test_split_respects_paragraph_boundaries():
    text = "Para one.\n\nPara two.\n\nPara three.\n\nPara four."
    chunks = _split_paragraphs(text, max_chars=30, overlap=10)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 60  # slack for overlap


def test_split_overlap_carries_content():
    text = "A" * 40 + "\n\n" + "B" * 40 + "\n\n" + "C" * 40
    chunks = _split_paragraphs(text, max_chars=50, overlap=45)
    assert len(chunks) >= 2
    # the overlap tail repeats the previous paragraph at the start of the next chunk
    assert chunks[1].startswith("A" * 40) or chunks[1].startswith("B" * 40)


def test_split_flattens_oversized_paragraph():
    text = "word " * 500  # one 2500-char paragraph, no blank lines
    chunks = _split_paragraphs(text.strip(), max_chars=400, overlap=50)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 400 + 50 + 2


def test_hard_split_prefers_sentence_boundaries():
    text = "First sentence here. Second sentence here. Third sentence here."
    chunks = _hard_split(text, max_chars=30)
    assert all(len(c) <= 30 for c in chunks)
    assert chunks[0].endswith(".")


def test_hard_split_slices_single_giant_sentence():
    text = "x" * 100
    chunks = _hard_split(text, max_chars=30)
    assert "".join(chunks) == text
    assert all(len(c) <= 30 for c in chunks)


def test_chunk_text_sequences_and_meta():
    text = "Intro paragraph.\n\nMore content here.\n\nAnd yet more content."
    chunks = chunk_text(text, "Test Source")
    assert chunks
    assert [c.sequence_n for c in chunks] == list(range(len(chunks)))
    for c in chunks:
        assert "section" in c.chunk_meta
        assert "paragraph_n" in c.chunk_meta


def test_chunk_text_empty_input():
    assert chunk_text("") == []


def test_chunk_text_detects_chapter_headings():
    body = "Some paragraph text that belongs to this chapter.\n\n"
    text = f"Chapter One: Beginnings\n\n{body}Chapter Two: Endings\n\n{body}"
    chunks = chunk_text(text, "Book")
    sections = {c.chunk_meta["section"] for c in chunks}
    assert len(sections) >= 2
