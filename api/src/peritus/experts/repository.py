import dataclasses
import json

import asyncpg

from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier


class ExpertRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(
        self,
        name: str,
        topic: str,
        tier: ExpertTier = ExpertTier.STANDARD,
        owner_id: str | None = None,
    ) -> Expert:
        config = ExpertConfig.from_tier(tier)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO experts (name, topic, status, tier, config, owner_id)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::uuid)
                RETURNING *
                """,
                name, topic, ExpertStatus.QUEUED.value,
                tier.value, json.dumps(dataclasses.asdict(config)), owner_id,
            )
        return _row_to_expert(row)

    async def get_by_id(self, expert_id: int) -> Expert | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM experts WHERE id = $1", expert_id)
        return _row_to_expert(row) if row else None

    async def get_by_name(self, name: str) -> Expert | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM experts WHERE lower(name) = lower($1)", name
            )
        return _row_to_expert(row) if row else None

    async def list_all(self) -> list[Expert]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT e.*,
                    COALESCE(
                        (SELECT jsonb_object_agg(source_type, cnt)
                         FROM (
                             SELECT source_type, COUNT(*)::int AS cnt
                             FROM sources
                             WHERE expert_id = e.id AND passed = true
                             GROUP BY source_type
                         ) sc),
                        '{}'::jsonb
                    ) AS source_type_counts
                FROM experts e
                ORDER BY e.created_at DESC
                """
            )
        return [_row_to_expert(r) for r in rows]

    async def list_for_user(self, owner_id: str, include_unowned: bool) -> list[Expert]:
        """Experts visible to a user: their own, plus legacy NULL-owned for admins."""
        clause, params = _visibility_clause(owner_id, include_unowned, alias="e", idx=1)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT e.*,
                    COALESCE(
                        (SELECT jsonb_object_agg(source_type, cnt)
                         FROM (
                             SELECT source_type, COUNT(*)::int AS cnt
                             FROM sources
                             WHERE expert_id = e.id AND passed = true
                             GROUP BY source_type
                         ) sc),
                        '{{}}'::jsonb
                    ) AS source_type_counts
                FROM experts e
                WHERE {clause}
                ORDER BY e.created_at DESC
                """,
                *params,
            )
        return [_row_to_expert(r) for r in rows]

    async def get_for_user(
        self, name: str, owner_id: str, include_unowned: bool
    ) -> Expert | None:
        """Get an expert by slug, only if the user is allowed to see it."""
        clause, params = _visibility_clause(owner_id, include_unowned, alias="experts", idx=2)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM experts WHERE lower(name) = lower($1) AND {clause}",
                name, *params,
            )
        return _row_to_expert(row) if row else None

    async def delete_for_user(
        self, name: str, owner_id: str, include_unowned: bool
    ) -> bool:
        """Delete an expert by slug if the user owns it. Returns True if a row went."""
        clause, params = _visibility_clause(owner_id, include_unowned, alias="experts", idx=2)
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM experts WHERE lower(name) = lower($1) AND {clause}",
                name, *params,
            )
        # asyncpg returns e.g. "DELETE 1"
        return result.rsplit(" ", 1)[-1] != "0"

    async def update_status(
        self,
        expert_id: int,
        status: ExpertStatus,
        error: str | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE experts
                SET status = $1, error = $2, updated_at = NOW()
                WHERE id = $3
                """,
                status.value, error, expert_id,
            )

    async def update_key_concepts(self, expert_id: int, key_concepts: list[str]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE experts SET key_concepts = $1::jsonb, updated_at = NOW() WHERE id = $2",
                json.dumps(key_concepts), expert_id,
            )

    async def update_counts(
        self,
        expert_id: int,
        source_count: int,
        chunk_count: int,
        node_count: int,
        edge_count: int,
        avg_quality: float | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE experts
                SET source_count = $1, chunk_count = $2,
                    node_count = $3, edge_count = $4,
                    avg_quality = $5, updated_at = NOW()
                WHERE id = $6
                """,
                source_count, chunk_count, node_count, edge_count, avg_quality, expert_id,
            )

    async def update_persona(
        self,
        expert_id: int,
        persona_name: str,
        persona_bio: str,
        persona_style: str,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE experts
                SET persona_name = $1, persona_bio = $2, persona_style = $3,
                    updated_at = NOW()
                WHERE id = $4
                """,
                persona_name, persona_bio, persona_style, expert_id,
            )

    async def update_config(self, expert_id: int, config: ExpertConfig) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE experts SET config = $1::jsonb, updated_at = NOW() WHERE id = $2",
                json.dumps(dataclasses.asdict(config)), expert_id,
            )

    async def reset_build_state(self, expert_id: int) -> None:
        """Clear all derived corpus state so a (re)build starts from a clean slate.

        Builds are not checkpointed, so a retry re-runs the whole pipeline. Deleting
        the previous attempt's sources/chunks/graph first keeps a retry from creating
        duplicate rows. Child tables cascade from `sources`, but we delete each
        explicitly so this is correct regardless of FK cascade direction.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM expert_edges WHERE expert_id = $1", expert_id)
            await conn.execute("DELETE FROM expert_nodes WHERE expert_id = $1", expert_id)
            await conn.execute("DELETE FROM source_chunks WHERE expert_id = $1", expert_id)
            await conn.execute("DELETE FROM sources WHERE expert_id = $1", expert_id)
            await conn.execute(
                """
                    UPDATE experts
                    SET source_count = 0, chunk_count = 0, node_count = 0,
                        edge_count = 0, avg_quality = NULL, error = NULL,
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                expert_id,
            )

    async def delete(self, expert_id: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM experts WHERE id = $1", expert_id)

    async def fuzzy_find(self, query: str) -> Expert | None:
        """Find the closest expert by name using trigram similarity."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT *, similarity(lower(name), lower($1)) AS sim
                FROM experts
                ORDER BY sim DESC
                LIMIT 1
                """,
                query,
            )
        if row and row["sim"] > 0.1:
            return _row_to_expert(row)
        return None


