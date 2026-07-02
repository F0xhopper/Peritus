"""Unit tests for the pure evaluation metrics and citation parsing."""

from peritus.chat.grounding import Passage, parse_cited_indices, used_citation_labels
from peritus.eval import metrics


def _passage(i: int, source_id: int = 0) -> Passage:
    return Passage(index=i, citation=f"Src {i}", source_id=source_id, text=f"text {i}")


def test_parse_cited_indices_only_valid():
    text = "Claim one [1]. Claim two [3][5]. Bogus [99]."
    assert parse_cited_indices(text, num_passages=5) == {1, 3, 5}


def test_used_citation_labels_filters_to_cited():
    passages = [_passage(1), _passage(2), _passage(3)]
    labels = used_citation_labels(passages, cited={1, 3})
    assert labels == ["Src 1", "Src 3"]


def test_recall_at_k():
    assert metrics.recall_at_k([5, 9, 2, 7], gold_chunk_ids=[2, 7], k=4) == 1.0
    assert metrics.recall_at_k([5, 9, 2, 7], gold_chunk_ids=[2, 7], k=2) == 0.0
    assert metrics.recall_at_k([5, 2], gold_chunk_ids=[2, 7], k=2) == 0.5
    assert metrics.recall_at_k([], gold_chunk_ids=[], k=5) == 1.0


def test_citation_validity():
    assert metrics.citation_validity("Grounded [1] and [2].", num_passages=2) == 1.0
    assert metrics.citation_validity("Half [1] bad [9].", num_passages=2) == 0.5
    assert metrics.citation_validity("No citations here.", num_passages=2) == 0.0


def test_cited_supporting_sources():
    text = "Answer [1] and [2]."
    passage_source_ids = {1: 12, 2: 99}
    # gold source 12 is cited (via passage 1); recall = 1.0
    assert metrics.cited_supporting_sources(text, passage_source_ids, [12]) == 1.0
    # gold source 50 is never cited; recall = 0.0
    assert metrics.cited_supporting_sources(text, passage_source_ids, [50]) == 0.0


def test_looks_like_refusal():
    assert metrics.looks_like_refusal("The passages do not cover this topic.")
    assert metrics.looks_like_refusal("I don't have enough information to answer.")
    assert not metrics.looks_like_refusal("The dichotomy of control [1] means...")


def test_aggregate():
    assert metrics.aggregate([1.0, 0.0, 0.5]) == 0.5
    assert metrics.aggregate([]) == 0.0
