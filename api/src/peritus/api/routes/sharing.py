"""Share links: "anyone with the link can read and ask".

Three audiences, and each endpoint names which one it serves.

- **The owner** turns a link on (``PUT``), copies it, resets it (``POST
  …/reset``) or turns it off (``DELETE``). All four resolve the expert through
  the ownership gate, so a viewer — even one holding a grant — gets a 404.
- **Anyone holding the link**, signed in or not, can read the share card and its
  picture. That is what makes a pasted link unfurl into a preview, and what lets
  the share page say what this expert is before asking anyone to sign in.
- **A signed-in holder** accepts the link, which records a grant. From then on
  the expert resolves by slug for them everywhere the read clause applies —
  Overview, Sources, graph, chat — until the owner resets or disables the link.

Chat stays behind a session: it costs money per message and is rate-limited per
user, so an anonymous visitor is sent to sign in first.

The anonymous endpoints are not rate-limited. The token is 192 random bits, so
there is nothing to enumerate, and the only caller in practice is the web
server — a per-IP limit here would throttle every visitor behind one address.
"""

import re

from fastapi import APIRouter, HTTPException, Request, Response

from peritus.api.deps import (
    CurrentUser,
    ExpertRepo,
    OwnedExpert,
    Pictures,
    ReadableExpert,
    Shares,
)
from peritus.api.routes.experts import _picture_out
from peritus.api.schemas.experts import ExpertAvatar
from peritus.api.schemas.sharing import ShareAcceptOut, SharedExpertOut, ShareStateOut
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert, ExpertAccess, ShareLink
from peritus.experts.share_repository import ShareRepository

logger = get_logger(__name__)

router = APIRouter(tags=["sharing"])

# `secrets.token_urlsafe(24)` is exactly 32 characters of this alphabet. Anything
# else cannot be a token, so it is a 404 before it reaches the database.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")

# A share response must never outlive the link: a revoked link has to stop
# rendering on the next request, not when some cache decides. And a share page
# is not something a search engine should ever list.
_ANONYMOUS_HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}


async def _state(shares: ShareRepository, expert: Expert, link: ShareLink | None) -> ShareStateOut:
    return ShareStateOut(
        enabled=link is not None,
        token=link.token if link else None,
        created_at=link.created_at if link else None,
        viewer_count=await shares.viewer_count(link.id) if link else 0,
        uploaded_source_count=await shares.uploaded_source_count(expert.id),
    )


async def _shared_expert(token: str, repo: ExpertRepo) -> Expert:
    if not _TOKEN_RE.match(token):
        raise HTTPException(status_code=404, detail="This link is not active")
    expert = await repo.get_by_share_token(token)
    if not expert:
        raise HTTPException(status_code=404, detail="This link is not active")
    return expert


# ── the owner ───────────────────────────────────────────────────────────────


@router.get("/experts/{slug}/share", response_model=ShareStateOut)
async def get_share(expert: OwnedExpert, shares: Shares):
    return await _state(shares, expert, await shares.get_active(expert.id))


@router.put("/experts/{slug}/share", response_model=ShareStateOut)
async def enable_share(expert: OwnedExpert, user: CurrentUser, shares: Shares):
    """Turn the link on. Idempotent: a live link is returned, never replaced."""
    link = await shares.enable(expert.id, user.id)
    logger.info("Share link on for expert %d", expert.id)
    return await _state(shares, expert, link)


@router.post("/experts/{slug}/share/reset", response_model=ShareStateOut)
async def reset_share(expert: OwnedExpert, user: CurrentUser, shares: Shares):
    """Replace the link. Everyone who opened the old one loses access."""
    link = await shares.reset(expert.id, user.id)
    logger.info("Share link reset for expert %d", expert.id)
    return await _state(shares, expert, link)


@router.delete("/experts/{slug}/share", status_code=204)
async def disable_share(expert: OwnedExpert, shares: Shares):
    """Turn the link off. Everyone who opened it loses access; their own chats
    are kept but can no longer be continued."""
    await shares.disable(expert.id)
    logger.info("Share link off for expert %d", expert.id)


# ── a viewer ────────────────────────────────────────────────────────────────


@router.delete("/experts/{slug}/access", status_code=204)
async def leave_shared_expert(expert: ReadableExpert, user: CurrentUser, shares: Shares):
    """Remove a shared expert from the caller's workspace.

    The owner cannot "leave" their own expert — that would be a delete, which
    is a different, destructive action with its own route.
    """
    if expert.is_owned_by(user.id, include_unowned=user.is_admin):
        raise HTTPException(status_code=409, detail="You own this expert")
    await shares.remove_access(expert.id, user.id)


# ── anyone holding the link ─────────────────────────────────────────────────


@router.get("/share/{token}", response_model=SharedExpertOut)
async def get_shared_expert(token: str, response: Response, repo: ExpertRepo):
    """The share card. Readable without a session, so a link can unfurl."""
    expert = await _shared_expert(token, repo)
    response.headers.update(_ANONYMOUS_HEADERS)
    return SharedExpertOut(
        topic=expert.topic,
        tier=expert.tier.value,
        readiness=expert.readiness,
        graph_expanded=expert.graph_expanded,
        build_active=expert.build_active,
        persona_name=expert.persona_name,
        persona_bio=expert.persona_bio,
        key_concepts=expert.key_concepts,
        source_count=expert.source_count,
        chunk_count=expert.chunk_count,
        node_count=expert.node_count,
        avg_quality=expert.avg_quality,
        source_type_counts=expert.source_type_counts,
        avatar=ExpertAvatar(**expert.avatar) if expert.avatar else None,
        picture=_picture_out(expert.picture),
        created_at=expert.created_at,
    )


@router.get("/share/{token}/picture")
async def get_shared_picture(token: str, request: Request, repo: ExpertRepo, pictures: Pictures):
    """The picture's bytes for the share page and its link preview.

    Revalidated on every use (``no-cache`` with an ETag) rather than cached
    immutably like the signed-in picture: a 304 costs nothing, and a link that
    has been turned off must stop serving its image too.
    """
    expert = await _shared_expert(token, repo)
    blob = await pictures.get_blob(expert.id)
    if blob is None:
        raise HTTPException(status_code=404, detail="This expert has no picture")
    image, content_type, sha256 = blob
    etag = f'"{sha256}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "public, no-cache",
        "X-Robots-Tag": "noindex, nofollow",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=image, media_type=content_type, headers=headers)


@router.post("/share/{token}/accept", response_model=ShareAcceptOut)
async def accept_share(token: str, user: CurrentUser, repo: ExpertRepo, shares: Shares):
    """Open the link as a signed-in user: record a grant, return the slug.

    Idempotent. The owner opening their own link gets no grant — they already
    have more than one would give them.
    """
    expert = await _shared_expert(token, repo)
    if expert.is_owned_by(user.id, include_unowned=user.is_admin):
        return ShareAcceptOut(slug=expert.name, access=ExpertAccess.OWNER)
    link = await shares.resolve(token)
    if link is None:  # revoked between the two reads
        raise HTTPException(status_code=404, detail="This link is not active")
    await shares.grant(link.id, user.id)
    logger.info("Share link accepted for expert %d", expert.id)
    return ShareAcceptOut(slug=expert.name, access=ExpertAccess.VIEWER)
