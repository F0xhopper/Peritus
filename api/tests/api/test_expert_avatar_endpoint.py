"""API contract for `PUT /experts/{slug}/avatar`.

DB mocked; these pin the contract the web client builds against — that the
avatar rides on every expert response, that a null body is the reset rather than
a bad request, and that the mutation is owner-scoped like every other one.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from peritus.experts.domain import Expert, ExpertStatus, ExpertTier

OWNER_ID = "11111111-1111-1111-1111-111111111111"


def _expert(avatar: dict | None = None) -> Expert:
    return Expert(
        id=1,
        name="stoic-philosophy",
        topic="Stoic philosophy",
        status=ExpertStatus.READY,
        owner_id=OWNER_ID,
        tier=ExpertTier.STANDARD,
        readiness="graph_ready",
        persona_name="Dr. Aurelia Vance",
        avatar=avatar,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def app():
    from peritus.api.app import create_app
    from peritus.api.auth import AuthUser, require_user

    app = create_app()
    app.dependency_overrides[require_user] = lambda: AuthUser(
        id=OWNER_ID, email="owner@test", is_admin=False
    )
    return app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _repo(owned: Expert | None, updated: Expert | None = None):
    repo = AsyncMock()
    repo.get_owned_for_user = AsyncMock(return_value=owned)
    repo.get_for_user = AsyncMock(return_value=owned)
    repo.update_avatar = AsyncMock(return_value=updated if updated is not None else owned)
    return repo


@pytest.mark.asyncio
async def test_sets_an_avatar_and_returns_the_updated_expert(client):
    chosen = {"style": "shapes", "seed": "Dr. Aurelia Vance", "hue": None}
    repo = _repo(_expert(), _expert(avatar=chosen))
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository", return_value=repo),
    ):
        resp = await client.put(
            "/experts/stoic-philosophy/avatar", json={"avatar": chosen}
        )

    assert resp.status_code == 200
    assert resp.json()["avatar"] == chosen
    repo.update_avatar.assert_awaited_once_with(1, chosen)


@pytest.mark.asyncio
async def test_null_avatar_resets_to_the_generated_default(client):
    repo = _repo(_expert(avatar={"style": "glass", "seed": None, "hue": None}), _expert())
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository", return_value=repo),
    ):
        resp = await client.put("/experts/stoic-philosophy/avatar", json={"avatar": None})

    assert resp.status_code == 200
    assert resp.json()["avatar"] is None
    # NULL, not an empty object: the client's "derive it" signal is a null column.
    repo.update_avatar.assert_awaited_once_with(1, None)


@pytest.mark.asyncio
async def test_seed_may_be_omitted(client):
    repo = _repo(_expert())
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository", return_value=repo),
    ):
        resp = await client.put(
            "/experts/stoic-philosophy/avatar", json={"avatar": {"style": "rings"}}
        )

    assert resp.status_code == 200
    repo.update_avatar.assert_awaited_once_with(1, {"style": "rings", "seed": None, "hue": None})


@pytest.mark.asyncio
async def test_a_face_style_is_a_400_with_the_allowed_list(client):
    repo = _repo(_expert())
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository", return_value=repo),
    ):
        resp = await client.put(
            "/experts/stoic-philosophy/avatar", json={"avatar": {"style": "avataaars"}}
        )

    assert resp.status_code == 400
    assert "avataaars" in resp.json()["detail"]
    assert "sigil" in resp.json()["detail"]  # names what IS allowed
    repo.update_avatar.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_hue_is_discarded_not_stored(client):
    # There are no per-expert colours. An older client that still sends a hue
    # has its style saved and the hue dropped, rather than getting a 422.
    repo = _repo(_expert())
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository", return_value=repo),
    ):
        resp = await client.put(
            "/experts/stoic-philosophy/avatar",
            json={"avatar": {"style": "sigil", "hue": 900}},
        )

    assert resp.status_code == 200
    repo.update_avatar.assert_awaited_once_with(1, {"style": "sigil", "seed": None, "hue": None})


@pytest.mark.asyncio
async def test_someone_elses_expert_is_a_404_not_a_403(client):
    """Existence is not disclosed — the same convention as every other mutation."""
    repo = _repo(None)
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository", return_value=repo),
    ):
        resp = await client.put(
            "/experts/someone-elses/avatar", json={"avatar": {"style": "shapes"}}
        )

    assert resp.status_code == 404
    repo.update_avatar.assert_not_awaited()


@pytest.mark.asyncio
async def test_avatar_rides_on_the_expert_list_and_detail(client):
    """The web client reads the avatar off the responses it already fetches, so
    a missing field here would mean a second request per expert."""
    chosen = {"style": "identicon", "seed": "pinned", "hue": 40}
    repo = AsyncMock()
    repo.list_for_user = AsyncMock(return_value=[_expert(avatar=chosen)])
    repo.get_for_user = AsyncMock(return_value=_expert(avatar=chosen))
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository", return_value=repo),
    ):
        listed = await client.get("/experts")
        detail = await client.get("/experts/stoic-philosophy")

    assert listed.json()[0]["avatar"] == chosen
    assert detail.json()["avatar"] == chosen


@pytest.mark.asyncio
async def test_derived_avatar_serialises_as_null(client):
    repo = AsyncMock()
    repo.list_for_user = AsyncMock(return_value=[_expert()])
    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository", return_value=repo),
    ):
        resp = await client.get("/experts")

    # Present and null, never absent: the client branches on it.
    assert "avatar" in resp.json()[0]
    assert resp.json()[0]["avatar"] is None
