import asyncpg

from peritus.core.exceptions import ConflictError, NotFoundError
from peritus.experts.domain import Expert, ExpertStatus
from peritus.experts.repository import ExpertRepository


class ExpertService:
    def __init__(self, pool: asyncpg.Pool) -> None:
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
