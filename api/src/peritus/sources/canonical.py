"""Canonical works, looked for on purpose and recorded as found whole or in part.

The research plan names the works an expert on a topic must contain. Until
this module, "found" meant a candidate whose title contained the work's title as
a substring: a New Advent page titled "SUMMA THEOLOGIAE: The natural law (Prima
Secundae Partis, Q. 94)" satisfied "Summa Theologiae", and the Thomism corpus
(job 53) held one question of roughly six hundred and called the Summa found.

Two things change.

**Extent.** Every hit is classified before fetch as ``whole`` or ``partial``. A
title carrying a question, chapter, book, part or volume number, or a URL on a
site that serves a work one section per page, is partial. A partial hit is
still fetched first — one question of the Summa is worth having — but it never
marks the work found, and the resolver keeps looking.

**Scope.** A plan names works at two scopes: canonical for the topic as a whole,
and the primary text that teaches each key concept — usually a named part of
something longer ("I-II qq. 90–97", "Book II", "§§ 3–5"). Both are resolved the
same way; a work named at both scopes is resolved once, with every section
anyone asked for (:func:`merge_works`).

**Routes,** by the kind of work, stopping once the work is found well enough:

- texts and books: Project Gutenberg's catalogue and the Internet Archive when
  public domain, then Exa on primary-text hosts, then Exa anywhere;
- papers: OpenAlex by title, then Exa;
- standards: Exa.

Only the best hit per work jumps the fetch queue; the rest compete in triage.
The fetchers cut the named sections out of long texts (sources/sections.py).

What happened to each work goes into ``build_summary.corpus.must_have`` as
``found_whole | found_sections | found_partial | not_found | not_obtainable``,
with the routes tried. A plan also names works in its figures' own voices
(``figure`` scope) and substitutes for works that cannot be had; per concept,
:func:`concept_named_texts` says whether its named text reached the corpus,
which is what coverage's "has primary" gate reads (docs/plans/syllabus.md).
"""

from __future__ import annotations

import asyncio
import difflib
import itertools
import re
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import quote

import httpx

from peritus.core.logging import get_logger
from peritus.sources.domain import (
    FIGURE_ABOUT_ONLY,
    FIGURE_OWN_VOICE,
    NAMED_FOUND,
    NAMED_MISSING,
    NAMED_PARTIAL,
    RawSource,
    SourceCandidate,
    SourceType,
)
from peritus.sources.hosts import title_names_about_site, url_is_about_host

logger = get_logger(__name__)

EXTENT_WHOLE = "whole"
EXTENT_PARTIAL = "partial"

FOUND_WHOLE = "found_whole"
FOUND_PARTIAL = "found_partial"
NOT_FOUND = "not_found"

DISCOVERED_CANONICAL = "canonical"

ROUTE_GUTENBERG = "gutenberg"
ROUTE_ARCHIVE = "internet_archive"
ROUTE_EXA_PRIMARY = "exa_primary_hosts"
ROUTE_EXA = "exa"
ROUTE_OPENALEX = "openalex"
ROUTE_ARXIV = "arxiv"

WORK_KINDS: tuple[str, ...] = ("text", "book", "paper", "standard")

# Hosts that carry primary texts rather than material about them. The same
# family the triage prior already trusts.
PRIMARY_TEXT_HOSTS: tuple[str, ...] = (
    "gutenberg.org",
    "archive.org",
    "ccel.org",
    "newadvent.org",
    "perseus.tufts.edu",
    "sacred-texts.com",
    "marxists.org",
    "oll.libertyfund.org",
    "wikisource.org",
)

# A section marker in a title: a question, chapter, book, part, volume, article,
# lecture or section *number*. Numbers are required, so "The Book of Job" and
# "Part and Whole in Aristotle" are not sections.
_NUMERAL = (
    r"(?:\d+|[ivxlc]+|one|two|three|four|five|six|seven|eight|nine|ten"
    r"|first|second|third|fourth|fifth)\b"
)
_SECTION_RE = re.compile(
    r"(?:"
    r"\bq{1,2}\.?\s*\d+"
    r"|\bquestions?\s+\d+"
    rf"|\b(?:chapter|chap|ch)\.?\s*{_NUMERAL}"
    rf"|\bbook\s+{_NUMERAL}"
    rf"|\bpart\s+{_NUMERAL}(?:\s*-\s*{_NUMERAL})?"
    rf"|\bvol(?:ume)?\.?\s*{_NUMERAL}"
    r"|\barticle\s+\d+"
    r"|\blecture\s+\d+"
    r"|\bsection\s+\d+"
    r"|\bthe\s+(?:first|second|third|fourth|fifth)\s+book\b"
    r")",
    re.IGNORECASE,
)

# Sites that serve a long work one section per page.
_PER_SECTION_URLS: tuple[re.Pattern[str], ...] = (
    re.compile(r"newadvent\.org/summa/"),
    re.compile(r"ccel\.org/.+/summa/"),
)

_EXA_RESULTS = 5
_ARCHIVE_ROWS = 6
_ARCHIVE_TIMEOUT = 15.0
_ARXIV_TIMEOUT = 15.0
_HEADERS = {"User-Agent": "Peritus/2.0 (research corpus builder)"}
_MIN_TEXT = 2_000
# The same ceiling the Gutenberg fetcher applies. Raising it without a way to
# choose *which* part of a long work to keep would only buy a longer prefix —
# see docs/plans/source-selection.md §7.C.
_MAX_CHARS = 200_000
# Share of whitespace-separated tokens in an OCR sample that must be ordinary
# words. Some archive items carry OCR of a scan that is mostly noise.
_MIN_WORD_SHARE = 0.6
_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'’\-]*[.,;:!?)]*$")
_MAX_PARTIAL_PER_WORK = 2


