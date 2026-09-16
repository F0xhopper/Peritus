"""DB-backed tests for share links (migration 031).

The security story is three sentences, and each gets a test:

- A slug alone never grants anything; a grant on a *live* link does.
- Resetting or disabling a link revokes every grant made on it, at once.
- A grant lets someone read and chat, never mutate, and never see other
  people's conversations or answer trails.

Skips without ``PERITUS_TEST_DATABASE_URL`` (see ``tests/conftest.py``).
"""

import pytest

from peritus.audit.repository import AuditRepository, AuditScope
from peritus.chat.conversation_repository import ConversationRepository
from peritus.experts.domain import ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.experts.share_repository import ShareRepository

OWNER = "11111111-1111-1111-1111-111111111111"
VIEWER = "22222222-2222-2222-2222-222222222222"
STRANGER = "33333333-3333-3333-3333-333333333333"


async def _expert(pool, name="thomism", owner=OWNER):
    expert = await ExpertRepository(pool).create(
        name=name, topic=name, tier=ExpertTier.LITE, owner_id=owner
    )
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE experts SET readiness = 'graph_ready', status = 'ready' WHERE id = $1",
            expert.id,
        )
    return expert


async def _readable(pool, slug, user):
    return await ExpertRepository(pool).get_for_user(slug, user, include_unowned=False)


@pytest.mark.asyncio
async def test_enable_is_idempotent_and_the_token_is_long(db_pool):
    expert = await _expert(db_pool)
    shares = ShareRepository(db_pool)

    first = await shares.enable(expert.id, OWNER)
    again = await shares.enable(expert.id, OWNER)

    assert first.token == again.token
    assert len(first.token) >= 32
    assert (await shares.get_active(expert.id)).id == first.id


@pytest.mark.asyncio
async def test_a_slug_grants_nothing_and_a_grant_grants_read(db_pool):
    expert = await _expert(db_pool)
    shares = ShareRepository(db_pool)
    link = await shares.enable(expert.id, OWNER)

    # Sharing is on, but knowing the slug is not holding the link.
    assert await _readable(db_pool, "thomism", VIEWER) is None
    assert await ExpertRepository(db_pool).get_public("thomism") is None

    await shares.grant(link.id, VIEWER)
    await shares.grant(link.id, VIEWER)  # opening the link twice is harmless

    assert await _readable(db_pool, "thomism", VIEWER) is not None
    assert await _readable(db_pool, "thomism", STRANGER) is None
    # Read, never mutate.
    repo = ExpertRepository(db_pool)
    assert await repo.get_owned_for_user("thomism", VIEWER, include_unowned=False) is None
    assert await shares.viewer_count(link.id) == 1


@pytest.mark.asyncio
async def test_token_resolves_only_while_live(db_pool):
    expert = await _expert(db_pool)
    shares = ShareRepository(db_pool)
    repo = ExpertRepository(db_pool)
    link = await shares.enable(expert.id, OWNER)

    assert (await repo.get_by_share_token(link.token)).id == expert.id
    assert await repo.get_by_share_token("x" * 32) is None

    await shares.disable(expert.id)
    assert await repo.get_by_share_token(link.token) is None
    assert await shares.resolve(link.token) is None


@pytest.mark.asyncio
async def test_reset_revokes_every_earlier_grant(db_pool):
    expert = await _expert(db_pool)
    shares = ShareRepository(db_pool)
    old = await shares.enable(expert.id, OWNER)
    await shares.grant(old.id, VIEWER)
    assert await _readable(db_pool, "thomism", VIEWER) is not None

    new = await shares.reset(expert.id, OWNER)

    assert new.token != old.token
    assert await _readable(db_pool, "thomism", VIEWER) is None
    assert await ExpertRepository(db_pool).get_by_share_token(old.token) is None
    assert await shares.viewer_count(new.id) == 0
    # Opening the new link restores access.
    await shares.grant(new.id, VIEWER)
    assert await _readable(db_pool, "thomism", VIEWER) is not None


@pytest.mark.asyncio
async def test_disable_revokes_and_re_enable_does_not_restore(db_pool):
    """Turning a link off and on again mints a new token — old holders stay out."""
    expert = await _expert(db_pool)
    shares = ShareRepository(db_pool)
    old = await shares.enable(expert.id, OWNER)
    await shares.grant(old.id, VIEWER)

    assert await shares.disable(expert.id) is True
    assert await shares.disable(expert.id) is False
    assert await _readable(db_pool, "thomism", VIEWER) is None

    new = await shares.enable(expert.id, OWNER)
    assert new.token != old.token
    assert await _readable(db_pool, "thomism", VIEWER) is None


