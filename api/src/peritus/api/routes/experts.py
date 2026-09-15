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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sse_starlette.sse import EventSourceResponse

from peritus.api.auth import AuthUser, require_user
from peritus.api.ratelimit import SlidingWindowLimiter
from peritus.api.schemas.experts import (
    BuildRequest,
    CatalogCategory,
    CatalogEntry,
    CatalogMetaOut,
    CatalogUpdateRequest,
    CreditStateOut,
    ExpertPictureOut,
    ExpertSummary,
    ExpertWithCatalog,
    GrantCreditsRequest,
    LedgerEntryOut,
    PlanOut,
    SetAvatarRequest,
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
from peritus.experts.avatar import InvalidAvatar
from peritus.experts.avatar import normalise as normalise_avatar
from peritus.experts.builder import FETCHER_NAMES
from peritus.experts.domain import (
    ExpertAccess,
    ExpertPicture,
    ExpertStatus,
    ExpertTier,
    ExpertVisibility,
)
from peritus.experts.picture_repository import ExpertPictureRepository
from peritus.experts.repository import ExpertRepository
from peritus.experts.service import ExpertService
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


def _picture_out(picture: ExpertPicture | None) -> ExpertPictureOut | None:
    """Project a found picture down to what a client needs to render and credit it.

    The bytes, the shortlist and the byte size are all deliberately absent: the
    image is one endpoint away behind the same read rule as the expert itself,
    and everything here is safe on a public catalog card.
    """
    if picture is None:
        return None
    return ExpertPictureOut(
        version=picture.version,
        width=picture.width,
        height=picture.height,
        provider=picture.provider,
        title=picture.page_title,
        artist=picture.artist,
        license=picture.license,
        license_url=picture.license_url,
        page_url=picture.page_url,
        file_page_url=picture.file_page_url,
        attribution_required=picture.attribution_required,
    )


def _access(e, user: AuthUser) -> ExpertAccess:
    """The caller's relationship to an expert they have already been allowed to read."""
    if e.is_owned_by(user.id, include_unowned=user.is_admin):
        return ExpertAccess.OWNER
    return ExpertAccess.VIEWER


def _summary_fields(e, user: AuthUser) -> dict[str, Any]:
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
        "build_active": e.build_active,
        "avatar": e.avatar,
        "picture": _picture_out(e.picture),
        "access": _access(e, user),
        "created_at": e.created_at,
    }


def _expert_to_summary(e, user: AuthUser) -> ExpertSummary:
    return ExpertSummary(**_summary_fields(e, user))


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


def _expert_with_catalog(e, user: AuthUser) -> ExpertWithCatalog:
    return ExpertWithCatalog(
        **_summary_fields(e, user),
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
        picture=_picture_out(e.picture),
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
    """One catalog card. Public experts only — sharing a private expert is a
    token link (``GET /share/{token}``), never its slug."""
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
    return [_expert_to_summary(e, user) for e in experts]


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

    if req.sources is not None:
        unknown = [s for s in req.sources if s not in FETCHER_NAMES]
        if unknown or not req.sources:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown source type(s): {', '.join(unknown)}. "
                    if unknown
                    else "sources, when given, must name at least one source type. "
                )
                + f"Valid source types: {', '.join(FETCHER_NAMES)}",
            )

    base_slug = _slugify(req.topic)
    if not base_slug:
        raise HTTPException(
            status_code=400,
            detail="Topic must contain at least one letter or number",
        )

    # Slugs are globally unique but derived from the topic, so two users can
    # legitimately want the same one. Walk base, base-2, base-3… until we hit
    # either a slug the caller owns (their expert on this topic → rebuild) or a
    # free slug (→ create). Another user's expert is silently stepped over — its
    # existence is never revealed.
    expert = None
    slug = base_slug
    for i in range(1, 51):
        slug = base_slug if i == 1 else f"{base_slug}-{i}"
        candidate = await repo.get_by_name(slug)
        if candidate is None:
            expert = None
            break
        if candidate.is_owned_by(user.id, include_unowned=user.is_admin):
            expert = candidate
            break
    else:
        raise HTTPException(
            status_code=409,
            detail="Too many experts already exist for this topic — rename it slightly",
        )

    active = await jobs.get_active_job(expert.id, job_type=JobType.BUILD) if expert else None

    if active is not None:
        # A build is already queued/running — attach to it rather than starting a
        # duplicate. Don't touch the expert's status (it may be mid-build), and
        # don't charge again: this job already holds its credits.
        job = active
        logger.info("Attaching to in-flight build job %d for %r", job.id, slug)
    else:
        try:
            tier = (
                req.tier
                if req.tier is not None
                else await entitlements.resolve_tier(user.id, None, user.email)
            )
            # Check before creating anything, so a denial leaves no orphaned rows.
            await entitlements.authorize_build(user.id, tier, user.email)
        except EntitlementError as exc:
            logger.info("Build denied for %s: %s", user.id, exc.code)
            raise _entitlement_http_error(exc) from None

        if expert is None:
            expert = await repo.create(
                name=slug, topic=req.topic, tier=tier, owner_id=user.id
            )
        elif expert.tier != tier:
            # Rebuild at a different depth: the worker builds from the expert
            # row, so tier and config must move with the request or the new
            # build silently runs at the old depth.
            await repo.update_tier(expert.id, tier)
            await repo.update_status(expert.id, ExpertStatus.QUEUED)
        else:
            # Rebuild of a finished expert — the worker resets prior corpus state first.
            await repo.update_status(expert.id, ExpertStatus.QUEUED)
        job = await jobs.enqueue(
            expert.id,
            tier=tier.value,
            source_filter=req.sources or None,
            max_attempts=settings.WORKER_MAX_ATTEMPTS,
        )
        # First event in the durable log, so every client — including one that
        # reconnects later — learns which expert this stream belongs to without
        # re-deriving the slug client-side.
        await jobs.append_event(job.id, "created", {
            "type": "created",
            "slug": expert.name,
            "expert_id": expert.id,
            "job_id": job.id,
            "tier": tier.value,
            "topic": expert.topic,
        })
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
    """Expert detail. Readable if the caller owns it, it is public, or it is
    shared with them through a live link. ``access`` says which."""
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    return _expert_with_catalog(expert, user)