# Words that make a title *about* a work rather than the work: "The Cambridge
# Companion to the Summa Theologiae", "Elements of moral theology, based on the
# Summa Theologiae". A substring match accepted both as the Summa.
_ABOUT_MARKERS = re.compile(
    r"\b(?:companion|commentar(?:y|ies)|introduction|guide|handbook|based on|"
    r"study|studies|essays?|notes on|lectures? on|reader|review|according to|"
    r"interpretation|reading|approach(?:es)?|thought of|philosophy of|theology of|"
    r"dictionary|encyclopedia|bibliography|summary|outline)\b"
)
_LEADING_ARTICLE = re.compile(r"^(?:the|a|an)\s+")
_NORM_RE = re.compile(r"[^a-z0-9 ]")


def _norm_title(text: str) -> str:
    return _LEADING_ARTICLE.sub("", " ".join(_NORM_RE.sub(" ", text.casefold()).split()))


_PARENTHETICAL = re.compile(r"\s*[\(\[]([^\)\]]+)[\)\]]\s*")


def title_variants(title: str) -> list[str]:
    """A title and the alternate names a plan puts in brackets.

    "De Ente et Essentia (On Being and Essence)" is looked for — and matched —
    as itself, as "De Ente et Essentia" and as "On Being and Essence". Matching
    the bracketed form literally missed the English copy a concept lookup found.
    """
    variants = [title.strip()]
    main = _PARENTHETICAL.sub(" ", title).strip()
    if main and main not in variants:
        variants.append(main)
    for inner in _PARENTHETICAL.findall(title):
        inner = inner.strip()
        if len(inner) > 3 and inner not in variants:
            variants.append(inner)
    return variants


def title_key(title: str) -> str:
    """The work a title names, for comparing titles across plan entries and metadata."""
    return _norm_title(_PARENTHETICAL.sub(" ", title or ""))


def names_the_work(title: str, wanted: str, author: str = "") -> bool:
    """Whether a title is the wanted work itself, under any of the names it was given.

    Never a title whose site suffix names an encyclopedia or summary service
    ("De Ente et Essentia — Philopedia"), nor one where the work's title is only
    the object of a preposition ("the existence-essence distinction in De Ente
    et Essentia"). Round 1 of a live Thomism build fetched pages like these as
    the work, each lifted to the front of the queue by its title.
    """
    if title_names_about_site(title):
        return False
    return any(
        _names_the_work(title, variant, author)
        and not _work_is_object_of_preposition(title, variant)
        for variant in title_variants(wanted)
    )


def _names_the_work(title: str, wanted: str, author: str = "") -> bool:
    """Whether a title is the wanted work itself, not merely a title mentioning it.

    The title must start with the work's title (after a leading article or the
    author's name, as in "St. Thomas Aquinas: The Summa Contra Gentiles"), or
    contain it with nothing that marks the title as a book about it
    ("companion", "commentary", "based on"…), or be a near-exact match.
    """
    t, w = _norm_title(title), _norm_title(wanted)
    if not t or not w:
        return False
    for name_token in [tok for tok in _norm_title(author).split() if len(tok) > 2]:
        t = re.sub(rf"^(?:(?:st|saint)\s+)?(?:\w+\s+)?{re.escape(name_token)}\s+", "", t)
    t = _LEADING_ARTICLE.sub("", t)
    # A prefix match, tolerant of the spelling of the edition ("Summa
    # Theologica" for "Summa Theologiae").
    if t.startswith(w) or difflib.SequenceMatcher(None, w, t[: len(w)]).ratio() >= 0.85:
        return True
    if w in t and not _ABOUT_MARKERS.search(t):
        return True
    return difflib.SequenceMatcher(None, w, t).ratio() >= 0.85


def matching_work(title: str, wanted_titles: list[str], url: str = "") -> str | None:
    """The must-have title this candidate title is, or ``None``.

    A match says the candidate is *of* the work, not about it. Whether it is the
    whole work is :func:`classify_extent`'s question, answered separately.

    A URL on an encyclopedia or summary host is never the work, whatever its title.
    """
    if url_is_about_host(url):
        return None
    return next((w for w in wanted_titles if w.strip() and names_the_work(title, w)), None)


_PREPOSITION_BEFORE = re.compile(r"\b(?:in|of|on|about)\s+$")


def _work_is_object_of_preposition(title: str, wanted: str) -> bool:
    """ "… in De Ente et Essentia", "… of the Summa": a title about the work.

    Only when the work's title is not where the title starts: "The Summa
    Theologica of St. Thomas" is the work, and "Thomas Aquinas: De ente et
    essentia: English" is too.
    """
    t, w = _norm_title(title), _norm_title(wanted)
    if not w or t.startswith(w):
        return False
    index = f" {t} ".find(f" {w} ")
    if index <= 0:
        return False
    before = f" {t} "[: index + 1]
    before = re.sub(r"\b(?:the|a|an)\s+$", "", before)
    return bool(_PREPOSITION_BEFORE.search(before))


def classify_extent(title: str, url: str = "", *, volume: str | None = None) -> str:
    """``partial`` when the hit is one section of a work, else ``whole``."""
    if volume:
        return EXTENT_PARTIAL
    if _SECTION_RE.search(title or ""):
        return EXTENT_PARTIAL
    lowered = (url or "").lower()
    if any(rx.search(lowered) for rx in _PER_SECTION_URLS):
        return EXTENT_PARTIAL
    return EXTENT_WHOLE


