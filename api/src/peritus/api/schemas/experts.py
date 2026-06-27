from datetime import datetime
from pydantic import BaseModel

from peritus.experts.domain import ExpertTier


class ExpertSummary(BaseModel):
    id: int
    name: str
    topic: str
    status: str
    tier: str = ExpertTier.STANDARD.value
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


class BuildRequest(BaseModel):
    topic: str
    tier: ExpertTier = ExpertTier.STANDARD
