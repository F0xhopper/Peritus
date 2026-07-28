"""Credit ledger and entitlement tests.

The ledger is the money, so the invariants that matter are: balance is always
the sum of its own history, a job is charged exactly once no matter how many
times it is submitted, and a build that produces nothing is refunded exactly
once.

DB-backed (needs ``PERITUS_TEST_DATABASE_URL``); skipped otherwise, like the
other queue/repository suites.
"""

import pytest

from peritus.billing.domain import FREE, LAB, InsufficientCredits, TierNotInPlan
from peritus.billing.repository import BillingRepository
from peritus.billing.service import EntitlementService
from peritus.experts.domain import ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.jobs.repository import JobRepository

pytestmark = pytest.mark.asyncio

OWNER = "33333333-3333-3333-3333-333333333333"
OTHER = "44444444-4444-4444-4444-444444444444"


async def _job(pool, name: str = "credited", tier: ExpertTier = ExpertTier.LITE):
    expert = await ExpertRepository(pool).create(
        name=name, topic=name, tier=tier, owner_id=OWNER
    )
    return await JobRepository(pool).enqueue(expert.id, tier.value, None, max_attempts=3)


# ── provisioning ────────────────────────────────────────────────────────────

async def test_account_is_provisioned_once_with_its_signup_grant(db_pool):
    service = EntitlementService(db_pool)
    first = await service.credit_state(OWNER, "alice@lab.edu")
    second = await service.credit_state(OWNER, "alice@lab.edu")

    assert first.plan is FREE
    assert first.balance == FREE.included_credits
    # Signing in again must not re-trigger the welcome grant.
    assert second.balance == first.balance


async def test_balance_is_the_sum_of_the_ledger(db_pool):
    service = EntitlementService(db_pool)
    await service.ensure_account(OWNER)
    await service.grant(OWNER, 10, reason="pilot", actor="cli")
    await service.grant(OWNER, -3, reason="clawback", actor="cli")

    repo = BillingRepository(db_pool)
    assert await repo.balance(OWNER) == FREE.included_credits + 7


async def test_grant_by_email_resolves_the_account(db_pool):
    service = EntitlementService(db_pool)
    await service.ensure_account(OWNER, "alice@lab.edu")
    assert await service.resolve_owner("alice@lab.edu") == OWNER
    assert await service.resolve_owner("nobody@example.com") is None


# ── authorisation ───────────────────────────────────────────────────────────

async def test_build_is_denied_without_enough_credits(db_pool):
    service = EntitlementService(db_pool)
    await service.ensure_account(OWNER)
    # The free plan's grant buys one lite build, not a standard one — and
    # standard isn't on the plan either, so that denial fires first.
    with pytest.raises(TierNotInPlan):
        await service.authorize_build(OWNER, ExpertTier.STANDARD)

    await service.set_plan(OWNER, LAB)
    with pytest.raises(InsufficientCredits) as exc:
        await service.authorize_build(OWNER, ExpertTier.PRO)
    payload = exc.value.to_payload()["error"]
    assert payload["code"] == "insufficient_credits"
    assert payload["required_credits"] == 8


async def test_hold_is_idempotent_per_job(db_pool):
    """A double-submitted build must be charged once, not twice."""
    service = EntitlementService(db_pool)
    await service.ensure_account(OWNER)
    await service.grant(OWNER, 10, reason="test")
    before = (await service.credit_state(OWNER)).balance

    job = await _job(db_pool)
    await service.hold_for_job(OWNER, job.id, ExpertTier.LITE)
    await service.hold_for_job(OWNER, job.id, ExpertTier.LITE)
    await service.hold_for_job(OWNER, job.id, ExpertTier.LITE)

    after = (await service.credit_state(OWNER)).balance
    assert after == before - 1


async def test_hold_refuses_when_the_balance_runs_out(db_pool):
    service = EntitlementService(db_pool)
    await service.ensure_account(OWNER)
    # Spend the signup grant down to zero.
    await service.grant(OWNER, -FREE.included_credits, reason="zero out")
    job = await _job(db_pool)
    with pytest.raises(InsufficientCredits):
        await service.hold_for_job(OWNER, job.id, ExpertTier.LITE)
    assert (await service.credit_state(OWNER)).balance == 0


async def test_held_credits_are_reported_while_a_build_is_in_flight(db_pool):
    service = EntitlementService(db_pool)
    await service.ensure_account(OWNER)
    await service.grant(OWNER, 10, reason="test")
    job = await _job(db_pool)
    await service.hold_for_job(OWNER, job.id, ExpertTier.LITE)

    state = await service.credit_state(OWNER)
    assert state.held == 1
    assert state.consumed == 1


