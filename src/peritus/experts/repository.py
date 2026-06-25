import asyncpg

from peritus.experts.domain import Expert, ExpertStatus


class ExpertRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(self, name: str, topic: str) -> Expert:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO experts (name, topic, status)
                VALUES ($1, $2, $3)
                RETURNING *
                """,
                name, topic, ExpertStatus.BUILDING.value,
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
            rows = await conn.fetch("SELECT * FROM experts ORDER BY created_at DESC")
        return [_row_to_expert(r) for r in rows]

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


def _row_to_expert(row: asyncpg.Record) -> Expert:
    return Expert(
        id=row["id"],
        name=row["name"],
        topic=row["topic"],
        status=ExpertStatus(row["status"]),
        persona_name=row["persona_name"],
        persona_bio=row["persona_bio"],
        persona_style=row["persona_style"],
        source_count=row["source_count"],
        chunk_count=row["chunk_count"],
        node_count=row["node_count"],
        edge_count=row["edge_count"],
        avg_quality=row["avg_quality"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
