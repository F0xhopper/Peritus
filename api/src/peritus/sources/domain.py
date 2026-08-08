from dataclasses import dataclass, field
from enum import StrEnum


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


@dataclass
class RawSource:
    source_type: SourceType
    url: str
    title: str
    author: str | None
    text: str
    metadata: dict = field(default_factory=dict)


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


@dataclass
class DroppedSource:
    raw: RawSource
    quality_score: float
    relevance_score: float
    drop_reason: str