# ── settlement ──────────────────────────────────────────────────────────────

async def test_failed_build_is_refunded_exactly_once(db_pool):
    """The over-cap / failure policy: no usable expert means no charge."""
    service = EntitlementService(db_pool)
    await service.ensure_account(OWNER)
    await service.grant(OWNER, 10, reason="test")
    before = (await service.credit_state(OWNER)).balance

    job = await _job(db_pool)
    await service.hold_for_job(OWNER, job.id, ExpertTier.LITE)
    assert (await service.credit_state(OWNER)).balance == before - 1

    assert await service.refund_job(job.id, "Build failed") == 1
    # A retried refund (worker + cancel endpoint can both fire) must be a no-op.
    assert await service.refund_job(job.id, "Build failed again") == 0
    assert (await service.credit_state(OWNER)).balance == before


async def test_refunding_a_job_with_no_hold_is_a_no_op(db_pool):
    service = EntitlementService(db_pool)
    job = await _job(db_pool, name="unheld")
    assert await service.refund_job(job.id, "nothing to refund") == 0


async def test_successful_build_keeps_the_hold_and_records_its_cost(db_pool):
    service = EntitlementService(db_pool)
    await service.ensure_account(OWNER)
    await service.grant(OWNER, 10, reason="test")
    job = await _job(db_pool)
    await service.hold_for_job(OWNER, job.id, ExpertTier.LITE)
    before = (await service.credit_state(OWNER)).balance

    await service.settle_job(job.id, 0.83)

    assert (await service.credit_state(OWNER)).balance == before
    entry = next(e for e in await service.ledger(OWNER) if e.job_id == job.id)
    assert entry.cost_usd == pytest.approx(0.83)


# ── metering persistence ────────────────────────────────────────────────────

async def test_usage_rolls_up_onto_the_job_and_breaks_down_by_stage(db_pool):
    from peritus.billing.metering import BuildMeter, Stage

    repo = BillingRepository(db_pool)
    job = await _job(db_pool, name="metered")

    meter = BuildMeter(job_id=job.id, expert_id=job.expert_id, owner_id=OWNER)
    meter.set_stage(Stage.CONTEXTUALIZATION)
    meter.record_message(
        "claude-haiku-4-5",
        type("U", (), {"input_tokens": 1_000_000, "output_tokens": 0,
                       "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0})(),
        batch=True,
    )
    meter.record_embedding("text-embedding-3-large", 100_000)

    await repo.record_usage(job.id, job.expert_id, OWNER, meter.drain())

    breakdown = await repo.job_usage_breakdown(job.id)
    # 1M Haiku input at batch rate = $0.50; 100k embeddings = $0.013.
    assert breakdown["cost_usd"] == pytest.approx(0.513, abs=1e-3)
    assert breakdown["embed_tokens"] == 100_000
    stages = {r["stage"] for r in breakdown["by_stage"]}
    assert stages == {Stage.CONTEXTUALIZATION}
    modes = {r["mode"] for r in breakdown["by_model"]}
    assert "batch" in modes


async def test_repeated_flushes_accumulate_rather_than_overwrite(db_pool):
    from peritus.billing.metering import BuildMeter, Stage

    repo = BillingRepository(db_pool)
    job = await _job(db_pool, name="twice-flushed")
    meter = BuildMeter(job_id=job.id, expert_id=job.expert_id, owner_id=OWNER)
    usage = type("U", (), {"input_tokens": 1_000_000, "output_tokens": 0,
                           "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0})

    meter.set_stage(Stage.VALIDATION)
    meter.record_message("claude-haiku-4-5", usage(), batch=False)
    await repo.record_usage(job.id, job.expert_id, OWNER, meter.drain())
    meter.record_message("claude-haiku-4-5", usage(), batch=False)
    await repo.record_usage(job.id, job.expert_id, OWNER, meter.drain())

    breakdown = await repo.job_usage_breakdown(job.id)
    assert breakdown["cost_usd"] == pytest.approx(2.0, abs=1e-3)
    assert breakdown["input_tokens"] == 2_000_000


async def test_cap_snapshot_and_exceeded_marker_are_recorded(db_pool):
    repo = BillingRepository(db_pool)
    job = await _job(db_pool, name="capped")

    await repo.set_job_cap(job.id, 1.25)
    await repo.mark_cap_exceeded(job.id)

    breakdown = await repo.job_usage_breakdown(job.id)
    assert breakdown["spend_cap_usd"] == pytest.approx(1.25)
    assert breakdown["cap_exceeded_at"] is not None
