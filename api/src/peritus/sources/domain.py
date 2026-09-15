from dataclasses import dataclass, field, replace
from enum import StrEnum

from peritus.sources.identifiers import (
    normalise_arxiv_id,
    normalise_doi,
    normalise_openalex_id,
    normalise_pmcid,
    normalise_pmid,
)


class SourceType(StrEnum):
    WIKIPEDIA = "wikipedia"
    ARXIV = "arxiv"
    YOUTUBE = "youtube"
    EXA = "exa"
    WEB = "web"
    GUTENBERG = "gutenberg"
    PDF = "pdf"
    REDDIT = "reddit"
    THOUGHT_LEADER = "thought_leader"
    PUBMED = "pubmed"
    OPENALEX = "openalex"
    # Supplied by the expert's owner rather than found by discovery. Kept as its
    # own type so per-type fetch caps, source-type counts, and the catalog can
    # tell hand-picked material from what the pipeline went looking for.
    UPLOAD = "upload"


# Identity precedence. A DOI is the publisher's own permanent name for a work
# and the one identifier every downstream tool (Zotero, Covidence, Crossref)
# agrees on, so it leads. arXiv follows because a preprint often has no DOI at
# all. Semantic Scholar's own id comes last: it is stable but private to one
# vendor, so it identifies a work only when nothing public does.
_KEY_ORDER: tuple[str, ...] = ("doi", "arxiv_id", "pmcid", "pmid", "openalex_id", "s2_id")


@dataclass(frozen=True)
class Identifiers:
    """The names by which two records can be recognised as the same work.

    Constructed through :meth:`build` so every value is normalised on the way
    in — a DOI written ``https://doi.org/10.1234/AB`` and one written
    ``10.1234/ab`` are the same identity, and only normalisation makes them
    compare equal.
    """

    doi: str | None = None          # bare, lowercased, no https://doi.org/
    arxiv_id: str | None = None     # bare, version stripped
    pmid: str | None = None
    pmcid: str | None = None
    openalex_id: str | None = None  # W…
    s2_id: str | None = None        # Semantic Scholar paperId

    @classmethod
    def build(
        cls,
        *,
        doi: str | None = None,
        arxiv_id: str | None = None,
        pmid: str | int | None = None,
        pmcid: str | None = None,
        openalex_id: str | None = None,
        s2_id: str | None = None,
    ) -> "Identifiers":
        return cls(
            doi=normalise_doi(doi),
            arxiv_id=normalise_arxiv_id(arxiv_id),
            pmid=normalise_pmid(pmid),
            pmcid=normalise_pmcid(pmcid),
            openalex_id=normalise_openalex_id(openalex_id),
            s2_id=(s2_id or "").strip() or None if isinstance(s2_id, str) else None,
        )

    def canonical_key(self) -> str | None:
        """The single key this work de-duplicates on, or ``None`` if unidentified.

        Prefixed with the scheme so a PMID and an OpenAlex id that happen to
        share digits can never collide.
        """
        for name in _KEY_ORDER:
            value = getattr(self, name)
            if value:
                return f"{name}:{value}"
        return None

    def keys(self) -> set[str]:
        """*Every* scheme-qualified key this record answers to.

        Identity is not transitive through ``canonical_key`` alone: a record
        with only a DOI and a record with a DOI *and* an arXiv id share the DOI
        but not the canonical key of the second. Matching on any shared key is
        what actually merges them.
        """
        return {
            f"{name}:{value}"
            for name in _KEY_ORDER
            if (value := getattr(self, name))
        }

    def merge(self, other: "Identifiers") -> "Identifiers":
        """Union of two records' identifiers; this record's values win on conflict."""
        return Identifiers(
            **{
                name: getattr(self, name) or getattr(other, name)
                for name in _KEY_ORDER
            }
        )

    def is_empty(self) -> bool:
        return not any(getattr(self, name) for name in _KEY_ORDER)

    def to_dict(self) -> dict[str, str]:
        """JSON-ready, dropping the absent schemes rather than writing nulls."""
        return {
            name: value
            for name in _KEY_ORDER
            if (value := getattr(self, name))
        }

    @classmethod
    def from_metadata(cls, metadata: dict | None) -> "Identifiers":
        """Identifiers spelled the way the fetchers' ``metadata`` dicts spell them.

        ``metadata`` predates the typed field and every fetcher still fills it,
        so reading it as a fallback means a candidate constructed by hand — by a
        test, by a caller outside the search path — still resolves to full text
        instead of silently degrading to its abstract.
        """
        if not isinstance(metadata, dict):
            return cls()
        return cls.build(
            doi=metadata.get("doi"),
            arxiv_id=metadata.get("arxiv_id"),
            pmid=metadata.get("pmid"),
            pmcid=metadata.get("pmcid"),
            openalex_id=metadata.get("openalex_id"),
            s2_id=metadata.get("semantic_scholar_id") or metadata.get("s2_id"),
        )

    @classmethod
    def from_dict(cls, data: dict | None) -> "Identifiers":
        if not isinstance(data, dict):
            return cls()
        return cls.build(**{k: v for k, v in data.items() if k in _KEY_ORDER})

    def with_(self, **updates) -> "Identifiers":
        """A copy with some fields replaced, re-normalised."""
        merged = {**self.to_dict(), **updates}
        return Identifiers.build(**merged)


