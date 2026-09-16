"""The screening decision: band selection, the reviewer's override, and the
errored-batch path that used to throw sources away.

No network: ``gather_claude_calls`` is stubbed, so what is under test is the
decision logic rather than the model.
"""

from typing import Any, ClassVar
from unittest.mock import patch

import pytest

from peritus.core.config import settings
from peritus.sources import validator as validator_module
from peritus.sources.domain import RawSource, SourceType
from peritus.sources.validator import (
    REVIEW_BAND_Q,
    REVIEW_BAND_R,
    RUBRIC_VERSION,
    needs_second_opinion,
    validate_sources,
)

# ── stubs ────────────────────────────────────────────────────────────────────


class _Block:
    type = "tool_use"

    def __init__(self, validations: list[dict]) -> None:
        self.input = {"validations": validations}


class _Response:
    def __init__(self, validations: list[dict]) -> None:
        self.content = [_Block(validations)]


def _verdict(q: float, r: float, **overrides) -> dict:
    return {
        "quality_score": q,
        "relevance_score": r,
        "content_type": "paper",
        "source_tier": "secondary",
        "difficulty": 3,
        "key_claims": ["a claim"],
        "covered_concepts": ["analogy"],
        "drop_reason": None if (q >= 5 and r >= 6) else "below threshold",
        **overrides,
    }


def _source(title: str = "A source") -> RawSource:
    return RawSource(SourceType.WEB, f"https://x.test/{title}", title, None, "body " * 200)


def _stub_calls(first_pass: list[list[dict] | None], review: list[list[dict] | None]):
    """Serve the first pass and the review pass from separate scripts.

    ``description`` is how the validator names its two call sets, and keying on
    it is what lets one stub answer both without guessing from call order.
    """
    queues = {"validate": list(first_pass), "validate-review": list(review)}

    async def _gather(params, live_concurrency=None, description="", on_result=None):
        queue = queues[description]
        responses = []
        for i, _p in enumerate(params):
            entry = queue[i] if i < len(queue) else None
            resp = None if entry is None else _Response(entry)
            responses.append(resp)
            if on_result:
                await on_result(i, resp)
        return responses

    return patch.object(validator_module, "gather_claude_calls", _gather)


# ── the band ─────────────────────────────────────────────────────────────────


def test_the_band_is_either_side_of_each_threshold():
    """Errors live near the line; the tails are cheap and right."""
    assert not needs_second_opinion(_verdict(9.0, 9.0) | {"drop": False})
    assert not needs_second_opinion(_verdict(1.0, 1.0) | {"drop": True})
    assert needs_second_opinion(_verdict(REVIEW_BAND_Q[0], 9.0) | {"drop": True})
    assert needs_second_opinion(_verdict(9.0, REVIEW_BAND_R[1] - 0.1) | {"drop": False})
    assert not needs_second_opinion(_verdict(REVIEW_BAND_Q[1], 9.0) | {"drop": False})


def test_a_source_that_was_never_judged_always_gets_a_second_look():
    """An errored batch is a provider failure, not a verdict. Routing it here is
    what turns a blip into one extra call instead of a discarded source."""
    assert needs_second_opinion(
        {"quality_score": 0.0, "relevance_score": 0.0, "drop_reason": "validation error"}
    )


# ── the reviewer ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_second_opinion_is_off_by_default(monkeypatch):
    monkeypatch.setattr(settings, "VALIDATE_SECOND_OPINION", False)
    with _stub_calls([[_verdict(5.5, 6.5)]], review=[]):
        passed, _dropped = await validate_sources("t", [_source()], ["analogy"])
    assert len(passed) == 1
    assert passed[0].review_model is None
    assert passed[0].validator_model == settings.FAST_MODEL


@pytest.mark.asyncio
async def test_the_reviewer_verdict_replaces_the_first_pass(monkeypatch):
    monkeypatch.setattr(settings, "VALIDATE_SECOND_OPINION", True)
    monkeypatch.setattr(settings, "VALIDATE_REVIEW_MODEL", "claude-sonnet-5")

    # Borderline on both axes → reviewed, and the reviewer drops it.
    with _stub_calls([[_verdict(5.5, 6.5)]], review=[[_verdict(3.0, 3.0)]]):
        passed, dropped = await validate_sources("t", [_source()], ["analogy"])

    assert passed == []
    assert len(dropped) == 1
    row = dropped[0]
    assert row.quality_score == 3.0
    # Both verdicts survive: the ledger has to be able to show that a decision
    # was re-examined and what it said before.
    assert row.first_pass_quality == 5.5
    assert row.first_pass_relevance == 6.5
    assert row.review_model == "claude-sonnet-5"
    assert row.validator_model == "claude-sonnet-5"


