"""The entitlement seam.

Everything that decides "may this build run, and what may it spend" goes through
here, so there is exactly one place to change when a payment provider is finally
chosen. No provider is integrated: credits enter the system through
:meth:`EntitlementService.grant`, which the CLI and the admin endpoint call, and
which a webhook would call in exactly the same way.
"""

import asyncpg

from peritus.billing.domain import (
    DEFAULT_PLAN,
    CreditSource,
    CreditState,
    InsufficientCredits,
    LedgerEntry,
    Plan,
    TierNotInPlan,
    credit_cost,
    get_plan,
    spend_cap_usd,
)
from peritus.billing.repository import BillingRepository
from peritus.billing.settings import settings
from peritus.core.logging import get_logger
from peritus.experts.domain import ExpertTier

logger = get_logger(__name__)


class EntitlementService:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._repo = BillingRepository(pool)

    # ── account lifecycle ───────────────────────────────────────────────────

    async def ensure_account(self, owner_id: str, email: str | None = None) -> dict:
        """Provision the account on first touch, with its plan's signup grant."""
        return await self._repo.ensure_account(
            owner_id,
            email=email,
            plan=DEFAULT_PLAN.name,
            signup_credits=DEFAULT_PLAN.included_credits,
        )

    async def credit_state(self, owner_id: str, email: str | None = None) -> CreditState:
        account = await self.ensure_account(owner_id, email)
        totals = await self._repo.credit_totals(owner_id)
        override = account.get("spend_cap_override_usd")
        return CreditState(
            owner_id=owner_id,
            plan=get_plan(account.get("plan")),
            balance=totals["balance"],
            granted=totals["granted"],
            consumed=totals["consumed"],
            held=totals["held"],
            spend_cap_override_usd=float(override) if override is not None else None,
            created_at=account.get("created_at"),
        )

    async def ledger(self, owner_id: str, limit: int = 50) -> list[LedgerEntry]:
        return await self._repo.list_ledger(owner_id, limit)

    # ── authorisation ───────────────────────────────────────────────────────

    async def resolve_tier(
        self, owner_id: str, requested: ExpertTier | None, email: str | None = None
    ) -> ExpertTier:
        """Pick the tier for a build that didn't name one.

        An explicit request is honoured as-is (and judged by ``authorize_build``).
        With no request, the deepest tier the caller's plan allows *and* their
        balance can pay for wins — so a bare ``{"topic": ...}`` builds at the
        best depth the account supports instead of 402ing on a fixed default.
        When nothing is affordable, the plan's cheapest tier is returned so the
        denial that follows names the smallest viable purchase, not the largest.
        """
        if requested is not None:
            return requested
        if not settings.CREDITS_ENFORCED:
            return ExpertTier.STANDARD
        state = await self.credit_state(owner_id, email)
        allowed = state.plan.allowed_tiers or (ExpertTier.LITE,)
        for tier in sorted(allowed, key=credit_cost, reverse=True):
            if credit_cost(tier) <= state.balance:
                return tier
        return min(allowed, key=credit_cost)

    async def authorize_build(
        self, owner_id: str, tier: ExpertTier, email: str | None = None
    ) -> CreditState:
        """Check that a build at this tier is allowed. Raises on denial.

        Called *before* the job row exists, so it can 402 without leaving an
        orphaned job behind. It is a check, not a charge — the charge is
        :meth:`hold_for_job`, which re-checks under a row lock. The gap between
        the two is deliberate and safe: the authoritative test is the one that
        writes.
        """
        state = await self.credit_state(owner_id, email)
        if not settings.CREDITS_ENFORCED:
            return state
        if tier not in state.plan.allowed_tiers:
            raise TierNotInPlan(tier=tier, plan=state.plan)
        required = credit_cost(tier)
        if state.balance < required:
            raise InsufficientCredits(
                required=required, available=state.balance, tier=tier, plan=state.plan
            )
        return state

    async def hold_for_job(
        self, owner_id: str, job_id: int, tier: ExpertTier
    ) -> None:
        """Take the credit hold for an enqueued job. Raises if it cannot be paid.

        Idempotent per job: a hold already recorded for this job id is accepted
        as-is, so attaching to an in-flight build (or a retried enqueue) never
        double-charges.
        """
        required = credit_cost(tier)
        placed, balance = await self._repo.hold_for_job(
            owner_id,
            job_id,
            required,
            tier.value,
            require_balance=settings.CREDITS_ENFORCED,
        )
        if not placed:
            state = await self.credit_state(owner_id)
            raise InsufficientCredits(
                required=required, available=balance, tier=tier, plan=state.plan
            )
        logger.info(
            "Held %d credit(s) for job %d (owner=%s, tier=%s)",
            required, job_id, owner_id, tier.value,
        )

    async def cap_for_build(
        self, owner_id: str, tier: ExpertTier
    ) -> float:
        """The per-build spend ceiling that applies to this owner at this tier."""
        account = await self._repo.get_account(owner_id)
        plan = get_plan(account.get("plan") if account else None)
        override = account.get("spend_cap_override_usd") if account else None
        return spend_cap_usd(
            tier, plan, float(override) if override is not None else None
        )

    async def record_job_cap(self, job_id: int, cap_usd: float | None) -> None:
        """Snapshot the cap onto the job so a later price change can't re-judge it."""
        await self._repo.set_job_cap(job_id, cap_usd)

    # ── settlement ──────────────────────────────────────────────────────────

    async def refund_job(self, job_id: int, reason: str) -> int:
        """Return a job's hold. Idempotent; returns credits refunded.

        **The over-cap / failure policy.** A build that does not produce a usable
        expert is refunded in full — permanent failure, user cancellation, or a
        spend-cap abort alike. The user gets nothing, so they pay nothing; the
        real provider spend is ours to absorb, and the per-build cap is what
        bounds how much that can ever be. Retries inside one job keep the same
        hold, so a build that eventually succeeds is charged exactly once.
        """
        refunded = await self._repo.refund_job(job_id, reason)
        if refunded:
            logger.info("Refunded %d credit(s) for job %d: %s", refunded, job_id, reason)
        return refunded

    async def settle_job(self, job_id: int, cost_usd: float) -> None:
        """Record realised spend against a succeeded job's hold, for reporting."""
        await self._repo.record_job_cost(job_id, cost_usd)

    # ── admin / manual issuance ─────────────────────────────────────────────

    async def grant(
        self,
        owner_id: str,
        amount: int,
        reason: str | None = None,
        actor: str | None = None,
        source: str = CreditSource.MANUAL.value,
        external_ref: str | None = None,
        email: str | None = None,
    ) -> int:
        """Issue credits by hand. Returns the new balance.

        This is the whole "billing integration" for now: a founder runs
        ``peritus credits grant`` (or POSTs the admin endpoint) and the customer
        can build. A payment provider, when chosen, calls this same method from
        its webhook with its own ``source``/``external_ref``.
        """
        await self.ensure_account(owner_id, email)
        balance = await self._repo.grant(
            owner_id, amount, reason=reason, source=source, actor=actor,
            external_ref=external_ref,
        )
        logger.info(
            "Granted %d credit(s) to %s by %s (%s) — balance now %d",
            amount, owner_id, actor or "unknown", reason or "no reason given", balance,
        )
        return balance

    async def set_plan(self, owner_id: str, plan: Plan, actor: str | None = None) -> None:
        await self.ensure_account(owner_id)
        await self._repo.set_plan(owner_id, plan.name)
        logger.info("Set plan for %s to %s (by %s)", owner_id, plan.name, actor or "unknown")

    async def resolve_owner(self, identifier: str) -> str | None:
        """Resolve a CLI-supplied user id or email to an owner id."""
        identifier = identifier.strip()
        if "@" in identifier:
            account = await self._repo.find_account_by_email(identifier)
            return str(account["owner_id"]) if account else None
        return identifier

    async def list_accounts(self, limit: int = 100) -> list[dict]:
        return await self._repo.list_accounts(limit)

    async def usage_for_job(self, job_id: int) -> dict:
        return await self._repo.job_usage_breakdown(job_id)
