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

from peritus.billing.domain import SpendCapExceeded
from peritus.billing.metering import (
    BuildMeter,
    flush_once,
    flush_periodically,
    install_instrumentation,
    reset_meter,
    set_meter,
)
from peritus.billing.repository import BillingRepository
from peritus.billing.service import EntitlementService
from peritus.billing.settings import settings as billing_settings
from peritus.core.config import settings
from peritus.core.exceptions import BuildError, IngestionError
from peritus.core.logging import get_logger
from peritus.experts.builder import BuildResult, ExpertBuilder
from peritus.experts.domain import ExpertStatus, ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.jobs.domain import BuildJob
from peritus.jobs.repository import JobRepository
from peritus.uploads.service import ingest_upload, summary_event

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
        self._entitlements = EntitlementService(pool)
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

        if not job.is_build:
            await self._run_ingest_job(job, expert)
            return

        cancelled = False
        cap_exceeded = False
        build_task: asyncio.Task[Any] | None = None

        # Metering context for this job. Bound here, before the build task is
        # created, so every task the pipeline spawns inherits it — and so two
        # concurrent builds in this worker meter independently.
        meter = await self._start_meter(job, expert)
        meter_token = set_meter(meter) if meter is not None else None

        async def heartbeat_loop() -> None:
            nonlocal cancelled, cap_exceeded
            while True:
                await asyncio.sleep(settings.WORKER_HEARTBEAT_INTERVAL)
                # The cap check rides the heartbeat: it is the one place that
                # already runs on a fixed cadence regardless of what stage the
                # build is in, so a runaway is stopped mid-stage rather than at
                # the next stage boundary.
                if meter is not None and meter.over_cap and not cap_exceeded:
                    cap_exceeded = True
                    if build_task is not None:
                        build_task.cancel()
                    return
                alive = await self._jobs.heartbeat(job.id, self.worker_id)
                if not alive:
                    cancelled = True
                    if build_task is not None:
                        build_task.cancel()
                    return

        hb_task = asyncio.create_task(heartbeat_loop())
        flush_task = (
            asyncio.create_task(flush_periodically(meter, self._persist_usage(meter)))
            if meter is not None
            else None
        )
        try:
            await expert_repo.update_status(expert.id, ExpertStatus.BUILDING)
            await expert_repo.reset_build_state(expert.id)
            await self._jobs.append_event(job.id, "build_started", {
                "type": "build_started",
                "attempt": job.attempts,
                "max_attempts": job.max_attempts,
            })

            async def on_event(event: dict[str, Any]) -> None:
                # Stage attribution for spend piggybacks on the progress events
                # the builder already emits, so no builder change is needed.
                if meter is not None:
                    meter.observe_event(event)
                await self._jobs.append_event(job.id, event["type"], event)

            builder = self._builder_factory(job.source_filter)
            build_task = asyncio.create_task(builder.build(expert, on_event=on_event))
            try:
                result: BuildResult = await build_task
            except asyncio.CancelledError:
                if cap_exceeded:
                    raise SpendCapExceeded(
                        meter.spent_usd if meter else 0.0,
                        float(meter.cap_usd) if meter and meter.cap_usd else 0.0,
                    ) from None
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
            # The build produced a usable expert, so the hold stands. Record what
            # it actually cost against the ledger entry for reporting.
            if meter is not None:
                with suppress(Exception):
                    await self._entitlements.settle_job(job.id, meter.spent_usd)
            logger.info(
                "Job %d succeeded (expert=%d, cost=$%.4f)",
                job.id, job.expert_id, meter.spent_usd if meter else 0.0,
            )

        except SpendCapExceeded as exc:
            await self._on_cap_exceeded(job, expert_repo, exc)
        except _JobCancelled:
            await self._on_cancelled(job, expert_repo)
        except asyncio.CancelledError:
            # Graceful shutdown: return the job to the queue for another worker.
            # The hold stays — the job is still going to run.
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
            if flush_task is not None:
                flush_task.cancel()
                with suppress(asyncio.CancelledError):
                    await flush_task
            # Final flush: whatever the build spent in its last few seconds must
            # still be recorded, including on the failure and cancellation paths.
            if meter is not None:
                with suppress(Exception):
                    await flush_once(meter, self._persist_usage(meter))
            if meter_token is not None:
                reset_meter(meter_token)

    async def _run_ingest_job(self, job: BuildJob, expert) -> None:
        """Ingest one user-supplied document.

        Shares the queue's durability with a build — claimed, heartbeaten,
        retried, reaped — and nothing else. In particular it never moves the
        expert out of ``ready``: an upload is added *to* a working expert, and a
        document that fails to parse is not a reason to take that expert offline.
        There is no metering and no credit hold either; see UPLOAD_PLAN.md.
        """
        upload_id = (job.payload or {}).get("upload_id")
        if not isinstance(upload_id, int):
            await self._jobs.mark_failed(
                job.id, self.worker_id, "Ingest job has no upload_id"
            )
            return

        cancelled = False
        ingest_task: asyncio.Task[Any] | None = None

        async def heartbeat_loop() -> None:
            nonlocal cancelled
            while True:
                await asyncio.sleep(settings.WORKER_HEARTBEAT_INTERVAL)
                if not await self._jobs.heartbeat(job.id, self.worker_id):
                    cancelled = True
                    if ingest_task is not None:
                        ingest_task.cancel()
                    return

        hb_task = asyncio.create_task(heartbeat_loop())
        try:
            await self._jobs.append_event(job.id, "build_started", {
                "type": "build_started",
                "kind": "ingest_source",
                "attempt": job.attempts,
                "max_attempts": job.max_attempts,
            })

            async def on_event(event: dict[str, Any]) -> None:
                await self._jobs.append_event(job.id, event["type"], event)

            ingest_task = asyncio.create_task(
                ingest_upload(self._pool, expert, upload_id, on_event=on_event)
            )
            try:
                summary = await ingest_task
            except asyncio.CancelledError:
                if cancelled:
                    raise _JobCancelled from None
                raise  # worker shutdown — propagate so _drain requeues it

            await self._jobs.append_event(job.id, "done", summary_event(summary))
            await self._jobs.mark_succeeded(job.id, self.worker_id)
            logger.info(
                "Ingest job %d succeeded (expert=%d, upload=%d)",
                job.id, job.expert_id, upload_id,
            )

        except _JobCancelled:
            await self._jobs.append_event(job.id, "cancelled", {
                "type": "cancelled", "message": "Upload cancelled",
            })
            logger.info("Ingest job %d cancelled", job.id)
        except asyncio.CancelledError:
            await self._jobs.release_for_shutdown(job.id, self.worker_id)
            logger.info("Ingest job %d released back to queue (shutdown)", job.id)
            raise
        except IngestionError as exc:
            # A document we genuinely cannot read. Retrying will not change that,
            # so fail it now with the message written for the person who
            # uploaded it rather than burning the retry budget.
            await self._jobs.append_event(job.id, "error", {
                "type": "error", "message": str(exc),
            })
            await self._jobs.mark_failed(job.id, self.worker_id, str(exc))
            logger.info("Ingest job %d rejected: %s", job.id, exc)
        except Exception as exc:
            # Anything else (a provider blip, a dropped connection) is worth
            # another attempt on the normal backoff.
            logger.exception("Ingest job %d failed", job.id)
            await self._fail_or_retry_ingest(job, exc)
        finally:
            if ingest_task is not None and not ingest_task.done():
                ingest_task.cancel()
                with suppress(asyncio.CancelledError):
                    await ingest_task
            hb_task.cancel()
            with suppress(asyncio.CancelledError):
                await hb_task

    async def _fail_or_retry_ingest(self, job: BuildJob, exc: Exception) -> None:
        message = f"{type(exc).__name__}: {exc}"
        if job.attempts < job.max_attempts:
            backoff = settings.WORKER_BACKOFF_BASE * (2 ** (job.attempts - 1))
            logger.warning(
                "Ingest job %d attempt %d/%d failed (%s) — retrying in %.0fs",
                job.id, job.attempts, job.max_attempts, message, backoff,
            )
            await self._jobs.requeue(job.id, self.worker_id, message, backoff)
            return
        await self._jobs.append_event(job.id, "error", {
            "type": "error", "message": message,
        })
        await self._jobs.mark_failed(job.id, self.worker_id, message)

    async def _start_meter(self, job: BuildJob, expert) -> "BuildMeter | None":
        """Build the cost meter for a job, or None if metering can't be set up.

        Metering is observability plus a safety valve — never a reason a build
        fails to start. Any problem here degrades to an unmetered build.
        """
        try:
            install_instrumentation()
            tier = ExpertTier(job.tier) if job.tier else expert.tier
            cap = await self._entitlements.cap_for_build(expert.owner_id or "", tier)
            # The cap is always snapshotted onto the job, so spend stays readable
            # against the ceiling that applied. Whether it is *armed* is separate:
            # in observe-only mode the meter carries no cap and never aborts.
            await self._entitlements.record_job_cap(job.id, cap)
            return BuildMeter(
                job_id=job.id,
                expert_id=expert.id,
                owner_id=expert.owner_id,
                cap_usd=cap if billing_settings.SPEND_CAP_ENFORCED else None,
            )
        except Exception as exc:
            logger.warning("Could not start cost metering for job %d: %s", job.id, exc)
            return None

    def _persist_usage(self, meter: "BuildMeter"):
        repo = BillingRepository(self._pool)

        async def persist(rows) -> None:
            await repo.record_usage(meter.job_id, meter.expert_id, meter.owner_id, rows)

        return persist

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
        # A cancelled build leaves nothing usable behind, so it is not charged.
        with suppress(Exception):
            await self._entitlements.refund_job(job.id, "Build cancelled")

    async def _on_cap_exceeded(
        self, job: BuildJob, expert_repo: ExpertRepository, exc: SpendCapExceeded
    ) -> None:
        """Terminal: stop, keep the evidence, refund the credit.

        Deliberately *not* retryable. A retry would re-spend the same money on
        the same corpus and hit the same ceiling, so the job is failed outright
        even with attempts remaining. The user is refunded in full — they have no
        usable expert — and the overspend stays visible in build_usage_events.
        """
        message = str(exc)
        logger.error("Job %d aborted on spend cap: %s", job.id, message)
        with suppress(Exception):
            await BillingRepository(self._pool).mark_cap_exceeded(job.id)
        with suppress(Exception):
            await expert_repo.update_status(job.expert_id, ExpertStatus.FAILED, message)
        with suppress(Exception):
            await self._jobs.append_event(job.id, "error", {
                "type": "error",
                "message": message,
                "code": "spend_cap_exceeded",
                "spent_usd": round(exc.spent_usd, 4),
                "cap_usd": exc.cap_usd,
            })
        await self._jobs.mark_failed(job.id, self.worker_id, message)
        with suppress(Exception):
            await self._entitlements.refund_job(job.id, "Build exceeded its spend cap")

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
            # No usable expert was produced, so the hold is returned. A retry
            # inside the same job keeps its hold, so a build that eventually
            # succeeds is charged exactly once.
            with suppress(Exception):
                await self._entitlements.refund_job(job.id, f"Build failed: {message[:200]}")
            await expert_repo.update_status(job.expert_id, ExpertStatus.FAILED, message)
            await self._jobs.append_event(job.id, "error", {
                "type": "error", "message": message,
            })
            await self._jobs.mark_failed(job.id, self.worker_id, message)
