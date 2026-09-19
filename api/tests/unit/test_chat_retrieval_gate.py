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
    build_user_message,
    evidence_strength,
    relevance_threshold,
    retrieval_is_weak,
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
        text=f"This is passage {chunk_id}, and it is written as prose.",
        context_text=None,
        score=score,
        source_ref=SourceRef(
            source_id=chunk_id, title=f"S{chunk_id}", source_type="web", quality_score=7.0
        ),
    )


def _response(
    scores: dict[int, float],
    reranked: bool = True,
    per_query: dict[str, list[int]] | None = None,
    extra: dict[int, float] | None = None,
) -> SearchResponse:
    """``scores`` are the returned results; ``extra`` further scored candidates."""
    hits = [_hit(c, s) for c, s in scores.items()]
    more = [_hit(c, s) for c, s in (extra or {}).items()]
    return SearchResponse(
        query="q",
        results=hits,
        total=len(hits),
        reranked=reranked,
        reranker="cohere" if reranked else "none",
        candidates=sorted(hits + more, key=lambda r: r.score, reverse=True),
        per_query=per_query or {},
    )


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


_STRONG = {1: 0.8, 2: 0.7, 3: 0.6, 4: 0.5, 5: 0.45, 6: 0.3, 7: 0.2, 8: 0.1, 9: 0.05, 10: 0.02}


async def test_strong_first_pass_runs_no_second_pass():
    agent = _agent(_PLAN, _response(_STRONG))
    ctx = await agent.gather_context(_expert(), "What is the end of man?")

    assert agent._search.batch_search.await_count == 1
    assert ctx.trail.coverage_satisfied is True
    assert ctx.trail.second_pass is False
    assert ctx.trail.reranker == "cohere"
    # Five clear 0.5 × 0.8; STANDARD keeps at least 15 // 2 = 7, so the two
    # best of the rest make it up. 8–10 stay out of the prompt but in the trail.
    assert [p.chunk_id for p in ctx.passages] == [1, 2, 3, 4, 5, 6, 7]
    assert [s.chunk_id for s in ctx.trail.steps] == list(range(1, 11))
    assert ctx.evidence == "strong"


async def test_weak_first_pass_searches_the_fallback_queries():
    agent = _agent(
        _PLAN,
        _response({1: 0.2, 2: 0.18, 3: 0.02}),
        _response({7: 0.7, 2: 0.3}),
    )
    ctx = await agent.gather_context(_expert(), "What is the end of man?")

    second = agent._search.batch_search.await_args_list[1].kwargs
    assert second["queries"] == ["final cause human nature", "vision of God happiness"]
    # The primary pass already searched the question verbatim.
    assert second["include_question"] is False
    assert second["topic"] == "Thomism"
    assert ctx.trail.coverage_satisfied is False
    assert ctx.trail.followup_queries == _PLAN.fallback_queries
    vias = {s.chunk_id: s.via for s in ctx.trail.steps}
    assert vias[7] == "coverage_followup" and vias[1] == "primary"
    # Nothing is dropped: fewer than the tier's minimum were found.
    assert {p.chunk_id for p in ctx.passages} == {1, 2, 3, 7}


async def test_a_weak_best_score_is_weak_even_with_many_passages():
    scores = {i: 0.22 - i * 0.001 for i in range(1, 11)}
    agent = _agent(_PLAN, _response(scores), _response({}))
    ctx = await agent.gather_context(_expert(), "q")
    assert ctx.trail.coverage_satisfied is False
    assert agent._search.batch_search.await_count == 2


async def test_the_floor_is_relative_to_the_question():
    """The king question: every passage relevant, the best only 0.156.

    An absolute 0.15 floor kept three annals and dropped Alfred; relative to
    the best passage, the 0.08–0.10 passages are near the top and stay.
    """
    scores = {1: 0.156, 2: 0.10, 3: 0.09, 4: 0.085, 5: 0.08, 6: 0.02, 7: 0.01}
    agent = _agent(_PLAN, _response(scores), _response({}))
    ctx = await agent.gather_context(_expert(), "Who was the most impactful king?")
    assert [p.chunk_id for p in ctx.passages][:5] == [1, 2, 3, 4, 5]
    assert ctx.evidence == "thin"


