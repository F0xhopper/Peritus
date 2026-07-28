"""Entitlements: plans, credits, and the errors a denied build raises.

**The credit model, and why.**

A build is the capex. It is paid for in *credits*, an integer currency, not in
dollars — dollars are what Peritus spends, credits are what the customer holds.
Keeping them separate means the price ladder can be re-tuned (a cheaper model, a
better cache hit rate) without repricing anything a customer already bought, and
a customer's balance never moves because a provider changed a rate card.

The ledger is append-only: balance is ``SUM(delta)``. There is no mutable
balance column to drift, and every movement carries who/why/when. That matches
the product's own pitch — the corpus is auditable, so the account should be too.

A build takes a **hold** at the moment the job is ENQUEUED, keyed by job id with
a unique index, which makes authorisation idempotent under double-submit. The
hold is refunded in full if the build does not produce a usable expert (failure,
cancellation, or spend-cap abort). We eat the cost of our own failures; the cap
bounds how much that can be.

Chat is free and ungated — over catalog experts and over your own. The corpus
already exists; retrieval is cheap relative to a build, and the free tier's
whole job is to get someone to a good answer in five seconds.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from peritus.billing.settings import settings
from peritus.experts.domain import ExpertTier, tier_economics


class LedgerEntryType(StrEnum):
    GRANT  = "grant"    # (+) issuance: admin grant, signup, plan renewal
    HOLD   = "hold"     # (-) reservation taken at build enqueue
    REFUND = "refund"   # (+) hold returned; build produced nothing usable
    ADJUST = "adjust"   # (±) manual correction


class CreditSource(StrEnum):
    """Where a ledger entry came from.

    The provider-agnostic seam. No payment provider is integrated; when one is
    chosen, its webhook writes ``source='<provider>'`` plus ``external_ref`` and
    nothing else in this module changes.
    """

    MANUAL = "manual"   # issued by hand (CLI / admin endpoint)
    SIGNUP = "signup"   # automatic grant on account provisioning
    PLAN   = "plan"     # plan renewal / entitlement top-up
    SYSTEM = "system"   # refunds and corrections made by the system


@dataclass(frozen=True)
class Plan:
    """A named entitlement bundle.

    Plans live in code, not in the database: they are product decisions that
    should be reviewable in a diff, and an account only stores its plan *name*.
    """

    name: str
    display_name: str
    # Credits granted when an account is first put on this plan.
    included_credits: int
    # Tiers a build on this plan may request.
    allowed_tiers: tuple[ExpertTier, ...]
    # Multiplier on the tier's per-build spend cap. A higher plan is trusted
    # with a longer leash on the same tier.
    spend_cap_multiplier: float = 1.0
    description: str = ""


FREE = Plan(
    name="free",
    display_name="Free",
    included_credits=settings.FREE_SIGNUP_CREDITS,
    allowed_tiers=(ExpertTier.LITE,),
    description=(
        "Unlimited chat over the public catalog. One Lite build to try building "
        "your own corpus."
    ),
)

STARTER = Plan(
    name="starter",
    display_name="Starter",
    included_credits=20,
    allowed_tiers=(ExpertTier.LITE, ExpertTier.STANDARD),
    description="For a single researcher running reviews on their own corpora.",
)

LAB = Plan(
    name="lab",
    display_name="Lab",
    included_credits=100,
    allowed_tiers=(ExpertTier.LITE, ExpertTier.STANDARD, ExpertTier.PRO),
    spend_cap_multiplier=1.5,
    description="For a group: Pro-depth builds and a higher per-build ceiling.",
)

PLANS: dict[str, Plan] = {p.name: p for p in (FREE, STARTER, LAB)}
DEFAULT_PLAN = FREE


def get_plan(name: str | None) -> Plan:
    """Resolve a plan name, falling back to free for unknown/legacy values."""
    if not name:
        return DEFAULT_PLAN
    return PLANS.get(name, DEFAULT_PLAN)


def credit_cost(tier: ExpertTier) -> int:
    """Credits one build at this tier consumes."""
    return tier_economics(tier).credit_cost


_CAP_OVERRIDES: dict[ExpertTier, float] = {
    ExpertTier.LITE: settings.TIER_CAP_LITE_USD,
    ExpertTier.STANDARD: settings.TIER_CAP_STANDARD_USD,
    ExpertTier.PRO: settings.TIER_CAP_PRO_USD,
}


def spend_cap_usd(
    tier: ExpertTier,
    plan: Plan = DEFAULT_PLAN,
    account_override_usd: float | None = None,
) -> float:
    """The per-build spend ceiling that applies to one build.

    Precedence: per-account override → env override for the tier → tier default,
    then scaled by the plan's multiplier (an account override is taken as final
    and is not scaled).
    """
    if account_override_usd is not None and account_override_usd > 0:
        return float(account_override_usd)
    base = _CAP_OVERRIDES.get(tier) or 0.0
    if base <= 0:
        base = tier_economics(tier).spend_cap_usd
    return base * plan.spend_cap_multiplier


@dataclass(frozen=True)
class CreditState:
    """What the client needs to render the credit UI."""

    owner_id: str
    plan: Plan
    balance: int
    granted: int      # lifetime credits in
    consumed: int     # lifetime credits out (net of refunds)
    held: int         # credits currently reserved by in-flight builds
    spend_cap_override_usd: float | None = None
    created_at: datetime | None = None


@dataclass
class LedgerEntry:
    id: int
    owner_id: str
    entry_type: LedgerEntryType
    delta: int
    job_id: int | None
    tier: str | None
    reason: str | None
    source: str
    external_ref: str | None
    actor: str | None
    cost_usd: float | None
    created_at: datetime


# ── denial ───────────────────────────────────────────────────────────────────


class EntitlementError(Exception):
    """A build was refused for entitlement reasons.

    Carries a structured, renderable payload rather than a prose message: the
    client should be able to draw the right UI (an upgrade prompt vs. a
    "request credits" prompt vs. "this tier isn't on your plan") without
    parsing English.
    """

    #: Machine-readable code the client switches on.
    code = "entitlement_denied"
    #: HTTP status the API layer maps this to.
    status_code = 402

    def __init__(self, message: str, **details) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, **self.details}}


class InsufficientCredits(EntitlementError):
    code = "insufficient_credits"

    def __init__(
        self,
        *,
        required: int,
        available: int,
        tier: ExpertTier,
        plan: Plan,
    ) -> None:
        super().__init__(
            f"This {tier.value} build costs {required} credit"
            f"{'s' if required != 1 else ''}, and you have {available}.",
            required_credits=required,
            available_credits=available,
            tier=tier.value,
            plan=plan.name,
            # A hint for the UI, not a route: there is no checkout yet, so the
            # only way to get credits today is to ask.
            remedy={
                "kind": "request_credits",
                "label": "Request credits",
                "detail": "Credits are issued manually while billing is in private beta.",
            },
        )


class TierNotInPlan(EntitlementError):
    code = "tier_not_in_plan"

    def __init__(self, *, tier: ExpertTier, plan: Plan) -> None:
        allowed = [t.value for t in plan.allowed_tiers]
        super().__init__(
            f"The {tier.value} tier is not available on the {plan.display_name} plan.",
            tier=tier.value,
            plan=plan.name,
            allowed_tiers=allowed,
            remedy={
                "kind": "change_tier",
                "label": f"Build at {allowed[-1]} instead" if allowed else "Upgrade",
                "detail": "Pick an included tier, or ask for an upgrade.",
            },
        )


class SpendCapExceeded(Exception):
    """A running build crossed its per-build spend ceiling.

    Raised inside the worker, not the API. Terminal by construction: a retry
    would spend the same money again, so the job is failed rather than requeued
    and the credit hold is refunded.
    """

    def __init__(self, spent_usd: float, cap_usd: float) -> None:
        super().__init__(
            f"Build exceeded its spend cap: ${spent_usd:.2f} of ${cap_usd:.2f}."
        )
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd
