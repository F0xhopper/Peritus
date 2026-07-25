"""DB-backed tests for ConversationRepository.

Claim contention, title-once semantics, JSONB citation round-trips, recents
filtering and FK cascades are Postgres behaviour that mocks can't verify.
Requires PERITUS_TEST_DATABASE_URL pointing at a migrated throwaway database
(014_conversations.sql applied); skips otherwise via the db_pool fixture.
"""

import pytest

from peritus.chat.conversation_repository import ConversationRepository
from peritus.experts.domain import ExpertTier
from peritus.experts.repository import ExpertRepository

OWNER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

CITATIONS = [{"n": 1, "label": "Meditations, Book 2", "source_id": 7}]


async def _make_expert(db_pool, name="stoicism", owner_id=OWNER):
    return await ExpertRepository(db_pool).create(
        name=name, topic=name, tier=ExpertTier.LITE, owner_id=owner_id
    )


@pytest.mark.asyncio
async def test_visibility_scoping(db_pool):
    expert = await _make_expert(db_pool)
    repo = ConversationRepository(db_pool)
    conv = await repo.create(expert.id, OWNER)

    assert await repo.get_for_user(conv.id, OWNER, include_unowned=False) is not None
    # Another user sees nothing — and admin include_unowned only adds legacy
    # NULL-owned rows, not other users' rows.
    assert await repo.get_for_user(conv.id, OTHER, include_unowned=False) is None
    assert await repo.get_for_user(conv.id, OTHER, include_unowned=True) is None

    legacy = await repo.create(expert.id, None)
    assert await repo.get_for_user(legacy.id, OTHER, include_unowned=True) is not None


@pytest.mark.asyncio
async def test_claim_contention_and_release(db_pool):
    expert = await _make_expert(db_pool)
    repo = ConversationRepository(db_pool)
    conv = await repo.create(expert.id, OWNER)

    assert await repo.claim_stream(conv.id) is True
    assert await repo.claim_stream(conv.id) is False  # second sender loses
    await repo.release_claim(conv.id)
    assert await repo.claim_stream(conv.id) is True


@pytest.mark.asyncio
async def test_stale_claim_self_heals(db_pool):
    expert = await _make_expert(db_pool)
    repo = ConversationRepository(db_pool)
    conv = await repo.create(expert.id, OWNER)

    assert await repo.claim_stream(conv.id) is True
    # Simulate a crashed stream: age the claim past the stale window.
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE conversations SET streaming_started_at = now() - interval '4 minutes'"
            " WHERE id = $1::uuid",
            conv.id,
        )
    assert await repo.claim_stream(conv.id) is True


@pytest.mark.asyncio
async def test_title_set_only_on_first_message(db_pool):
    expert = await _make_expert(db_pool)
    repo = ConversationRepository(db_pool)
    conv = await repo.create(expert.id, OWNER)

    updated = await repo.add_user_message(conv.id, "What is virtue?", "What is virtue?")
    assert updated.title == "What is virtue?"
    assert updated.message_count == 1

    updated = await repo.add_user_message(conv.id, "And courage?", "And courage?")
    assert updated.title == "What is virtue?"  # COALESCE keeps the first title
    assert updated.message_count == 2


@pytest.mark.asyncio
async def test_finish_stream_persists_assistant_with_citations(db_pool):
    expert = await _make_expert(db_pool)
    repo = ConversationRepository(db_pool)
    conv = await repo.create(expert.id, OWNER)
    await repo.add_user_message(conv.id, "What is virtue?", "What is virtue?")
    await repo.claim_stream(conv.id)

    await repo.finish_stream(
        conv.id, "Virtue is enough. [1]", CITATIONS, True, interrupted=False
    )

    messages = await repo.get_messages(conv.id)
    assert [m.role for m in messages] == ["user", "assistant"]
    answer = messages[-1]
    assert answer.content == "Virtue is enough. [1]"
    assert answer.citations == CITATIONS  # JSONB round-trip, exact shape
    assert answer.has_contradiction is True
    assert answer.interrupted is False

    fresh = await repo.get_for_user(conv.id, OWNER, include_unowned=False)
    assert fresh is not None
    assert fresh.message_count == 2
    assert fresh.streaming_started_at is None  # claim cleared


