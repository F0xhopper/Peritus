import asyncio

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.sources.domain import Identifiers, RawSource, SourceCandidate, SourceType
from peritus.sources.fetchers.base import note_search_failure
from peritus.sources.identifiers import identifiers_from_url

logger = get_logger(__name__)

_MAX_CHARS = 80_000
_SNIPPET_CHARS = 600


def excluded_domains() -> list[str]:
    """Hosts triage penalises hard enough that searching them is paying to discard.

    Built from the triage prior's own table, so the two cannot drift apart.
    """
    from peritus.sources.triage import penalised_hosts

    return penalised_hosts()


class ExaFetcher:
    async def search(
        self,
        query: str,
        max_results: int = 8,
        *,
        include_domains: list[str] | None = None,
    ) -> list[SourceCandidate]:
        """Neural search with page text as the snippet.

        ``include_domains`` restricts the search (the canonical-work resolver
        uses it for primary-text hosts). Otherwise the hosts triage would score
        down are excluded, so their results are never paid for in triage tokens
        or fetch slots. Exa accepts one list or the other, not both.
        """
        if not settings.EXA_API_KEY:
            logger.warning("EXA_API_KEY not set — skipping Exa fetcher")
            return []

        domain_filter: dict[str, list[str]] = (
            {"include_domains": include_domains}
            if include_domains
            else {"exclude_domains": excluded_domains()}
        )
        try:
            from exa_py import Exa  # type: ignore
            client = Exa(api_key=settings.EXA_API_KEY)
            # exa_py is a sync client — keep it off the event loop.
            results = await asyncio.to_thread(
                client.search_and_contents,
                query,
                num_results=max_results,
                type="neural",
                text={"max_characters": _SNIPPET_CHARS},
                **domain_filter,
            )
            candidates = []
            for r in results.results:
                snippet = getattr(r, "text", None) or ""
                if not r.url:
                    continue
                # Exa lands on doi.org and arxiv.org constantly. Without this
                # the same paper found by exa and by openalex are two sources.
                doi, arxiv_id = identifiers_from_url(r.url)
                candidates.append(SourceCandidate(
                    source_type=SourceType.EXA,
                    url=r.url,
                    title=r.title or r.url,
                    author=None,
                    snippet=snippet,
                    metadata={"exa_id": r.id},
                    identifiers=Identifiers.build(doi=doi, arxiv_id=arxiv_id),
                ))
            return candidates
        except Exception as exc:
            logger.warning("Exa search failed for %r: %s", query, exc)
            note_search_failure(*classify_search_error(exc, "Exa"))
            return []

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        from peritus.sources.sections import apply_sections

        text = await fetch_exa_contents(candidate.url)
        if len(text) < 500:
            return None
        text, selected = apply_sections(text, candidate.metadata, _MAX_CHARS)
        return RawSource(
            source_type=SourceType.EXA,
            url=candidate.url,
            title=candidate.title,
            author=candidate.author,
            text=text,
            metadata={**candidate.metadata, **selected},
            identifiers=candidate.identifiers,
        )


async def fetch_exa_contents(url: str) -> str:
    """Full-text retrieval for a URL Exa has already indexed. '' on failure."""
    if not settings.EXA_API_KEY:
        return ""
    try:
        from exa_py import Exa  # type: ignore
        client = Exa(api_key=settings.EXA_API_KEY)
        results = await asyncio.to_thread(client.get_contents, [url], text=True)
        for r in results.results:
            return getattr(r, "text", None) or ""
        return ""
    except Exception as exc:
        logger.warning("Exa contents fetch failed for %r: %s", url, exc)
        return ""


def classify_search_error(exc: BaseException, service: str) -> tuple[str, str]:
    """``(status, message)`` for a search API exception, by what it looks like.

    SDKs wrap HTTP errors in their own types, so the status code is read off the
    message as a last resort — good enough to tell a rate limit from a timeout
    in a build log, which is all it is for.
    """
    from peritus.sources.fetchers.base import (
        STATUS_ERROR,
        STATUS_RATE_LIMITED,
        STATUS_TIMEOUT,
    )

    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if isinstance(exc, TimeoutError) or "timeout" in lowered or "timed out" in lowered:
        return STATUS_TIMEOUT, f"{service}: {text}"
    if "429" in lowered or "rate limit" in lowered or "too many requests" in lowered:
        return STATUS_RATE_LIMITED, f"{service}: {text}"
    return STATUS_ERROR, f"{service}: {text}"