SCOPE_OVERALL = "overall"
SCOPE_CONCEPT = "concept"
# A work by one of the plan's named figures: their own voice (docs/plans/syllabus.md, 3.A).
SCOPE_FIGURE = "figure"

FOUND_SECTIONS = "found_sections"
# An in-copyright work with no authorised free text, looked for and not found.
# Distinct from not_found, which says a search failed to find something that
# can be had (docs/plans/syllabus.md, 3.B).
NOT_OBTAINABLE = "not_obtainable"


@dataclass
class MustHaveWork:
    """A text the plan says the corpus needs.

    ``scope`` says why: ``overall`` works are canonical for the topic as a whole;
    ``concept`` works are the primary text that teaches one key concept —
    usually a named part of something longer, which is what ``sections`` holds;
    ``figure`` works are one work in a named figure's own voice.

    ``open_text`` says an authorised free text exists although the work is not
    public domain. A work that is neither cannot legally be had, and may name a
    ``substitute`` that can.
    """

    title: str
    author: str = ""
    kind: str = "book"
    public_domain: bool = False
    sections: str = ""
    scope: str = SCOPE_OVERALL
    concepts: list[str] = field(default_factory=list)
    open_text: bool = False
    substitute: MustHaveWork | None = None
    # The figure whose voice this work is, for SCOPE_FIGURE.
    figure: str = ""
    # The title this work stands in for, when it is a substitute.
    substitute_for: str = ""

    @classmethod
    def from_plan(cls, raw: dict[str, Any], scope: str = SCOPE_OVERALL) -> MustHaveWork:
        concept = str(raw.get("concept") or "").strip()
        work = cls(
            title=str(raw.get("title") or "").strip(),
            author=str(raw.get("author") or "").strip(),
            kind=str(raw["kind"]) if raw.get("kind") in WORK_KINDS else "book",
            public_domain=bool(raw.get("public_domain")),
            sections=str(raw.get("sections") or "").strip(),
            scope=scope,
            concepts=[concept] if concept else [],
            open_text=bool(raw.get("open_text")),
        )
        substitute = raw.get("substitute")
        if isinstance(substitute, dict) and str(substitute.get("title") or "").strip():
            work.substitute = cls.from_plan({**substitute, "substitute": None}, scope)
            work.substitute.concepts = list(work.concepts)
            work.substitute.substitute_for = work.title
        return work

    @property
    def obtainable(self) -> bool:
        """Whether a free text can legally exist. Papers and standards are judged by their routes."""
        return self.kind not in ("text", "book") or self.public_domain or self.open_text

    def copy(self) -> MustHaveWork:
        return replace(self, concepts=list(self.concepts))

    def absorb(self, other: MustHaveWork) -> None:
        """Take another entry for the same work into this one: its concepts, and
        whatever it knows about whether a free text exists."""
        for concept in other.concepts:
            if concept not in self.concepts:
                self.concepts.append(concept)
        self.public_domain = self.public_domain or other.public_domain
        self.open_text = self.open_text or other.open_text
        self.substitute = self.substitute or other.substitute

    @property
    def search_title(self) -> str:
        """The title without a bracketed alternate name, for search APIs."""
        return _PARENTHETICAL.sub(" ", self.title).strip() or self.title

    @property
    def key(self) -> str:
        """Title and author surname — the work, whatever edition or alternate name."""
        surname = (_norm_title(self.author).split() or [""])[-1]
        return f"{title_key(self.title)}|{surname}"


def merge_works(works: list[MustHaveWork]) -> list[MustHaveWork]:
    """The lookups to run: one per concept passage, one per remaining work.

    A long work is usually named twice over — canonical for the topic, with a
    hint covering all of it, and as the primary text for several concepts, each
    asking for its own part. Merging those into one lookup (as this first did)
    made the section hint the whole work, so the cut kept the work's opening
    again, and gave every concept one volume when its passages live in
    different ones.

    So when concept entries exist for a work, they are the lookups: each finds
    its own volume and keeps its own sections, and the overall entry adds its
    scope to them rather than a lookup of its own. Entries naming the same work
    and the same sections are one lookup. A work named only overall stays one
    lookup, with its hint.
    """
    concept_keys = {w.key for w in works if w.title and w.scope == SCOPE_CONCEPT}
    overall_keys = {w.key for w in works if w.title and w.scope == SCOPE_OVERALL}

    merged: dict[tuple[str, str], MustHaveWork] = {}
    for work in works:
        if not work.title:
            continue
        if work.scope == SCOPE_OVERALL and work.key in concept_keys:
            continue
        if work.scope == SCOPE_FIGURE and work.key in concept_keys | overall_keys:
            # Already looked for as a canonical or concept text.
            continue
        slot = (work.key, _norm_title(work.sections) if work.scope == SCOPE_CONCEPT else "")
        existing = merged.get(slot)
        if existing is None:
            merged[slot] = work.copy()
            continue
        existing.absorb(work)
        if not existing.sections and work.sections:
            existing.sections = work.sections

    for lookup in merged.values():
        if lookup.scope == SCOPE_CONCEPT and lookup.key in overall_keys:
            # Canonical for the topic too: queued with the canonical works.
            lookup.scope = SCOPE_OVERALL
    return list(merged.values())


