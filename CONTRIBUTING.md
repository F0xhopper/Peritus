# Contributing

Thanks for looking. Peritus is a personal project, but issues and pull requests are welcome.

> **No licence is granted.** This repository is public to be read; all rights are reserved. By
> opening a pull request you agree your contribution can be used under whatever licence the project
> eventually adopts. If that is a problem, open an issue first and we will sort it out before you
> write anything.

## Before you start

- **Open an issue first** for anything beyond a small fix. A lot of the design has reasoning behind
  it that is not obvious from the code, and it is cheaper to find that out before you build.
- **Read [docs/README.md](docs/README.md).** It is the whole system in one page and it will save you
  more time than it costs.
- **Set up locally with [docs/development.md](docs/development.md).**

## Getting set up

```bash
cp api/.env.example api/.env        # DATABASE_URL + ANTHROPIC_API_KEY + OPENAI_API_KEY
cp web/.env.example web/.env.local

cd api && pip install -e ".[dev]" && python migrations/apply.py && cd ..
cd web && npm ci && cd ..

just dev-solo        # API + worker, :8000
just web             # web app, :3000
```

## Before you push

```bash
just check           # ruff, mypy, pytest, eslint, tsc, vitest, next build
```

That is every check CI runs except the DB-backed tests and Rust. If you touched anything the
DB-backed tests cover — the job queue, conversations, credits, uploads, visibility — run them too:

```bash
just test-db postgresql://postgres:postgres@localhost:5432/peritus_test
```

The fixture `TRUNCATE`s. Never point that at a database you care about.

If you touched the web UI, also run `just build-web && just e2e-web`. The Playwright suite covers
seven device profiles including a reduced-motion pass, and it will catch a layout that breaks at
360px before a reviewer has to.

## What CI will check

Six jobs, all of which must pass: the Python suite against a real pgvector service, the production
Docker image run the way Fly runs it, the web app's lint/typecheck/tests/build, Playwright,
Lighthouse performance budgets, and `cargo check`. See
[docs/development.md](docs/development.md#what-ci-runs).

## Conventions

**Commit messages** are `type: imperative summary`, optionally scoped:

```
feat: share experts by link
fix(billing): forecast graph cost only for the chunks graph extraction reads
ci: pull Vercel settings over REST so a project token works
docs: …   refactor: …   test: …   web: …
```

Write the summary so it says what changed *and why it matters*, not just which file moved.

**Comments explain why, not what.** This codebase leans on comments that record the reasoning and
the failure that motivated a line — see `api/src/peritus/experts/domain.py` or `web/AGENTS.md` for
the house style. A comment that restates the code is noise; a comment that says "this was 2 and
every lite build died mid-graph" is the most valuable thing in the file.

**Match the surrounding code.** Naming, structure and comment density vary a little between
`api/`, `web/` and `cli/`. Follow whatever is already there.

## Things that will get a pull request sent back

These are invariants, not preferences. Each one has cost something already.

1. **Never coerce a missing count to zero.** `null` means "not recorded" and must render as a gap.
   A fabricated zero in an evidence record is worse than a visible hole.
2. **Never gate chat on build `status`.** Gate it on `readiness`. An expert answers from
   `chat_ready`, a whole stage before the build job finishes.
3. **Never let an enrichment failure fail a build.** Graph extraction and persona degrade
   (`stage_degraded`) and leave a working expert. Only corpus assembly can fail a build, and a
   failed build refunds its credit hold in full.
4. **Never treat a closed SSE stream as a finished build.** Only `done`, `error` or `cancelled` is
   terminal; anything else means reconnect from the cursor.
5. **Never add anything that implies payment.** There is no checkout. The only credit remedy in the
   product is "request credits".
6. **Never weaken the grounding contract.** A persona shapes voice and pedagogy; it can never relax
   the rule that substantive claims come from cited passages.
7. **Never write a backwards-incompatible migration.** They are forward-only and run as a release
   command on every deploy, against the previous version's code.

## Schema and API changes

There is no codegen between the Python schemas and the clients. A change to a response shape means:

- `web/lib/api/types.ts` and the fixtures in `web/tests/fixtures/` — the fixture tests are the
  schema check
- `cli/src/api/types.rs` for the Rust TUI
- a migration in `api/migrations/`, numbered, forward-only, backwards-compatible
- `uv lock` in `api/` if you changed `pyproject.toml`

## Reporting a security issue

Please do not open a public issue. See [SECURITY.md](SECURITY.md).
