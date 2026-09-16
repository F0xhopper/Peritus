# Configuration

Where settings live, and the ones worth understanding before you change them.

## Where settings live

| Component | File | Loaded by |
|---|---|---|
| API + worker | `api/.env` (template: [`api/.env.example`](../api/.env.example)) | `api/src/peritus/core/config.py` |
| Web app | `web/.env.local` (template: [`web/.env.example`](../web/.env.example)) | Next.js |
| Rust TUI | `~/.config/peritus/config.toml`, written by the TUI itself | `cli/src/config/` |
| Production (API) | `api/fly.toml` `[env]` for non-secrets, Fly secrets for credentials | Fly.io |
| Production (web) | Vercel project settings | Vercel |

**[`api/.env.example`](../api/.env.example) is the reference.** Every setting there carries a
comment explaining what it does and what breaks if it is wrong, and it is kept current with the
code. This page does not repeat it — it covers the decisions behind the settings you are most
likely to reach for.

Prices, plans and tier depths are deliberately **not** environment settings. They live in
`api/src/peritus/billing/domain.py` and `api/src/peritus/experts/domain.py` so they are reviewable
in a diff.

## The minimum to run

```bash
DATABASE_URL=postgresql://user:password@localhost:5432/peritus
ANTHROPIC_API_KEY=sk-ant-...        # all reasoning: plan, triage, validate, graph, persona, chat
OPENAI_API_KEY=sk-...               # embeddings only
```

That is enough to build and chat. Everything else has a working default.

## Provider keys

| Key | Without it |
|---|---|
| `ANTHROPIC_API_KEY` | Nothing works |
| `OPENAI_API_KEY` | Nothing embeds, so nothing is retrievable |
| `COHERE_API_KEY` | **Strongly recommended.** Every chat question falls back to ~7 windowed Haiku calls per retrieval pass, up to twice per question. Cohere rerank is cheaper (~$2 per 1K searches) *and* better |
| `EXA_API_KEY` | The Exa neural-search and YouTube channels find nothing |
| `MISTRAL_API_KEY` | PDFs that need OCR are skipped |
| `S2_API_KEY` | The PDF fetcher and citation snowballing share an unauthenticated Semantic Scholar pool that rate-limits hard |
| `PERITUS_CONTACT` | Wikimedia's API policy asks for a contact in the User-Agent, for expert pictures |

## Models

| Setting | Used for | Default |
|---|---|---|
| `CLAUDE_MODEL` | Chat composition and persona | `claude-sonnet-5` |
| `PLAN_MODEL` | The research brief. Empty follows `CLAUDE_MODEL` — one call per build that shapes the whole corpus, so it is deliberately not the fast model | `CLAUDE_MODEL` |
| `FAST_MODEL` | Triage, validation, contextualisation, coverage | `claude-haiku-4-5-20251001` |
| `GRAPH_MODEL` | Graph extraction | `claude-haiku-4-5-20251001` |
| `EMBED_MODEL` / `EMBED_DIM` | Embeddings | `text-embedding-3-large` / `3072` |

Changing `EMBED_MODEL` or `EMBED_DIM` invalidates every existing embedding. There is no migration
path short of rebuilding.

## Cost

Builds route through the **Anthropic Message Batches API at half price** where a stage has enough
requests to batch, at the cost of wall-clock time (a batch can queue for up to an hour per stage).

`BUILD_EXECUTION_DEFAULT` decides which builds do that:

| Value | Behaviour |
|---|---|
| `auto` (default) | The first build of an expert runs live — a person is watching it. Rebuilds and refreshes batch |
| `interactive` | Everything runs live: fastest, full price |
| `background` | Everything batches: cheapest, hours of wall clock |

Per-build **spend caps** are hard ceilings enforced by the meter at runtime. A build that crosses
one is aborted terminally and its credit hold refunded in full. Defaults are $3 / $6 / $12 for
lite / standard / pro, overridable per deployment with `PERITUS_TIER_CAP_{LITE,STANDARD,PRO}_USD`.
They are a safety valve against a runaway, not a budget — they sit well above the cost of a healthy
build. Setting them too low kills every build mid-graph, which is exactly what an earlier 1/3/8
ladder did.

The **discovery budget** (`PERITUS_TIER_DISCOVERY_*_USD`) is different: a soft target the discovery
loop spends *towards* and its stop condition, sized to leave room for graph extraction and persona
after it.

## Auth

Set `SUPABASE_URL`, `SUPABASE_ANON_KEY` and `BOOTSTRAP_ADMIN_EMAIL` to require login. Add
`SUPABASE_JWT_SECRET` only if the project has not migrated to asymmetric signing keys.

With none of these set the server runs in **open dev mode**: no login, every request acts as the
bootstrap admin.

> **In production, set `PERITUS_ENV=production`.** The server then refuses to start with auth
> disabled, so a missing `SUPABASE_URL` can never silently drop every request into admin mode. This
> is the single most important setting on this page.

`AUTH_ALLOW_SIGNUP=false` makes the deployment invite-only: unknown emails cannot self-provision,
and users are added from the Supabase dashboard.

One-time Supabase setup: the *Magic Link* email template must include `{{ .Token }}` (a six-digit
code), because the TUI and CLI verify the code directly rather than following a link. For Google
SSO, `<NEXT_PUBLIC_APP_URL>/api/auth/callback` must be in the redirect allowlist, matching the
scheme and port exactly.

## The worker

Builds run in a durable Postgres-backed queue, so something must run a worker.

| Setting | Meaning |
|---|---|
| `RUN_WORKER_IN_PROCESS` | Run a worker inside the API process. Local dev only; production runs `peritus-worker` separately |
| `WORKER_CONCURRENCY` | Concurrent builds per worker process |
| `WORKER_HEARTBEAT_INTERVAL` / `WORKER_STALE_TIMEOUT` | How a crashed worker's jobs are detected and reclaimed |
| `WORKER_MAX_ATTEMPTS` / `WORKER_BACKOFF_BASE` | Retries before permanent failure, and the backoff |

A single process serving API traffic *and* running builds needs `DB_POOL_MAX_SIZE` raised alongside
`WORKER_CONCURRENCY`.

## Two settings that are correctness, not tuning

**`HNSW_ITERATIVE_SCAN`** (default `relaxed_order`) decides how a filtered HNSW scan behaves when
the `expert_id` filter rejects most of what the index returns. `off` **silently truncates
results** — 40 rows measured for a 184-chunk expert. Leave it alone unless you know why you are
changing it.

**`CHAT_HISTORY_TRIM_BLOCK`** (default 6) exists for the prompt cache. Trimming one message per
turn moves the cached prefix every turn so it never hits, exactly when a conversation is long
enough for caching to be worth anything. Dropping in blocks holds the prefix still for half a block
of turns.

## Web app

Two settings, both in [`web/.env.example`](../web/.env.example):

- **`PERITUS_API_URL`** — the FastAPI backend. Server-only on purpose: the browser never talks to
  the API directly, which is what lets the API keep CORS closed. Naming it `NEXT_PUBLIC_*` would
  defeat the backend-for-frontend design.
- **`NEXT_PUBLIC_APP_URL`** — this app's own public origin, used to build the Google OAuth redirect.
  It is inlined at build time, so changing it needs a redeploy.

## Production

Non-secret API settings are reviewed in git (`api/fly.toml` `[env]`); credentials are Fly secrets. A
secret overrides an `[env]` entry of the same name, so do not set both. Full detail, including the
GitHub secrets the pipeline needs, is in [deployment.md](deployment.md).
