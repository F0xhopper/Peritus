from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ExpertStatus(str, Enum):
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


@dataclass
class Expert:
    id: int
    name: str          # user-facing slug, e.g. "stoic philosophy"
    topic: str         # raw build topic string
    status: ExpertStatus
    persona_name: str | None = None
    persona_bio: str | None = None
    persona_style: str | None = None
    source_count: int = 0
    chunk_count: int = 0
    node_count: int = 0
    edge_count: int = 0
    avg_quality: float | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
