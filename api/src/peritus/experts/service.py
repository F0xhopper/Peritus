import json

import asyncpg

from peritus.core.exceptions import ConflictError, NotFoundError
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert, ExpertStatus
from peritus.experts.repository import ExpertRepository

logger = get_logger(__name__)


class ExpertService:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._repo = ExpertRepository(pool)

    async def create(self, topic: str, owner_id: str | None = None) -> Expert:
        name = topic.lower().strip()
        existing = await self._repo.get_by_name(name)
        if existing:
            raise ConflictError(f"Expert already exists: {name!r}")
        return await self._repo.create(name, topic, owner_id=owner_id)

    async def get(self, name_or_id: str | int) -> Expert:
        if isinstance(name_or_id, int):
            expert = await self._repo.get_by_id(name_or_id)
        else:
            expert = await self._repo.get_by_name(name_or_id)
            if not expert:
                expert = await self._repo.fuzzy_find(name_or_id)
        if not expert:
            raise NotFoundError("Expert", str(name_or_id))
        return expert

    async def list_all(self) -> list[Expert]:
        return await self._repo.list_all()

    async def delete(self, name_or_id: str | int) -> None:
        expert = await self.get(name_or_id)
        await self._repo.delete(expert.id)

    async def mark_failed(self, expert_id: int, error: str) -> None:
        await self._repo.update_status(expert_id, ExpertStatus.FAILED, error)

    async def mark_ready(self, expert_id: int) -> None:
        await self._repo.update_status(expert_id, ExpertStatus.READY)

    async def regenerate_persona(self, name_or_id: str | int) -> Expert:
        """Re-voice an already-built expert without rebuilding its corpus.

        The persona is generated once, at the end of a build, and then persisted
        forever — so a change to the persona prompt only reaches experts built
        after it. That would be an acceptable lag if personas were cosmetic, but
        the persona is half of the answer's voice: an expert carrying a persona
        generated under the old "describe how they cite and qualify claims"
        prompt keeps hedging no matter what the current contract says. This
        replays only the persona stage, off the corpus already in the database —
        one model call instead of a full re-fetch, re-validate and re-embed.
        """
        # Imported lazily: the builder drags in every fetcher (and their optional
        # third-party dependencies), which no other caller of this service needs.
        from peritus.experts.builder import generate_persona
        from peritus.graph.repository import GraphRepository

        expert = await self.get(name_or_id)
        sources = await self._passed_source_digest(expert.id)
        if not sources:
            raise NotFoundError("Corpus for expert", expert.name)

        top_nodes = await GraphRepository(self._pool).get_top_nodes(expert.id, 20)
        persona = await generate_persona(expert.topic, sources, top_nodes)
        await self._repo.update_persona(
            expert.id,
            persona_name=persona["name"],
            persona_bio=persona["bio"],
            persona_style=persona["style"],
        )
        logger.info(
            "Regenerated persona for expert %d (%r): %s",
            expert.id, expert.name, persona["name"],
        )
        return await self.get(expert.id)

    async def _passed_source_digest(
        self, expert_id: int
    ) -> list[tuple[str, str, float | None, list[str]]]:
        """The corpus as the persona prompt wants it: best sources first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT title, content_type, quality_score, key_claims
                FROM sources
                WHERE expert_id = $1 AND passed = true
                ORDER BY quality_score DESC NULLS LAST
                LIMIT 15
                """,
                expert_id,
            )
        return [
            (
                r["title"],
                r["content_type"] or "other",
                r["quality_score"],
                _as_claims(r["key_claims"]),
            )
            for r in rows
        ]


def _as_claims(raw) -> list[str]:
    """``sources.key_claims`` is JSONB, which asyncpg hands back as a string."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return [c for c in (raw or []) if isinstance(c, str)]
