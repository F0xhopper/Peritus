"""Semantic chunker — clean → sections → paragraph-sized chunks with overlap.

Source-agnostic: takes raw text + optional section hints from the source metadata.
Heuristic heading detection falls back when no hints are provided.

Before any of that, text that is not prose is removed (see :func:`clean_text`).
Measured on the production corpus, a quarter of all chunks were under 300 chars
and most of those were not prose: table-of-contents lines (201 of the Summa
Contra Gentiles' 213 chunks), numbered reference entries, and page chrome such
as "## Publish with us". Every one was contextualised, embedded, sent to graph
extraction and eligible for a context slot at chat time.
"""

import re
from dataclasses import dataclass

from peritus.core.config import settings
from peritus.core.logging import get_logger

logger = get_logger(__name__)

_CHAPTER_PATTERNS = [
    re.compile(r"^(chapter|part|book)\s+\w+[\s:—–-]", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s{0,4}[IVXLC]+\.\s+\w", re.MULTILINE),
]

# A numbered line ("3. Possession and Privation") is a heading only when a body
# follows it. Without that condition it matched every numbered list item, TOC
# line and reference, and each became a section — and so a chunk — of its own.
_NUMBERED_HEADING = re.compile(r"^\s{0,4}\d{1,2}\.\s+[A-Z][A-Za-z ]{3,}", re.MULTILINE)
_NUMBERED_HEADING_MIN_BODY = 200

_SECTION_PATTERNS = [
    re.compile(r"^\s{0,4}#{1,3} .+", re.MULTILINE),
    re.compile(r"^[A-Z][A-Z\s]{5,40}$", re.MULTILINE),
]

# A chunk shorter than this is merged into a neighbour: on its own it is rarely
# enough to answer anything, and it competes for a context slot with passages
# that are.
MIN_CHUNK_CHARS = 300

# ── Non-prose line patterns ──────────────────────────────────────────────────
# Each was written against lines sampled from the production corpus.

# "50. That God has proper knowledge of all things ... 80"
_TOC_LINE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?\S.{2,}?(?:\.{3,}|…+|\s\.\s\.\s\.)\s*\d{1,4}\s*$"
)

_REFERENCE_LINES = [
    # "22. Johnson RM, Evans JD, Robinson GE (2009) Changes in …"
    re.compile(r"^\s*\d{1,3}\.\s+(?:[A-Z][\w'’-]+\s[A-Z]{1,3}[,.]?\s*){1,}.*\(\d{4}[a-z]?\)"),
    # "6. Blackburn, Simon. 1998. Realism and Truth …" / "30. Lucas, J. R., The Phenomenon …"
    re.compile(
        r"^\s*\d{1,3}\.\s+[A-Z][\w'’-]+,\s+(?:[A-Z][a-z]+\.?|(?:[A-Z]\.\s?)+),?\s.*\b(?:1[5-9]|20)\d{2}\b"
    ),
    # "17. Id at 153." / "19. Ibid., p. 11."
    re.compile(r"^\s*\d{1,3}\.\s+(?:Ibid|Id\.?|Op\.\s?cit|Cf\.)\b", re.IGNORECASE),
    # Publisher link chrome on a reference entry.
    re.compile(
        r"\[(?:Google Scholar|CrossRef|PubMed|Scopus|Web of Science)\]|\bGoogle Scholar\.?\s*$"
    ),
    # A line that is only a DOI or doi.org link.
    re.compile(r"^\s*(?:doi:\s*|https?://(?:dx\.)?doi\.org/)\S+\s*$", re.IGNORECASE),
]

# "HOME | PERIODICALS | ABOUT | CONTACT" — pipe-separated navigation, as opposed
# to a markdown table row, which starts with a pipe.
_NAV_LINE = re.compile(r"^(?!\s*\|)[^|\n]{1,30}(?:\s\|\s[^|\n]{1,30}){3,}\s*$")

# A line that is only a number: page numbers and footnote markers from PDF text.
_BARE_NUMBER_LINE = re.compile(r"^\s*\d{1,4}\s*$")

