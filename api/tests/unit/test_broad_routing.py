"""Phase 4: section runs, broad-question routing and source diversity.

No model call and no database: the search, the section index and the graph are
stubbed at the agent's seams.
"""

from unittest.mock import AsyncMock, patch

from peritus.chat.agent import QueryPlan, diversify
from peritus.graph.retriever import EnrichedResult
from peritus.ingestion.summaries import MAX_RUN, SectionHit, section_runs
from tests.unit.test_chat_retrieval_gate import _STRONG, _agent, _expert, _hit, _response


def _prose(n: int) -> str:
    return f"This is passage {n} about kings and their kingdoms, and it is written as prose."


def _row(source: int, seq: int, section: str = "", title: str = "Work") -> dict:
    return {
        "source_id": source,
        "sequence_n": seq,
        "text": _prose(seq),
        "chunk_meta": {"section": section},
        "title": title,
    }


def test_runs_break_at_headings_gaps_sources_and_length():
    rows = [_row(1, i, "A") for i in range(5)]
    rows += [_row(1, i, "B") for i in range(5, 9)]
    rows += [_row(1, i, "B") for i in range(20, 20 + MAX_RUN + 4)]
    rows += [_row(2, 0, "A"), _row(2, 1, "A"), _row(2, 2, "A")]
    runs = section_runs(rows)
    spans = [(r.source_id, r.seq_start, r.seq_end) for r in runs]
    assert spans[:2] == [(1, 0, 4), (1, 5, 8)]
    assert spans[2] == (1, 20, 20 + MAX_RUN - 1)  # capped at MAX_RUN
    assert spans[3] == (1, 20 + MAX_RUN, 20 + MAX_RUN + 3)
    assert spans[4] == (2, 0, 2)


def test_a_short_run_joins_the_one_before_it():
    rows = [_row(1, i, "A") for i in range(4)] + [_row(1, 4, "stray")] + [_row(1, 5, "stray")]
    runs = section_runs(rows)
    assert [(r.seq_start, r.seq_end) for r in runs] == [(0, 5)]
    rows = [_row(1, 0, "x"), _row(1, 1, "y"), _row(1, 2, "y"), _row(1, 3, "y")]
    assert [(r.seq_start, r.seq_end) for r in section_runs(rows)] == [(0, 3)]


_WORDS = [
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "zeta",
    "theta",
    "iota",
    "kappa",
    "lambda",
    "sigma",
    "omega",
]


def _e(chunk_id: int, source: int, score: float = 0.0) -> EnrichedResult:
    hit = _hit(chunk_id, score)
    hit.source_id = source
    words = " ".join(f"{w}{chunk_id}" for w in _WORDS)
    hit.text = f"The passage numbered {chunk_id} says that {words} is what it was."
    return EnrichedResult(result=hit)


def test_a_dominant_source_gives_up_neighbours_first():
    retrieved = [_e(1, 7, 0.8), _e(2, 7, 0.6), _e(3, 9, 0.5)]
    neighbours = [_e(11, 7), _e(12, 7), _e(13, 7)]
    alt = _e(20, 8, 0.45).result
    kept, nbrs, add = diversify(retrieved, neighbours, [], [alt], threshold=0.4)
    assert [r.chunk_id for r in add] == [20]
    assert [e.result.chunk_id for e in nbrs] == [11, 12]
    assert len(kept) == 3


def test_nothing_is_swapped_without_a_good_alternative():
    retrieved = [_e(1, 7, 0.8), _e(2, 7, 0.6)]
    below = _e(20, 8, 0.1).result
    kept, _nbrs, add = diversify(retrieved, [], [], [below], threshold=0.4)
    assert add == [] and len(kept) == 2


async def test_a_broad_question_seats_its_routed_sections():
    plan = QueryPlan(subqueries=["kings of the heptarchy"], question_type="comparison")
    resp = _response(_STRONG)
    resp.query_embeddings = {"kings of the heptarchy": [0.1], "Who mattered most?": [0.2]}
    agent = _agent(plan, resp)
    routed = _hit(500, 0.0)
    routed.source_id = 42
    routed.text = "Alfred the Great defended Wessex against the Danes and founded burhs."
    agent._search.best_in_spans = AsyncMock(return_value=[[routed]])
    with patch(
        "peritus.chat.agent.search_sections",
        AsyncMock(return_value=[SectionHit(42, 10, 20, 0.6)]),
    ):
        ctx = await agent.gather_context(_expert(), "Who mattered most?")

    vias = {s.chunk_id: s.via for s in ctx.trail.steps}
    assert vias[500] == "section_route"
    assert 500 in [p.chunk_id for p in ctx.passages]
    # Ranked inside the section by the question itself.
    assert agent._search.best_in_spans.await_args.args[2] == [0.2]


async def test_a_lookup_is_not_routed():
    plan = QueryPlan(subqueries=["date of the synod"], question_type="specific_fact")
    resp = _response(_STRONG)
    resp.query_embeddings = {"date of the synod": [0.1]}
    agent = _agent(plan, resp)
    with patch("peritus.chat.agent.search_sections", AsyncMock()) as search:
        await agent.gather_context(_expert(), "When was the synod?")
    search.assert_not_awaited()


def test_the_best_passages_own_run_is_never_given_up():
    retrieved = [_e(1, 7, 0.8), _e(2, 7, 0.6)]
    neighbours = [_e(11, 7), _e(12, 7)]
    alternatives = [_e(20, 8, 0.5).result, _e(21, 9, 0.5).result, _e(22, 5, 0.5).result]
    kept, nbrs, add = diversify(
        retrieved, neighbours, [], alternatives, threshold=0.4, protected={1, 11, 12}
    )
    # 12 and 11 are protected; the only thing source 7 can give up is passage 2.
    assert [e.result.chunk_id for e in nbrs] == [11, 12]
    assert [e.result.chunk_id for e in kept] == [1]
    assert [r.chunk_id for r in add] == [20]
