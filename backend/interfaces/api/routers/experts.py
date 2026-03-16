"""Expert management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from application.use_cases.create_expert import (
    create_expert_stream,
    get_expert,
    list_experts,
)
from core.exceptions import IndexBuildError
from core.logger import get_logger
from domain.entities import Expert

router = APIRouter(prefix="/api/experts", tags=["experts"])
logger = get_logger(__name__)


class CreateExpertRequest(BaseModel):
    topic: str


class ExpertSummary(BaseModel):
    slug: str
    topic: str
    persona_name: str
    status: str
    source_count: int
    node_count: int
    relation_count: int
    description: str
    created_at: str


def _to_summary(expert: Expert) -> ExpertSummary:
    return ExpertSummary(
        slug=expert.slug,
        topic=expert.topic,
        persona_name=expert.persona_name,
        status=expert.status.value,
        source_count=expert.source_count,
        node_count=expert.node_count,
        relation_count=expert.relation_count,
        description=expert.description,
        created_at=expert.created_at.isoformat(),
    )


@router.post("/create")
async def create_expert(body: CreateExpertRequest):
    """
    Build a Peritus Expert for a given topic.

    Streams plain-text progress lines as SSE events.
    Final line is: `data: DONE slug={slug}\\n\\n`
    """
    if not body.topic.strip():
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")

    return StreamingResponse(
        create_expert_stream(body.topic.strip()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("", response_model=list[ExpertSummary])
async def get_all_experts():
    """List all registered experts."""
    return [_to_summary(e) for e in list_experts()]


@router.get("/{slug}", response_model=ExpertSummary)
async def get_expert_by_slug(slug: str):
    """Get a single expert by slug."""
    expert = get_expert(slug)
    if not expert:
        raise HTTPException(status_code=404, detail=f"Expert '{slug}' not found.")
    return _to_summary(expert)
