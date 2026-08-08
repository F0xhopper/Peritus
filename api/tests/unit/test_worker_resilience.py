"""The build worker's poll loop must survive a database blip.

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

    async def reap_stale(self, timeout):
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

        async def reap_stale(self, timeout):
            return 0

    worker._jobs = _Cancelling()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(worker.run(), timeout=5)