# Section headings whose sections are page chrome or back matter, not content.
_BOILERPLATE_HEADINGS = re.compile(
    r"^\s{0,4}#{1,6}\s*(?:"
    r"acknowledge?ments?|competing interests?|conflicts? of interests?|"
    r"declaration of (?:competing )?interests?|informed consent(?: statement)?|"
    r"institutional review board(?: statement)?|data availability(?: statement)?|"
    r"author contributions?|funding(?: statement)?|additional information|"
    r"publish with us|other ways to access|was this page helpful\??|"
    r"similar items.*|flag this item.*|.*citation style:?|cite this (?:article|page)|"
    r"rights and permissions|about this (?:article|book|chapter)|share this (?:article|page)|"
    r"related (?:articles|posts|items)|table of contents|contents|topics|readme|"
    r"(?P<back>references|bibliography|works cited|literature cited|notes and references|footnotes)"
    r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# Page chrome is short. A "Contents" heading over 90K chars of text is not chrome,
# whatever it is called, and cutting to the next heading would take all of it.
_BOILERPLATE_MAX_CHARS = 2000
# Back matter is long, so it has no length cap — but it is at the back. A
# "References" heading in the first fifth of a document is something else.
_BACK_MATTER_MIN_POSITION = 0.2
_ANY_HEADING = re.compile(r"^\s{0,4}#{1,6}\s+\S", re.MULTILINE)


@dataclass
class TextChunk:
    text: str
    sequence_n: int
    chunk_meta: dict


@dataclass
class CleanStats:
    """What :func:`clean_text` removed, for the build log."""

    chars_in: int
    chars_out: int

    @property
    def dropped_share(self) -> float:
        return 0.0 if self.chars_in == 0 else 1 - self.chars_out / self.chars_in


def chunk_text(text: str, source_title: str = "") -> list[TextChunk]:
    cleaned, stats = clean_text(text)
    if stats.chars_in and stats.dropped_share >= 0.05:
        # A source that is mostly junk (the Summa was 94% table of contents) is
        # worth seeing in the build log: it was probably fetched from the wrong
        # resolver, and the prose version is somewhere else.
        log = logger.warning if stats.dropped_share >= 0.5 else logger.info
        log(
            "Dropped %.0f%% of %r as non-prose (%d of %d chars)",
            stats.dropped_share * 100,
            source_title,
            stats.chars_in - stats.chars_out,
            stats.chars_in,
        )

    sections = _detect_sections(cleaned)
    logger.info("Detected %d sections for %r", len(sections), source_title)

    pieces: list[tuple[str, str]] = []
    for sec_title, sec_text in sections:
        if not sec_text.strip():
            continue
        paras = _split_paragraphs(sec_text, settings.CHUNK_SIZE_CHARS, settings.CHUNK_OVERLAP_CHARS)
        pieces.extend((sec_title, p) for p in paras)

    pieces = _merge_small(pieces, MIN_CHUNK_CHARS, settings.CHUNK_SIZE_CHARS)

    chunks: list[TextChunk] = []
    para_n_by_section: dict[str, int] = {}
    for seq, (sec_title, para_text) in enumerate(pieces):
        para_n = para_n_by_section.get(sec_title, 0) + 1
        para_n_by_section[sec_title] = para_n
        chunks.append(
            TextChunk(
                text=para_text,
                sequence_n=seq,
                chunk_meta={"section": sec_title, "paragraph_n": para_n},
            )
        )

    logger.info("Built %d chunks for %r", len(chunks), source_title)
    return chunks


def clean_text(text: str) -> tuple[str, CleanStats]:
    """Remove what is not prose: TOC lines, reference entries, page chrome.

    Conservative by construction — each pattern matches a shape prose does not
    take — and line-based, so a paragraph of real text is never cut in half.
    """
    chars_in = len(text)
    text = _drop_boilerplate_sections(text)
    kept = [line for line in text.split("\n") if not _is_junk_line(line)]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return cleaned, CleanStats(chars_in=chars_in, chars_out=len(cleaned))


# Length ceilings on the line patterns. A text extractor often emits a whole
# paragraph as one line, and a pattern that matches a line drops all of it — so
# each shape is only trusted at the length that shape actually has.
_TOC_MAX_LINE = 200
_REFERENCE_MAX_LINE = 500


def _is_junk_line(line: str) -> bool:
    if not line.strip():
        return False
    if _BARE_NUMBER_LINE.match(line) or _NAV_LINE.match(line):
        return True
    if len(line) <= _TOC_MAX_LINE and _TOC_LINE.match(line):
        return True
    return len(line) <= _REFERENCE_MAX_LINE and any(p.search(line) for p in _REFERENCE_LINES)


def _drop_boilerplate_sections(text: str) -> str:
    """Cut a boilerplate-headed section from its heading to the next heading."""
    out: list[str] = []
    pos = 0
    for m in _BOILERPLATE_HEADINGS.finditer(text):
        if m.start() < pos:
            continue
        nxt = _ANY_HEADING.search(text, m.end())
        end = nxt.start() if nxt else len(text)
        if m.group("back"):
            if m.start() < len(text) * _BACK_MATTER_MIN_POSITION:
                continue
        elif end - m.start() > _BOILERPLATE_MAX_CHARS:
            continue
        out.append(text[pos : m.start()])
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _detect_sections(text: str) -> list[tuple[str, str]]:
    boundaries: list[tuple[int, str]] = []

    for pattern in _CHAPTER_PATTERNS + _SECTION_PATTERNS:
        for m in pattern.finditer(text):
            boundaries.append((m.start(), _line_at(text, m.start())))

    starts = [m.start() for m in _NUMBERED_HEADING.finditer(text)]
    for i, start in enumerate(starts):
        line_end = text.find("\n", start)
        line_end = len(text) if line_end == -1 else line_end
        next_start = starts[i + 1] if i + 1 < len(starts) else len(text)
        if len(text[line_end:next_start].strip()) >= _NUMBERED_HEADING_MIN_BODY:
            boundaries.append((start, _line_at(text, start)))

    boundaries.sort(key=lambda x: x[0])
    # Deduplicate overlapping boundaries
    deduped: list[tuple[int, str]] = []
    for b in boundaries:
        if not deduped or b[0] > deduped[-1][0] + 5:
            deduped.append(b)

    if not deduped:
        return [("Full Text", text)]

    sections: list[tuple[str, str]] = []
    if deduped[0][0] > 0 and text[: deduped[0][0]].strip():
        sections.append(("Full Text", text[: deduped[0][0]].strip()))
    for i, (start, title) in enumerate(deduped):
        end = deduped[i + 1][0] if i + 1 < len(deduped) else len(text)
        sections.append((title, text[start:end].strip()))
    return sections


def _line_at(text: str, start: int) -> str:
    end = text.find("\n", start)
    return text[start : end if end != -1 else len(text)].strip()


def _split_paragraphs(text: str, max_chars: int, overlap: int) -> list[str]:
    """Pack paragraphs into chunks of at most ``max_chars``.

    A paragraph too long for one chunk is split at sentence boundaries. Each
    chunk after the first opens with the last sentence of the one before it,
    when that sentence is no longer than ``overlap`` — enough to carry a
    referent across the cut. The old overlap rebuilt a tail from whole
    paragraphs that fit in 200 chars, which for prose was almost never any.
    """
    raw_paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    # Flatten any paragraph that exceeds max_chars (e.g. transcript with no blank lines)
    paras: list[str] = []
    for para in raw_paras:
        if len(para) > max_chars:
            paras.extend(_hard_split(para, max_chars))
        else:
            paras.append(para)

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paras:
        if current and current_len + len(para) + 2 > max_chars:
            chunks.append("\n\n".join(current))
            tail = _last_sentence(current[-1])
            if tail and len(tail) <= overlap and len(tail) + len(para) + 1 <= max_chars:
                current, current_len = [tail], len(tail) + 2
            else:
                current, current_len = [], 0

        current.append(para)
        current_len += len(para) + 2

    if current:
        chunks.append("\n\n".join(current))

    return [c for c in chunks if c.strip()]


def _last_sentence(text: str) -> str:
    sentences = [s for s in _SENTENCE_BREAK.split(text.strip()) if s.strip()]
    # A one-sentence paragraph carried whole is a repeated paragraph, not overlap.
    return sentences[-1].strip() if len(sentences) > 1 else ""


def _merge_small(
    pieces: list[tuple[str, str]], min_chars: int, max_chars: int
) -> list[tuple[str, str]]:
    """Fold each chunk under ``min_chars`` into a neighbour.

    The previous chunk if the result stays within ``max_chars`` plus the small
    chunk's own allowance, else the next one; a small chunk with no neighbour
    that fits stands alone. Section labels follow the larger side, which is the
    one whose content dominates the merged chunk.
    """
    limit = max_chars + min_chars
    out: list[tuple[str, str]] = []
    carry: tuple[str, str] | None = None
    for section, text in pieces:
        if carry is not None:
            text = f"{carry[1]}\n\n{text}"
            section = carry[0] if len(carry[1]) > len(text) - len(carry[1]) else section
            carry = None
        if len(text) >= min_chars:
            out.append((section, text))
            continue
        if out and len(out[-1][1]) + len(text) + 2 <= limit:
            prev_section, prev_text = out[-1]
            out[-1] = (prev_section, f"{prev_text}\n\n{text}")
        else:
            carry = (section, text)
    if carry is not None:
        if out and len(out[-1][1]) + len(carry[1]) + 2 <= limit:
            out[-1] = (out[-1][0], f"{out[-1][1]}\n\n{carry[1]}")
        else:
            out.append(carry)
    return out


_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def _hard_split(text: str, max_chars: int) -> list[str]:
    """Split an oversized block at sentence boundaries, falling back to character slicing."""
    sentences = _SENTENCE_BREAK.split(text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            for i in range(0, len(sentence), max_chars):
                chunks.append(sentence[i : i + max_chars])
        elif current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = (current + " " + sentence).strip() if current else sentence

    if current:
        chunks.append(current.strip())

    return chunks
