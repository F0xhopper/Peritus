from datetime import datetime
from pydantic import BaseModel


class ExpertSummary(BaseModel):
    id: int
    name: str
    topic: str
    status: str
    persona_name: str | None = None
    source_count: int = 0
    chunk_count: int = 0
    node_count: int = 0
    edge_count: int = 0
    created_at: datetime


class ExpertDetail(ExpertSummary):
    persona_bio: str | None = None
    persona_style: str | None = None
    avg_quality: float | None = None
    error: str | None = None
    updated_at: datetime


class BuildRequest(BaseModel):
    topic: str
    depth: str = "normal"
