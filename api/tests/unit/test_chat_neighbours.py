"""Neighbour expansion: which positions are asked for, and the order they are read in.

Pure functions plus the agent's seam. No model call and no database.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from peritus.chat.agent import ChatAgent, QueryPlan
from peritus.chat.grounding import build_grounded_context
from peritus.chat.neighbours import reading_order, wanted_positions
from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier
from peritus.graph.retriever import EnrichedResult
from peritus.search.domain import SearchResponse, SearchResult, SourceRef


def _chunk(chunk_id: int, source_id: int, seq: int, score: float = 0.0) -> EnrichedResult:
    return EnrichedResult(
        result=SearchResult(
            chunk_id=chunk_id,
            expert_id=1,
            source_id=source_id,
            text=f"This is the text of work {source_id} at position {seq}, which is prose.",
            context_text=None,
            score=score,
            sequence_n=seq,
            source_ref=SourceRef(
                source_id=source_id, title=f"Work {source_id}", source_type="web", quality_score=9.0
            ),
        )
    )


def _ids(items: list[EnrichedResult]) -> list[int]:
    return [e.result.chunk_id for e in items]


def test_neighbours_are_asked_for_nearest_first_and_what_follows_before_what_precedes():
    anchor = _chunk(1, source_id=7, seq=50)
    assert wanted_positions([anchor], {(7, 50)}, before=1, after=2) == [(7, 51), (7, 49), (7, 52)]


def test_a_held_or_already_wanted_position_is_not_asked_for_twice():
    first, second = _chunk(1, 7, 50), _chunk(2, 7, 52)
    wanted = wanted_positions([first, second], {(7, 50), (7, 52)}, before=1, after=2)
    # 51 sits between the two anchors and 52 is already held.
    assert wanted == [(7, 51), (7, 49), (7, 53), (7, 54)]


def test_no_position_before_the_start_of_a_source():
    assert wanted_positions([_chunk(1, 7, 0)], {(7, 0)}, before=2, after=1) == [(7, 1)]


def test_a_run_is_read_in_source_order_where_its_best_passage_ranked():
    best, other, third = _chunk(1, 7, 50), _chunk(2, 9, 3), _chunk(3, 7, 48)
    neighbours = [_chunk(11, 7, 51), _chunk(12, 7, 49), _chunk(13, 9, 4)]
    ordered = reading_order([best, other, third], neighbours)
    # 48–51 is one run because 49 joins the third-ranked passage to the best.
    assert _ids(ordered) == [3, 12, 1, 11, 2, 13]


def test_a_neighbour_touching_nothing_is_dropped():
    anchor = _chunk(1, 7, 50)
    # 51 was missing from the corpus, so 52 is two rows from anything held.
    assert _ids(reading_order([anchor], [_chunk(12, 7, 52)])) == [1]


def test_unsequenced_chunks_sharing_a_position_each_stand_alone():
    a, b = _chunk(1, 7, 0), _chunk(2, 7, 0)
    assert _ids(reading_order([a, b], [])) == [1, 2]


def test_a_continuation_says_which_passage_it_continues():
    block, passages = build_grounded_context(
        [_chunk(1, 7, 50), _chunk(2, 7, 51), _chunk(3, 9, 52)], max_passages=10
    )
    assert [p.chunk_id for p in passages] == [1, 2, 3]
    assert "[2] Work 7 (continues directly from [1])" in block
    assert "[1] Work 7\n" in block and "[3] Work 9\n" in block


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


def _agent(hits: list[EnrichedResult], corpus: list[EnrichedResult]) -> ChatAgent:
    agent = ChatAgent(MagicMock())
    agent._plan = AsyncMock(return_value=QueryPlan(subqueries=["whether God exists"]))
    results = [e.result for e in hits]
    agent._search.batch_search = AsyncMock(
        return_value=SearchResponse(query="q", results=results, total=len(results), reranked=True)
    )
    by_position = {(e.result.source_id, e.result.sequence_n): e.result for e in corpus}

    async def fetch_by_position(expert_id, positions):
        return [by_position[p] for p in positions if p in by_position]

    async def expand(results, expert_id, hops=1):
        return [EnrichedResult(result=r) for r in results]

    agent._search.fetch_by_position = AsyncMock(side_effect=fetch_by_position)
    agent._graph.expand = expand
    return agent


async def test_the_best_passages_arrive_with_the_text_around_them():
    hits = [_chunk(50, 7, 50, 0.6), _chunk(90, 9, 3, 0.4), _chunk(91, 9, 30, 0.2)]
    corpus = [_chunk(i, 7, i) for i in range(45, 56)]
    agent = _agent(hits, corpus)

    ctx = await agent.gather_context(_expert(), "What is the most tangible proof of God?")

    # The argument the best hit opens is read through; source 9 has nothing
    # either side of it in this corpus, so its passages stand as they were.
    assert [p.chunk_id for p in ctx.passages] == [49, 50, 51, 52, 90, 91]
    vias = {s.chunk_id: s.via for s in ctx.trail.steps}
    assert vias[50] == "primary" and vias[51] == "neighbour"
    assert len(ctx.passages) <= ctx.trail.context_cap


async def test_anchors_are_chosen_by_rank_not_by_clearing_a_floor():
    # Only 50 clears the relative floor; 20 and 30 are kept to make up the
    # minimum. On a question where everything scores low the best passages
    # still have context worth reading, so all three bring their neighbours.
    hits = [_chunk(50, 7, 50, 0.6), _chunk(20, 7, 20, 0.05), _chunk(30, 7, 30, 0.04)]
    agent = _agent(hits, [_chunk(i, 7, i) for i in range(0, 60)])

    ctx = await agent.gather_context(_expert(), "q")

    assert [p.chunk_id for p in ctx.passages] == [49, 50, 51, 52, 19, 20, 21, 22, 29, 30, 31, 32]


async def test_a_neighbour_that_is_not_prose_is_left_out():
    hits = [_chunk(50, 7, 50, 0.6)]
    junk = _chunk(51, 7, 51)
    junk.result.text = (
        "Da waes sefter for^yrnendre tide ymb fif hund wintra 7 tu 7 Cap. 23. hundnigontig "
        "wintra from Cristes hidercyme ; Mauricius casere feng to rice 7 fset hsefde an 7 "
        "twentig wintra. Se wses feorSa eac fiftegum from Augusto. Dses case sealde gerihte "
        "Gregorius papa ond ealne eard bearn heora cynn ond eald ge wurdon swylce"
    )
    agent = _agent(hits, [_chunk(49, 7, 49), junk, _chunk(52, 7, 52)])

    ctx = await agent.gather_context(_expert(), "q")

    # 52 is two rows from anything held once 51 is gone, so it goes too.
    assert [p.chunk_id for p in ctx.passages] == [49, 50]


async def test_a_failed_neighbour_fetch_costs_the_answer_nothing():
    hits = [_chunk(50, 7, 50, 0.6), _chunk(90, 9, 3, 0.4), _chunk(91, 9, 30, 0.2)]
    agent = _agent(hits, [])
    agent._search.fetch_by_position = AsyncMock(side_effect=RuntimeError("pool exhausted"))

    ctx = await agent.gather_context(_expert(), "q")

    assert [p.chunk_id for p in ctx.passages] == [50, 90, 91]


async def test_a_neighbour_a_search_already_found_keeps_the_step_it_was_found_with():
    # Chunk 51 was retrieved but fell below the floor; it comes back as the
    # neighbour of 50 and is in the prompt — once in the trail, as a search hit.
    hits = [
        _chunk(50, 7, 50, 0.6),
        _chunk(90, 9, 3, 0.5),
        _chunk(91, 9, 30, 0.4),
        _chunk(51, 7, 51, 0.05),
    ]
    agent = _agent(hits, [_chunk(51, 7, 51)])

    ctx = await agent.gather_context(_expert(), "q")

    assert [p.chunk_id for p in ctx.passages] == [50, 51, 90, 91]
    steps = [s for s in ctx.trail.steps if s.chunk_id == 51]
    assert len(steps) == 1 and steps[0].via == "primary" and steps[0].score == 0.05
    assert ctx.trail.duplicate_hits == 0
