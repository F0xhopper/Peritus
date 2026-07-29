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


class JobType(StrEnum):
    """What a queued job actually does.

    The queue was built for builds and everything about it generalises — claim,
    heartbeat, retry, reap, and the persisted event tail are all indifferent to
    what the job body is. Only :meth:`JobWorker._run_job` cares, and it branches
    here.
    """

    BUILD = "build"
    # Ingest one user-supplied document (see ``peritus.uploads``). Its target is
    # in ``BuildJob.payload`` as ``{"upload_id": int}``.
    INGEST_SOURCE = "ingest_source"


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
    # Defaulted so every existing constructor call and test fixture stays valid;
    # rows written before migration 021 read back as builds, which they were.
    job_type: JobType = JobType.BUILD
    payload: dict[str, Any] | None = None

    @property
    def is_build(self) -> bool:
        return self.job_type is JobType.BUILD


@dataclass
class BuildEventRow:
    seq: int
    job_id: int
    type: str
    payload: dict[str, Any]
    created_at: datetime
