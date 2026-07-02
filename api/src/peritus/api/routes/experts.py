import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from peritus.api.auth import AuthUser, require_user
from peritus.api.schemas.experts import BuildRequest, ExpertDetail, ExpertSummary
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.domain import ExpertStatus
from peritus.experts.repository import ExpertRepository
from peritus.infrastructure.database import get_pool
from peritus.jobs.domain import TERMINAL_EVENT_TYPES, BuildJob
from peritus.jobs.repository import JobRepository

logger = get_logger(__name__)

router = APIRouter(prefix="/experts", tags=["experts"])


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
async def list_experts(user: AuthUser = Depends(require_user)):
    pool = get_pool()
    repo = ExpertRepository(pool)
    experts = await repo.list_for_user(user.id, include_unowned=user.is_admin)
    return [_expert_to_summary(e) for e in experts]


@router.get("/{slug}", response_model=ExpertDetail)
async def get_expert(slug: str, user: AuthUser = Depends(require_user)):
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    return _expert_to_detail(expert)


@router.delete("/{slug}", status_code=204)
async def delete_expert(slug: str, user: AuthUser = Depends(require_user)):
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    # Cancel any in-flight build first so the worker aborts cooperatively instead of
    # racing the cascade delete of the expert's rows.
    await JobRepository(pool).request_cancel(expert.id)
    await repo.delete(expert.id)


@router.post("/build")
async def build_expert(
    req: BuildRequest, request: Request, user: AuthUser = Depends(require_user)
):
    """Enqueue a durable build job and stream its progress.

    The build runs in a worker (separate process or in-process), not in this request,
    so it survives client disconnects and server restarts. This response tails the
    job's persisted event log; disconnecting no longer cancels the build.
    """
    pool = get_pool()
    repo = ExpertRepository(pool)
    jobs = JobRepository(pool)
    slug = _slugify(req.topic)
    if not slug:
        raise HTTPException(
            status_code=400,
            detail="Topic must contain at least one letter or number",
        )

    expert = await repo.get_by_name(slug)
    if expert is not None and await repo.get_for_user(
        slug, user.id, include_unowned=user.is_admin
    ) is None:
        # Expert slugs are globally unique, but this one belongs to another user.
        # Hide its existence (404, not 403) rather than let them rebuild it.
        raise HTTPException(status_code=404, detail="Expert not found")
    active = await jobs.get_active_job(expert.id) if expert else None

    if active is not None:
        # A build is already queued/running — attach to it rather than starting a
        # duplicate. Don't touch the expert's status (it may be mid-build).
        job = active
        logger.info("Attaching to in-flight build job %d for %r", job.id, slug)
    else:
        if expert is None:
            expert = await repo.create(
                name=slug, topic=req.topic, tier=req.tier, owner_id=user.id
            )
        else:
            # Rebuild of a finished expert — the worker resets prior corpus state first.
            await repo.update_status(expert.id, ExpertStatus.QUEUED)
        job = await jobs.enqueue(
            expert.id,
            tier=req.tier.value if hasattr(req.tier, "value") else req.tier,
            source_filter=req.sources or None,
            max_attempts=settings.WORKER_MAX_ATTEMPTS,
        )
        logger.info("Enqueued build job %d for %r (expert=%d)", job.id, slug, expert.id)

    return EventSourceResponse(_tail_events(jobs, job.id, after=0, request=request))


@router.get("/{slug}/build/events")
async def build_events(
    slug: str,
    request: Request,
    after: int = Query(0, ge=0),
    user: AuthUser = Depends(require_user),
):
    """Reconnect to (or re-watch) a build's progress from a cursor. Multiple clients
    can tail the same build; pass the last `seq` you saw as `after` to resume.
    """
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    jobs = JobRepository(pool)
    job = await jobs.get_latest_job(expert.id)
    if not job:
        raise HTTPException(status_code=404, detail="No build job for this expert")
    return EventSourceResponse(_tail_events(jobs, job.id, after=after, request=request))


@router.post("/{slug}/build/cancel", status_code=202)
async def cancel_build(
    slug: str, user: AuthUser = Depends(require_user)
) -> dict[str, Any]:
    """Cancel the active (queued or running) build for an expert.

    A running worker notices on its next heartbeat and aborts cooperatively; a
    queued job simply never starts. The expert is marked failed so the UI doesn't
    show a build that will never finish.
    """
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    jobs = JobRepository(pool)
    job = await jobs.get_active_job(expert.id)
    if job is None:
        raise HTTPException(status_code=409, detail="No active build for this expert")
    await jobs.request_cancel(expert.id)
    # Terminal event so any client tailing the log stops cleanly, and a status the
    # worker would otherwise only set once its heartbeat fails.
    await jobs.append_event(job.id, "cancelled", {
        "type": "cancelled", "message": "Build cancelled",
    })
    await repo.update_status(expert.id, ExpertStatus.FAILED, "Build cancelled")
    logger.info("Cancelled build job %d for %r", job.id, slug)
    return {"job_id": job.id, "status": "cancelled"}


@router.get("/{slug}/build/status")
async def build_status(
    slug: str, user: AuthUser = Depends(require_user)
) -> dict[str, Any]:
    """Point-in-time job status for polling clients."""
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    job = await JobRepository(pool).get_latest_job(expert.id)
    if not job:
        raise HTTPException(status_code=404, detail="No build job for this expert")
    return {
        "job_id": job.id,
        "expert_status": expert.status.value,
        "job_status": job.status.value,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "last_error": job.last_error,
        "updated_at": job.updated_at,
    }


async def _tail_events(
    jobs: JobRepository,
    job_id: int,
    after: int,
    request: Request,
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE frames from the durable build_events log until a terminal event or
    the client disconnects. Terminating the connection does not affect the build.
    """
    last_seq = after
    while True:
        if await request.is_disconnected():
            return
        events = await jobs.read_events(job_id, last_seq)
        for ev in events:
            last_seq = ev.seq
            yield {"id": str(ev.seq), "data": json.dumps(ev.payload)}
            if ev.type in TERMINAL_EVENT_TYPES:
                return
        if events:
            continue  # drain quickly while events are flowing
        # Caught up: if the job already reached a terminal state with no further
        # events to send, stop; otherwise poll for more.
        job: BuildJob | None = await jobs.get_job(job_id)
        if job is None:
            return  # job (and expert) was deleted
        if job.status.value in ("succeeded", "failed", "cancelled"):
            return
        await asyncio.sleep(settings.JOB_EVENT_POLL_INTERVAL)
