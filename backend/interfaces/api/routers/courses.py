"""Course generation endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from application.use_cases.create_expert import get_expert
from application.use_cases.generate_course import generate_course_stream
from core.exceptions import CourseGenerationError, ExpertNotFoundError
from core.logger import get_logger
from domain.entities import Difficulty, ExpertStatus

router = APIRouter(prefix="/api/courses", tags=["courses"])
logger = get_logger(__name__)


class GenerateCourseRequest(BaseModel):
    expert_slug: str
    difficulty: Difficulty = Difficulty.INTERMEDIATE
    focus: Optional[str] = None


@router.post("/generate")
async def generate_course(body: GenerateCourseRequest):
    """
    Generate a structured Markdown course from a Peritus Expert.

    Streams the course as Markdown text via SSE.

    Args body:
        expert_slug: The expert's URL slug.
        difficulty: beginner | intermediate | advanced | custom
        focus: Optional custom focus area (used when difficulty=custom).
    """
    expert = get_expert(body.expert_slug)
    if not expert:
        raise HTTPException(status_code=404, detail=f"Expert '{body.expert_slug}' not found.")

    if expert.status != ExpertStatus.READY:
        raise HTTPException(
            status_code=409,
            detail=f"Expert '{body.expert_slug}' is not ready (status: {expert.status.value}).",
        )

    async def _stream():
        try:
            async for chunk in generate_course_stream(expert, body.difficulty, body.focus):
                yield chunk
        except (CourseGenerationError, ExpertNotFoundError) as exc:
            yield f"\n\n**Error:** {exc}\n"

    return StreamingResponse(
        _stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
