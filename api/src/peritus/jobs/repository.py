import json
from typing import Any

import asyncpg

from peritus.jobs.domain import BuildEventRow, BuildJob, JobStatus, JobType


class JobRepository:
    """Postgres-backed durable queue for expert build jobs.

    Claiming uses `SELECT ... FOR UPDATE SKIP LOCKED` so any number of workers can
    pull from the queue without ever grabbing the same job twice.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── enqueue / lookup ────────────────────────────────────────────────────

    async def enqueue(
        self,
        expert_id: int,
        tier: str,
        source_filter: list[str] | None,
        max_attempts: int,
        job_type: JobType = JobType.BUILD,
        payload: dict[str, Any] | None = None,
    ) -> BuildJob:
        """Insert a queued job. If an active *build* already exists for this expert
        (partial unique index), return that one instead — resubmits are idempotent.

        Only builds are deduplicated that way. Two ingest jobs for one expert are
        two different documents, and collapsing them would silently drop one; the
        unique index is scoped to builds for the same reason (migration 021).
        """
        async with self._pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO build_jobs
                        (expert_id, status, tier, source_filter, max_attempts, job_type, payload)
                    VALUES ($1, 'queued', $2, $3::jsonb, $4, $5, $6::jsonb)
                    RETURNING *
                    """,
                    expert_id, tier,
                    json.dumps(source_filter) if source_filter is not None else None,
                    max_attempts,
                    str(job_type),
                    json.dumps(payload) if payload is not None else None,
                )
                return _row_to_job(row)
            except asyncpg.UniqueViolationError:
                existing = await self.get_active_job(expert_id, job_type=JobType.BUILD)
                if existing:
                    return existing
                raise

    async def get_job(self, job_id: int) -> BuildJob | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM build_jobs WHERE id = $1", job_id)
        return _row_to_job(row) if row else None

    async def get_active_job(
        self, expert_id: int, job_type: JobType | None = None
    ) -> BuildJob | None:
        """The newest queued-or-running job for this expert, optionally by type.

        Callers that mean "is a build in progress" must pass
        ``job_type=JobType.BUILD``: an unfiltered call can now return an ingest
        job, and build-cancel and build-status logic would misread that as a
        build.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM build_jobs
                WHERE expert_id = $1 AND status IN ('queued', 'running')
                  AND ($2::text IS NULL OR job_type = $2)
                ORDER BY id DESC LIMIT 1
                """,
                expert_id, str(job_type) if job_type is not None else None,
            )
        return _row_to_job(row) if row else None

    async def get_latest_job(self, expert_id: int) -> BuildJob | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM build_jobs WHERE expert_id = $1 ORDER BY id DESC LIMIT 1",
                expert_id,
            )
        return _row_to_job(row) if row else None

    # ── worker lifecycle ────────────────────────────────────────────────────

    async def claim(self, worker_id: str) -> BuildJob | None:
        """Atomically claim the next runnable job for this worker, or None."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE build_jobs
                SET status = 'running', locked_by = $1, heartbeat_at = NOW(),
                    attempts = attempts + 1, updated_at = NOW()
                WHERE id = (
                    SELECT id FROM build_jobs
                    WHERE status = 'queued' AND available_at <= NOW()
                    ORDER BY available_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING *
                """,
                worker_id,
            )
        return _row_to_job(row) if row else None

    async def heartbeat(self, job_id: int, worker_id: str) -> bool:
        """Bump the liveness beat. Returns False if the job is no longer ours or no
        longer running (cancelled or reaped) — the worker treats that as a stop signal.
        """
        async with self._pool.acquire() as conn:
            result: str = await conn.execute(
                """
                UPDATE build_jobs SET heartbeat_at = NOW(), updated_at = NOW()
                WHERE id = $1 AND locked_by = $2 AND status = 'running'
                """,
                job_id, worker_id,
            )
        return result.endswith(" 1")

    async def mark_succeeded(self, job_id: int, worker_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE build_jobs SET status = 'succeeded', last_error = NULL,
                    updated_at = NOW()
                WHERE id = $1 AND locked_by = $2 AND status = 'running'
                """,
                job_id, worker_id,
            )

    async def mark_failed(self, job_id: int, worker_id: str, error: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE build_jobs SET status = 'failed', last_error = $3, updated_at = NOW()
                WHERE id = $1 AND locked_by = $2 AND status = 'running'
                """,
                job_id, worker_id, error[:2000],
            )

    async def requeue(
        self, job_id: int, worker_id: str, error: str, backoff_seconds: float
    ) -> None:
        """Return a job to the queue after a retryable failure, gated by backoff."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE build_jobs
                SET status = 'queued', locked_by = NULL, last_error = $3,
                    available_at = NOW() + make_interval(secs => $4), updated_at = NOW()
                WHERE id = $1 AND locked_by = $2 AND status = 'running'
                """,
                job_id, worker_id, error[:2000], float(backoff_seconds),
            )

    async def release_for_shutdown(self, job_id: int, worker_id: str) -> None:
        """Put an in-flight job straight back on the queue on graceful shutdown so a
        surviving worker (or the restarted one) picks it up immediately.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE build_jobs
                SET status = 'queued', locked_by = NULL, available_at = NOW(),
                    updated_at = NOW()
                WHERE id = $1 AND locked_by = $2 AND status = 'running'
                """,
                job_id, worker_id,
            )

    # ── crash recovery / cancellation ───────────────────────────────────────

    async def reap_stale(self, timeout_seconds: float) -> int:
        """Recover jobs whose worker died: their heartbeat has gone stale. Requeue
        those with retries left; permanently fail the rest (and mark their experts
        failed). Returns the number of jobs reaped.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            requeued = await conn.fetch(
                """
                    UPDATE build_jobs
                    SET status = 'queued', locked_by = NULL, available_at = NOW(),
                        last_error = 'Worker heartbeat timed out — requeued', updated_at = NOW()
                    WHERE status = 'running'
                      AND heartbeat_at < NOW() - make_interval(secs => $1)
                      AND attempts < max_attempts
                    RETURNING id
                    """,
                float(timeout_seconds),
            )
            failed = await conn.fetch(
                """
                    UPDATE build_jobs
                    SET status = 'failed', locked_by = NULL,
                        last_error = 'Worker heartbeat timed out — retries exhausted',
                        updated_at = NOW()
                    WHERE status = 'running'
                      AND heartbeat_at < NOW() - make_interval(secs => $1)
                      AND attempts >= max_attempts
                    RETURNING expert_id
                    """,
                float(timeout_seconds),
            )
            for r in failed:
                await conn.execute(
                    """
                        UPDATE experts SET status = 'failed',
                            error = 'Build worker crashed and retries were exhausted.',
                            updated_at = NOW()
                        WHERE id = $1
                        """,
                    r["expert_id"],
                )
        return len(requeued) + len(failed)

    async def request_cancel(
        self, expert_id: int, job_type: JobType | None = None
    ) -> bool:
        """Cancel active jobs for an expert. A running job sees the heartbeat stop
        returning True and aborts cooperatively. Returns True if anything was cancelled.

        ``job_type=None`` cancels every active job, which is what deleting an
        expert wants. Cancelling a *build* must pass ``JobType.BUILD``: an
        unscoped cancel would also throw away documents the user had queued for
        ingest, which they never asked to cancel and cannot recover.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE build_jobs SET status = 'cancelled', updated_at = NOW()
                WHERE expert_id = $1 AND status IN ('queued', 'running')
                  AND ($2::text IS NULL OR job_type = $2)
                """,
                expert_id, str(job_type) if job_type is not None else None,
            )
        return not result.endswith(" 0")

    # ── durable event log ───────────────────────────────────────────────────

    async def append_event(self, job_id: int, type_: str, payload: dict[str, Any]) -> int:
        async with self._pool.acquire() as conn:
            seq = await conn.fetchval(
                """
                INSERT INTO build_events (job_id, type, payload)
                VALUES ($1, $2, $3::jsonb)
                RETURNING seq
                """,
                job_id, type_, json.dumps(payload),
            )
        return int(seq)

    async def read_events(
        self, job_id: int, after_seq: int, limit: int = 500
    ) -> list[BuildEventRow]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT seq, job_id, type, payload, created_at
                FROM build_events
                WHERE job_id = $1 AND seq > $2
                ORDER BY seq
                LIMIT $3
                """,
                job_id, after_seq, limit,
            )
        return [_row_to_event(r) for r in rows]


def _row_to_job(row: asyncpg.Record) -> BuildJob:
    raw_filter = row["source_filter"]
    if isinstance(raw_filter, str):
        raw_filter = json.loads(raw_filter)
    # `.get` rather than indexing: tests and older callers build Records/mappings
    # that predate migration 021 and carry neither column.
    payload = row.get("payload")
    if isinstance(payload, str):
        payload = json.loads(payload)
    return BuildJob(
        id=row["id"],
        expert_id=row["expert_id"],
        status=JobStatus(row["status"]),
        tier=row["tier"],
        source_filter=list(raw_filter) if raw_filter else None,
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        available_at=row["available_at"],
        locked_by=row["locked_by"],
        heartbeat_at=row["heartbeat_at"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        job_type=JobType(row.get("job_type") or JobType.BUILD),
        payload=payload,
    )


def _row_to_event(row: asyncpg.Record) -> BuildEventRow:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return BuildEventRow(
        seq=row["seq"],
        job_id=row["job_id"],
        type=row["type"],
        payload=payload,
        created_at=row["created_at"],
    )
