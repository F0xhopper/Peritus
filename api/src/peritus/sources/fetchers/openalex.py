"""OpenAlex fetcher — scholarly literature across every discipline.

ArXiv covers STEM preprints and Europe PMC covers biomedicine, which leaves the
majority of academia — humanities, social science, law, economics, psychology,
education, engineering, business — with no dedicated scholarly channel at all.
OpenAlex indexes ~250M works across all of it, is free, needs no API key, and
returns title, authors, abstract, venue, citation counts and open-access
locations from a single JSON call, which fits the cheap-`search()` half of the
Fetcher contract exactly.

fetch() delegates to the shared full-text resolver (sources/fulltext.py), which
climbs from structured full text down to an open-access PDF, a landing page and
finally the abstract — so a biomedical work found here gets Europe PMC's free
JATS rather than an OCR bill, and a paywalled-but-relevant paper still
contributes its densest paragraph instead of being lost.
"""

import re

import httpx

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.sources.domain import (
    Identifiers,
    RawSource,
    SourceCandidate,
    SourceType,
    resolved_identifiers,
)

logger = get_logger(__name__)

_WORKS_URL = "https://api.openalex.org/works"

HEADERS = {"User-Agent": "Peritus/2.0 (research corpus builder)"}
MIN_FULL_TEXT = 3_000
MAX_FULL_TEXT = 120_000
# Below this an abstract is a stub, not something worth an embedding slot.
MIN_ABSTRACT = 200
# Retracted works and paratext (covers, tables of contents, editorial boards)
# are never corpus material; works without an abstract can't be triaged.
_FILTER = "has_abstract:true,is_retracted:false,is_paratext:false"

_WS_RE = re.compile(r"\s+")

# Aliased rather than referenced inline so the tests can assert against one name.
SOURCE_TYPE: SourceType = SourceType.OPENALEX


class OpenAlexFetcher:
    async def search(self, query: str, max_results: int = 4) -> list[SourceCandidate]:
        params: dict[str, str | int] = {
            "search": query,
            "filter": _FILTER,
            "per-page": max(1, min(max_results, 50)),
        }
        # OpenAlex's polite pool (faster, more reliable) just wants an email.
        if settings.OPENALEX_MAILTO:
            params["mailto"] = settings.OPENALEX_MAILTO
        try:
            async with httpx.AsyncClient(timeout=30, headers=HEADERS) as http:
                resp = await http.get(_WORKS_URL, params=params)
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:
            logger.warning("OpenAlex search failed for %r: %s", query, exc)
            return []

        results = payload.get("results", []) or []
        candidates = [_to_candidate(w) for w in results[:max_results]]
        return [c for c in candidates if c is not None]

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        from peritus.sources.fulltext import FullTextHints, resolve_full_text

        resolved = await resolve_full_text(
            resolved_identifiers(candidate), FullTextHints.from_candidate(candidate)
        )
        full_text = resolved.text if resolved else ""
        abstract = candidate.metadata.get("abstract") or candidate.snippet

        has_full = len(full_text) >= MIN_FULL_TEXT
        if has_full:
            # Full texts routinely omit their own abstract; prepend it — it is
            # usually the densest statement of the work's claim.
            text = f"{candidate.title}\n\n{abstract}\n\n{full_text}"[:MAX_FULL_TEXT]
        elif len(abstract) >= MIN_ABSTRACT:
            text = f"{candidate.title}\n\n{abstract}"
        else:
            return None

        metadata = {k: v for k, v in candidate.metadata.items() if k != "abstract"}
        metadata["full_text"] = has_full
        metadata["abstract"] = abstract
        metadata["full_text_method"] = (
            resolved.method if resolved is not None and has_full else "abstract"
        )
        return RawSource(
            source_type=SOURCE_TYPE,
            url=candidate.url,
            title=candidate.title,
            author=candidate.author,
            text=text,
            metadata=metadata,
            identifiers=candidate.identifiers,
        )


