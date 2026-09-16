"""API contract tests for share links and the catalog's admin gate.

DB mocked; the SQL behaviour (revocation, grants, scoping) is pinned by the
DB-backed tests in ``tests/unit/test_share_links.py``. These pin what a client
builds against: who may call what, which fields a share card carries, and what
it must never leak.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from peritus.experts.domain import (
    CatalogMeta,
    Expert,
    ExpertStatus,
    ExpertTier,
    ExpertVisibility,
    ShareLink,
)
from tests.conftest import call_api as _call

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


# ── the owner ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enable_returns_the_token_and_the_uploads_warning_count(api_app):
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=_expert())
    shares = AsyncMock()
    shares.enable = AsyncMock(return_value=_link())
    shares.viewer_count = AsyncMock(return_value=3)
    shares.uploaded_source_count = AsyncMock(return_value=2)
    resp = await _call(
        api_app(OWNER, expert_repo=experts, shares=shares), "PUT", "/experts/thomism/share"
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["token"] == TOKEN
    assert body["viewer_count"] == 3
    assert body["uploaded_source_count"] == 2
    shares.enable.assert_awaited_once_with(7, OWNER)


@pytest.mark.asyncio
async def test_share_state_when_off_has_no_token(api_app):
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=_expert())
    shares = AsyncMock()
    shares.get_active = AsyncMock(return_value=None)
    shares.uploaded_source_count = AsyncMock(return_value=0)
    resp = await _call(
        api_app(OWNER, expert_repo=experts, shares=shares), "GET", "/experts/thomism/share"
    )

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
async def test_only_the_owner_manages_the_link(api_app, method, path):
    """A viewer holding a grant resolves nothing through the ownership gate — 404."""
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=None)
    shares = AsyncMock()
    resp = await _call(api_app(VIEWER, expert_repo=experts, shares=shares), method, path)

    assert resp.status_code == 404
    shares.enable.assert_not_awaited()
    shares.reset.assert_not_awaited()
    shares.disable.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_and_disable_call_through(api_app):
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=_expert())
    shares = AsyncMock()
    shares.reset = AsyncMock(return_value=_link())
    shares.viewer_count = AsyncMock(return_value=0)
    shares.uploaded_source_count = AsyncMock(return_value=0)
    reset = await _call(
        api_app(OWNER, expert_repo=experts, shares=shares), "POST", "/experts/thomism/share/reset"
    )
    off = await _call(
        api_app(OWNER, expert_repo=experts, shares=shares), "DELETE", "/experts/thomism/share"
    )

    assert reset.status_code == 200
    assert off.status_code == 204
    shares.reset.assert_awaited_once_with(7, OWNER)
    shares.disable.assert_awaited_once_with(7)


# ── anyone holding the link ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_share_card_is_anonymous_uncached_noindexed_and_narrow(api_app):
    experts = AsyncMock()
    experts.get_by_share_token = AsyncMock(return_value=_expert())
    resp = await _call(api_app(None, expert_repo=experts), "GET", f"/share/{TOKEN}")

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert "noindex" in resp.headers["x-robots-tag"]
    card = resp.json()
    assert card["persona_name"] == "Fr. Reginald"
    for leaked in ("name", "id", "owner_id", "error", "catalog", "access", "token"):
        assert leaked not in card, f"share card leaks {leaked}"


@pytest.mark.parametrize("token", ["short", "B" * 32, "has space" + "x" * 30])
@pytest.mark.asyncio
async def test_unknown_malformed_or_revoked_links_404(api_app, token):
    experts = AsyncMock()
    experts.get_by_share_token = AsyncMock(return_value=None)
    resp = await _call(api_app(None, expert_repo=experts), "GET", f"/share/{token}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_accept_requires_a_session(api_app):
    from peritus.api.app import create_app

    # Without a Supabase project the API runs every request as the dev admin, so
    # configure one: the point is that this route has an auth dependency at all.
    with patch("peritus.api.auth.settings.SUPABASE_JWT_SECRET", "test-secret"):
        resp = await _call(create_app(), "POST", f"/share/{TOKEN}/accept")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_accept_grants_a_viewer_and_returns_the_slug(api_app):
    experts = AsyncMock()
    experts.get_by_share_token = AsyncMock(return_value=_expert())
    shares = AsyncMock()
    shares.resolve = AsyncMock(return_value=_link())
    resp = await _call(
        api_app(VIEWER, expert_repo=experts, shares=shares), "POST", f"/share/{TOKEN}/accept"
    )

    assert resp.json() == {"slug": "thomism", "access": "viewer"}
    shares.grant.assert_awaited_once_with("link-1", VIEWER)


@pytest.mark.asyncio
async def test_the_owner_opening_their_own_link_gets_no_grant(api_app):
    experts = AsyncMock()
    experts.get_by_share_token = AsyncMock(return_value=_expert())
    shares = AsyncMock()
    resp = await _call(
        api_app(OWNER, expert_repo=experts, shares=shares), "POST", f"/share/{TOKEN}/accept"
    )

    assert resp.json() == {"slug": "thomism", "access": "owner"}
    shares.grant.assert_not_awaited()


# ── a viewer ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_viewer_can_leave_but_an_owner_cannot(api_app):
    experts = AsyncMock()
    experts.get_for_user = AsyncMock(return_value=_expert())
    shares = AsyncMock()
    left = await _call(
        api_app(VIEWER, expert_repo=experts, shares=shares), "DELETE", "/experts/thomism/access"
    )
    refused = await _call(
        api_app(OWNER, expert_repo=experts, shares=shares), "DELETE", "/experts/thomism/access"
    )

    assert left.status_code == 204
    assert refused.status_code == 409
    shares.remove_access.assert_awaited_once_with(7, VIEWER)


@pytest.mark.asyncio
async def test_expert_detail_says_whether_the_caller_owns_it(api_app):
    experts = AsyncMock()
    experts.get_for_user = AsyncMock(return_value=_expert())
    as_viewer = await _call(api_app(VIEWER, expert_repo=experts), "GET", "/experts/thomism")
    as_owner = await _call(api_app(OWNER, expert_repo=experts), "GET", "/experts/thomism")

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
async def test_an_owner_cannot_publish_or_reorder_the_shelf(api_app, body):
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=_expert())
    resp = await _call(
        api_app(OWNER, expert_repo=experts), "PATCH", "/experts/thomism/catalog", json=body
    )

    assert resp.status_code == 403
    experts.update_catalog.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_owner_can_still_unpublish_and_an_admin_can_publish(api_app):
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=_expert())
    experts.update_catalog = AsyncMock(return_value=_expert())
    unpublish = await _call(
        api_app(OWNER, expert_repo=experts),
        "PATCH",
        "/experts/thomism/catalog",
        json={"visibility": "private"},
    )
    publish = await _call(
        api_app(OWNER, is_admin=True, expert_repo=experts),
        "PATCH",
        "/experts/thomism/catalog",
        json={"visibility": "public", "is_featured": True},
    )

    assert unpublish.status_code == 200
    assert publish.status_code == 200


@pytest.mark.asyncio
async def test_unlisted_is_rejected_as_a_visibility(api_app):
    experts = AsyncMock()
    experts.get_owned_for_user = AsyncMock(return_value=_expert())
    resp = await _call(
        api_app(OWNER, is_admin=True, expert_repo=experts),
        "PATCH",
        "/experts/thomism/catalog",
        json={"visibility": "unlisted"},
    )
    assert resp.status_code == 422
