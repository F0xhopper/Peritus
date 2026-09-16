"""Domain objects projected onto the shapes clients receive.

Three route modules render an expert — the workspace, the public catalog and a
share link — and each needs a different subset with a different rule about what
may be shown. Keeping the projections here rather than in whichever route module
happened to define one first is what stops a field appearing on one surface and
silently missing from another.

The important one is :func:`to_catalog_entry`: it is the *narrow* projection, and
it is narrow on purpose. Nothing in it identifies the owner or exposes build
internals — a catalog card is marketing plus provenance counts, not an admin
view.
"""

from typing import Any

from peritus.api.auth import AuthUser
from peritus.api.schemas.experts import (
    CatalogEntry,
    CatalogMetaOut,
    ExpertAccess,
    ExpertPictureOut,
    ExpertSummary,
    ExpertWithCatalog,
)
from peritus.experts.domain import ExpertPicture


def picture_out(picture: ExpertPicture | None) -> ExpertPictureOut | None:
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


def access_for(e, user: AuthUser) -> ExpertAccess:
    """The caller's relationship to an expert they have already been allowed to read."""
    if e.is_owned_by(user.id, include_unowned=user.is_admin):
        return ExpertAccess.OWNER
    return ExpertAccess.VIEWER


def summary_fields(e, user: AuthUser) -> dict[str, Any]:
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
        "picture": picture_out(e.picture),
        "access": access_for(e, user),
        "created_at": e.created_at,
    }


def to_summary(e, user: AuthUser) -> ExpertSummary:
    return ExpertSummary(**summary_fields(e, user))


def catalog_meta(e) -> CatalogMetaOut:
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


def with_catalog(e, user: AuthUser) -> ExpertWithCatalog:
    return ExpertWithCatalog(
        **summary_fields(e, user),
        error=e.error,
        updated_at=e.updated_at,
        catalog=catalog_meta(e),
    )


def to_catalog_entry(e) -> CatalogEntry:
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
        picture=picture_out(e.picture),
        published_at=c.published_at,
        created_at=e.created_at,
    )
