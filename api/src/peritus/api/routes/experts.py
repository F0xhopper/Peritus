"""Expert, catalog and billing endpoints.

**Router shape.** This router carries no path prefix and every route spells out
its full path. That is deliberate: the same router serves ``/experts/*`` (the
caller's own workspace), ``/catalog/*`` (the public shelf) and ``/billing/*``
(credit state), and a ``/experts`` prefix would have forced the latter two into
nonsense paths like ``/experts/billing/me``. Registration order matters — literal
segments are declared before their parameterised siblings.

**Two authorisation predicates, and the difference matters.**

- *Read/chat*: ``ExpertRepository.get_for_user`` — owned, admin-visible legacy,
  public, or shared with the caller through a live link. This is what makes a
  catalog or shared expert chattable.
- *Mutate*: ``ExpertRepository.get_owned_for_user`` — owned only. Rebuild,
  cancel, delete and curate all use this, so publishing or sharing an expert
  never makes it writable by anyone but its owner.

Rows outside the caller's scope 404 rather than 403, so slugs stay unguessable.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sse_starlette.sse import EventSourceResponse

from peritus.api.deps import (
    CurrentUser,
    Entitlements,
    ExpertRepo,
    Experts,
    Jobs,
    OwnedExpert,
    Pictures,
    ReadableExpert,
)
from peritus.api.presenters import to_summary, with_catalog
from peritus.api.ratelimit import SlidingWindowLimiter
from peritus.api.schemas.experts import (
    BuildRequest,
    CatalogUpdateRequest,
    ExpertSummary,
    ExpertWithCatalog,
    SetAvatarRequest,
)
from peritus.billing.domain import (
    EntitlementError,
)
from peritus.core.config import settings
from peritus.core.exceptions import ConflictError
from peritus.core.logging import get_logger
from peritus.experts.avatar import InvalidAvatar
from peritus.experts.avatar import normalise as normalise_avatar
from peritus.experts.build.constants import FETCHER_NAMES
from peritus.experts.domain import (
    ExpertStatus,
    ExpertVisibility,
)
from peritus.experts.service import InvalidBuildRequest
from peritus.jobs.domain import TERMINAL_EVENT_TYPES, BuildJob, JobType
from peritus.jobs.repository import JobRepository

logger = get_logger(__name__)

router = APIRouter(tags=["experts"])


def _slugify(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:80]


def _entitlement_http_error(exc: EntitlementError) -> HTTPException:
    """Map a denial onto a structured, renderable HTTP error.

    The body is the payload the client should render, not prose: a code to
    switch on, the numbers to show, and a ``remedy`` hint describing the one
    action available. There is no checkout yet, so the remedy is "ask" — but
    the shape does not change when there is one.
    """
    return HTTPException(status_code=exc.status_code, detail=exc.to_payload()["error"])


# ── the caller's own experts ────────────────────────────────────────────────


@router.get("/experts", response_model=list[ExpertSummary])
async def list_experts(user: CurrentUser, repo: ExpertRepo) -> list[ExpertSummary]:
    """The caller's workspace — their own experts only.

    Deliberately does not fold in the public catalog: "my experts" must not grow
    every time the founder publishes something. The catalog is ``GET /catalog``.
    """
    experts = await repo.list_for_user(user.id, include_unowned=user.is_admin)
    return [to_summary(e, user) for e in experts]


@router.post("/experts/build")
async def build_expert(
    req: BuildRequest,
    request: Request,
    user: CurrentUser,
    experts: Experts,
    jobs: Jobs,
) -> EventSourceResponse:
    """Enqueue a durable build job and stream its progress.

    The build runs in a worker (separate process or in-process), not in this
    request, so it survives client disconnects and server restarts. This
    response tails the job's persisted event log; disconnecting no longer
    cancels the build.

    The choreography — slug resolution, entitlement check, create-or-requeue,
    enqueue, hold, cancel-on-refusal — lives in
    ``ExpertService.request_build``. What is left here is the mapping from its
    three failure modes onto status codes.
    """
    try:
        result = await experts.request_build(
            topic=req.topic,
            owner_id=user.id,
            owner_email=user.email,
            is_admin=user.is_admin,
            tier=req.tier,
            sources=req.sources,
            known_sources=FETCHER_NAMES,
        )
    except InvalidBuildRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except EntitlementError as exc:
        logger.info("Build denied for %s: %s", user.id, exc.code)
        raise _entitlement_http_error(exc) from None

    return EventSourceResponse(_tail_events(jobs, result.job.id, after=0, request=request))


@router.get("/experts/{slug}", response_model=ExpertWithCatalog)
async def get_expert(expert: ReadableExpert, user: CurrentUser) -> ExpertWithCatalog:
    """Expert detail. Readable if the caller owns it, it is public, or it is
    shared with them through a live link. ``access`` says which."""
    return with_catalog(expert, user)


@router.patch("/experts/{slug}/catalog", response_model=ExpertWithCatalog)
async def update_expert_catalog(
    expert: OwnedExpert, req: CatalogUpdateRequest, user: CurrentUser, repo: ExpertRepo
) -> ExpertWithCatalog:
    """Curate an expert: publish/unpublish, blurb, category, tags, featured, rank.

    Owner-scoped: a public expert is readable by everyone and curatable only by
    the person who built it.

    **Publishing and shelf order are admin-only.** The catalog is curated, and
    an owner who could set ``visibility``, ``is_featured`` or ``catalog_rank``
    could put anything at the top of the public shelf. Owners share with a link
    instead (``PUT /experts/{slug}/share``). Taking one's own expert *off* the
    shelf stays open to its owner — nobody should need permission to unpublish.
    """
    curating_the_shelf = (
        (req.visibility is not None and req.visibility is not ExpertVisibility.PRIVATE)
        or req.is_featured is not None
        or req.catalog_rank is not None
        or "catalog_rank" in (req.clear or [])
    )
    if curating_the_shelf and not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Only an admin can publish to the catalog or change its order. "
            "Share this expert with a link instead.",
        )

    updated = await repo.update_catalog(
        expert.id,
        visibility=req.visibility,
        is_featured=req.is_featured,
        catalog_rank=req.catalog_rank,
        blurb=req.blurb,
        category=req.category,
        tags=req.tags,
        published_by=user.id,
        clear=frozenset(req.clear or []),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Expert not found")
    logger.info(
        "Curated expert %r: visibility=%s featured=%s rank=%s",
        expert.name,
        updated.catalog.visibility.value,
        updated.catalog.is_featured,
        updated.catalog.catalog_rank,
    )
    return with_catalog(updated, user)


@router.put("/experts/{slug}/avatar", response_model=ExpertWithCatalog)
async def set_expert_avatar(
    expert: OwnedExpert, req: SetAvatarRequest, user: CurrentUser, repo: ExpertRepo
) -> ExpertWithCatalog:
    """Pin this expert's picture avatar, or reset it to the generated default.

    Owner-scoped, like every other mutation: a published expert is readable by
    everyone and re-skinnable only by the person who built it.

    PUT rather than PATCH because the body replaces the whole recipe — there is
    no merge, and `{"avatar": null}` is the reset.
    """
    try:
        avatar = normalise_avatar(req.avatar.model_dump() if req.avatar else None)
    except InvalidAvatar as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    updated = await repo.update_avatar(expert.id, avatar)
    if not updated:
        raise HTTPException(status_code=404, detail="Expert not found")
    logger.info(
        "Set avatar for expert %r: style=%s", expert.name, avatar["style"] if avatar else "derived"
    )
    return with_catalog(updated, user)


# ── the expert's picture ────────────────────────────────────────────────────
#
# Three endpoints, and the read rule on all of them is the expert's own: a
# private expert's picture is a 404 to anyone but its owner and the people it is
# shared with, a public one's is readable by any signed-in user. Refresh and
# delete are owner-only like every other mutation. (An anonymous share page gets
# the picture through ``GET /share/{token}/picture`` instead.)

# Each refresh fans out to five or six Wikimedia requests, so it is throttled
# per user. Deliberately generous — the picker's "Find another" is a button a
# person presses a few times in a row while deciding — and deliberately present,
# because nothing else bounds how often it can be pressed.
_picture_refresh_limiter = SlidingWindowLimiter(limit=6, window=60.0)


@router.get("/experts/{slug}/picture")
async def get_expert_picture(
    expert: ReadableExpert, request: Request, pictures: Pictures
) -> Response:
    """The picture's bytes.

    Cached hard and forever under a versioned URL: the ``?v=`` the client
    appends is this picture's content hash, so a *different* picture is a
    different URL and an immutable cache can never serve a stale one. The query
    is ignored here — it exists only to move the URL.

    ``private`` rather than ``public`` because a shared proxy must not hold an
    image whose visibility depends on who asked for it.
    """
    blob = await pictures.get_blob(expert.id)
    if blob is None:
        raise HTTPException(status_code=404, detail="This expert has no picture")
    image, content_type, sha256 = blob

    etag = f'"{sha256}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=31536000, immutable",
    }
    # A 304 must carry the validators and nothing else — notably no body and no
    # Content-Length, which is why this is not just `Response(status_code=304)`
    # with the image attached.
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)

    return Response(content=image, media_type=content_type, headers=headers)


@router.post("/experts/{slug}/picture/refresh", response_model=ExpertWithCatalog)
async def refresh_expert_picture(
    expert: OwnedExpert, user: CurrentUser, experts: Experts
) -> ExpertWithCatalog:
    """Search Wikimedia again and store whatever it finds. Owner only.

    Synchronous: it is five or six HTTP requests and no model call, so it
    returns in a couple of seconds and the client can render the result rather
    than poll for it. A search that finds nothing acceptable is a 422 naming the
    reason — "no free, non-mark, non-living-person image exists for this topic"
    is a real answer, not a server error.
    """
    from peritus.experts.picture import PictureSkipped

    ok, retry_after = _picture_refresh_limiter.check_with_retry_after(user.id)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail="Too many picture searches. Try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        updated = await experts.refresh_picture(expert.id)
    except PictureSkipped as skip:
        raise HTTPException(
            status_code=422, detail=_PICTURE_SKIP_MESSAGES.get(skip.reason, skip.reason)
        ) from None
    logger.info("Refreshed picture for expert %r", expert.name)
    return with_catalog(updated, user)


@router.delete("/experts/{slug}/picture", status_code=204)
async def delete_expert_picture(expert: OwnedExpert, pictures: Pictures) -> None:
    """Remove the found picture; the expert falls back to its recipe or sigil.

    Distinct from picking a sigil style in the avatar picker, which writes a
    recipe that Reset would then undo — bringing the picture straight back. This
    is how an owner says "not this, and not any".
    """
    await pictures.delete(expert.id)
    logger.info("Removed picture for expert %r", expert.name)


# What each skip reason means to the person who pressed the button.
_PICTURE_SKIP_MESSAGES: dict[str, str] = {
    "no_candidate": (
        "No freely licensed picture of this subject was found. Wikipedia's "
        "article may have no image, or the only one is a map, a logo or a "
        "photograph of someone living."
    ),
    "timeout": "Wikimedia did not answer in time. Try again shortly.",
    "provider_unavailable": "Wikimedia is unreachable right now. Try again shortly.",
    "too_large": "The pictures found were too large or were not images.",
    "disabled": "Picture search is turned off on this server.",
}


@router.delete("/experts/{slug}", status_code=204)
async def delete_expert(expert: OwnedExpert, repo: ExpertRepo, jobs: Jobs) -> None:
    # Cancel any in-flight build first so the worker aborts cooperatively instead of
    # racing the cascade delete of the expert's rows.
    await jobs.request_cancel(expert.id)
    await repo.delete(expert.id)


@router.get("/experts/{slug}/build/events")
async def build_events(
    expert: ReadableExpert,
    request: Request,
    jobs: Jobs,
    after: int = Query(0, ge=0),
) -> EventSourceResponse:
    """Reconnect to (or re-watch) a build's progress from a cursor. Multiple clients
    can tail the same build; pass the last `seq` you saw as `after` to resume.
    """
    job = await jobs.get_latest_job(expert.id)
    if not job:
        raise HTTPException(status_code=404, detail="No build job for this expert")
    return EventSourceResponse(_tail_events(jobs, job.id, after=after, request=request))


@router.post("/experts/{slug}/build/cancel", status_code=202)
async def cancel_build(
    expert: OwnedExpert, repo: ExpertRepo, jobs: Jobs, entitlements: Entitlements
) -> dict[str, Any]:
    """Cancel the active (queued or running) build for an expert.

    A running worker notices on its next heartbeat and aborts cooperatively; a
    queued job simply never starts. The expert is marked failed so the UI doesn't
    show a build that will never finish.
    """
    job = await jobs.get_active_job(expert.id, job_type=JobType.BUILD)
    if job is None:
        raise HTTPException(status_code=409, detail="No active build for this expert")
    await jobs.request_cancel(expert.id, job_type=JobType.BUILD)
    # Terminal event so any client tailing the log stops cleanly, and a status the
    # worker would otherwise only set once its heartbeat fails.
    await jobs.append_event(
        job.id,
        "cancelled",
        {
            "type": "cancelled",
            "message": "Build cancelled",
        },
    )
    await repo.update_status(expert.id, ExpertStatus.FAILED, "Build cancelled")
    # A *queued* job may never be claimed by a worker, so the refund cannot wait
    # for one to observe the cancellation. Idempotent, so a worker that does
    # observe it later is harmless.
    refunded = 0
    try:
        refunded = await entitlements.refund_job(job.id, "Build cancelled")
    except Exception as exc:  # never fail a cancel because the refund failed
        logger.warning("Could not refund job %d on cancel: %s", job.id, exc)
    logger.info("Cancelled build job %d for %r", job.id, expert.name)
    return {"job_id": job.id, "status": "cancelled", "credits_refunded": refunded}


@router.get("/experts/{slug}/build/status")
async def build_status(expert: ReadableExpert, jobs: Jobs) -> dict[str, Any]:
    """Point-in-time job status for polling clients."""
    job = await jobs.get_latest_job(expert.id)
    if not job:
        raise HTTPException(status_code=404, detail="No build job for this expert")
    return {
        "job_id": job.id,
        "expert_status": expert.status.value,
        "expert_readiness": expert.readiness,
        "job_status": job.status.value,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "last_error": job.last_error,
        "updated_at": job.updated_at,
    }


@router.get("/experts/{slug}/build/usage")
async def build_usage(
    expert: OwnedExpert, jobs: Jobs, entitlements: Entitlements
) -> dict[str, Any]:
    """What the latest build of this expert actually cost, broken down by stage.

    Owner-scoped: spend is not part of a catalog expert's public card.
    """
    job = await jobs.get_latest_job(expert.id)
    if not job:
        raise HTTPException(status_code=404, detail="No build job for this expert")
    return await entitlements.usage_for_job(job.id)


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
