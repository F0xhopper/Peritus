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

TEST_DB_URL = os.getenv("PERITUS_TEST_DATABASE_URL")


@pytest.fixture
async def db_pool():
    if not TEST_DB_URL:
        pytest.skip("PERITUS_TEST_DATABASE_URL not set — skipping DB-backed test")
    pool = await asyncpg.create_pool(
        TEST_DB_URL, min_size=1, max_size=5, statement_cache_size=0
    )
    # Start each test from a clean slate; CASCADE clears sources/chunks/graph/jobs/events.
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE experts RESTART IDENTITY CASCADE")
    yield pool
    await pool.close()
