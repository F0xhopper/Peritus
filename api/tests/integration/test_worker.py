"""BuildWorker end-to-end against a real DB with a fake builder.

Needs PERITUS_TEST_DATABASE_URL (skips otherwise).
"""

import pytest

from peritus.core.exceptions import BuildError
from peritus.experts.builder import BuildResult
from peritus.experts.domain import ExpertStatus, ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.jobs.domain import JobStatus
from peritus.jobs.repository import JobRepository
from peritus.jobs.worker import BuildWorker

pytestmark = pytest.mark.asyncio


def _result(expert_id: int) -> BuildResult:
    return BuildResult(
        expert_id=expert_id, source_count=3, dropped_count=1, chunk_count=10,
        node_count=5, edge_count=4, avg_quality=7.5, persona_name="Dr. Test",
    )


class _FakeBuilder:
    def __init__(self, *, fail_times: int = 0, error: Exception | None = None):
        self.fail_times = fail_times
        self.error = error or RuntimeError("transient")
        self.calls = 0

    async def build(self, expert, on_event=None):
        self.calls += 1
        if on_event:
            await on_event({"type": "stage", "stage": 1, "name": "discover"})
        if self.calls <= self.fail_times:
            raise self.error
        return _result(expert.id)


async def _worker(pool, builder) -> BuildWorker:
    return BuildWorker(pool, concurrency=1, builder_factory=lambda sf: builder)


async def _seed(pool, name: str, max_attempts: int = 3):
    expert = await ExpertRepository(pool).create(name=name, topic=name, tier=ExpertTier.LITE)
    job = await JobRepository(pool).enqueue(expert.id, "lite", None, max_attempts=max_attempts)
    return expert, job


async def test_successful_build(db_pool):
    jobs = JobRepository(db_pool)
    expert, _ = await _seed(db_pool, "worker-ok")
    worker = await _worker(db_pool, _FakeBuilder())

    job = await jobs.claim(worker.worker_id)
    await worker._run_job(job)

    reloaded = await ExpertRepository(db_pool).get_by_id(expert.id)
    assert reloaded.status is ExpertStatus.READY
    final = await jobs.get_job(job.id)
    assert final.status is JobStatus.SUCCEEDED
    events = await jobs.read_events(job.id, 0)
    types = [e.type for e in events]
    assert "build_started" in types and types[-1] == "done"


async def test_retry_then_succeed(db_pool):
    jobs = JobRepository(db_pool)
    expert, _ = await _seed(db_pool, "worker-retry")
    builder = _FakeBuilder(fail_times=1)  # fail attempt 1, succeed attempt 2
    worker = await _worker(db_pool, builder)

    job1 = await jobs.claim(worker.worker_id)
    await worker._run_job(job1)
    after_fail = await jobs.get_job(job1.id)
    assert after_fail.status is JobStatus.QUEUED
    assert (await ExpertRepository(db_pool).get_by_id(expert.id)).status is ExpertStatus.QUEUED

    # Clear backoff so we can immediately re-claim in the test.
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE build_jobs SET available_at = NOW() WHERE id=$1", job1.id)

    job2 = await jobs.claim(worker.worker_id)
    assert job2.attempts == 2
    await worker._run_job(job2)
    assert (await jobs.get_job(job2.id)).status is JobStatus.SUCCEEDED
    assert (await ExpertRepository(db_pool).get_by_id(expert.id)).status is ExpertStatus.READY


async def test_build_error_is_not_retried(db_pool):
    jobs = JobRepository(db_pool)
    expert, _ = await _seed(db_pool, "worker-deaderror")
    builder = _FakeBuilder(fail_times=99, error=BuildError("no sources"))
    worker = await _worker(db_pool, builder)

    job = await jobs.claim(worker.worker_id)  # attempts=1, max=3
    await worker._run_job(job)

    final = await jobs.get_job(job.id)
    assert final.status is JobStatus.FAILED  # BuildError is a deterministic dead-end
    assert final.attempts == 1  # not retried despite budget remaining
    reloaded = await ExpertRepository(db_pool).get_by_id(expert.id)
    assert reloaded.status is ExpertStatus.FAILED
    assert "no sources" in (reloaded.error or "")
