# Peritus — Application Evaluation

**Date:** 2026-07-29
**Commit:** `a6d3836` (main, with ~2,600 uncommitted lines in the working tree)
**Scope:** Backend, build pipeline, retrieval, data layer, frontend, CI/CD. Security explicitly out of scope per request.

---

## ⚠️ Read this first — how complete this evaluation is

This was planned as a seven-agent parallel sweep. **All seven agents were terminated by an API session limit within a few minutes of launch**, before any produced a report. What follows is a single-threaded evaluation I ran directly.

Every finding below is **verified by reading the code or running the command**, with file:line evidence. Nothing here is inferred or assumed. But the coverage is uneven, and you should know where:

| Area | Depth |
|---|---|
| Test / CI / build health | ✅ Thorough — commands run |
| Retrieval SQL, RRF, hybrid search | ✅ Thorough — read in full |
| Vector & FTS indexing, migration 019 | ✅ Thorough |
| Deployment & migration path | ✅ Thorough |
| Citation resolution / grounding | ✅ Thorough |
| Prompt caching | ✅ Thorough |
| Config vs `.env.example` | ✅ Thorough — mechanically diffed |
| Job queue semantics | 🟡 Moderate — claim/heartbeat/reap read, not exhaustive |
| Source validation robustness | 🟡 Moderate |
| Frontend (build, boundaries, tokens, contract) | 🟡 Moderate — spot-checked, not page-by-page |
| **Rust CLI (`cli/`)** | ❌ **Not evaluated** |
| **UI/UX + accessibility, page-by-page** | ❌ **Not evaluated** |
| **Billing / metering arithmetic** | ❌ **Not evaluated** |
| **Graph extraction & node dedup merge** | ❌ **Not evaluated** |
| **Per-fetcher failure modes** | ❌ **Not evaluated** |
| **Chat stream claim/interrupt logic** | ❌ **Not evaluated** |

The unevaluated rows are not "probably fine" — they are unexamined. Billing arithmetic and the graph dedup merge in particular are the two I would prioritise next, because both can silently produce wrong results that no test would catch.

---

## Summary

**Overall grade: B.** The engineering quality of the code I read is genuinely high — well above typical for a project at this stage. The retrieval SQL, the job queue, and migration 019 are the work of someone who understands the systems they are building on, and the code comments explain *why* rather than *what*. That is rare and worth preserving.

The problems are almost entirely **at the seams, not in the code**: what ships, what CI actually checks, and whether the docs describe the product that exists. The single most serious finding is that **database migrations are never applied on deploy** — which means the flagship performance fix in migration 019 is probably not live in production.

**Biggest risk:** the gap between the code's quality and the delivery pipeline's rigour. The code is A-grade; the pipeline around it is C-grade, and the pipeline is what determines what users actually get.

---

## Critical findings

### C1. Migrations are never applied on deploy — production may be running an un-migrated schema

**Evidence:**
- `api/fly.toml` — no `release_command` (verified: `grep -c release_command` → `0`)
- `.github/workflows/deploy.yml` — runs `flyctl deploy` only; no migration step
- `api/Dockerfile` — no migration on start
- `Justfile:migrate` exists but is a manual, local-only target

Deploy applies code. Nothing applies schema. Every deploy assumes a human remembered to run `just migrate` against production first, in the right order, before the code that depends on it went live.

**Why this is critical right now:** `api/migrations/019_vector_index.sql` is **modified in the working tree and uncommitted**. Its own header states the problem it fixes:

> *"that CREATE INDEX has always failed and the table has always had **no** vector index: every semantic search sorts by exact distance over every chunk the expert owns, and a chat turn runs four to six of those concurrently."*

If 019 has not been applied to production, every chat turn is running 4–6 concurrent sequential scans over the full chunk table. The fix is written and correct — it may simply not be deployed.

**Fix:** add to `fly.toml`:
```toml
[deploy]
  release_command = "python migrations/apply.py"
```
Then verify against production: `SELECT filename FROM _migrations ORDER BY filename;`

---

### C2. CI silently skips every database-backed test

**Evidence — verified by running:**
```
421 passed, 54 skipped in 1.67s
```
All 54 skips are `PERITUS_TEST_DATABASE_URL not set — skipping DB-backed test`. `.github/workflows/ci.yml` never sets that variable and defines no Postgres service container, so **all 54 skip in CI too — and CI reports green.**

The 1.67s runtime is the tell: nothing touches a database.

What is consequently untested on every push:
- `test_job_repository.py` (6) — the claim/heartbeat/reap logic the whole build system depends on
- `test_conversation_repository.py` (11) — chat persistence
- `test_credits.py` (14) — **billing correctness**
- `test_expert_visibility.py` (10)
- `test_source_uploads.py` (11)
- `test_worker.py` (3)

