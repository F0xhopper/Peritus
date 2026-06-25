from dataclasses import dataclass, field


@dataclass
class SourceRef:
    source_id: int
    title: str
    source_type: str
    quality_score: float | None


@dataclass
class SearchResult:
    chunk_id: int
    expert_id: int
    source_id: int
    text: str
    context_text: str | None
    score: float
    source_ref: SourceRef
    sequence_n: int = 0
    chunk_meta: dict = field(default_factory=dict)

    @property
    def citation(self) -> str:
        q = f" · Q:{self.source_ref.quality_score:.1f}" if self.source_ref.quality_score else ""
        return f"{self.source_ref.title} — {self.source_ref.source_type.title()}{q}"


@dataclass
class SearchResponse:
    query: str
    results: list[SearchResult]
    total: int