@dataclass
class WorkResolution:
    """What the resolver found for one must-have work, before anything is fetched."""

    work: MustHaveWork
    candidates: list[SourceCandidate] = field(default_factory=list)
    routes_tried: list[str] = field(default_factory=list)
    route_errors: dict[str, str] = field(default_factory=dict)

    @property
    def whole(self) -> bool:
        """A whole copy with a route to its text. A catalogue record with only an
        abstract names the work; it does not hold it, and must not stop the search."""
        return any(
            c.metadata.get("must_have_extent") == EXTENT_WHOLE
            and not c.metadata.get("abstract_only_hit")
            for c in self.candidates
        )

    @property
    def sufficient(self) -> bool:
        """Found well enough to stop looking.

        A whole work always is. With a sections hint, a text that the hint's
        sections can be cut from is too: a Gutenberg volume containing the named
        questions is what the plan asked for, and looking further only finds more
        copies of the same volume.
        """
        if self.whole:
            return True
        return bool(self.work.sections) and any(
            c.metadata.get("sections_expected") for c in self.candidates
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.work.title,
            "author": self.work.author,
            "kind": self.work.kind,
            "scope": self.work.scope,
            "concepts": list(self.work.concepts),
            "sections": self.work.sections,
            "public_domain": self.work.public_domain,
            "open_text": self.work.open_text,
            "figure": self.work.figure,
            "substitute_for": self.work.substitute_for,
            "routes_tried": list(self.routes_tried),
            "route_errors": dict(self.route_errors),
            "candidates": [
                {
                    "url": c.url,
                    "title": c.title,
                    "extent": c.metadata.get("must_have_extent"),
                    "route": c.metadata.get("canonical_route"),
                    "priority": bool(c.metadata.get("fetch_priority")),
                }
                for c in self.candidates
            ],
        }


# Concurrent route calls across every work being resolved. Exa and the
# Internet Archive both rate-limit, and a plan with a primary text per concept
# can name a dozen works.
_RESOLVE_CONCURRENCY = 4


async def resolve_works(
    works: list[MustHaveWork],
    *,
    exa_search=None,
    max_chars: dict[str, int] | None = None,
) -> list[WorkResolution]:
    """Resolve every work, concurrently and bounded. Never raises.

    ``exa_search(query, max_results, include_domains=None)`` is injected so the
    resolver has no hard dependency on an Exa key; ``None`` skips the Exa routes.
    ``max_chars`` is the text ceiling per scope, stamped on each candidate for
    the fetcher that cuts sections from it.
    """
    semaphore = asyncio.Semaphore(_RESOLVE_CONCURRENCY)

    async def _bounded(work: MustHaveWork) -> WorkResolution:
        async with semaphore:
            return await _resolve_one(work, exa_search, (max_chars or {}).get(work.scope))

    return list(await asyncio.gather(*[_bounded(w) for w in merge_works(works)]))


def _routes_for(work: MustHaveWork, exa_search) -> list[tuple[str, Any]]:
    """Where to look, by what kind of work it is.

    Texts and books: the public-domain libraries first when the work is public
    domain, then Exa on the hosts that carry primary texts, then Exa anywhere.
    Papers: OpenAlex by title, then Exa. Standards and specifications: Exa, which
    finds the issuing body's own page.
    """
    routes: list[tuple[str, Any]] = []
    if work.kind in ("text", "book") and not work.obtainable:
        # In copyright with no authorised free text: the public-domain libraries'
        # licence checks would refuse any hit, and the primary-text hosts carry
        # none. One open search, and "not obtainable" if it finds nothing.
        return [(ROUTE_EXA, _exa_open_route)] if exa_search is not None else []
    if work.kind in ("text", "book"):
        if work.public_domain:
            routes.append((ROUTE_GUTENBERG, _gutenberg_route))
            routes.append((ROUTE_ARCHIVE, _archive_route))
        if exa_search is not None:
            routes.append((ROUTE_EXA_PRIMARY, _exa_primary_route))
    elif work.kind == "paper":
        # arXiv first: an exact-title hit there is the preprint with free full
        # text, where OpenAlex's index can put a re-registered copy of a famous
        # paper, with a broken PDF, at the top of its results.
        routes.append((ROUTE_ARXIV, _arxiv_route))
        routes.append((ROUTE_OPENALEX, _openalex_route))
    if exa_search is not None:
        routes.append((ROUTE_EXA, _exa_open_route))
    return routes


async def _resolve_one(
    work: MustHaveWork, exa_search, max_chars: int | None = None
) -> WorkResolution:
    resolution = WorkResolution(work=work)
    seen_urls: set[str] = set()
    for name, route in _routes_for(work, exa_search):
        resolution.routes_tried.append(name)
        try:
            found = await route(work, exa_search)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            resolution.route_errors[name] = f"{type(exc).__name__}: {exc}"[:200]
            logger.warning("Canonical %r via %s failed: %s", work.title, name, exc)
            continue
        partial_count = sum(
            1 for c in resolution.candidates if c.metadata.get("must_have_extent") == EXTENT_PARTIAL
        )
        for candidate in found:
            candidate = as_archive_candidate(candidate) or candidate
            key = candidate.url.rstrip("/").lower()
            if key in seen_urls:
                continue
            extent = candidate.metadata.get("must_have_extent")
            if extent == EXTENT_PARTIAL:
                if partial_count >= _MAX_PARTIAL_PER_WORK:
                    continue
                partial_count += 1
            seen_urls.add(key)
            candidate.metadata.update(
                {
                    "must_have_title": work.title,
                    "must_have_scope": work.scope,
                    "canonical_route": name,
                    "discovered_via": DISCOVERED_CANONICAL,
                }
            )
            if work.concepts:
                candidate.metadata["must_have_concepts"] = list(work.concepts)
            if work.figure:
                candidate.metadata["must_have_figure"] = work.figure
            if work.sections:
                candidate.metadata["must_have_sections"] = work.sections
            if max_chars:
                candidate.metadata["text_max_chars"] = max_chars
            resolution.candidates.append(candidate)
        if resolution.sufficient:
            break

    _mark_priority(resolution)
    logger.info(
        "Canonical %r (%s): %s via %s (%d candidate(s))",
        work.title,
        work.scope,
        "whole" if resolution.whole else ("partial" if resolution.candidates else "nothing"),
        " → ".join(resolution.routes_tried),
        len(resolution.candidates),
    )
    return resolution


