import asyncio
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from peritus.api.auth import require_api_key
from peritus.api.schemas.experts import BuildRequest, ExpertDetail, ExpertSummary
from peritus.experts.builder import BuildResult, ExpertBuilder
from peritus.experts.domain import ExpertStatus
from peritus.experts.repository import ExpertRepository
from peritus.infrastructure.database import get_pool

router = APIRouter(prefix="/experts", tags=["experts"], dependencies=[Depends(require_api_key)])


def _slugify(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:80]


def _expert_to_summary(e) -> ExpertSummary:
    return ExpertSummary(
        id=e.id,
        name=e.name,
        topic=e.topic,
        status=e.status.value if hasattr(e.status, "value") else e.status,
        tier=e.tier.value if hasattr(e.tier, "value") else e.tier,
        persona_name=e.persona_name,
        persona_bio=e.persona_bio,
        persona_style=e.persona_style,
        avg_quality=e.avg_quality,
        key_concepts=e.key_concepts,
        source_count=e.source_count,
        chunk_count=e.chunk_count,
        node_count=e.node_count,
        edge_count=e.edge_count,
        source_type_counts=e.source_type_counts,
        created_at=e.created_at,
    )


def _expert_to_detail(e) -> ExpertDetail:
    return ExpertDetail(
        id=e.id,
        name=e.name,
        topic=e.topic,
        status=e.status.value if hasattr(e.status, "value") else e.status,
        tier=e.tier.value if hasattr(e.tier, "value") else e.tier,
        persona_name=e.persona_name,
        persona_bio=e.persona_bio,
        persona_style=e.persona_style,
        avg_quality=e.avg_quality,
        key_concepts=e.key_concepts,
        source_count=e.source_count,
        chunk_count=e.chunk_count,
        node_count=e.node_count,
        edge_count=e.edge_count,
        source_type_counts=e.source_type_counts,
        error=e.error,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


@router.get("", response_model=list[ExpertSummary])
async def list_experts():
    pool = get_pool()
    repo = ExpertRepository(pool)
    experts = await repo.list_all()
    return [_expert_to_summary(e) for e in experts]


@router.get("/{slug}", response_model=ExpertDetail)
async def get_expert(slug: str):
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_by_name(slug)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    return _expert_to_detail(expert)


@router.delete("/{slug}", status_code=204)
async def delete_expert(slug: str):
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_by_name(slug)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    await repo.delete(expert.id)


@router.post("/build")
async def build_expert(req: BuildRequest):
    pool = get_pool()
    repo = ExpertRepository(pool)
    slug = _slugify(req.topic)
    expert = await repo.create(name=slug, topic=req.topic, tier=req.tier)

    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def on_event(event: dict) -> None:
        await queue.put(event)

    async def run_build() -> None:
        try:
            builder = ExpertBuilder(pool)
            result: BuildResult = await builder.build(expert, on_event=on_event)
            await repo.update_status(expert.id, ExpertStatus.READY)
            await queue.put({
                "type": "done",
                "expert_id": result.expert_id,
                "source_count": result.source_count,
                "chunk_count": result.chunk_count,
                "node_count": result.node_count,
                "edge_count": result.edge_count,
            })
        except Exception as exc:
            await repo.update_status(expert.id, ExpertStatus.FAILED, str(exc))
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)  # sentinel

    asyncio.create_task(run_build())

    async def event_generator():
        while True:
            event = await queue.get()
            if event is None:
                break
            yield {"data": json.dumps(event)}

    return EventSourceResponse(event_generator())
