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
        sources = await self._repo.passed_source_digest(expert.id)
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
            expert.id,
            expert.name,
            persona["name"],
        )
        return await self.get(expert.id)

    async def refresh_picture(
        self,
        name_or_id: str | int,
        *,
        hints_from_corpus: bool = True,
        deadline: float | None = None,
    ) -> Expert:
        """Find this expert's picture again, from scratch, and store the result.

        The build finds a picture once and then leaves it alone — a rebuild does
        not re-find, because the topic has not changed and the owner may have
        chosen the one that is there. This is the explicit "find another": the
        backfill for experts built before pictures existed, and the picker's
        Find-another button.

        ``hints_from_corpus`` adds the titles of the expert's own validated
        Wikipedia sources to the query list. Those have already been judged
        relevant to this corpus by the validator, so on an expert whose topic
        string is vague they are a much better search than the topic is.

        ``deadline`` overrides ``PICTURE_TIMEOUT``, which is sized for a build:
        20 seconds is right when nothing may wait on the search and the fallback
        is a monogram nobody will notice. An operator running the backfill is
        waiting at a terminal on purpose and has no such constraint — and when
        Wikimedia is pacing us, a single honoured ``Retry-After`` can be most of
        a build's whole budget.

        Raises :class:`PictureSkipped` when nothing acceptable was found, so the
        caller can say *why* rather than only that nothing changed.
        """
        # Imported lazily for the same reason `regenerate_persona` imports the
        # builder lazily: no other caller of this service wants httpx clients
        # and Wikimedia plumbing loaded at import time.
        from peritus.experts.picture import find_picture
        from peritus.experts.picture_repository import ExpertPictureRepository
        from peritus.infrastructure.wikimedia import WikimediaClient

        expert = await self.get(name_or_id)
        hints = await self._wikipedia_source_titles(expert.id) if hints_from_corpus else ()

        async with WikimediaClient() as client:
            found = await find_picture(
                client, expert.topic, expert.key_concepts, hints, deadline=deadline
            )
        await ExpertPictureRepository(self._pool).upsert(expert.id, found, chosen_by="build")
        logger.info(
            "Refreshed picture for expert %d (%r): %s (%s)",
            expert.id,
            expert.name,
            found.page_title,
            found.license,
        )
        return await self.get(expert.id)

    async def remove_picture(self, name_or_id: str | int) -> Expert:
        """Drop the found picture. The expert falls back to its recipe or sigil.

        Distinct from choosing a sigil style in the picker: that writes a
        recipe, and Reset would then bring the picture straight back.
        """
        from peritus.experts.picture_repository import ExpertPictureRepository

        expert = await self.get(name_or_id)
        await ExpertPictureRepository(self._pool).delete(expert.id)
        return await self.get(expert.id)

    async def _wikipedia_source_titles(self, expert_id: int) -> tuple[str, ...]:
        """Titles of this expert's validated Wikipedia sources, best first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT title
                FROM sources
                WHERE expert_id = $1 AND passed = true AND source_type = 'wikipedia'
                ORDER BY quality_score DESC NULLS LAST
                LIMIT 3
                """,
                expert_id,
            )
        return tuple(r["title"] for r in rows if r["title"])