def _mark_priority(resolution: WorkResolution) -> None:
    """Only the best hit for a work jumps the fetch queue.

    Priority means "fetched before anything else, at any score" — so giving it to
    every hit for every work lets a plan with a primary text per concept spend a
    round's money on alternate copies. The rest stay candidates carrying the
    work's name and compete in triage like anything else.
    """
    if not resolution.candidates:
        return
    ordered = sorted(
        resolution.candidates,
        key=lambda c: (
            0 if c.metadata.get("must_have_extent") == EXTENT_WHOLE else 1,
            1 if c.metadata.get("abstract_only_hit") else 0,
            0 if c.metadata.get("sections_expected") else 1,
        ),
    )
    best = ordered[0]
    best.metadata["fetch_priority"] = True
    # The topic's canonical works, then concept texts, then figures' works.
    best.metadata["priority_rank"] = {SCOPE_OVERALL: 0, SCOPE_CONCEPT: 1}.get(
        resolution.work.scope, 2
    )


# ── route: the Gutenberg catalogue ───────────────────────────────────────────


async def _gutenberg_route(work: MustHaveWork, _exa) -> list[SourceCandidate]:
    from peritus.infrastructure.gutenberg_catalogue import load_catalogue

    catalogue = await load_catalogue()
    if catalogue is None:
        raise RuntimeError("Gutenberg catalogue unavailable")
    books = await asyncio.to_thread(catalogue.resolve, work.search_title, work.author, 8)
    if not books:
        return []

    candidates = []
    for book in books:
        # The catalogue's own match is loose by design (it finds "Theologica"
        # for "Theologiae"); this is the check that the book is the work and
        # not, say, an earlier draft or a commentary with the work in its title.
        if not names_the_work(book.title.splitlines()[0], work.title, work.author):
            continue
        extent = classify_extent(book.title.splitlines()[0], book.url)
        candidates.append(
            SourceCandidate(
                source_type=SourceType.GUTENBERG,
                url=book.url,
                title=book.display_title,
                author=book.authors or work.author or None,
                snippet=f"{book.display_title} by {book.authors or 'unknown'}. "
                f"Subjects: {book.subjects[:300]}",
                metadata={"gutenberg_id": book.id, "must_have_extent": extent},
            )
        )
    ordered = order_by_sections(candidates, work.sections)
    if work.sections and ordered and ordered[0].metadata.get("section_affinity", 0) > 0:
        # The volume the hint points at can have the named sections cut from it
        # at fetch time, which is enough to stop looking for a whole copy.
        ordered[0].metadata["sections_expected"] = True
    return ordered[:3]


_DESIGNATOR = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def order_by_sections(candidates: list[SourceCandidate], sections: str) -> list[SourceCandidate]:
    """Whole records first; among volumes, the one the sections hint points at.

    Matched on tokens *and* adjacent pairs, so "Prima Pars" prefers "Part I
    (Prima Pars)" over "Pars Prima Secundae", and "I-II" is one token rather than
    two roman numerals that every volume title contains.
    """

    def tokens(text: str) -> list[str]:
        return _DESIGNATOR.findall(text.casefold())

    stop = {"and", "qq", "q", "the", "of", "on", "in", "part", "vol", "volume", "book"}
    hint_tokens = [t for t in tokens(sections) if t not in stop and not t.isdigit()]
    hint_pairs = set(itertools.pairwise(hint_tokens))

    def affinity(title: str) -> int:
        words = [t for t in tokens(title) if t not in stop]
        pairs = set(itertools.pairwise(words))
        return 2 * len(hint_pairs & pairs) + len(set(hint_tokens) & set(words))

    for c in candidates:
        c.metadata["section_affinity"] = affinity(c.title) if hint_tokens else 0

    return sorted(
        candidates,
        key=lambda c: (
            0 if c.metadata.get("must_have_extent") == EXTENT_WHOLE else 1,
            -c.metadata["section_affinity"],
        ),
    )


# ── route: the Internet Archive ──────────────────────────────────────────────

_ARCHIVE_SEARCH = "https://archive.org/advancedsearch.php"
_ARCHIVE_ID_RE = re.compile(r"archive\.org/(?:details|stream|download)/([^/?#]+)", re.IGNORECASE)


def archive_identifier(url: str) -> str | None:
    """The Internet Archive item a URL points into, if it points into one."""
    match = _ARCHIVE_ID_RE.search(url or "")
    return match.group(1) if match else None


def as_archive_candidate(candidate: SourceCandidate) -> SourceCandidate | None:
    """Route an archive.org page to the item's text, whatever found it.

    A search hit on ``archive.org/details/<id>`` is the item's catalogue page:
    a title, a description, and a "Free Download, Borrow" banner. Fetched as a
    web page it passes nothing; four of the seven junk fetches on a live
    rebuild were exactly that. The text is in the item's OCR file.
    """
    identifier = archive_identifier(candidate.url)
    if identifier is None:
        return None
    candidate.metadata["archive_id"] = identifier
    candidate.metadata["canonical_fetcher"] = "archive"
    return candidate