The tests are written. They are good tests. They have never run in CI.

**Fix — add to the `api` job in `ci.yml`:**
```yaml
    services:
      postgres:
        image: pgvector/pgvector:pg17
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready --health-interval 10s
          --health-timeout 5s --health-retries 5
        ports: ["5432:5432"]
```
with `PERITUS_TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/postgres` on the test step, plus a `python migrations/apply.py` step before it.

---

### C3. The web app is entirely absent from CI

`.github/workflows/ci.yml` has two jobs: `api` (Python) and `cli` (Rust). There is **no job for `web/`** — no typecheck, no lint, no build. All recent development has gone into `web/`.

`npx next build` currently passes clean (21 routes, verified), so nothing is broken *today*. But the surface receiving the most change has zero automated protection.

**Fix:** a third job running `npm ci && npx tsc --noEmit && npx next build` in `web/`.

---

### C4. `mypy` finds 28 errors and CI does not run it

CI runs `ruff check` (clean) but not `mypy`. `Justfile:lint` runs both — CI only runs half of it. Verified: **28 errors across 8 files.**

I triaged them. Most are type-stub noise, but two are real:

**Real bug — `api/src/peritus/sources/validator.py:222-223`:**
```python
q = float(raw.get("quality_score", 0))
r = float(raw.get("relevance_score", 0))
```
`raw` is parsed LLM output. If the model returns `null` or a non-numeric value for a score, `float()` raises `TypeError`/`ValueError`. This sits **outside** the `try/except` at lines 215–219 that guards parsing, so the exception escapes `validate_sources` and **fails the entire build** — after the money for discovery and fetching has already been spent.

The tool schema constrains the model, which makes this uncommon rather than impossible. What makes it a genuine finding is that this file already sets the correct defensive standard elsewhere — `_match_concepts` (line 154) and `_normalise_tier` (line 172) both carefully coerce and validate model output. The scores, which are the fields that actually decide whether a source is kept, are the one place that trust is extended.

**Fix:** coerce defensively and fall back to `_ERROR_VALIDATION` on failure, matching the existing pattern.

**Real bug — `api/src/peritus/jobs/worker.py:380`:** `None` assigned to a `float`-typed variable. Worth a look given it sits in the metering path.

**Noise — safe to silence:** `chat/streaming.py:109,117,123` is the loop variable `payload` (typed `str | RetrievedContext` from line 62) being reused at line 109 to hold a dict. Functionally correct — the loop has finished — but it should be a differently-named variable. `api/auth.py:69,85,86` and the `anthropic`-SDK arg-type errors are stub strictness.

---

## Significant findings

### S1. Contextual prefixes are invisible to keyword search

The contextualizer is a headline feature and a real per-chunk cost. `ingestion/pipeline.py:134-137` correctly embeds `chunk + context`, so the **semantic** arm sees it.

But the **keyword** arm indexes and queries text only:
```sql
to_tsvector('english', sc.text)        -- search/service.py:156, 161
ON source_chunks USING gin (expert_id, to_tsvector('english', text))  -- 019:62
```

Notably, `migrations/004_contextual_retrieval.sql:15` did it correctly on the legacy `chunks` table:
```sql
to_tsvector('english', coalesce(context, '') || ' ' || text)
```
The newer `source_chunks` table dropped that. So you pay to generate context, embed it, store it — and half the retrieval pipeline cannot see it.

**Fix:** index and query `coalesce(context_text,'') || ' ' || text`. Both the index expression and the two query sites must match exactly or the planner will not use the index.

---

### S2. Multi-query fusion discards the strongest relevance signal

`search/service.py:231-239`:
```python
if hit.chunk_id not in best or hit.score > best[hit.chunk_id].score:
    best[hit.chunk_id] = hit
```

`batch_search` runs 2–6 subqueries, each producing its own RRF scores. Merging takes the **maximum** score per chunk.

This is not how reciprocal rank fusion is meant to compose. RRF's whole value is that contributions **sum**: a chunk retrieved by four subqueries should outrank a chunk retrieved by one. Taking the max makes those two chunks *identical* — a chunk ranked #1 by one subquery scores `1/61`, and so does a chunk ranked #1 by all six.

Agreement across independently-planned subqueries is the best evidence of relevance the system has, and it is being thrown away at the merge step. The cross-encoder reranker partially masks this, which is likely why it hasn't surfaced.

**Fix:** accumulate rather than take max — `best[id].score += hit.score`. Cheap change, likely a material retrieval-quality gain. Worth A/B-ing through the existing `eval/` harness.

