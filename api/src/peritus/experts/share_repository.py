"""Persistence for share links and the grants made on them (migration 031).

The model is a document's "anyone with the link" setting:

- An owner turns sharing on and gets one link. Turning it on again returns the
  same link, so a copied URL keeps working.
- Anyone signed in who opens the link gets a grant. Read access for a non-owner
  is a grant on a *live* link — see ``repository._granted_clause``.
- Resetting the link revokes the old row and mints a new token; turning sharing
  off revokes it. Either way every grant on the old row stops matching at once,
  and none of them has to be found and deleted.

Nothing here authorises anything: callers resolve ownership first
(``ExpertRepository.get_owned_for_user``) and map a miss to 404.
"""

import secrets

import asyncpg

from peritus.experts.domain import SHARE_TOKEN_BYTES, ShareLink


def new_share_token() -> str:
    return secrets.token_urlsafe(SHARE_TOKEN_BYTES)


class ShareRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_active(self, expert_id: int) -> ShareLink | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM expert_share_links WHERE expert_id = $1 AND revoked_at IS NULL",
                expert_id,
            )
        return _row_to_link(row) if row else None

    async def enable(self, expert_id: int, created_by: str | None) -> ShareLink:
        """Return the live link, minting one if there is none. Idempotent.

        A concurrent enable loses on the partial unique index and reads the
        winner's row instead of failing.
        """
        existing = await self.get_active(expert_id)
        if existing:
            return existing
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO expert_share_links (expert_id, token, created_by)
                VALUES ($1, $2, $3::uuid)
                ON CONFLICT (expert_id) WHERE revoked_at IS NULL DO NOTHING
                RETURNING *
                """,
                expert_id, new_share_token(), created_by,
            )
        if row:
            return _row_to_link(row)
        winner = await self.get_active(expert_id)
        assert winner is not None
        return winner

    async def reset(self, expert_id: int, created_by: str | None) -> ShareLink:
        """Revoke the live link (if any) and mint a new one, atomically."""
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                UPDATE expert_share_links SET revoked_at = now()
                WHERE expert_id = $1 AND revoked_at IS NULL
                """,
                expert_id,
            )
            row = await conn.fetchrow(
                """
                INSERT INTO expert_share_links (expert_id, token, created_by)
                VALUES ($1, $2, $3::uuid)
                RETURNING *
                """,
                expert_id, new_share_token(), created_by,
            )
        return _row_to_link(row)

    async def disable(self, expert_id: int) -> bool:
        """Revoke the live link. True if there was one."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE expert_share_links SET revoked_at = now()
                WHERE expert_id = $1 AND revoked_at IS NULL
                """,
                expert_id,
            )
        return result.rsplit(" ", 1)[-1] != "0"

    async def resolve(self, token: str) -> ShareLink | None:
        """The live link for a token, or None for an unknown or revoked one."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM expert_share_links WHERE token = $1 AND revoked_at IS NULL",
                token,
            )
        return _row_to_link(row) if row else None

    async def grant(self, link_id: str, user_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO expert_share_grants (link_id, user_id)
                VALUES ($1::uuid, $2::uuid)
                ON CONFLICT DO NOTHING
                """,
                link_id, user_id,
            )

    async def viewer_count(self, link_id: str) -> int:
        async with self._pool.acquire() as conn:
            n = await conn.fetchval(
                "SELECT count(*)::int FROM expert_share_grants WHERE link_id = $1::uuid",
                link_id,
            )
        return int(n or 0)

    async def remove_access(self, expert_id: int, user_id: str) -> bool:
        """Drop every grant this user holds on this expert, live or revoked.

        "Remove from my experts" for a viewer. Opening the link again re-grants.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM expert_share_grants g
                USING expert_share_links l
                WHERE l.id = g.link_id AND l.expert_id = $1 AND g.user_id = $2::uuid
                """,
                expert_id, user_id,
            )
        return result.rsplit(" ", 1)[-1] != "0"

    async def uploaded_source_count(self, expert_id: int) -> int:
        """Kept sources the owner uploaded. A viewer can read passages from these,
        so the share dialog names the number before the owner turns sharing on."""
        async with self._pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT count(*)::int FROM sources
                WHERE expert_id = $1 AND discovered_via = 'upload' AND passed = true
                """,
                expert_id,
            )
        return int(n or 0)


def _row_to_link(row: asyncpg.Record) -> ShareLink:
    return ShareLink(
        id=str(row["id"]),
        expert_id=row["expert_id"],
        token=row["token"],
        created_at=row["created_at"],
        created_by=str(row["created_by"]) if row["created_by"] else None,
        revoked_at=row["revoked_at"],
    )