async def _archive_route(work: MustHaveWork, _exa) -> list[SourceCandidate]:
    query = (
        f"title:({_archive_escape(work.search_title)}) AND mediatype:texts "
        "AND NOT access-restricted-item:true"
    )
    if work.author:
        surname = work.author.split()[-1]
        query += f" AND creator:({_archive_escape(surname)})"
    params: list[tuple[str, str | int | float | bool | None]] = [
        ("q", query),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "creator"),
        ("fl[]", "volume"),
        ("fl[]", "language"),
        ("sort[]", "downloads desc"),
        ("rows", _ARCHIVE_ROWS),
        ("output", "json"),
    ]
    async with httpx.AsyncClient(timeout=_ARCHIVE_TIMEOUT, headers=_HEADERS) as http:
        resp = await http.get(_ARCHIVE_SEARCH, params=params)
        resp.raise_for_status()
        docs = (resp.json().get("response") or {}).get("docs") or []

    candidates = []
    for doc in docs:
        identifier = doc.get("identifier")
        title = _first(doc.get("title"))
        if not identifier or not title or not names_the_work(title, work.title, work.author):
            continue
        language = " ".join(_as_list(doc.get("language"))).casefold()
        if language and not any(tag in language for tag in ("eng", "english")):
            continue
        url = f"https://archive.org/details/{identifier}"
        candidates.append(
            SourceCandidate(
                source_type=SourceType.WEB,
                url=url,
                title=title,
                author=_first(doc.get("creator")) or work.author or None,
                snippet=f"{title}. Full text from the Internet Archive.",
                metadata={
                    "archive_id": identifier,
                    "canonical_fetcher": "archive",
                    "must_have_extent": classify_extent(
                        title, url, volume=_first(doc.get("volume"))
                    ),
                },
            )
        )
    return candidates


def _archive_escape(text: str) -> str:
    return re.sub(r'[\\"():\[\]{}^~*?!+\-]', " ", text).strip()


def _first(value: Any) -> str:
    items = _as_list(value)
    return str(items[0]).strip() if items else ""


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def public_domain_cutoff_year(today: int | None = None) -> int:
    """Works published before this year are in the US public domain.

    95 years after publication, entering each 1 January: in 2026, works from
    1930 and earlier.
    """
    import datetime

    year = today or datetime.date.today().year
    return year - 95


_YEAR_RE = re.compile(r"\b(1[4-9]\d\d|20\d\d)\b")


def archive_item_is_reusable(
    metadata: dict[str, Any], today: int | None = None
) -> tuple[bool, str]:
    """Whether an archive.org item's text may go into a corpus, and why.

    The Internet Archive holds scans of in-copyright books uploaded by users and
    digitising partners alike; a live rebuild pulled the full text of a 2014
    monograph that way. An item is used only when its metadata says it may be:
    an open licence (public domain mark, CC0, Creative Commons), or a publication
    year before the US public-domain cutoff. No licence and no year means no.
    """
    licence = str(metadata.get("licenseurl") or "").casefold()
    if "publicdomain" in licence or "creativecommons.org" in licence:
        return True, f"licence {licence}"
    status = " ".join(_as_list(metadata.get("possible-copyright-status"))).casefold()
    if "public domain" in status and "not" not in status:
        return True, f"copyright status: {status}"
    years = [
        int(y)
        for field_name in ("year", "date", "publicdate_original", "date_published")
        for value in _as_list(metadata.get(field_name))
        for y in _YEAR_RE.findall(str(value))
    ]
    earliest = min(years, default=None)
    if earliest is not None:
        cutoff = public_domain_cutoff_year(today)
        if earliest < cutoff:
            return True, f"published {earliest}, before {cutoff}"
        return False, f"published {earliest}, not before {cutoff}"
    return False, "no licence and no publication year"


class ArchiveTextFetcher:
    """Full text of an Internet Archive item, from its OCR text file.

    Checks the item may be reused before downloading anything, cuts the named
    sections when the plan asked for some, and rejects OCR that is mostly noise.
    """

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        from peritus.sources.sections import apply_sections

        identifier = candidate.metadata.get("archive_id") or archive_identifier(candidate.url)
        if not identifier:
            return None
        async with httpx.AsyncClient(timeout=60, headers=_HEADERS, follow_redirects=True) as http:
            meta_resp = await http.get(f"https://archive.org/metadata/{identifier}")
            meta_resp.raise_for_status()
            item = meta_resp.json()
            reusable, why = archive_item_is_reusable(item.get("metadata") or {})
            if not reusable:
                logger.warning(
                    "Internet Archive item %s not used: %s (%r)",
                    identifier,
                    why,
                    candidate.title,
                )
                return None
            names = [
                str(f.get("name", ""))
                for f in (item.get("files") or [])
                if str(f.get("name", "")).endswith("_djvu.txt")
            ]
            if not names:
                return None
            preferred = f"{identifier}_djvu.txt"
            name = preferred if preferred in names else names[0]
            resp = await http.get(f"https://archive.org/download/{identifier}/{quote(name)}")
            resp.raise_for_status()
            text = resp.text.strip()
        if len(text) < _MIN_TEXT:
            return None
        if not looks_like_prose(text):
            logger.warning(
                "Internet Archive text for %s is mostly OCR noise — not using it", identifier
            )
            return None
        text, selected = apply_sections(text, candidate.metadata, _MAX_CHARS)
        return RawSource(
            source_type=candidate.source_type,
            url=candidate.url,
            title=candidate.title,
            author=candidate.author,
            text=text,
            metadata={
                **candidate.metadata,
                **selected,
                "archive_id": identifier,
                "full_text": True,
                "full_text_method": "archive_djvu_text",
            },
            identifiers=candidate.identifiers,
        )


