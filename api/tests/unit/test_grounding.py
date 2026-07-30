"""Unit tests for the grounding contract helpers — context numbering, citation
parsing, and citation resolution. These are the invariants the product rests on."""

from peritus.chat.grounding import (
    GROUNDING_CONTRACT,
    build_grounded_context,
    build_system_prompt,
    parse_citations,
    parse_cited_indices,
    strip_dangling_citations,
    used_citation_labels,
    used_citations,
)
from peritus.graph.retriever import EnrichedResult
from peritus.search.domain import SearchResult, SourceRef


def _enriched(chunk_id: int, text: str = "some passage text") -> EnrichedResult:
    result = SearchResult(
        chunk_id=chunk_id,
        expert_id=1,
        source_id=chunk_id * 10,
        text=text,
        context_text=None,
        score=0.5,
        source_ref=SourceRef(
            source_id=chunk_id * 10, title=f"Source {chunk_id}",
            source_type="web", quality_score=8.0,
        ),
    )
    return EnrichedResult(result=result)


def test_context_numbers_start_at_one_and_dedupe_chunks():
    enriched = [_enriched(1), _enriched(2), _enriched(1)]  # chunk 1 repeated
    block, passages = build_grounded_context(enriched, max_passages=10)

    assert [p.index for p in passages] == [1, 2]
    assert block.startswith("[1] ")
    assert "[3]" not in block


def test_context_respects_max_passages():
    enriched = [_enriched(i) for i in range(1, 6)]
    _, passages = build_grounded_context(enriched, max_passages=3)
    assert len(passages) == 3


def test_parse_cited_indices_ignores_out_of_range():
    cited = parse_cited_indices("Claim [1]. Another [2][7]. Bogus [999].", num_passages=3)
    assert cited == {1, 2}


def test_parse_citations_reports_out_of_range_markers_separately():
    """Dropping an invented citation from the list is not enough — the caller has
    to know it was there, because the marker is still sitting in the prose."""
    cited, dangling = parse_citations(
        "Claim [1]. Another [2][7]. Bogus [999].", num_passages=3
    )
    assert cited == {1, 2}
    assert dangling == {7, 999}


def test_parse_citations_reports_nothing_dangling_for_a_clean_answer():
    cited, dangling = parse_citations("All good [1][2][3].", num_passages=3)
    assert cited == {1, 2, 3}
    assert dangling == set()


def test_strip_dangling_citations_removes_only_the_invalid_markers():
    out = strip_dangling_citations("Claim [1]. Bogus [42]. Also [2].", num_passages=3)
    assert out == "Claim [1]. Bogus . Also [2]."


def test_strip_dangling_citations_leaves_a_clean_answer_untouched():
    text = "Claim [1] and [2]."
    assert strip_dangling_citations(text, num_passages=2) == text


def test_used_citations_preserve_numbers_and_order():
    _, passages = build_grounded_context([_enriched(1), _enriched(2), _enriched(3)], 10)
    out = used_citations(passages, cited={3, 1})
    assert [c["n"] for c in out] == [1, 3]
    assert all({"n", "label", "source_id"} <= set(c) for c in out)

    labels = used_citation_labels(passages, cited={2})
    assert labels == [passages[1].citation]


def test_system_prompt_puts_contract_before_persona():
    prompt = build_system_prompt("Speak like a pirate.", "naval history")
    assert prompt.startswith(GROUNDING_CONTRACT)
    assert prompt.index(GROUNDING_CONTRACT) < prompt.index("Speak like a pirate.")


def test_system_prompt_falls_back_without_persona():
    prompt = build_system_prompt(None, "naval history")
    assert "naval history" in prompt