@dataclass
class SourceCandidate:
    """A search hit that has not been fully fetched yet.

    Discovery is two-phase: fetchers first return cheap candidates (metadata +
    snippet), triage ranks them against the research brief, and only the winners
    pay the full download/OCR cost via the fetcher's fetch(candidate).
    """

    source_type: SourceType
    url: str
    title: str
    author: str | None
    snippet: str
    metadata: dict = field(default_factory=dict)
    # Typed identity. ``metadata`` still carries per-fetcher copies of the same
    # values for the code that reads them by name; this is the field dedup, the
    # full-text resolver and snowballing key on.
    identifiers: Identifiers = field(default_factory=Identifiers)


@dataclass
class RawSource:
    source_type: SourceType
    url: str
    title: str
    author: str | None
    text: str
    metadata: dict = field(default_factory=dict)
    identifiers: Identifiers = field(default_factory=Identifiers)


# How deeply a source treats a key concept (docs/plans/syllabus.md, 4.A), graded
# by the validator and counted by coverage: sets_out and treats count toward a
# concept's target, a passing mention never does.
DEPTH_SETS_OUT = "sets_out"
DEPTH_TREATS = "treats"
DEPTH_MENTIONS = "mentions"
DEPTHS: tuple[str, ...] = (DEPTH_SETS_OUT, DEPTH_TREATS, DEPTH_MENTIONS)
COUNTING_DEPTHS: frozenset[str] = frozenset({DEPTH_SETS_OUT, DEPTH_TREATS})

# The status of a concept's named primary text (4.C). Written by the resolver's
# outcome, read by coverage's "has primary" gate.
NAMED_FOUND = "found"
NAMED_PARTIAL = "partial"
NAMED_MISSING = "missing"
NAMED_NONE = "none_named"

# A named figure whose own writing reached the corpus (3.E).
FIGURE_OWN_VOICE = "own_voice"
FIGURE_ABOUT_ONLY = "about_only"


@dataclass
class ValidatedSource:
    raw: RawSource
    quality_score: float
    relevance_score: float
    content_type: str
    difficulty: int
    key_claims: list[str]
    covered_concepts: list[str] = field(default_factory=list)
    # primary | secondary | tertiary — how close this source sits to the subject
    # itself, orthogonal to how good it is. ``None`` when the validator failed or
    # returned something outside the rubric; never silently treated as a tier.
    source_tier: str | None = None
    # Which model's verdict this row records. Written by the validator rather
    # than read from settings at persist time: with a second-opinion pass, two
    # different models judge different sources in the same build, and a column
    # filled in from configuration would attribute both to whichever model the
    # config happened to name.
    validator_model: str | None = None
    # Set only when the borderline-band reviewer overrode a first pass, so the
    # ledger can show that a decision was re-examined and what it said before.
    review_model: str | None = None
    first_pass_quality: float | None = None
    first_pass_relevance: float | None = None
    # full | partial | abstract — how much of the work the text actually is.
    # ``None`` for a source built by hand, which is treated as counting. See
    # :func:`peritus.sources.substance.substance_of`.
    substance: str | None = None
    # How deeply this source treats each key concept it was tagged with:
    # sets_out | treats | mentions (docs/plans/syllabus.md, 4.A).
    # ``covered_concepts`` is the names at ``treats`` or deeper. Empty for a
    # source validated before graded tags, whose tags coverage reads as ``treats``.
    concept_depths: dict[str, str] = field(default_factory=dict)

    @property
    def source_type(self) -> SourceType:
        return self.raw.source_type

    @property
    def url(self) -> str:
        return self.raw.url

    @property
    def title(self) -> str:
        return self.raw.title

    @property
    def author(self) -> str | None:
        return self.raw.author

    @property
    def text(self) -> str:
        return self.raw.text

    @property
    def identifiers(self) -> Identifiers:
        return self.raw.identifiers


@dataclass
class DroppedSource:
    raw: RawSource
    quality_score: float
    relevance_score: float
    drop_reason: str
    validator_model: str | None = None
    review_model: str | None = None
    first_pass_quality: float | None = None
    first_pass_relevance: float | None = None

    @property
    def url(self) -> str:
        return self.raw.url

    @property
    def identifiers(self) -> Identifiers:
        return self.raw.identifiers


def with_identifiers[T: (RawSource, SourceCandidate)](item: T, ids: Identifiers) -> T:
    """A copy of a candidate/source carrying merged identifiers."""
    return replace(item, identifiers=item.identifiers.merge(ids))


def resolved_identifiers[T: (RawSource, SourceCandidate)](item: T) -> Identifiers:
    """The typed identifiers, backfilled from ``metadata`` where they are absent."""
    return item.identifiers.merge(Identifiers.from_metadata(item.metadata))
