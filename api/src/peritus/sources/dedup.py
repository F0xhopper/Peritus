"""Three de-duplication passes, ordered by how much evidence each one needs.

A bigger corpus that contains the same paper three times is worse than a smaller
one: every duplicate is paid for three times (fetch, validate, contextualise,
embed, graph) and then competes with itself at retrieval, so a question about it
comes back with three near-identical passages instead of three perspectives.

1. **Identity** — before triage, on the identifiers the fetchers now carry. The
   cheapest and most certain: two records with the same DOI are the same work,
   and no amount of string comparison is needed to know it.
2. **URL** — after identity, on a normalised URL. Catches the same page reached
   by two search engines, plus the arXiv ``/abs`` ↔ ``/pdf`` ↔ ar5iv aliases,
   which identity misses only when the id was never parsed.
3. **Content** — after fetching, on a simhash of the text. This is the preprint
   versus published-version case: two records, no shared identifier, the same
   document. It runs on text that already exists, costs about a millisecond per
   source, and needs no model call.

Embeddings are deliberately *not* used for step 3. They cost money, and at this
point in the pipeline the chunk embeddings do not exist yet — computing them
early to de-duplicate would spend on exactly the sources about to be discarded.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from peritus.core.logging import get_logger
from peritus.sources.domain import (
    Identifiers,
    RawSource,
    SourceCandidate,
    SourceType,
)
from peritus.sources.identifiers import arxiv_id_from_url

logger = get_logger(__name__)

# Query parameters that never change what a page *is*. Stripping them turns the
# same article shared through three campaigns into one URL.
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "ref_src",
    "source", "amp", "_ga", "igshid", "spm", "at_medium", "at_campaign",
})

# Fetch-preference order when several records turn out to be one work. The
# winner is the one whose fetcher yields the best full text, because that is the
# only thing that differs between them once identity has established they are
# the same paper.
_MERGE_PREFERENCE: tuple[SourceType, ...] = (
    SourceType.ARXIV,
    SourceType.PUBMED,
    SourceType.OPENALEX,
    SourceType.PDF,
    SourceType.EXA,
    SourceType.WEB,
)

# Simhash over word 5-shingles.
#
# The threshold is calibrated, not conventional. Measured on 40 real documents
# from one corpus — the hard case, since distinct documents on one topic share
# most of their vocabulary — against 780 distinct pairs and 75 same-document
# pairs transformed the way two renderings of one paper actually differ (a
# reference list appended, front matter prepended, OCR noise, 10–25% of
# sentences dropped):
#
#   distance   catches      wrongly merges
#              duplicates   distinct pairs
#        3        9.3%         0.000%       <- the textbook value; useless here
#        8       52.0%         0.000%
#       10       60.0%         0.000%       <- chosen
#       12       72.0%         0.128%
#       16       85.3%         0.128%
#
# At 3 this pass could only catch documents differing by whitespace, which
# identity and URL dedup already catch — which is why it never once fired on a
# live build.
#
# 10 rather than 12+ because the two errors are not symmetric. A missed
# duplicate costs money and some retrieval redundancy, and is visible in the
# ledger. A false merge silently deletes a good source, and nobody ever sees the
# paper that was not kept. So this takes the largest distance with no observed
# false merge and accepts that ~40% of real near-duplicates still get through —
# a simhash over shingles is a blunt instrument for two texts differing by a
# quarter of their sentences, and claiming otherwise would be the wrong kind of
# confidence.
SIMHASH_BITS = 64
SIMHASH_MAX_DISTANCE = 10
_SHINGLE_SIZE = 5
# Below this a text has too few shingles for the hash to mean anything, and two
# short abstracts on one topic collide easily. Short texts fall back to identity
# and URL, which have already run.
_MIN_FINGERPRINT_CHARS = 600

_WORD_RE = re.compile(r"[a-z0-9]+")


# ── URL normalisation ────────────────────────────────────────────────────────

def normalise_url(url: str) -> str:
    """A URL reduced to what identifies the document, for equality only.

    Lowercased host without ``www.``, no fragment, no tracking parameters, no
    trailing slash, and every arXiv spelling of one paper mapped to one key.
    Never use the result as an address — it is a comparison key.
    """
    if not url:
        return ""
    arxiv_id = arxiv_id_from_url(url)
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = (parts.hostname or "").lower().removeprefix("www.")
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    path = (parts.path or "").rstrip("/").lower() or "/"
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS
        )
    )
    return urlunsplit(("", host, path, query, ""))


# ── content fingerprinting ───────────────────────────────────────────────────

def _shingles(text: str) -> list[str]:
    words = _WORD_RE.findall(text.lower())
    if len(words) < _SHINGLE_SIZE:
        return [" ".join(words)] if words else []
    return [
        " ".join(words[i: i + _SHINGLE_SIZE])
        for i in range(len(words) - _SHINGLE_SIZE + 1)
    ]


def simhash(text: str) -> int | None:
    """64-bit simhash over word 5-shingles, or ``None`` for a text too short to hash."""
    if len(text) < _MIN_FINGERPRINT_CHARS:
        return None
    shingles = _shingles(text)
    if not shingles:
        return None
    weights = [0] * SIMHASH_BITS
    mask = (1 << SIMHASH_BITS) - 1
    for shingle in shingles:
        # Python's hash() is salted per process, so it cannot be used: the same
        # corpus must fingerprint the same way in every worker and every run.
        h = _stable_hash(shingle) & mask
        for bit in range(SIMHASH_BITS):
            weights[bit] += 1 if (h >> bit) & 1 else -1
    value = 0
    for bit in range(SIMHASH_BITS):
        if weights[bit] > 0:
            value |= 1 << bit
    return value


def _stable_hash(text: str) -> int:
    """FNV-1a, 64-bit. Deterministic across processes, which ``hash()`` is not."""
    h = 0xCBF29CE484222325
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


# ── the set of everything a build has already considered ─────────────────────

@dataclass
class SeenSet:
    """Everything a build has already fetched, triaged or rejected.

    The discovery loop searches several times, and without this each round
    re-considers the same tail: the same candidates re-triaged, the same pages
    re-fetched, the budget spent on work already done. Membership is checked on
    *any* shared identifier key, not just the canonical one, so a record with a
    DOI matches an earlier record that had the same DOI plus an arXiv id.
    """

    identity_keys: set[str] = field(default_factory=set)
    urls: set[str] = field(default_factory=set)
    fingerprints: list[int] = field(default_factory=list)

    def add_candidate(self, candidate: SourceCandidate) -> None:
        self.identity_keys |= candidate.identifiers.keys()
        if candidate.url:
            self.urls.add(normalise_url(candidate.url))

    def add_source(self, source: RawSource) -> None:
        self.identity_keys |= source.identifiers.keys()
        if source.url:
            self.urls.add(normalise_url(source.url))
        fingerprint = simhash(source.text)
        if fingerprint is not None:
            self.fingerprints.append(fingerprint)

    def add_url(self, url: str) -> None:
        if url:
            self.urls.add(normalise_url(url))

    def has(self, identifiers: Identifiers, url: str) -> bool:
        if identifiers.keys() & self.identity_keys:
            return True
        return bool(url) and normalise_url(url) in self.urls

    def near_duplicate_of(self, text: str) -> bool:
        fingerprint = simhash(text)
        if fingerprint is None:
            return False
        return any(
            hamming(fingerprint, seen) <= SIMHASH_MAX_DISTANCE
            for seen in self.fingerprints
        )

    def __len__(self) -> int:
        return len(self.urls) + len(self.identity_keys)


# ── the passes ───────────────────────────────────────────────────────────────

@dataclass
class DedupReport:
    """What each pass removed. Emitted as the ``dedup_done`` event.

    The audit surface reports "records identified" and "records screened" as
    separate numbers, and the difference between them is only honest if it can
    be broken down into the reasons records disappeared.
    """

    candidates: int = 0
    identity_merged: int = 0
    url_merged: int = 0
    seen_skipped: int = 0
    kept: int = 0

    def as_event(self) -> dict:
        return {
            "candidates": self.candidates,
            "identity_merged": self.identity_merged,
            "url_merged": self.url_merged,
            "seen_skipped": self.seen_skipped,
            "kept": self.kept,
        }


def _preference(candidate: SourceCandidate) -> tuple[int, int]:
    """Sort key deciding which record of a work survives the merge.

    Lower is better. A pubmed record with a PMCID and an openalex record with an
    OA PDF both beat their own type's default, because in both cases the reason
    to prefer that fetcher — free structured full text, an actual PDF — is
    present rather than assumed.
    """
    try:
        rank = _MERGE_PREFERENCE.index(candidate.source_type)
    except ValueError:
        rank = len(_MERGE_PREFERENCE)
    has_text_route = bool(
        candidate.identifiers.pmcid
        or candidate.identifiers.arxiv_id
        or candidate.metadata.get("oa_pdf_url")
    )
    return (rank, 0 if has_text_route else 1)


def deduplicate_candidates(
    candidates: list[SourceCandidate],
    seen: SeenSet | None = None,
) -> tuple[list[SourceCandidate], DedupReport]:
    """Identity then URL, with provenance from the losers folded into the winner.

    Order within the surviving list follows first appearance, so a caller that
    relies on fetcher order (the search phase pools fetchers in a fixed order)
    sees no reshuffling beyond the removals.
    """
    report = DedupReport(candidates=len(candidates))

    # Pass 1: identity. Union-find over shared identifier keys — two records
    # sharing *any* key are the same work, even when their canonical keys differ
    # because one of them carries an extra id.
    by_key: dict[str, int] = {}
    groups: dict[int, list[SourceCandidate]] = {}
    ungrouped: list[SourceCandidate] = []
    next_group = 0

    for candidate in candidates:
        keys = candidate.identifiers.keys()
        if not keys:
            ungrouped.append(candidate)
            continue
        existing = {by_key[k] for k in keys if k in by_key}
        if not existing:
            group = next_group
            next_group += 1
            groups[group] = [candidate]
        else:
            group = min(existing)
            for other in existing - {group}:
                groups[group].extend(groups.pop(other))
                for k, g in list(by_key.items()):
                    if g == other:
                        by_key[k] = group
            groups[group].append(candidate)
        for key in keys:
            by_key[key] = group

    merged_by_identity: dict[int, SourceCandidate] = {
        group: _merge_group(members) for group, members in groups.items()
    }
    report.identity_merged = sum(len(m) - 1 for m in groups.values())

    # Rebuild in first-appearance order.
    emitted: set[int] = set()
    ordered: list[SourceCandidate] = []
    for candidate in candidates:
        keys = candidate.identifiers.keys()
        if not keys:
            continue
        group = by_key[next(iter(keys))]
        if group in emitted:
            continue
        emitted.add(group)
        ordered.append(merged_by_identity[group])
    # Interleaving is not preserved between identified and unidentified records;
    # ranking happens at triage, so relative order here carries no meaning
    # beyond stability.
    ordered.extend(ungrouped)

    # Pass 2: URL, over the identity-merged list.
    kept: list[SourceCandidate] = []
    seen_urls: set[str] = set()
    for candidate in ordered:
        if seen is not None and seen.has(candidate.identifiers, candidate.url):
            report.seen_skipped += 1
            continue
        key = normalise_url(candidate.url)
        if key and key in seen_urls:
            report.url_merged += 1
            continue
        if key:
            seen_urls.add(key)
        kept.append(candidate)

    report.kept = len(kept)
    return kept, report


def _merge_group(members: list[SourceCandidate]) -> SourceCandidate:
    """One record standing for several, keeping every identifier and provenance."""
    if len(members) == 1:
        return members[0]
    winner = min(members, key=_preference)
    identifiers = winner.identifiers
    discovered: list[str] = []
    merged_from: list[str] = []
    for member in members:
        identifiers = identifiers.merge(member.identifiers)
        via = member.metadata.get("discovered_via")
        if isinstance(via, str) and via and via not in discovered:
            discovered.append(via)
        if member is not winner and member.url:
            merged_from.append(member.url)

    metadata = dict(winner.metadata)
    # Anything the losers knew about how to reach full text is worth keeping:
    # the openalex record's OA PDF makes the arXiv record's fallback better.
    for member in members:
        for key in ("oa_pdf_url", "oa_landing_url", "abstract", "cited_by_count"):
            if not metadata.get(key) and member.metadata.get(key):
                metadata[key] = member.metadata[key]
    if merged_from:
        metadata["merged_from"] = merged_from
    if len(discovered) > 1:
        metadata["also_discovered_via"] = discovered[1:]

    winner.identifiers = identifiers
    winner.metadata = metadata
    return winner


def deduplicate_sources_by_content(
    sources: list[RawSource],
    seen: SeenSet | None = None,
) -> tuple[list[RawSource], list[tuple[RawSource, str]]]:
    """Drop fetched sources whose text is a near-duplicate of one already kept.

    Returns ``(kept, [(dropped, duplicate_of_url)])``. The duplicates are
    returned rather than discarded so the ledger can record them as dropped
    *for a stated reason* — a source that silently disappears between fetching
    and validation is exactly the kind of gap the screening flow exists to close.

    The longer text wins: two renderings of one paper differ mainly in how much
    of it survived extraction.
    """
    ranked = sorted(range(len(sources)), key=lambda i: -len(sources[i].text))
    fingerprints: list[tuple[int, RawSource]] = []
    keep: set[int] = set()
    duplicates: list[tuple[RawSource, str]] = []

    for i in ranked:
        source = sources[i]
        fingerprint = simhash(source.text)
        if fingerprint is None:
            keep.add(i)
            continue
        if seen is not None and seen.near_duplicate_of(source.text):
            duplicates.append((source, "a source kept in an earlier round"))
            continue
        match = next(
            (
                other
                for other_fp, other in fingerprints
                if hamming(fingerprint, other_fp) <= SIMHASH_MAX_DISTANCE
            ),
            None,
        )
        if match is not None:
            duplicates.append((source, match.url))
            continue
        fingerprints.append((fingerprint, source))
        keep.add(i)

    kept = [s for i, s in enumerate(sources) if i in keep]
    if duplicates:
        logger.info(
            "Content fingerprinting removed %d near-duplicate source(s) of %d",
            len(duplicates), len(sources),
        )
    return kept, duplicates


def deduplicate_by_url[T: (RawSource, SourceCandidate)](items: Iterable[T]) -> list[T]:
    """URL-only dedup, keeping the first occurrence.

    Retained for the within-fetcher pass, where candidates have not been
    identity-merged yet and a full pass would be wasted work.
    """
    seen: set[str] = set()
    unique: list[T] = []
    for item in items:
        key = normalise_url(item.url)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(item)
    return unique
