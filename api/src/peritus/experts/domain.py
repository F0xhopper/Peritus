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


@dataclass
class Expert:
    id: int
    name: str          # user-facing slug, e.g. "stoic-philosophy"
    topic: str         # raw build topic string
    status: ExpertStatus
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
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
