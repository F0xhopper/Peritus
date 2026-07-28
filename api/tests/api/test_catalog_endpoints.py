"""API contract tests for the public catalog and billing endpoints.

DB and services are mocked, so these pin the *contract* the frontend builds
against: which fields a catalog card carries, what a public response must never
leak, and what a credit-denial body looks like.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from peritus.billing.domain import FREE, CreditState
from peritus.experts.domain import (
    CatalogMeta,
    Expert,
    ExpertStatus,
    ExpertTier,
    ExpertVisibility,
)

ADMIN_ID = "00000000-0000-0000-0000-000000000000"


def _make_expert(
    name: str = "stoicism",
    visibility: ExpertVisibility = ExpertVisibility.PUBLIC,
    readiness: str = "graph_ready",
) -> Expert:
    return Expert(
        id=1,
        name=name,
        topic="stoic philosophy",
        status=ExpertStatus.READY,
        owner_id=ADMIN_ID,
        tier=ExpertTier.STANDARD,
        readiness=readiness,
        persona_name="Dr. Aurelia Vance",
        persona_bio="A scholar of the Stoa.",
        persona_style="Cites the primary texts.",
        source_count=18,
        chunk_count=940,
        node_count=210,
        avg_quality=8.2,
        catalog=CatalogMeta(
            visibility=visibility,
            is_featured=True,
            catalog_rank=1,
            blurb="Answers from Epictetus, Seneca and Marcus Aurelius.",
            category="Philosophy",
            tags=["ethics", "virtue"],
            published_at=datetime.now(UTC),
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def app():
    from peritus.api.app import create_app
    from peritus.api.auth import AuthUser, require_user

    app = create_app()
    app.dependency_overrides[require_user] = lambda: AuthUser(
        id=ADMIN_ID, email="admin@test", is_admin=True
    )
    return app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── public catalog ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_catalog_is_readable_without_a_token(app):
    """The shop window renders on a logged-out landing page."""
    from peritus.api.auth import require_user

    # No auth override at all — prove the route has no auth dependency.
    app.dependency_overrides.pop(require_user, None)

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
    ):
        repo = AsyncMock()
        repo.list_catalog = AsyncMock(return_value=[_make_expert()])
        MockRepo.return_value = repo

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as anon:
            resp = await anon.get("/catalog")

    assert resp.status_code == 200
    card = resp.json()[0]
    assert card["name"] == "stoicism"
    assert card["blurb"].startswith("Answers from")
    assert card["category"] == "Philosophy"
    assert card["tags"] == ["ethics", "virtue"]
    assert card["is_featured"] is True


@pytest.mark.asyncio
async def test_catalog_card_never_exposes_owner_or_build_internals(client):
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
    ):
        repo = AsyncMock()
        repo.list_catalog = AsyncMock(return_value=[_make_expert()])
        MockRepo.return_value = repo
        resp = await client.get("/catalog")

    card = resp.json()[0]
    for leaked in ("owner_id", "error", "id", "visibility"):
        assert leaked not in card, f"catalog card leaks {leaked}"


@pytest.mark.asyncio
async def test_catalog_passes_filters_through(client):
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
    ):
        repo = AsyncMock()
        repo.list_catalog = AsyncMock(return_value=[])
        MockRepo.return_value = repo
        await client.get("/catalog?category=Medicine&tag=oncology&featured=true&limit=5")

    repo.list_catalog.assert_awaited_once_with(
        category="Medicine", tag="oncology", featured_only=True, limit=5, offset=0
    )


@pytest.mark.asyncio
async def test_catalog_detail_404s_for_an_unanswerable_expert(client):
    """A public expert mid-rebuild has no corpus — it must not be offered."""
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
    ):
        repo = AsyncMock()
        repo.get_public = AsyncMock(return_value=_make_expert(readiness="pending"))
        MockRepo.return_value = repo
        resp = await client.get("/catalog/stoicism")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_chat_ready_expert_is_still_offered(client):
    """Answerable a stage before the job finishes — that is the point of readiness."""
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
    ):
        repo = AsyncMock()
        repo.get_public = AsyncMock(return_value=_make_expert(readiness="chat_ready"))
        MockRepo.return_value = repo
        resp = await client.get("/catalog/stoicism")

    assert resp.status_code == 200
    body = resp.json()
    assert body["readiness"] == "chat_ready"
    assert body["graph_expanded"] is False


# ── curation ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_curation_is_owner_scoped(client):
    """Readable-but-not-owned must 404 on the curate path, not 403."""
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
    ):
        repo = AsyncMock()
        repo.get_owned_for_user = AsyncMock(return_value=None)
        MockRepo.return_value = repo
        resp = await client.patch("/experts/stoicism/catalog", json={"visibility": "public"})

    assert resp.status_code == 404
    repo.update_catalog.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_sets_visibility_and_echoes_catalog_meta(client):
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
    ):
        repo = AsyncMock()
        repo.get_owned_for_user = AsyncMock(return_value=_make_expert())
        repo.update_catalog = AsyncMock(return_value=_make_expert())
        MockRepo.return_value = repo
        resp = await client.patch(
            "/experts/stoicism/catalog",
            json={"visibility": "public", "blurb": "New blurb", "tags": ["ethics"]},
        )

    assert resp.status_code == 200
    assert resp.json()["catalog"]["visibility"] == "public"
    kwargs = repo.update_catalog.await_args.kwargs
    assert kwargs["visibility"] is ExpertVisibility.PUBLIC
    assert kwargs["published_by"] == ADMIN_ID


@pytest.mark.asyncio
async def test_over_long_blurb_is_rejected_before_the_db(client):
    with patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()):
        resp = await client.patch(
            "/experts/stoicism/catalog", json={"blurb": "x" * 500}
        )
    assert resp.status_code == 422


# ── billing ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_credit_state_exposes_the_price_ladder(client):
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.EntitlementService") as MockService,
    ):
        service = AsyncMock()
        service.credit_state = AsyncMock(
            return_value=CreditState(
                owner_id=ADMIN_ID, plan=FREE, balance=1, granted=1, consumed=0, held=0
            )
        )
        MockService.return_value = service
        resp = await client.get("/billing/me")

    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"]["name"] == "free"
    assert body["balance"] == 1
    tiers = {t["tier"]: t for t in body["tiers"]}
    assert set(tiers) == {"lite", "standard", "pro"}
    assert tiers["lite"]["included_in_plan"] is True
    assert tiers["pro"]["included_in_plan"] is False
    assert tiers["lite"]["credit_cost"] < tiers["pro"]["credit_cost"]
    assert tiers["pro"]["spend_cap_usd"] > 0


@pytest.mark.asyncio
async def test_admin_grant_requires_admin(app):
    from peritus.api.auth import AuthUser, require_user

    app.dependency_overrides[require_user] = lambda: AuthUser(
        id="99999999-9999-9999-9999-999999999999", email="user@test", is_admin=False
    )
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.EntitlementService") as MockService,
    ):
        MockService.return_value = AsyncMock()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            resp = await c.post(
                "/admin/credits/grant", json={"owner": "a@b.com", "amount": 10}
            )

    # 404, not 403 — a non-admin should not learn the endpoint exists.
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_grant_issues_credits(client):
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.EntitlementService") as MockService,
    ):
        service = AsyncMock()
        service.resolve_owner = AsyncMock(return_value=ADMIN_ID)
        service.grant = AsyncMock(return_value=21)
        MockService.return_value = service
        resp = await client.post(
            "/admin/credits/grant",
            json={"owner": "alice@lab.edu", "amount": 20, "reason": "pilot"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"owner_id": ADMIN_ID, "balance": 21, "granted": 20}
    assert service.grant.await_args.kwargs["reason"] == "pilot"
