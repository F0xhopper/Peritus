"""Shared fixtures.

Queue/worker tests need a real Postgres because they exercise `FOR UPDATE SKIP
LOCKED`, partial unique indexes and heartbeat reaping — behaviour that cannot be
mocked meaningfully. Point them at a throwaway, already-migrated database via
`PERITUS_TEST_DATABASE_URL`; they skip when it is unset so the default suite needs
no infrastructure.
"""

import contextlib
import os
from unittest.mock import MagicMock

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

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
    # Accounts must be truncated too: the credits tests provision the same owner
    # id and assume its signup grant fires fresh each test — a leftover account
    # row (with whatever plan/ledger the previous test left it on) breaks them.
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE experts RESTART IDENTITY CASCADE")
        await conn.execute("TRUNCATE accounts RESTART IDENTITY CASCADE")
    yield pool
    await pool.close()


@pytest.fixture(autouse=True)
def _no_live_primary_text_suggestions(monkeypatch):
    """The feedback round's primary-text suggestion is a strong-model call.

    Tests that exercise the discovery loop must not reach the API through it;
    a test about suggestions patches it with its own stub over this one.
    """

    async def _none(*_args, **_kwargs):
        return []

    monkeypatch.setattr("peritus.experts.builder.suggest_primary_texts", _none)


def _returns(value):
    """A zero-argument provider for `dependency_overrides`.

    Deliberately not `lambda v=value: v`. FastAPI reads an override's signature
    the same way it reads a route's, so that parameter becomes a *query
    parameter* named `v` with the object as its default — and the value the
    handler receives is whatever pydantic makes of it, not the object the test
    passed in. The symptom is a mock that serves the right data while recording
    none of the calls.
    """

    def _provider():
        return value

    return _provider


@pytest.fixture
def api_app():
    """A FastAPI app with its collaborators replaceable.

    `app.dependency_overrides` rather than `patch("peritus.api.routes.X.Y")`:
    the routes take their repositories and services as dependencies (see
    `peritus.api.deps`), so a test names what it is substituting instead of
    reaching into a module's namespace — and the substitution is scoped to the
    app rather than to the process.

        app = api_app(user=OWNER, expert_repo=experts, shares=shares)

    `user=None` leaves the real auth dependency in place, which is how the "this
    route requires a session" tests are written.
    """
    from peritus.api import deps
    from peritus.api.app import create_app
    from peritus.api.auth import AuthUser, require_user

    # Keyword → the provider it replaces. Every one is a callable in `deps`.
    providers = {
        "pool": deps.db_pool,
        "expert_repo": deps.expert_repo,
        "expert_service": deps.expert_service,
        "jobs": deps.job_repo,
        "audits": deps.audit_service,
        "conversations": deps.conversation_repo,
        "uploads": deps.upload_repo,
        "shares": deps.share_repo,
        "pictures": deps.picture_repo,
        "billing": deps.billing_repo,
        "entitlements": deps.entitlements,
    }

    def _build(
        user: str | None = None,
        is_admin: bool = False,
        email: str = "u@test",
        **overrides,
    ):
        unknown = set(overrides) - set(providers)
        if unknown:
            raise TypeError(f"api_app got unknown override(s): {', '.join(sorted(unknown))}")

        app = create_app()
        if user is not None:
            app.dependency_overrides[require_user] = lambda: AuthUser(
                id=user, email=email, is_admin=is_admin
            )
        # A pool is always provided: nothing should reach the real one, and
        # `get_pool()` raises when no pool has been initialised.
        app.dependency_overrides[deps.db_pool] = _returns(overrides.get("pool") or MagicMock())
        for key, value in overrides.items():
            if key == "pool":
                continue
            app.dependency_overrides[providers[key]] = _returns(value)
        return app

    return _build


async def call_api(app, method: str, path: str, **kwargs):
    """One request against an ASGI app, with no network."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@contextlib.contextmanager
def override_dep(app, provider, value):
    """Replace one dependency for the duration of the block, then restore it.

    A drop-in for `patch("peritus.api.routes.X.SomeRepository", return_value=…)`
    that names the dependency rather than the module attribute, so it keeps
    working when a handler moves between route files.
    """
    previous = app.dependency_overrides.get(provider)
    app.dependency_overrides[provider] = _returns(value)
    try:
        yield value
    finally:
        if previous is None:
            app.dependency_overrides.pop(provider, None)
        else:
            app.dependency_overrides[provider] = previous


class _LazyDep:
    """Stands in for `patch("…SomeRepository") as MockRepo`.

    The patched-class idiom sets `MockRepo.return_value` *inside* the `with`
    block, after the override would already have been installed. Dependency
    overrides are read per request, not at install time, so this holds the value
    and hands it over whenever the request finally arrives.
    """

    def __init__(self) -> None:
        self.return_value = None

    def __call__(self):
        return self.return_value


@contextlib.contextmanager
def lazy_dep(app, provider):
    """`with lazy_dep(app, deps.job_repo) as MockJobs:` then `MockJobs.return_value = …`."""
    previous = app.dependency_overrides.get(provider)
    stub = _LazyDep()
    app.dependency_overrides[provider] = stub
    try:
        yield stub
    finally:
        if previous is None:
            app.dependency_overrides.pop(provider, None)
        else:
            app.dependency_overrides[provider] = previous
