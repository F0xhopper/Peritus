"""What the validator actually sees when it judges a source.

The old preview was three 800-character windows cut at fixed offsets from the
raw text, and nothing else. That asks a model to infer, from an arbitrary slice
of prose, facts the pipeline already knows for certain: whether this is a
120,000-character paper or a 2,000-character blog post, whether its text is a
structured full text or an abstract, whether it has a reference list, what year
it is from, and how it was found. Those are the facts a reviewer reads first,
and a model asked to guess them guesses badly.

So a preview here is a **record**, not a slice: known facts stated as facts, the
document's own section headings as evidence of its shape, and body samples
chosen to avoid the front matter and the bibliography — the two regions that
look identical across every paper and tell you nothing about this one.

Everything is pure and bounded. ``build_preview`` fits in
:data:`PREVIEW_MAX_CHARS` for the first pass; ``build_review_preview`` gets the
larger budget the borderline band deserves.
"""

from __future__ import annotations

import re

from peritus.ingestion.chunker import _detect_sections
from peritus.sources.domain import RawSource
from peritus.sources.fulltext import default_method_for

# First pass, one call per batch of five on the fast model. The old budget was
# ~2,400 characters of body; this is the same order of magnitude with the facts
# added, so a batch still fits comfortably.
PREVIEW_MAX_CHARS = 3_500
# Second opinion, one call per source on the strong model.
REVIEW_PREVIEW_MAX_CHARS = 12_000

_SAMPLE_CHARS = 700
_REVIEW_SAMPLE_CHARS = 2_200
MAX_HEADINGS = 12

