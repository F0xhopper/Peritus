"""Both chat surfaces are throttled, on one shared per-user budget.

Chat is the only paid action with no credit gate: every message is a planning
call, a rerank, a coverage assessment and a composition. These tests are about
the wiring, not the limiter (tests/unit/test_ratelimit.py covers that) — that
each route actually depends on the throttle, that the two cannot be used to
sidestep each other, and that the throttle runs before any expensive work.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from peritus.api import ratelimit
from peritus.api.auth import AuthUser, require_user
from peritus.api.ratelimit import SlidingWindowLimiter
from peritus.chat.conversation_repository import Conversation
from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier
from peritus.search.readiness import Readiness

ADMIN_ID = "00000000-0000-0000-0000-000000000000"
OTHER_ID = "99999999-9999-9999-9999-999999999999"
CONV_ID = "11111111-1111-1111-1111-111111111111"


def _expert() -> Expert:
    return Expert(
        id=1, name="stoicism", topic="stoicism", status=ExpertStatus.READY,
        tier=ExpertTier.STANDARD, config=ExpertConfig.from_tier(ExpertTier.STANDARD),
        owner_id=ADMIN_ID, created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )


def _conversation() -> Conversation:
    now = datetime.now(UTC)
    return Conversation(
        id=CONV_ID, expert_id=1, owner_id=ADMIN_ID, title=None, message_count=0,
        streaming_started_at=None, created_at=now, last_message_at=now,
        expert_slug="stoicism", expert_topic="stoicism",
        expert_persona_name="Marcus", expert_status="ready",
    )


@pytest.fixture
def tight_limit(monkeypatch):
    """One message per window, so the second call is the interesting one."""
    monkeypatch.setattr(ratelimit, "_chat_limiter", SlidingWindowLimiter(limit=1, window=60))


@pytest.fixture
def current_user():
    """Mutable identity, so one test can switch accounts mid-flight."""
    return {"id": ADMIN_ID}


@pytest.fixture
def app(current_user):
    from peritus.api.app import create_app

    app = create_app()
    app.dependency_overrides[require_user] = lambda: AuthUser(
        id=current_user["id"], email="admin@test", is_admin=True
    )
    return app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def stateless_backend():
    """Everything behind POST /experts/{slug}/chat, stubbed."""
    repo = AsyncMock()
    repo.get_for_user = AsyncMock(return_value=_expert())

    async def _readiness(_pool, _expert_id):
        return Readiness.GRAPH_READY

    async def _stream(*_args, **_kwargs):
        yield {"type": "done"}

    with patch("peritus.api.routes.chat.get_pool", return_value=MagicMock()), \
         patch("peritus.api.routes.chat.ExpertRepository", return_value=repo), \
         patch("peritus.api.routes.chat.get_readiness", new=_readiness), \
         patch("peritus.chat.streaming.stream_expert_answer", new=_stream):
        yield repo


async def _post_chat(client):
    return await client.post(
        "/experts/stoicism/chat", json={"question": "what is virtue?", "history": []}
    )


# ── the stateless endpoint ──


async def test_first_message_is_allowed(client, tight_limit, stateless_backend):
    assert (await _post_chat(client)).status_code == 200


async def test_second_message_is_throttled(client, tight_limit, stateless_backend):
    await _post_chat(client)
    resp = await _post_chat(client)

    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"


async def test_throttling_happens_before_any_lookup(client, tight_limit, stateless_backend):
    """The throttle is worthless if the expensive work runs first. A rejected
    request must not even reach the database."""
    await _post_chat(client)
    stateless_backend.get_for_user.reset_mock()

    await _post_chat(client)

    stateless_backend.get_for_user.assert_not_called()


async def test_another_account_is_unaffected(
    client, tight_limit, stateless_backend, current_user
):
    await _post_chat(client)
    assert (await _post_chat(client)).status_code == 429

    current_user["id"] = OTHER_ID
    assert (await _post_chat(client)).status_code == 200


# ── the stateful endpoint, on the same budget ──


@pytest.fixture
def stateful_backend():
    convs = AsyncMock()
    convs.get_for_user = AsyncMock(return_value=_conversation())
    convs.claim_stream = AsyncMock(return_value=True)
    convs.recent_history = AsyncMock(return_value=[])
    convs.add_user_message = AsyncMock(return_value=_conversation())
    experts = AsyncMock()
    experts.get_by_id = AsyncMock(return_value=_expert())

    async def _readiness(_pool, _expert_id):
        return Readiness.GRAPH_READY

    async def _stream(*_args, **_kwargs):
        yield {"type": "done"}

    with patch("peritus.api.routes.conversations.get_pool", return_value=MagicMock()), \
         patch("peritus.api.routes.conversations.ConversationRepository", return_value=convs), \
         patch("peritus.api.routes.conversations.ExpertRepository", return_value=experts), \
         patch("peritus.api.routes.conversations.get_readiness", new=_readiness), \
         patch("peritus.chat.streaming.stream_expert_answer", new=_stream):
        yield convs


async def _post_message(client):
    return await client.post(
        f"/conversations/{CONV_ID}/messages", json={"question": "what is virtue?"}
    )


async def test_conversation_messages_are_throttled(client, tight_limit, stateful_backend):
    assert (await _post_message(client)).status_code == 200
    assert (await _post_message(client)).status_code == 429


async def test_the_two_surfaces_share_one_budget(
    client, tight_limit, stateless_backend, stateful_backend
):
    """They cost the same to serve, so one must not be a way around the other."""
    assert (await _post_chat(client)).status_code == 200
    assert (await _post_message(client)).status_code == 429


async def test_a_throttled_message_does_not_claim_the_stream(
    client, tight_limit, stateful_backend
):
    """A rejected request must leave no state behind — a claim taken and never
    released locks the conversation out of answers until it goes stale."""
    await _post_message(client)
    stateful_backend.claim_stream.reset_mock()

    assert (await _post_message(client)).status_code == 429

    stateful_backend.claim_stream.assert_not_called()
