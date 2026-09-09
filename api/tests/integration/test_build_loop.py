"""The discovery loop: how many rounds run, and why it stops.

Everything below a round is stubbed — no fetchers, no models, no network. What
is under test is the loop: when it searches again, when it stops, and whether
the reason it gives for stopping is the true one. That reason is the surface the
audit trail publishes, so a wrong one is worse than no loop at all.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from peritus.experts.builder import (
    STOP_ACCEPTANCE_COLLAPSED,
    STOP_LOOP_DISABLED,
    STOP_MAX_ROUNDS,
    STOP_NO_NEW_CANDIDATES,
    STOP_SOURCE_LIMIT,
    STOP_TARGETS_MET,
    ExpertBuilder,
)
from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier
from peritus.sources.domain import Identifiers, RawSource, SourceType, ValidatedSource

pytestmark = pytest.mark.asyncio

_CONCEPTS = ["analogy", "participation"]
_PLAN = {"fetcher_plans": {}, "key_concepts": _CONCEPTS, "must_have_works": []}
# Enough source types to satisfy STANDARD's min_source_types of 2.
_TYPES = (SourceType.OPENALEX, SourceType.ARXIV, SourceType.WEB)


def _expert(tier: ExpertTier = ExpertTier.STANDARD) -> Expert:
    return Expert(
        id=1,
        name="thomism",
        topic="Thomism",
        status=ExpertStatus.BUILDING,
        tier=tier,
        config=ExpertConfig.from_tier(tier),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _raw(key: str, source_type: SourceType) -> RawSource:
    return RawSource(
        source_type=source_type,
        url=f"https://x.test/{key}",
        title=f"Source {key}",
        author=None,
        text="body " * 400,
        metadata={},
        identifiers=Identifiers.build(doi=f"10.1234/{key}"),
    )


def _validated(raw: RawSource, concepts: list[str]) -> ValidatedSource:
    return ValidatedSource(
        raw=raw,
        quality_score=8.0,
        relevance_score=8.0,
        content_type="paper",
        difficulty=3,
        key_claims=["a claim"],
        covered_concepts=concepts,
        source_tier="primary",
        validator_model="haiku",
    )


class _Loop:
    """Drives ``_run_discovery`` with the inside of a round replaced.

    ``covered(round_n)`` decides which concepts that round's accepted sources
    cover, which is what makes the coverage target reachable or not.
    """

    def __init__(
        self,
        covered,
        *,
        per_round: int = 6,
        accepted_per_round: int = 5,
        snowball_candidates: list | None = None,
    ) -> None:
        self.covered = covered
        self.per_round = per_round
        self.accepted_per_round = accepted_per_round
        self.snowball_candidates = snowball_candidates or []
        self.rounds_run: list[int] = []
        self.extras_seen: list[int] = []
        self.caps_seen: list[dict] = []
        self.events: list[dict] = []

    async def _round(
        self, topic, plan, queries, must_have, budget, budget_usd, seen, extra,
        caps, type_counts, on_event, n, batched,
    ):
        self.rounds_run.append(n)
        self.extras_seen.append(len(extra))
        self.caps_seen.append(dict(caps))
        return (
            [_raw(f"{n}-{i}", _TYPES[i % len(_TYPES)]) for i in range(self.per_round)],
            Decimal("0.05"),
        )

    async def _validate(self, expert, topic, raws, concepts, on_event, n):
        accepted = [
            _validated(raw, self.covered(n)) for raw in raws[: self.accepted_per_round]
        ]
        return accepted, []

    async def run(self, expert: Expert, loop_enabled: bool = True):
        builder = ExpertBuilder(MagicMock())
        # Two loop-eligible fetchers, so a later round has somewhere to search.
        builder._fetchers = {"exa": (None, 5), "web": (None, 3)}
        builder._discovery_round = self._round
        builder._validate_round = self._validate

        async def _on_event(event: dict) -> None:
            self.events.append(event)

        with (
            patch(
                "peritus.experts.builder.feedback_queries",
                AsyncMock(return_value={c: [f"query for {c}"] for c in _CONCEPTS}),
            ),
            patch(
                "peritus.experts.builder.snowball",
                AsyncMock(return_value=self.snowball_candidates),
            ),
            patch("peritus.experts.builder.discovery_loop_enabled", lambda: loop_enabled),
        ):
            return await builder._run_discovery(expert, "Thomism", _PLAN, _on_event)

    def types(self) -> list[str]:
        return [e["type"] for e in self.events]


def _covers(*concepts: str):
    return lambda _round: list(concepts)


# ── stop conditions ──────────────────────────────────────────────────────────


async def test_the_loop_stops_as_soon_as_the_targets_are_met():
    """Round 0 covers one concept; round 1 closes the other, and nothing more
    is searched for — the search stopped because it was finished."""
    loop = _Loop(lambda n: ["analogy"] if n == 0 else _CONCEPTS)
    outcome = await loop.run(_expert())

    assert loop.rounds_run == [0, 1]
    assert outcome.stop_reason == STOP_TARGETS_MET
    assert outcome.rounds == 2
    assert outcome.coverage.met


async def test_a_corpus_that_never_closes_its_gaps_stops_at_the_round_limit():
    loop = _Loop(_covers("analogy"))
    outcome = await loop.run(_expert(ExpertTier.STANDARD))

    # STANDARD allows two rounds *after* the first.
    assert loop.rounds_run == [0, 1, 2]
    assert outcome.stop_reason == STOP_MAX_ROUNDS
    assert not outcome.coverage.met
    assert [c.concept for c in outcome.coverage.unmet] == ["participation"]


async def test_lite_runs_exactly_one_extra_round_so_its_cost_profile_does_not_move():
    loop = _Loop(_covers("analogy"))
    outcome = await loop.run(_expert(ExpertTier.LITE))
    assert loop.rounds_run == [0, 1]
    assert outcome.stop_reason == STOP_MAX_ROUNDS


async def test_pro_searches_further_than_standard():
    loop = _Loop(_covers("analogy"))
    outcome = await loop.run(_expert(ExpertTier.PRO))
    assert loop.rounds_run == [0, 1, 2, 3]
    assert outcome.rounds == 4


async def test_acceptance_collapse_stops_before_paying_for_more_of_the_same():
    """A round fetched real sources and validation wanted almost none of them.
    That is an exhausted search space, not an under-explored one, and another
    round is spend without return."""
    loop = _Loop(_covers("analogy"), per_round=10, accepted_per_round=1)
    outcome = await loop.run(_expert(ExpertTier.PRO))

    assert loop.rounds_run == [0]
    assert outcome.stop_reason == STOP_ACCEPTANCE_COLLAPSED


async def test_a_small_round_is_not_mistaken_for_a_collapse():
    """Below the sample size, a low acceptance rate is small numbers rather than
    evidence — three sources with one accepted must not end the search."""
    loop = _Loop(_covers("analogy"), per_round=3, accepted_per_round=1)
    outcome = await loop.run(_expert(ExpertTier.STANDARD))
    assert len(loop.rounds_run) > 1
    assert outcome.stop_reason != STOP_ACCEPTANCE_COLLAPSED


async def test_a_round_with_nowhere_left_to_search_stops_and_says_so():
    """No loop-eligible fetchers and no snowball candidates means a later round
    has no queries to run at all."""
    loop = _Loop(_covers("analogy"))
    builder_patch = patch("peritus.experts.builder.discovery_loop_enabled", lambda: True)

    builder = ExpertBuilder(MagicMock())
    builder._fetchers = {"gutenberg": (None, 4)}  # never a loop fetcher
    builder._discovery_round = loop._round
    builder._validate_round = loop._validate

    async def _on_event(event: dict) -> None:
        loop.events.append(event)

    with (
        builder_patch,
        patch("peritus.experts.builder.feedback_queries", AsyncMock(return_value={})),
        patch("peritus.experts.builder.snowball", AsyncMock(return_value=[])),
    ):
        outcome = await builder._run_discovery(_expert(), "Thomism", _PLAN, _on_event)

    assert loop.rounds_run == [0]
    assert outcome.stop_reason == STOP_NO_NEW_CANDIDATES
    assert outcome.rounds == 1, "a round that never ran is not a round that ran"


async def test_the_loop_can_be_switched_off_entirely():
    """BACKGROUND builds batch each round's validation separately, so three
    rounds could add hours of queueing to a build nobody is watching."""
    loop = _Loop(_covers("analogy"))
    outcome = await loop.run(_expert(), loop_enabled=False)

    assert loop.rounds_run == [0]
    assert outcome.stop_reason == STOP_LOOP_DISABLED


# ── what a later round is given ──────────────────────────────────────────────


async def test_later_rounds_receive_snowball_candidates():
    from peritus.sources.domain import SourceCandidate

    candidate = SourceCandidate(
        source_type=SourceType.OPENALEX,
        url="https://doi.org/10.5555/cited",
        title="A cited work",
        author=None,
        snippet="s",
        metadata={"discovered_via": "snowball:backward"},
        identifiers=Identifiers.build(doi="10.5555/cited"),
    )
    loop = _Loop(_covers("analogy"), snowball_candidates=[candidate])
    await loop.run(_expert())

    assert loop.extras_seen[0] == 0, "round 0 has no accepted corpus to snowball from"
    assert loop.extras_seen[1] == 1


async def test_the_seen_set_grows_so_later_rounds_do_not_refetch():
    """A candidate a round already fetched must not be re-fetched by the next
    one; otherwise the loop spends its rounds re-considering the same tail."""
    seen_sizes: list[int] = []
    loop = _Loop(_covers("analogy"))
    inner = loop._round

    async def _record(*args):
        # seen is the 8th positional argument; see _Loop._round.
        seen_sizes.append(len(args[6]))
        return await inner(*args)

    loop._round = _record
    await loop.run(_expert())

    assert seen_sizes[0] == 0
    assert seen_sizes[1] > 0


# ── what it reports ──────────────────────────────────────────────────────────


async def test_every_round_announces_itself_and_its_coverage():
    loop = _Loop(lambda n: ["analogy"] if n == 0 else _CONCEPTS)
    await loop.run(_expert())

    types = loop.types()
    assert types.count("round_started") == 2
    assert types.count("coverage_report") == 2
    assert types[-1] == "discovery_done"
    # A stage event per round: the meter attributes spend to whichever stage was
    # last announced, and round 1's triage happens after round 0's validate.
    assert types.count("stage") == 2


async def test_the_summary_carries_the_reason_and_the_final_coverage():
    loop = _Loop(_covers("analogy"))
    outcome = await loop.run(_expert())
    summary = outcome.summary()

    assert summary["stop_reason"] == STOP_MAX_ROUNDS
    assert summary["rounds"] == 3
    assert summary["accepted"] == 15
    assert summary["coverage"]["met"] is False
    assert summary["rubric_version"].startswith("v5")
    assert summary["budget_usd"] > 0


async def test_feedback_queries_are_reported_so_the_search_is_reproducible():
    loop = _Loop(_covers("analogy"))
    await loop.run(_expert())

    feedback = [e for e in loop.events if e["type"] == "feedback_queries"]
    assert feedback, "a round whose queries are not written down cannot be checked"
    assert feedback[0]["round"] == 1
    assert feedback[0]["queries"]


@pytest.mark.asyncio
async def test_the_source_ceiling_is_reported_as_itself_not_as_a_spent_budget():
    """Two different limits must not share one reason.

    A live PRO build stopped with `budget_exhausted` while $4.71 of its $7.00
    discovery budget was unspent — the count ceiling had filled. The stop reason
    is the only surface this loop publishes, so reporting the wrong limit makes
    it a false statement.
    """
    # LITE's count ceiling is 30; a round that fetches all of it leaves none.
    loop = _Loop(_covers("analogy"), per_round=30, accepted_per_round=25)
    outcome = await loop.run(_expert(ExpertTier.LITE))

    assert loop.rounds_run == [0]
    assert outcome.stop_reason == STOP_SOURCE_LIMIT
    # The money was never the constraint here.
    assert outcome.committed_usd < outcome.budget_usd


@pytest.mark.asyncio
async def test_caps_are_computed_once_and_their_counts_persist_across_rounds():
    """A cap applied per round is not a cap on the corpus.

    Recomputing per round would let a source type take its full share again in
    every round, which is exactly the flooding the cap exists to prevent — and
    it is the corpus, not the round, that a reader ends up questioning.
    """
    loop = _Loop(_covers("analogy"))
    await loop.run(_expert(ExpertTier.STANDARD))

    assert len(loop.caps_seen) > 1, "the test needs more than one round to be meaningful"
    assert all(c == loop.caps_seen[0] for c in loop.caps_seen), (
        "caps must be identical every round — they are a property of the build"
    )
    # And they are sized against the whole build, not one round's slice.
    assert sum(loop.caps_seen[0].values()) > 60


@pytest.mark.asyncio
async def test_budget_reserved_for_rejected_sources_is_released():
    """The estimate is made at fetch time, before anything is judged, so it
    covers every source fetched. Only the accepted ones are ever ingested, and
    holding the rejected ones' cost against the budget stops the loop about a
    rejection-rate early — measured live at $3.04 reserved of a $3.00 budget
    for 60 sources when only 48 would be ingested."""
    # 6 fetched per round, 2 accepted: two thirds of each round is rejected.
    loop = _Loop(_covers("analogy"), per_round=6, accepted_per_round=2)
    outcome = await loop.run(_expert(ExpertTier.STANDARD))

    rounds = len(loop.rounds_run)
    reserved_at_fetch = 0.05 * rounds  # what _discovery_round reported
    assert outcome.committed_usd < reserved_at_fetch, (
        "the rejected sources' reservation must be given back"
    )
    assert outcome.committed_usd > 0, "the accepted sources still cost something"
