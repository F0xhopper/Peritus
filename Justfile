# ── API ──────────────────────────────────────────────────────────────────────

dev:
    cd api && uvicorn peritus.api.app:app --reload --host 0.0.0.0 --port 8000

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
