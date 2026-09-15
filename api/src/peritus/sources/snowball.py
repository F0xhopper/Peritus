"""Citation snowballing: what the accepted corpus vouches for.

An accepted source is a judgement the pipeline has already paid for and already
trusts. What it cites, and what cites it, is therefore the highest-precision
discovery channel available — better than any search query, because it is the
field's own opinion of what matters rather than a search engine's.

Three things changed from the version this replaces, which followed at most
three seeds' backward references and kept anything with 50+ citations:

**Forward citations.** Backward citation finds a seed's ancestors. Forward
citation finds the work that *superseded* it — which the planner cannot know
about, because it postdates whatever made the topic famous. A corpus with only
backward citations is systematically old.

**Co-citation instead of a flat floor.** "50 citations" means canonical in
machine learning and unheard-of in a small humanities subfield, so the floor was
really a filter on discipline. What travels across fields is *relative* standing
(a percentile within the seed's own reference list) and *agreement* (how many
different accepted sources point at the same work). A paper two of your accepted
sources both cite is worth fetching whatever its absolute count.

**Triage, not a bypass.** Snowball results used to be fetched directly. They now
enter the round's triage like anything else, so they are ranked against the same
brief and compete on the same terms — and the ledger can compare their
acceptance rate against the plan fetchers', which is the only way to know
whether the ranking here is any good.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx

from peritus.core.logging import get_logger
from peritus.sources.dedup import SeenSet
from peritus.sources.domain import Identifiers, SourceCandidate, SourceType, ValidatedSource
from peritus.sources.fetchers.pdf import identifiers_from_external, semantic_scholar_headers

logger = get_logger(__name__)

_S2 = "https://api.semanticscholar.org/graph/v1"

# Semantic Scholar allows 500 ids per batch call; a build never approaches it,
# but batching is what keeps the request count polite as seeds grow.
_BATCH_LIMIT = 100
_REFERENCE_LIMIT = 100
_CITATION_LIMIT = 100
_REQUEST_TIMEOUT = 20.0
# Concurrent seed lookups. S2 rate-limits unauthenticated traffic, so this stays
# well below the fetch stage's concurrency.
_SEED_CONCURRENCY = 3

# A candidate must sit in the top of its own list to be worth a fetch slot. A
# percentile travels across fields where an absolute citation count does not.
_PERCENTILE_FLOOR = 0.80
# …unless more than one accepted source points at it, which is stronger evidence
# than any percentile.
_CO_CITATION_OVERRIDE = 2

_FIELDS = "title,abstract,citationCount,year,authors,externalIds,openAccessPdf"

# A candidate is only worth a fetch slot if there is some route to text for it.
# Semantic Scholar has no abstract for most books and older canonical works, and
# a candidate with neither a usable abstract nor a route to full text is fetched,
# returns nothing, and silently refills its slot — measured at 16 of 20 proposals
# on a real humanities corpus, and the 16 included exactly the canonical works
# snowballing exists to find. Proposing them is not free: they displace
# candidates that can actually be read.
#
# Matches the floor the openalex fetcher applies, since that is where these
# candidates are routed.
_MIN_STANDALONE_ABSTRACT = 200

DISCOVERED_BACKWARD = "snowball:backward"
DISCOVERED_FORWARD = "snowball:forward"


@dataclass
class SnowballCandidate:
    """One work the citation graph pointed at, with the evidence for it."""

    identifiers: Identifiers
    title: str
    abstract: str
    authors: str | None
    year: int | None
    citations: int
    direction: str
    # Accepted sources that cite it or are cited by it, by their URL. Length is
    # the co-citation count and the primary ranking signal.
    seeds: set[str] = field(default_factory=set)
    # Best percentile this candidate reached in any one seed's list.
    percentile: float = 0.0
    oa_pdf_url: str | None = None

    @property
    def co_citations(self) -> int:
        return len(self.seeds)

    @property
    def rank_key(self) -> tuple[int, float, int]:
        return (self.co_citations, self.percentile, self.citations)

    def worth_fetching(self) -> bool:
        return (
            self.co_citations >= _CO_CITATION_OVERRIDE
            or self.percentile >= _PERCENTILE_FLOOR
        )

    @property
    def is_fetchable(self) -> bool:
        """Whether any route to this work's text exists.

        An abstract long enough to stand on its own, an open-access PDF, or an
        identifier that reaches free full text (arXiv's ar5iv, Europe PMC's
        JATS). Without one of those the fetch is guaranteed to return nothing.
        """
        return (
            len(self.abstract) >= _MIN_STANDALONE_ABSTRACT
            or bool(self.oa_pdf_url)
            or bool(self.identifiers.arxiv_id)
            or bool(self.identifiers.pmcid)
        )

    @property
    def is_priority(self) -> bool:
        """Whether this work should be fetched ahead of everything else.

        Two or more of the corpus's own accepted sources point at it. That is
        the strongest evidence of importance the pipeline can obtain — stronger
        than any triage score, which reads a title and a snippet — and it must
        not be lost to the fetch queue's cost ordering, which would otherwise
        rank a long canonical paper below a cheap web page.
        """
        return self.co_citations >= _CO_CITATION_OVERRIDE

    def to_candidate(self) -> SourceCandidate:
        """Enter triage as an ordinary candidate, carrying its identity.

        The URL prefers the DOI resolver: triage's domain prior already treats
        ``doi.org`` as evidence of a published scholarly work, and the full-text
        resolver keys on identifiers rather than the URL anyway.
        """
        ids = self.identifiers
        if ids.doi:
            url = f"https://doi.org/{ids.doi}"
        elif ids.arxiv_id:
            url = f"https://arxiv.org/abs/{ids.arxiv_id}"
        elif ids.pmcid:
            url = f"https://europepmc.org/article/PMC/{ids.pmcid}"
        elif ids.openalex_id:
            url = f"https://openalex.org/{ids.openalex_id}"
        else:
            url = f"https://www.semanticscholar.org/paper/{ids.s2_id}"
        return SourceCandidate(
            source_type=SourceType.OPENALEX,
            url=url,
            title=self.title,
            author=self.authors,
            snippet=self.abstract or self.title,
            metadata={
                "discovered_via": self.direction,
                "snowballed": True,
                "citations": self.citations,
                "cited_by_count": self.citations,
                "year": self.year,
                "co_citations": self.co_citations,
                "fetch_priority": self.is_priority,
                "snowball_seed_urls": sorted(self.seeds),
                "oa_pdf_url": self.oa_pdf_url,
                "is_open_access": bool(self.oa_pdf_url),
                **ids.to_dict(),
            },
            identifiers=ids,
        )


def seed_ids(sources: list[ValidatedSource]) -> list[tuple[str, ValidatedSource]]:
    """``(semantic scholar id, source)`` for every accepted source S2 can resolve.

    Seeded only from *accepted* sources, so a paper the validator rejected never
    lends its references any authority.
    """
    seeds: list[tuple[str, ValidatedSource]] = []
    seen: set[str] = set()
    for source in sources:
        ids = source.identifiers
        if ids.arxiv_id:
            key = f"arXiv:{ids.arxiv_id}"
        elif ids.doi:
            key = f"DOI:{ids.doi}"
        elif ids.pmid:
            key = f"PMID:{ids.pmid}"
        elif ids.s2_id:
            key = ids.s2_id
        else:
            continue
        if key in seen:
            continue
        seen.add(key)
        seeds.append((key, source))
    return seeds


async def snowball(
    accepted: list[ValidatedSource],
    seen: SeenSet | None = None,
    max_candidates: int = 10,
) -> list[SourceCandidate]:
    """Candidates from the citation neighbourhood of this round's accepted sources.

    Best-effort throughout: Semantic Scholar is unauthenticated and rate-limits,
    so a failed lookup costs one seed's contribution and nothing else. Returns
    triage-ready candidates ranked by co-citation, then percentile, then raw
    citation count.
    """
    seeds = seed_ids(accepted)
    if not seeds or max_candidates <= 0:
        return []

    pool: dict[str, SnowballCandidate] = {}
    semaphore = asyncio.Semaphore(_SEED_CONCURRENCY)

    async with httpx.AsyncClient(
        timeout=_REQUEST_TIMEOUT, headers=semantic_scholar_headers(), follow_redirects=True
    ) as http:

        async def _one(key: str, source: ValidatedSource) -> None:
            async with semaphore:
                backward = await _fetch_list(http, key, "references", _REFERENCE_LIMIT)
                forward = await _fetch_list(http, key, "citations", _CITATION_LIMIT)
            _absorb(pool, backward, source, DISCOVERED_BACKWARD)
            _absorb(pool, forward, source, DISCOVERED_FORWARD)

        await asyncio.gather(*[_one(key, source) for key, source in seeds])

    # Never propose what the build has already seen — its own seeds included.
    seed_keys: set[str] = set()
    for _key, source in seeds:
        seed_keys |= source.identifiers.keys()

    eligible = [
        c for c in pool.values()
        if c.worth_fetching()
        and not (c.identifiers.keys() & seed_keys)
        and not (seen is not None and seen.has(c.identifiers, ""))
    ]
    unreadable = [c for c in eligible if not c.is_fetchable]
    ranked = sorted(
        (c for c in eligible if c.is_fetchable),
        key=lambda c: c.rank_key,
        reverse=True,
    )[:max_candidates]

    if unreadable:
        # Worth a line rather than a silent drop: these are works the corpus's
        # own sources vouch for, and the reason they cannot be used is a gap in
        # what the indexes hold, not a judgement about them.
        logger.info(
            "Snowball: %d well-cited work(s) skipped for having no reachable text "
            "(no abstract, no open-access PDF, no arXiv/PMC id) — e.g. %s",
            len(unreadable),
            "; ".join(c.title[:60] for c in unreadable[:3]),
        )

    if ranked:
        logger.info(
            "Snowball: %d seed(s) → %d candidate(s) considered → %d proposed "
            "(%d backward, %d forward, %d co-cited by 2+)",
            len(seeds), len(pool), len(ranked),
            sum(1 for c in ranked if c.direction == DISCOVERED_BACKWARD),
            sum(1 for c in ranked if c.direction == DISCOVERED_FORWARD),
            sum(1 for c in ranked if c.co_citations >= _CO_CITATION_OVERRIDE),
        )
    return [c.to_candidate() for c in ranked]


async def _fetch_list(
    http: httpx.AsyncClient, key: str, edge: str, limit: int
) -> list[dict]:
    """One seed's references or citations, as bare paper records."""
    field_name = "citedPaper" if edge == "references" else "citingPaper"
    try:
        resp = await http.get(
            f"{_S2}/paper/{key}/{edge}",
            params={"fields": _FIELDS, "limit": limit},
        )
        if resp.status_code == 429:
            logger.warning("Snowball: Semantic Scholar rate-limited %s for %s (429)", edge, key)
            return []
        if resp.status_code != 200:
            logger.debug("S2 %s for %s returned %d", edge, key, resp.status_code)
            return []
        rows = resp.json().get("data", []) or []
    except Exception as exc:
        logger.debug("S2 %s failed for %s: %s", edge, key, exc)
        return []
    return [row.get(field_name) or {} for row in rows]


