"""One chain that turns a work's identity into the best text available for it.

Every scholarly fetcher used to climb its own private ladder, so what a source
was worth depended on which fetcher happened to find it. A biomedical paper
found through OpenAlex was OCR'd from the publisher's PDF — a paid step — while
Europe PMC held the same article as free, structured JATS full text; an arXiv
paper whose ar5iv render failed fell all the way back to its abstract although
the PDF was one fetch away; a DOI-only citation was resolved to a landing page
and read as HTML.

The chain here is ordered by *quality first, cost second*: structured full text
(ar5iv, JATS) before OCR, OCR before a landing page, a landing page before an
abstract. Each step's method is recorded on the result, so the ledger can say
how a source's text was actually obtained rather than implying they were all
obtained the same way.

The steps themselves are not new — they are the fetchers' existing code paths,
called from one place instead of four.
"""

from __future__ import annotations

from dataclasses import dataclass

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.http import RESEARCH_UA, shared_client
from peritus.sources.domain import Identifiers, SourceCandidate

logger = get_logger(__name__)

HEADERS = {"User-Agent": RESEARCH_UA}

# Below this, "full text" is a stub, a paywall notice, or a cookie banner — not
# something worth preferring over the abstract the fetcher already has.
MIN_FULL_TEXT = 3_000
MAX_FULL_TEXT = 120_000

# How the text was obtained. Persisted on `sources.full_text_method`, so these
# strings are part of the audit surface and should not be renamed lightly.
METHOD_AR5IV = "ar5iv"
METHOD_ARXIV_PDF = "arxiv_pdf_ocr"
METHOD_EUROPE_PMC = "europepmc_jats"
METHOD_OA_PDF = "oa_pdf_ocr"
METHOD_LANDING = "oa_landing_html"
METHOD_ABSTRACT = "abstract"

# Methods that cost money (Mistral OCR bills per page). The fetch stage sorts
# these last so a fixed budget buys text before it buys OCR.
PAID_METHODS: frozenset[str] = frozenset({METHOD_ARXIV_PDF, METHOD_OA_PDF})

# How the non-scholarly fetchers get their text. They do not go through the
# chain above — there is no full-text ladder to climb for a forum thread — but
# the column still has to say how the text was obtained, and NULL reads as
# "unknown" for a source whose retrieval was never in doubt. It also matters to
# the validator: the preview's "Text obtained by" line said `abstract` for a
# 72,000-character Exa article, which is not a small thing to tell a model that
# is judging depth.
_FETCHER_METHODS: dict[str, str] = {
    "wikipedia": "wikipedia_extract",
    "exa": "exa_contents",
    "web": "web_html",
    "youtube": "youtube_transcript",
    "reddit": "reddit_thread",
    "gutenberg": "gutenberg_text",
    "thought_leader": "thought_leader_page",
    "upload": "upload",
}


def default_method_for(source_type: str) -> str | None:
    """How this source type retrieves text when no resolver step recorded one."""
    return _FETCHER_METHODS.get(source_type)


@dataclass(frozen=True)
class FullTextHints:
    """What the calling fetcher already knows, so the chain need not re-discover it."""

    oa_pdf_url: str | None = None
    oa_landing_url: str | None = None
    # Tri-state, and the third state matters. ``False`` is a fetcher saying "I
    # looked this up and it is not open access", which makes a full-text request
    # a guaranteed 404 not worth spending; ``None`` is "nobody has said", which
    # is the normal case for a work reached through a citation, and there the
    # request is worth making. Collapsing the two to a bool either wastes a
    # request on every closed-access record or silently strands every source
    # that arrived without the flag on its abstract.
    open_access: bool | None = None

    @classmethod
    def from_metadata(cls, metadata: dict | None) -> FullTextHints:
        metadata = metadata or {}
        # Europe PMC calls the flag `open_access`; OpenAlex and the PDF fetcher
        # call it `is_open_access`. Both mean the same thing here.
        flag = metadata.get("is_open_access", metadata.get("open_access"))
        return cls(
            oa_pdf_url=metadata.get("oa_pdf_url"),
            oa_landing_url=metadata.get("oa_landing_url"),
            open_access=None if flag is None else bool(flag),
        )

    @classmethod
    def from_candidate(cls, candidate: SourceCandidate) -> FullTextHints:
        return cls.from_metadata(candidate.metadata)

    def merge(self, other: FullTextHints) -> FullTextHints:
        return FullTextHints(
            oa_pdf_url=self.oa_pdf_url or other.oa_pdf_url,
            oa_landing_url=self.oa_landing_url or other.oa_landing_url,
            open_access=self.open_access if self.open_access is not None else other.open_access,
        )


@dataclass(frozen=True)
class FullText:
    text: str
    method: str

    @property
    def chars(self) -> int:
        return len(self.text)


def _long_enough(text: str) -> bool:
    return len(text) >= MIN_FULL_TEXT


async def resolve_full_text(
    ids: Identifiers,
    hints: FullTextHints | None = None,
) -> FullText | None:
    """Best available full text for a work, or ``None`` if there is none.

    Never raises: every step is best-effort, and a step that fails hands the
    work to the next one. The caller falls back to title + abstract on ``None``,
    which is what the fetchers already do.
    """
    hints = hints or FullTextHints()

    if ids.arxiv_id:
        result = await _from_arxiv(ids.arxiv_id)
        if result:
            return result

    result = await _from_europe_pmc(ids, hints)
    if result:
        return result

    result = await _from_hints(hints)
    if result:
        return result

    # A DOI and nothing else: ask OpenAlex what it knows, then retry the steps
    # that identity or hints have just unlocked. Skipped when the work already
    # carries an OpenAlex id — it came *from* OpenAlex, so asking OpenAlex about
    # it again is a round trip that cannot return anything new — and when hints
    # are already present, for the same reason.
    if ids.doi and not ids.openalex_id and not hints.oa_pdf_url and not hints.oa_landing_url:
        enriched_ids, enriched_hints = await resolve_hints_by_doi(ids.doi)
        merged_ids = ids.merge(enriched_ids)
        merged_hints = hints.merge(enriched_hints)
        if merged_ids.pmcid or merged_ids.pmid:
            result = await _from_europe_pmc(merged_ids, merged_hints)
            if result:
                return result
        return await _from_hints(merged_hints)

    return None


