from dataclasses import dataclass, field

from peritus.search.labels import citation_label


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
        """How a passage is labelled: the work, and where in it the passage sits.

        It used to read ``Langstroth on the Hive — Exa · Q:8.5``: the fetcher
        that found the source and the screening score it was given. That string
        is the model's label for the passage, the SSE citation, the text in the
        reader's citation popover and the ``aria-label`` a screen reader speaks
        on every marker — so a vendor name and an internal score were being read
        aloud beside every sentence of every answer. Then it was the bare title,
        which says which book and not where in it. See ``search/labels.py``.
        """
        return citation_label(self.source_ref.title, self.chunk_meta)


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
    #: Which reranker scored ``results`` ("cohere", "llm_window", "none").
    reranker: str | None = None
    #: Every candidate the reranker scored, best first, with its score —
    #: ``results`` is the first ``top_k`` of these. What a subquery with no
    #: passage in ``results`` draws its guaranteed seats from.
    candidates: list[SearchResult] = field(default_factory=list)
    #: Each searched query's own hits, chunk ids in that query's fused order.
    #: Fusion and a single rerank against the whole question can hand every
    #: seat to one part of a two-part question; this is what lets the caller
    #: see which part got nothing.
    per_query: dict[str, list[int]] = field(default_factory=dict)
    #: Each searched query's embedding, so a caller routing the same question
    #: through another index (section summaries) need not embed it twice.
    query_embeddings: dict[str, list[float]] = field(default_factory=dict)
