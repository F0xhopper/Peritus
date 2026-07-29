"""Pool construction, connection init, and the vector capability probe.

The properties here are all ones whose absence is silent: a pool with no
statement timeout looks identical to one with, until a slow query pins every
connection; codecs registered per query instead of per connection cost three
round trips a search and nothing visible; a closed pool left in the global
fails later, somewhere else.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from peritus.core.config import settings
from peritus.infrastructure import database


@pytest.fixture(autouse=True)
def clean_module_state(monkeypatch):
    monkeypatch.setattr(database, "_pool", None)
    monkeypatch.setattr(database, "_halfvec_supported", False)


def _fake_pool(halfvec: bool = True) -> MagicMock:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=halfvec)
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    pool.close = AsyncMock()
    return pool


# ── pool construction ──


async def test_pool_is_created_with_a_statement_timeout():
    """Without one, a single pathological query pins a connection forever."""
    with patch.object(
        database.asyncpg, "create_pool", AsyncMock(return_value=_fake_pool())
    ) as create_pool:
        await database.init_pool()

    kwargs = create_pool.call_args.kwargs
    assert kwargs["command_timeout"] == settings.DB_COMMAND_TIMEOUT
    assert kwargs["min_size"] == settings.DB_POOL_MIN_SIZE
    assert kwargs["max_size"] == settings.DB_POOL_MAX_SIZE
    # Supabase's transaction pooler cannot see server-side prepared statements.
    assert kwargs["statement_cache_size"] == 0
    assert kwargs["init"] is database._init_connection


async def test_init_pool_is_idempotent():
    with patch.object(
        database.asyncpg, "create_pool", AsyncMock(return_value=_fake_pool())
    ) as create_pool:
        await database.init_pool()
        await database.init_pool()

    assert create_pool.await_count == 1


# ── connection init ──


async def test_vector_codecs_are_registered_once_per_connection():
    """The hot-path fix: register_vector costs up to three introspection round
    trips, and a chat turn runs four to six searches in parallel."""
    conn = AsyncMock()
    with patch("pgvector.asyncpg.register_vector", AsyncMock()) as register:
        await database._init_connection(conn)

    register.assert_awaited_once_with(conn)
    executed = [call.args[0] for call in conn.execute.await_args_list]
    assert any("CREATE EXTENSION IF NOT EXISTS vector" in sql for sql in executed)
    assert any("CREATE EXTENSION IF NOT EXISTS pg_trgm" in sql for sql in executed)


async def test_search_no_longer_registers_codecs_per_query():
    """Guards the regression directly: reintroducing a per-query registration
    is an easy, invisible edit."""
    import inspect

    from peritus.search import service

    assert "register_vector" not in inspect.getsource(service)


# ── the capability probe ──


@pytest.mark.parametrize("available", [True, False])
async def test_probe_records_halfvec_availability(available):
    with patch.object(
        database.asyncpg, "create_pool", AsyncMock(return_value=_fake_pool(halfvec=available))
    ):
        await database.init_pool()

    assert database.halfvec_supported() is available


async def test_probe_failure_degrades_to_unsupported():
    """A probe that cannot run must not stop the server booting — it only picks
    the distance expression, and the unindexed one is always correct."""
    pool = _fake_pool()
    pool.acquire = MagicMock(side_effect=OSError("connection reset"))

    with patch.object(database.asyncpg, "create_pool", AsyncMock(return_value=pool)):
        await database.init_pool()

    assert database.halfvec_supported() is False
    assert database.get_pool() is pool


async def test_missing_halfvec_is_warned_about_loudly(caplog):
    """The whole failure mode is silent — no index, correct results, slow."""
    import logging

    with caplog.at_level(logging.WARNING, logger="peritus.infrastructure.database"), \
         patch.object(
             database.asyncpg, "create_pool", AsyncMock(return_value=_fake_pool(halfvec=False))
         ):
        await database.init_pool()

    assert any("exact scan" in r.getMessage() for r in caplog.records)


# ── lifecycle ──


async def test_get_pool_before_init_is_an_explicit_error():
    with pytest.raises(RuntimeError, match="not initialised"):
        database.get_pool()


async def test_close_pool_clears_the_global():
    """A closed pool left behind fails at query time, in some unrelated caller,
    instead of saying it is gone — and it blocks re-entering the lifespan."""
    pool = _fake_pool()
    with patch.object(database.asyncpg, "create_pool", AsyncMock(return_value=pool)):
        await database.init_pool()

    await database.close_pool()

    pool.close.assert_awaited_once()
    with pytest.raises(RuntimeError, match="not initialised"):
        database.get_pool()


async def test_pool_can_be_reinitialised_after_close():
    with patch.object(
        database.asyncpg, "create_pool", AsyncMock(side_effect=[_fake_pool(), _fake_pool()])
    ) as create_pool:
        await database.init_pool()
        await database.close_pool()
        await database.init_pool()

    assert create_pool.await_count == 2
    assert isinstance(database.get_pool(), MagicMock)


async def test_close_pool_is_safe_when_never_initialised():
    await database.close_pool()  # must not raise


def test_asyncpg_is_the_module_under_patch():
    """Sanity: the tests above patch the symbol the module actually calls."""
    assert database.asyncpg is asyncpg
