"""Whether a chunk is prose worth paying for — decided before anything is paid for.

`chunker.clean_text` removes lines that have the shape of junk (a table of
contents, a numbered reference, a navigation bar). What it cannot see is a whole
chunk that is not prose in the corpus's language: an OCR'd scholarly edition
that interleaves Old English, Latin and apparatus with the translation (230
chunks of expert 66), a PubMed reference list whose entries are too long to
match a line pattern, an archive.org page of navigation ("Software Internet
Arcade Console Living Room"). Every one of those was contextualised, embedded,
keyword-indexed, sent to graph extraction and eligible for a context slot — and
the neighbour of the top hit on "who was the most impactful king?" was one.

The measure is the one ``sources/language.py`` uses for a whole text — the share
of common English function words — applied per chunk. Calibrated by hand on
chunks sampled from experts 41, 42, 43, 63 and 66 (2026-09-19): under 0.12 on a
chunk of forty words or more, 40 of 40 sampled were not usable prose (Latin, Old
English, reference entries, repository metadata); between 0.12 and 0.16 real
prose appears (the *Historia Brittonum* at 0.13, dense mathematics at 0.13), so
the threshold sits under it. Reference lists, which run 0.13–0.20, are caught by
their own shape instead.

Pure functions, no model call.
"""

from __future__ import annotations

import re

from peritus.core.config import settings
from peritus.sources.language import _ENGLISH, _WORD

#: Why a chunk was dropped, as counted in the build summary.
REASON_NOT_PROSE = "not_prose"
REASON_REFERENCES = "references"
REASON_FRAGMENT = "fragment"

_MIN_SHARE = 0.12
# Below this many words the function-word share is noise.
_MIN_WORDS_FOR_SHARE = 40
# A chunk this short with no sentence in it is a heading, a call number or a
# stray caption.
_FRAGMENT_MAX_WORDS = 25
_SENTENCE = re.compile(r"[a-z][a-z,;)'\"’”]*\s+[a-z]+[^.!?]*[.!?]")

# One bibliographic entry: "(2012)", "2015.", "et al.", "doi", a journal volume.
_CITATION_MARK = re.compile(
    r"\(\d{4}[a-z]?\)|\bet al\b|\bdoi\b|\b\d{1,4}\s*[:(]\s*\d{1,4}[)–-]|\b(?:19|20)\d{2}[a-z]?\.",
    re.IGNORECASE,
)
_REFERENCE_MIN_MARKS = 4
_REFERENCE_MAX_SHARE = 0.22


def function_word_share(text: str) -> tuple[float, int]:
    """``(share of English function words, word count)`` for ``text``."""
    words = [w.casefold() for w in _WORD.findall(text)]
    if not words:
        return 0.0, 0
    return sum(1 for w in words if w in _ENGLISH) / len(words), len(words)


def chunk_rejection(text: str) -> str | None:
    """Why ``text`` should not be ingested, or None when it is prose.

    Conservative: each rule was checked against real prose that sits near it,
    and when in doubt the chunk is kept. Only English has a word list, so for
    any other corpus language only the fragment rule applies.
    """
    share, words = function_word_share(text)
    if words <= _FRAGMENT_MAX_WORDS and not _SENTENCE.search(text):
        return REASON_FRAGMENT
    if settings.CORPUS_LANGUAGE != "en":
        return None
    if words >= _MIN_WORDS_FOR_SHARE and share < _MIN_SHARE:
        return REASON_NOT_PROSE
    if share < _REFERENCE_MAX_SHARE and len(_CITATION_MARK.findall(text)) >= _REFERENCE_MIN_MARKS:
        return REASON_REFERENCES
    return None


def is_prose(text: str) -> bool:
    return chunk_rejection(text) is None


# ── Near-duplicates ──────────────────────────────────────────────────────────

_SHINGLE = 5
_DUPLICATE_CONTAINMENT = 0.6


def shingles(text: str) -> set[tuple[str, ...]]:
    """Five-word shingles of ``text``, case-folded."""
    words = re.findall(r"\w+", text.casefold())
    if len(words) < _SHINGLE:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + _SHINGLE]) for i in range(len(words) - _SHINGLE + 1)}


def near_duplicate(a: set[tuple[str, ...]], b: set[tuple[str, ...]]) -> bool:
    """Whether one shingled text is mostly contained in the other.

    Containment in either direction, so a 1,500-character chunk of one edition
    and the 1,000-character chunk of another that sits inside it still match.
    The same translation of the same article, fetched from four hosts, is the
    same passage four times — and four seats of a fifteen-seat context.
    """
    if not a or not b:
        return False
    shared = len(a & b)
    return max(shared / len(a), shared / len(b)) >= _DUPLICATE_CONTAINMENT
