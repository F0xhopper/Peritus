"""Durable queue semantics for JobRepository (needs PERITUS_TEST_DATABASE_URL)."""

import asyncio
import time

import asyncpg
import pytest

from peritus.core.config import settings
from peritus.experts.domain import ExpertStatus, ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.jobs.domain import JobStatus
from peritus.jobs.repository import JobRepository
from tests.conftest import TEST_DB_URL

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


async def test_reap_spares_the_jobs_a_live_worker_declares(db_pool):
    """A stale heartbeat is evidence a worker died — evidence the worker itself
    can contradict. It reaped its own running builds otherwise, re-claimed them,
    and ran a second copy over the first."""
    jobs = JobRepository(db_pool)
    eid = await _new_expert(db_pool, "reap-protected")
    job = await jobs.enqueue(eid, "lite", None, max_attempts=3)
    await jobs.claim("w1")
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE build_jobs SET heartbeat_at = NOW() - INTERVAL '1 hour' WHERE id=$1",
            job.id,
        )

    # w1 still holds the task, so it says so and the job is left alone.
    assert await jobs.reap_stale(1, protect_job_ids={job.id}) == 0
    assert (await jobs.get_job(job.id)).status is JobStatus.RUNNING

    # Unprotected — a genuinely dead worker — it is reaped as before.
    assert await jobs.reap_stale(1) == 1
    assert (await jobs.get_job(job.id)).status is JobStatus.QUEUED


@pytest.mark.parametrize("call", ["claim", "reap_stale"])
async def test_poll_loop_gives_up_on_an_exhausted_pool(db_pool, monkeypatch, call):
    """Claiming and reaping must time out, not park.

    These two are the *entire* worker poll loop. An unbounded `acquire()` here
    does not slow the loop, it ends it — parked inside acquire forever, never
    claiming and, far worse, never reaping. The process stays up, logs nothing
    and burns no CPU, while every stale job in the queue sits at 'running'
    because the only thing that would recover them is asleep. Observed in the
    wild: a build stuck 'running' for 88 minutes with a live worker beside it.
    """
    if not TEST_DB_URL:
        pytest.skip("PERITUS_TEST_DATABASE_URL not set — skipping DB-backed test")
    monkeypatch.setattr(settings, "DB_ACQUIRE_TIMEOUT", 0.25)

    # A pool of exactly one connection, held for the duration — the smallest
    # faithful model of "every connection is busy".
    pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=1, statement_cache_size=0)
    try:
        jobs = JobRepository(pool)
        async with pool.acquire():
            started = time.monotonic()
            with pytest.raises(TimeoutError):
                # The backstop only stops a regression from hanging the suite —
                # it must not be what satisfies pytest.raises, or this test would
                # pass against the unbounded acquire it exists to forbid. The
                # elapsed assertion is the real one.
                await asyncio.wait_for(
                    jobs.claim("w1") if call == "claim" else jobs.reap_stale(1),
                    timeout=30,
                )
            elapsed = time.monotonic() - started
        assert elapsed < 5, (
            f"{call}() waited {elapsed:.1f}s — the timeout came from the test's backstop, "
            "so the acquire is unbounded again"
        )
        # The pool is healthy again the moment a connection frees up.
        assert await jobs.claim("w1") is None
    finally:
        await pool.close()


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