@pytest.mark.asyncio
async def test_confident_verdicts_are_never_sent_to_the_reviewer(monkeypatch):
    monkeypatch.setattr(settings, "VALIDATE_SECOND_OPINION", True)
    reviewed: list[Any] = []

    async def _record(payload):
        reviewed.append(payload)

    with _stub_calls([[_verdict(9.0, 9.0), _verdict(1.0, 1.0)]], review=[]):
        passed, dropped = await validate_sources(
            "t", [_source("keep"), _source("drop")], ["analogy"], on_reviewed=_record
        )
    assert len(passed) == 1 and len(dropped) == 1
    assert reviewed == [], "the tails are cheap and right — do not pay to re-ask"


@pytest.mark.asyncio
async def test_an_errored_batch_is_rescued_rather_than_dropped(monkeypatch):
    """The old behaviour dropped all five of a failed batch as 'validation
    error' — a fifth of a lite corpus lost to one bad response."""
    monkeypatch.setattr(settings, "VALIDATE_SECOND_OPINION", True)
    sources = [_source(f"s{i}") for i in range(3)]

    with _stub_calls([None], review=[[_verdict(8.0, 8.0)]] * 3):
        passed, dropped = await validate_sources("t", sources, ["analogy"])

    assert len(passed) == 3
    assert dropped == []
    # A rescued source has no first pass to report — it was never scored, and
    # writing 0.0 would read as "the model scored it zero".
    assert passed[0].first_pass_quality is None


@pytest.mark.asyncio
async def test_an_errored_batch_the_reviewer_cannot_rescue_still_drops(monkeypatch):
    monkeypatch.setattr(settings, "VALIDATE_SECOND_OPINION", True)
    with _stub_calls([None], review=[None]):
        passed, dropped = await validate_sources("t", [_source()], ["analogy"])
    assert passed == []
    assert dropped[0].drop_reason == "validation error"


@pytest.mark.asyncio
async def test_reviewed_callback_reports_both_verdicts_and_the_reversal(monkeypatch):
    monkeypatch.setattr(settings, "VALIDATE_SECOND_OPINION", True)
    seen: list[dict] = []

    async def _record(payload):
        seen.append(payload)

    with _stub_calls([[_verdict(4.5, 6.5)]], review=[[_verdict(8.0, 8.0)]]):
        await validate_sources("t", [_source()], ["analogy"], on_reviewed=_record)

    assert seen[0]["reversed"] is True
    assert seen[0]["first_q"] == 4.5
    assert seen[0]["q"] == 8.0
    assert seen[0]["passed"] is True


# ── provenance ───────────────────────────────────────────────────────────────


def test_the_rubric_version_names_the_graded_tags_rubric():
    """What the validator is asked changed (concept tags carry a depth, and an
    about-page on the thought-leader channel is tertiary) even though the
    thresholds did not, and a screening run has to be able to tell v7 from v8."""
    assert RUBRIC_VERSION == "v8-graded-tags-q5r6"
    assert "q5r6" in RUBRIC_VERSION


@pytest.mark.asyncio
async def test_concept_tags_are_matched_against_the_plan_not_invented(monkeypatch):
    monkeypatch.setattr(settings, "VALIDATE_SECOND_OPINION", False)
    verdict = _verdict(8.0, 8.0, covered_concepts=["ANALOGY", "made up"])
    with _stub_calls([[verdict]], review=[]):
        passed, _ = await validate_sources("t", [_source()], ["analogy"])
    assert passed[0].covered_concepts == ["analogy"]


@pytest.mark.asyncio
async def test_a_string_where_a_verdict_was_expected_does_not_take_the_batch(monkeypatch):
    """Found on a real build: the model put a bare string in the validations
    array and `.get` raised out of the batch's result handler, costing all of
    its sources. A malformed entry is the model failing to answer, so it is
    treated as unjudged and re-asked rather than dropped."""
    monkeypatch.setattr(settings, "VALIDATE_SECOND_OPINION", True)
    sources = [_source("a"), _source("b")]

    # Batch returns one good verdict and one bare string.
    class _MixedBlock:
        type = "tool_use"
        input: ClassVar[dict[str, Any]] = {"validations": [_verdict(9.0, 9.0), "looks fine to me"]}

    class _MixedResponse:
        content: ClassVar[list[Any]] = [_MixedBlock()]

    queues = {"validate": [_MixedResponse()], "validate-review": [_Response([_verdict(8.0, 8.0)])]}

    async def _gather(params, live_concurrency=None, description="", on_result=None):
        out = []
        for i, _p in enumerate(params):
            resp = queues[description][i] if i < len(queues[description]) else None
            out.append(resp)
            if on_result:
                await on_result(i, resp)
        return out

    with patch.object(validator_module, "gather_claude_calls", _gather):
        passed, dropped = await validate_sources("t", sources, ["analogy"])

    # Neither source is lost: one was judged, the other was re-asked.
    assert len(passed) == 2
    assert dropped == []
