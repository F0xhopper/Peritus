"""The per-answer retrieval trail.

Two things are being protected here. First, that every retrieved passage is
accounted for with the right disposition — including the ones that never
reached the model. Second, that the trail stays a *trail*: no score, no grade,
no groundedness figure anywhere in what a client receives.
"""

from peritus.chat.agent import RetrievalStep, RetrievalTrail
from peritus.chat.audit_trail import audit_db_rows, build_audit_payload
from peritus.chat.grounding import Passage


def _step(rank: int, chunk_id: int, source_id: int, via: str = "primary") -> RetrievalStep:
    return RetrievalStep(
        chunk_id=chunk_id,
        source_id=source_id,
        source_title=f"Source {source_id}",
        source_type="arxiv",
        quality_score=8.25,
        rank=rank,
        score=0.5 / rank,
        via=via,
    )


def _passage(index: int, source_id: int) -> Passage:
    return Passage(
        index=index, citation=f"Source {source_id} — Arxiv", source_id=source_id, text="…"
    )


def _trail(steps: list[RetrievalStep], **overrides) -> RetrievalTrail:
    fields = dict(
        subqueries=["stoic view of death", "memento mori"],
        followup_queries=[],
        coverage_satisfied=True,
        second_pass=False,
        context_cap=3,
        duplicate_hits=0,
        graph_expanded=True,
        steps=steps,
    )
    fields.update(overrides)
    return RetrievalTrail(**fields)


# ── dispositions ──

def test_every_retrieved_passage_gets_a_disposition():
    steps = [_step(1, 10, 100), _step(2, 11, 101), _step(3, 12, 102), _step(4, 13, 103)]
    passages = [_passage(1, 100), _passage(2, 101), _passage(3, 102)]  # cap = 3

    payload = build_audit_payload(
        trail=_trail(steps), passages=passages, cited={1, 3},
        answer_text="Grounded [1] and [3].", has_contradiction=False, graph_ready=True,
    )

    dispositions = [d["disposition"] for d in payload["dispositions"]]
    assert dispositions == [
        "cited",
        "in_context_uncited",
        "cited",
        # Retrieved, ranked below the tier's context cap, never shown to the model.
        "not_in_context",
    ]
    assert [d["n"] for d in payload["dispositions"]] == [1, 2, 3, None]


def test_counts_reconcile_across_the_funnel():
    steps = [_step(1, 10, 100), _step(2, 11, 101), _step(3, 12, 102), _step(4, 13, 103)]
    passages = [_passage(1, 100), _passage(2, 101), _passage(3, 102)]

    payload = build_audit_payload(
        trail=_trail(steps, duplicate_hits=2), passages=passages, cited={1},
        answer_text="[1]", has_contradiction=False, graph_ready=True,
    )
    counts = payload["passages"]
    assert counts["unique"] == 4
    assert counts["duplicate_hits"] == 2
    assert counts["retrieved"] == 6          # unique + duplicates actually returned
    assert counts["in_context"] == 3
    assert counts["cited"] == 1
    assert counts["not_in_context"] == 1
    assert counts["context_cap"] == 3


def test_sources_are_counted_distinctly_from_passages():
    """Three passages from one source is one source, not three."""
    steps = [_step(1, 10, 100), _step(2, 11, 100), _step(3, 12, 200)]
    passages = [_passage(1, 100), _passage(2, 100), _passage(3, 200)]

    payload = build_audit_payload(
        trail=_trail(steps), passages=passages, cited={1, 2},
        answer_text="[1][2]", has_contradiction=False, graph_ready=True,
    )
    assert payload["sources"]["in_context"] == 2
    assert payload["sources"]["cited"] == 1