def _visibility_clause(
    owner_id: str, include_unowned: bool, alias: str, idx: int
) -> tuple[str, list]:
    """Build a WHERE fragment scoping experts to a user.

    Regular users see only their own experts. Admins additionally see legacy
    experts with no owner (owner_id IS NULL) so nothing predating auth is orphaned.
    ``idx`` is the 1-based position of the owner_id parameter in the final query.
    """
    own = f"{alias}.owner_id = ${idx}::uuid"
    if include_unowned:
        return (f"({own} OR {alias}.owner_id IS NULL)", [owner_id])
    return (own, [owner_id])


def _row_to_expert(row: asyncpg.Record) -> Expert:
    keys = row.keys()

    # key_concepts stored as JSONB — decode from string if asyncpg doesn't auto-decode.
    _raw_concepts = row["key_concepts"] if "key_concepts" in keys else None
    if isinstance(_raw_concepts, str):
        _raw_concepts = json.loads(_raw_concepts)
    key_concepts: list[str] = list(_raw_concepts) if _raw_concepts else []

    # source_type_counts is a computed column present only in list_all queries.
    source_type_counts: dict[str, int] = {}
    if "source_type_counts" in keys and row["source_type_counts"]:
        raw = row["source_type_counts"]
        source_type_counts = dict(raw) if isinstance(raw, dict) else json.loads(raw)

    # Tier and config — fall back to STANDARD defaults for rows predating the migration.
    tier = ExpertTier(row["tier"]) if "tier" in keys and row["tier"] else ExpertTier.STANDARD

    raw_config = row["config"] if "config" in keys else None
    if isinstance(raw_config, str):
        raw_config = json.loads(raw_config)
    config = ExpertConfig(**raw_config) if raw_config else ExpertConfig.from_tier(tier)

    owner_id = row["owner_id"] if "owner_id" in keys and row["owner_id"] else None

    return Expert(
        id=row["id"],
        name=row["name"],
        topic=row["topic"],
        status=ExpertStatus(row["status"]),
        owner_id=str(owner_id) if owner_id else None,
        tier=tier,
        config=config,
        persona_name=row["persona_name"],
        persona_bio=row["persona_bio"],
        persona_style=row["persona_style"],
        source_count=row["source_count"],
        chunk_count=row["chunk_count"],
        node_count=row["node_count"],
        edge_count=row["edge_count"],
        avg_quality=row["avg_quality"],
        key_concepts=key_concepts,
        source_type_counts=source_type_counts,
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
