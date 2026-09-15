"""API contract for the three picture endpoints.

DB mocked, like the avatar endpoint tests beside this one. What they pin is the
part a client cannot discover for itself: that the picture rides on every expert
response as `picture` (present and null when absent), that the bytes are cached
immutably under a versioned URL and revalidate with an ETag, and that the read
rule is the expert's own — so a private expert's picture is a 404 to a stranger
while a published one's is not.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from peritus.experts.domain import (
    Expert,
    ExpertPicture,
    ExpertStatus,
    ExpertTier,
    ExpertVisibility,
)

OWNER_ID = "11111111-1111-1111-1111-111111111111"
STRANGER_ID = "22222222-2222-2222-2222-222222222222"
SHA = "a" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 64


def _picture(license_name: str = "Public domain") -> ExpertPicture:
    return ExpertPicture(
        provider="wikipedia",
        file_url="https://upload.wikimedia.org/thumb/512px-Zeno.jpg",
        file_page_url="https://commons.wikimedia.org/wiki/File:Zeno_of_Citium.jpg",
        license=license_name,
        sha256=SHA,
        width=512,
        height=683,
        byte_size=len(JPEG),
        file_name="File:Zeno_of_Citium.jpg",
        page_url="https://en.wikipedia.org/wiki/Stoicism",
        page_title="Zeno of Citium",
        artist="Paolo Monti",
        license_url="https://creativecommons.org/publicdomain/mark/1.0/",
        query="Stoicism",
        chosen_by="build",
        found_at=datetime.now(UTC),
    )


def _expert(
    picture: ExpertPicture | None = None,
    *,
    owner_id: str | None = OWNER_ID,
    visibility: ExpertVisibility = ExpertVisibility.PRIVATE,
) -> Expert:
    expert = Expert(
        id=1,
        name="stoic-philosophy",
        topic="Stoic philosophy",
        status=ExpertStatus.READY,
        owner_id=owner_id,
        tier=ExpertTier.STANDARD,
        readiness="graph_ready",
        persona_name="Dr. Aurelia Vance",
        picture=picture,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    expert.catalog.visibility = visibility
    return expert


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


def _repos(expert: Expert | None, blob: tuple[bytes, str, str] | None = None):
    """Patch both repositories this router reaches for."""
    experts = AsyncMock()
    experts.get_for_user = AsyncMock(return_value=expert)
    experts.get_owned_for_user = AsyncMock(return_value=expert)
    pictures = AsyncMock()
    pictures.get_blob = AsyncMock(return_value=blob)
    pictures.delete = AsyncMock(return_value=True)
    return experts, pictures


def _patched(experts, pictures):
    return (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository", return_value=experts),
        patch("peritus.api.routes.experts.ExpertPictureRepository", return_value=pictures),
    )


# ── the picture rides on the expert ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_picture_and_its_provenance_ride_on_expert_detail(client):
    experts, pictures = _repos(_expert(_picture()))
    a, b, c = _patched(experts, pictures)
    with a, b, c:
        resp = await client.get("/experts/stoic-philosophy")

    assert resp.status_code == 200
    picture = resp.json()["picture"]
    assert picture["version"] == SHA[:12]
    assert picture["title"] == "Zeno of Citium"
    assert picture["artist"] == "Paolo Monti"
    assert picture["license"] == "Public domain"
    assert picture["file_page_url"].startswith("https://commons.wikimedia.org/")
    # Public domain needs no credit line; CC BY does.
    assert picture["attribution_required"] is False


@pytest.mark.asyncio
async def test_a_cc_by_picture_requires_attribution(client):
    experts, pictures = _repos(_expert(_picture("CC BY-SA 4.0")))
    a, b, c = _patched(experts, pictures)
    with a, b, c:
        resp = await client.get("/experts/stoic-philosophy")

    assert resp.json()["picture"]["attribution_required"] is True


@pytest.mark.asyncio
async def test_picture_is_null_not_absent_when_there_is_none(client):
    """A client must never have to distinguish "no picture" from "old server"."""
    experts, pictures = _repos(_expert())
    a, b, c = _patched(experts, pictures)
    with a, b, c:
        resp = await client.get("/experts/stoic-philosophy")

    body = resp.json()
    assert "picture" in body
    assert body["picture"] is None


@pytest.mark.asyncio
async def test_picture_rides_on_the_workspace_list_too(client):
    experts, pictures = _repos(_expert(_picture()))
    experts.list_for_user = AsyncMock(return_value=[_expert(_picture())])
    a, b, c = _patched(experts, pictures)
    with a, b, c:
        resp = await client.get("/experts")

    assert resp.json()[0]["picture"]["version"] == SHA[:12]


@pytest.mark.asyncio
async def test_picture_rides_on_the_public_catalog_card(client):
    """A catalog card is anonymous-readable, so only the safe fields are on it."""
    experts, pictures = _repos(None)
    experts.get_public = AsyncMock(
        return_value=_expert(_picture(), visibility=ExpertVisibility.PUBLIC)
    )
    a, b, c = _patched(experts, pictures)
    with a, b, c:
        resp = await client.get("/catalog/stoic-philosophy")

    picture = resp.json()["picture"]
    assert picture["version"] == SHA[:12]
    assert "byte_size" not in picture


# ── the bytes ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_serves_the_bytes_with_an_etag_and_an_immutable_cache(client):
    experts, pictures = _repos(_expert(_picture()), blob=(JPEG, "image/jpeg", SHA))
    a, b, c = _patched(experts, pictures)
    with a, b, c:
        resp = await client.get("/experts/stoic-philosophy/picture?v=" + SHA[:12])

    assert resp.status_code == 200
    assert resp.content == JPEG
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["etag"] == f'"{SHA}"'
    # `private`, because whether this image may be seen depends on who asked.
    assert resp.headers["cache-control"] == "private, max-age=31536000, immutable"


@pytest.mark.asyncio
async def test_if_none_match_revalidates_to_304_with_no_body(client):
    experts, pictures = _repos(_expert(_picture()), blob=(JPEG, "image/jpeg", SHA))
    a, b, c = _patched(experts, pictures)
    with a, b, c:
        resp = await client.get(
            "/experts/stoic-philosophy/picture",
            headers={"If-None-Match": f'"{SHA}"'},
        )

    assert resp.status_code == 304
    assert resp.content == b""
    assert resp.headers["etag"] == f'"{SHA}"'


@pytest.mark.asyncio
async def test_an_expert_with_no_picture_is_a_404_not_an_empty_image(client):
    experts, pictures = _repos(_expert(), blob=None)
    a, b, c = _patched(experts, pictures)
    with a, b, c:
        resp = await client.get("/experts/stoic-philosophy/picture")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_a_private_experts_picture_is_a_404_to_anyone_else(app):
    """The read rule is the expert's own — `get_for_user` returns None, so 404."""
    from peritus.api.auth import AuthUser, require_user

    app.dependency_overrides[require_user] = lambda: AuthUser(
        id=STRANGER_ID, email="stranger@test", is_admin=False
    )
    experts, pictures = _repos(None, blob=(JPEG, "image/jpeg", SHA))
    a, b, c = _patched(experts, pictures)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        with a, b, c:
            resp = await http.get("/experts/stoic-philosophy/picture")

    assert resp.status_code == 404
    pictures.get_blob.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_shared_experts_picture_is_readable_by_a_signed_in_stranger(app):
    from peritus.api.auth import AuthUser, require_user

    app.dependency_overrides[require_user] = lambda: AuthUser(
        id=STRANGER_ID, email="stranger@test", is_admin=False
    )
    shared = _expert(_picture(), visibility=ExpertVisibility.PUBLIC)
    experts, pictures = _repos(shared, blob=(JPEG, "image/jpeg", SHA))
    a, b, c = _patched(experts, pictures)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        with a, b, c:
            resp = await http.get("/experts/stoic-philosophy/picture")

    assert resp.status_code == 200
    assert resp.content == JPEG


