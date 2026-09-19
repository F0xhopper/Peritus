"""How a passage is labelled: the work, and where in it the passage sits.

The label used to be the source's title and nothing else, so every passage of
the Prima Pars read "Summa Theologica, Part I (Prima Pars) — From the Complete
American Edition". The model could not say "in the question on the existence of
God" with any confidence, the reader's citation panel could not show it, and a
judge comparing the answer with a closed-book one marked it down for naming no
locus while the closed-book answer named eight from memory.

The section heading is on every chunk (``chunk_meta.section``) — but it is what
the chunker's heading heuristics matched, and on the stored corpus that
includes a line of prose that happened to begin "part of the army…", a
reference entry, "## Cited by (32)" and a title truncated at a line break. So a
heading is used only when it looks like one; otherwise the label is the title
alone, as before. A numbered locus (``chunk_meta.locus``: "I, q. 2, a. 3")
comes from structural ingestion and leads when present.

The same string reaches the model, the SSE ``sources`` event and the citation
panel, so it is kept short.
"""

from __future__ import annotations

import re

from peritus.sources.titles import clean_title

# Site and edition chrome on the end of a scraped title.
_TITLE_SUFFIX = re.compile(
    r"\s*(?:"
    r"[-|–—•]\s*(?:Archive\.org|Internet Archive|Wikisource, the free online library|Wikipedia"
    r"|Cambridge Core|Springer Nature Link|Library of Congress|researchr publication"
    r"|Nature Communications|Internet Encyclopedia of Philosophy|Philosophy Institute)"
    r"|—\s*From the Complete American Edition"
    r"|\|\s*[^|]{1,40}\|\s*\d+\s+Citations"
    r")\s*$",
    re.IGNORECASE,
)
# "(PDF) " in front, or "PDF" glued onto an all-caps title ("PDFAQUINAS ON …").
_TITLE_PREFIX = re.compile(r"^(?:\(PDF\)\s*|PDF(?=[A-Z]{3}))")

_HEADING_MAX_CHARS = 70
_HEADING_MAX_WORDS = 10
# Words that mark a heading as page furniture or back matter, not a place in
# the work.
_NOT_A_PLACE = re.compile(
    r"\b(?:cited by|save article|kindle|references|bibliography|contents|abstract|"
    r"copyright|press|login|download|footnotes?|index|acknowledge?ments?|cookies?|"
    r"similar content|contributions|author information|electronic edition|nasa ads)\b",
    re.IGNORECASE,
)
# "Part 1 The kinds of question we ask…": a numbered heading with the first
# sentence of its body run on. The number is the heading.
_NUMBERED_LEAD = re.compile(
    r"^(?P<lead>(?:part|book|chapter|question|article|section|lecture|letter)\s+"
    r"(?:\d{1,4}|[IVXLC]{1,8})\b)",
    re.IGNORECASE,
)
_ROMAN = re.compile(r"^[IVXLC]+$")
_YEAR_ENTRY = re.compile(r"\b(?:1[5-9]|20)\d{2}\b.*,|,.*\b(?:1[5-9]|20)\d{2}\b")


def citation_title(title: str) -> str:
    """A source title without the site and edition chrome scraped along with it."""
    text = _TITLE_PREFIX.sub("", " ".join((title or "").split()))
    previous = None
    while previous != text:
        previous = text
        text = _TITLE_SUFFIX.sub("", text)
    return clean_title(text) or clean_title(title)


def section_heading(
    raw: str | None,
    title: str = "",
    max_chars: int = _HEADING_MAX_CHARS,
    max_words: int = _HEADING_MAX_WORDS,
) -> str | None:
    """``raw`` as a heading fit to show, or None when it is not one."""
    text = " ".join((raw or "").split())
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = re.sub(r"\s*\[\d{1,4}\]\s*$", "", text).strip(" .:")
    if not text or text.casefold() == "full text":
        return None
    lead = _NUMBERED_LEAD.match(text)
    if lead and (len(text) > max_chars or len(text.split()) > max_words):
        text = lead.group("lead")
    # "CHAPTER XIII 25": the trailing number is the page it was printed on.
    text = re.sub(
        r"^((?:chapter|book|part)\s+[IVXLC]+)\s+(?:\d{1,4}|\S*[\^|]\S*)$",
        r"\1",
        text,
        flags=re.IGNORECASE,
    )
    if (
        len(text) > max_chars
        or len(text.split()) > max_words
        or (not text[0].isupper() and not text[0].isdigit())
        or re.search(r"[\^|{}<>]", text)
        or _NOT_A_PLACE.search(text)
        or _YEAR_ENTRY.search(text)
        or _ROMAN.match(text)
        or re.fullmatch(r"[\d.\s]+", text)
        or sum(c.isalpha() for c in text) < 3
    ):
        return None
    if _squash(text) and _squash(text) in _squash(title):
        # "THE ECCLESIASTICAL HISTORY OF" under a title that says so already.
        return None
    return _unshout(text)


def citation_label(title: str, chunk_meta: dict | None) -> str:
    """The label a passage is cited by: the work, then its place in it."""
    meta = chunk_meta or {}
    work = citation_title(title)
    heading = section_heading(meta.get("section"), work) or section_heading(
        meta.get("heading"), work, max_chars=100, max_words=14
    )
    locus = " ".join(str(meta.get("locus") or "").split()) or None
    place = " · ".join(p for p in (locus, heading) if p)
    return f"{work} — {place}" if place else work


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _unshout(text: str) -> str:
    """Title-case an all-capitals heading, keeping roman numerals upper."""
    letters = [c for c in text if c.isalpha()]
    if not letters or any(c.islower() for c in letters):
        return text
    small = {"a", "an", "the", "and", "or", "of", "in", "on", "to", "by", "for", "with", "at"}
    words = text.split(" ")
    out = []
    for i, word in enumerate(words):
        if _ROMAN.match(word.strip(".,;:")):
            out.append(word)
        elif i and word.lower() in small:
            out.append(word.lower())
        else:
            out.append(word[:1] + word[1:].lower())
    return " ".join(out)
