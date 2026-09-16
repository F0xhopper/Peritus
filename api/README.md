# Peritus API

Python 3.12 / FastAPI. This one package is the whole backend: the HTTP API, the build pipeline, the
durable job worker, and a Python CLI. It ships as one Docker image running two commands.

For what the system does and why, start at [`../docs/README.md`](../docs/README.md).

## Entry points

| Command | What it is |
|---|---|
| `peritus` | The CLI — build, chat, sign in, manage experts, catalog and credits |
| `peritus-server` | The FastAPI server (uvicorn) |
| `peritus-worker` | The build worker: claims jobs from the queue and runs the pipeline |

## Setup

```bash
cp .env.example .env            # every setting is documented inline
pip install -e ".[dev]"
python migrations/apply.py
```

From the repository root, `just dev-solo` runs the server with a worker inside it, and `just dev`
runs them as two processes (the production shape).

## Layout

```
src/peritus/
  api/            FastAPI app, routes, schemas, JWT verification, rate limiting
  cli/            Typer CLI — build · chat · login · experts · catalog · credits
  core/           Settings and logging
  experts/        Build coordinator, tiers, coverage targets, composition, repository
  sources/        11 fetchers, triage, validation, canonical-work resolution, orientation
  ingestion/      Chunking, contextualisation, embedding
  graph/          Concept-graph extraction, entity resolution, retrieval
  search/         Hybrid semantic (pgvector) + keyword (Postgres FTS) search
  chat/           Grounded chat agent, the grounding contract, conversations
  billing/        Plans, the credit ledger, spend caps
  jobs/           Postgres job queue, worker, runner
  uploads/        User-supplied PDF / text / URL sources
  infrastructure/ Postgres pool, embeddings, reranker, Anthropic client, OCR, Wikimedia
  eval/           Offline golden-set harness and metrics
migrations/       Numbered SQL files + an idempotent apply.py
tests/            pytest
```

## Development

```bash
just lint        # ruff check src tests && mypy src
just test        # pytest
just test-db     # pytest with the DB-backed tests enabled
just migrate     # apply migrations
```

**The DB-backed tests skip silently without `PERITUS_TEST_DATABASE_URL`** — around 50 tests
covering the job queue, conversations, credits, uploads and visibility. CI provides a
`pgvector/pgvector:pg17` service so they always run there. The fixture `TRUNCATE`s: never point
that variable at a database you care about.

## Migrations

Numbered SQL files applied in order by `migrations/apply.py`, which records each in a `_migrations`
table inside the same transaction as the migration itself. It is idempotent, it runs as Fly's
`release_command` on every deploy, and CI exercises it twice per run (the second must be a no-op).

Migrations are **forward-only**. A rollback across a schema change needs that migration to have
been backwards-compatible.

`python migrations/apply.py --status` lists what has run and what is pending, and changes nothing.
A `pg_advisory_lock` around the apply loop means two runners cannot both decide the same file is
pending.

Thirteen of them (010, 013, 018, 024, 031, 032) migrate or delete **data**, not just schema. Those
rely on the transaction wrapper for idempotence: the `UPDATE` and the `INSERT INTO _migrations`
commit together, so a crash rolls both back and the next run repeats the whole thing from a
consistent state. A data migration that is not safe to re-run from scratch does not belong here.
032 is stricter again — it drops the pre-expert tables, so it refuses and aborts the release if any
of them still holds a row.

## Dependencies are locked

`uv.lock` pins every package. The image installs it with `uv sync --frozen` and CI tests the same
set, so a deploy can never pick up a new major release of an SDK that nobody ran. After changing
`pyproject.toml`, run `uv lock` here and commit the lock — CI's `uv lock --check` fails otherwise.

## Configuration

Every setting lives in [`.env.example`](.env.example) with a comment explaining what it does and
what breaks if it is wrong. The ones worth knowing before you start are summarised in
[`../docs/configuration.md`](../docs/configuration.md).
