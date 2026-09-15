"""Keep the parts of a long work that a plan asked for, not the first N characters.

A long primary text is capped before it is ingested — ingestion costs money per
character — and a cap applied as a prefix keeps whatever the work happens to
open with. On a STANDARD build of "Thomism" the Summa Theologiae I-II was cut
at 200,000 characters of a 2.9 MB volume: questions 1–45, on happiness and
human acts, while the plan had asked for the treatise on law (qq. 90–108).
"Natural law" appeared once in what was kept.

Most long works carry numbered headings — QUESTION 94, CHAPTER 13, BOOK II,
LECTURE 7, SECTION 4 — so a hint like "I-II qq. 90–97" or "Book II, chapters
1–10" can be turned into number ranges and matched against them. What matched
is kept in the work's own order, up to the cap. The cap is a ceiling, not a
target: nothing is added to fill it, because paying to ingest material nobody
asked for is exactly the cost this module exists to avoid.

When the hint names nothing that can be matched, or the text has no numbered
headings, the text is truncated as before and the caller is told nothing
matched — which the corpus summary reports as a partial work, not a found one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Heading kinds, singular. A heading is a line that starts with one of these
# followed by a number (arabic or roman), optionally followed by a title.
_HEADING_WORDS = (
    "question", "chapter", "book", "part", "section", "lecture", "article",
    "letter", "epistle", "canto", "act", "discourse", "sermon", "meditation",
    "treatise", "essay", "lesson", "paragraph",
)
_ROMAN = r"[ivxlcdm]+"
_HEADING_RE = re.compile(
    rf"^[ \t]*(?:#{{1,6}}[ \t]*)?(?P<kind>{'|'.join(_HEADING_WORDS)})s?\.?[ \t]+"
    rf"(?P<num>\d{{1,4}}|{_ROMAN})\b[^\n]{{0,120}}$",
    re.IGNORECASE | re.MULTILINE,
)

# "9.  Methods" (or Markdown's "## 9. Methods"): a number, a full stop and a
# capitalised title on a line of their own. Subsection headings ("9.2.1.") count
# toward their top-level number, because converted documents often lose the
# top-level heading and keep the subsections.
_NUMBERED_HEADING_RE = re.compile(
    r"^[ \t]{0,3}(?:#{1,6}[ \t]*)?(?P<num>\d{1,3})(?:\.\d{1,3})*\.?[ \t]{1,4}[A-Z][^\n]{2,100}$",
    re.MULTILINE,
)

# In a hint: a kind word (or its abbreviation) and what follows it, up to the
# next kind word.
_HINT_KIND = re.compile(
    r"\b(?P<kind>qq?|questions?|ch(?:ap(?:ter)?)?s?|chapters?|bk|books?|parts?|"
    r"sect(?:ion)?s?|lect(?:ure)?s?|art(?:icle)?s?|letters?|epistles?|cantos?|"
    r"sermons?|meditations?|lessons?|paras?|paragraphs?)\b\.?",
    re.IGNORECASE,
)
_NUMBER = rf"(?:\d{{1,4}}|\b{_ROMAN}\b)"
_RANGE = re.compile(
    rf"(?P<a>{_NUMBER})(?:\s*(?:-|–|—|to)\s*(?P<b>{_NUMBER}))?", re.IGNORECASE
)

_KIND_ALIASES = {
    "q": "question", "qq": "question", "question": "question", "questions": "question",
    "ch": "chapter", "chs": "chapter", "chap": "chapter", "chaps": "chapter",
    "chapter": "chapter", "chapters": "chapter",
    "bk": "book", "book": "book", "books": "book",
    "part": "part", "parts": "part",
    "sect": "section", "sects": "section", "section": "section", "sections": "section",
    "§": "section", "§§": "section",
    "lect": "lecture", "lects": "lecture", "lecture": "lecture", "lectures": "lecture",
    "art": "article", "arts": "article", "article": "article", "articles": "article",
    "letter": "letter", "letters": "letter", "epistle": "epistle", "epistles": "epistle",
    "canto": "canto", "cantos": "canto", "sermon": "sermon", "sermons": "sermon",
    "meditation": "meditation", "meditations": "meditation",
    "lesson": "lesson", "lessons": "lesson",
    "para": "paragraph", "paras": "paragraph", "paragraph": "paragraph", "paragraphs": "paragraph",
}

# Heading kinds that contain other kinds.
_CONTAINER_KINDS = ("part", "book")

# A section shorter than this is a table-of-contents entry, not the section.
_MIN_SECTION_CHARS = 400
# Kept in front of the selected sections: enough of the opening to carry the
# title page and translator's note that say what the text is.
_FRONT_MATTER_CHARS = 1_500
# Ranges wider than this are a misread hint ("1–5000"), not a selection.
_MAX_RANGE_SPAN = 400


@dataclass(frozen=True)
class Selection:
    text: str
    # True when at least one named section was found and kept.
    matched: bool
    sections_kept: int = 0
    # Why nothing matched, for the log; empty when something did.
    reason: str = ""


def roman_to_int(value: str) -> int | None:
    numerals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total, previous = 0, 0
    for char in reversed(value.lower()):
        number = numerals.get(char)
        if number is None:
            return None
        total += -number if number < previous else number
        previous = max(previous, number)
    return total or None


def _to_int(token: str) -> int | None:
    return int(token) if token.isdigit() else roman_to_int(token)


def parse_hint(hint: str) -> dict[str, list[tuple[int, int]]]:
    """Number ranges per heading kind, from a free-text sections hint.

    "I-II qq. 90–97; q. 2" → {"question": [(90, 97), (2, 2)]}. Only numbers that
    follow a kind word count, so a part designator ("I-II") or a year in the
    hint is not mistaken for a question number.
    """
    ranges: dict[str, list[tuple[int, int]]] = {}
    # "§" is not a word character, so it cannot sit inside the \b-bounded
    # pattern; it is spelled out first.
    hint = re.sub(r"§+", " sections ", hint or "")
    matches = list(_HINT_KIND.finditer(hint))
    for index, match in enumerate(matches):
        kind = _KIND_ALIASES.get(match.group("kind").lower().rstrip("."))
        if kind is None:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(hint)
        span = hint[match.end():end]
        # Numbers belong to this kind word until something that is not a number,
        # a range or a list separator appears.
        span = re.split(r"[^\divxlcdmIVXLCDM\s,;–—\-and to]", span, maxsplit=1)[0]
        for r in _RANGE.finditer(span):
            a = _to_int(r.group("a"))
            b = _to_int(r.group("b")) if r.group("b") else a
            if a is None or b is None:
                continue
            low, high = min(a, b), max(a, b)
            if high - low > _MAX_RANGE_SPAN:
                continue
            ranges.setdefault(kind, []).append((low, high))
    return ranges


@dataclass(frozen=True)
class _Section:
    kind: str
    number: int
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


def find_sections(text: str) -> dict[str, list[_Section]]:
    """Numbered sections by heading kind, each running to the next heading of its kind.

    Specifications, standards and many technical documents number their
    top-level sections without the word ("9.  Methods", "4. Security
    Considerations"). Those count as sections when the text has no "SECTION n"
    headings of its own.
    """
    by_kind: dict[str, list[tuple[int, int]]] = {}
    for match in _HEADING_RE.finditer(text):
        kind = match.group("kind").lower()
        number = _to_int(match.group("num"))
        if number is None:
            continue
        by_kind.setdefault(kind, []).append((match.start(), number))
    # Prose that merely mentions "Section 4 of the licence" at the start of a
    # line looks like a heading too, so the bare numbering wins whenever it is
    # the richer sequence.
    numbered: list[tuple[int, int]] = []
    for m in _NUMBERED_HEADING_RE.finditer(text):
        number = int(m.group("num"))
        # Consecutive headings under one top-level number are one section.
        if not numbered or numbered[-1][1] != number:
            numbered.append((m.start(), number))
    distinct = len({n for _, n in numbered})
    if distinct >= 3 and distinct > len({n for _, n in by_kind.get("section", [])}):
        by_kind["section"] = numbered

    sections: dict[str, list[_Section]] = {}
    for kind, heads in by_kind.items():
        heads.sort()
        sections[kind] = [
            _Section(kind, number, start, heads[i + 1][0] if i + 1 < len(heads) else len(text))
            for i, (start, number) in enumerate(heads)
        ]
    return sections


def select_sections(text: str, hint: str, max_chars: int) -> Selection:
    """The named sections of ``text``, in order, within ``max_chars``."""
    if len(text) <= max_chars and not hint:
        return Selection(text, False, reason="no sections hint")
    ranges = parse_hint(hint)
    if not ranges:
        return Selection(text[:max_chars], False, reason="the hint names no numbered sections")

    found = find_sections(text)

    def _matching(kind: str, within: list[_Section] | None = None) -> list[_Section]:
        wanted = ranges.get(kind, [])
        return [
            section for section in found.get(kind, [])
            if section.length >= _MIN_SECTION_CHARS
            and any(low <= section.number <= high for low, high in wanted)
            and (within is None or any(c.start <= section.start < c.end for c in within))
        ]

    # "Book II, chapters 1–10" means chapters inside Book II. When the hint names
    # a container and something smaller, and the text has the container's
    # headings, the smaller sections are taken from inside it.
    containers = [k for k in _CONTAINER_KINDS if k in ranges and _matching(k)]
    inner = [k for k in ranges if k not in _CONTAINER_KINDS]
    chosen: list[_Section] = []
    if containers and inner:
        spans = [c for k in containers for c in _matching(k)]
        for kind in inner:
            chosen += _matching(kind, within=spans)
        if not chosen:
            chosen = spans
    else:
        for kind in ranges:
            chosen += _matching(kind)
    if not chosen:
        kinds = ", ".join(sorted(found)) or "none"
        return Selection(
            text[:max_chars], False,
            reason=f"no heading matched {sorted(ranges)} (headings found: {kinds})",
        )

    # A number can appear more than once (a table of contents, a second series);
    # keep the longest occurrence of each, then restore reading order.
    best: dict[tuple[str, int], _Section] = {}
    for section in chosen:
        key = (section.kind, section.number)
        if key not in best or section.length > best[key].length:
            best[key] = section
    ordered = sorted(best.values(), key=lambda s: s.start)

    first_heading = min(
        (sec.start for secs in found.values() for sec in secs), default=ordered[0].start
    )
    front = text[: min(_FRONT_MATTER_CHARS, first_heading, ordered[0].start)].strip()
    parts: list[str] = [front] if front else []
    used = len(front)
    kept = 0
    for section in ordered:
        body = text[section.start: section.end].strip()
        room = max_chars - used
        if room <= _MIN_SECTION_CHARS:
            break
        parts.append(body[:room])
        used += min(len(body), room) + 2
        kept += 1
    return Selection("\n\n".join(parts), kept > 0, sections_kept=kept)


def apply_sections(text: str, metadata: dict, default_max_chars: int) -> tuple[str, dict]:
    """Cut a fetched text down to its named sections and its ceiling.

    For fetchers: reads ``must_have_sections`` and ``text_max_chars`` off the
    candidate's metadata and returns the text to keep plus the metadata to
    record — whether the sections were found, and whether anything was cut.
    """
    max_chars = int(metadata.get("text_max_chars") or default_max_chars)
    hint = str(metadata.get("must_have_sections") or "")
    if not hint:
        return text[:max_chars], {"truncated": len(text) > max_chars}
    selection = select_sections(text, hint, max_chars)
    recorded: dict = {
        "sections_matched": selection.matched,
        "sections_kept": selection.sections_kept,
        "truncated": len(selection.text) < len(text),
    }
    if not selection.matched:
        recorded["sections_reason"] = selection.reason
    return selection.text, recorded