async def fetch_by_doi(doi: str) -> SourceCandidate | None:
    """Resolve one DOI to a triage-shaped candidate. Used by citation snowballing.

    Returns None when OpenAlex doesn't know the DOI or the record is too thin
    to be worth an embedding slot.
    """
    params: dict[str, str] = {}
    if settings.OPENALEX_MAILTO:
        params["mailto"] = settings.OPENALEX_MAILTO
    try:
        async with httpx.AsyncClient(timeout=30, headers=HEADERS) as http:
            resp = await http.get(f"{_WORKS_URL}/https://doi.org/{doi}", params=params)
            if resp.status_code != 200:
                return None
            return _to_candidate(resp.json())
    except Exception as exc:
        logger.debug("OpenAlex DOI lookup failed for %r: %s", doi, exc)
        return None


def _to_candidate(work: dict) -> SourceCandidate | None:
    """Map one OpenAlex work onto a candidate.

    Returns None for records too thin to triage — no title, or an abstract
    shorter than a stub.
    """
    title = (work.get("display_name") or work.get("title") or "").strip()
    abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
    if not title or len(abstract) < MIN_ABSTRACT:
        return None

    primary = work.get("primary_location") or {}
    best_oa = work.get("best_oa_location") or {}
    doi_url = work.get("doi")  # OpenAlex returns the full https://doi.org/… form
    url = primary.get("landing_page_url") or doi_url or work.get("id")
    if not url:
        return None

    venue = ((primary.get("source") or {}).get("display_name")) or None
    # OpenAlex mirrors the other registries' ids on every work it knows about,
    # so a biomedical work found here arrives with the pmcid that unlocks free
    # Europe PMC full text — see sources/fulltext.py.
    ids = work.get("ids") or {}
    return SourceCandidate(
        source_type=SOURCE_TYPE,
        url=url,
        title=title,
        author=_authors(work),
        snippet=abstract,
        metadata={
            "openalex_id": work.get("id"),
            "doi": _bare_doi(doi_url),
            "year": work.get("publication_year"),
            "cited_by_count": work.get("cited_by_count"),
            "venue": venue,
            "work_type": work.get("type"),
            "oa_pdf_url": best_oa.get("pdf_url"),
            "oa_landing_url": best_oa.get("landing_page_url"),
            "is_open_access": bool((work.get("open_access") or {}).get("is_oa")),
            "pmid": ids.get("pmid"),
            "pmcid": ids.get("pmcid"),
            "abstract": abstract,
        },
        identifiers=Identifiers.build(
            openalex_id=work.get("id"),
            doi=doi_url,
            pmid=_bare_registry_id(ids.get("pmid")),
            pmcid=_bare_registry_id(ids.get("pmcid")),
        ),
    )


def _reconstruct_abstract(inverted: dict | None) -> str:
    """OpenAlex ships abstracts as an inverted index ({word: [positions]})."""
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = [
        (pos, word)
        for word, poss in inverted.items()
        if isinstance(poss, list)
        for pos in poss
        if isinstance(pos, int)
    ]
    if not positions:
        return ""
    positions.sort()
    return _WS_RE.sub(" ", " ".join(word for _, word in positions)).strip()


def _authors(work: dict) -> str | None:
    """First three authors, matching the arxiv fetcher's author convention."""
    names = [
        name
        for a in work.get("authorships") or []
        if isinstance(a, dict)
        for name in [(a.get("author") or {}).get("display_name")]
        if isinstance(name, str) and name.strip()
    ]
    return ", ".join(names[:3]) if names else None


def _bare_registry_id(url: str | None) -> str | None:
    """OpenAlex ships PMIDs and PMCIDs as resolver URLs; the tail is the id."""
    if not url or not isinstance(url, str):
        return None
    return url.rstrip("/").rsplit("/", 1)[-1] or None


def _bare_doi(doi_url: str | None) -> str | None:
    if not doi_url:
        return None
    return doi_url.removeprefix("https://doi.org/").removeprefix("http://doi.org/") or None
