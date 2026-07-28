from datetime import datetime

from pydantic import BaseModel, Field

from peritus.experts.domain import BLURB_MAX_CHARS, ExpertTier, ExpertVisibility


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
    published_at: datetime | None = None
    created_at: datetime


class CatalogCategory(BaseModel):
    name: str
    count: int


class BuildRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    tier: ExpertTier = ExpertTier.STANDARD
    # Optional fetcher allowlist (e.g. ["wikipedia", "arxiv"]); None = all fetchers.
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
