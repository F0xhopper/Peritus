"""API contract tests for the expert build endpoint and tier field exposure.

DB and builder are mocked so no infrastructure is required.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier


def _make_expert(tier: ExpertTier = ExpertTier.STANDARD, name: str = "stoicism") -> Expert:
    return Expert(
        id=1,
        name=name,
        topic=name,
        status=ExpertStatus.READY,
        tier=tier,
        config=ExpertConfig.from_tier(tier),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def app():
    from peritus.api.app import create_app
    return create_app()


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Test 12: invalid tier rejected (no mocks needed — Pydantic validates first) ──

@pytest.mark.asyncio
async def test_invalid_tier_rejected(client):
    with patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()):
        resp = await client.post("/experts/build", json={"topic": "stoicism", "tier": "ultra"})
    assert resp.status_code == 422


# ── Test 13: default tier is standard ──

def test_default_tier_is_standard():
    from peritus.api.schemas.experts import BuildRequest
    req = BuildRequest(topic="stoicism")
    assert req.tier == ExpertTier.STANDARD


# ── Test 11: valid tier accepted ──

@pytest.mark.asyncio
async def test_valid_tier_accepted(client):
    expert = _make_expert(ExpertTier.LITE, name="stoicism")

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
        patch("peritus.api.routes.experts.ExpertBuilder") as MockBuilder,
    ):
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock(return_value=expert)
        MockRepo.return_value = mock_repo

        # Builder.build hangs the SSE stream — just don't let it proceed
        mock_builder = AsyncMock()
        mock_builder.build = AsyncMock(side_effect=Exception("abort"))
        MockBuilder.return_value = mock_builder

        resp = await client.post(
            "/experts/build",
            json={"topic": "stoicism", "tier": "lite"},
        )

    # SSE stream opens successfully (200), even if the background task fails
    assert resp.status_code == 200


# ── Test 14: tier surfaced in GET response ──

@pytest.mark.asyncio
async def test_tier_in_get_response(client):
    expert = _make_expert(ExpertTier.LITE, name="stoicism")

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
    ):
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=expert)
        MockRepo.return_value = mock_repo

        resp = await client.get("/experts/stoicism")

    assert resp.status_code == 200
    assert resp.json()["tier"] == "lite"
