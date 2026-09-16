"""Normalisation for the identifiers that say two records are the same work.

Every scholarly fetcher already receives identifiers — a DOI from Europe PMC, an
arXiv id from the arXiv API, ``externalIds`` from Semantic Scholar — and until
now each stored them in its own free-form ``metadata`` shape, or discarded them.
The consequence was that the same paper arriving as an arXiv preprint, a journal
DOI and a Semantic Scholar OA PDF looked like three different sources: three
fetches, three validations, three contextualisation passes, three sets of chunks
competing with each other at retrieval time.

Everything here is pure and total. An unparseable input returns ``None`` rather
than raising: these run over strings that came off arbitrary web pages, and an
identifier that cannot be read is simply an absence of evidence.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

# A DOI is "10." + a registrant code + "/" + an opaque suffix. The suffix may
# contain almost anything, so the pattern is deliberately permissive on the
# right-hand side and strict on the prefix, which is the part that identifies it
# as a DOI at all.
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)

# Trailing punctuation that comes from prose or markup rather than the DOI.
_DOI_TRAILING = ".,;:)]}>\"'"

# Both arXiv id schemes: the modern NNNN.NNNNN(vN) and the pre-2007
# archive/YYMMNNN form (e.g. math.GT/0309136).
_ARXIV_NEW = r"\d{4}\.\d{4,5}"
_ARXIV_OLD = r"[a-z-]+(?:\.[A-Z]{2})?/\d{7}"
_ARXIV_ID_RE = re.compile(rf"^(?:arxiv:)?({_ARXIV_NEW}|{_ARXIV_OLD})(v\d+)?$", re.IGNORECASE)
_ARXIV_URL_RE = re.compile(rf"/(?:abs|pdf|html)/({_ARXIV_NEW}|{_ARXIV_OLD})(v\d+)?", re.IGNORECASE)

_PMCID_RE = re.compile(r"^PMC\d+$", re.IGNORECASE)
_DIGITS_RE = re.compile(r"^\d+$")
# OpenAlex work ids are "W" + digits, usually shipped as a full URL.
_OPENALEX_RE = re.compile(r"(W\d+)\s*$", re.IGNORECASE)

# Hosts whose paths carry an arXiv id in the same shape arxiv.org uses.
_ARXIV_HOSTS = ("arxiv.org", "ar5iv.labs.arxiv.org", "ar5iv.org", "browse.arxiv.org")


def normalise_doi(raw: str | None) -> str | None:
    """A bare, lowercased DOI — no scheme, no ``doi.org``, no trailing prose.

    DOIs are case-insensitive by specification, so lowercasing is the canonical
    form and is what makes two spellings of one DOI compare equal.
    """
    if not raw or not isinstance(raw, str):
        return None
    text = unquote(raw.strip())
    match = _DOI_RE.search(text)
    if not match:
        return None
    doi = match.group(1).rstrip(_DOI_TRAILING)
    return doi.lower() or None


def normalise_arxiv_id(raw: str | None) -> str | None:
    """A bare arXiv id with any version suffix stripped.

    Version is dropped deliberately: v1 and v3 of a preprint are the same work,
    and keeping both would defeat the point of having an identity at all.
    """
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if "/" in text and ("arxiv.org" in text.lower() or text.lower().startswith("http")):
        return arxiv_id_from_url(text)
    match = _ARXIV_ID_RE.match(text)
    if not match:
        return None
    return match.group(1).lower()


def normalise_pmid(raw: str | int | None) -> str | None:
    """A bare PubMed id — digits only."""
    if raw is None:
        return None
    text = str(raw).strip().upper().removeprefix("PMID:").strip()
    return text if _DIGITS_RE.match(text) else None


def normalise_pmcid(raw: str | None) -> str | None:
    """A PubMed Central id in its canonical ``PMC…`` spelling."""
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip().upper().removeprefix("PMCID:").strip()
    if _DIGITS_RE.match(text):
        text = f"PMC{text}"
    return text if _PMCID_RE.match(text) else None


def normalise_openalex_id(raw: str | None) -> str | None:
    """The bare ``W…`` work id; OpenAlex ships it as ``https://openalex.org/W…``."""
    if not raw or not isinstance(raw, str):
        return None
    match = _OPENALEX_RE.search(raw.strip())
    return match.group(1).upper() if match else None


def doi_from_url(url: str | None) -> str | None:
    """A DOI carried in a URL — ``doi.org/10.…`` or a publisher path containing one.

    Exa and the web fetcher land on doi.org and publisher URLs constantly and
    carry no identifiers of their own, so this is where most of their identity
    comes from.
    """
    if not url or not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    # Only trust an in-path DOI from a resolver or a publisher path segment that
    # announces itself; a bare "10.1234/x" appearing inside a query string is
    # usually a tracking parameter, not the work's identity.
    if host.endswith("doi.org") or "/doi/" in parts.path.lower():
        return normalise_doi(unquote(parts.path))
    return None


def arxiv_id_from_url(url: str | None) -> str | None:
    """An arXiv id carried in an arxiv.org or ar5iv URL."""
    if not url or not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url if "//" in url else f"//{url}")
    except ValueError:
        return None
    host = (parts.hostname or "").lower().removeprefix("www.")
    if not any(host == h or host.endswith(f".{h}") for h in _ARXIV_HOSTS):
        return None
    path = parts.path
    match = _ARXIV_URL_RE.search(path)
    if match:
        return match.group(1).lower()
    # ar5iv serves /html/<id> and also bare /<id>.
    tail = path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".pdf")
    return normalise_arxiv_id(tail)


def identifiers_from_url(url: str | None) -> tuple[str | None, str | None]:
    """``(doi, arxiv_id)`` derivable from a URL alone. Both may be ``None``."""
    return doi_from_url(url), arxiv_id_from_url(url)
