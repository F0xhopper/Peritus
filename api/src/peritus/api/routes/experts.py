"""Expert, catalog and billing endpoints.

**Router shape.** This router carries no path prefix and every route spells out
its full path. That is deliberate: the same router serves ``/experts/*`` (the
caller's own workspace), ``/catalog/*`` (the public shelf) and ``/billing/*``
(credit state), and a ``/experts`` prefix would have forced the latter two into
nonsense paths like ``/experts/billing/me``. Registration order matters — literal
segments are declared before their parameterised siblings.

**Two authorisation predicates, and the difference matters.**

- *Read/chat*: ``ExpertRepository.get_for_user`` — owned, admin-visible legacy,
  or shared (public/unlisted). This is what makes a catalog expert chattable.
- *Mutate*: ``ExpertRepository.get_owned_for_user`` — owned only. Rebuild,
  cancel, delete and curate all use this, so publishing an expert never makes it
  writable by anyone but its owner.

Rows outside the caller's scope 404 rather than 403, so slugs stay unguessable.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from peritus.api.auth import AuthUser, require_user
from peritus.api.schemas.experts import (
    BuildRequest,
    CatalogCategory,
    CatalogEntry,
    CatalogMetaOut,
    CatalogUpdateRequest,
    CreditStateOut,
    ExpertDetail,
    ExpertSummary,
    ExpertWithCatalog,
    GrantCreditsRequest,
    LedgerEntryOut,
    PlanOut,
    TierPriceOut,
)
from peritus.billing.domain import (
    PLANS,
    EntitlementError,
    credit_cost,
    get_plan,
    spend_cap_usd,
)
from peritus.billing.service import EntitlementService
from peritus.billing.settings import settings as billing_settings
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.domain import ExpertStatus, ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.infrastructure.database import get_pool
from peritus.jobs.domain import TERMINAL_EVENT_TYPES, BuildJob, JobType
from peritus.jobs.repository import JobRepository

logger = get_logger(__name__)

router = APIRouter(tags=["experts"])


def _slugify(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:80]


def _entitlements() -> EntitlementService:
    """Resolved per request so tests can patch the class in this module."""
    return EntitlementService(get_pool())


def _entitlement_http_error(exc: EntitlementError) -> HTTPException:
    """Map a denial onto a structured, renderable HTTP error.

    The body is the payload the client should render, not prose: a code to
    switch on, the numbers to show, and a ``remedy`` hint describing the one
    action available. There is no checkout yet, so the remedy is "ask" — but
    the shape does not change when there is one.
    """
    return HTTPException(status_code=exc.status_code, detail=exc.to_payload()["error"])


def _summary_fields(e) -> dict[str, Any]:
    return {
        "id": e.id,
        "name": e.name,
        "topic": e.topic,
        "status": e.status.value if hasattr(e.status, "value") else e.status,
        "tier": e.tier.value if hasattr(e.tier, "value") else e.tier,
        "readiness": e.readiness,
        "graph_expanded": e.graph_expanded,
        "persona_name": e.persona_name,
        "persona_bio": e.persona_bio,
        "persona_style": e.persona_style,
        "avg_quality": e.avg_quality,
        "key_concepts": e.key_concepts,
        "source_count": e.source_count,
        "chunk_count": e.chunk_count,
        "node_count": e.node_count,
        "edge_count": e.edge_count,
        "source_type_counts": e.source_type_counts,
        "created_at": e.created_at,
    }


def _expert_to_summary(e) -> ExpertSummary:
    return ExpertSummary(**_summary_fields(e))


def _expert_to_detail(e) -> ExpertDetail:
    return ExpertDetail(**_summary_fields(e), error=e.error, updated_at=e.updated_at)


def _catalog_meta(e) -> CatalogMetaOut:
    c = e.catalog
    return CatalogMetaOut(
        visibility=c.visibility.value,
        is_featured=c.is_featured,
        catalog_rank=c.catalog_rank,
        blurb=c.blurb,
        category=c.category,
        tags=c.tags,
        published_at=c.published_at,
    )


def _expert_with_catalog(e) -> ExpertWithCatalog:
    return ExpertWithCatalog(
        **_summary_fields(e),
        error=e.error,
        updated_at=e.updated_at,
        catalog=_catalog_meta(e),
    )


def _to_catalog_entry(e) -> CatalogEntry:
    """Project an expert down to what a stranger may see.

    Nothing here identifies the owner or exposes build internals: a catalog card
    is marketing plus provenance counts, not an admin view.
    """
    c = e.catalog
    return CatalogEntry(
        name=e.name,
        topic=e.topic,
        tier=e.tier.value if hasattr(e.tier, "value") else e.tier,
        readiness=e.readiness,
        graph_expanded=e.graph_expanded,
        persona_name=e.persona_name,
        persona_bio=e.persona_bio,
        blurb=c.blurb,
        category=c.category,
        tags=c.tags,
        is_featured=c.is_featured,
        key_concepts=e.key_concepts,
        source_count=e.source_count,
        chunk_count=e.chunk_count,
        node_count=e.node_count,
        avg_quality=e.avg_quality,
        source_type_counts=e.source_type_counts,
        published_at=c.published_at,
        created_at=e.created_at,
    )


# ── public catalog (no authentication) ──────────────────────────────────────
#
# Anonymous read is a deliberate choice, scoped to exactly two endpoints:
# listing the catalog and reading one shared expert's card.
#
# Why anonymous: the catalog is the product's shop window. A logged-out landing
# page has to render it, and requiring a token to see what Peritus has built
# would put a login wall in front of the one thing that makes someone sign up.
# Everything on these responses was explicitly published by its owner.
#
# Why *only* these: chat costs real money per message and must be attributable
# and rate-limitable, so it stays behind ``require_user`` — free, but not
# anonymous. Everything owner-scoped obviously stays authenticated too.


@router.get("/catalog", response_model=list[CatalogEntry])
async def list_catalog(
    category: str | None = Query(None, max_length=80),
    tag: str | None = Query(None, max_length=80),
    featured: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """The curated public shelf. Readable without a session."""
    repo = ExpertRepository(get_pool())
    experts = await repo.list_catalog(
        category=category, tag=tag, featured_only=featured, limit=limit, offset=offset
    )
    return [_to_catalog_entry(e) for e in experts]


@router.get("/catalog/categories", response_model=list[CatalogCategory])
async def list_catalog_categories():
    repo = ExpertRepository(get_pool())
    return [CatalogCategory(name=n, count=c) for n, c in await repo.list_catalog_categories()]


@router.get("/catalog/{slug}", response_model=CatalogEntry)
async def get_catalog_expert(slug: str):
    """One catalog card. Resolves public *and* unlisted slugs — unlisted experts
    are shareable by link, they are only absent from the listing."""
    repo = ExpertRepository(get_pool())
    expert = await repo.get_public(slug)
    if not expert or not expert.is_chattable:
        raise HTTPException(status_code=404, detail="Expert not found")
    return _to_catalog_entry(expert)


# ── billing / credit state ──────────────────────────────────────────────────


def _plan_out(plan) -> PlanOut:
    return PlanOut(
        name=plan.name,
        display_name=plan.display_name,
        included_credits=plan.included_credits,
        allowed_tiers=[t.value for t in plan.allowed_tiers],
        description=plan.description,
    )


@router.get("/billing/me", response_model=CreditStateOut)
async def get_credit_state(user: AuthUser = Depends(require_user)):
    """The caller's plan, credit balance, and the price of each tier.

    Provisions the account on first call, which is where the free plan's signup
    grant lands. Chat is never gated by anything here.
    """
    state = await _entitlements().credit_state(user.id, user.email)
    return CreditStateOut(
        plan=_plan_out(state.plan),
        balance=state.balance,
        granted=state.granted,
        consumed=state.consumed,
        held=state.held,
        credits_enforced=billing_settings.CREDITS_ENFORCED,
        tiers=[
            TierPriceOut(
                tier=tier.value,
                credit_cost=credit_cost(tier),
                spend_cap_usd=spend_cap_usd(tier, state.plan, state.spend_cap_override_usd),
                included_in_plan=tier in state.plan.allowed_tiers,
            )
            for tier in ExpertTier
        ],
    )


@router.get("/billing/ledger", response_model=list[LedgerEntryOut])
async def get_credit_ledger(
    limit: int = Query(50, ge=1, le=200), user: AuthUser = Depends(require_user)
):
    entries = await _entitlements().ledger(user.id, limit)
    return [
        LedgerEntryOut(
            id=e.id,
            entry_type=e.entry_type.value,
            delta=e.delta,
            job_id=e.job_id,
            tier=e.tier,
            reason=e.reason,
            source=e.source,
            cost_usd=e.cost_usd,
            created_at=e.created_at,
        )
        for e in entries
    ]


@router.post("/admin/credits/grant")
async def grant_credits(
    req: GrantCreditsRequest, user: AuthUser = Depends(require_user)
) -> dict[str, Any]:
    """Issue credits by hand. Admin only.

    This is the entire billing integration today: no payment provider, just a
    founder granting credits to a customer who asked. A provider webhook would
    call ``EntitlementService.grant`` in exactly this way.
    """
    if not user.is_admin:
        raise HTTPException(status_code=404, detail="Not found")
    service = _entitlements()
    owner_id = await service.resolve_owner(req.owner)
    if not owner_id:
        raise HTTPException(status_code=404, detail=f"No account matching {req.owner!r}")
    if req.plan:
        if req.plan not in PLANS:
            raise HTTPException(status_code=400, detail=f"Unknown plan {req.plan!r}")
        await service.set_plan(owner_id, get_plan(req.plan), actor=user.email)
    balance = await service.grant(
        owner_id,
        req.amount,
        reason=req.reason or "Manual grant",
        actor=user.email or user.id,
        email=req.owner if "@" in req.owner else None,
    )
    return {"owner_id": owner_id, "balance": balance, "granted": req.amount}


# ── the caller's own experts ────────────────────────────────────────────────


@router.get("/experts", response_model=list[ExpertSummary])
async def list_experts(user: AuthUser = Depends(require_user)):
    """The caller's workspace — their own experts only.

    Deliberately does not fold in the public catalog: "my experts" must not grow
    every time the founder publishes something. The catalog is ``GET /catalog``.
    """
    pool = get_pool()
    repo = ExpertRepository(pool)
    experts = await repo.list_for_user(user.id, include_unowned=user.is_admin)
    return [_expert_to_summary(e) for e in experts]


@router.post("/experts/build")
async def build_expert(
    req: BuildRequest, request: Request, user: AuthUser = Depends(require_user)
):
    """Enqueue a durable build job and stream its progress.

    The build runs in a worker (separate process or in-process), not in this
    request, so it survives client disconnects and server restarts. This
    response tails the job's persisted event log; disconnecting no longer
    cancels the build.

    **This is the gate.** Builds are the paid action, so credits are checked and
    held here, at enqueue — never mid-build, when the money is already being
    spent. Attaching to an already-running build is free: its hold was taken
    when it was enqueued.
    """
    pool = get_pool()
    repo = ExpertRepository(pool)
    jobs = JobRepository(pool)
    entitlements = _entitlements()
    slug = _slugify(req.topic)
    if not slug:
        raise HTTPException(
            status_code=400,
            detail="Topic must contain at least one letter or number",
        )

    expert = await repo.get_by_name(slug)
    if expert is not None and await repo.get_owned_for_user(
        slug, user.id, include_unowned=user.is_admin
    ) is None:
        # Expert slugs are globally unique, but this one belongs to another user
        # (or is a catalog expert the caller merely has read access to). Hide its
        # existence (404, not 403) rather than let them rebuild it.
        raise HTTPException(status_code=404, detail="Expert not found")
    active = await jobs.get_active_job(expert.id, job_type=JobType.BUILD) if expert else None

    if active is not None:
        # A build is already queued/running — attach to it rather than starting a
        # duplicate. Don't touch the expert's status (it may be mid-build), and
        # don't charge again: this job already holds its credits.
        job = active
        logger.info("Attaching to in-flight build job %d for %r", job.id, slug)
    else:
        tier = req.tier if isinstance(req.tier, ExpertTier) else ExpertTier(req.tier)
        # Check before creating anything, so a denial leaves no orphaned rows.
        try:
            await entitlements.authorize_build(user.id, tier, user.email)
        except EntitlementError as exc:
            logger.info("Build denied for %s (%s): %s", user.id, tier.value, exc.code)
            raise _entitlement_http_error(exc) from None

        if expert is None:
            expert = await repo.create(
                name=slug, topic=req.topic, tier=req.tier, owner_id=user.id
            )
        else:
            # Rebuild of a finished expert — the worker resets prior corpus state first.
            await repo.update_status(expert.id, ExpertStatus.QUEUED)
        job = await jobs.enqueue(
            expert.id,
            tier=tier.value,
            source_filter=req.sources or None,
            max_attempts=settings.WORKER_MAX_ATTEMPTS,
        )
        # The authoritative charge. Re-checks the balance under a row lock, and
        # is idempotent per job id — so a double-submit that lands on the same
        # job never double-charges. If it fails here the job is cancelled rather
        # than left to run unpaid.
        try:
            await entitlements.hold_for_job(user.id, job.id, tier)
        except EntitlementError as exc:
            await jobs.request_cancel(expert.id, job_type=JobType.BUILD)
            await repo.update_status(expert.id, ExpertStatus.FAILED, "Not enough credits")
            raise _entitlement_http_error(exc) from None

        logger.info("Enqueued build job %d for %r (expert=%d)", job.id, slug, expert.id)

    return EventSourceResponse(_tail_events(jobs, job.id, after=0, request=request))


@router.get("/experts/{slug}", response_model=ExpertWithCatalog)
async def get_expert(slug: str, user: AuthUser = Depends(require_user)):
    """Expert detail. Readable if the caller owns it *or* it is public/unlisted."""
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    return _expert_with_catalog(expert)


@router.patch("/experts/{slug}/catalog", response_model=ExpertWithCatalog)
async def update_expert_catalog(
    slug: str, req: CatalogUpdateRequest, user: AuthUser = Depends(require_user)
):
    """Curate an expert: publish/unpublish, blurb, category, tags, featured, rank.

    Owner-scoped: a public expert is readable by everyone and curatable only by
    the person who built it.
    """
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_owned_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")

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
        slug, updated.catalog.visibility.value, updated.catalog.is_featured,
        updated.catalog.catalog_rank,
    )
    return _expert_with_catalog(updated)


@router.delete("/experts/{slug}", status_code=204)
async def delete_expert(slug: str, user: AuthUser = Depends(require_user)):
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_owned_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    # Cancel any in-flight build first so the worker aborts cooperatively instead of
    # racing the cascade delete of the expert's rows.
    await JobRepository(pool).request_cancel(expert.id)
    await repo.delete(expert.id)


@router.get("/experts/{slug}/build/events")
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


@router.post("/experts/{slug}/build/cancel", status_code=202)
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
    expert = await repo.get_owned_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    jobs = JobRepository(pool)
    job = await jobs.get_active_job(expert.id, job_type=JobType.BUILD)
    if job is None:
        raise HTTPException(status_code=409, detail="No active build for this expert")
    await jobs.request_cancel(expert.id, job_type=JobType.BUILD)
    # Terminal event so any client tailing the log stops cleanly, and a status the
    # worker would otherwise only set once its heartbeat fails.
    await jobs.append_event(job.id, "cancelled", {
        "type": "cancelled", "message": "Build cancelled",
    })
    await repo.update_status(expert.id, ExpertStatus.FAILED, "Build cancelled")
    # A *queued* job may never be claimed by a worker, so the refund cannot wait
    # for one to observe the cancellation. Idempotent, so a worker that does
    # observe it later is harmless.
    refunded = 0
    try:
        refunded = await _entitlements().refund_job(job.id, "Build cancelled")
    except Exception as exc:  # never fail a cancel because the refund failed
        logger.warning("Could not refund job %d on cancel: %s", job.id, exc)
    logger.info("Cancelled build job %d for %r", job.id, slug)
    return {"job_id": job.id, "status": "cancelled", "credits_refunded": refunded}


@router.get("/experts/{slug}/build/status")
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
        "expert_readiness": expert.readiness,
        "job_status": job.status.value,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "last_error": job.last_error,
        "updated_at": job.updated_at,
    }


@router.get("/experts/{slug}/build/usage")
async def build_usage(
    slug: str, user: AuthUser = Depends(require_user)
) -> dict[str, Any]:
    """What the latest build of this expert actually cost, broken down by stage.

    Owner-scoped: spend is not part of a catalog expert's public card.
    """
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_owned_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    job = await JobRepository(pool).get_latest_job(expert.id)
    if not job:
        raise HTTPException(status_code=404, detail="No build job for this expert")
    return await _entitlements().usage_for_job(job.id)


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
