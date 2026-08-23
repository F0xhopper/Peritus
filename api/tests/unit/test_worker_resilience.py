"""The build worker's poll loop and heartbeat must survive a database blip.

`claim` runs against Postgres on every poll. Against a transaction pooler a
pooled connection can be closed server-side at any moment, and asyncpg only
discovers it on next use — raising ConnectionDoesNotExistError out of the claim.
Before this was handled, that exception left `run()`, left `worker_main()`, and
killed the worker process along with every in-flight build.

These tests run with no database: the loop's failure handling is the subject, so
the repository is faked.
"""

import asyncio

import pytest
from asyncpg.exceptions import ConnectionDoesNotExistError

from peritus.core.config import settings
from peritus.jobs.worker import BuildWorker

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _fast_polling(monkeypatch):
    """Collapse the poll interval so backoff maths stays sub-second."""
    monkeypatch.setattr(settings, "WORKER_POLL_INTERVAL", 0.001)


class _FlakyJobs:
    """Fails `claim` the first `fail_times` calls, then reports an empty queue."""

    def __init__(self, worker: BuildWorker, fail_times: int, stop_after: int):
        self._worker = worker
        self._fail_times = fail_times
        self._stop_after = stop_after
        self.calls = 0

    async def claim(self, worker_id):
        self.calls += 1
        if self.calls >= self._stop_after:
            self._worker.request_stop()
        if self.calls <= self._fail_times:
            raise ConnectionDoesNotExistError(
                "connection was closed in the middle of operation"
            )
        return None

    async def reap_stale(self, timeout, *, protect_job_ids=None):
        return 0


def _worker() -> BuildWorker:
    # The pool is only stored and handed to collaborators we replace below.
    return BuildWorker(pool=object(), concurrency=1, builder_factory=lambda sf: None)


async def test_run_survives_a_dropped_connection():
    worker = _worker()
    worker._jobs = _FlakyJobs(worker, fail_times=1, stop_after=4)

    await asyncio.wait_for(worker.run(), timeout=5)

    # Reached the stop condition rather than dying on the first failure.
    assert worker._jobs.calls >= 4


async def test_run_survives_a_sustained_outage():
    """Every poll fails. The loop must keep going, not exit."""
    worker = _worker()
    worker._jobs = _FlakyJobs(worker, fail_times=99, stop_after=5)

    await asyncio.wait_for(worker.run(), timeout=10)

    assert worker._jobs.calls >= 5


async def test_backoff_grows_and_is_capped():
    """Repeated failures must not hot-loop, and must not back off unboundedly."""
    worker = _worker()
    delays: list[float] = []

    async def fake_wait_for(awaitable, timeout):
        delays.append(timeout)
        awaitable.close()
        raise TimeoutError

    original = asyncio.wait_for
    asyncio.wait_for = fake_wait_for  # type: ignore[assignment]
    try:
        for attempt in range(1, 12):
            await worker._pause_after_failure(attempt, RuntimeError("boom"))
    finally:
        asyncio.wait_for = original  # type: ignore[assignment]

    assert delays == sorted(delays), "backoff must be non-decreasing"
    assert delays[0] < delays[-1], "backoff must actually grow"
    assert max(delays) <= 60.0, "backoff must stay capped"


async def test_stop_is_honoured_while_backing_off():
    """A shutdown signal during backoff must not wait out the delay."""
    worker = _worker()
    worker.request_stop()

    await asyncio.wait_for(worker._pause_after_failure(10, RuntimeError("boom")), timeout=2)


async def test_cancellation_still_propagates():
    """CancelledError is BaseException, so `except Exception` must not eat it —
    graceful shutdown depends on it reaching the caller."""
    worker = _worker()

    class _Cancelling:
        async def claim(self, worker_id):
            raise asyncio.CancelledError

        async def reap_stale(self, timeout, *, protect_job_ids=None):
            return 0

    worker._jobs = _Cancelling()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(worker.run(), timeout=5)


# ── heartbeat liveness ──────────────────────────────────────────────────────
#
# The heartbeat loop is a job's only claim on being alive. It used to await
# `jobs.heartbeat(...)` bare, so a single failed beat — a dropped pooled
# connection, a saturated pool timing the acquire out — ended the task for good.
# The build carried on with nothing beating for it, WORKER_STALE_TIMEOUT later
# the reaper requeued it, and after WORKER_MAX_ATTEMPTS of that the expert was
# marked failed while its build was still running. Two concurrent builds made
# that routine: only ever one of them survived to "ready".


class _RecordingJobs:
    """Heartbeats raise `fail_times` times, then answer `answer`."""

    def __init__(self, fail_times: int = 0, answer: bool = True):
        self._fail_times = fail_times
        self._answer = answer
        self.calls = 0
        self.reap_args: list = []

    async def heartbeat(self, job_id, worker_id):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise ConnectionDoesNotExistError(
                "connection was closed in the middle of operation"
            )
        return self._answer

    async def reap_stale(self, timeout, *, protect_job_ids=None):
        self.reap_args.append(protect_job_ids)
        return 0


async def test_beat_assumes_alive_when_the_database_is_unreachable():
    """An unanswerable beat means "unknown", not "dead" — the loop must go on."""
    worker = _worker()
    worker._jobs = _RecordingJobs(fail_times=1)

    assert await worker._beat(7) is True  # failed beat, treated as alive
    assert await worker._beat(7) is True  # and the next one gets through
    assert worker._jobs.calls == 2


async def test_beat_still_reports_a_job_that_is_no_longer_ours():
    """Swallowing transport errors must not swallow the real stop signal."""
    worker = _worker()
    worker._jobs = _RecordingJobs(answer=False)

    assert await worker._beat(7) is False


async def test_reaper_is_told_which_jobs_this_worker_is_running(monkeypatch):
    """A worker knows its own live jobs, and must never reap them on the
    strength of a heartbeat it merely failed to send."""
    monkeypatch.setattr(settings, "WORKER_STALE_TIMEOUT", 0.0)
    worker = _worker()
    worker._jobs = _RecordingJobs()
    worker._running_job_ids = {41, 42}

    await worker._maybe_reap()

    assert worker._jobs.reap_args == [{41, 42}]