---

### S3. Prompt cache is busted on every turn once conversations exceed the history cap

`chat/agent.py:363`:
```python
trimmed = list(history[-settings.CHAT_HISTORY_MAX_MESSAGES:])
```

The cache breakpoint logic (lines 366–378) is correct and well-reasoned, and the docstring's claim holds — *until history exceeds `CHAT_HISTORY_MAX_MESSAGES`*. After that, the sliding window drops the oldest message each turn, so the cached **prefix changes every turn** and never hits.

The docstring states "the whole prior conversation is then billed at ~0.1× instead of full input price." That is true early and false exactly where it matters most — long conversations, which have the largest prefixes and the most to save.

**Fix:** trim in stable blocks (drop the oldest N when the cap is hit, then hold steady for N turns) so the prefix stays byte-identical across runs of turns.

---

### S4. Hallucinated citations vanish from the list but remain in the prose

`chat/grounding.py:200-207` bounds-checks correctly — `if 1 <= n <= num_passages`. Out-of-range citations are dropped from `used_citations`.

But nothing rewrites the answer text. If the model emits `[47]` with 25 passages, the reader sees `[47]` inline with no corresponding entry. For a product whose entire proposition is *"a citation on every claim"*, a dangling citation marker is a credibility failure precisely where credibility is the feature.

**Fix:** detect out-of-range markers post-stream and either strip them or surface an explicit warning. At minimum, log the rate — it is a direct measure of grounding quality you are not currently collecting.

---

### S5. The web app has no error boundaries at all

Verified: **zero** `error.tsx`, `not-found.tsx`, or `global-error.tsx` files in `web/app/`. Only two `loading.tsx` exist (`experts/`, `chats/[id]/`) across ~15 routes.

Every dashboard page is an async server component fetching from the Python API. Any throw — API down, 500, timeout, malformed payload — renders Next's default error page. A researcher mid-audit hits a raw stack-trace screen.

**Fix:** an `error.tsx` at `app/(dashboard)/`, a root `global-error.tsx`, a `not-found.tsx` for bad slugs, and `loading.tsx` for the remaining routes.

---

### S6. `.env.example` is missing 9 settings, including deployment-critical ones

Mechanically diffed `core/config.py` (66 settings) against `api/.env.example` (57 documented). Undocumented:

`AUTH_ALLOW_SIGNUP`, `AUTH_RATE_LIMIT`, `AUTH_RATE_WINDOW`, `BUILD_EXECUTION_DEFAULT`, **`CORS_ALLOW_ORIGINS`**, `HNSW_ITERATIVE_SCAN`, **`PERITUS_ENV`**, `PLAN_MODEL`, `SUPABASE_JWT_AUD`

`CORS_ALLOW_ORIGINS` and `PERITUS_ENV` are ones you must get right to deploy at all. Nothing in `.env.example` mentions they exist. (Good news: no drift the other way — every documented key is real.)

---

### S7. Documentation describes a product one iteration behind the code

**README.md:15** — *"Peritus is two components"* (`api/` and `cli/`). The web dashboard, where all recent work has gone, is essentially absent from the README.

**README.md** — *"the ledger ... is not yet readable back through the API"* and *"Exposing the ledger, plus CSV and RIS export, is the next thing being built."*

This is false. It is built:
- `GET /experts/{slug}/sources` — `routes/sources.py:190`
- `GET /experts/{slug}/corpus-report/export` — `routes/audit.py:88`
- `audit/export.py` — full CSV **and** RIS serialisation, with a considered rationale for RIS and correct CRLF handling

The same stale claim is in **user-facing marketing copy** — `web/components/marketing/faq.tsx:28`: *"Not yet... CSV and RIS export is the next thing being built."* You have shipped one of your most differentiating features and are still telling prospective users you haven't.

---

## Minor findings

- **`migrations/apply.py:38-40`** — applying a migration and recording it in `_migrations` are two separate `execute` calls, not one transaction. A crash between them re-runs the migration. Most are `IF NOT EXISTS`-guarded so this is usually benign, but any non-idempotent `ALTER TABLE` would fail on retry. Wrap both in `async with conn.transaction():`.
- **`web/components/experts/source-manager.tsx:276`** — icon-only button with no `aria-label` or `sr-only` text. This was the *only* instance found, which speaks well of the rest.
- **Rust CLI is drifting.** `cli/` last touched 2026-07-04; `api/` and `web/` on 2026-07-28. CI runs `cargo check --locked`, which proves the Rust compiles — it proves *nothing* about whether the API contract it depends on still exists. Three-plus weeks of heavy API change have gone unverified against it. Decide explicitly whether this is a maintained surface.
- **Stale planning docs** in the repo root and `api/`: `CHAT_PLAN.md`, `ANSWER_QUALITY_PLAN.md`, `UPLOAD_PLAN.md`. Unclear which are live.
- **Root `package.json`** contains only `shadcn` as a devDependency, with a full `node_modules/` beside it. Probably wants to live in `web/`.
- **~2,600 uncommitted lines on `main`**, including a page rename (`screening`→`discovery`, `ledger`→`sources`) and migration 019. This is a lot of unbacked-up, unreviewed work sitting in a working tree.

