"""The dependencies every route resolves its expert and its collaborators from.

**Two gates, and the difference is the security boundary.** :data:`ReadableExpert`
answers "may this user read or chat with this expert" — owned, admin-visible
legacy, public, or shared through a live link. :data:`OwnedExpert` answers "may
this user act on it" — owned only. Rebuild, curate, upload, share and delete are
all the second one. Reaching for the wrong annotation is the one mistake that
matters here, which is why they are named for what they grant rather than for
the query they run.

Both answer **404, not 403**, for anything out of scope: an expert's existence
is not disclosed to someone who cannot reach it.

This file exists because that resolve-or-404 helper had been written four times
(`audit._readable_expert`, `conversations._get_readable_expert`,
`sources._owned_expert`, `sharing._owned_expert`) and inlined thirteen more
times in `experts.py`. Four copies of an authorisation check is four places for
one of them to drift.

The service and repository providers are here for the same reason and one more:
a handler that calls ``AuditService(get_pool())`` knows about the pool, and a
test that wants to substitute the service has to monkeypatch a module attribute.
Declared as dependencies, they are replaced with ``app.dependency_overrides``,
which is scoped to the test rather than to the process.
"""

from typing import Annotated

import asyncpg
from fastapi import Depends, HTTPException

from peritus.api.auth import AuthUser, require_user
from peritus.audit.service import AuditService
from peritus.billing.repository import BillingRepository
from peritus.billing.service import EntitlementService
from peritus.chat.conversation_repository import ConversationRepository
from peritus.experts.domain import Expert
from peritus.experts.picture_repository import ExpertPictureRepository
from peritus.experts.repository import ExpertRepository
from peritus.experts.service import ExpertService
from peritus.experts.share_repository import ShareRepository
from peritus.infrastructure.database import get_pool
from peritus.jobs.repository import JobRepository
from peritus.uploads.repository import UploadRepository

# ── the pool ─────────────────────────────────────────────────────────────────


def db_pool() -> asyncpg.Pool:
    """The connection pool, as a dependency rather than a module-level call.

    Everything below takes it this way, so overriding this one provider in a
    test redirects every repository and service at once.
    """
    return get_pool()


Pool = Annotated[asyncpg.Pool, Depends(db_pool)]


# ── repositories and services ────────────────────────────────────────────────


def expert_repo(pool: Pool) -> ExpertRepository:
    return ExpertRepository(pool)


def expert_service(pool: Pool) -> ExpertService:
    return ExpertService(pool)


def job_repo(pool: Pool) -> JobRepository:
    return JobRepository(pool)


def audit_service(pool: Pool) -> AuditService:
    return AuditService(pool)


def conversation_repo(pool: Pool) -> ConversationRepository:
    return ConversationRepository(pool)


def upload_repo(pool: Pool) -> UploadRepository:
    return UploadRepository(pool)


def share_repo(pool: Pool) -> ShareRepository:
    return ShareRepository(pool)


def picture_repo(pool: Pool) -> ExpertPictureRepository:
    return ExpertPictureRepository(pool)


def billing_repo(pool: Pool) -> BillingRepository:
    return BillingRepository(pool)


def entitlements(pool: Pool) -> EntitlementService:
    return EntitlementService(pool)


ExpertRepo = Annotated[ExpertRepository, Depends(expert_repo)]
Experts = Annotated[ExpertService, Depends(expert_service)]
Jobs = Annotated[JobRepository, Depends(job_repo)]
Audits = Annotated[AuditService, Depends(audit_service)]
Conversations = Annotated[ConversationRepository, Depends(conversation_repo)]
Uploads = Annotated[UploadRepository, Depends(upload_repo)]
Shares = Annotated[ShareRepository, Depends(share_repo)]
Pictures = Annotated[ExpertPictureRepository, Depends(picture_repo)]
Billing = Annotated[BillingRepository, Depends(billing_repo)]
Entitlements = Annotated[EntitlementService, Depends(entitlements)]

CurrentUser = Annotated[AuthUser, Depends(require_user)]


# ── the two expert gates ─────────────────────────────────────────────────────

_NOT_FOUND = "Expert not found"


async def readable_expert(slug: str, user: CurrentUser, repo: ExpertRepo) -> Expert:
    """An expert the caller may READ, or 404.

    Read visibility is owned, admin-visible legacy, public, or shared through a
    live link — which is what makes a catalog or shared expert chattable without
    the chat routes knowing anything about sharing.

    **Never use this to authorise a mutation.** Use :func:`owned_expert`.
    """
    expert = await repo.get_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return expert


async def owned_expert(slug: str, user: CurrentUser, repo: ExpertRepo) -> Expert:
    """An expert the caller may MUTATE, or 404.

    Ownership only: a share grant lets someone read and chat, never rebuild,
    curate, upload to, re-share or delete.
    """
    expert = await repo.get_owned_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return expert


ReadableExpert = Annotated[Expert, Depends(readable_expert)]
OwnedExpert = Annotated[Expert, Depends(owned_expert)]
