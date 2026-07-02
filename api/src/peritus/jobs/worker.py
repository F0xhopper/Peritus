"""BuildWorker — claims durable build jobs and runs the pipeline to completion.

Runs either as a standalone process (`peritus-worker`) or inside the API process
(when RUN_WORKER_IN_PROCESS is set). Either way the same loop:

  reap crashed jobs → claim up to WORKER_CONCURRENCY jobs → run each with a
  heartbeat → persist progress to build_events → succeed / retry / fail.
"""

import asyncio
import os
import socket
import uuid
from collections.abc import Callable
from contextlib import suppress
from typing import Any

import asyncpg

from peritus.core.config import settings
from peritus.core.exceptions import BuildError
from peritus.core.logging import get_logger
from peritus.experts.builder import BuildResult, ExpertBuilder
from peritus.experts.domain import ExpertStatus
from peritus.experts.repository import ExpertRepository
from peritus.jobs.domain import BuildJob
from peritus.jobs.repository import JobRepository

logger = get_logger(__name__)


class _JobCancelled(Exception):
    """Raised internally when a running job is cancelled or reaped mid-build."""


class BuildWorker:
    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        concurrency: int | None = None,
        builder_factory: Callable[[list[str] | None], Any] | None = None,
    ) -> None:
        self._pool = pool
        self._jobs = JobRepository(pool)
        self._concurrency = concurrency or settings.WORKER_CONCURRENCY
        # Injectable so tests can substitute a fake ExpertBuilder.
        self._builder_factory: Callable[[list[str] | None], Any] = builder_factory or (
            lambda source_filter: ExpertBuilder(pool, source_filter=source_filter)
        )
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()
        self._running: set[asyncio.Task[None]] = set()
        self._reap_counter = 0.0

    def request_stop(self) -> None:
        """Signal the run loop to stop claiming new work and drain."""
        self._stop.set()

    async def run(self) -> None:
        logger.info("BuildWorker %s started (concurrency=%d)", self.worker_id, self._concurrency)
        try:
            while not self._stop.is_set():
                await self._maybe_reap()
                claimed_any = await self._fill_slots()
                if not claimed_any:
                    # Nothing to do — idle until the next poll or a stop signal.
                    with suppress(TimeoutError):
                        await asyncio.wait_for(
                            self._stop.wait(), timeout=settings.WORKER_POLL_INTERVAL
                        )
        finally:
            await self._drain()
            logger.info("BuildWorker %s stopped", self.worker_id)

    async def _fill_slots(self) -> bool:
        claimed_any = False
        while len(self._running) < self._concurrency and not self._stop.is_set():
            job = await self._jobs.claim(self.worker_id)
            if job is None:
                break
            claimed_any = True
            logger.info(
                "Claimed job %d (expert=%d, attempt=%d)", job.id, job.expert_id, job.attempts
            )
            task = asyncio.create_task(self._run_job(job))
            self._running.add(task)
            task.add_done_callback(self._running.discard)
        return claimed_any

    async def _maybe_reap(self) -> None:
        # Run the reaper roughly every stale-timeout window, not every poll.
        self._reap_counter += settings.WORKER_POLL_INTERVAL
        if self._reap_counter < settings.WORKER_STALE_TIMEOUT:
            return
        self._reap_counter = 0.0
        try:
            n = await self._jobs.reap_stale(settings.WORKER_STALE_TIMEOUT)
            if n:
                logger.warning("Reaped %d stale build job(s)", n)
        except Exception as exc:  # never let reaping kill the loop
            logger.warning("Reaper failed: %s", exc)

    async def _drain(self) -> None:
        """On shutdown, cancel in-flight builds and hand their jobs back to the queue."""
        if not self._running:
            return
        logger.info("Draining %d in-flight job(s) for graceful shutdown", len(self._running))
        for task in list(self._running):
            task.cancel()
        await asyncio.gather(*list(self._running), return_exceptions=True)

    # ── single job execution ────────────────────────────────────────────────

    async def _run_job(self, job: BuildJob) -> None:
        expert_repo = ExpertRepository(self._pool)
        expert = await expert_repo.get_by_id(job.expert_id)
        if expert is None:
            # Expert was deleted before we started — nothing to build.
            await self._jobs.mark_failed(job.id, self.worker_id, "Expert no longer exists")
            return

        cancelled = False
        build_task: asyncio.Task[Any] | None = None

        async def heartbeat_loop() -> None:
            nonlocal cancelled
            while True:
                await asyncio.sleep(settings.WORKER_HEARTBEAT_INTERVAL)
                alive = await self._jobs.heartbeat(job.id, self.worker_id)
                if not alive:
                    cancelled = True
                    if build_task is not None:
                        build_task.cancel()
                    return

        hb_task = asyncio.create_task(heartbeat_loop())
        try:
            await expert_repo.update_status(expert.id, ExpertStatus.BUILDING)
            await expert_repo.reset_build_state(expert.id)
            await self._jobs.append_event(job.id, "build_started", {
                "type": "build_started",
                "attempt": job.attempts,
                "max_attempts": job.max_attempts,
            })

            async def on_event(event: dict[str, Any]) -> None:
                await self._jobs.append_event(job.id, event["type"], event)

            builder = self._builder_factory(job.source_filter)
            build_task = asyncio.create_task(builder.build(expert, on_event=on_event))
            try:
                result: BuildResult = await build_task
            except asyncio.CancelledError:
                if cancelled:
                    raise _JobCancelled from None
                raise  # worker shutdown — propagate so _drain requeues it

            await expert_repo.update_status(expert.id, ExpertStatus.READY)
            await self._jobs.append_event(job.id, "done", {
                "type": "done",
                "expert_id": result.expert_id,
                "source_count": result.source_count,
                "chunk_count": result.chunk_count,
                "node_count": result.node_count,
                "edge_count": result.edge_count,
                "persona_name": result.persona_name,
                "avg_quality": result.avg_quality,
            })
            await self._jobs.mark_succeeded(job.id, self.worker_id)
            logger.info("Job %d succeeded (expert=%d)", job.id, job.expert_id)

        except _JobCancelled:
            await self._on_cancelled(job, expert_repo)
        except asyncio.CancelledError:
            # Graceful shutdown: return the job to the queue for another worker.
            await self._jobs.release_for_shutdown(job.id, self.worker_id)
            logger.info("Job %d released back to queue (shutdown)", job.id)
            raise
        except Exception as exc:
            await self._on_failure(job, expert_repo, exc)
        finally:
            # Never leave the pipeline running detached (e.g. on shutdown cancellation).
            if build_task is not None and not build_task.done():
                build_task.cancel()
                with suppress(asyncio.CancelledError):
                    await build_task
            hb_task.cancel()
            with suppress(asyncio.CancelledError):
                await hb_task

    async def _on_cancelled(self, job: BuildJob, expert_repo: ExpertRepository) -> None:
        logger.info("Job %d cancelled", job.id)
        # Best-effort — the expert row may already be deleted (cancel via DELETE).
        with suppress(Exception):
            await self._jobs.append_event(job.id, "cancelled", {
                "type": "cancelled", "message": "Build cancelled",
            })
        with suppress(Exception):
            await expert_repo.update_status(
                job.expert_id, ExpertStatus.FAILED, "Build cancelled"
            )

    async def _on_failure(
        self, job: BuildJob, expert_repo: ExpertRepository, exc: Exception
    ) -> None:
        message = str(exc) or exc.__class__.__name__
        retryable = not isinstance(exc, BuildError)  # BuildError = deterministic dead-end
        if retryable and job.attempts < job.max_attempts:
            backoff = settings.WORKER_BACKOFF_BASE * (2 ** (job.attempts - 1))
            logger.warning(
                "Job %d attempt %d/%d failed: %s — retrying in %.0fs",
                job.id, job.attempts, job.max_attempts, message, backoff,
            )
            await self._jobs.append_event(job.id, "retry", {
                "type": "retry", "attempt": job.attempts,
                "max_attempts": job.max_attempts, "message": message,
            })
            await expert_repo.update_status(job.expert_id, ExpertStatus.QUEUED)
            await self._jobs.requeue(job.id, self.worker_id, message, backoff)
        else:
            logger.error("Job %d failed permanently: %s", job.id, message)
            await expert_repo.update_status(job.expert_id, ExpertStatus.FAILED, message)
            await self._jobs.append_event(job.id, "error", {
                "type": "error", "message": message,
            })
            await self._jobs.mark_failed(job.id, self.worker_id, message)