---

## What is genuinely good

This section is not padding. These are real strengths and several are unusual.

**The retrieval SQL is expert-level.** `search/service.py:123-138` explains why ranking happens in a wrapper over an already-limited subquery — because a window function is evaluated before `LIMIT`, so `ROW_NUMBER() OVER (...) ... LIMIT k` forces the `WindowAgg` to consume every chunk the expert owns, defeating the point of an ANN index. That is a genuinely subtle planner behaviour, correctly diagnosed, correctly fixed, and *verified on Postgres 17 / pgvector 0.8* per the comment.

**Migration 019 is the best file in the repository.** It correctly identifies that pgvector cannot index a `vector` above 2000 dimensions, that the corpus is embedded at 3072, and that migration 005's index had therefore *silently never existed*. It fixes this via a `halfvec` expression index, keeps the stored column full-precision, degrades gracefully on pgvector < 0.7, and reads the dimension off the column rather than hardcoding it. It then handles `hnsw.iterative_scan` — correctly framed as a **correctness** setting, not a tuning knob, because an HNSW scan cannot carry the `expert_id` filter and silently returns short results (measured: 40 rows from a 184-chunk expert). It even explains why `SET LOCAL` inside the query transaction is required: Supabase's transaction pooler resets session state. This is a class of bug most projects never find.

**The job queue is production-grade.** `SELECT ... FOR UPDATE SKIP LOCKED` for multi-worker claiming, heartbeats, `reap_stale` distinguishing requeue from retry-exhausted, and `release_for_shutdown` for graceful drain. The `[processes]` split in `fly.toml` correctly runs the worker as its own process group so an API deploy never kills an in-flight build.

**Citation resolution is correct.** Bounds-checked, `p.index` used consistently between inline markers and the rendered list, no off-by-one — the classic bug in this design, and it isn't here.

**Defensive parsing of model output**, where applied. `_match_concepts` maps model tags back onto the canonical list and discards invented ones; `_normalise_tier` returns `None` rather than guessing, with a comment on why an unclassifiable source must not be silently counted as good or bad news. (S3 is a finding precisely because it's the exception.)

**Design-token discipline in the frontend is excellent.** Across ~130 components, only two files contain hardcoded hex — the Google logo (brand-mandated) and recharts defaults. Both legitimate. This is much better than typical.

**The comments explain *why*.** Throughout, they document reasoning, trade-offs, and measurements rather than restating the code. `streaming.py:68` — raising `RuntimeError` instead of `assert` because `python -O` strips assertions and the resulting `AttributeError` would say nothing useful — is a good example of the general standard.

**Intellectual honesty in the product copy.** `faq.tsx:20` states plainly that screening is a single model pass with no inter-rater statistic and no published sensitivity or specificity, and should be treated as auditable triage. For a product sold on defensibility, refusing to over-claim is the correct and the commercially harder choice.

---

## Recommended order of work

1. **Add `release_command` to `fly.toml`** and verify migration 019 is applied in production (C1) — highest impact, ~10 minutes. If 019 isn't live, this alone transforms chat latency.
2. **Add Postgres to CI** (C2) — 54 written tests, including all billing tests, currently never run.
3. **Add a `web/` job to CI** (C3) — your most active surface has no protection.
4. **Fix the `float()` coercion in `validator.py`** (C4) — cheap; prevents a late-stage build failure after spend.
5. **Sum RRF contributions instead of taking max** (S2) — small diff, plausibly the largest retrieval-quality win available; measure it with `eval/`.
6. **Add error boundaries to `web/`** (S5).
7. **Include `context_text` in the FTS index** (S1) — you're paying for context the keyword arm can't see.
8. **Update README and `faq.tsx`** (S7) — you have shipped RIS/CSV export and are still advertising it as unbuilt.
9. **Commit the working tree.** 2,600 lines of good work is sitting unbacked-up.

Then commission the evaluation passes that didn't run: **billing arithmetic** and the **graph dedup merge** first, since both fail silently.
