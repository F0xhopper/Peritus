"""Standalone worker entrypoint: `peritus-worker`."""

import asyncio
import signal
from contextlib import suppress

from peritus.core.logging import get_logger
from peritus.infrastructure.database import close_pool, get_pool, init_pool
from peritus.jobs.worker import BuildWorker

logger = get_logger(__name__)


async def _run() -> None:
    await init_pool()
    worker = BuildWorker(get_pool())

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):  # e.g. Windows
            loop.add_signal_handler(sig, worker.request_stop)

    try:
        await worker.run()
    finally:
        await close_pool()


def worker_main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    worker_main()
