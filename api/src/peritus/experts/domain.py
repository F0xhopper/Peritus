from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from peritus.experts.coverage import CoverageTarget


class ExpertStatus(StrEnum):
    QUEUED = "queued"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class ExpertTier(StrEnum):
    LITE = "lite"
    STANDARD = "standard"
    PRO = "pro"


class ExpertVisibility(StrEnum):
    """Who may READ and CHAT WITH an expert. Never who may mutate it.

    Mutation (rebuild, delete, curate) is owner-only at every layer regardless
    of visibility — see ``ExpertRepository.get_owned_for_user``.
    """

    PRIVATE = "private"  # owner, plus anyone holding a grant on a live share link
    PUBLIC = "public"  # anyone; appears in the curated catalog (admin-published)


class ExpertAccess(StrEnum):
    """The caller's relationship to an expert they can read (migration 031).

    Echoed on every expert response so a client can hide the controls a viewer
    cannot use. It is a rendering hint only — every mutating route re-checks
    ownership itself.
    """

    OWNER = "owner"
    VIEWER = "viewer"


# Share tokens: 192 random bits, URL-safe. Mirrored by a length CHECK in 031.
SHARE_TOKEN_BYTES = 24


@dataclass(frozen=True)
class ShareLink:
    """One share link. At most one per expert has ``revoked_at`` unset."""

    id: str
    expert_id: int
    token: str
    created_at: datetime
    created_by: str | None = None
    revoked_at: datetime | None = None


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
    # ── Coverage targets: what "this concept is covered" means at this tier ──
    # These belong here rather than in TierEconomics because they are a
    # *retrieval* property — how deeply the expert can answer on each part of
    # its syllabus — and because ExpertConfig is what the builder already reads.
    # Snapshotted into experts.config at create time like everything else here,
    # so raising a tier's target does not silently re-grade existing experts.
    #
    # Defaulted so a row written before this field existed still deserialises;
    # the defaults are STANDARD's, which is what those rows were built as unless
    # their multiplier says otherwise.
    coverage_min_sources: int = 2
    coverage_min_source_types: int = 2
    coverage_require_non_tertiary: bool = True
    # Every concept needs a primary source (docs/plans/source-selection.md §9).
    # Defaulted False so a row snapshotted before it existed is not re-graded.
    coverage_require_primary: bool = False
    # Discovery rounds *after* the first. 1 is today's behaviour: one pass, then
    # one targeted round for what it missed.
    discovery_max_rounds: int = 2
    # Rounds after the first that must run before meeting the targets can stop
    # the loop. Defaulted 0 for the same reason as coverage_require_primary.
    discovery_min_rounds: int = 0
    # Snowball references followed per round, and how many hops deep. Two hops
    # means an accepted snowball find seeds the next round's snowball, which the
    # discovery loop gives for free.
    snowball_max_per_round: int = 10
    snowball_hops: int = 1
    # How many of the plan's per-concept primary texts the build looks for by
    # title (docs/plans/source-selection.md, "primary texts per concept").
    # Defaulted 0 so a config snapshotted before it existed builds as it did.
    concept_primary_texts: int = 0
    # The most key concepts the planner may name (docs/plans/syllabus.md,
    # phase 2). Defaulted 8 — the old fixed cap — so a snapshotted config plans
    # as it did.
    max_key_concepts: int = 8
    # How many of the plan's named figures get one of their works looked up by
    # title (phase 3.A). Defaulted 0 so an old snapshot builds as it did.
    figure_texts: int = 0

    @classmethod
    def from_tier(cls, tier: ExpertTier) -> "ExpertConfig":
        return _TIER_DEFAULTS[tier]

    def coverage_target(self, subject_kind: str = "canon") -> "CoverageTarget":
        """The tier's target, for the kind of subject the plan named.

        ``subject_kind`` defaults to canon — the target as it always was. A
        practice or a research front adds a current-material requirement per
        concept (experts/coverage.py, sources/subject.py).
        """
        from peritus.experts.coverage import CoverageTarget
        from peritus.sources.subject import normalise_subject_kind

        return CoverageTarget(
            min_sources=self.coverage_min_sources,
            min_source_types=self.coverage_min_source_types,
            require_non_tertiary=self.coverage_require_non_tertiary,
            max_rounds=self.discovery_max_rounds,
            require_primary=self.coverage_require_primary,
            min_rounds=self.discovery_min_rounds,
            subject_kind=normalise_subject_kind(subject_kind),
        )


