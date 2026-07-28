"""The `retrieval_audit` event on the chat stream.

Both chat endpoints share ``stream_expert_answer`` and forward whatever it
yields, so this covers the event for the stateless and stateful routes at once.

The event is an audit trail, not a verdict: it must appear without disturbing
the existing event order, and it must never carry a score for the answer.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from peritus.chat.agent import RetrievalStep, RetrievalTrail, RetrievedContext
from peritus.chat.grounding import Passage
from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier
from peritus.search.readiness import Readiness

ANSWER = "Virtue is the only good [1]. Fate is indifferent [2]."


def _expert() -> Expert:
    return Expert(
        id=1, name="stoicism", topic="stoicism", status=ExpertStatus.READY,
        tier=ExpertTier.STANDARD, config=ExpertConfig.from_tier(ExpertTier.STANDARD),
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )


def _context() -> RetrievedContext:
    passages = [
        Passage(index=1, citation="Meditations — Gutenberg", source_id=10, text="…"),
        Passage(index=2, citation="Enchiridion — Gutenberg", source_id=11, text="…"),
    ]
    steps = [
        RetrievalStep(chunk_id=100, source_id=10, source_title="Meditations",
                      source_type="gutenberg", quality_score=9.0, rank=1, score=0.9,
                      via="primary"),
        RetrievalStep(chunk_id=101, source_id=11, source_title="Enchiridion",
                      source_type="gutenberg", quality_score=8.0, rank=2, score=0.8,
                      via="primary"),
        # Retrieved but below the context cap — invisible in the answer, and
        # exactly what the trail exists to surface.
        RetrievalStep(chunk_id=102, source_id=12, source_title="A blog",
                      source_type="web", quality_score=6.0, rank=3, score=0.3,
                      via="coverage_followup"),
    ]
    return RetrievedContext(
        context_block="[1] …\n\n[2] …",
        passages=passages,
        has_contradiction=True,
        trail=RetrievalTrail(
            subqueries=["stoic definition of virtue", "stoic view of fate"],
            followup_queries=["stoic providence"],
            coverage_satisfied=False,
            second_pass=True,
            context_cap=2,
            duplicate_hits=1,
            graph_expanded=True,
            steps=steps,
        ),
    )


def _agent_with(context: RetrievedContext):
    agent = MagicMock()

    async def _retrieve(_expert, _question):
        yield ("status", "Planning search queries…")
        yield ("context", context)

    agent.retrieve = _retrieve
    return agent


def _anthropic_streaming(text: str):
    client = MagicMock()

    class _Stream:
        @property
        async def text_stream(self):
            yield text

    @asynccontextmanager
    async def _stream(**_kwargs):
        yield _Stream()

    client.messages.stream = _stream
    return client


async def _collect(context=None, readiness=Readiness.GRAPH_READY, audit_id="aud-1"):
    from peritus.chat import streaming

    service = MagicMock()
    service.record_answer_audit = AsyncMock(return_value=audit_id)

    async def _get_readiness(_pool, _expert_id):
        return readiness

    with (
        patch.object(streaming, "ChatAgent", return_value=_agent_with(context or _context())),
        patch.object(streaming, "get_anthropic_client",
                     return_value=_anthropic_streaming(ANSWER)),
        patch.object(streaming, "get_readiness", new=_get_readiness),
        patch.object(streaming, "AuditService", return_value=service),
    ):
        events = [
            ev
            async for ev in streaming.stream_expert_answer(
                MagicMock(), _expert(), "What is virtue?", [], conversation_id="conv-1"
            )
        ]
    return events, service


def _find(events, type_):
    return next(e for e in events if e["type"] == type_)


# ── event ordering ──

@pytest.mark.asyncio
async def test_audit_event_sits_between_sources_and_done():
    """Clients that only know the old events must be unaffected, so the new one
    slots in after the citations and before the terminal event."""
    events, _ = await _collect()
    order = [e["type"] for e in events]
    assert order[0] == "status"
    assert order[-3:] == ["sources", "retrieval_audit", "done"]


# ── content ──

@pytest.mark.asyncio
async def test_audit_reports_retrieved_considered_and_cited():
    events, _ = await _collect()
    audit = _find(events, "retrieval_audit")

    counts = audit["passages"]
    assert counts["unique"] == 3          # everything retrieval surfaced
    assert counts["duplicate_hits"] == 1
    assert counts["retrieved"] == 4
    assert counts["in_context"] == 2      # what the model was actually shown
    assert counts["cited"] == 2           # what the answer used
    assert counts["not_in_context"] == 1
    assert counts["context_cap"] == 2


@pytest.mark.asyncio
async def test_audit_gives_every_passage_a_disposition():
    events, _ = await _collect()
    audit = _find(events, "retrieval_audit")
    assert [d["disposition"] for d in audit["dispositions"]] == [
        "cited", "cited", "not_in_context",
    ]
    assert [d["chunk_id"] for d in audit["dispositions"]] == [100, 101, 102]
    assert audit["dispositions"][2]["retrieved_via"] == "coverage_followup"
    assert audit["dispositions"][2]["source_title"] == "A blog"


@pytest.mark.asyncio
async def test_audit_records_the_search_that_was_run():
    events, _ = await _collect()
    audit = _find(events, "retrieval_audit")
    assert audit["subqueries"] == ["stoic definition of virtue", "stoic view of fate"]
    assert audit["followup_queries"] == ["stoic providence"]
    assert audit["coverage"] == {"satisfied": False, "second_pass": True}


@pytest.mark.asyncio
async def test_audit_carries_no_score_for_the_answer():
    """Groundedness is offline-eval only; its live display was removed
    deliberately and must not return through this event."""
    events, _ = await _collect()
    flat = repr(_find(events, "retrieval_audit")).lower()
    for banned in ("groundedness", "faithful", "confidence", "accuracy"):
        assert banned not in flat


# ── the graph-not-built distinction ──

@pytest.mark.asyncio
async def test_ungraphed_expert_reports_contradictions_as_unknown():
    events, _ = await _collect(readiness=Readiness.CHAT_READY)
    graph = _find(events, "retrieval_audit")["graph"]
    assert graph["contradiction_traversed"] is None
    assert graph["unavailable_reason"]


@pytest.mark.asyncio
async def test_graphed_expert_reports_a_traversed_contradiction():
    events, _ = await _collect(readiness=Readiness.GRAPH_READY)
    graph = _find(events, "retrieval_audit")["graph"]
    assert graph["contradiction_traversed"] is True
    assert graph["unavailable_reason"] is None


# ── persistence ──

@pytest.mark.asyncio
async def test_audit_is_persisted_against_the_conversation():
    events, service = await _collect()
    audit = _find(events, "retrieval_audit")
    assert audit["audit_id"] == "aud-1"
    assert audit["persisted"] is True

    header, rows = service.record_answer_audit.await_args.args
    assert header["expert_id"] == 1
    assert header["conversation_id"] == "conv-1"
    assert header["question"] == "What is virtue?"
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_unpersisted_audit_still_streams_and_says_so():
    events, _ = await _collect(audit_id=None)
    audit = _find(events, "retrieval_audit")
    assert audit["audit_id"] is None
    assert audit["persisted"] is False


# ── the audit must never cost the user an answer ──

@pytest.mark.asyncio
async def test_answer_survives_a_failing_audit():
    """The answer has already been delivered by this point; a failure to account
    for it must not turn a good answer into an error."""
    from peritus.chat import streaming

    async def _boom(_pool, _expert_id):
        raise RuntimeError("readiness lookup exploded")

    with (
        patch.object(streaming, "ChatAgent", return_value=_agent_with(_context())),
        patch.object(streaming, "get_anthropic_client",
                     return_value=_anthropic_streaming(ANSWER)),
        patch.object(streaming, "get_readiness", new=_boom),
    ):
        events = [
            ev
            async for ev in streaming.stream_expert_answer(
                MagicMock(), _expert(), "What is virtue?", []
            )
        ]

    types = [e["type"] for e in events]
    assert "retrieval_audit" not in types
    assert types[-1] == "done"
    assert _find(events, "sources")["citations"]


@pytest.mark.asyncio
async def test_answer_survives_a_missing_trail():
    """Older or degraded retrieval paths may produce no trail at all."""
    context = _context()
    context.trail = None
    events, _ = await _collect(context=context)
    audit = _find(events, "retrieval_audit")
    assert audit["dispositions"] == []
    assert audit["passages"]["unique"] == 0