def looks_like_prose(text: str) -> bool:
    """Whether OCR text reads as words, judged on a sample from its middle."""
    middle = len(text) // 2
    tokens = text[max(0, middle - 10_000) : middle + 10_000].split()
    if len(tokens) < 50:
        tokens = text.split()
    if not tokens:
        return False
    words = sum(1 for token in tokens if _WORD_RE.match(token))
    return words / len(tokens) >= _MIN_WORD_SHARE


def _foreign_wikisource(url: str) -> bool:
    """A Wikisource page in a language other than English."""
    lowered = url.lower()
    if "wikisource.org" not in lowered:
        return False
    if re.search(r"/wiki/[a-z]{2,3}:", lowered):
        return True
    host = lowered.split("//", 1)[-1].split("/", 1)[0]
    return host not in ("en.wikisource.org", "wikisource.org", "www.wikisource.org")


# ── route: OpenAlex, for papers ──────────────────────────────────────────────


async def _openalex_route(work: MustHaveWork, _exa) -> list[SourceCandidate]:
    """A named paper, by title. A paper is whole or it is not the paper."""
    from peritus.sources.fetchers.openalex import has_route_to_text, search_by_title

    found = await search_by_title(work.search_title, work.author)
    kept = []
    for candidate in found:
        if not names_the_work(candidate.title, work.title, work.author):
            continue
        candidate.metadata["must_have_extent"] = EXTENT_WHOLE
        if not has_route_to_text(candidate):
            candidate.metadata["abstract_only_hit"] = True
        kept.append(candidate)
    kept.sort(key=lambda c: 1 if c.metadata.get("abstract_only_hit") else 0)
    return kept[:2]


async def _arxiv_route(work: MustHaveWork, _exa) -> list[SourceCandidate]:
    """A named preprint on arXiv, by exact title. Free full text when it is there.

    Called without the client's retries and under a short deadline: the arXiv
    API rate-limits hard, the library's own retry loop sleeps for over a minute
    before giving up, and a failure here must be recorded as a failed route
    rather than as "not on arXiv".
    """
    import arxiv  # type: ignore

    from peritus.sources.fetchers.arxiv import _to_candidate

    title = re.sub(r'["\\]', " ", work.search_title).strip()
    client = arxiv.Client(page_size=5, delay_seconds=0, num_retries=0)
    search = arxiv.Search(query=f'ti:"{title}"', max_results=3)
    papers = await asyncio.wait_for(
        asyncio.to_thread(lambda: list(client.results(search))), timeout=_ARXIV_TIMEOUT
    )
    kept = []
    for paper in papers:
        candidate = _to_candidate(paper)
        if names_the_work(candidate.title, work.title, work.author):
            candidate.metadata["must_have_extent"] = EXTENT_WHOLE
            kept.append(candidate)
    return kept[:1]


# ── routes: Exa ──────────────────────────────────────────────────────────────


async def _exa_primary_route(work: MustHaveWork, exa_search) -> list[SourceCandidate]:
    return await _exa_route(work, exa_search, list(PRIMARY_TEXT_HOSTS))


async def _exa_open_route(work: MustHaveWork, exa_search) -> list[SourceCandidate]:
    return await _exa_route(work, exa_search, None)


async def _exa_route(
    work: MustHaveWork, exa_search, include_domains: list[str] | None
) -> list[SourceCandidate]:
    # The sections go into the query: a site that serves a long work one part
    # per page (a question, a chapter) is found by the part's number.
    query = " ".join(p for p in (f'"{work.search_title}"', work.author, work.sections) if p)
    results = await exa_search(query, _EXA_RESULTS, include_domains=include_domains)
    kept = []
    for candidate in results:
        if not names_the_work(candidate.title, work.title, work.author):
            continue
        if _foreign_wikisource(candidate.url) or url_is_about_host(candidate.url):
            continue
        candidate.metadata["must_have_extent"] = classify_extent(candidate.title, candidate.url)
        kept.append(candidate)
    return kept


# ── outcome, once the corpus exists ─────────────────────────────────────────


def _primary_hits(
    passed_metadata: list[tuple[str, dict]], wanted_key: str
) -> list[tuple[str, dict]]:
    """Accepted sources carrying the work's title that the validator classified primary."""
    return [
        (url, meta)
        for url, meta in passed_metadata
        if title_key(str(meta.get("must_have_title") or "")) == wanted_key
        and meta.get("source_tier", "primary") == "primary"
    ]


