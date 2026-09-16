# Development

How to get Peritus running locally, what the checks are, and the conventions that will bite you if
you do not know them.

## Prerequisites

| | |
|---|---|
| Python | 3.12+ |
| Node.js | 22+ |
| Rust | stable (only for the TUI) |
| PostgreSQL | 17 with `pgvector` |
| [`just`](https://github.com/casey/just) | runs every task in this repository |
| [`hivemind`](https://github.com/DarthSim/hivemind) | runs the multi-process dev stack (`just dev`) |
| [`uv`](https://docs.astral.sh/uv/) | what CI installs with; optional locally, required to change dependencies |

You need an `ANTHROPIC_API_KEY` and an `OPENAI_API_KEY` to build anything. `COHERE_API_KEY` is
strongly recommended: without it every chat question falls back to roughly seven windowed Haiku
calls per retrieval pass, which is both slower and worse than Cohere's reranker at about $2 per
1,000 searches.

## Database

Peritus needs Postgres with the `pgvector` extension — the schema declares vector columns, so a
plain `postgres` image will not do.

```bash
docker run -d --name peritus-db \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=peritus \
  -p 5432:5432 pgvector/pgvector:pg17
```

`docker-compose.yml` at the repository root brings up the API and worker against it.

## First run

```bash
cp api/.env.example api/.env        # DATABASE_URL + API keys
cp web/.env.example web/.env.local

cd api && pip install -e ".[dev]" && python migrations/apply.py && cd ..
cd web && npm ci && cd ..

just dev-solo                       # API + in-process worker, :8000
just web                            # Next.js, :3000
```

With no Supabase settings the API runs in **open dev mode**: no login, every request acts as
`BOOTSTRAP_ADMIN_EMAIL`.

### Something must run a build worker

Builds execute in a durable Postgres-backed job queue. Without a worker they enqueue and sit there,
which looks exactly like a hang at the first pipeline stage.

| Command | Shape |
|---|---|
| `just dev-solo` | API with a worker inside the same process. Simplest |
| `just dev` | API and worker as separate processes, via hivemind. What production looks like |
| `just api` | API only. Builds queue and never run |
| `just worker` | A standalone worker, to run beside `just api` |

## The task runner

```bash
# API
just dev / dev-solo / api / worker    # run it
just migrate                          # apply migrations
just lint                             # ruff check, ruff format --check, mypy
just test                             # pytest
just test-db [url]                    # pytest with the DB-backed tests enabled

# Web
just web                              # dev server
just lint-web                         # prettier + eslint + tsc + vitest — exactly the web CI job
just build-web                        # next build
just e2e-web                          # Playwright, all seven device projects
just e2e-web-fast                     # desktop only, for a fast loop
just lighthouse-web                   # performance budgets

# CLI
just lint-cli                         # cargo fmt --check + clippy -D warnings + cargo test
just build-cli / run-cli

# Everything
just format                           # write ruff format, prettier and cargo fmt
just check                            # every check CI runs, except the DB tests
```

## Formatting

Three formatters, one 100-column budget: **ruff format** for Python, **rustfmt** for Rust,
**Prettier** for the web app (no semicolons, single quotes, Tailwind classes sorted). `.editorconfig`
carries the shared whitespace rules for everything else.

`just format` writes all three. The checks live with each language's lint recipe (`just lint`,
`just lint-web`, `just lint-cli`), which is exactly what CI runs. Nothing here is discretionary — if
the formatter disagrees with you, the formatter is right.

Install the hooks once per clone so a commit cannot introduce noise:

```bash
uvx pre-commit install     # or: pipx install pre-commit && pre-commit install
```

`.pre-commit-config.yaml` runs the three formatters, `ruff check --fix`, whitespace and
large-file checks, and **gitleaks** over the staged files. It uses the repository's own pinned
Prettier and rustfmt, so a hook and CI can never run different versions.

## Adding a setting

Two places, always: the field on `Settings` in `api/src/peritus/core/config.py` with the comment
that explains it, and the same key in `api/.env.example` with the same comment.
`tests/unit/test_env_example.py` fails if you do one without the other, or if the two defaults
disagree. Enum-valued settings get a `Literal` type so a typo fails at startup rather than silently
falling back at the point of use. `just settings` prints the current list.

## Tests

**Python.** `just test` runs pytest. The DB-backed tests — job queue claim/heartbeat/reap,
conversation persistence, credit arithmetic, expert visibility, source uploads — **skip silently**
without `PERITUS_TEST_DATABASE_URL`. To run them:

```bash
just test-db postgresql://postgres:postgres@localhost:5432/peritus_test
```

> The fixture runs `TRUNCATE … RESTART IDENTITY CASCADE`. **Never point that variable at a database
> you care about**, and never at production.

**Web.** `npx vitest run` covers the SSE frame parser, the build-event reducer, the proxy's
refresh-once and dead-refresh paths, cookie shaping, formatting and the avatar resolver. The
fixture tests are the schema check: there is no codegen between the Python schemas and
`web/lib/api/types.ts`, so a payload that drifts fails there rather than in a user's browser.

**End to end.** Playwright runs seven projects — desktop, laptop, two iPads, an iPhone, a Pixel and
a reduced-motion pass — against the mock API in `web/e2e/mock-api`, which serves captured fixtures
and streams real SSE with real `id:` cursors. A real build costs money and takes minutes, so it can
never be what CI runs against. `playwright.config.ts` starts both servers itself, but it needs a
build: run `just build-web` after changing anything.

**Rust.** CI runs `cargo check --locked`.

## What CI runs

Six jobs on every pull request, and `deploy.yml` calls the same workflow on every push to `main`, so
nothing reaches production without passing it.

| Job | What |
|---|---|
| `api` | ruff, `ruff format --check`, mypy, `pip-audit` on the production lock, migrations, pytest against a real `pgvector/pgvector:pg17` service with a 67% coverage floor, and a CLI smoke check |
| `api-image` | Builds the production Dockerfile and runs it the way Fly does: migrations twice (the second must be a no-op), `/health` and `/ready`, and the worker's SIGTERM drain (must exit 0) |
| `web` | eslint, `prettier --check`, `tsc --noEmit`, `npm audit --audit-level=high`, vitest, `next build` |
| `web-e2e` | Playwright across seven device profiles |
| `web-lighthouse` | LCP < 2.5s, CLS < 0.1, TBT < 200ms, on public and authenticated pages |
| `cli` | `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test`, `cargo audit` |

Every job has a `timeout-minutes`, and a pull request touching only `docs/**` or
`**/*.md` runs none of them — a push to `main` still runs the full suite, because
that is the gate production depends on.

`just check` runs everything except the DB tests and the audits; `just audit`
runs those three separately, since they fail on the world changing rather than on
this repository changing.

The coverage floor is a ratchet. Raise it when coverage rises; never lower it to
make a red run green.

## Conventions that matter

**`null` is never zero.** Any count the system did not record is `null` with a reason. A fabricated
zero in an evidence record is worse than a visible gap — this holds from the database through the
API to the rendered page.

**Readiness gates chat, not status.** An expert answers from `chat_ready`, a stage before its build
job finishes. Anything that reads `status` to decide whether chat is available hides a working
expert for the length of graph extraction.

**Enrichment degrades, it does not destroy.** Graph extraction and persona failures emit
`stage_degraded` and leave an answerable expert. Only corpus assembly can fail a build, and a failed
build refunds its credit hold in full.

**A closed SSE stream is not a finished build.** Only `done`, `error` or `cancelled` is terminal.

**Migrations are forward-only** and applied in one transaction with their `_migrations` row. They
run as Fly's `release_command` on every deploy, so a migration that is not backwards-compatible
with the currently-running code is an outage.

**Dependencies are locked.** After changing `api/pyproject.toml`, run `uv lock` in `api/` and commit
the lock — CI's `uv lock --check` fails otherwise.

**Prices live in code, not the database.** `billing/domain.py` and `experts/domain.py` hold plans
and tier economics so they are reviewable in a diff. `ExpertConfig` is snapshotted into
`experts.config` at create time, so adding a field there needs a default that makes an existing row
build the way it always did.

## Where to read next

- [README.md](README.md) — the whole system, end to end. Start here
- [build-flow.md](build-flow.md) — the pipeline stage by stage
- [api-reference.md](api-reference.md) — endpoints, auth, SSE, error shapes
- [configuration.md](configuration.md) — settings and where they live
- [`web/AGENTS.md`](../web/AGENTS.md) — the web app's conventions and its accumulated gotchas
- [deployment.md](deployment.md) — how this reaches production
