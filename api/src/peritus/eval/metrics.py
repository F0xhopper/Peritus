"""Pure, dependency-free evaluation metrics.

Kept side-effect-free so they can be unit-tested in CI without a database, API
keys, or a live expert. The harness in ``runner.py`` wires these to real data.
"""

from __future__ import annotations

from peritus.chat.grounding import parse_cited_indices


def recall_at_k(retrieved_chunk_ids: list[int], gold_chunk_ids: list[int], k: int) -> float:
    """Fraction of the gold supporting chunks present in the top-k retrieved."""
    gold = set(gold_chunk_ids)
    if not gold:
        return 1.0
    topk = set(retrieved_chunk_ids[:k])
    return len(gold & topk) / len(gold)


def citation_validity(answer_text: str, num_passages: int) -> float:
    """Fraction of bracketed citations in the answer that reference a real passage.

    A score below 1.0 means the model cited a number it was never given — i.e. a
    fabricated citation.
    """
    import re

    all_refs = [int(m.group(1)) for m in re.finditer(r"\[(\d{1,3})\]", answer_text)]
    if not all_refs:
        return 0.0  # an uncited answer is not verifiable
    valid = [n for n in all_refs if 1 <= n <= num_passages]
    return len(valid) / len(all_refs)


def cited_supporting_sources(
    answer_text: str,
    passage_source_ids: dict[int, int],
    gold_source_ids: list[int],
) -> float:
    """Did the answer cite passages from the sources that actually support it?

    ``passage_source_ids`` maps passage number → source_id; ``gold_source_ids`` are
    the source ids known to contain the answer. Returns recall over gold sources.
    """
    gold = set(gold_source_ids)
    if not gold:
        return 1.0
    cited = parse_cited_indices(answer_text, max(passage_source_ids, default=0))
    cited_sources = {passage_source_ids[n] for n in cited if n in passage_source_ids}
    return len(gold & cited_sources) / len(gold)


def looks_like_refusal(answer_text: str) -> bool:
    """Heuristic: did the expert decline for lack of evidence?"""
    t = answer_text.lower()
    cues = (
        "don't have enough", "do not have enough", "not enough information",
        "cannot answer", "can't answer", "no information", "isn't covered",
        "is not covered", "passages do not", "passages don't", "insufficient",
        "not addressed in", "outside the scope",
    )
    return any(c in t for c in cues)


def aggregate(scores: list[float]) -> float:
    return round(sum(scores) / len(scores), 4) if scores else 0.0
