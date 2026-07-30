# Peritus — Evaluation & Cleanup

**Date:** 2026-07-30
**Base:** `2867b5e` (main), on top of the working tree's in-flight dashboard refactor
**Scope:** `api/` and `web/`. The Rust CLI (`cli/`) was excluded by request.

This pass did two things: finished the evaluation the [previous one](#appendix--what-changed-since-the-2026-07-29-evaluation) could not complete, and applied the cleanup. Every finding below was verified by reading the code or running the command. Where something is unverified, it says so.

---

## Verification state

All of these were run against the working tree at the end of the pass:

| Check | Before | After |
|---|---|---|
| `ruff check src tests` | clean | clean |
| `mypy src` | **28 errors / 8 files** | **clean** (115 files) |
| `pytest` | 421 passed, 54 skipped | **435 passed**, 54 skipped |
| `npx tsc --noEmit` | clean | clean |
| `npx eslint .` | clean | clean |
| `npx next build` | 21 routes | **34 routes**, clean |

**The 54 skipped tests still have not executed anywhere.** They skip without `PERITUS_TEST_DATABASE_URL`. CI now provides one (see [T1](#t1-ci-now-runs-what-just-lint-runs-plus-the-db-tests-and-the-web-app)), but I could not run them locally: there is no Docker and no local Postgres on this machine, and the only reachable database is production Supabase — where the test fixture's `TRUNCATE experts RESTART IDENTITY CASCADE` would have destroyed real data. **Expect the first CI run to be the first time these 54 tests have ever run, and budget for them failing.** That is the point of turning them on, but it is not the same as knowing they pass.

---

## Critical findings

### C1. Migrations were never applied on deploy — **fixed**

`api/fly.toml` had no `release_command`; `deploy.yml` ran `flyctl deploy` alone; the `Dockerfile` did not migrate on start. `just migrate` is a local target. So every deploy shipped code and nothing shipped schema, on the assumption that a human had remembered to run migrations against production first, in the right order, before the code depending on them went live.

**Fixed** — `api/fly.toml` now carries:

```toml
[deploy]
  release_command = "python migrations/apply.py"
```

Verified safe: the `Dockerfile` already `COPY migrations/ migrations/` with `WORKDIR /app`, so the path resolves, and `apply.py` is idempotent against the `_migrations` table.

> **Still needs a human.** Confirm what production is actually on before the next deploy:
> `SELECT filename FROM _migrations ORDER BY filename;`
> If `019_vector_index.sql` is absent, every semantic search has been doing an exact-distance scan over every chunk the expert owns, four to six times per chat turn. Applying it is the single largest latency win available.

### C2. Migrations were applied non-transactionally — **fixed**

`apply.py` ran the migration and recorded it in `_migrations` as two separate `execute` calls. A crash between them leaves a migration applied but unrecorded, so the next run re-applies it. Benign for the current `IF NOT EXISTS`-guarded files, silently fatal for the first non-idempotent `ALTER TABLE` anyone adds.

**Fixed** — both statements are now one `async with conn.transaction():`, and the connection closes in a `finally`. Verified no migration uses `CREATE INDEX CONCURRENTLY`, `VACUUM`, or `CREATE DATABASE` (which cannot run in a transaction); `019`'s `ALTER DATABASE … SET` is transactional and already wrapped in a `DO` block with its own exception handler.

### C3. A build could die after the money was spent — **fixed**

`sources/validator.py` coerced two LLM-supplied fields with a bare `float()`:

```python
q = float(raw.get("quality_score", 0))
r = float(raw.get("relevance_score", 0))
```

`None` or a non-numeric value raises, and this sat **outside** the `try/except` guarding the parse above it — so the exception escaped `validate_sources` and failed the whole build, after discovery and fetching had already been paid for.

The finding is not "an LLM might return something odd". It is that this file already sets the correct standard everywhere else — `_match_concepts` discards invented tags, `_normalise_tier` returns `None` rather than guessing, with a comment on why. The two fields that actually decide whether a source is kept were the one place trust was extended.

**Fixed** — a `_coerce_score` helper matching the file's existing defensive style; an unreadable score scores 0, which is the same outcome as an explicit rejection, so one source drops instead of the run.

**Second bug found while fixing it:** the coerced floats were computed for the threshold test and then **thrown away** — `ValidatedSource` was built from `result["quality_score"]`, the raw model value. A model returning `"7"` scored correctly and then persisted the *string* to the ledger and the CSV/RIS export. The coerced values are now written back into `raw`.

---

## Significant findings

### S1. Every source upload permanently duplicated the graph — **fixed** *(new)*

This was in the previous evaluation's "not evaluated" list. It is a real bug, and the code documented the opposite of what it did.

`uploads/service.py:_extend_graph` claimed:

> *"`bulk_insert_from_extractions` already resolves a label that matches an existing node onto that node, so a document about something the corpus already covers deepens the existing concept rather than creating a rival."*

It did not. `bulk_insert_from_extractions` ran a plain `INSERT INTO expert_nodes` with **no `ON CONFLICT`**, and `merge_node_extractions` deduplicates only *within* the current extraction set, in memory, by label. Verified there is no unique constraint on `(expert_id, label)` — migration `013` added one for `expert_edges` only.

The cleanup pass that *would* have caught it, `_resolve_entities` (embedding cosine similarity ≥ 0.93), is called from **`experts/builder.py` only** — never from the upload path. So:

- Upload a source about something the corpus already covers → a second, rival copy of every concept it mentions.
- Nothing ever merges them.
- The graph degrades with every upload, and `contradicts` edges start pointing at the wrong twin.

**Fixed** — `bulk_insert_from_extractions` now reads the expert's existing nodes keyed on `lower(btrim(label))` and updates instead of inserting on a match: chunk evidence unioned, longest description kept, properties merged, and `embedding = coalesce($5, embedding)` so a re-extraction that failed to embed cannot blank a stored vector. The docstring now states what the code does, including the limitation that only exact normalised-label matches resolve here and near-duplicate merging remains a build-time pass.

### S2. RRF fusion discarded its strongest signal — **fixed**

`search/service.py:_merge_hits` merged the per-subquery hit lists by taking the **maximum** score per chunk. Reciprocal rank fusion's entire value is that contributions **sum**. Taking the max makes a chunk ranked #1 by one subquery and a chunk ranked #1 by all six *numerically identical* — so agreement across independently-planned subqueries, the best relevance evidence the system has, had no effect on the ordering. The cross-encoder reranker partially masks this, which is likely why it never surfaced.

**Fixed** — scores now accumulate. The existing test asserted the max behaviour, so it was rewritten; the replacement pins the property that matters (three subqueries agreeing outranks one confident arm) rather than just the arithmetic.

Worth A/B-ing through the existing `eval/` harness — that is what it is for.

### S3. You paid for contextual prefixes half the pipeline could not see — **fixed**

The ingestion pipeline generates an Anthropic-style contextual prefix per chunk — a real per-chunk Claude cost — and `ingestion/pipeline.py` correctly embeds `chunk + context`, so the **semantic** arm sees it. The **keyword** arm indexed and queried `to_tsvector('english', text)` alone.

So the prefix was generated, paid for, embedded and stored, and then the keyword arm was structurally unable to match on it — despite the prefix being exactly the text carrying the disambiguating nouns a keyword query is most likely to use. Migration `004` did this correctly on the legacy `chunks` table; `source_chunks` dropped it.

**Fixed** — new `migrations/022_fts_includes_context.sql` indexes `coalesce(context_text,'') || ' ' || text`, and both query sites now use a shared `_FTS_EXPR` constant so they cannot drift from the index expression. The old text-only indexes are dropped: nothing referenced that expression any more and each still cost an update on every chunk write.

### S4. The prompt cache never hit on long conversations — **fixed**

`chat/agent.py` trimmed history with `history[-CHAT_HISTORY_MAX_MESSAGES:]`. The cache-breakpoint logic around it is correct and well-reasoned, and its docstring's claim — *"the whole prior conversation is then billed at ~0.1× instead of full input price"* — held right up until history exceeded the cap. After that the window slid by one turn's worth every turn, so the cached prefix changed every turn and never hit.

It was false in exactly the case with the most to save: long conversations have the largest prefixes.

**Fixed** — trimming is now quantised to `CHAT_HISTORY_TRIM_BLOCK` (default 6) via a `_trim_start` helper, so the window's start holds still for several turns and consecutive turns share a byte-identical prefix. The trade-off is holding somewhat fewer than the cap; that is documented in both the setting and the docstring.

This function had **no test coverage at all**. Added `tests/unit/test_chat_history_trim.py` (8 tests), which pins the cache-stability property directly — a sliding window passes every cap assertion you can write and still never hits cache, so asserting the cap alone would not have caught this. It also pins that trimming never lands on a leading `assistant` message, which Claude rejects.

### S5. Hallucinated citations vanished from the list but stayed in the prose — **fixed**

`chat/grounding.py` bounds-checked correctly and dropped out-of-range citations from `used_citations`. Nothing recorded that they had been there. For a product whose proposition is *"a citation on every claim"*, a dangling `[47]` next to a list of 25 is a credibility failure precisely where credibility is the feature.

**Fixed** — `parse_citations` now returns `(valid, out_of_range)`, and `streaming.py` logs the rate and forwards `dangling_citations` on the `sources` event. Tokens are already on the wire when this is known, so the prose cannot be repaired; a `strip_dangling_citations` helper exists for the non-streaming and persistence paths. The rate is a direct measure of grounding quality that was not being collected at all.

**Good news found while fixing it:** the web renderer already degrades safely. `components/chat/message.tsx:renderCitations` only turns a marker into a clickable chip when it is backed by a real citation, so a dangling `[47]` renders as ordinary text rather than a broken link. The contract is now typed in `lib/api/types.ts`.

### S6. The web app had no error boundaries at all — **fixed**

Verified: **zero** `error.tsx`, `global-error.tsx`, or `not-found.tsx` in `web/app/`, and only two `loading.tsx` across ~15 routes. Every dashboard page is an async server component fetching from the FastAPI backend, so "the API is down, slow, or returned something unexpected" is a routine outcome. Any throw rendered Next's default error screen — a researcher mid-audit hitting a stack trace.

Worse: **six pages call `notFound()`** (`experts/[slug]` and its four children, plus `chats/[id]`) and there was no `not-found.tsx` anywhere for them to render.

**Fixed** — added `app/(dashboard)/error.tsx`, `app/global-error.tsx`, `app/(dashboard)/not-found.tsx`, `app/(dashboard)/experts/[slug]/loading.tsx` (which covers that segment and its four children), and a shared `components/error-state.tsx`.

Two things worth knowing about how these were written:

- `web/AGENTS.md` instructs that this Next version has breaking changes and its bundled docs must be read first. It was right to: the error-boundary retry prop in Next 16.2 is **`unstable_retry`**, not the `reset` that every older tutorial (and my own default) would have used. Written from `node_modules/next/dist/docs/`.
- `Button` here is Base UI, not Radix — it takes `nativeButton={false} render={<Link/>}`, not `asChild`. My first draft used `asChild`; caught and corrected against the codebase's own usage.

The not-found copy deliberately does not imply the resource exists but is off-limits. The API returns 404 rather than 403 for another user's rows on purpose, and the UI must not leak what the API withholds.

### S7. `.env.example` was missing 10 settings — **fixed**

Mechanically diffed `core/config.py` (67 settings) against `api/.env.example` (57 documented). Undocumented: `AUTH_ALLOW_SIGNUP`, `AUTH_RATE_LIMIT`, `AUTH_RATE_WINDOW`, `BUILD_EXECUTION_DEFAULT`, **`CORS_ALLOW_ORIGINS`**, `HNSW_ITERATIVE_SCAN`, **`PERITUS_ENV`**, `PLAN_MODEL`, `SUPABASE_JWT_AUD` (plus the one this pass added).

`PERITUS_ENV` and `CORS_ALLOW_ORIGINS` are both things you must get right to deploy at all, and nothing in `.env.example` mentioned they existed. `HNSW_ITERATIVE_SCAN` is a correctness setting, not a tuning knob.

**Fixed** — all ten documented in their proper sections with the reasoning from `config.py`. Re-verified mechanically: undocumented **0**, documented-but-nonexistent **0**.

### S8. The docs and marketing copy described a product one iteration behind — **fixed**

`README.md:15` said *"Peritus is two components"* (`api/`, `cli/`) — the web dashboard, where all recent work has gone, was absent.

More seriously, both the README and `web/components/marketing/faq.tsx` told readers that the ledger was not readable through the API and that *"CSV and RIS export is the next thing being built"*.

Verified false — it is shipped, end to end:

| Endpoint | File |
|---|---|
| `GET /experts/{slug}/sources` | `routes/sources.py:190` |
| `GET /experts/{slug}/corpus-report` | `routes/audit.py:69` |
| `GET /experts/{slug}/corpus-report/export?format=csv\|ris` | `routes/audit.py:90` |

with full CSV **and** RIS serialisation in `audit/export.py` (including spreadsheet-formula defusing and correct CRLF), a `decision=all\|accepted\|rejected` filter, and a working web proxy route.

**You were telling prospective customers that one of your most differentiating features did not exist yet.** Both now describe what ships.

---

## Minor findings

- **`graph/repository.py` — `get_neighbours` did not scope its node fetch by expert.** The final `SELECT … FROM expert_nodes WHERE id = ANY($1)` had no `expert_id` filter. Not exploitable today (the ids come from edges already scoped to the expert), but it was the one query in the file relying on that invariant rather than enforcing it. **Fixed.**
- **`graph/repository.py` — edges were inserted one round trip at a time** inside the transaction. **Fixed:** resolved into a dict keyed by relation (keeping the strongest weight) and written with a single `executemany`. Also removes a redundant second pass that recomputed the same set.
- **`billing/metering.py:275`** — `result.message` on a possibly-`None` union. Guarded at runtime by `contextlib.suppress`, so a type-only defect, but in the metering path. **Fixed** with `getattr`.
- **`jobs/worker.py`** — `None` assigned to a `float`-typed variable, and `record_job_cap` called identically in both branches of an if/else. **Fixed:** record once, then decide whether to *arm* the cap.
- **`chat/streaming.py`** — the retrieval loop's `payload` variable was reused 40 lines later to hold the audit dict. Functionally fine, three mypy errors, and genuinely confusing to read. **Fixed:** renamed to `audit_payload`.
- **`api/auth.py`** — JWT arguments were assembled into dicts and `**`-splatted, which defeats type checking on a security-critical call (14 of the 28 mypy errors). **Fixed** by passing them explicitly. Verified against PyJWT's source that `issuer=None` skips issuer validation, so the HS256 fallback's behaviour is unchanged.
- **`web/components/experts/source-manager.tsx`** — the icon-only remove button flagged previously already has its `aria-label` in the working tree. No action needed; it was the only instance found, which speaks well of the rest.
- **Rust CLI is drifting.** `cli/` last touched 2026-07-04; `api/` and `web/` are current. CI runs `cargo check --locked`, which proves the Rust compiles and **nothing** about whether the API contract it consumes still exists. Out of scope here, but it needs an explicit decision: maintained surface, or archived.

---

## Tooling and repo hygiene

### T1. CI now runs what `just lint` runs, plus the DB tests and the web app

Three gaps, all fixed in `.github/workflows/ci.yml`:

- **`mypy` was never run.** `just lint` runs ruff *and* mypy; CI ran only ruff. That gap is where 28 type errors and two real bugs accumulated.
- **Every database-backed test silently skipped.** No Postgres service, no `PERITUS_TEST_DATABASE_URL` — so 54 tests skipped in CI while it reported green. The 1.67s suite runtime was the tell. Among them: the job queue's claim/heartbeat/reap logic that the whole build system rests on, conversation persistence, source uploads, expert visibility, and **all 14 credit tests**. Now runs against `pgvector/pgvector:pg17` with migrations applied first — which also exercises the migration runner that C1's `release_command` now depends on. (See the caveat in [Verification state](#verification-state): these have still never actually run.)
- **`web/` was absent entirely.** Two jobs, `api` and `cli`, and none for the surface receiving all the change. Now lints, typechecks and builds.

### T2. Local commands now mirror CI

There was no local command for anything in `web/`. Added to the `Justfile`: `web`, `lint-web`, `build-web`, `test-db` (with a loud warning that the fixture `TRUNCATE`s, so it must never point at a real database), and `check`, which runs everything CI does bar the DB tests and Rust. Validated with `just --list`.

### T3. Dead code and redundant dependencies removed

Verified unreferenced before deleting, and `tsc`/`eslint`/`next build` clean after:

| Removed | Why |
|---|---|
| `web/lib/mock-data.ts` | Placeholder for a pre-auth dashboard shell that now uses real endpoints. Zero references. |
| `web/components/charts/builds-chart.tsx` | Hardcoded demo data. Zero references. |
| `web/components/ui/chart.tsx` | Only consumer was `builds-chart`. |
| **`recharts` dependency** | Only consumer was `ui/chart.tsx`. An entirely dead chain, top to bottom. |
| 8 unused shadcn primitives | `alert`, `collapsible`, `popover`, `progress`, `scroll-area`, `select`, `table`, `tabs` — all zero references (the one `tabs` hit was a comment). Mostly orphaned by the in-flight audit-page refactor. |
| Root `package.json`, `package-lock.json`, `node_modules/` (73 MB) | Contained only `shadcn`, which `web/package.json` already has. The MCP server uses `npx shadcn@latest` and does not read it. |
| `peritus.log` (104 KB) | Gitignored build artifact sitting in the working tree. |

> The 8 primitives are one command back if the refactor wants them:
> `cd web && npx shadcn@latest add table tabs select progress popover scroll-area alert collapsible`

### T4. Stale planning docs archived, not deleted

`CHAT_PLAN.md`, `api/ANSWER_QUALITY_PLAN.md`, `api/UPLOAD_PLAN.md` and `web/DASHBOARD_PLAN.md` all describe features that have since shipped. `DASHBOARD_PLAN.md` opens by calling `web/` a stock `create-next-app` scaffold with no code written — flatly untrue now, and actively misleading at the repo root.

`git mv`'d to `docs/plans/` with a `README.md` mapping each to what it shipped as and stating plainly that where a plan and the code disagree, the code is right. The reasoning is preserved (it is good reasoning); the appearance of currency is not.

`eval/` was checked and **kept** — `compare.py` has no importers, but it and `runner.py` are deliberate `python -m` harnesses with documented usage, not dead code. `compare.py` is exactly the tool for measuring S2.

---

## What is genuinely good

Not padding. These are real, and several are unusual.

**The retrieval SQL is expert-level.** `search/service.py` explains why ranking happens in a wrapper over an already-limited subquery: a window function is evaluated *before* `LIMIT`, so `ROW_NUMBER() OVER (…) … LIMIT k` puts the `WindowAgg` between the limit and the scan and forces it to consume every chunk the expert owns — defeating most of the point of an ANN index. Subtle planner behaviour, correctly diagnosed, correctly fixed, verified on Postgres 17 / pgvector 0.8.

**Migration 019 is the best file in the repository.** It identifies that pgvector cannot index a `vector` above 2000 dimensions, that the corpus is embedded at 3072, and that migration 005's index had therefore *silently never existed*. It fixes this with a `halfvec` expression index, keeps the stored column full-precision, degrades gracefully on pgvector < 0.7, and reads the dimension off the column rather than hardcoding it. It then handles `hnsw.iterative_scan` as a **correctness** setting — because an HNSW scan cannot carry the `expert_id` filter and silently returns short results (measured: 40 rows from a 184-chunk expert) — and explains why `SET LOCAL` inside the query transaction is additionally required, since Supabase's transaction pooler resets session state. Most projects never find this class of bug.

**The job queue is production-grade.** `SELECT … FOR UPDATE SKIP LOCKED` for multi-worker claiming, heartbeats, `reap_stale` distinguishing requeue from retry-exhausted, `release_for_shutdown` for graceful drain. `fly.toml`'s `[processes]` split correctly runs the worker as its own process group so an API deploy never kills an in-flight build.

**The metering design is careful in a way that is easy to get wrong.** Cost is derived from what the *response* reported — model string off the response, live/batch from which wrapper saw it — and the module docstring is explicit that configuration is not evidence of what happened, because a build can fall back from batch to live mid-stage. The meter is a mutable object in a `ContextVar` specifically so stage transitions are visible to tasks created before them. Recording is lock-guarded but never awaits, because it sits on the hot path of every provider call. `drain`/`restore` make a failed flush retryable without double-counting. I went looking for arithmetic errors here and found none.

**Pricing over-estimates on purpose.** An unknown model id resolves to Opus pricing so that an unrecognised model trips the spend cap early rather than running unmetered. That is the correct direction to be wrong in, and the comment says so.

**Citation resolution is correct.** Bounds-checked, `p.index` used consistently between inline markers and rendered list, no off-by-one — the classic bug in this design, and it isn't here.

**Defensive parsing of model output, where applied.** `_match_concepts` maps tags back onto the canonical list and discards invented ones. `_normalise_tier` returns `None` rather than guessing, with a comment on why an unclassifiable source must not be silently counted as good or bad news. `graph/extractor.py` drops incomplete nodes and edges and logs the count, and warns explicitly on `max_tokens` truncation. C3 was a finding *because* it was the exception.

**Design-token discipline in the frontend is excellent.** Across ~130 components only two files contain hardcoded hex — the Google logo (brand-mandated) and recharts defaults (now deleted). Much better than typical.

**The comments explain *why*.** Throughout, they document reasoning, trade-offs and measurements rather than restating the code. `streaming.py` raising `RuntimeError` instead of `assert` — because `python -O` strips assertions and the resulting `AttributeError` would say nothing useful — is representative of the standard.

**Intellectual honesty in the product copy.** `faq.tsx` states plainly that screening is a single model pass with no inter-rater statistic and no published sensitivity or specificity, and should be treated as auditable triage. For a product sold on defensibility, refusing to over-claim is both correct and commercially harder. Which is exactly why S8 mattered: the same file was *under*-claiming a feature that shipped.

---

## What to do next

1. **Verify migration state in production** before the next deploy — `SELECT filename FROM _migrations ORDER BY filename;`. If `019` is missing, applying it is the largest single latency win available. The `release_command` handles it from now on, but not retroactively.
2. **Watch the first CI run.** 54 tests are executing for the first time. Failures there are pre-existing, not regressions from this pass.
3. **Measure S2 and S3** through `eval/compare.py`. RRF summation and context-aware keyword search are both plausible retrieval-quality gains, and you have the harness to prove it rather than assume it.
4. **Commit the working tree.** There is a large in-flight dashboard refactor here (audit pages being restructured into `sources`/`graph`) plus this pass, all unbacked-up on `main`.
5. **Decide about `cli/`.** Three-plus weeks of API change have gone unverified against it. `cargo check` proves compilation, not contract.
6. **Consider a unique index on `expert_nodes (expert_id, lower(btrim(label)))`.** S1 is fixed in application code; a constraint would make it structurally impossible to regress. Needs a dedup migration first, since existing data may already carry duplicates from the upload path.

### Still not evaluated

Stated plainly, because "not mentioned" should not read as "fine":

- **Per-fetcher failure modes** across the nine source fetchers — not examined.
- **Chat stream claim/interrupt** under concurrency — read the streaming path, did not test the claim/interrupt race.
- **Frontend page-by-page UI/UX and accessibility** — structural issues addressed (S6), not a design review. `build-progress.tsx` (993 lines) and `knowledge-graph.tsx` (925 lines) are both large enough to deserve a look.
- **`cli/`** — excluded by request.

---

## Appendix — what changed since the 2026-07-29 evaluation

The previous pass was planned as a seven-agent parallel sweep; all seven were terminated by a session limit before reporting, and it fell back to a single-threaded review that left billing arithmetic, graph dedup, chat stream internals, per-fetcher behaviour and page-by-page frontend explicitly unexamined.

This pass closed three of those. **Billing arithmetic** was reviewed and is sound — one type-only defect, no arithmetic errors. **Graph dedup** turned out to hold the most serious new bug in the codebase (S1). **Frontend** structural gaps are fixed (S6). Two remain open above.

Its nine recommendations are all now done: `release_command` (C1), Postgres in CI (T1), a `web` CI job (T1), the `float()` coercion (C3), RRF summation (S2), error boundaries (S6), `context_text` in the FTS index (S3), README and `faq.tsx` (S8), with the working tree still to commit.
