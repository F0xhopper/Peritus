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

# The 54 DB-backed tests (job queue, conversations, credits, uploads, visibility)
# skip unless PERITUS_TEST_DATABASE_URL points at a scratch pgvector database.
# Never point it at a database you care about: the fixture TRUNCATEs.
test-db url="postgresql://postgres:postgres@localhost:5432/peritus_test":
    cd api && PERITUS_TEST_DATABASE_URL={{url}} DATABASE_URL={{url}} python migrations/apply.py
    cd api && PERITUS_TEST_DATABASE_URL={{url}} python -m pytest

lint:
    cd api && ruff check src tests && ruff format --check src tests && mypy src

migrate:
    cd api && python migrations/apply.py

# Every setting, its type and its default, as a Markdown table.
settings:
    cd api && python scripts/settings_reference.py

# ── Web ──────────────────────────────────────────────────────────────────────

web:
    cd web && npm run dev

# Exactly what the `web` CI job runs, so a green local run means a green CI run.
lint-web:
    cd web && npx prettier --check . && npx eslint . && npx tsc --noEmit && npx vitest run

build-web:
    cd web && npx next build

# The browser suite, across all seven device projects. Starts the mock API and
# `next start` itself, so there is nothing to set up first — but it needs a
# build, so run `build-web` after changing anything.
e2e-web:
    cd web && npx playwright test

# One project only, for a fast loop while working on a page.
e2e-web-fast:
    cd web && npx playwright test --project=desktop

# The performance budgets (web-design.md §9), on the public pages and on the app
# pages with a session. Needs a build, like `e2e-web`.
lighthouse-web:
    cd web && npm run lighthouse

# ── Everything ───────────────────────────────────────────────────────────────

# Write every formatter's output. `just lint` and `lint-web` check the same
# three; CI checks them too, so this is the fix for a red format gate.
format:
    cd api && ruff format src tests
    cd web && npx prettier --write .
    cd cli && cargo fmt

# The dependency audits CI runs, for all three ecosystems. Separate from
# `check` because they hit the network and fail on the world changing rather
# than on this repository changing.
audit:
    cd api && uv export --frozen --no-dev --no-hashes --no-emit-project -o /tmp/peritus-audit.txt && uvx pip-audit -r /tmp/peritus-audit.txt
    cd web && npm audit --audit-level=high
    cd cli && cargo audit

# Every check CI runs, except the DB-backed tests (see `test-db`) and the audits.
check: lint test lint-web build-web lint-cli

# ── CLI ──────────────────────────────────────────────────────────────────────

# Exactly what the `cli` CI job runs.
lint-cli:
    cd cli && cargo fmt --check && cargo clippy --locked --all-targets -- -D warnings && cargo test --locked

build-cli:
    cd cli && cargo build --release

run-cli:
    cd cli && cargo run

# ── Docker ───────────────────────────────────────────────────────────────────

docker-up:
    docker compose up --build -d

docker-down:
    docker compose down