@pytest.mark.asyncio
async def test_finish_stream_zero_tokens_clears_claim_only(db_pool):
    expert = await _make_expert(db_pool)
    repo = ConversationRepository(db_pool)
    conv = await repo.create(expert.id, OWNER)
    await repo.add_user_message(conv.id, "What is virtue?", "What is virtue?")
    await repo.claim_stream(conv.id)

    await repo.finish_stream(conv.id, "", None, False, interrupted=True)

    messages = await repo.get_messages(conv.id)
    assert [m.role for m in messages] == ["user"]  # orphaned question kept, no assistant row
    fresh = await repo.get_for_user(conv.id, OWNER, include_unowned=False)
    assert fresh is not None
    assert fresh.streaming_started_at is None


@pytest.mark.asyncio
async def test_interrupted_partial_persisted(db_pool):
    expert = await _make_expert(db_pool)
    repo = ConversationRepository(db_pool)
    conv = await repo.create(expert.id, OWNER)
    await repo.add_user_message(conv.id, "What is virtue?", "What is virtue?")

    await repo.finish_stream(conv.id, "Virtue is", None, False, interrupted=True)

    answer = (await repo.get_messages(conv.id))[-1]
    assert answer.interrupted is True
    assert answer.citations is None


@pytest.mark.asyncio
async def test_recent_history_shape_and_window(db_pool):
    expert = await _make_expert(db_pool)
    repo = ConversationRepository(db_pool)
    conv = await repo.create(expert.id, OWNER)
    await repo.add_user_message(conv.id, "q1", "q1")
    await repo.finish_stream(conv.id, "a1", None, False, interrupted=False)
    await repo.add_user_message(conv.id, "q2", "q2")

    history = await repo.recent_history(conv.id, limit=10)
    assert history == [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
    ]
    # Window keeps the *last* N, oldest-first.
    assert await repo.recent_history(conv.id, limit=2) == history[-2:]


@pytest.mark.asyncio
async def test_recents_filter_empties_and_order(db_pool):
    expert = await _make_expert(db_pool)
    repo = ConversationRepository(db_pool)

    older = await repo.create(expert.id, OWNER)
    newer = await repo.create(expert.id, OWNER)
    empty = await repo.create(expert.id, OWNER)  # never gets a message

    await repo.add_user_message(older.id, "first", "first")
    await repo.add_user_message(newer.id, "second", "second")

    recents = await repo.list_recent_for_user(OWNER, include_unowned=False, limit=10)
    assert [c.id for c in recents] == [newer.id, older.id]
    assert empty.id not in {c.id for c in recents}
    # Expert columns joined in for the sidebar row.
    assert recents[0].expert_slug == "stoicism"
    assert recents[0].expert_status is not None

    per_expert = await repo.list_for_expert(expert.id)
    assert [c.id for c in per_expert] == [newer.id, older.id]


@pytest.mark.asyncio
async def test_expert_cascade_deletes_conversations(db_pool):
    expert = await _make_expert(db_pool)
    repo = ConversationRepository(db_pool)
    conv = await repo.create(expert.id, OWNER)
    await repo.add_user_message(conv.id, "q", "q")

    await ExpertRepository(db_pool).delete(expert.id)

    assert await repo.get_for_user(conv.id, OWNER, include_unowned=False) is None
    async with db_pool.acquire() as conn:
        left = await conn.fetchval(
            "SELECT count(*) FROM conversation_messages WHERE conversation_id = $1::uuid",
            conv.id,
        )
    assert left == 0


@pytest.mark.asyncio
async def test_delete_conversation_scoped(db_pool):
    expert = await _make_expert(db_pool)
    repo = ConversationRepository(db_pool)
    conv = await repo.create(expert.id, OWNER)

    assert await repo.delete(conv.id, OTHER, include_unowned=False) is False
    assert await repo.delete(conv.id, OWNER, include_unowned=False) is True
    assert await repo.get_for_user(conv.id, OWNER, include_unowned=False) is None
