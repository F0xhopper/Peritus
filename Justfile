# ── API ──────────────────────────────────────────────────────────────────────

# Run the full local dev stack (API + build worker) via hivemind. This is the
# one you want: without the worker, builds stall at "Identifying key concepts…".
dev:
    hivemind Procfile.dev

# Run just the API (no worker — builds will queue but not run).
api:
    cd api && uvicorn peritus.api.app:app --reload --host 0.0.0.0 --port 8000

# Run a standalone build worker (production shape: API and worker as separate processes).
worker:
    cd api && python -m peritus.jobs.runner

# Run the API with an in-process build worker (single-process, no hivemind needed).
dev-solo:
    cd api && RUN_WORKER_IN_PROCESS=true uvicorn peritus.api.app:app --reload --host 0.0.0.0 --port 8000

test:
    cd api && python -m pytest

lint:
    cd api && ruff check src tests && mypy src

migrate:
    cd api && python migrations/apply.py

# ── CLI ──────────────────────────────────────────────────────────────────────

build-cli:
    cd cli && cargo build --release

run-cli:
    cd cli && cargo run

# ── Docker ───────────────────────────────────────────────────────────────────

docker-up:
    docker compose up --build -d

docker-down:
    docker compose down