def test_followup_pass_is_attributed_to_the_coverage_round():
    steps = [_step(1, 10, 100), _step(2, 11, 101, via="coverage_followup")]
    payload = build_audit_payload(
        trail=_trail(steps, followup_queries=["stoic funerary practice"], second_pass=True,
                     coverage_satisfied=False),
        passages=[_passage(1, 100), _passage(2, 101)],
        cited=set(), answer_text="No citations.", has_contradiction=False, graph_ready=True,
    )
    assert [d["retrieved_via"] for d in payload["dispositions"]] == [
        "primary", "coverage_followup",
    ]
    assert payload["coverage"] == {"satisfied": False, "second_pass": True}
    assert payload["followup_queries"] == ["stoic funerary practice"]


# ── the graph-not-built distinction ──

def test_contradiction_flag_is_null_when_the_graph_is_not_built_yet():
    """An expert can answer before its concept graph exists. Reporting False
    there would read as 'no contradictions found', which is a finding — and
    for this product, the wrong one to invent."""
    payload = build_audit_payload(
        trail=_trail([_step(1, 10, 100)]), passages=[_passage(1, 100)], cited={1},
        answer_text="[1]", has_contradiction=False, graph_ready=False,
    )
    assert payload["graph"]["contradiction_traversed"] is None
    assert "not a finding that none exist" in payload["graph"]["unavailable_reason"]


def test_contradiction_flag_is_boolean_once_the_graph_exists():
    for flag in (True, False):
        payload = build_audit_payload(
            trail=_trail([_step(1, 10, 100)]), passages=[_passage(1, 100)], cited=set(),
            answer_text="", has_contradiction=flag, graph_ready=True,
        )
        assert payload["graph"]["contradiction_traversed"] is flag
        assert payload["graph"]["unavailable_reason"] is None


# ── it is a trail, not a score ──

def test_payload_contains_no_quality_or_confidence_score():
    """Groundedness lives in chat/faithfulness.py for offline evaluation only.
    Its live display was removed deliberately and must not creep back in here."""
    payload = build_audit_payload(
        trail=_trail([_step(1, 10, 100)]), passages=[_passage(1, 100)], cited={1},
        answer_text="[1]", has_contradiction=False, graph_ready=True,
    )
    flat = repr(payload).lower()
    for banned in ("groundedness", "faithful", "confidence", "accuracy", "grade"):
        assert banned not in flat


# ── degraded inputs ──

def test_missing_trail_degrades_to_empty_rather_than_raising():
    """Retrieval trails are best-effort; an answer must never fail for want of one."""
    payload = build_audit_payload(
        trail=None, passages=[], cited=set(), answer_text="hi",
        has_contradiction=False, graph_ready=True,
    )
    assert payload["dispositions"] == []
    assert payload["passages"]["unique"] == 0
    assert payload["subqueries"] == []


# ── persistence mapping ──

def test_db_rows_mirror_the_payload():
    steps = [_step(1, 10, 100), _step(2, 11, 101)]
    payload = build_audit_payload(
        trail=_trail(steps), passages=[_passage(1, 100)], cited={1},
        answer_text="[1] only", has_contradiction=True, graph_ready=True,
    )
    header, rows = audit_db_rows(payload, expert_id=7, conversation_id="abc", question="Q?")

    assert header["expert_id"] == 7
    assert header["conversation_id"] == "abc"
    assert header["question"] == "Q?"
    assert header["cited_passages"] == 1
    assert header["context_passages"] == 1
    assert header["unique_passages"] == 2
    assert header["contradiction_traversed"] is True
    assert header["answer_chars"] == len("[1] only")

    assert len(rows) == 2
    assert rows[0]["disposition"] == "cited"
    assert rows[1]["disposition"] == "not_in_context"
    assert rows[1]["passage_n"] is None
    assert rows[0]["source_title"] == "Source 100"


def test_ungraphed_contradiction_persists_as_false_not_null():
    """The column is NOT NULL; readiness distinguishes the two states at read time."""
    payload = build_audit_payload(
        trail=_trail([_step(1, 10, 100)]), passages=[_passage(1, 100)], cited=set(),
        answer_text="", has_contradiction=False, graph_ready=False,
    )
    header, _ = audit_db_rows(payload, expert_id=1, conversation_id=None, question="Q")
    assert header["contradiction_traversed"] is False