_TIER_DEFAULTS: dict[ExpertTier, ExpertConfig] = {
    ExpertTier.LITE: ExpertConfig(
        source_multiplier=0.5,
        retrieval_top_k=5,
        max_subqueries=2,
        graph_hops=1,
        coverage_extra_k=3,
        max_context_passages=8,
        max_response_tokens=1024,
        # LITE keeps the old shape exactly: one concept-covering source of any
        # kind, one extra round. Its cost profile must not move.
        coverage_min_sources=1,
        coverage_min_source_types=1,
        coverage_require_non_tertiary=False,
        coverage_require_primary=False,
        discovery_max_rounds=1,
        discovery_min_rounds=0,
        snowball_max_per_round=3,
        snowball_hops=1,
        concept_primary_texts=3,
        max_key_concepts=8,
        figure_texts=0,
    ),
    ExpertTier.STANDARD: ExpertConfig(
        source_multiplier=1.0,
        retrieval_top_k=10,
        max_subqueries=4,
        graph_hops=1,
        coverage_extra_k=5,
        max_context_passages=15,
        max_response_tokens=2048,
        # Three counting sources and a primary text per concept, and a feedback
        # round that always runs. The old target (two sources, two types, one
        # non-tertiary) was met by the Thomism corpus after round 0 with 3 of
        # 43 sources primary, and the round that could have fixed that never ran.
        coverage_min_sources=3,
        coverage_min_source_types=2,
        coverage_require_non_tertiary=True,
        coverage_require_primary=True,
        discovery_max_rounds=2,
        discovery_min_rounds=1,
        snowball_max_per_round=10,
        snowball_hops=1,
        concept_primary_texts=8,
        max_key_concepts=10,
        figure_texts=3,
    ),
    ExpertTier.PRO: ExpertConfig(
        source_multiplier=2.0,
        retrieval_top_k=20,
        max_subqueries=6,
        # 1, not 2: passage annotation only uses edges touching the passage's
        # own anchors, so a second hop was fetched and discarded.
        graph_hops=1,
        coverage_extra_k=10,
        max_context_passages=25,
        max_response_tokens=4096,
        coverage_min_sources=4,
        coverage_min_source_types=2,
        coverage_require_non_tertiary=True,
        coverage_require_primary=True,
        discovery_max_rounds=3,
        discovery_min_rounds=1,
        snowball_max_per_round=20,
        snowball_hops=2,
        concept_primary_texts=16,
        max_key_concepts=14,
        figure_texts=6,
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
    ``discovery_budget_usd`` — soft target the discovery loop spends *towards*,
        counting money already metered plus its own estimate of what the sources
        it has committed to will cost to ingest. Not a ceiling and not enforced
        by the meter: it is the loop's stop condition, deliberately well under
        the hard cap so graph extraction, reconciliation and persona still fit.
    """

    credit_cost: int
    spend_cap_usd: float
    discovery_budget_usd: float


# The price ladder. Credit costs are roughly proportional to the source
# multiplier (0.5 / 1.0 / 2.0), which is what actually drives per-build spend:
# sources → chunks → contextualisation calls → graph-extraction batches.
#
# The caps are a safety valve, not a budget: they sit well above the observed
# cost of a healthy build at each tier, so they only fire on a genuine runaway
# (a pathological corpus, a retry storm, a model price change). Override per
# deployment with PERITUS_TIER_CAP_{LITE,STANDARD,PRO}_USD.
#
# Sizing: a measured healthy *interactive* lite build (18 sources, 576 chunks)
# spends ≈ $1.60 — contextualisation ~$0.65, graph extraction ~$0.79, the rest
# in validation/plan/triage/persona. First builds always run interactive (a
# person is watching), so caps must clear the interactive cost with headroom,
# not the half-price batched cost. The previous 1/3/8 caps sat *below* healthy
# cost and killed every lite build mid-graph.
#
# Discovery budgets: a measured healthy lite build spends ≈$1.60 in total, of
# which roughly half is graph extraction and persona — stages that run *after*
# discovery has finished choosing. The numbers below leave that half free at
# every tier, so a loop that spends its whole discovery budget still completes.
# Override per deployment with PERITUS_TIER_DISCOVERY_{LITE,STANDARD,PRO}_USD.
_TIER_ECONOMICS: dict[ExpertTier, TierEconomics] = {
    ExpertTier.LITE: TierEconomics(credit_cost=1, spend_cap_usd=3.00, discovery_budget_usd=1.25),
    ExpertTier.STANDARD: TierEconomics(
        credit_cost=3, spend_cap_usd=6.00, discovery_budget_usd=3.00
    ),
    ExpertTier.PRO: TierEconomics(credit_cost=8, spend_cap_usd=12.00, discovery_budget_usd=7.00),
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


# Licences that need no credit line beside the picture. Everything else we
# accept (CC BY, CC BY-SA) requires attribution wherever the picture is shown as
# an identity, which is why this is a property of the record rather than a
# judgement made in the web client.
_NO_ATTRIBUTION_PREFIXES: tuple[str, ...] = ("public domain", "pd", "cc0")


@dataclass(frozen=True)
class ExpertPicture:
    """A found, licensed picture of what an expert is *about* (migration 027).

    Deliberately not the avatar. ``Expert.avatar`` is the owner's rendering
    recipe and stays authoritative; this is the default an expert arrives with,
    and it sits between that recipe and the derived monogram:

        avatar (chosen) -> picture (found) -> sigil (derived)

    The bytes are not here. Every list query would carry 100 KB per row for
    something only one endpoint serves, so the blob lives behind
    ``ExpertPictureRepository.get_blob`` and this record carries what a client
    needs to *render* it: a version for the cache-busting URL, dimensions, and
    the provenance that has to be shown beside it.
    """

    provider: str
    file_url: str
    file_page_url: str
    license: str
    sha256: str
    width: int = 0
    height: int = 0
    byte_size: int = 0
    file_name: str | None = None
    page_url: str | None = None
    page_title: str | None = None
    artist: str | None = None
    license_url: str | None = None
    query: str | None = None
    chosen_by: str = "build"
    found_at: datetime | None = None

    @property
    def version(self) -> str:
        """Short content hash. The ``?v=`` that makes an immutable cache safe."""
        return self.sha256[:12]

    @property
    def attribution_required(self) -> bool:
        """False for public domain and CC0; true for every CC BY variant."""
        name = self.license.strip().casefold()
        return not any(name.startswith(p) for p in _NO_ATTRIBUTION_PREFIXES)


@dataclass
class Expert:
    id: int
    name: str  # user-facing slug, e.g. "stoic-philosophy"
    topic: str  # raw build topic string
    status: ExpertStatus
    owner_id: str | None = None  # Supabase auth.users.id; NULL = legacy/admin-owned
    tier: ExpertTier = ExpertTier.STANDARD
    config: ExpertConfig = field(
        default_factory=lambda: ExpertConfig.from_tier(ExpertTier.STANDARD)
    )
    persona_name: str | None = None
    persona_bio: str | None = None
    persona_style: str | None = None
    source_count: int = 0
    chunk_count: int = 0
    node_count: int = 0
    edge_count: int = 0
    avg_quality: float | None = None
    key_concepts: list[str] = field(default_factory=list)
    # What the last discovery loop did and why it stopped (migration 025).
    # Survives the corpus wipe a rebuild performs, so a rebuild can say what the
    # previous build concluded — see builder._log_previous_build.
    build_summary: dict | None = None
    # The owner's chosen picture avatar (migration 026), or None for "derive it
    # from the persona name" — which is what every expert starts as and what
    # every expert built before this column stays as. See ExpertAvatar.
    avatar: dict | None = None
    # The picture found for this expert's subject (migration 027), or None.
    # Joined on by the list/detail/catalog queries; never selected with its
    # bytes. Outranked by `avatar` and outranks the derived monogram.
    picture: ExpertPicture | None = None
    source_type_counts: dict[str, int] = field(default_factory=dict)  # computed, not stored
    # Computed, not stored: whether a build job is queued or running right now.
    # None where the query did not select it.
    build_active: bool | None = None
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