# ── remove and refresh ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_is_204_and_removes_the_row(client):
    experts, pictures = _repos(_expert(_picture()))
    a, b, c = _patched(experts, pictures)
    with a, b, c:
        resp = await client.delete("/experts/stoic-philosophy/picture")

    assert resp.status_code == 204
    pictures.delete.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_delete_is_owner_only(app):
    """A published expert is readable by everyone and mutable by nobody else."""
    from peritus.api.auth import AuthUser, require_user

    app.dependency_overrides[require_user] = lambda: AuthUser(
        id=STRANGER_ID, email="stranger@test", is_admin=False
    )
    experts, pictures = _repos(None)
    # Readable, but not owned — which is exactly the case that must still 404.
    experts.get_for_user = AsyncMock(
        return_value=_expert(_picture(), visibility=ExpertVisibility.PUBLIC)
    )
    a, b, c = _patched(experts, pictures)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        with a, b, c:
            resp = await http.delete("/experts/stoic-philosophy/picture")

    assert resp.status_code == 404
    pictures.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_returns_the_updated_expert(client):
    experts, pictures = _repos(_expert())
    service = AsyncMock()
    service.refresh_picture = AsyncMock(return_value=_expert(_picture()))
    a, b, c = _patched(experts, pictures)
    with a, b, c, patch(
        "peritus.api.routes.experts.ExpertService", return_value=service
    ):
        resp = await client.post("/experts/stoic-philosophy/picture/refresh")

    assert resp.status_code == 200
    assert resp.json()["picture"]["version"] == SHA[:12]
    service.refresh_picture.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_a_search_that_finds_nothing_is_a_422_that_says_why(client):
    """"No free image of this subject exists" is an answer, not a server error."""
    from peritus.experts.picture import PictureSkipped

    experts, pictures = _repos(_expert())
    service = AsyncMock()
    service.refresh_picture = AsyncMock(side_effect=PictureSkipped("no_candidate"))
    a, b, c = _patched(experts, pictures)
    with a, b, c, patch(
        "peritus.api.routes.experts.ExpertService", return_value=service
    ):
        resp = await client.post("/experts/stoic-philosophy/picture/refresh")

    assert resp.status_code == 422
    assert "freely licensed" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_refresh_is_throttled_because_each_call_fans_out_to_wikimedia(client):
    from peritus.api.ratelimit import SlidingWindowLimiter
    from peritus.api.routes import experts as routes

    experts, pictures = _repos(_expert())
    service = AsyncMock()
    service.refresh_picture = AsyncMock(return_value=_expert(_picture()))
    a, b, c = _patched(experts, pictures)
    limiter = SlidingWindowLimiter(limit=2, window=60.0)
    with a, b, c, patch.object(routes, "_picture_refresh_limiter", limiter), patch(
        "peritus.api.routes.experts.ExpertService", return_value=service
    ):
        first = await client.post("/experts/stoic-philosophy/picture/refresh")
        second = await client.post("/experts/stoic-philosophy/picture/refresh")
        third = await client.post("/experts/stoic-philosophy/picture/refresh")

    assert (first.status_code, second.status_code) == (200, 200)
    assert third.status_code == 429
    assert int(third.headers["retry-after"]) >= 1