async def resolve_hints_by_doi(doi: str) -> tuple[Identifiers, FullTextHints]:
    """What OpenAlex knows about a bare DOI: more identifiers, and OA locations."""
    from peritus.sources.fetchers.openalex import fetch_by_doi

    try:
        candidate = await fetch_by_doi(doi)
    except Exception as exc:
        logger.debug("OpenAlex DOI enrichment failed for %r: %s", doi, exc)
        return Identifiers(), FullTextHints()
    if candidate is None:
        return Identifiers(), FullTextHints()
    return candidate.identifiers, FullTextHints.from_candidate(candidate)


async def _from_arxiv(arxiv_id: str) -> FullText | None:
    """ar5iv's HTML rendering, then the PDF through OCR when a key is set.

    The PDF fallback is the point: ar5iv cannot render every paper (older TeX,
    unusual packages), and before this a render failure silently cost the corpus
    a whole paper's body when the PDF was one request away.
    """
    from peritus.sources.fetchers.arxiv import fetch_ar5iv

    try:
        http = shared_client(timeout=30, headers=HEADERS, guarded=True)
        text = await fetch_ar5iv(http, arxiv_id)
        if _long_enough(text):
            return FullText(text[:MAX_FULL_TEXT], METHOD_AR5IV)
    except Exception as exc:
        logger.debug("ar5iv failed for arXiv:%s: %s", arxiv_id, exc)

    if not settings.MISTRAL_API_KEY:
        return None
    try:
        from peritus.infrastructure.pdf_parser import parse_pdf_url

        text = await parse_pdf_url(f"https://arxiv.org/pdf/{arxiv_id}")
        if _long_enough(text):
            return FullText(text[:MAX_FULL_TEXT], METHOD_ARXIV_PDF)
    except Exception as exc:
        logger.debug("arXiv PDF OCR failed for arXiv:%s: %s", arxiv_id, exc)
    return None


async def _from_europe_pmc(ids: Identifiers, hints: FullTextHints | None = None) -> FullText | None:
    """Europe PMC's JATS body, for anything with (or resolvable to) a PMCID.

    Preferred over OCR whichever fetcher found the source: it is free, fast, and
    already structured into sections, where OCR of the same article costs money
    per page and arrives as a flat page dump.
    """
    from peritus.sources.fetchers.pubmed import fetch_full_text, pmcid_for_pmid

    if hints is not None and hints.open_access is False:
        # A fetcher has already established this is not open access. Only the
        # open-access subset has retrievable full text, so the request is a
        # guaranteed 404 — don't spend it.
        return None
    pmcid = ids.pmcid
    if not pmcid and ids.pmid:
        pmcid = await pmcid_for_pmid(ids.pmid)
    if not pmcid:
        return None
    try:
        http = shared_client(timeout=30, headers=HEADERS, guarded=True)
        text = await fetch_full_text(http, pmcid)
    except Exception as exc:
        logger.debug("Europe PMC full text failed for %s: %s", pmcid, exc)
        return None
    if _long_enough(text):
        return FullText(text[:MAX_FULL_TEXT], METHOD_EUROPE_PMC)
    return None


async def _from_hints(hints: FullTextHints) -> FullText | None:
    """The open-access locations a fetcher handed over: PDF first, then landing page."""
    if hints.oa_pdf_url and settings.MISTRAL_API_KEY:
        try:
            from peritus.infrastructure.pdf_parser import parse_pdf_url

            text = await parse_pdf_url(hints.oa_pdf_url)
            if _long_enough(text):
                return FullText(text[:MAX_FULL_TEXT], METHOD_OA_PDF)
        except Exception as exc:
            logger.debug("OA PDF OCR failed for %r: %s", hints.oa_pdf_url, exc)

    if hints.oa_landing_url:
        from peritus.sources.fetchers.web import fetch_page_text

        try:
            text = await fetch_page_text(hints.oa_landing_url, max_chars=MAX_FULL_TEXT)
            if _long_enough(text):
                return FullText(text[:MAX_FULL_TEXT], METHOD_LANDING)
        except Exception as exc:
            logger.debug("OA landing page failed for %r: %s", hints.oa_landing_url, exc)
    return None


def expected_method(ids: Identifiers, hints: FullTextHints | None = None) -> str:
    """Which step the chain will *probably* take, without taking it.

    Used by the fetch stage to sort free paths ahead of paid ones and by the
    cost estimator, both of which need a guess before any network call. A guess
    that turns out wrong costs nothing — the recorded method always comes from
    what actually ran.
    """
    hints = hints or FullTextHints()
    if ids.arxiv_id:
        return METHOD_AR5IV
    if ids.pmcid or ids.pmid:
        return METHOD_EUROPE_PMC
    if hints.oa_pdf_url and settings.MISTRAL_API_KEY:
        return METHOD_OA_PDF
    if hints.oa_landing_url:
        return METHOD_LANDING
    return METHOD_ABSTRACT


def is_paid_path(ids: Identifiers, hints: FullTextHints | None = None) -> bool:
    """Whether resolving this work is expected to spend money on OCR."""
    return expected_method(ids, hints) in PAID_METHODS
