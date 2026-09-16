"""The curated public shelf. No authentication anywhere in this file.

Split from `routes/experts.py` because the audience is different and so is the
projection: these three endpoints serve strangers, and every response goes
through `presenters.to_catalog_entry`, which is the narrow shape that carries no
owner and no build internals.

A private expert is never reachable here. Sharing one is a token link
(`GET /share/{token}`), never its slug.
"""

from fastapi import APIRouter, HTTPException, Query

from peritus.api.deps import ExpertRepo
from peritus.api.presenters import to_catalog_entry
from peritus.api.schemas.experts import CatalogCategory, CatalogEntry

router = APIRouter(tags=["catalog"])


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
    repo: ExpertRepo,
    category: str | None = Query(None, max_length=80),
    tag: str | None = Query(None, max_length=80),
    featured: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[CatalogEntry]:
    """The curated public shelf. Readable without a session."""
    experts = await repo.list_catalog(
        category=category, tag=tag, featured_only=featured, limit=limit, offset=offset
    )
    return [to_catalog_entry(e) for e in experts]


@router.get("/catalog/categories", response_model=list[CatalogCategory])
async def list_catalog_categories(repo: ExpertRepo) -> list[CatalogCategory]:
    return [CatalogCategory(name=n, count=c) for n, c in await repo.list_catalog_categories()]


@router.get("/catalog/{slug}", response_model=CatalogEntry)
async def get_catalog_expert(slug: str, repo: ExpertRepo) -> CatalogEntry:
    """One catalog card. Public experts only — sharing a private expert is a
    token link (``GET /share/{token}``), never its slug."""
    expert = await repo.get_public(slug)
    if not expert or not expert.is_chattable:
        raise HTTPException(status_code=404, detail="Expert not found")
    return to_catalog_entry(expert)
