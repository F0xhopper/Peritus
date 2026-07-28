"""Billing, entitlements, and build cost metering.

Three concerns, deliberately separated:

- :mod:`peritus.billing.pricing` — tokens to dollars, from observed usage.
- :mod:`peritus.billing.metering` — what a running build is actually spending,
  attributed per stage, plus the per-build spend ceiling.
- :mod:`peritus.billing.service` — whether a build may start at all, and the
  credit ledger behind that answer.

No payment provider is integrated. Credits enter through
``EntitlementService.grant``; that method is the seam a provider webhook would
call, and nothing else in the codebase needs to know one exists.
"""

from peritus.billing.domain import (
    PLANS,
    CreditState,
    EntitlementError,
    InsufficientCredits,
    Plan,
    SpendCapExceeded,
    TierNotInPlan,
    credit_cost,
    get_plan,
    spend_cap_usd,
)
from peritus.billing.metering import BuildMeter, Stage, install_instrumentation
from peritus.billing.service import EntitlementService

__all__ = [
    "PLANS",
    "BuildMeter",
    "CreditState",
    "EntitlementError",
    "EntitlementService",
    "InsufficientCredits",
    "Plan",
    "SpendCapExceeded",
    "Stage",
    "TierNotInPlan",
    "credit_cost",
    "get_plan",
    "install_instrumentation",
    "spend_cap_usd",
]
