from dataclasses import dataclass, field
from enum import Enum


class SourceType(str, Enum):
    WIKIPEDIA = "wikipedia"
    ARXIV = "arxiv"
    YOUTUBE = "youtube"
    EXA = "exa"
    WEB = "web"
    GUTENBERG = "gutenberg"
    PDF = "pdf"


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
