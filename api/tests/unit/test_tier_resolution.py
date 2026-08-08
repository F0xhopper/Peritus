"""EntitlementService.resolve_tier — the server-side answer to "just a topic".

No DB: credit_state is patched with a canned CreditState, so these pin the
selection policy itself — deepest allowed tier the balance can pay for, with a
sane floor when nothing is affordable.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from peritus.billing.domain import FREE, LAB, STARTER, CreditState
from peritus.billing.service import EntitlementService
from peritus.experts.domain import ExpertTier

pytestmark = pytest.mark.asyncio

OWNER = "00000000-0000-0000-0000-000000000000"


def _state(plan, balance: int) -> CreditState:
    return CreditState(
        owner_id=OWNER, plan=plan, balance=balance, granted=balance, consumed=0, held=0
    )


def _service() -> EntitlementService:
    return EntitlementService(MagicMock())


async def _resolve(plan, balance: int) -> ExpertTier:
    service = _service()
    with patch.object(
        EntitlementService, "credit_state", AsyncMock(return_value=_state(plan, balance))
    ):
        return await service.resolve_tier(OWNER, None)


async def test_explicit_tier_is_honoured_without_a_lookup():
    service = _service()
    with patch.object(EntitlementService, "credit_state", AsyncMock()) as state:
        tier = await service.resolve_tier(OWNER, ExpertTier.PRO)
    assert tier is ExpertTier.PRO
    state.assert_not_awaited()


async def test_free_plan_resolves_to_lite():
    """The whole point: a fresh free account posting only a topic must land on
    the one tier its plan can build, not the old unbuildable standard default."""
    assert await _resolve(FREE, balance=1) is ExpertTier.LITE


async def test_lab_plan_with_a_full_balance_takes_the_deepest_tier():
    assert await _resolve(LAB, balance=100) is ExpertTier.PRO


async def test_resolution_steps_down_to_what_the_balance_affords():
    # Lab allows pro (8 credits) but the balance only covers standard (3).
    assert await _resolve(LAB, balance=5) is ExpertTier.STANDARD


async def test_broke_account_falls_back_to_the_cheapest_allowed_tier():
    """Nothing is affordable: return the smallest allowed tier so the 402 that
    follows quotes the smallest viable purchase."""
    assert await _resolve(STARTER, balance=0) is ExpertTier.LITE


async def test_unenforced_credits_default_to_standard():
    service = _service()
    with patch("peritus.billing.service.settings") as mock_settings:
        mock_settings.CREDITS_ENFORCED = False
        tier = await service.resolve_tier(OWNER, None)
    assert tier is ExpertTier.STANDARD
