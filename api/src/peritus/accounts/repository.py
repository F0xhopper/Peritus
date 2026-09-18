"""The parts of an account that GoTrue's user API does not expose.

GoTrue answers "who is this" and "change my password", but it has no endpoint
that lists a user's sessions, none that says whether an account has a password
at all, and deleting a user needs the service role. The API's own Postgres
connection *is* the service role on Supabase, so these read and write the
``auth`` schema directly — always keyed on the caller's own id, never on
anything from a request body.

On a plain local Postgres there is no ``auth`` schema. Every method here says so
with :class:`AuthSchemaUnavailable` instead of answering "no sessions" or
"no password", which would be a lie a UI would then render.
"""

from dataclasses import dataclass
from datetime import datetime

import asyncpg

from peritus.core.logging import get_logger

logger = get_logger(__name__)


class AuthSchemaUnavailable(Exception):
    """This database has no Supabase ``auth`` schema (local development)."""


@dataclass(frozen=True)
class SignInSession:
    id: str
    created_at: datetime
    last_active_at: datetime | None
    user_agent: str | None


@dataclass(frozen=True)
class DeletionCounts:
    experts: int
    conversations: int


class AccountRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._has_auth: bool | None = None

    async def _require_auth_schema(self, conn: asyncpg.Connection) -> None:
        if self._has_auth is None:
            self._has_auth = bool(
                await conn.fetchval("SELECT to_regclass('auth.users') IS NOT NULL")
            )
        if not self._has_auth:
            raise AuthSchemaUnavailable

    async def has_password(self, user_id: str) -> bool:
        async with self._pool.acquire() as conn:
            await self._require_auth_schema(conn)
            return bool(
                await conn.fetchval(
                    "SELECT coalesce(encrypted_password, '') <> '' "
                    "FROM auth.users WHERE id = $1::uuid",
                    user_id,
                )
            )

    async def list_sessions(self, user_id: str) -> list[SignInSession]:
        """Live sessions, most recently used first.

        A session past ``not_after`` is dead whatever its row says, so it is not
        shown as something to sign out of.
        """
        async with self._pool.acquire() as conn:
            await self._require_auth_schema(conn)
            rows = await conn.fetch(
                """
                SELECT id::text AS id,
                       created_at,
                       coalesce(refreshed_at, updated_at) AS last_active_at,
                       user_agent
                FROM auth.sessions
                WHERE user_id = $1::uuid
                  AND (not_after IS NULL OR not_after > now())
                ORDER BY coalesce(refreshed_at, updated_at, created_at) DESC
                LIMIT 50
                """,
                user_id,
            )
        return [
            SignInSession(
                id=r["id"],
                created_at=r["created_at"],
                last_active_at=r["last_active_at"],
                user_agent=r["user_agent"],
            )
            for r in rows
        ]

    async def delete_session(self, user_id: str, session_id: str) -> bool:
        """End one session. Its refresh tokens go with it (FK cascade), so the
        device is signed out at its next refresh — within the access token's
        lifetime, an hour at most."""
        async with self._pool.acquire() as conn:
            await self._require_auth_schema(conn)
            result = await conn.execute(
                "DELETE FROM auth.sessions WHERE id = $1::uuid AND user_id = $2::uuid",
                session_id,
                user_id,
            )
        return not result.endswith(" 0")

    async def delete_account(self, user_id: str) -> DeletionCounts:
        """Delete the account and everything it owns, in one transaction.

        Most rows would go by ``ON DELETE CASCADE`` from ``auth.users`` — but only
        where migration 011/014/016 found the ``auth`` schema and added the FK,
        and a few columns (share grants, uploads) never had one. So every table
        with an owner column is named here explicitly rather than trusting the
        cascade. Spend records in ``build_usage_events`` are kept for cost
        accounting and dissociated from the person.
        """
        async with self._pool.acquire() as conn:
            await self._require_auth_schema(conn)
            async with conn.transaction():
                # Stop any build the worker is running for these experts; it sees
                # the cancel on its next heartbeat instead of racing the delete.
                await conn.execute(
                    """
                    UPDATE build_jobs SET status = 'cancelled', updated_at = NOW()
                    WHERE status IN ('queued', 'running')
                      AND expert_id IN (SELECT id FROM experts WHERE owner_id = $1::uuid)
                    """,
                    user_id,
                )
                await conn.execute(
                    "DELETE FROM expert_share_grants WHERE user_id = $1::uuid", user_id
                )
                conversations = await conn.fetchval(
                    "WITH d AS (DELETE FROM conversations WHERE owner_id = $1::uuid RETURNING 1) "
                    "SELECT count(*) FROM d",
                    user_id,
                )
                await conn.execute("DELETE FROM source_uploads WHERE owner_id = $1", user_id)
                experts = await conn.fetchval(
                    "WITH d AS (DELETE FROM experts WHERE owner_id = $1::uuid RETURNING 1) "
                    "SELECT count(*) FROM d",
                    user_id,
                )
                await conn.execute(
                    "UPDATE build_usage_events SET owner_id = NULL WHERE owner_id = $1::uuid",
                    user_id,
                )
                await conn.execute("DELETE FROM accounts WHERE owner_id = $1::uuid", user_id)
                # Last: identities, sessions and refresh tokens cascade from here.
                await conn.execute("DELETE FROM auth.users WHERE id = $1::uuid", user_id)
        logger.info(
            "Account deleted: user=%s experts=%d conversations=%d",
            user_id,
            experts,
            conversations,
        )
        return DeletionCounts(experts=int(experts or 0), conversations=int(conversations or 0))
