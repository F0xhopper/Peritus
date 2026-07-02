"""Durable queue semantics for JobRepository (needs PERITUS_TEST_DATABASE_URL)."""

import asyncio

import pytest

from peritus.experts.domain import ExpertStatus, ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.jobs.domain import JobStatus
from peritus.jobs.repository import JobRepository

pytestmark = pytest.mark.asyncio


async def _new_expert(pool, name: str) -> int:
    e = await ExpertRepository(pool).create(name=name, topic=name, tier=ExpertTier.LITE)
    return e.id


async def test_enqueue_is_idempotent_per_expert(db_pool):
    jobs = JobRepository(db_pool)
    eid = await _new_expert(db_pool, "idem")
    a = await jobs.enqueue(eid, "lite", None, max_attempts=3)
    b = await jobs.enqueue(eid, "lite", None, max_attempts=3)
    assert a.id == b.id  # partial unique index → same active job


async def test_claim_skip_locked_no_double_grab(db_pool):
    jobs = JobRepository(db_pool)
    eid = await _new_expert(db_pool, "single")
    await jobs.enqueue(eid, "lite", None, max_attempts=3)

    # Two workers race for one job: exactly one wins, the other gets nothing.
    r1, r2 = await asyncio.gather(jobs.claim("w1"), jobs.claim("w2"))
    got = [r for r in (r1, r2) if r is not None]
    assert len(got) == 1
    assert got[0].status is JobStatus.RUNNING
    assert got[0].attempts == 1


async def test_backoff_gates_claim(db_pool):
    jobs = JobRepository(db_pool)
    eid = await _new_expert(db_pool, "backoff")
    job = await jobs.enqueue(eid, "lite", None, max_attempts=3)
    claimed = await jobs.claim("w1")
    assert claimed is not None
    await jobs.requeue(job.id, "w1", "boom", backoff_seconds=100)
    # available_at is now in the future — nothing is claimable.
    assert await jobs.claim("w1") is None


async def test_reap_requeues_then_fails(db_pool):
    jobs = JobRepository(db_pool)
    eid = await _new_expert(db_pool, "reap")
    job = await jobs.enqueue(eid, "lite", None, max_attempts=2)

    # Attempt 1: claim, then simulate a crashed worker (stale heartbeat).
    await jobs.claim("w1")
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE build_jobs SET heartbeat_at = NOW() - INTERVAL '1 hour' WHERE id=$1",
            job.id,
        )
    assert await jobs.reap_stale(1) == 1
    reaped = await jobs.get_job(job.id)
    assert reaped.status is JobStatus.QUEUED  # retries remain

    # Attempt 2 (max): claim, crash again → reaper fails it permanently.
    await jobs.claim("w1")
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE build_jobs SET heartbeat_at = NOW() - INTERVAL '1 hour' WHERE id=$1",
            job.id,
        )
    assert await jobs.reap_stale(1) == 1
    dead = await jobs.get_job(job.id)
    assert dead.status is JobStatus.FAILED
    expert = await ExpertRepository(db_pool).get_by_id(eid)
    assert expert.status is ExpertStatus.FAILED


async def test_heartbeat_false_after_cancel(db_pool):
    jobs = JobRepository(db_pool)
    eid = await _new_expert(db_pool, "cancel")
    job = await jobs.enqueue(eid, "lite", None, max_attempts=3)
    await jobs.claim("w1")
    assert await jobs.heartbeat(job.id, "w1") is True
    assert await jobs.request_cancel(eid) is True
    # Cancelled job is no longer 'running' → heartbeat reports stop.
    assert await jobs.heartbeat(job.id, "w1") is False


async def test_event_log_cursor(db_pool):
    jobs = JobRepository(db_pool)
    eid = await _new_expert(db_pool, "events")
    job = await jobs.enqueue(eid, "lite", None, max_attempts=3)
    s1 = await jobs.append_event(job.id, "stage", {"type": "stage", "n": 1})
    await jobs.append_event(job.id, "stage", {"type": "stage", "n": 2})
    await jobs.append_event(job.id, "done", {"type": "done"})

    all_events = await jobs.read_events(job.id, after_seq=0)
    assert [e.type for e in all_events] == ["stage", "stage", "done"]
    assert [e.seq for e in all_events] == sorted(e.seq for e in all_events)

    tail = await jobs.read_events(job.id, after_seq=s1)
    assert [e.payload.get("n", e.type) for e in tail] == [2, "done"]
