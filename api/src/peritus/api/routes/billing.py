"""Credit state, the ledger, and the one admin endpoint that issues credits.

Split from `routes/experts.py` because none of it is about an expert: it is the
account's plan and balance, which the client reads before it offers to build
anything.

There is no payment provider. `POST /admin/credits/grant` is the entire billing
integration today — a founder granting credits to a customer who asked — and a
provider webhook would call `EntitlementService.grant` in exactly the same way.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from peritus.api.deps import CurrentUser, Entitlements
from peritus.api.schemas.experts import (
    CreditStateOut,
    GrantCreditsRequest,
    LedgerEntryOut,
    PlanOut,
    TierPriceOut,
)
from peritus.billing.domain import (
    PLANS,
    credit_cost,
    get_plan,
    spend_cap_usd,
)
from peritus.billing.settings import settings as billing_settings
from peritus.core.logging import get_logger
from peritus.experts.domain import ExpertTier

logger = get_logger(__name__)

router = APIRouter(tags=["billing"])


def _plan_out(plan) -> PlanOut:
    return PlanOut(
        name=plan.name,
        display_name=plan.display_name,
        included_credits=plan.included_credits,
        allowed_tiers=[t.value for t in plan.allowed_tiers],
        description=plan.description,
    )


@router.get("/billing/me", response_model=CreditStateOut)
async def get_credit_state(user: CurrentUser, entitlements: Entitlements):
    """The caller's plan, credit balance, and the price of each tier.

    Provisions the account on first call, which is where the free plan's signup
    grant lands. Chat is never gated by anything here.
    """
    state = await entitlements.credit_state(user.id, user.email)
    return CreditStateOut(
        plan=_plan_out(state.plan),
        balance=state.balance,
        granted=state.granted,
        consumed=state.consumed,
        held=state.held,
        credits_enforced=billing_settings.CREDITS_ENFORCED,
        tiers=[
            TierPriceOut(
                tier=tier.value,
                credit_cost=credit_cost(tier),
                spend_cap_usd=spend_cap_usd(tier, state.plan, state.spend_cap_override_usd),
                included_in_plan=tier in state.plan.allowed_tiers,
            )
            for tier in ExpertTier
        ],
    )


@router.get("/billing/ledger", response_model=list[LedgerEntryOut])
async def get_credit_ledger(
    user: CurrentUser,
    entitlements: Entitlements,
    limit: int = Query(50, ge=1, le=200),
):
    entries = await entitlements.ledger(user.id, limit)
    return [
        LedgerEntryOut(
            id=e.id,
            entry_type=e.entry_type.value,
            delta=e.delta,
            job_id=e.job_id,
            tier=e.tier,
            reason=e.reason,
            source=e.source,
            cost_usd=e.cost_usd,
            created_at=e.created_at,
        )
        for e in entries
    ]


@router.post("/admin/credits/grant")
async def grant_credits(
    req: GrantCreditsRequest, user: CurrentUser, service: Entitlements
) -> dict[str, Any]:
    """Issue credits by hand. Admin only.

    This is the entire billing integration today: no payment provider, just a
    founder granting credits to a customer who asked. A provider webhook would
    call ``EntitlementService.grant`` in exactly this way.
    """
    if not user.is_admin:
        raise HTTPException(status_code=404, detail="Not found")
    owner_id = await service.resolve_owner(req.owner)
    if not owner_id:
        raise HTTPException(status_code=404, detail=f"No account matching {req.owner!r}")
    if req.plan:
        if req.plan not in PLANS:
            raise HTTPException(status_code=400, detail=f"Unknown plan {req.plan!r}")
        await service.set_plan(owner_id, get_plan(req.plan), actor=user.email)
    balance = await service.grant(
        owner_id,
        req.amount,
        reason=req.reason or "Manual grant",
        actor=user.email or user.id,
        email=req.owner if "@" in req.owner else None,
    )
    return {"owner_id": owner_id, "balance": balance, "granted": req.amount}
