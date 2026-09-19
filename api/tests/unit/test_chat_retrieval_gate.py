"""The chat retrieval loop: planner context, relevance gate, relevance floor.

R6/R7/R10 in docs/plans/retrieval-quality.md. No model call and no database:
the planner, search and graph are stubbed at the agent's seams.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from peritus.chat.agent import (
    ChatAgent,
    QueryPlan,
    _conversation_block,
    apply_relevance_floor,
)
from peritus.chat.audit_trail import build_audit_payload
from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier
from peritus.graph.retriever import EnrichedResult
from peritus.search.domain import SearchResponse, SearchResult, SourceRef


def _expert() -> Expert:
    return Expert(
        id=1,
        name="thomism",
        topic="Thomism",
        status=ExpertStatus.READY,
        tier=ExpertTier.STANDARD,
        config=ExpertConfig.from_tier(ExpertTier.STANDARD),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _hit(chunk_id: int, score: float) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        expert_id=1,
        source_id=chunk_id,
        text=f"passage {chunk_id}",
        context_text=None,
        score=score,
        source_ref=SourceRef(
            source_id=chunk_id, title=f"S{chunk_id}", source_type="web", quality_score=7.0
        ),
    )


def _response(scores: dict[int, float], reranked: bool = True) -> SearchResponse:
    hits = [_hit(c, s) for c, s in scores.items()]
    return SearchResponse(query="q", results=hits, total=len(hits), reranked=reranked)


def _agent(plan: QueryPlan, *responses: SearchResponse) -> ChatAgent:
    agent = ChatAgent(MagicMock())
    agent._plan = AsyncMock(return_value=plan)
    agent._search.batch_search = AsyncMock(side_effect=list(responses))
    agent._search.fetch_by_position = AsyncMock(return_value=[])

    async def expand(results, expert_id, hops=1):
        return [EnrichedResult(result=r) for r in results]

    agent._graph.expand = expand
    return agent


_PLAN = QueryPlan(
    subqueries=["ultimate end of man beatitude"],
    fallback_queries=["final cause human nature", "vision of God happiness"],
)


async def test_strong_first_pass_runs_no_second_pass():
    agent = _agent(_PLAN, _response({1: 0.8, 2: 0.6, 3: 0.4, 4: 0.05}))
    ctx = await agent.gather_context(_expert(), "What is the end of man?")

    assert agent._search.batch_search.await_count == 1
    assert ctx.trail.coverage_satisfied is True
    assert ctx.trail.second_pass is False
    # Passage 4 is below the floor and three clear it: kept out of the prompt,
    # but still in the trail as retrieved-and-not-shown.
    assert [p.chunk_id for p in ctx.passages] == [1, 2, 3]
    assert [s.chunk_id for s in ctx.trail.steps] == [1, 2, 3, 4]


async def test_weak_first_pass_searches_the_fallback_queries():
    agent = _agent(
        _PLAN,
        _response({1: 0.5, 2: 0.08, 3: 0.02}),
        _response({7: 0.7, 2: 0.3}),
    )
    ctx = await agent.gather_context(_expert(), "What is the end of man?")

    second = agent._search.batch_search.await_args_list[1].kwargs
    assert second["queries"] == ["final cause human nature", "vision of God happiness"]
    # The primary pass already searched the question verbatim.
    assert second["include_question"] is False
    assert ctx.trail.coverage_satisfied is False
    assert ctx.trail.followup_queries == _PLAN.fallback_queries
    # Chunk 3 stays out. Chunk 2 was below the floor in the first pass (0.08)
    # but cleared it in the follow-up (0.3), so it is numbered where it cleared.
    assert [p.chunk_id for p in ctx.passages] == [1, 7, 2]
    vias = {s.chunk_id: s.via for s in ctx.trail.steps}
    assert vias[7] == "coverage_followup" and vias[1] == "primary"


async def test_unscored_results_are_never_gated_or_floored():
    """No reranker ran: RRF scores say nothing about relevance."""
    agent = _agent(_PLAN, _response({1: 0.03, 2: 0.02, 3: 0.01, 4: 0.01}, reranked=False))
    ctx = await agent.gather_context(_expert(), "What is the end of man?")

    assert agent._search.batch_search.await_count == 1
    assert ctx.trail.coverage_satisfied is None
    assert len(ctx.passages) == 4


async def test_a_follow_up_is_searched_and_reranked_as_the_question_it_stands_for():
    plan = QueryPlan(
        subqueries=["Garrigou-Lagrange on potency"],
        standalone_question="How does Garrigou-Lagrange define potency?",
    )
    agent = _agent(plan, _response({1: 0.9, 2: 0.8, 3: 0.7}))
    history = [
        {"role": "user", "content": "Who were the main twentieth-century Thomists?"},
        {"role": "assistant", "content": "Maritain, Gilson and Garrigou-Lagrange …"},
    ]
    await agent.gather_context(_expert(), "How does the third one define potency?", history)

    assert agent._plan.await_args.args[3] == history
    first = agent._search.batch_search.await_args_list[0].kwargs
    assert first["question"] == "How does Garrigou-Lagrange define potency?"


def test_floor_keeps_the_best_ranked_when_too_few_clear_it():
    enriched = [
        EnrichedResult(result=_hit(c, s)) for c, s in [(1, 0.5), (2, 0.1), (3, 0.09), (4, 0.01)]
    ]
    kept = apply_relevance_floor(enriched, [True] * 4, floor=0.15, min_keep=3)
    assert [e.result.chunk_id for e in kept] == [1, 2, 3]


def test_floor_counts_unique_chunks_toward_the_minimum():
    enriched = [
        EnrichedResult(result=_hit(c, s)) for c, s in [(1, 0.5), (1, 0.4), (2, 0.1), (3, 0.05)]
    ]
    kept = apply_relevance_floor(enriched, [True] * 4, floor=0.15, min_keep=2)
    assert [e.result.chunk_id for e in kept] == [1, 1, 2]


def test_conversation_block_is_the_last_exchange_trimmed():
    history = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "Which Thomists matter most?"},
        {"role": "assistant", "content": [{"type": "text", "text": "word " * 200}]},
    ]
    block = _conversation_block(history)
    assert "old" not in block
    assert block.startswith("User: Which Thomists matter most?\nExpert: word")
    assert len(block) < 500 and block.endswith("…")
    assert _conversation_block([]) == ""


def test_plan_parses_fallbacks_and_standalone_question():
    plan = QueryPlan.from_tool_input(
        {
            "subqueries": ["a b c"],
            "fallback_queries": ["x", " ", "y", "z"],
            "standalone_question": "  What is X?  ",
        },
        "what is it?",
    )
    assert plan.fallback_queries == ["x", "y"]
    assert plan.standalone_question == "What is X?"
    assert QueryPlan.from_tool_input({"subqueries": ["a"]}, "q").standalone_question is None


def test_plan_reads_a_string_of_subqueries_as_queries_not_characters():
    # What the fast model actually returned for "What is the most tangible proof
    # for God…": a string, with its own tool-call markup leaked into it. Iterated,
    # it became 72 one-character subqueries that swamped the real one.
    leaked = '<parameter name="item">cosmological argument proof God existence modern atheism'
    plan = QueryPlan.from_tool_input({"subqueries": leaked, "fallback_queries": leaked}, "q")
    assert plan.subqueries == ["cosmological argument proof God existence modern atheism"]
    assert plan.fallback_queries == plan.subqueries

    several = '<parameter name="item">first mover</parameter><parameter name="item">five ways'
    assert QueryPlan.from_tool_input({"subqueries": several}, "q").subqueries == [
        "first mover",
        "five ways",
    ]


def test_plan_caps_subqueries_and_falls_back_to_the_question():
    many = [f"query {i}" for i in range(9)]
    assert QueryPlan.from_tool_input({"subqueries": many}, "q", 4).subqueries == many[:4]
    assert QueryPlan.from_tool_input({"subqueries": many}, "q", 6).subqueries == many[:6]
    for junk in (None, 7, {"a": 1}, [], [" ", 3], "<parameter>"):
        assert QueryPlan.from_tool_input({"subqueries": junk}, "the question").subqueries == [
            "the question"
        ]


async def test_audit_matches_steps_to_passages_by_chunk_not_position():
    agent = _agent(_PLAN, _response({1: 0.8, 2: 0.05, 3: 0.6, 4: 0.5}))
    ctx = await agent.gather_context(_expert(), "What is the end of man?")

    payload = build_audit_payload(
        trail=ctx.trail,
        passages=ctx.passages,
        cited={2},
        answer_text="…[2]",
        has_contradiction=False,
        graph_ready=True,
    )
    by_chunk = {d["chunk_id"]: d for d in payload["dispositions"]}
    # Chunk 2 ranked second but the floor kept it out, so passage [2] is chunk 3.
    assert by_chunk[2]["n"] is None and by_chunk[2]["disposition"] == "not_in_context"
    assert by_chunk[3]["n"] == 2 and by_chunk[3]["disposition"] == "cited"
