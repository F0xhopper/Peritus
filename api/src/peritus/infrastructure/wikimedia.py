"""One HTTP client for everything Peritus asks of Wikimedia.

Two callers today: :mod:`peritus.experts.picture`, which finds an expert's
picture, and :mod:`peritus.sources.fetchers.wikipedia`, which fetches article
text. They shared nothing before and each invented its own user agent; the
Wikimedia API policy asks for one that names the tool and carries a contact
address, so the constant lives here and both use it.

Every method returns plain dicts straight off the API, and the only state is an
``httpx.AsyncClient``. That is deliberate: the policy that decides which picture
is acceptable is pure functions in ``experts/picture.py``, and those tests feed
a fake of this class recorded JSON rather than touching the network.
"""

import asyncio
import random
import re
from typing import Any

import httpx

from peritus.core.config import settings
from peritus.core.logging import get_logger

logger = get_logger(__name__)

API_URL = "https://en.wikipedia.org/w/api.php"
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"


def user_agent() -> str:
    """The User-Agent every Wikimedia request carries.

    Their API etiquette asks for a tool name, a version and a way to reach the
    operator. ``PERITUS_CONTACT`` is unset in a fresh checkout — we still send a
    descriptive agent then, because an anonymous-but-honest one is better than
    the default httpx string, but a deployment making real volume should set it.
    """
    contact = settings.PERITUS_CONTACT.strip()
    suffix = f"; {contact}" if contact else ""
    return f"Peritus/2.0 (research corpus builder{suffix})"


# How many times one request is retried, and the floor of the backoff between
# attempts. Both are small: the whole search runs under a build's deadline, and
# a request worth many minutes of retrying is a request worth abandoning.
_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 8.0

# What a 429 costs when the response does not say. Deliberately far above the
# backoff a 5xx gets: a 429 means "you personally are asking too often", and
# retrying it in a second is how a client earns a longer ban rather than an
# answer.
_THROTTLE_WAIT = 5.0


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """How long to wait before retrying, preferring what the server asked for.

    ``Retry-After`` is seconds or an HTTP date; only the numeric form is worth
    parsing, because that is what MediaWiki sends. A 429 with no header at all
    still waits :data:`_THROTTLE_WAIT`, not a fraction of a second.
    """
    header = response.headers.get("retry-after", "").strip()
    if header.isdigit():
        # Bounded: a server asking for ten minutes is asking for more than a
        # build has, and the caller degrades to no picture far more cheaply.
        return min(60.0, float(header))
    if response.status_code == 429:
        return _THROTTLE_WAIT * attempt
    return min(_BACKOFF_MAX, _BACKOFF_BASE * 2 ** (attempt - 1))


def normalise_title(title: str) -> str:
    """MediaWiki's canonical form of a page or file title.

    Underscores and spaces are interchangeable in a title and the API is free to
    return either — ``pageimages`` uses underscores, ``imageinfo`` uses spaces.
    Anything that keys one endpoint's result by another's title must go through
    this, or it will miss every title with a space in it.
    """
    return " ".join(title.replace("_", " ").split())