async def test_a_subquery_that_won_nothing_gets_a_seat_of_its_own():
    plan = QueryPlan(
        subqueries=["divine simplicity no composition", "objection to divine simplicity"],
        fallback_queries=["x"],
    )
    first = dict(_STRONG)
    # The objection subquery's own hits (50, 51, 52) scored under everything
    # the simplicity half found, and none reached the returned results.
    resp = _response(
        first,
        per_query={
            "divine simplicity no composition": [1, 2, 3, 4, 5],
            "objection to divine simplicity": [50, 51, 52],
        },
        extra={50: 0.04, 51: 0.03, 52: 0.01},
    )
    agent = _agent(plan, resp)
    ctx = await agent.gather_context(_expert(), "Why is God simple, and the objection?")

    ids = [p.chunk_id for p in ctx.passages]
    assert 50 in ids and 51 in ids and 52 not in ids
    vias = {s.chunk_id: s.via for s in ctx.trail.steps}
    assert vias[50] == "subquery_seat"
    # The part of the question the evidence reaches only through a seat.
    assert ctx.evidence == "partial"


async def test_a_subquery_with_a_leading_hit_in_context_gets_no_seat():
    plan = QueryPlan(subqueries=["a", "b"], fallback_queries=["x"])
    resp = _response(
        _STRONG,
        per_query={"a": [1, 2], "b": [60, 3, 61]},
        extra={60: 0.04, 61: 0.03},
    )
    ctx = await _agent(plan, resp).gather_context(_expert(), "q")
    assert 60 not in [p.chunk_id for p in ctx.passages]


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


def test_threshold_is_half_the_best_score_and_never_under_the_floor():
    assert relevance_threshold([0.8, 0.3]) == 0.4
    assert relevance_threshold([0.05, 0.01]) == 0.04
    assert relevance_threshold([]) == 0.04


def test_weak_retrieval_is_a_low_best_or_too_few_near_it():
    assert retrieval_is_weak([0.24] * 10)
    assert retrieval_is_weak([0.9, 0.1, 0.1, 0.1, 0.1, 0.1])
    assert not retrieval_is_weak([0.9, 0.8, 0.7, 0.6, 0.5])
    assert retrieval_is_weak([])


def test_evidence_strength():
    assert evidence_strength([0.14, 0.1, 0.09]) == "thin"
    assert evidence_strength([0.28, 0.27, 0.24, 0.16]) == "partial"
    assert evidence_strength([0.8, 0.7]) == "partial"
    assert evidence_strength([0.8, 0.7, 0.6, 0.2]) == "strong"
    assert evidence_strength([0.8, 0.7, 0.6], part_uncovered=True) == "partial"


def test_evidence_note_lands_in_the_turn_message_only_when_not_strong():
    strong = build_user_message("q", "[1] x", evidence="strong")["content"]
    thin = build_user_message("q", "[1] x", evidence="thin")["content"]
    assert "Evidence:" not in strong
    assert "Evidence: thin" in thin and thin.index("Evidence: thin") < thin.index("Question: q")


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
    # Chunk 2 ranked second and scored last: under the floor and the minimum.
    scores = {1: 0.8, 2: 0.001, 3: 0.7, 4: 0.6, 5: 0.5, 6: 0.45, 7: 0.3, 8: 0.2, 9: 0.1}
    agent = _agent(_PLAN, _response(scores))
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


async def test_planner_is_retried_once_on_a_provider_error(monkeypatch):
    import anthropic
    import httpx
    from anthropic.types import ToolUseBlock

    from peritus.chat import agent as agent_module

    monkeypatch.setattr(agent_module, "_PLAN_RETRY_DELAY", 0)
    good = MagicMock()
    good.content = [
        ToolUseBlock(
            type="tool_use",
            id="t1",
            name="create_plan",
            input={
                "subqueries": ["first mover"],
                "fallback_queries": ["motion"],
                "standalone_question": "q",
                "asker_level": "novice",
                "question_type": "explanation",
                "answer_directive": "Explain it.",
            },
        )
    ]
    error = anthropic.InternalServerError(
        "boom", response=httpx.Response(500, request=httpx.Request("POST", "http://x")), body=None
    )
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=[error, good])
    monkeypatch.setattr(agent_module, "get_anthropic_client", lambda: client)

    plan = await ChatAgent(MagicMock())._plan("q", "Thomism")
    assert client.messages.create.await_count == 2
    assert plan.subqueries == ["first mover"] and plan.question_type == "explanation"


def test_the_same_text_from_another_source_takes_one_seat():
    from peritus.chat.agent import _unique_chunks

    article = (
        "Whether God is altogether simple? The absolute simplicity of God may be shown in many "
        "ways. First, from the previous articles of this question. For there is neither "
        "composition of quantitative parts in God, since He is not a body; nor composition of "
        "matter and form; nor does His nature differ from His suppositum."
    )
    a, b, c = _hit(1, 0.9), _hit(2, 0.8), _hit(3, 0.7)
    a.text, b.text = article, "Question 3 on the web. " + article
    ids = [e.result.chunk_id for e in _unique_chunks([EnrichedResult(r) for r in (a, b, c)], 10)]
    assert ids == [1, 3]
