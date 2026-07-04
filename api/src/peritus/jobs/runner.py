"""Standalone worker entrypoint: `peritus-worker`."""

import asyncio
import signal
from contextlib import suppress

from peritus.core.logging import get_logger, setup_logging
from peritus.infrastructure.database import close_pool, get_pool, init_pool
from peritus.jobs.worker import BuildWorker

logger = get_logger(__name__)


async def _run() -> None:
    from peritus.core.config import settings

    # The worker is its own process, so it must configure logging itself —
    # otherwise its logger.* calls fall back to Python's unconfigured root
    # (WARNING-only, unformatted) and INFO build progress is lost.
    setup_logging(settings.LOG_LEVEL, log_file=settings.LOG_FILE or None)

    missing = settings.check_required_vars()
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Copy api/.env.example to api/.env and fill them in."
        )
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
