"""API contract tests for share links and the catalog's admin gate.

DB mocked; the SQL behaviour (revocation, grants, scoping) is pinned by the
DB-backed tests in ``tests/unit/test_share_links.py``. These pin what a client
builds against: who may call what, which fields a share card carries, and what
it must never leak.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from peritus.experts.domain import (
    CatalogMeta,
    Expert,
    ExpertStatus,
    ExpertTier,
    ExpertVisibility,
    ShareLink,
)

OWNER = "11111111-1111-1111-1111-111111111111"
VIEWER = "22222222-2222-2222-2222-222222222222"
TOKEN = "A" * 32


def _expert(owner=OWNER) -> Expert:
    return Expert(
        id=7,
        name="thomism",
        topic="Thomism",
        status=ExpertStatus.READY,
        owner_id=owner,
        tier=ExpertTier.STANDARD,
        readiness="graph_ready",
        persona_name="Fr. Reginald",
        persona_bio="Reads the Summa closely.",
        key_concepts=["analogy of being"],
        source_count=12,
        error="internal detail",
        catalog=CatalogMeta(visibility=ExpertVisibility.PRIVATE),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _link() -> ShareLink:
    return ShareLink(id="link-1", expert_id=7, token=TOKEN, created_at=datetime.now(UTC))


def _app(user_id: str | None, is_admin: bool = False):
    from peritus.api.app import create_app
    from peritus.api.auth import AuthUser, require_user

    app = create_app()
    if user_id:
        app.dependency_overrides[require_user] = lambda: AuthUser(
            id=user_id, email="u@test", is_admin=is_admin
        )
    return app


async def _call(app, method: str, path: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.request(method, path, **kwargs)


def _patched(experts: AsyncMock, shares: AsyncMock | None = None):
    return (
        patch("peritus.api.routes.sharing.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.sharing.ExpertRepository", return_value=experts),
        patch("peritus.api.routes.sharing.ShareRepository", return_value=shares or AsyncMock()),
    )


# ── the owner ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enable_returns_the_token_and_the_uploads_warning_count():
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=_expert())
    shares = AsyncMock()
    shares.enable = AsyncMock(return_value=_link())
    shares.viewer_count = AsyncMock(return_value=3)
    shares.uploaded_source_count = AsyncMock(return_value=2)
    p1, p2, p3 = _patched(experts, shares)
    with p1, p2, p3:
        resp = await _call(_app(OWNER), "PUT", "/experts/thomism/share")

    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["token"] == TOKEN
    assert body["viewer_count"] == 3
    assert body["uploaded_source_count"] == 2
    shares.enable.assert_awaited_once_with(7, OWNER)


@pytest.mark.asyncio
async def test_share_state_when_off_has_no_token():
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=_expert())
    shares = AsyncMock()
    shares.get_active = AsyncMock(return_value=None)
    shares.uploaded_source_count = AsyncMock(return_value=0)
    p1, p2, p3 = _patched(experts, shares)
    with p1, p2, p3:
        resp = await _call(_app(OWNER), "GET", "/experts/thomism/share")

    assert resp.json() == {
        "enabled": False,
        "token": None,
        "created_at": None,
        "viewer_count": 0,
        "uploaded_source_count": 0,
    }


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/experts/thomism/share"),
        ("PUT", "/experts/thomism/share"),
        ("POST", "/experts/thomism/share/reset"),
        ("DELETE", "/experts/thomism/share"),
    ],
)
@pytest.mark.asyncio
async def test_only_the_owner_manages_the_link(method, path):
    """A viewer holding a grant resolves nothing through the ownership gate — 404."""
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=None)
    shares = AsyncMock()
    p1, p2, p3 = _patched(experts, shares)
    with p1, p2, p3:
        resp = await _call(_app(VIEWER), method, path)

    assert resp.status_code == 404
    shares.enable.assert_not_awaited()
    shares.reset.assert_not_awaited()
    shares.disable.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_and_disable_call_through():
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=_expert())
    shares = AsyncMock()
    shares.reset = AsyncMock(return_value=_link())
    shares.viewer_count = AsyncMock(return_value=0)
    shares.uploaded_source_count = AsyncMock(return_value=0)
    p1, p2, p3 = _patched(experts, shares)
    with p1, p2, p3:
        reset = await _call(_app(OWNER), "POST", "/experts/thomism/share/reset")
        off = await _call(_app(OWNER), "DELETE", "/experts/thomism/share")

    assert reset.status_code == 200
    assert off.status_code == 204
    shares.reset.assert_awaited_once_with(7, OWNER)
    shares.disable.assert_awaited_once_with(7)


# ── anyone holding the link ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_share_card_is_anonymous_uncached_noindexed_and_narrow():
    experts = AsyncMock()
    experts.get_by_share_token = AsyncMock(return_value=_expert())
    p1, p2, p3 = _patched(experts)
    with p1, p2, p3:
        resp = await _call(_app(None), "GET", f"/share/{TOKEN}")

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert "noindex" in resp.headers["x-robots-tag"]
    card = resp.json()
    assert card["persona_name"] == "Fr. Reginald"
    for leaked in ("name", "id", "owner_id", "error", "catalog", "access", "token"):
        assert leaked not in card, f"share card leaks {leaked}"


@pytest.mark.parametrize("token", ["short", "B" * 32, "has space" + "x" * 30])
@pytest.mark.asyncio
async def test_unknown_malformed_or_revoked_links_404(token):
    experts = AsyncMock()
    experts.get_by_share_token = AsyncMock(return_value=None)
    p1, p2, p3 = _patched(experts)
    with p1, p2, p3:
        resp = await _call(_app(None), "GET", f"/share/{token}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_accept_requires_a_session():
    from peritus.api.app import create_app

    # Without a Supabase project the API runs every request as the dev admin, so
    # configure one: the point is that this route has an auth dependency at all.
    with patch("peritus.api.auth.settings.SUPABASE_JWT_SECRET", "test-secret"):
        resp = await _call(create_app(), "POST", f"/share/{TOKEN}/accept")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_accept_grants_a_viewer_and_returns_the_slug():
    experts = AsyncMock()
    experts.get_by_share_token = AsyncMock(return_value=_expert())
    shares = AsyncMock()
    shares.resolve = AsyncMock(return_value=_link())
    p1, p2, p3 = _patched(experts, shares)
    with p1, p2, p3:
        resp = await _call(_app(VIEWER), "POST", f"/share/{TOKEN}/accept")

    assert resp.json() == {"slug": "thomism", "access": "viewer"}
    shares.grant.assert_awaited_once_with("link-1", VIEWER)


@pytest.mark.asyncio
async def test_the_owner_opening_their_own_link_gets_no_grant():
    experts = AsyncMock()
    experts.get_by_share_token = AsyncMock(return_value=_expert())
    shares = AsyncMock()
    p1, p2, p3 = _patched(experts, shares)
    with p1, p2, p3:
        resp = await _call(_app(OWNER), "POST", f"/share/{TOKEN}/accept")

    assert resp.json() == {"slug": "thomism", "access": "owner"}
    shares.grant.assert_not_awaited()


# ── a viewer ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_viewer_can_leave_but_an_owner_cannot():
    experts = AsyncMock()
    experts.get_for_user = AsyncMock(return_value=_expert())
    shares = AsyncMock()
    p1, p2, p3 = _patched(experts, shares)
    with p1, p2, p3:
        left = await _call(_app(VIEWER), "DELETE", "/experts/thomism/access")
        refused = await _call(_app(OWNER), "DELETE", "/experts/thomism/access")

    assert left.status_code == 204
    assert refused.status_code == 409
    shares.remove_access.assert_awaited_once_with(7, VIEWER)


@pytest.mark.asyncio
async def test_expert_detail_says_whether_the_caller_owns_it():
    experts = AsyncMock()
    experts.get_for_user = AsyncMock(return_value=_expert())
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository", return_value=experts),
    ):
        as_viewer = await _call(_app(VIEWER), "GET", "/experts/thomism")
        as_owner = await _call(_app(OWNER), "GET", "/experts/thomism")

    assert as_viewer.json()["access"] == "viewer"
    assert as_owner.json()["access"] == "owner"


# ── the catalog is curated ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        {"visibility": "public"},
        {"is_featured": True},
        {"catalog_rank": 1},
        {"clear": ["catalog_rank"]},
    ],
)
@pytest.mark.asyncio
async def test_an_owner_cannot_publish_or_reorder_the_shelf(body):
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=_expert())
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository", return_value=experts),
    ):
        resp = await _call(_app(OWNER), "PATCH", "/experts/thomism/catalog", json=body)

    assert resp.status_code == 403
    experts.update_catalog.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_owner_can_still_unpublish_and_an_admin_can_publish():
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=_expert())
    experts.update_catalog = AsyncMock(return_value=_expert())
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository", return_value=experts),
    ):
        unpublish = await _call(
            _app(OWNER), "PATCH", "/experts/thomism/catalog", json={"visibility": "private"}
        )
        publish = await _call(
            _app(OWNER, is_admin=True),
            "PATCH",
            "/experts/thomism/catalog",
            json={"visibility": "public", "is_featured": True},
        )

    assert unpublish.status_code == 200
    assert publish.status_code == 200


@pytest.mark.asyncio
async def test_unlisted_is_rejected_as_a_visibility():
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=_expert())
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository", return_value=experts),
    ):
        resp = await _call(
            _app(OWNER, is_admin=True),
            "PATCH",
            "/experts/thomism/catalog",
            json={"visibility": "unlisted"},
        )
    assert resp.status_code == 422
