"""Finding a picture of what an expert is about.

An expert's default identity used to be a monogram derived from its persona
name. This module finds something better: the picture Wikipedia's editors chose
to head the article on the subject — the bust of Zeno for Stoicism, the Gentile
da Fabriano panel for Thomism — with its licence and its attribution recorded.

**It is a picture of the subject, never a headshot of the persona.** That
distinction is what keeps migration 026's original reasoning intact. A found
image of Zeno illustrates Stoicism the way a book cover does; it makes no claim
that "Dr. Elena Vasquez" is a real person who wrote the answers. Two rules
follow from it and are enforced below rather than left to taste:

- **No living people.** A portrait of someone alive beside an invented name is a
  worse misrepresentation than a generated face, and carries publicity-rights
  exposure that a bust of Marcus Aurelius does not. Checked against Wikidata:
  P31 contains Q5 (human) and there is no P570 (date of death) → dropped.
- **No marks.** A flag, a map, a logo, a seal or a coat of arms is what an
  article's lead image is when the subject is a country, a company or an
  organisation, and none of them is legible at 40px. Dropped by file name.

**Free licences only.** Public domain, CC0, CC BY, CC BY-SA. Anything NC or ND
is refused, and so is any file with a non-empty ``Restrictions`` field —
trademark, personality rights, national insignia — and any file the API will
not label at all. `pilicense=free` already refuses most of the rest upstream;
this is the second gate, because an unlabelled file is not a free one.

Everything here except :func:`find_picture` is a pure function over API
payloads, which is what lets the tests assert the policy on recorded JSON with
no network at all.
"""

import asyncio
import hashlib
import re
import struct
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.wikimedia import WikimediaClient, normalise_title

logger = get_logger(__name__)

# Licence short names we accept, compared case-insensitively after stripping
# version numbers and punctuation. Wikimedia writes these many ways ("CC BY-SA
# 4.0", "cc-by-sa-3.0", "Public domain", "PD-US"), so the match is on a
# normalised prefix rather than on equality with a fixed string.
_ACCEPTED_LICENSE_PREFIXES: tuple[str, ...] = (
    "public domain",
    "pd",
    "cc0",
    "cc by",
)

# Refused even when they appear inside an otherwise-accepted string: "CC BY-NC"
# starts with "cc by" and is emphatically not free enough to ship.
_REFUSED_LICENSE_MARKERS: tuple[str, ...] = ("nc", "nd", "noncommercial", "noderivs")

# What an article's lead image is when the subject is a place, a state or an
# organisation. Unreadable at 40px and not a picture of an idea.
# `\b` is wrong here: Commons file names are underscore-separated and `_` is a
# word character, so `\bmap\b` never matches "Map_of_Greece". These lookarounds
# treat anything that is not a letter or a digit as a separator, which is what
# an underscore, a space, a hyphen and a dot all are in a file name.
_MARK_RE = re.compile(
    r"(?<![a-z0-9])"
    r"(flags?|maps?|logos?|icons?|seals?|coat[\s_-]?of[\s_-]?arms|emblems?|"
    r"signature|locator|banner|insignia|crest|badge|wordmark|blank)"
    r"(?![a-z0-9])",
    re.IGNORECASE,
)

# Magic bytes for the four formats a browser will certainly render. An HTML
# error page served with `Content-Type: image/jpeg` fails this, which is the
# point — the content type is the server's claim, the bytes are the fact.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

# Wikidata property and item ids used by the living-person rule.
_P_INSTANCE_OF = "P31"
_P_DATE_OF_DEATH = "P570"
_Q_HUMAN = "Q5"

# Below this, the original is too small to crop to a square tile that still
# looks like something at 64px.
_MIN_ORIGINAL_SIDE = 240

# Words too common to establish that an article is about a subject. Not a real
# stopword list — just the ones that would otherwise connect any two English
# phrases through the `is_on_topic` rule below.
_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "from", "into", "that", "this", "there",
    "their", "about", "over", "under", "between", "through", "during",
    "history", "list", "introduction", "overview", "modern", "general",
    "theory", "theories", "study", "studies", "science", "sciences",
    "system", "systems", "method", "methods", "analysis", "research",
})


