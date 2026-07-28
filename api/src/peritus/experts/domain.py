from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ExpertStatus(StrEnum):
    QUEUED = "queued"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class ExpertTier(StrEnum):
    LITE     = "lite"
    STANDARD = "standard"
    PRO      = "pro"


class ExpertVisibility(StrEnum):
    """Who may READ and CHAT WITH an expert. Never who may mutate it.

    Mutation (rebuild, delete, curate) is owner-only at every layer regardless
    of visibility — see ``ExpertRepository.get_owned_for_user``.
    """

    PRIVATE  = "private"    # owner only (admins also see legacy owner-less rows)
    UNLISTED = "unlisted"   # anyone with the slug; never appears in the catalog
    PUBLIC   = "public"     # anyone; appears in the curated catalog


# Visibility levels that make an expert readable/chattable beyond its owner.
SHARED_VISIBILITIES: frozenset[str] = frozenset(
    {ExpertVisibility.UNLISTED.value, ExpertVisibility.PUBLIC.value}
)

# Readiness values (migration 018) at which an expert can answer a question.
# The catalog lists on this rather than on job status: a public expert whose
# chunks are embedded is useful to a visitor even while its graph is still
# extracting, and hiding it would waste the whole point of a warm catalog.
CHATTABLE_READINESS: frozenset[str] = frozenset({"chat_ready", "graph_ready"})


@dataclass(frozen=True)
class ExpertConfig:
    source_multiplier: float
    retrieval_top_k: int
    max_subqueries: int
    graph_hops: int
    coverage_extra_k: int
    max_context_passages: int
    max_response_tokens: int

    @classmethod
    def from_tier(cls, tier: ExpertTier) -> "ExpertConfig":
        return _TIER_DEFAULTS[tier]


_TIER_DEFAULTS: dict[ExpertTier, ExpertConfig] = {
    ExpertTier.LITE: ExpertConfig(
        source_multiplier=0.5,
        retrieval_top_k=5,
        max_subqueries=2,
        graph_hops=1,
        coverage_extra_k=3,
        max_context_passages=8,
        max_response_tokens=1024,
    ),
    ExpertTier.STANDARD: ExpertConfig(
        source_multiplier=1.0,
        retrieval_top_k=10,
        max_subqueries=4,
        graph_hops=1,
        coverage_extra_k=5,
        max_context_passages=15,
        max_response_tokens=2048,
    ),
    ExpertTier.PRO: ExpertConfig(
        source_multiplier=2.0,
        retrieval_top_k=20,
        max_subqueries=6,
        graph_hops=2,
        coverage_extra_k=10,
        max_context_passages=25,
        max_response_tokens=4096,
    ),
}


@dataclass(frozen=True)
class TierEconomics:
    """The price side of a tier. Deliberately *not* part of ``ExpertConfig``.

    ``ExpertConfig`` is serialised into ``experts.config`` at create time, so
    anything in it is frozen into every existing row. Prices must be free to
    change without rewriting history, so they live here and are resolved fresh
    on every authorisation, then snapshotted onto the build job.

    ``credit_cost``  — credits a build at this tier consumes.
    ``spend_cap_usd`` — hard ceiling on real provider spend for one build at this
        tier. Enforced by the meter at runtime; a build that crosses it is
        aborted and the credit hold is refunded in full (see billing/service.py).
    """

    credit_cost: int
    spend_cap_usd: float


# The price ladder. Credit costs are roughly proportional to the source
# multiplier (0.5 / 1.0 / 2.0), which is what actually drives per-build spend:
# sources → chunks → contextualisation calls → graph-extraction batches.
#
# The caps are a safety valve, not a budget: they sit well above the observed
# cost of a healthy build at each tier, so they only fire on a genuine runaway
# (a pathological corpus, a retry storm, a model price change). Override per
# deployment with PERITUS_TIER_CAP_{LITE,STANDARD,PRO}_USD.
_TIER_ECONOMICS: dict[ExpertTier, TierEconomics] = {
    ExpertTier.LITE:     TierEconomics(credit_cost=1, spend_cap_usd=1.00),
    ExpertTier.STANDARD: TierEconomics(credit_cost=3, spend_cap_usd=3.00),
    ExpertTier.PRO:      TierEconomics(credit_cost=8, spend_cap_usd=8.00),
}


def tier_economics(tier: ExpertTier) -> TierEconomics:
    return _TIER_ECONOMICS[tier]


@dataclass
class CatalogMeta:
    """Curation fields — what the public catalog renders and orders by."""

    visibility: ExpertVisibility = ExpertVisibility.PRIVATE
    is_featured: bool = False
    catalog_rank: int | None = None
    blurb: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    published_at: datetime | None = None
    published_by: str | None = None

    @property
    def is_public(self) -> bool:
        return self.visibility is ExpertVisibility.PUBLIC


# A blurb renders on a catalog card; mirrored by a CHECK constraint in 015.
BLURB_MAX_CHARS = 280


@dataclass
class Expert:
    id: int
    name: str          # user-facing slug, e.g. "stoic-philosophy"
    topic: str         # raw build topic string
    status: ExpertStatus
    owner_id: str | None = None  # Supabase auth.users.id; NULL = legacy/admin-owned
    tier: ExpertTier = ExpertTier.STANDARD
    config: ExpertConfig = field(default_factory=lambda: ExpertConfig.from_tier(ExpertTier.STANDARD))
    persona_name: str | None = None
    persona_bio: str | None = None
    persona_style: str | None = None
    source_count: int = 0
    chunk_count: int = 0
    node_count: int = 0
    edge_count: int = 0
    avg_quality: float | None = None
    key_concepts: list[str] = field(default_factory=list)
    source_type_counts: dict[str, int] = field(default_factory=dict)  # computed, not stored
    catalog: CatalogMeta = field(default_factory=CatalogMeta)
    # Retrieval readiness (migration 018): pending | chat_ready | graph_ready.
    # Held as a plain string so this module stays free of a search/ dependency;
    # the canonical enum is peritus.search.readiness.Readiness.
    readiness: str = "pending"
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def visibility(self) -> ExpertVisibility:
        return self.catalog.visibility

    @property
    def is_chattable(self) -> bool:
        """Whether this expert can answer a question right now.

        An expert becomes answerable when its chunks are embedded — one whole
        stage before the build job finishes. Gating chat on ``status == 'ready'``
        would hide a usable expert for the length of graph extraction.
        """
        return self.readiness in CHATTABLE_READINESS

    @property
    def graph_expanded(self) -> bool:
        """Whether graph expansion is available (the concept graph is built)."""
        return self.readiness == "graph_ready"

    def is_owned_by(self, owner_id: str, include_unowned: bool = False) -> bool:
        """Mutation predicate. Public experts are still only mutable by their owner."""
        if self.owner_id is None:
            return include_unowned
        return self.owner_id == owner_id