class WikimediaClient:
    """Thin async wrapper over the MediaWiki Action APIs.

    Owns its ``httpx.AsyncClient`` and is an async context manager, so a caller
    that makes five requests in one build opens one connection pool rather than
    five. Safe to use without the context manager too — ``aclose`` is idempotent.
    """

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "WikimediaClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip"},
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, url: str, params: dict[str, Any]) -> dict:
        """One GET, retried on 429 and 5xx, with Wikimedia's own pacing honoured.

        Written by hand rather than with ``tenacity`` because the only backoff
        that matters here is the one the *server* asks for. A 429 carries
        ``Retry-After``, and an exponential curve that ignores it is how a
        client that is merely being paced turns into one that is being blocked —
        which is exactly what the first backfill run did, retrying three times
        in four seconds and failing four of five experts.
        """
        last: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                resp = await self._http().get(url, params={**params, "format": "json"})
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status != 429 and status < 500:
                    raise  # a 404 or a 400 is an answer, not a blip
                last = exc
                delay = _retry_delay(exc.response, attempt)
            except httpx.TransportError as exc:
                last = exc
                delay = min(_BACKOFF_MAX, _BACKOFF_BASE * 2 ** (attempt - 1))

            if attempt == _MAX_ATTEMPTS:
                break
            # Jittered, so two builds throttled at the same moment do not come
            # back in lockstep and throttle each other again.
            await asyncio.sleep(delay * (1 + random.random() * 0.25))

        assert last is not None
        raise last

    # ── the five calls the picture finder makes ─────────────────────────────

    async def search_with_snippets(self, query: str, limit: int = 3) -> list[dict[str, str]]:
        """``{title, snippet}`` for articles matching ``query``, best first, snippet as plain text."""
        data = await self._get(
            API_URL,
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "srnamespace": 0,
                "srprop": "snippet",
            },
        )
        return [
            {"title": hit["title"], "snippet": re.sub(r"<[^>]+>", "", hit.get("snippet") or "")}
            for hit in data.get("query", {}).get("search", [])
        ]

    async def extract(self, title: str, section_format: str = "plain") -> str:
        """An article's plain-text extract; ``section_format="wiki"`` keeps ``== Heading ==`` markers."""
        data = await self._get(
            API_URL,
            {
                "action": "query",
                "titles": title,
                "prop": "extracts",
                "explaintext": True,
                "exsectionformat": section_format,
            },
        )
        pages = (data.get("query") or {}).get("pages") or {}
        page: dict[str, Any] = next(iter(pages.values()), {}) if pages else {}
        return str(page.get("extract") or "")

    async def search_articles(self, query: str, limit: int = 3) -> list[str]:
        """Article titles matching ``query``, best first."""
        data = await self._get(
            API_URL,
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "srnamespace": 0,
                "srprop": "",
            },
        )
        return [hit["title"] for hit in data.get("query", {}).get("search", [])]

    async def page_images(self, titles: list[str], thumb_size: int = 512) -> list[dict]:
        """Lead image, Wikidata id and disambiguation flag for up to 50 titles.

        ``pilicense=free`` is the important parameter: it makes the API refuse
        to hand back a non-free lead image at all, so a fair-use album cover
        never even enters the candidate list.
        """
        if not titles:
            return []
        data = await self._get(
            API_URL,
            {
                "action": "query",
                "titles": "|".join(titles[:50]),
                "prop": "pageimages|pageprops",
                "piprop": "thumbnail|name|original",
                "pithumbsize": thumb_size,
                "pilimit": 50,
                "pilicense": "free",
                "ppprop": "wikibase_item|disambiguation",
                "redirects": 1,
            },
        )
        pages = data.get("query", {}).get("pages", {})
        # Negative page ids are "no such page"; they carry nothing useful.
        return [p for p in pages.values() if isinstance(p, dict) and p.get("pageid")]

    async def wikidata_claims(self, entity_ids: list[str]) -> dict[str, dict]:
        """``{Q1234: claims}`` for the entities behind a batch of articles."""
        ids = [e for e in entity_ids if e][:50]
        if not ids:
            return {}
        data = await self._get(
            WIKIDATA_API_URL,
            {
                "action": "wbgetentities",
                "ids": "|".join(ids),
                "props": "claims",
            },
        )
        entities = data.get("entities", {})
        return {
            qid: entity.get("claims", {})
            for qid, entity in entities.items()
            if isinstance(entity, dict)
        }

    async def image_info(self, file_titles: list[str], thumb_width: int = 512) -> dict[str, dict]:
        """``{File:Foo bar.jpg: imageinfo}`` — licence, credit, mime, size, urls.

        **Keys are normalised, and that is not cosmetic.** ``pageimages`` hands
        back a file name with underscores (``Beekeeper_2017.jpg``); this endpoint
        echoes the canonical title with spaces (``Beekeeper 2017.jpg``). Looking
        the result up under the name you asked with therefore misses every file
        whose name contains a space — which silently made every such expert
        "no freely licensed picture found", including most of them.
        """
        titles = [t for t in file_titles if t][:50]
        if not titles:
            return {}
        data = await self._get(
            API_URL,
            {
                "action": "query",
                "titles": "|".join(titles),
                "prop": "imageinfo",
                "iiprop": "extmetadata|mime|size|url",
                "iiurlwidth": thumb_width,
            },
        )
        out: dict[str, dict] = {}
        for page in data.get("query", {}).get("pages", {}).values():
            if not isinstance(page, dict):
                continue
            info = page.get("imageinfo") or []
            if info:
                out[normalise_title(page.get("title", ""))] = info[0]
        return out

    async def download(self, url: str, max_bytes: int) -> bytes | None:
        """Fetch an image, refusing anything over ``max_bytes``.

        The cap is enforced while streaming rather than on ``Content-Length``:
        a server is free to omit or lie about that header, and the point of the
        cap is that a hostile or mistaken response cannot cost us memory.
        """
        try:
            async with self._http().stream("GET", url) as resp:
                resp.raise_for_status()
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    logger.info("Picture at %s declares %s bytes — over the cap", url, declared)
                    return None
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        logger.info("Picture at %s exceeded %d bytes mid-stream", url, max_bytes)
                        return None
                    chunks.append(chunk)
        except asyncio.CancelledError:
            raise
        except httpx.HTTPError as exc:
            logger.info("Could not download picture %s: %s", url, exc)
            return None
        return b"".join(chunks)
