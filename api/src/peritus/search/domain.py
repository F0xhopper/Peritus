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
        """How a passage is labelled — the source's title, and nothing else.

        It used to read ``Langstroth on the Hive — Exa · Q:8.5``: the fetcher
        that found the source and the screening score it was given. That string
        is the model's label for the passage, the SSE citation, the text in the
        reader's citation popover and the ``aria-label`` a screen reader speaks
        on every marker — so a vendor name and an internal score were being read
        aloud beside every sentence of every answer. The score is still on the
        source row for anyone querying the record; it is not a caption.
        """
        return self.source_ref.title


@dataclass
class SearchResponse:
    query: str
    results: list[SearchResult]
    total: int
    #: Whether ``results[i].score`` is a reranker's relevance score (0–1,
    #: comparable across questions) rather than a fused RRF score (a rank
    #: artefact, not a relevance judgement). Only the former can be held to a
    #: relevance floor.
    reranked: bool = False
