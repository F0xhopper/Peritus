"""Unit tests for _merge_hits — the pure RRF fusion helper in SearchService.

It takes the per-subquery hit lists and fuses them by chunk_id, summing the
per-arm RRF scores, then sorts descending. Pure function, no I/O.
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


def test_merge_sums_scores_across_subqueries():
    a = [_hit(1, 0.5), _hit(2, 0.3)]
    b = [_hit(1, 0.8), _hit(3, 0.1)]

    merged = _merge_hits([a, b])

    by_id = {h.chunk_id: round(h.score, 6) for h in merged}
    assert by_id == {1: 1.3, 2: 0.3, 3: 0.1}


def test_agreement_across_subqueries_outranks_a_single_strong_hit():
    """The point of summing: three subqueries agreeing beats one confident arm."""
    agreed = [[_hit(1, 0.4)], [_hit(1, 0.4)], [_hit(1, 0.4)]]
    lone = [[_hit(2, 0.9)]]

    merged = _merge_hits(agreed + lone)

    assert [h.chunk_id for h in merged] == [1, 2]


def test_merge_sorts_descending_by_score():
    merged = _merge_hits([[_hit(1, 0.2), _hit(2, 0.9)], [_hit(3, 0.5)]])
    assert [h.chunk_id for h in merged] == [2, 3, 1]


def test_merge_does_not_double_count_within_one_subquery():
    """A single arm never returns the same chunk twice; if it did, fusion must
    not silently inflate that chunk above genuinely-agreed ones."""
    merged = _merge_hits([[_hit(1, 0.5)], [_hit(2, 0.4)]])
    assert {h.chunk_id: round(h.score, 6) for h in merged} == {1: 0.5, 2: 0.4}