@router.patch("/experts/{slug}/catalog", response_model=ExpertWithCatalog)
async def update_expert_catalog(
    slug: str, req: CatalogUpdateRequest, user: AuthUser = Depends(require_user)
):
    """Curate an expert: publish/unpublish, blurb, category, tags, featured, rank.

    Owner-scoped: a public expert is readable by everyone and curatable only by
    the person who built it.

    **Publishing and shelf order are admin-only.** The catalog is curated, and
    an owner who could set ``visibility``, ``is_featured`` or ``catalog_rank``
    could put anything at the top of the public shelf. Owners share with a link
    instead (``PUT /experts/{slug}/share``). Taking one's own expert *off* the
    shelf stays open to its owner — nobody should need permission to unpublish.
    """
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_owned_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
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
        slug, updated.catalog.visibility.value, updated.catalog.is_featured,
        updated.catalog.catalog_rank,
    )
    return _expert_with_catalog(updated, user)


@router.put("/experts/{slug}/avatar", response_model=ExpertWithCatalog)
async def set_expert_avatar(
    slug: str, req: SetAvatarRequest, user: AuthUser = Depends(require_user)
):
    """Pin this expert's picture avatar, or reset it to the generated default.

    Owner-scoped, like every other mutation: a published expert is readable by
    everyone and re-skinnable only by the person who built it.

    PUT rather than PATCH because the body replaces the whole recipe — there is
    no merge, and `{"avatar": null}` is the reset.
    """
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_owned_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")

    try:
        avatar = normalise_avatar(req.avatar.model_dump() if req.avatar else None)
    except InvalidAvatar as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    updated = await repo.update_avatar(expert.id, avatar)
    if not updated:
        raise HTTPException(status_code=404, detail="Expert not found")
    logger.info(
        "Set avatar for expert %r: style=%s", slug, avatar["style"] if avatar else "derived"
    )
    return _expert_with_catalog(updated, user)


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
    slug: str, request: Request, user: AuthUser = Depends(require_user)
):
    """The picture's bytes.

    Cached hard and forever under a versioned URL: the ``?v=`` the client
    appends is this picture's content hash, so a *different* picture is a
    different URL and an immutable cache can never serve a stale one. The query
    is ignored here — it exists only to move the URL.

    ``private`` rather than ``public`` because a shared proxy must not hold an
    image whose visibility depends on who asked for it.
    """
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")

    blob = await ExpertPictureRepository(pool).get_blob(expert.id)
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
async def refresh_expert_picture(slug: str, user: AuthUser = Depends(require_user)):
    """Search Wikimedia again and store whatever it finds. Owner only.

    Synchronous: it is five or six HTTP requests and no model call, so it
    returns in a couple of seconds and the client can render the result rather
    than poll for it. A search that finds nothing acceptable is a 422 naming the
    reason — "no free, non-mark, non-living-person image exists for this topic"
    is a real answer, not a server error.
    """
    from peritus.experts.picture import PictureSkipped

    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_owned_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")

    ok, retry_after = _picture_refresh_limiter.check_with_retry_after(user.id)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail="Too many picture searches. Try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        updated = await ExpertService(pool).refresh_picture(expert.id)
    except PictureSkipped as skip:
        raise HTTPException(
            status_code=422, detail=_PICTURE_SKIP_MESSAGES.get(skip.reason, skip.reason)
        ) from None
    logger.info("Refreshed picture for expert %r", slug)
    return _expert_with_catalog(updated, user)


@router.delete("/experts/{slug}/picture", status_code=204)
async def delete_expert_picture(slug: str, user: AuthUser = Depends(require_user)):
    """Remove the found picture; the expert falls back to its recipe or sigil.

    Distinct from picking a sigil style in the avatar picker, which writes a
    recipe that Reset would then undo — bringing the picture straight back. This
    is how an owner says "not this, and not any".
    """
    pool = get_pool()
    repo = ExpertRepository(pool)
    expert = await repo.get_owned_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    await ExpertPictureRepository(pool).delete(expert.id)
    logger.info("Removed picture for expert %r", slug)


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