@dataclass(frozen=True)
class Candidate:
    """One article's lead image, as far as the policy has judged it."""

    page_title: str
    page_url: str
    file_name: str            # 'File:Zeno_of_Citium.jpg'
    thumb_url: str
    thumb_width: int
    thumb_height: int
    original_width: int
    original_height: int
    wikibase_item: str | None
    query: str                # the search that surfaced the article
    rank: int                 # position in the deduplicated article order
    # Filled in by the imageinfo pass.
    mime: str = ""
    license: str = ""
    license_url: str | None = None
    artist: str | None = None
    credit: str | None = None
    file_page_url: str = ""

    def as_metadata(self) -> dict:
        """The shape stored in ``expert_pictures.candidates`` — no bytes."""
        return {
            "page_title": self.page_title,
            "page_url": self.page_url,
            "file_name": self.file_name,
            "thumb_url": self.thumb_url,
            "license": self.license,
            "license_url": self.license_url,
            "artist": self.artist,
            "query": self.query,
        }


@dataclass(frozen=True)
class FoundPicture:
    """A picture, its bytes, and everything needed to credit it."""

    image: bytes
    content_type: str
    width: int
    height: int
    sha256: str
    provider: str
    file_name: str | None
    file_url: str
    file_page_url: str
    page_url: str | None
    page_title: str | None
    artist: str | None
    license: str
    license_url: str | None
    query: str | None
    candidates: list[dict] = field(default_factory=list)

    @property
    def byte_size(self) -> int:
        return len(self.image)

    @property
    def version(self) -> str:
        return self.sha256[:12]


class PictureSkipped(Exception):
    """No picture was found. ``reason`` is what the build event reports."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ── the policy, as pure functions ───────────────────────────────────────────


def _normalise_license(raw: str) -> str:
    text = unicodedata.normalize("NFKD", raw or "").casefold()
    return re.sub(r"[^a-z0-9 ]+", " ", text).strip()


def is_free_license(extmetadata: dict) -> bool:
    """Whether a file's ``extmetadata`` names a licence we may ship.

    Three ways to fail: a licence we do not accept, an NC/ND variant of one we
    otherwise would, and a non-empty ``Restrictions`` field — which is how
    Commons flags trademarked logos, personality rights and national insignia
    on files whose *copyright* is genuinely free.
    """
    if not isinstance(extmetadata, dict):
        return False

    restrictions = _extmeta(extmetadata, "Restrictions")
    if restrictions.strip():
        return False

    name = _normalise_license(_extmeta(extmetadata, "LicenseShortName"))
    if not name:
        # An unlabelled file is not a free file. Fail closed.
        return False

    tokens = name.split()
    if any(marker in tokens for marker in _REFUSED_LICENSE_MARKERS):
        return False
    # "cc by nc sa" normalises to tokens including "nc"; "cc by sa 4 0" does not.
    return any(name.startswith(prefix) for prefix in _ACCEPTED_LICENSE_PREFIXES)


def looks_like_a_mark(file_name: str) -> bool:
    """True for flags, maps, logos, seals — and for every SVG.

    SVG is excluded wholesale rather than by name: on Commons it is almost
    exclusively the format of diagrams, charts and insignia, and the ones that
    are not are still line art that reads as noise in a 40px rounded square.
    """
    if not file_name:
        return True
    if file_name.casefold().endswith(".svg"):
        return True
    return bool(_MARK_RE.search(file_name))


def is_living_human(claims: dict) -> bool:
    """True when Wikidata says this is a person with no recorded death.

    Absent or unreadable claims return False: an article we cannot classify is
    judged on its file name and its licence like any other, and the alternative
    — dropping everything Wikidata has not catalogued — would throw away most
    abstract topics, which are exactly the ones that need a picture most.
    """
    if not isinstance(claims, dict):
        return False
    instance_of = claims.get(_P_INSTANCE_OF) or []
    is_human = any(
        (c.get("mainsnak", {}).get("datavalue", {}).get("value", {}) or {}).get("id") == _Q_HUMAN
        for c in instance_of
        if isinstance(c, dict)
    )
    if not is_human:
        return False
    return not (claims.get(_P_DATE_OF_DEATH) or [])


def _content_words(text: str) -> set[str]:
    """Words in ``text`` substantial enough to mean something on their own."""
    return {
        w for w in re.split(r"[^a-z0-9]+", (text or "").casefold())
        if len(w) > 3 and w not in _STOPWORDS
    }


def is_on_topic(page_title: str, query: str, topic: str) -> bool:
    """Whether this article is plausibly *about* what we were looking for.

    The rule exists because a full-text search will happily answer a query about
    Aristotelian logic with Susan Sontag's *Against Interpretation* — which has
    a free lead image (its dust jacket) where none of the logic articles has one
    at all, so every filter downstream passes it and an expert on syllogisms
    ends up illustrated with an unrelated book cover.

    **An article found by the topic's own search always passes.** That search is
    Wikipedia's own answer to "what is this subject", and its results are
    routinely named nothing like the topic — the picture for Stoicism is the
    lead image of the *Stoicism* article, but the second hit is "Zeno of
    Citium", which shares not one word with it. Demanding lexical overlap there
    would throw away exactly the case this feature is for.

    A hit from a *concept* query has no such standing, so it must share a
    substantial word with either that concept or the topic.
    """
    if query.strip().casefold() == topic.strip().casefold():
        return True
    title_words = _content_words(page_title)
    return bool(title_words & (_content_words(query) | _content_words(topic)))


def _title_key(text: str) -> str:
    """Case- and punctuation-insensitive form, for the exact-title bonus."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").casefold())


