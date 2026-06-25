"""Semantic chunker — sections → paragraph-sized chunks with overlap.

Source-agnostic: takes raw text + optional section hints from the source metadata.
Heuristic heading detection falls back when no hints are provided.
"""

import re
from dataclasses import dataclass

from peritus.core.config import settings
from peritus.core.logging import get_logger

logger = get_logger(__name__)

_CHAPTER_PATTERNS = [
    re.compile(r"^(chapter|part|book)\s+\w+[\s:—–-]", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s{0,4}[IVXLC]+\.\s+\w", re.MULTILINE),
    re.compile(r"^\s{0,4}\d{1,2}\.\s+[A-Z][A-Za-z ]{3,}", re.MULTILINE),
]

_SECTION_PATTERNS = [
    re.compile(r"^\s{0,4}#{1,3} .+", re.MULTILINE),
    re.compile(r"^[A-Z][A-Z\s]{5,40}$", re.MULTILINE),
]


@dataclass
class TextChunk:
    text: str
    sequence_n: int
    chunk_meta: dict


def chunk_text(text: str, source_title: str = "") -> list[TextChunk]:
    sections = _detect_sections(text)
    logger.info("Detected %d sections for %r", len(sections), source_title)

    chunks: list[TextChunk] = []
    seq = 0

    for sec_title, sec_text in sections:
        if not sec_text.strip():
            continue
        paras = _split_paragraphs(sec_text, settings.CHUNK_SIZE_CHARS, settings.CHUNK_OVERLAP_CHARS)
        for para_n, para_text in enumerate(paras, start=1):
            chunks.append(TextChunk(
                text=para_text,
                sequence_n=seq,
                chunk_meta={"section": sec_title, "paragraph_n": para_n},
            ))
            seq += 1

    logger.info("Built %d chunks for %r", len(chunks), source_title)
    return chunks


def _detect_sections(text: str) -> list[tuple[str, str]]:
    boundaries: list[tuple[int, str]] = []

    for pattern in _CHAPTER_PATTERNS + _SECTION_PATTERNS:
        for m in pattern.finditer(text):
            heading = text[m.start():text.find("\n", m.start())].strip()
            boundaries.append((m.start(), heading))

    boundaries.sort(key=lambda x: x[0])
    # Deduplicate overlapping boundaries
    deduped: list[tuple[int, str]] = []
    for b in boundaries:
        if not deduped or b[0] > deduped[-1][0] + 5:
            deduped.append(b)

    if not deduped:
        return [("Full Text", text)]

    sections: list[tuple[str, str]] = []
    for i, (start, title) in enumerate(deduped):
        end = deduped[i + 1][0] if i + 1 < len(deduped) else len(text)
        sections.append((title, text[start:end].strip()))
    return sections


def _split_paragraphs(text: str, max_chars: int, overlap: int) -> list[str]:
    raw_paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in raw_paras:
        if current_len + len(para) + 1 > max_chars and current:
            chunks.append("\n\n".join(current))
            tail: list[str] = []
            tail_len = 0
            for p in reversed(current):
                if tail_len + len(p) <= overlap:
                    tail.insert(0, p)
                    tail_len += len(p)
                else:
                    break
            current = tail
            current_len = tail_len

        current.append(para)
        current_len += len(para) + 1

    if current:
        chunks.append("\n\n".join(current))

    return [c for c in chunks if c.strip()]
