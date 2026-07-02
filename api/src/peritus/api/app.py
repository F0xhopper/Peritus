import asyncio
import hashlib
import secrets
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from peritus.api.routes import chat, experts, health
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.database import close_pool, get_pool, init_pool

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = settings.check_required_vars()
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Copy api/.env.example to api/.env and fill them in."
        )
    await init_pool()

    worker = None
    worker_task = None
    if settings.RUN_WORKER_IN_PROCESS:
        # Convenience for local/single-node dev: run a build worker alongside the API.
        # In production, run `peritus-worker` as its own process instead.
        from peritus.jobs.worker import BuildWorker

        worker = BuildWorker(get_pool())
        worker_task = asyncio.create_task(worker.run())
        logger.info("In-process build worker started (RUN_WORKER_IN_PROCESS=true)")

    try:
        yield
    finally:
        if worker is not None and worker_task is not None:
            worker.request_stop()
            with suppress(asyncio.CancelledError):
                await worker_task
        await close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="Peritus API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(experts.router)
    app.include_router(chat.router)
    return app


app = create_app()


def start() -> None:
    uvicorn.run("peritus.api.app:app", host="0.0.0.0", port=8000, reload=False)


def keygen() -> None:
    """Print a new API key + its SHA-256 hash."""
    key = "prt_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    print(f"API Key:  {key}")
    print(f"Key Hash: {key_hash}")
    print("\nAdd to .env:")
    print(f"PERITUS_API_KEY_HASH={key_hash}")
