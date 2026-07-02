from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Terminal event types written to build_events that end an SSE tail.
TERMINAL_EVENT_TYPES = frozenset({"done", "error", "cancelled"})


@dataclass
class BuildJob:
    id: int
    expert_id: int
    status: JobStatus
    tier: str
    source_filter: list[str] | None
    attempts: int
    max_attempts: int
    available_at: datetime
    locked_by: str | None
    heartbeat_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class BuildEventRow:
    seq: int
    job_id: int
    type: str
    payload: dict[str, Any]
    created_at: datetime