# Where a reference list starts. Sampling inside one wastes the window on
# citation strings that are the same in every paper in the field.
_REFERENCES_RE = re.compile(
    r"^\s{0,4}(references|bibliography|works cited|literature cited|notes and references)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_WS_RE = re.compile(r"\n{3,}")


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else f"{text[:limit].rstrip()}…"


def references_offset(text: str) -> int | None:
    """Character offset where the reference list begins, or ``None``.

    Only a match in the last third counts: papers cite "references" in their
    own prose, and a false positive here would throw away most of the body.
    """
    best: int | None = None
    floor = int(len(text) * 0.6)
    for match in _REFERENCES_RE.finditer(text):
        if match.start() >= floor:
            best = match.start()
            break
    return best


def _body_span(text: str) -> tuple[int, int]:
    """The region worth sampling: after the head, before the reference list."""
    end = references_offset(text) or len(text)
    return 0, end


def _headings(text: str, limit: int = MAX_HEADINGS) -> list[str]:
    """The document's own section headings, as the chunker detects them.

    ``_detect_sections`` was written for chunk boundaries and never used for
    anything else, though the shape of a document — Methods, Results, Discussion
    versus a single "Full Text" — is one of the strongest cheap signals of what
    it is.
    """
    try:
        sections = _detect_sections(text)
    except Exception:
        return []
    headings = [_clip(title, 80) for title, _body in sections if title and title != "Full Text"]
    # De-duplicated preserving order: numbered subsections repeat their parent's
    # words often enough that a raw list is mostly noise.
    seen: set[str] = set()
    unique: list[str] = []
    for heading in headings:
        key = heading.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(heading)
    return unique[:limit]


def _samples(text: str, count: int, width: int) -> list[str]:
    """``count`` evenly-spread windows from the body, skipping head and references."""
    start, end = _body_span(text)
    span = end - start
    if span <= 0:
        return []
    if span <= width * count:
        return [_WS_RE.sub("\n\n", text[start:end]).strip()]
    # Spread the windows over the middle of the body: the first tenth is title
    # pages and abstracts (already stated above), and the last tenth of a
    # reference-free body is usually acknowledgements.
    usable_start = start + span // 10
    usable_end = end - span // 10
    step = (usable_end - usable_start - width) // max(1, count - 1) if count > 1 else 0
    out: list[str] = []
    for i in range(count):
        at = usable_start + step * i
        window = text[at : at + width]
        # Start at a sentence boundary where one is close, so the sample does not
        # open mid-word.
        break_at = window.find(". ")
        if 0 <= break_at < width // 5:
            window = window[break_at + 2 :]
        out.append(_WS_RE.sub("\n\n", window).strip())
    return [w for w in out if w]


def _facts(raw: RawSource) -> list[tuple[str, str]]:
    """Everything the pipeline already knows, stated rather than inferred."""
    meta = raw.metadata or {}
    ids = raw.identifiers
    facts: list[tuple[str, str]] = [("Type", raw.source_type.value)]
    if raw.author:
        facts.append(("Author", _clip(raw.author, 200)))
    year = meta.get("year") or meta.get("published")
    if year:
        facts.append(("Year", _clip(str(year), 40)))
    venue = meta.get("venue") or meta.get("journal")
    if venue:
        facts.append(("Venue", _clip(str(venue), 120)))
    citations = meta.get("cited_by_count", meta.get("citations"))
    if isinstance(citations, int):
        facts.append(("Times cited", str(citations)))
    if ids.doi:
        facts.append(("DOI", ids.doi))
    if ids.arxiv_id:
        facts.append(("arXiv", ids.arxiv_id))
    facts.append(("Text length", f"{len(raw.text):,} characters"))
    # Never guess this. The old fallback read `abstract` for anything without a
    # `full_text` flag, which told the model that a 72,000-character article was
    # an abstract — a claim about depth, made to the one caller judging depth.
    method = meta.get("full_text_method") or default_method_for(raw.source_type.value)
    if not method:
        method = "full text" if meta.get("full_text") else "not recorded"
    facts.append(("Text obtained by", str(method)))
    refs_at = references_offset(raw.text)
    if refs_at is not None:
        facts.append(("Reference list", f"yes, ~{len(raw.text) - refs_at:,} characters"))
    else:
        facts.append(("Reference list", "not detected"))
    via = meta.get("discovered_via")
    if via:
        facts.append(("Found via", _clip(str(via), 80)))
    leader = meta.get("leader")
    if leader:
        facts.append(("Expected author", _clip(str(leader), 120)))
    return facts


def _abstract(raw: RawSource, limit: int) -> str:
    meta = raw.metadata or {}
    for key in ("abstract", "summary"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return _clip(value, limit)
    return ""


def _render(
    raw: RawSource,
    *,
    abstract_chars: int,
    sample_count: int,
    sample_width: int,
    budget: int,
) -> str:
    parts: list[str] = [
        f"Title: {_clip(raw.title, 300)}",
        *(f"{label}: {value}" for label, value in _facts(raw)),
    ]

    abstract = _abstract(raw, abstract_chars)
    if abstract:
        parts.append(f"\nAbstract / summary:\n{abstract}")

    headings = _headings(raw.text)
    if headings:
        parts.append("\nSection headings: " + " · ".join(headings))

    samples = _samples(raw.text, sample_count, sample_width)
    for i, sample in enumerate(samples, start=1):
        label = "Body sample" if len(samples) == 1 else f"Body sample {i}/{len(samples)}"
        parts.append(f"\n{label}:\n{sample}")

    rendered = "\n".join(parts)
    return rendered if len(rendered) <= budget else f"{rendered[:budget].rstrip()}\n[…truncated]"


def build_preview(raw: RawSource) -> str:
    """First-pass preview: the facts, the shape, and two body windows."""
    return _render(
        raw,
        abstract_chars=1_200,
        sample_count=2,
        sample_width=_SAMPLE_CHARS,
        budget=PREVIEW_MAX_CHARS,
    )


def build_review_preview(raw: RawSource) -> str:
    """Second-opinion preview: the same record with four larger windows.

    Only borderline sources reach this, one per call on the strong model, so it
    can afford to show most of a short paper and a real cross-section of a long
    one — which is the whole reason to ask again.
    """
    return _render(
        raw,
        abstract_chars=3_000,
        sample_count=4,
        sample_width=_REVIEW_SAMPLE_CHARS,
        budget=REVIEW_PREVIEW_MAX_CHARS,
    )
