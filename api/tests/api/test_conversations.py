"""API contract tests for stateful conversations.

DB, agent, and Anthropic are mocked so no infrastructure is required (style of
test_build_endpoint.py). Repository SQL behaviour (claim contention, cascade,
recents filtering) is covered by the DB-backed tests in
tests/unit/test_conversation_repository.py.
"""

import contextlib
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from peritus.api import deps
from peritus.api.routes.conversations import _title_from_question
from peritus.chat.conversation_repository import Conversation
from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier
from peritus.search.readiness import Readiness

ADMIN_ID = "00000000-0000-0000-0000-000000000000"
CONV_ID = "11111111-1111-1111-1111-111111111111"


def _make_expert(status: ExpertStatus = ExpertStatus.READY) -> Expert:
    return Expert(
        id=1,
        name="stoicism",
        topic="stoicism",
        status=status,
        tier=ExpertTier.STANDARD,
        config=ExpertConfig.from_tier(ExpertTier.STANDARD),
        owner_id=ADMIN_ID,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_conversation(**overrides) -> Conversation:
    now = datetime.now(UTC)
    fields = {
        "id": CONV_ID,
        "expert_id": 1,
        "owner_id": ADMIN_ID,
        "title": None,
        "message_count": 0,
        "streaming_started_at": None,
        "created_at": now,
        "last_message_at": now,
        "expert_slug": "stoicism",
        "expert_topic": "stoicism",
        "expert_persona_name": "Marcus",
        "expert_status": "ready",
    }
    fields.update(overrides)
    return Conversation(**fields)


@pytest.fixture
def app(api_app):
    return api_app(user=ADMIN_ID, is_admin=True, email="admin@test")


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def readiness():
    """The route's retrieval-readiness gate.

    Chat availability is gated on ``experts.readiness`` rather than build-job
    status (an expert answers as soon as its corpus is embedded, a stage before
    the job finishes), and that is a DB read these mocked tests have no database
    for. Defaults to a fully built expert; the not-ready cases dial it back.
    """
    state = {"value": Readiness.GRAPH_READY}

    async def _get_readiness(_pool, _expert_id):
        return state["value"]

    with patch("peritus.api.routes.conversations.get_readiness", new=_get_readiness):
        yield state


@contextlib.contextmanager
def _wired(app, mock_convs=None, mock_experts=None):
    """Substitute the two repositories the conversation routes depend on.

    `dependency_overrides` rather than patching the route module: the handlers
    take both as dependencies now, so the test names what it replaces.
    """
    app.dependency_overrides[deps.conversation_repo] = lambda: mock_convs or AsyncMock()
    app.dependency_overrides[deps.expert_repo] = lambda: mock_experts or AsyncMock()
    yield


# ── title truncation ──


def test_title_short_question_verbatim():
    assert _title_from_question("What is virtue?") == "What is virtue?"


def test_title_collapses_whitespace():
    assert _title_from_question("  What\n is   virtue? ") == "What is virtue?"
    assert _title_from_question("what is the potency") == "What is the potency"


def test_title_truncates_at_word_boundary_with_ellipsis():
    q = "Explain the difference between Stoic apatheia and modern emotional suppression in detail"
    title = _title_from_question(q)
    assert len(title) <= 61  # 60 chars + ellipsis
    assert title.endswith("…")
    assert not title[:-1].endswith(" ")
    # Cut on a word boundary: everything before the ellipsis is a prefix of the question.
    assert q.startswith(title[:-1])


# ── create ──


@pytest.mark.asyncio
async def test_create_conversation(client, app):
    mock_experts = AsyncMock()
    mock_experts.get_for_user = AsyncMock(return_value=_make_expert())
    mock_convs = AsyncMock()
    mock_convs.create = AsyncMock(
        return_value=_make_conversation(expert_slug=None, expert_topic=None, expert_status=None)
    )
    with _wired(app, mock_convs, mock_experts):
        resp = await client.post("/experts/stoicism/conversations")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == CONV_ID
    assert body["expert_slug"] == "stoicism"
    assert body["expert_status"] == "ready"
    assert body["title"] is None
    mock_convs.create.assert_awaited_once_with(1, ADMIN_ID)


@pytest.mark.asyncio
async def test_create_conversation_unknown_expert_404(client, app):
    mock_experts = AsyncMock()
    mock_experts.get_for_user = AsyncMock(return_value=None)
    with _wired(app, mock_experts=mock_experts):
        resp = await client.post("/experts/nope/conversations")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_conversation_not_ready_409(client, readiness, app):
    readiness["value"] = Readiness.PENDING
    mock_experts = AsyncMock()
    mock_experts.get_for_user = AsyncMock(return_value=_make_expert(ExpertStatus.BUILDING))
    with _wired(app, mock_experts=mock_experts):
        resp = await client.post("/experts/stoicism/conversations")
    assert resp.status_code == 409


# ── ownership 404s (repo scoping returns nothing → route must 404, not 403) ──


@pytest.mark.asyncio
async def test_get_conversation_not_visible_404(client, app):
    mock_convs = AsyncMock()
    mock_convs.get_for_user = AsyncMock(return_value=None)
    with _wired(app, mock_convs):
        resp = await client.get(f"/conversations/{CONV_ID}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rename_not_visible_404(client, app):
    mock_convs = AsyncMock()
    mock_convs.rename = AsyncMock(return_value=False)
    with _wired(app, mock_convs):
        resp = await client.patch(f"/conversations/{CONV_ID}", json={"title": "New title"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_not_visible_404(client, app):
    mock_convs = AsyncMock()
    mock_convs.delete = AsyncMock(return_value=False)
    with _wired(app, mock_convs):
        resp = await client.delete(f"/conversations/{CONV_ID}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_send_message_not_visible_404(client, app):
    mock_convs = AsyncMock()
    mock_convs.get_for_user = AsyncMock(return_value=None)
    with _wired(app, mock_convs):
        resp = await client.post(f"/conversations/{CONV_ID}/messages", json={"question": "hi"})
    assert resp.status_code == 404


# ── rename / delete happy paths ──


@pytest.mark.asyncio
async def test_rename_conversation(client, app):
    mock_convs = AsyncMock()
    mock_convs.rename = AsyncMock(return_value=True)
    mock_convs.get_for_user = AsyncMock(
        return_value=_make_conversation(title="New title", message_count=2)
    )
    with _wired(app, mock_convs):
        resp = await client.patch(f"/conversations/{CONV_ID}", json={"title": "  New title  "})

    assert resp.status_code == 200
    assert resp.json()["title"] == "New title"
    # Validator strips whitespace before the repository sees it.
    mock_convs.rename.assert_awaited_once_with(
        CONV_ID, ADMIN_ID, include_unowned=True, title="New title"
    )


@pytest.mark.asyncio
async def test_rename_blank_title_422(client, app):
    with _wired(app):
        resp = await client.patch(f"/conversations/{CONV_ID}", json={"title": "   "})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_conversation_204(client, app):
    mock_convs = AsyncMock()
    mock_convs.delete = AsyncMock(return_value=True)
    with _wired(app, mock_convs):
        resp = await client.delete(f"/conversations/{CONV_ID}")
    assert resp.status_code == 204


# ── lists ──


@pytest.mark.asyncio
async def test_recents_list(client, app):
    mock_convs = AsyncMock()
    mock_convs.list_recent_for_user = AsyncMock(
        return_value=[_make_conversation(title="What is virtue?", message_count=4)]
    )
    with _wired(app, mock_convs):
        resp = await client.get("/conversations?limit=8")

    assert resp.status_code == 200
    rows = resp.json()
    assert rows[0]["title"] == "What is virtue?"
    assert rows[0]["expert_persona_name"] == "Marcus"
    mock_convs.list_recent_for_user.assert_awaited_once_with(
        ADMIN_ID, include_unowned=True, limit=8
    )


@pytest.mark.asyncio
async def test_recents_limit_over_50_rejected(client, app):
    with _wired(app):
        resp = await client.get("/conversations?limit=100")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_expert_conversations_list(client, app):
    mock_experts = AsyncMock()
    mock_experts.get_for_user = AsyncMock(return_value=_make_expert())
    mock_convs = AsyncMock()
    mock_convs.list_for_expert = AsyncMock(return_value=[_make_conversation(message_count=2)])
    with _wired(app, mock_convs, mock_experts):
        resp = await client.get("/experts/stoicism/conversations")

    assert resp.status_code == 200
    assert len(resp.json()) == 1
    # Scoped to the caller: a shared or public expert has other people's chats.
    mock_convs.list_for_expert.assert_awaited_once_with(1, ADMIN_ID, include_unowned=True)


# ── the message stream ──


def _fake_stream(events):
    """An async generator factory matching stream_expert_answer's signature."""

    async def gen(pool, expert, question, history, conversation_id=None):
        for ev in events:
            if isinstance(ev, Exception):
                raise ev
            yield ev

    return gen


def _stream_mocks(conversation, expert=None, history=None):
    mock_convs = AsyncMock()
    mock_convs.get_for_user = AsyncMock(return_value=conversation)
    mock_convs.claim_stream = AsyncMock(return_value=True)
    mock_convs.recent_history = AsyncMock(return_value=history or [])
    mock_convs.add_user_message = AsyncMock(
        return_value=_make_conversation(title="What is virtue?", message_count=1)
    )
    mock_convs.finish_stream = AsyncMock()
    mock_experts = AsyncMock()
    mock_experts.get_by_id = AsyncMock(return_value=expert or _make_expert())
    return mock_convs, mock_experts


@pytest.mark.asyncio
async def test_send_message_streams_and_persists(client, app):
    citations = [{"n": 1, "label": "Meditations, Book 2", "source_id": 7}]
    events = [
        {"type": "status", "message": "Searching…"},
        {"type": "token", "text": "Virtue "},
        {"type": "token", "text": "is enough."},
        {"type": "sources", "citations": citations, "has_contradiction": False},
        {"type": "done"},
    ]
    mock_convs, mock_experts = _stream_mocks(_make_conversation())

    with (
        _wired(app, mock_convs, mock_experts),
        patch("peritus.chat.streaming.stream_expert_answer", new=_fake_stream(events)),
    ):
        resp = await client.post(
            f"/conversations/{CONV_ID}/messages", json={"question": "What is virtue?"}
        )

    assert resp.status_code == 200
    # meta event first, then the shared protocol.
    payloads = [json.loads(line[5:]) for line in resp.text.splitlines() if line.startswith("data:")]
    assert payloads[0]["type"] == "meta"
    assert payloads[0]["conversation_id"] == CONV_ID
    assert payloads[0]["title"] == "What is virtue?"
    assert [p["type"] for p in payloads[1:]] == ["status", "token", "token", "sources", "done"]

    mock_convs.add_user_message.assert_awaited_once_with(
        CONV_ID, "What is virtue?", fallback_title="What is virtue?"
    )
    mock_convs.finish_stream.assert_awaited_once_with(
        CONV_ID, "Virtue is enough.", citations, False, interrupted=False
    )


@pytest.mark.asyncio
async def test_send_message_busy_claim_409(client, app):
    mock_convs, mock_experts = _stream_mocks(_make_conversation())
    mock_convs.claim_stream = AsyncMock(return_value=False)
    with _wired(app, mock_convs, mock_experts):
        resp = await client.post(f"/conversations/{CONV_ID}/messages", json={"question": "hi"})
    assert resp.status_code == 409
    assert "already streaming" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_send_message_after_share_revoked_403(client, app):
    """A viewer's chat outlives the link it came through, but cannot continue."""
    mock_convs, mock_experts = _stream_mocks(_make_conversation())
    mock_experts.is_readable_by = AsyncMock(return_value=False)
    with _wired(app, mock_convs, mock_experts):
        resp = await client.post(f"/conversations/{CONV_ID}/messages", json={"question": "hi"})
    assert resp.status_code == 403
    assert "no longer shared" in resp.json()["detail"]
    mock_convs.claim_stream.assert_not_awaited()
    mock_convs.add_user_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_expert_not_ready_409(client, readiness, app):
    readiness["value"] = Readiness.PENDING
    mock_convs, mock_experts = _stream_mocks(
        _make_conversation(), expert=_make_expert(ExpertStatus.BUILDING)
    )
    with _wired(app, mock_convs, mock_experts):
        resp = await client.post(f"/conversations/{CONV_ID}/messages", json={"question": "hi"})
    assert resp.status_code == 409
    mock_convs.claim_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_error_persists_partial_interrupted(client, app):
    events = [
        {"type": "token", "text": "Virtue is"},
        RuntimeError("anthropic exploded"),
    ]
    mock_convs, mock_experts = _stream_mocks(_make_conversation())

    with (
        _wired(app, mock_convs, mock_experts),
        patch("peritus.chat.streaming.stream_expert_answer", new=_fake_stream(events)),
    ):
        resp = await client.post(
            f"/conversations/{CONV_ID}/messages", json={"question": "What is virtue?"}
        )

    assert resp.status_code == 200
    assert '"error"' in resp.text
    mock_convs.finish_stream.assert_awaited_once_with(
        CONV_ID, "Virtue is", None, False, interrupted=True
    )


@pytest.mark.asyncio
async def test_send_message_retry_reuses_orphaned_question(client, app):
    # Last stored message is the same user question (its stream died with zero
    # tokens): no duplicate insert, history excludes it.
    history = [
        {"role": "user", "content": "Old question"},
        {"role": "assistant", "content": "Old answer"},
        {"role": "user", "content": "What is virtue?"},
    ]
    events = [{"type": "token", "text": "ok"}, {"type": "done"}]
    conv = _make_conversation(title="What is virtue?", message_count=3)
    mock_convs, mock_experts = _stream_mocks(conv, history=history)

    captured: dict = {}

    async def gen(pool, expert, question, hist, conversation_id=None):
        captured["history"] = hist
        captured["conversation_id"] = conversation_id
        for ev in events:
            yield ev

    with (
        _wired(app, mock_convs, mock_experts),
        patch("peritus.chat.streaming.stream_expert_answer", new=gen),
    ):
        resp = await client.post(
            f"/conversations/{CONV_ID}/messages", json={"question": "What is virtue?"}
        )

    assert resp.status_code == 200
    mock_convs.add_user_message.assert_not_awaited()
    assert captured["history"] == history[:-1]


@pytest.mark.asyncio
async def test_send_message_question_too_long_422(client, app):
    with _wired(app):
        resp = await client.post(
            f"/conversations/{CONV_ID}/messages", json={"question": "x" * 4001}
        )
    assert resp.status_code == 422
