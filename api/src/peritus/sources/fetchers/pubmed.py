"""PubMed fetcher, via Europe PMC — searches biomedical literature (title +
abstract), fetches open-access full text as JATS XML.

Europe PMC rather than NCBI E-utilities. E-utilities splits a search into
`esearch` (PMIDs only) then `esummary`/`efetch` (XML) — two round trips before
you have a snippet at all, which breaks the cheap-`search()` half of the Fetcher
contract. Europe PMC returns title, abstract, authors and identifiers from one
JSON call, indexes a superset of MEDLINE (preprints, agricultural and patent
literature, clinical guidelines), serves open-access full text from a single
endpoint, and allows 10 requests/second unauthenticated — where E-utilities
allows 3 without an API key, and Peritus has no key to give it.
"""

import asyncio
import re

import httpx
from bs4 import BeautifulSoup

from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceCandidate, SourceType

logger = get_logger(__name__)

_REST = "https://www.ebi.ac.uk/europepmc/webservices/rest"
_SEARCH_URL = f"{_REST}/search"
_ARTICLE_URL = "https://europepmc.org/article/{src}/{ext_id}"

HEADERS = {"User-Agent": "Peritus/2.0 (research corpus builder)"}
MIN_FULL_TEXT = 3_000
MAX_FULL_TEXT = 120_000
# Below this an "abstract" is a structured-heading stub or a bare citation line,
# not something worth an embedding slot.
MIN_ABSTRACT = 200
# Europe PMC caps pageSize at 1000; the builder never asks for anything near it.
MAX_PAGE_SIZE = 100

# JATS subtrees that are citation plumbing rather than argument: <back> holds the
# reference list and acknowledgements, <xref> renders as a bare superscript digit
# mid-sentence, and figures/tables lose their meaning without the graphic.
_DROP_TAGS = (
    "back", "ref-list", "table-wrap", "fig", "xref",
    "graphic", "inline-graphic", "supplementary-material",
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\n{3,}")

# Aliased rather than referenced inline so the tests can assert against one name.
SOURCE_TYPE: SourceType = SourceType.PUBMED


class PubmedFetcher:
    async def search(self, query: str, max_results: int = 4) -> list[SourceCandidate]:
        params: dict[str, str | int] = {
            # Triage scores candidates on their snippet, so records without an
            # abstract are excluded here rather than fetched and dropped later.
            "query": f"({query}) AND (HAS_ABSTRACT:Y)",
            "format": "json",
            "resultType": "core",
            "pageSize": max(1, min(max_results, MAX_PAGE_SIZE)),
        }
        try:
            async with httpx.AsyncClient(timeout=30, headers=HEADERS) as http:
                resp = await http.get(_SEARCH_URL, params=params)
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:
            logger.warning("Europe PMC search failed for %r: %s", query, exc)
            return []

        results = payload.get("resultList", {}).get("result", []) or []
        candidates = [_to_candidate(r) for r in results[:max_results]]
        return [c for c in candidates if c is not None]

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        pmcid = candidate.metadata.get("pmcid")
        full_text = ""
        # Only the open-access subset has retrievable full text; asking for the
        # rest is a guaranteed 404, so don't spend the request.
        if pmcid and candidate.metadata.get("open_access"):
            try:
                async with httpx.AsyncClient(
                    timeout=30, headers=HEADERS, follow_redirects=True
                ) as http:
                    full_text = await fetch_full_text(http, pmcid)
            except Exception as exc:
                logger.warning("Europe PMC full text failed for %r: %s", pmcid, exc)
                full_text = ""

        abstract = candidate.metadata.get("abstract") or candidate.snippet
        has_full = len(full_text) >= MIN_FULL_TEXT
        if has_full:
            # JATS <body> excludes the abstract, so prepend it — it is usually the
            # densest statement of the paper's claim.
            text = f"{candidate.title}\n\n{abstract}\n\n{full_text}"[:MAX_FULL_TEXT]
        elif len(abstract) >= MIN_ABSTRACT:
            text = f"{candidate.title}\n\n{abstract}"
        else:
            return None

        metadata = {k: v for k, v in candidate.metadata.items() if k != "abstract"}
        metadata["full_text"] = has_full
        return RawSource(
            source_type=SOURCE_TYPE,
            url=candidate.url,
            title=candidate.title,
            author=candidate.author,
            text=text,
            metadata=metadata,
        )


def _to_candidate(result: dict) -> SourceCandidate | None:
    """Map one Europe PMC `core` search result onto a candidate.

    Returns None for records too thin to triage — no title, or an abstract that
    is only a structured heading.
    """
    title = _strip_markup(result.get("title", ""))
    abstract = _strip_markup(result.get("abstractText", ""))
    if not title or len(abstract) < MIN_ABSTRACT:
        return None

    src = result.get("source", "MED")
    ext_id = result.get("id", "")
    pmcid = result.get("pmcid")
    return SourceCandidate(
        source_type=SOURCE_TYPE,
        url=_ARTICLE_URL.format(src=src, ext_id=ext_id),
        title=title,
        author=_authors(result),
        snippet=abstract,
        metadata={
            "pmid": result.get("pmid"),
            "pmcid": pmcid,
            "doi": result.get("doi"),
            "journal": (result.get("journalInfo") or {}).get("journal", {}).get("title"),
            "year": result.get("pubYear"),
            "cited_by_count": result.get("citedByCount"),
            # Full text is only retrievable when the article is open access *and*
            # actually deposited in Europe PMC (inEPMC), not merely licensed as OA.
            "open_access": result.get("isOpenAccess") == "Y" and result.get("inEPMC") == "Y",
            "europepmc_source": src,
            "abstract": abstract,
        },
    )


def _authors(result: dict) -> str | None:
    """First three authors, matching the arxiv fetcher's author convention."""
    authors = (result.get("authorList") or {}).get("author") or []
    names: list[str] = [
        name
        for a in authors
        if isinstance(a, dict)
        for name in [a.get("fullName") or a.get("lastName")]
        if isinstance(name, str) and name.strip()
    ]
    if names:
        return ", ".join(names[:3])
    author_string = (result.get("authorString") or "").strip().rstrip(".")
    return author_string or None


def _strip_markup(text: str) -> str:
    """Europe PMC embeds structured-abstract headings as raw HTML/JATS tags."""
    return _TAG_RE.sub(" ", text or "").replace("  ", " ").strip()


def _jats_to_text(xml: str) -> str:
    soup = BeautifulSoup(xml, "lxml-xml")
    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()
    body = soup.find("body")
    if not body:
        return ""
    return _WS_RE.sub("\n\n", body.get_text(separator="\n", strip=True))


async def fetch_full_text(client: httpx.AsyncClient, pmcid: str) -> str:
    """Fetch the JATS XML body of an open-access article and flatten it to text."""
    try:
        resp = await client.get(f"{_REST}/{pmcid}/fullTextXML", timeout=20)
        if resp.status_code != 200:
            return ""
        # Off the loop — full-text JATS is big, and the parse is CPU-bound work
        # that would otherwise stall the build worker's heartbeat.
        return await asyncio.to_thread(_jats_to_text, resp.text)
    except Exception as exc:
        logger.debug("Europe PMC full text fetch failed for %r: %s", pmcid, exc)
        return ""
