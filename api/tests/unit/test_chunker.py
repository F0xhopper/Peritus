"""Tests for the semantic chunker."""

from peritus.ingestion.chunker import (
    _hard_split,
    _merge_small,
    _split_paragraphs,
    chunk_text,
    clean_text,
)


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
    # Bodies long enough to stand as chunks: a sub-300-char chunk is merged
    # into its neighbour, whatever section it came from.
    body = "Some paragraph text that belongs to this chapter. " * 8 + "\n\n"
    text = f"Chapter One: Beginnings\n\n{body}Chapter Two: Endings\n\n{body}"
    chunks = chunk_text(text, "Book")
    sections = {c.chunk_meta["section"] for c in chunks}
    assert len(sections) >= 2


# ── Chunk hygiene (R3) ──────────────────────────────────────────────────────
# Every junk line below is a real chunk from the production corpus.

_PROSE = (
    "Aquinas holds that the ultimate end of man is beatitude, which consists in the "
    "contemplation of God. Created goods cannot satisfy the will, because the will's "
    "object is the universal good. Happiness in this life is therefore imperfect, and "
    "perfect happiness is reserved for the vision of the divine essence."
)


def test_clean_text_drops_table_of_contents_lines():
    toc = "\n".join([
        "1. In what the office of a wise man consists ... 1",
        "50. That God has proper knowledge of all things ... 80",
        "67. Against those who say that the possible intellect is the imagination ... 281",
    ])
    cleaned, stats = clean_text(f"{toc}\n\n{_PROSE}")
    assert cleaned == _PROSE
    assert stats.dropped_share > 0.2


def test_clean_text_drops_reference_entries():
    refs = "\n".join([
        "22. Johnson RM, Evans JD, Robinson GE, Berenbaum MR (2009) Changes in transcript "
        "abundance relating to colony collapse disorder in honey bees.",
        "6. Blackburn, Simon. 1998. Realism and Truth: Wittgenstein, Wright, Rorty, and "
        "Minimalism. Mind 107: 157–81. [Google Scholar] [CrossRef]",
        "30. Lucas, J. R., The Phenomenon of Law in Hacker, P. M. S. and Raz, J., eds, "
        "Law, Morality, and Society (Clarendon Press, 1977)",
        "17. Id at 153.",
        "19. Ibid., p. 11. Cf. C.G., 1, 22.",
        "https://doi.org/10.1371/journal.pone.0000000",
    ])
    cleaned, _ = clean_text(f"{_PROSE}\n\n{refs}")
    assert cleaned == _PROSE


def test_clean_text_drops_boilerplate_sections_and_nav():
    page = (
        "HOME | PERIODICALS | ABOUT | CONTACT\n\n"
        f"## Natural law\n\n{_PROSE}\n\n"
        "## Competing interests\n\nThe authors declare that they have no competing interests.\n\n"
        "## Publish with us\n\nBack to top\n\n"
        f"## Virtue\n\n{_PROSE}"
    )
    cleaned, _ = clean_text(page)
    assert "PERIODICALS" not in cleaned
    assert "competing interests" not in cleaned
    assert "Back to top" not in cleaned
    assert cleaned.count(_PROSE) == 2
    assert "## Virtue" in cleaned


def test_clean_text_leaves_prose_and_real_tables_alone():
    text = (
        f"{_PROSE}\n\n"
        "| Colony | Mites per 100 bees |\n| --- | --- |\n| A | 3 |\n\n"
        "1. No deduction has two negative premises, and this is shown by counterexample "
        "in the Prior Analytics."
    )
    cleaned, stats = clean_text(text)
    assert cleaned == text
    assert stats.dropped_share == 0


def test_clean_text_keeps_a_long_paragraph_that_happens_to_end_like_a_toc_line():
    paragraph = _PROSE + " The count, he says, goes on... 3"
    cleaned, _ = clean_text(paragraph)
    assert cleaned == paragraph


def test_numbered_list_items_are_not_sections():
    """A numbered line used to open a section — and a chunk — of its own."""
    items = "\n\n".join(
        f"{i}. Possession and privation are opposed as a state and its absence"
        for i in range(1, 7)
    )
    chunks = chunk_text(f"{_PROSE}\n\n{items}", "Aristotle's Logic")
    assert len(chunks) == 1
    assert chunks[0].chunk_meta["section"] == "Full Text"


def test_text_before_the_first_heading_is_kept():
    text = f"{_PROSE}\n\n## Second part\n\n{_PROSE}"
    joined = "\n".join(c.text for c in chunk_text(text, "Paper"))
    assert joined.count("Aquinas holds") == 2


def test_merge_small_folds_short_chunks_into_a_neighbour():
    pieces = [("A", "x" * 600), ("B", "## Heading only"), ("C", "y" * 600)]
    merged = _merge_small(pieces, min_chars=300, max_chars=1000)
    assert len(merged) == 2
    assert merged[0][1].endswith("## Heading only")
    assert all(len(text) >= 300 for _, text in merged)


def test_merge_small_carries_forward_when_the_previous_chunk_is_full():
    pieces = [("A", "x" * 1299), ("B", "short"), ("C", "y" * 600)]
    merged = _merge_small(pieces, min_chars=300, max_chars=1000)
    assert [s for s, _ in merged] == ["A", "C"]
    assert merged[1][1].startswith("short")


def test_overlap_is_one_trailing_sentence():
    first = "Alpha sentence one. Alpha sentence two is the tail."
    second = "Beta paragraph " * 5
    chunks = _split_paragraphs(f"{first}\n\n{second.strip()}", max_chars=120, overlap=200)
    assert len(chunks) == 2
    assert chunks[1].startswith("Alpha sentence two is the tail.")


def test_a_long_section_under_a_chrome_heading_is_kept():
    # A real page: "## Table of Contents" followed by the whole work, no other heading.
    text = "## Table of Contents\n\n" + "\n\n".join([_PROSE] * 12)
    cleaned, _ = clean_text(text)
    assert cleaned.count(_PROSE) == 12


def test_references_heading_near_the_start_is_not_back_matter():
    text = "## References\n\n" + "\n\n".join([_PROSE] * 6)
    cleaned, _ = clean_text(text)
    assert cleaned.count(_PROSE) == 6


def test_back_matter_is_dropped_to_the_end():
    refs = "\n".join(f"A reference-looking line number {i} with no pattern" for i in range(80))
    text = "\n\n".join([_PROSE] * 6) + f"\n\n## References\n\n{refs}"
    cleaned, _ = clean_text(text)
    assert cleaned == "\n\n".join([_PROSE] * 6)