def must_have_outcomes(
    works: list[MustHaveWork],
    resolutions: list[WorkResolution],
    passed_metadata: list[tuple[str, dict]],
) -> list[dict[str, Any]]:
    """Per work: found whole, found in its named sections, found in part, not found.

    Judged on what *passed validation*, not on what the resolver proposed: a
    whole Gutenberg volume that failed to download is not a found work.
    ``passed_metadata`` is ``(url, metadata)`` per accepted source, which is where
    triage, the resolver and the fetchers record ``must_have_title``, its extent
    and whether the named sections were cut from it.
    """
    by_key: dict[str, list[WorkResolution]] = {}
    for resolution in resolutions:
        by_key.setdefault(title_key(resolution.work.title), []).append(resolution)

    distinct: dict[str, MustHaveWork] = {}
    for work in works:
        if not work.title:
            continue
        existing = distinct.get(work.key)
        if existing is None:
            distinct[work.key] = work.copy()
            continue
        existing.absorb(work)
        if work.scope == SCOPE_OVERALL:
            existing.scope = SCOPE_OVERALL
        if work.sections and work.sections not in existing.sections:
            existing.sections = "; ".join(p for p in (existing.sections, work.sections) if p)

    out = []
    for work in distinct.values():
        wanted = title_key(work.title)
        # Only a source the validator classified as primary is the work. A
        # Wikipedia article titled "Summa Theologica" and a lecture with the
        # same name both carried the must-have mark on a live build and were
        # reported as the Summa found whole.
        hits = _primary_hits(passed_metadata, wanted)
        whole = [
            url
            for url, meta in hits
            if meta.get("must_have_extent") == EXTENT_WHOLE and not meta.get("sections_matched")
        ]
        sections = [url for url, meta in hits if meta.get("sections_matched")]
        if whole:
            status, urls = FOUND_WHOLE, whole
        elif sections:
            status, urls = FOUND_SECTIONS, sections
        elif hits:
            status, urls = FOUND_PARTIAL, [url for url, _ in hits]
        elif not work.obtainable:
            status, urls = NOT_OBTAINABLE, []
        else:
            status, urls = NOT_FOUND, []
        found = by_key.get(wanted, [])
        entry: dict[str, Any] = {
            "title": work.title,
            "author": work.author,
            "kind": work.kind,
            "scope": work.scope,
            "concepts": list(work.concepts),
            "sections": work.sections,
            "status": status,
            "source_urls": urls,
            "routes_tried": sorted({r for res in found for r in res.routes_tried}),
            "route_errors": {k: v for res in found for k, v in res.route_errors.items()},
        }
        if work.substitute is not None:
            entry["substitute"] = work.substitute.title
        if work.substitute_for:
            entry["substitute_for"] = work.substitute_for
        if work.figure:
            entry["figure"] = work.figure
        out.append(entry)
    return out


def concept_named_texts(
    works: list[MustHaveWork],
    passed_metadata: list[tuple[str, dict]],
) -> dict[str, dict[str, Any]]:
    """Per concept with a named primary text: its status, and what was named.

    ``{concept: {"status": found | partial | missing, "texts": ["Summa
    Theologiae I-II qq. 90–97", …]}}``. A concept with no named text is absent,
    which coverage reads as ``none_named``.

    Judged per lookup, not per work: the Summa's first part found whole does not
    find the treatise on law in its second. A passed primary source is the named
    text for a concept when it carries the lookup's title and was looked up *for
    that concept* (or the lookup named no sections, so any whole copy is it).
    Found means cut to the named sections, or whole and not truncated; a whole
    copy truncated before the named sections, or a fragment, is partial.
    A substitute found for a text that cannot be had counts as found.
    """
    statuses: dict[str, dict[str, Any]] = {}
    rank = {NAMED_FOUND: 0, NAMED_PARTIAL: 1, NAMED_MISSING: 2}
    for lookup in merge_works([w for w in works if w.concepts]):
        wanted = title_key(lookup.title)
        hits = [
            meta
            for _url, meta in _primary_hits(passed_metadata, wanted)
            if not lookup.sections
            or set(meta.get("must_have_concepts") or []) & set(lookup.concepts)
        ]
        if any(
            meta.get("sections_matched")
            or (
                meta.get("must_have_extent") == EXTENT_WHOLE
                and not (lookup.sections and meta.get("truncated"))
            )
            for meta in hits
        ):
            status = NAMED_FOUND
        elif hits:
            status = NAMED_PARTIAL
        else:
            status = NAMED_MISSING
        label = " ".join(p for p in (lookup.title, lookup.sections) if p)
        for concept in lookup.concepts:
            current = statuses.setdefault(concept, {"status": status, "texts": []})
            if rank[status] < rank[current["status"]]:
                current["status"] = status
            current["texts"].append(label)
    return statuses


def figure_outcomes(
    figures: list[dict[str, Any]],
    works: list[MustHaveWork],
    passed: list[tuple[str, dict]],
) -> list[dict[str, Any]]:
    """Per named figure: ``own_voice | about_only | not_found | not_obtainable``.

    ``passed`` is ``(url, metadata)`` per accepted source, with ``source_tier``
    in the metadata. Own voice needs a passed non-tertiary source from the
    figure's own lookup, or from the thought-leader channel searching for that
    person — the validator classifies an about-page on that channel tertiary, so
    a non-tertiary one is, by that rule, the person's own writing.
    """
    by_figure = {w.figure.casefold(): w for w in works if w.figure}
    out = []
    for figure in figures:
        name = str(figure.get("name") or "").strip()
        if not name:
            continue
        key = name.casefold()
        work = by_figure.get(key)
        work_key = title_key(work.title) if work else None
        mine = [
            (url, meta)
            for url, meta in passed
            if str(meta.get("leader") or meta.get("must_have_figure") or "").casefold() == key
            or (work_key and title_key(str(meta.get("must_have_title") or "")) == work_key)
        ]
        own = [url for url, meta in mine if meta.get("source_tier") in ("primary", "secondary")]
        if own:
            status, urls = FIGURE_OWN_VOICE, own
        elif mine:
            status, urls = FIGURE_ABOUT_ONLY, [url for url, _ in mine]
        elif not figure.get("obtainable"):
            status, urls = NOT_OBTAINABLE, []
        else:
            status, urls = NOT_FOUND, []
        out.append({"name": name, "status": status, "source_urls": urls})
    return out
