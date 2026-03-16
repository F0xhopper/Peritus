from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.logger import configure_logging, get_logger
from interfaces.api.routers import chat, courses, experts

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "peritus_starting",
        host=settings.host,
        port=settings.port,
        model=settings.anthropic_model,
    )
    yield
    logger.info("peritus_shutdown")


app = FastAPI(
    title="Peritus",
    description="Domain-expert-first learning system with graph-grounded AI.",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(experts.router)
app.include_router(courses.router)
app.include_router(chat.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "peritus"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level="info",
    )
