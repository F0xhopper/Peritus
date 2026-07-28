"""Shared fixtures.

Queue/worker tests need a real Postgres because they exercise `FOR UPDATE SKIP
LOCKED`, partial unique indexes and heartbeat reaping — behaviour that cannot be
mocked meaningfully. Point them at a throwaway, already-migrated database via
`PERITUS_TEST_DATABASE_URL`; they skip when it is unset so the default suite needs
no infrastructure.
"""

import os

import asyncpg
import pytest

from peritus.infrastructure.database import _init_connection

TEST_DB_URL = os.getenv("PERITUS_TEST_DATABASE_URL")


@pytest.fixture
async def db_pool():
    if not TEST_DB_URL:
        pytest.skip("PERITUS_TEST_DATABASE_URL not set — skipping DB-backed test")
    # Same init callback as the real pool, so tests see the same connection
    # setup — in particular the pgvector codecs, which production installs once
    # per connection rather than per query.
    pool = await asyncpg.create_pool(
        TEST_DB_URL, min_size=1, max_size=5, statement_cache_size=0, init=_init_connection
    )
    # Start each test from a clean slate; CASCADE clears sources/chunks/graph/jobs/events.
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE experts RESTART IDENTITY CASCADE")
    yield pool
    await pool.close()
