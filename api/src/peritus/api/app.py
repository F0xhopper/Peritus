import hashlib
import secrets
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from peritus.infrastructure.database import close_pool, init_pool
from peritus.api.routes import health, experts, chat


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
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