def rank(candidates: list[Candidate], topic: str) -> list[Candidate]:
    """Order the shortlist: best picture of the topic first.

    Four signals, in priority order.

    1. **An article titled like the topic wins.** "Stoicism" is a better
       illustration of Stoicism than "Stoic physics", whatever their images.
    2. **An article that *is* what was searched for beats one that merely
       mentions it.** A search for "On Interpretation" returns Aristotle's
       treatise and also Susan Sontag's *Against Interpretation*; both share a
       substantial word, so :func:`is_on_topic` admits both, and only the title
       says which one the query was about.
    3. **Search order.** The API already ranked these by relevance, and the
       topic's own query ran first.
    4. **JPEG over PNG.** Photographs and paintings are JPEGs on Commons;
       rendered diagrams and screenshots are PNGs. Then larger originals, which
       correlate with a real photograph rather than a thumbnail someone uploaded.
    """
    topic_key = _title_key(topic)

    def key(c: Candidate) -> tuple:
        exact = 0 if _title_key(c.page_title) == topic_key else 1
        matches_query = 0 if _title_key(c.page_title) == _title_key(c.query) else 1
        jpeg = 0 if "jpeg" in c.mime or "jpg" in c.mime else 1
        area = c.original_width * c.original_height
        return (exact, matches_query, c.rank, jpeg, -area)

    return sorted(candidates, key=key)


def sniff(data: bytes) -> str | None:
    """The real content type of these bytes, or None if it is not an image.

    WebP needs the two-part RIFF check; the rest are plain prefixes.
    """
    if not data:
        return None
    for magic, content_type in _MAGIC:
        if data.startswith(magic):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def dimensions(data: bytes) -> tuple[int, int] | None:
    """The real pixel size of these bytes, from the file header. None if unreadable.

    Necessary because the API's own numbers describe something else. Ask
    ``pageimages`` for a 512px thumbnail and it reports ``width: 512`` while
    handing back a URL for the 960px bucket — the dimensions are the scale that
    was *requested*, not the file at that address. Storing those would put a
    number in the record that is simply not true of the image beside it.

    Header parsing rather than Pillow: four formats, forty lines, and no
    dependency for something that never needs to decode a pixel.
    """
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">II", data[16:24])
            return int(width), int(height)
        if data[:3] == b"GIF":
            width, height = struct.unpack("<HH", data[6:10])
            return int(width), int(height)
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return _webp_dimensions(data)
        if data[:2] == b"\xff\xd8":
            return _jpeg_dimensions(data)
    except (struct.error, IndexError, ValueError):
        return None
    return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Walk JPEG segments to the frame header, which is where the size lives."""
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        # Standalone markers carry no length field.
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        # Any SOFn but the arithmetic-coded and hierarchical ones.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return int(width), int(height)
        i += 2 + struct.unpack(">H", data[i + 2 : i + 4])[0]
    return None


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    """VP8, VP8L and VP8X each store the size differently."""
    chunk = data[12:16]
    if chunk == b"VP8 ":
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    return None


class _TagStripper(HTMLParser):
    """`Artist` and `Credit` arrive as HTML fragments with links in them."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def strip_html(raw: str) -> str:
    parser = _TagStripper()
    try:
        parser.feed(raw or "")
        parser.close()
    except Exception:  # malformed markup is not worth failing a build over
        return re.sub(r"<[^>]+>", " ", raw or "").strip()
    return " ".join("".join(parser.parts).split())


def _extmeta(extmetadata: dict, key: str) -> str:
    entry = (extmetadata or {}).get(key)
    if isinstance(entry, dict):
        value = entry.get("value")
        return value if isinstance(value, str) else ""
    return entry if isinstance(entry, str) else ""


# ── the orchestrator ────────────────────────────────────────────────────────


# The planner writes key concepts as syllabus lines, not as searches — "Feature
# engineering and feature stores for production consistency", "ML system design
# lifecycle (data collection through deployment and monitoring)". Handed to a
# full-text search those match almost nothing relevant, and the articles they do
# surface are whatever shares the most words. This is the length past which a
# query stops being a subject and starts being a sentence.
_QUERY_MAX_CHARS = 60


