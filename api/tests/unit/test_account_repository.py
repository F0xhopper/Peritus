"""DB-backed tests for account deletion and the session list.

The local test database has no Supabase ``auth`` schema, so each test builds the
two tables the repository touches — with the cascade Supabase has from
``auth.users`` to ``auth.sessions`` — and drops them afterwards. Deletion is the
one irreversible thing an account can do, so the test is on what survives it:
everything of the person's goes, everything of anyone else's stays.

Skips without ``PERITUS_TEST_DATABASE_URL`` (see ``tests/conftest.py``).
"""

import pytest

from peritus.accounts.repository import AccountRepository, AuthSchemaUnavailable
from peritus.billing.service import EntitlementService
from peritus.chat.conversation_repository import ConversationRepository
from peritus.experts.domain import ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.experts.share_repository import ShareRepository

LEAVER = "11111111-1111-1111-1111-111111111111"
STAYER = "22222222-2222-2222-2222-222222222222"
S1 = "aaaaaaaa-0000-0000-0000-000000000001"
S2 = "aaaaaaaa-0000-0000-0000-000000000002"
S3 = "aaaaaaaa-0000-0000-0000-000000000003"


@pytest.fixture
async def auth_schema(db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            CREATE SCHEMA auth;
            CREATE TABLE auth.users (
                id UUID PRIMARY KEY,
                email TEXT,
                encrypted_password TEXT
            );
            CREATE TABLE auth.sessions (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ,
                refreshed_at TIMESTAMP,
                not_after TIMESTAMPTZ,
                user_agent TEXT,
                ip INET
            );
            """
        )
        await conn.execute(
            "INSERT INTO auth.users VALUES ($1, 'leaver@x.org', '$2a$10$hash'), "
            "($2, 'stayer@x.org', '')",
            LEAVER,
            STAYER,
        )
    yield db_pool
    async with db_pool.acquire() as conn:
        await conn.execute("DROP SCHEMA auth CASCADE")


async def _expert(pool, name, owner):
    return await ExpertRepository(pool).create(
        name=name, topic=name, tier=ExpertTier.LITE, owner_id=owner
    )


async def test_without_auth_schema_says_so(db_pool):
    repo = AccountRepository(db_pool)
    with pytest.raises(AuthSchemaUnavailable):
        await repo.list_sessions(LEAVER)
    with pytest.raises(AuthSchemaUnavailable):
        await repo.delete_account(LEAVER)


async def test_has_password(auth_schema):
    repo = AccountRepository(auth_schema)
    assert await repo.has_password(LEAVER) is True
    assert await repo.has_password(STAYER) is False


async def test_sessions_are_the_callers_live_ones_newest_first(auth_schema):
    async with auth_schema.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO auth.sessions (id, user_id, created_at, updated_at, user_agent, ip, not_after)
            VALUES ($1, $4, now() - interval '2 days', now() - interval '1 day', 'Old', '10.0.0.1', NULL),
                   ($2, $4, now() - interval '1 hour', now(), 'New', NULL, NULL),
                   ($3, $4, now() - interval '9 days', now() - interval '9 days', 'Dead', NULL,
                    now() - interval '1 day')
            """,
            S1,
            S2,
            S3,
            LEAVER,
        )
    repo = AccountRepository(auth_schema)
    sessions = await repo.list_sessions(LEAVER)
    assert [s.id for s in sessions] == [S2, S1]
    assert sessions[1].ip == "10.0.0.1"
    assert await repo.list_sessions(STAYER) == []


async def test_a_session_can_only_be_revoked_by_its_owner(auth_schema):
    async with auth_schema.acquire() as conn:
        await conn.execute("INSERT INTO auth.sessions (id, user_id) VALUES ($1, $2)", S1, LEAVER)
    repo = AccountRepository(auth_schema)
    assert await repo.delete_session(STAYER, S1) is False
    assert await repo.delete_session(LEAVER, S1) is True
    assert await repo.list_sessions(LEAVER) == []


async def test_delete_account_removes_everything_of_theirs_and_nothing_else(auth_schema):
    pool = auth_schema
    shares = ShareRepository(pool)
    conversations = ConversationRepository(pool)
    billing = EntitlementService(pool)

    mine = await _expert(pool, "leaver-expert", LEAVER)
    theirs = await _expert(pool, "stayer-expert", STAYER)
    await conversations.create(mine.id, LEAVER)
    # A chat on someone else's shared expert is the leaver's, and goes too.
    await conversations.create(theirs.id, LEAVER)
    kept_chat = await conversations.create(theirs.id, STAYER)
    link = await shares.enable(theirs.id, STAYER)
    await shares.grant(link.id, LEAVER)
    await billing.ensure_account(LEAVER, "leaver@x.org")
    await billing.ensure_account(STAYER, "stayer@x.org")
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO auth.sessions (id, user_id) VALUES ($1, $2)", S1, LEAVER)
        await conn.execute(
            "INSERT INTO build_jobs (expert_id, status, tier) VALUES ($1, 'running', 'lite')",
            mine.id,
        )

    counts = await AccountRepository(pool).delete_account(LEAVER)

    assert (counts.experts, counts.conversations) == (1, 2)
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM auth.users WHERE id = $1", LEAVER) == 0
        assert await conn.fetchval("SELECT count(*) FROM auth.sessions") == 0
        assert await conn.fetchval("SELECT count(*) FROM experts WHERE id = $1", mine.id) == 0
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM expert_share_grants WHERE user_id = $1", LEAVER
            )
            == 0
        )
        assert await conn.fetchval("SELECT count(*) FROM accounts WHERE owner_id = $1", LEAVER) == 0
        assert (
            await conn.fetchval("SELECT count(*) FROM conversations WHERE owner_id = $1", LEAVER)
            == 0
        )
        # The other person's things are untouched.
        assert await conn.fetchval("SELECT count(*) FROM auth.users WHERE id = $1", STAYER) == 1
        assert await conn.fetchval("SELECT count(*) FROM experts WHERE id = $1", theirs.id) == 1
        assert (
            await conn.fetchval("SELECT count(*) FROM conversations WHERE id = $1", kept_chat.id)
            == 1
        )
        assert await conn.fetchval("SELECT count(*) FROM accounts WHERE owner_id = $1", STAYER) == 1
        assert await conn.fetchval("SELECT count(*) FROM expert_share_links") == 1
