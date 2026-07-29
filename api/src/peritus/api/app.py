import asyncio
import hashlib
import secrets
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from peritus.api.middleware import RequestContextMiddleware, install_error_handlers
from peritus.api.routes import audit, auth, chat, conversations, experts, health, sources
from peritus.core.config import settings
from peritus.core.logging import get_logger, setup_logging
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

    # Fail closed in production: never let a missing SUPABASE_URL silently disable
    # auth and run every request as the bootstrap admin.
    if settings.IS_PRODUCTION and not settings.AUTH_ENABLED:
        raise RuntimeError(
            "PERITUS_ENV=production but auth is not configured. Set SUPABASE_URL "
            "(and SUPABASE_ANON_KEY) or unset PERITUS_ENV for local development."
        )
    if not settings.AUTH_ENABLED:
        logger.warning(
            "AUTH DISABLED (dev mode): every request runs as the bootstrap admin. "
            "Set SUPABASE_URL to require login."
        )
    elif not settings.SUPABASE_ANON_KEY:
        logger.warning(
            "SUPABASE_URL is set but SUPABASE_ANON_KEY is not — login (/auth) will "
            "be unavailable. Also ensure the Supabase Magic Link email template "
            "includes {{ .Token }} so users receive a 6-digit code."
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
    # Uvicorn's own logging config is disabled (log_config=None in start()) so this
    # is the only place logging gets configured; skipping it left every logger.*
    # call in this app using Python's default (unformatted, no file handler) setup.
    setup_logging(settings.LOG_LEVEL, log_file=settings.LOG_FILE or None)

    app = FastAPI(title="Peritus API", version="1.0.0", lifespan=lifespan)
    # Order matters: middleware added last runs first, so the request id is bound
    # before CORS and is therefore available on every log line and error body,
    # including the ones CORS itself produces.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
        # Browser clients read the id off a failed response to report it.
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(experts.router)
    app.include_router(chat.router)
    app.include_router(conversations.router)
    app.include_router(audit.router)
    app.include_router(sources.router)
    return app


app = create_app()


def start() -> None:
    # log_config=None keeps uvicorn from installing its own dictConfig over ours.
    uvicorn.run("peritus.api.app:app", host="0.0.0.0", port=8000, reload=False, log_config=None)


def keygen() -> None:
    """Print a new API key + its SHA-256 hash."""
    key = "prt_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    print(f"API Key:  {key}")
    print(f"Key Hash: {key_hash}")
    print("\nAdd to .env:")
    print(f"PERITUS_API_KEY_HASH={key_hash}")
