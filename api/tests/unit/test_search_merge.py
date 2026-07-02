"""Unit tests for _merge_hits — the pure deduplication helper in SearchService.

It takes the per-subquery hit lists, deduplicates by chunk_id (keeping the best
score), and sorts descending. Pure function, no I/O.
"""

from peritus.search.domain import SearchResult, SourceRef
from peritus.search.service import _merge_hits


def _hit(chunk_id: int, score: float) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        expert_id=1,
        source_id=1,
        text=f"text for chunk {chunk_id}",
        context_text=None,
        score=score,
        source_ref=SourceRef(source_id=1, title="T", source_type="web", quality_score=7.0),
    )


def test_merge_empty():
    assert _merge_hits([]) == []
    assert _merge_hits([[], []]) == []


def test_merge_dedupes_by_chunk_keeping_best_score():
    a = [_hit(1, 0.5), _hit(2, 0.3)]
    b = [_hit(1, 0.8), _hit(3, 0.1)]

    merged = _merge_hits([a, b])

    by_id = {h.chunk_id: h.score for h in merged}
    assert by_id == {1: 0.8, 2: 0.3, 3: 0.1}


def test_merge_sorts_descending_by_score():
    merged = _merge_hits([[_hit(1, 0.2), _hit(2, 0.9)], [_hit(3, 0.5)]])
    assert [h.chunk_id for h in merged] == [2, 3, 1]