@pytest.mark.asyncio
async def test_is_readable_by_follows_revocation(db_pool):
    expert = await _expert(db_pool)
    shares = ShareRepository(db_pool)
    repo = ExpertRepository(db_pool)
    link = await shares.enable(expert.id, OWNER)
    await shares.grant(link.id, VIEWER)

    assert await repo.is_readable_by(expert.id, VIEWER, include_unowned=False)
    assert await repo.is_readable_by(expert.id, OWNER, include_unowned=False)
    await shares.disable(expert.id)
    assert not await repo.is_readable_by(expert.id, VIEWER, include_unowned=False)


@pytest.mark.asyncio
async def test_workspace_lists_shared_experts_until_left_or_revoked(db_pool):
    mine = await _expert(db_pool, "mine", owner=VIEWER)
    theirs = await _expert(db_pool, "thomism", owner=OWNER)
    await _expert(db_pool, "unshared", owner=OWNER)
    shares = ShareRepository(db_pool)
    repo = ExpertRepository(db_pool)
    link = await shares.enable(theirs.id, OWNER)
    await shares.grant(link.id, VIEWER)

    names = {e.name for e in await repo.list_for_user(VIEWER, include_unowned=False)}
    assert names == {mine.name, theirs.name}
    # The owner's workspace does not grow because someone opened their link.
    assert {e.name for e in await repo.list_for_user(OWNER, include_unowned=False)} == {
        "thomism",
        "unshared",
    }

    assert await shares.remove_access(theirs.id, VIEWER) is True
    assert {e.name for e in await repo.list_for_user(VIEWER, include_unowned=False)} == {mine.name}


@pytest.mark.asyncio
async def test_viewers_and_owner_see_only_their_own_answer_trails(db_pool):
    expert = await _expert(db_pool)
    shares = ShareRepository(db_pool)
    link = await shares.enable(expert.id, OWNER)
    await shares.grant(link.id, VIEWER)
    convs = ConversationRepository(db_pool)
    owner_chat = await convs.create(expert.id, OWNER)
    viewer_chat = await convs.create(expert.id, VIEWER)

    async with db_pool.acquire() as conn:
        for conversation_id, question in (
            (owner_chat.id, "owner question"),
            (viewer_chat.id, "viewer question"),
            (None, "stateless question"),
        ):
            await conn.execute(
                """
                INSERT INTO answer_audits (expert_id, conversation_id, question)
                VALUES ($1, $2::uuid, $3)
                """,
                expert.id,
                conversation_id,
                question,
            )

    audits = AuditRepository(db_pool)

    async def questions(user, owns):
        scope = AuditScope(caller_id=user, include_unowned=False, owns_expert=owns)
        rows = await audits.list_answer_audits(expert.id, 50, 0, scope=scope)
        assert await audits.count_answer_audits(expert.id, scope=scope) == len(rows)
        return {r["question"] for r in rows}

    assert await questions(VIEWER, owns=False) == {"viewer question"}
    assert await questions(OWNER, owns=True) == {"owner question", "stateless question"}
    assert await questions(STRANGER, owns=False) == set()


@pytest.mark.asyncio
async def test_uploaded_source_count_counts_kept_uploads_only(db_pool):
    expert = await _expert(db_pool)
    async with db_pool.acquire() as conn:
        for via, passed in (("upload", True), ("upload", False), ("plan", True)):
            await conn.execute(
                """
                INSERT INTO sources (expert_id, source_type, url, title, passed, discovered_via)
                VALUES ($1, 'pdf', $2, 't', $3, $4)
                """,
                expert.id,
                f"https://example.org/{via}-{passed}",
                passed,
                via,
            )
    assert await ShareRepository(db_pool).uploaded_source_count(expert.id) == 1


@pytest.mark.asyncio
async def test_deleting_the_expert_removes_links_and_grants(db_pool):
    expert = await _expert(db_pool)
    shares = ShareRepository(db_pool)
    link = await shares.enable(expert.id, OWNER)
    await shares.grant(link.id, VIEWER)

    await ExpertRepository(db_pool).delete(expert.id)

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM expert_share_links") == 0
        assert await conn.fetchval("SELECT count(*) FROM expert_share_grants") == 0
