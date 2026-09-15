from datetime import datetime

from pydantic import BaseModel, Field

from peritus.experts.domain import BLURB_MAX_CHARS, ExpertAccess, ExpertTier, ExpertVisibility


class ExpertAvatar(BaseModel):
    """A rendering recipe, not an image. See peritus.experts.avatar for why.

    ``seed`` is optional; the client derives it when absent. ``hue`` is kept for
    older clients and is always null — there are no per-expert colours, and a
    value sent here is discarded rather than refused.
    """

    style: str
    seed: str | None = None
    hue: int | None = None


class SetAvatarRequest(BaseModel):
    """Pin an avatar, or reset to the generated default.

    An explicit ``{"avatar": null}`` is the reset. It has to be a wrapper object
    rather than a bare nullable body so that "reset" and "you forgot the body"
    stay distinguishable.
    """

    avatar: ExpertAvatar | None = None


class ExpertPictureOut(BaseModel):
    """A found, licensed picture of the expert's *subject* (migration 027).

    Not the avatar and not a headshot: the avatar is the owner's rendering
    recipe and stays authoritative, while this is what a fresh expert arrives
    with. The bytes are at ``GET /experts/{slug}/picture``; ``version`` is the
    short content hash that goes in its ``?v=`` so an immutable cache is safe.

    The provenance fields are not decoration. CC BY and CC BY-SA require
    attribution wherever the picture is shown as an identity, so a client that
    renders this has to render the credit too — ``attribution_required`` says
    when, and ``file_page_url`` is where the licence is actually stated.
    """

    version: str
    width: int
    height: int
    provider: str
    title: str | None = None
    artist: str | None = None
    license: str
    license_url: str | None = None
    page_url: str | None = None
    file_page_url: str
    attribution_required: bool = True


class ExpertSummary(BaseModel):
    id: int
    name: str
    topic: str
    status: str
    tier: str = ExpertTier.STANDARD.value
    # Retrieval readiness: pending | chat_ready | graph_ready. An expert is
    # answerable from chat_ready onward — a stage before `status` becomes
    # 'ready' — so clients should gate the chat affordance on this, not status.
    readiness: str = "pending"
    graph_expanded: bool = False
    persona_name: str | None = None
    persona_bio: str | None = None
    persona_style: str | None = None
    avg_quality: float | None = None
    key_concepts: list[str] = []
    source_count: int = 0
    chunk_count: int = 0
    node_count: int = 0
    edge_count: int = 0
    source_type_counts: dict[str, int] = {}
    # Whether a build job is actually queued or running. `status` alone can read
    # 'queued' for an expert whose job no longer exists; clients show a build as
    # live only when this is true. None from a read that did not compute it.
    build_active: bool | None = None
    # The owner's chosen picture avatar, or None for "derive it from the persona
    # name" — see peritus.experts.avatar. Clients must handle None, because it
    # is what every expert looks like until someone changes it.
    avatar: ExpertAvatar | None = None
    # The found picture, or None when this expert has none. Present-and-null
    # rather than absent, like `avatar`, so a client never has to distinguish
    # "no picture" from "an older server that does not send the field".
    picture: ExpertPictureOut | None = None
    # The caller's relationship to this expert: "owner", or "viewer" for an
    # expert they can read through a share link or the public catalog. A
    # rendering hint for hiding controls; every mutation re-checks ownership.
    access: ExpertAccess = ExpertAccess.OWNER
    created_at: datetime


class ExpertDetail(ExpertSummary):
    error: str | None = None
    updated_at: datetime


class CatalogMetaOut(BaseModel):
    """Curation fields, echoed on owner-facing responses."""

    visibility: str = ExpertVisibility.PRIVATE.value
    is_featured: bool = False
    catalog_rank: int | None = None
    blurb: str | None = None
    category: str | None = None
    tags: list[str] = []
    published_at: datetime | None = None


class ExpertWithCatalog(ExpertDetail):
    catalog: CatalogMetaOut = CatalogMetaOut()


class CatalogEntry(BaseModel):
    """One card on the public catalog shelf.

    Deliberately narrower than ``ExpertDetail``: no id, no owner, no error, no
    build internals. This is the anonymous-readable projection.
    """

    name: str
    topic: str
    tier: str
    readiness: str = "pending"
    graph_expanded: bool = False
    persona_name: str | None = None
    persona_bio: str | None = None
    blurb: str | None = None
    category: str | None = None
    tags: list[str] = []
    is_featured: bool = False
    key_concepts: list[str] = []
    source_count: int = 0
    chunk_count: int = 0
    node_count: int = 0
    avg_quality: float | None = None
    source_type_counts: dict[str, int] = {}
    picture: ExpertPictureOut | None = None
    published_at: datetime | None = None
    created_at: datetime


class CatalogCategory(BaseModel):
    name: str
    count: int


class BuildRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    # None = pick the deepest tier the caller's plan allows and balance affords
    # (EntitlementService.resolve_tier), so `{"topic": ...}` alone always names
    # a buildable tier. An explicit tier is honoured and judged as requested.
    tier: ExpertTier | None = None
    # Optional fetcher allowlist (e.g. ["wikipedia", "arxiv"]); None = all fetchers.
    # Validated against the builder's fetcher names — an unknown name is a 400,
    # not a silently empty build.
    sources: list[str] | None = None


class CatalogUpdateRequest(BaseModel):
    """Curation patch. Every field is optional; omitted fields are left alone.

    ``clear`` names fields to null out, because omission already means "leave
    alone" and there would otherwise be no way to remove a blurb or un-rank an
    expert.
    """

    visibility: ExpertVisibility | None = None
    is_featured: bool | None = None
    catalog_rank: int | None = Field(default=None, ge=0, le=100_000)
    blurb: str | None = Field(default=None, max_length=BLURB_MAX_CHARS)
    category: str | None = Field(default=None, max_length=80)
    tags: list[str] | None = None
    clear: list[str] = []


# ── billing ─────────────────────────────────────────────────────────────────


class PlanOut(BaseModel):
    name: str
    display_name: str
    included_credits: int
    allowed_tiers: list[str]
    description: str = ""


class TierPriceOut(BaseModel):
    """One rung of the price ladder, as the client should render it."""

    tier: str
    credit_cost: int
    spend_cap_usd: float
    included_in_plan: bool


class CreditStateOut(BaseModel):
    plan: PlanOut
    balance: int
    granted: int
    consumed: int
    held: int
    credits_enforced: bool
    tiers: list[TierPriceOut] = []


class LedgerEntryOut(BaseModel):
    id: int
    entry_type: str
    delta: int
    job_id: int | None = None
    tier: str | None = None
    reason: str | None = None
    source: str
    cost_usd: float | None = None
    created_at: datetime


class GrantCreditsRequest(BaseModel):
    """Manual/admin credit issuance. No payment provider is involved."""

    owner: str = Field(min_length=1, description="Owner uuid or account email")
    amount: int = Field(ge=-100_000, le=100_000, description="Credits; negative to claw back")
    reason: str | None = Field(default=None, max_length=500)
    plan: str | None = Field(default=None, description="Optionally move the account to a plan")