def _absorb(
    pool: dict[str, SnowballCandidate],
    papers: list[dict],
    seed: ValidatedSource,
    direction: str,
) -> None:
    """Fold one seed's list into the shared pool, scoring by within-list percentile.

    The percentile is computed against *this list*, which is what makes the
    ranking field-agnostic: a paper in the top fifth of a physics reference list
    and one in the top fifth of a medieval-philosophy reference list are treated
    as equally endorsed, though their absolute counts differ by orders of
    magnitude.
    """
    scored = [(p, p.get("citationCount") or 0) for p in papers if p.get("title")]
    if not scored:
        return
    counts = sorted(count for _p, count in scored)
    total = len(counts)

    for paper, count in scored:
        ids = identifiers_from_external(paper.get("externalIds"))
        if paper.get("paperId"):
            ids = ids.with_(s2_id=paper["paperId"])
        key = ids.canonical_key()
        if key is None:
            continue
        # Fraction of this list the candidate is STRICTLY above. Ties must not
        # count: a reference list where nine of ten papers have one citation
        # each is nine papers nobody singled out, and counting ties as beating
        # each other would put every one of them in the top decile.
        percentile = sum(1 for c in counts if c < count) / total

        existing = pool.get(key)
        if existing is None:
            existing = SnowballCandidate(
                identifiers=ids,
                title=str(paper.get("title") or "").strip(),
                abstract=str(paper.get("abstract") or "").strip(),
                authors=_authors(paper),
                year=paper.get("year") if isinstance(paper.get("year"), int) else None,
                citations=count,
                direction=direction,
                oa_pdf_url=(paper.get("openAccessPdf") or {}).get("url"),
            )
            pool[key] = existing
        else:
            existing.identifiers = existing.identifiers.merge(ids)
            existing.citations = max(existing.citations, count)
            existing.abstract = existing.abstract or str(paper.get("abstract") or "").strip()
            existing.oa_pdf_url = existing.oa_pdf_url or (
                paper.get("openAccessPdf") or {}
            ).get("url")
            # A work reached both ways is reported as backward: it is both an
            # ancestor and a descendant of the corpus, and "backward" is the
            # stronger claim about it being foundational.
            if direction == DISCOVERED_BACKWARD:
                existing.direction = DISCOVERED_BACKWARD
        existing.seeds.add(seed.url)
        existing.percentile = max(existing.percentile, percentile)


def _authors(paper: dict) -> str | None:
    """First three authors, matching every other fetcher's convention."""
    names = [
        name
        for a in paper.get("authors") or []
        if isinstance(a, dict)
        for name in [a.get("name")]
        if isinstance(name, str) and name.strip()
    ]
    return ", ".join(names[:3]) if names else None