def _as_query(text: str) -> str:
    """Reduce one syllabus line to the subject it is about.

    Drops a parenthetical (which is always an enumeration of examples), then
    keeps the leading clause, then truncates at a word boundary. Deliberately
    crude: this is a search string, and the topic — which is already a subject —
    always runs first and carries the exact-title bonus.
    """
    text = re.sub(r"\s*\([^)]*\)", "", text or "").strip()
    text = re.split(r"[;:,]| — ", text)[0].strip()
    if len(text) > _QUERY_MAX_CHARS:
        text = text[:_QUERY_MAX_CHARS].rsplit(" ", 1)[0]
    return text.strip()


def build_queries(topic: str, key_concepts: list[str], hints: tuple[str, ...] = ()) -> list[str]:
    """The searches to run, topic first.

    ``hints`` are titles of the expert's own validated Wikipedia sources, which
    a re-find has and a first build does not. They are already judged relevant
    to this corpus by the validator, so they come after the topic but before the
    planner's concepts — and unlike the concepts they are already article
    titles, so they are used verbatim.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw, shape in [(topic, False), *[(h, False) for h in hints],
                       *[(c, True) for c in key_concepts[:4]]]:
        text = _as_query(raw) if shape else (raw or "").strip()
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        out.append(text)
    return out[:6]


async def find_picture(
    client: WikimediaClient,
    topic: str,
    key_concepts: list[str] | None = None,
    hints: tuple[str, ...] = (),
    *,
    deadline: float | None = None,
) -> FoundPicture:
    """Search, filter, rank, fetch. Raises :class:`PictureSkipped` if none fits.

    Raising rather than returning ``None`` so the reason travels with the
    failure: the caller turns it straight into the ``picture_skipped`` event,
    and the build log then says *why* an expert has no picture rather than only
    that it has none.

    The whole thing runs under one deadline. Five or six HTTP requests is well
    inside Wikimedia's public limits, but a build must never wait on them.
    """
    timeout = deadline if deadline is not None else settings.PICTURE_TIMEOUT
    try:
        async with asyncio.timeout(timeout):
            return await _find(client, topic, key_concepts or [], hints)
    except TimeoutError:
        raise PictureSkipped("timeout") from None


async def _find(
    client: WikimediaClient,
    topic: str,
    key_concepts: list[str],
    hints: tuple[str, ...],
) -> FoundPicture:
    queries = build_queries(topic, key_concepts, hints)

    # 1–2. Articles: every query's best hit before any query's second.
    #
    # Concatenating instead — running each query and appending until the cap is
    # reached — spends the whole budget on the first two queries, and the later
    # ones never run at all. On a real expert that lost "Organon", whose lead
    # image is a 13th-century manuscript of the Categories, because eight titles
    # had already been collected from "Aristotelian logic" and "On
    # Interpretation"; the picture it settled for was a Susan Sontag dust
    # jacket. Interleaving keeps the topic's own best hit first — which is what
    # the ranking leans on — while guaranteeing every query is represented.
    per_query: list[list[str]] = []
    for query in queries:
        per_query.append(await client.search_articles(query, limit=3))

    titles: list[str] = []
    title_query: dict[str, str] = {}
    for depth in range(3):
        for query, hits in zip(queries, per_query, strict=True):
            if depth >= len(hits):
                continue
            title = hits[depth]
            if title in title_query:
                continue
            title_query[title] = query
            titles.append(title)
    titles = titles[:8]
    if not titles:
        raise PictureSkipped("no_candidate")

    # 3. Lead images and identity, one batched call.
    pages = await client.page_images(titles, thumb_size=settings.PICTURE_THUMB_WIDTH)
    order = {
        title: depth
        for hits in per_query
        for depth, title in enumerate(hits)
        if title in title_query
    }
    candidates: list[Candidate] = []
    for page in pages:
        title = page.get("title", "")
        props = page.get("pageprops") or {}
        if "disambiguation" in props:
            continue
        thumb = page.get("thumbnail") or {}
        original = page.get("original") or {}
        file_name = page.get("pageimage") or ""
        if not thumb.get("source") or not file_name:
            continue  # no free lead image (pilicense=free already refused it)
        ow, oh = int(original.get("width") or 0), int(original.get("height") or 0)
        if ow and oh and min(ow, oh) < _MIN_ORIGINAL_SIDE:
            continue

        # 4. Marks, not pictures — and not pictures of something else.
        if looks_like_a_mark(file_name):
            continue
        if not is_on_topic(title, title_query.get(title, topic), topic):
            continue

        candidates.append(Candidate(
            page_title=title,
            page_url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
            file_name=f"File:{file_name}" if not file_name.startswith("File:") else file_name,
            thumb_url=thumb["source"],
            thumb_width=int(thumb.get("width") or 0),
            thumb_height=int(thumb.get("height") or 0),
            original_width=ow,
            original_height=oh,
            wikibase_item=props.get("wikibase_item"),
            query=title_query.get(title, topic),
            # Position within the query that found it, so a query's best hit
            # competes with every other query's best hit rather than with the
            # interleaving order.
            rank=order.get(title, 99),
        ))

    if not candidates:
        raise PictureSkipped("no_candidate")

    # 5. Living people.
    claims = await client.wikidata_claims(
        [c.wikibase_item for c in candidates if c.wikibase_item]
    )
    candidates = [
        c for c in candidates
        if not (c.wikibase_item and is_living_human(claims.get(c.wikibase_item, {})))
    ]
    if not candidates:
        raise PictureSkipped("no_candidate")

    # 6. Licence and credit.
    infos = await client.image_info(
        [c.file_name for c in candidates], thumb_width=settings.PICTURE_THUMB_WIDTH
    )
    licensed: list[Candidate] = []
    for c in candidates:
        # Through `normalise_title`, because `pageimages` named this file with
        # underscores and `imageinfo` keyed its answer with spaces.
        info = infos.get(normalise_title(c.file_name))
        if not info:
            continue
        extmeta = info.get("extmetadata") or {}
        if not is_free_license(extmeta):
            continue
        # `pageimages` already produced a real `/thumb/.../512px-*` URL, so it
        # is the one to keep. `imageinfo`'s `thumburl` looks equivalent and is
        # not: when MediaWiki cannot scale a file it hands back the *original*
        # under that key, and downloading a 12 MB collage instead of a 60 KB
        # thumbnail is how an expert loses its picture to the size cap.
        thumb_url = c.thumb_url or info.get("thumburl") or ""
        from_pageimages = bool(c.thumb_url)
        licensed.append(Candidate(
            **{
                **c.__dict__,
                "thumb_url": thumb_url,
                "thumb_width": c.thumb_width if from_pageimages else int(info.get("thumbwidth") or 0),
                "thumb_height": c.thumb_height if from_pageimages else int(info.get("thumbheight") or 0),
                "mime": info.get("mime") or "",
                "license": _extmeta(extmeta, "LicenseShortName"),
                "license_url": _extmeta(extmeta, "LicenseUrl") or None,
                "artist": strip_html(_extmeta(extmeta, "Artist")) or None,
                "credit": strip_html(_extmeta(extmeta, "Credit")) or None,
                "file_page_url": info.get("descriptionurl") or "",
            }
        ))

    if not licensed:
        raise PictureSkipped("no_candidate")

    # 7. Rank and pick.
    shortlist = rank(licensed, topic)[:6]
    metadata = [c.as_metadata() for c in shortlist]

    # 8. Fetch and store. The first candidate whose bytes are actually an image
    # under the cap wins; a too-large or broken file falls through to the next
    # rather than losing the expert its picture.
    too_large = False
    for candidate in shortlist:
        data = await client.download(candidate.thumb_url, settings.PICTURE_MAX_BYTES)
        if data is None:
            too_large = True
            continue
        content_type = sniff(data)
        if content_type is None:
            logger.info("Picture %s is not an image despite its type", candidate.thumb_url)
            too_large = True
            continue
        # The bytes are the authority on their own size; the API's numbers are
        # the scale we asked for, which is not the same thing. Fall back to what
        # it reported only when the header is unreadable.
        size = dimensions(data) or (
            candidate.thumb_width or settings.PICTURE_THUMB_WIDTH,
            candidate.thumb_height or settings.PICTURE_THUMB_WIDTH,
        )
        return FoundPicture(
            image=data,
            content_type=content_type,
            width=size[0],
            height=size[1],
            sha256=hashlib.sha256(data).hexdigest(),
            provider="wikipedia",
            file_name=candidate.file_name,
            file_url=candidate.thumb_url,
            file_page_url=candidate.file_page_url or candidate.page_url,
            page_url=candidate.page_url,
            page_title=candidate.page_title,
            artist=candidate.artist,
            license=candidate.license,
            license_url=candidate.license_url,
            query=candidate.query,
            candidates=metadata,
        )

    raise PictureSkipped("too_large" if too_large else "no_candidate")
