# Codebase cleanup plan

Audit date: 2026-09-16. Scope: the whole repository — `api/`, `web/`, `cli/`, `docs/`, `.github/`
and the root tooling. Read-only audit; nothing below has been applied yet.

**Headline.** The codebase is in good shape: every lint, type check and test suite is green, the
security-critical paths (auth, cookies, CSRF, SQL construction, ownership scoping) are sound, and the
documentation is unusually accurate. The problems are almost all *hygiene and enforcement* — things
that are true today but nothing guarantees — plus one oversized module, one real security gap, and
a layer of drift between config, docs and code. This plan is ordered so that the cheap, high-value,
zero-risk work lands first and the structural refactors last.

---

## Contents

- [Baseline](#baseline)
- [Top ten by impact](#top-ten-by-impact)
- [Findings](#findings)
  - [A. Repository and git hygiene](#a-repository-and-git-hygiene)
  - [B. Toolchain pins, formatting and governance](#b-toolchain-pins-formatting-and-governance)
  - [C. CI/CD](#c-cicd)
  - [D. Dependencies and supply chain](#d-dependencies-and-supply-chain)
  - [E. Security](#e-security)
  - [F. Configuration](#f-configuration)
  - [G. Python API](#g-python-api)
  - [H. Database schema and migrations](#h-database-schema-and-migrations)
  - [I. Python tests](#i-python-tests)
  - [J. Web app](#j-web-app)
  - [K. Rust CLI](#k-rust-cli)
  - [L. Documentation](#l-documentation)
- [Things that look wrong but are deliberate](#things-that-look-wrong-but-are-deliberate)
- [The plan](#the-plan)
  - [Phase 0 — Repository hygiene (one PR, no code changes)](#phase-0--repository-hygiene-one-pr-no-code-changes)
  - [Phase 1 — Format everything once, then enforce it](#phase-1--format-everything-once-then-enforce-it)
  - [Phase 2 — Security and dependency fixes](#phase-2--security-and-dependency-fixes)
  - [Phase 3 — CI hardening](#phase-3--ci-hardening)
  - [Phase 4 — Configuration and schema](#phase-4--configuration-and-schema)
  - [Phase 5 — API structure](#phase-5--api-structure)
  - [Phase 6 — Web app structure](#phase-6--web-app-structure)
  - [Phase 7 — Rust CLI](#phase-7--rust-cli)
  - [Phase 8 — Tests and docs](#phase-8--tests-and-docs)
- [Verification](#verification)
- [Appendix: how the numbers were produced](#appendix-how-the-numbers-were-produced)

---

## Baseline

What ran, on the `web` branch at `29bb5ae` (which is fully merged into `main`):

| Check | Result |
|---|---|
| `ruff check src tests` | pass |
| `ruff format --check src tests` | **168 of 225 files would be reformatted** |
| `mypy src` | pass, 144 files |
| `pytest` (no test DB) | 1048 passed, 81 skipped, 14s |
| `pytest --cov` (no test DB) | 63% total; not reported in CI |
| `eslint .` | 0 errors, 5 warnings |
| `tsc --noEmit` | pass |
| `vitest run` | 252 passed, 11 files |
| `cargo clippy` (default lints) | clean |
| `cargo clippy -- -W clippy::pedantic` | ~190 warnings, 85 of them `uninlined_format_args` |
| `cargo fmt --check` | **285 diffs** |
| `cargo test` | 26 tests exist; **CI never runs them** |
| `npm audit --omit=dev` | 0 vulnerabilities |
| `npm audit` (with dev) | 12 (7 high), every one via `@lhci/cli 0.15.1` |
| `pip-audit` (production lock) | `cryptography 49.0.0` — PYSEC-2026-3552, fixed in 50.0.0 |
| Secrets in git history | none (`.env` never committed; the one JWT-shaped hit is a zod test vector inside a once-committed `node_modules`) |

Size: 706 tracked files. `api/src` 36,404 lines of Python, `api/tests` 17,684, `web` 25,322 lines of
TS/TSX, `cli` 5,893 lines of Rust, 31 migrations (1,558 lines of SQL), 8,497 lines of docs.

---

## Top ten by impact

1. **64 MB of Lighthouse reports are tracked in git** (132 files under `web/`, plus `manifest.json`
   with absolute local paths). They are three quarters of the packed repository. A rule to ignore
   them was added in the last commit, but the files were never `git rm --cached`. → Phase 0.
2. **Formatting is not enforced anywhere.** 168 Python files and 285 Rust hunks differ from the
   formatter; the web app has no formatter at all. Every future PR will carry noise diffs until this
   is done once, in one commit, and then gated. → Phase 1.
3. **Server-side request forgery through user-supplied URLs.** `POST /experts/{slug}/sources/url`
   only checks the scheme; the fetch follows redirects with no private-address filter, so an
   authenticated user can make the worker request `http://10.…`, `169.254.169.254`, or Fly's
   internal 6PN addresses. → Phase 2.
4. **Per-IP auth throttling trusts the first `X-Forwarded-For` hop**, which the client controls, so
   the OTP brute-force limiter can be bypassed by rotating the header. → Phase 2.
5. **`experts/builder.py` is 3,851 lines**; the `ExpertBuilder` class alone is 1,887 lines with
   seven methods over 130 lines. It is the module every build touches and the hardest to change
   safely. → Phase 5.
6. **The Rust suite, clippy and `cargo fmt` are absent from CI**, and so are `ruff format`,
   `pip-audit`, `npm audit`, coverage and job timeouts. → Phase 3.
7. **Dependency drift**: a known-vulnerable `cryptography`, two SDKs a major version behind
   (`anthropic` 0.112 → 1.6, `openai` 2.44 → 3.14), four declared-but-unused Python packages, a
   duplicate `crossterm` in the Rust lock, and no Dependabot/Renovate to notice any of it. → Phase 2.
8. **Configuration drift**: ten settings exist in `config.py` but not in `.env.example`; one default
   disagrees; `Settings` is a hand-rolled `os.getenv` class that crashes on a malformed value with a
   bare `ValueError` at import, while `pydantic-settings` is declared and never used. → Phase 4.
9. **Legacy schema**: migrations 001–004 and 006 still create `books`, `chunks`, `specialties`,
   `specialty_books` and `api_keys`, none of which any code references. Every fresh database gets
   them, and every reader of the migrations has to work out that they are dead. → Phase 4.
10. **No toolchain pins or governance files**: no `.python-version`, `.nvmrc`, `engines`,
    `rust-toolchain.toml`, `.editorconfig`, `CODEOWNERS`, `dependabot.yml` or `LICENSE`. The local
    venv is Python 3.14.5 against a 3.12 target. → Phase 1.

---

## Findings

Severity: **critical** (exploitable or data-losing), **high** (will cause a real problem soon),
**medium** (costs time or quality now), **low** (polish).

### A. Repository and git hygiene

| Sev | Where | Problem | Fix |
|---|---|---|---|
| high | `web/127_0_0_1-*.report.{html,json}` (132 files) | 64 MB of Lighthouse output tracked; `.gitignore` rule exists but files remain in the index. | `git rm --cached` them; keep the ignore rule. |
| high | `web/manifest.json` | lhci's run manifest, tracked and permanently dirty, contains absolute `/Users/…` paths. | `git rm --cached`; add `/manifest.json` to `web/.gitignore`. |
| medium | git history | `node_modules` was committed at some point (8.6 MB `ts-morph` blob and friends). | Optional history rewrite (`git filter-repo --path node_modules --invert-paths`) if clone size matters; otherwise accept. |
| medium | local branches | `feat/supabase-auth`, `fix/worker-resilience-and-completeness`, `worktree-agent-aae82eba40d6ae6be`, `worktree-implement-supabase-auth` are all merged into `main`; two stale worktrees live under `.claude/worktrees/`. Remote has `origin/claude/expert-builder-process-length-uk60yv` and `origin/feat/supabase-auth`. | `git worktree remove` both, `git branch -d` the four, delete the two remote branches. |
| medium | root `.env` | A stale pre-Peritus file (Redis/Celery, S3, `COGNITA_USER_ID`, `MCP_PORT`, `CHUNK_SIZE_CHARS=1500`) holding real keys. Nothing loads it (`api/.env` wins), but it is one `cp` away from being mistaken for the real thing. | Delete it. Rotate any key in it that is not also in `api/.env`. |
| low | `api/peritus.log` | Written into the source tree because `setup_logging()` defaults `log_file` to `"peritus.log"` for the CLI. | Default to `None`; the CLI can pass an explicit path under `~/.cache/peritus/`. |
| low | `api/src/peritus/eval/golden/retrieval/thomism.json` | Untracked golden set sitting in the tree. | Commit it (it is the retrieval eval's only real fixture) or move it out. |
| low | root | No `LICENSE`. README says all rights reserved; GitHub shows "no license" either way. | Add a one-paragraph `LICENSE` stating exactly that. |

### B. Toolchain pins, formatting and governance

| Sev | Where | Problem | Fix |
|---|---|---|---|
| high | `api/` | `ruff format --check`: 168/225 files differ. `pyproject.toml` comments say "the formatter targets line-length (100)" but nothing runs it. | One `ruff format` commit, then a CI gate. |
| high | `cli/` | `cargo fmt --check`: 285 diffs. | One `cargo fmt` commit, then a CI gate. |
| medium | `web/` | No formatter at all (no prettier/biome config); style is whatever each editor did. | Add Prettier (or Biome) with the project's existing conventions (no semicolons, single quotes, 100 cols); one format commit; gate. |
| medium | repo root | Missing `api/.python-version` (3.12), `web/.nvmrc` (22), `package.json` `engines`, `cli/rust-toolchain.toml`, `.editorconfig`. Local venv is Python **3.14.5**; CI and Docker are 3.12; `uv.lock` even carries `>=3.15` markers. | Add all five pins. Recreate the venv with `uv venv --python 3.12`. |
| medium | `.github/` | No `dependabot.yml` (or Renovate), no `CODEOWNERS`. | Add Dependabot for pip (`api/`), npm (`web/`), cargo (`cli/`) and github-actions, weekly, grouped. |
| low | repo root | No `.pre-commit-config.yaml`; `just check` is the only local gate and it is opt-in. | Add pre-commit with ruff, ruff-format, prettier, cargo fmt and a secrets scanner (gitleaks). |
| low | `api/pyproject.toml` | `[project]` has no `readme`, `license`, `urls`, `classifiers`. Ruff selects only `E,F,I,UP,B,SIM`. | Fill the metadata. Widen ruff gradually (see Phase 1). |
| low | `cli/Cargo.toml` | No `[profile.release]` (`lto`, `codegen-units = 1`, `strip`), no `[lints]` table, edition 2021. | Add both; consider edition 2024. |

### C. CI/CD

| Sev | Where | Problem | Fix |
|---|---|---|---|
| high | `ci.yml` `cli` job | Only `cargo check --locked`. The 26 unit tests in `types.rs`, `home.rs`, `chat.rs`, `avatar.rs` never run; clippy and fmt never run. | `cargo fmt --check && cargo clippy --locked --all-targets -- -D warnings && cargo test --locked`. |
| high | `ci.yml` `api` job | No `ruff format --check`; no `pip-audit`. | Add both steps (`uv run ruff format --check src tests`; `uvx pip-audit -r <(uv export --frozen --no-dev)`). |
| medium | `ci.yml` `web` job | No `npm audit --omit=dev --audit-level=high`; no formatter check. | Add both. |
| medium | all workflows | No `timeout-minutes` on any job; a hung Playwright or Fly deploy runs for six hours. | Add `timeout-minutes` per job (api 20, api-image 20, web 15, web-e2e 30, lighthouse 20, cli 15, deploys 20). |
| medium | `deploy.yml` | `superfly/flyctl-actions/setup-flyctl@master` is an unpinned mutable ref on the production deploy path. | Pin to a release tag or SHA. |
| medium | `release.yml` | Tag push builds and publishes binaries with no CI gate — a tag on a red commit ships. | `needs:` a `workflow_call` of `ci.yml`, or require the tag to be on `main` after a green run. |
| medium | `ci.yml` | No coverage collection or threshold; the 63% (no-DB) / higher (with DB) number is invisible. | `pytest --cov --cov-report=xml`, upload as an artifact; add a floor (start at the current number, ratchet). |
| low | `ci.yml` | No `paths-ignore` for docs-only changes; a README typo runs Playwright across seven projects. | `paths-ignore: ['docs/**', '**/*.md']` on `pull_request` (keep `workflow_call` unfiltered). |
| low | `ci.yml` `web-e2e` | Playwright browsers reinstalled every run. | Cache `~/.cache/ms-playwright` keyed on the Playwright version. |
| low | actions | Pinned to major tags (`@v7`), not SHAs. | Pin to SHAs via Dependabot's github-actions ecosystem, which keeps them fresh. |

### D. Dependencies and supply chain

| Sev | Where | Problem | Fix |
|---|---|---|---|
| high | `api/uv.lock` | `cryptography 49.0.0` has PYSEC-2026-3552; fix is 50.0.0. It is the transitive dep behind `pyjwt[crypto]`. | `uv lock --upgrade-package cryptography`. |
| medium | `api/pyproject.toml` | Declared and never imported: `wikipedia-api`, `pydantic-settings`, `tenacity`, `structlog`. (`lxml` *is* used, as the bs4 parser; `python-multipart` is needed implicitly by FastAPI — keep both.) | Remove the four, `uv lock`. Or adopt `pydantic-settings` for `Settings` (Phase 4) and keep that one. |
| medium | `api/uv.lock` | `anthropic` 0.112 → 1.6.0 and `openai` 2.44 → 3.14 are a major behind; `starlette` 1.3 → 1.6, `fastapi` 0.138 → 0.141. | Schedule the two SDK majors as their own PRs with the batch and streaming paths exercised; bump the rest routinely. |
| medium | `web/package.json` | Every dev vulnerability chains from `@lhci/cli 0.15.1` (`lighthouse` → `puppeteer-core` → `extract-zip`, `tmp`, `qs`). | Bump `@lhci/cli` when a release clears it; meanwhile move it out of `devDependencies` into `npx --yes @lhci/cli@<ver>` in `scripts/lighthouse.mjs` so `npm ci` stops installing it, or accept it as CI-only tooling and document that. |
| low | `web/package.json` | `@types/d3-quadtree`, `@types/d3-selection`, `@types/d3-transition` in `dependencies`; those three plus `d3-quadtree/selection/transition` caret-pinned while everything else is exact. | Move `@types/*` to `devDependencies`; pin exact. |
| low | `web/tsconfig.json` | `target: ES2017`. Next 16 / React 19.3 ship ES2022-capable browsers; the low target costs transpilation of async/await, optional chaining and class fields. | `target: ES2022`. |
| low | `cli/Cargo.lock` | `crossterm` 0.28.1 (app) and 0.29.0 (`ratatui-crossterm`) both compiled in. | `crossterm = "0.29"` in `Cargo.toml`. |
| low | `cli/Cargo.toml` | `tokio = { features = ["full"] }` pulls in signal/process/fs/io-std the TUI does not use. | Enumerate: `rt-multi-thread, macros, sync, time, net`. |
| low | `cli/` | No `cargo audit` / `cargo deny` anywhere. | Add `cargo audit` to the cli CI job. |

### E. Security

The good news first, because it is most of the picture: JWT verification is JWKS-first with a
guarded HS256 fallback; the browser holds no token (two httpOnly cookies); every mutating BFF
handler runs `guardOrigin` (Sec-Fetch-Site + Origin); `next` redirect targets go through
`safeNext`; every SQL fragment that is interpolated is either an allowlisted sort key
(`audit/repository.py:32`), a server-built visibility clause, or a column-constant tuple —
there is no user-controlled SQL anywhere; every route that lacks an auth dependency is intentionally
public (auth flows, catalog, health, share pages); uploads have size and title limits; the
production server refuses to start with auth disabled.

| Sev | Where | Problem | Fix |
|---|---|---|---|
| high | `api/src/peritus/uploads/extract.py:98` → `sources/fetchers/web.py:25,137` | URL uploads are fetched server-side with `follow_redirects=True` and only a `http(s)://` prefix check (`api/schemas/sources.py:24`). Private ranges, loopback, link-local (cloud metadata) and Fly's internal network are reachable, and a public hostname can redirect there. | Resolve the host before fetching and reject non-global addresses (`ipaddress.ip_address(...).is_global`); re-check on every redirect hop (httpx `event_hooks` or manual redirect loop); apply the same guard to `sources/fetchers/pdf.py:145` and `sources/fulltext.py:203,247`, which fetch discovery-supplied URLs. |
| high | `api/src/peritus/api/ratelimit.py:71` | `_client_ip` takes the **first** `X-Forwarded-For` entry — the one the client wrote. On Fly the trustworthy value is `Fly-Client-IP` (or the last XFF hop). | Read `Fly-Client-IP` when present, else the last XFF hop, else the socket peer; only honour any forwarded header when `settings.IS_PRODUCTION` or an explicit `TRUST_PROXY_HEADERS` flag is set. |
| medium | Fly secrets (per `docs/deployment.md`) | `SUPABASE_JWT_SECRET` is still set in production, so the HS256 fallback in `api/auth.py:67` stays live. The project uses JWKS. | Unset the secret in Fly; keep the code path for self-hosters but log a warning at startup when both are configured. |
| low | `api/src/peritus/infrastructure/database.py:56` | `_init_connection` runs `CREATE EXTENSION IF NOT EXISTS` twice on **every new pooled connection** — a privileged DDL statement on a runtime path; migrations already do it. | Remove from the init callback. |
| low | `web/app/api/vitals/route.ts:24` | Logs unbounded, unsanitised `name`/`path` strings from an unauthenticated beacon (deliberately unguarded — see the file's comment). | Clamp length and strip control characters before logging. |
| low | `api/src/peritus/infrastructure/supabase_auth.py:37` | A new `httpx.AsyncClient` per GoTrue call. | Module-level client created in `lifespan`. |

### F. Configuration

| Sev | Where | Problem | Fix |
|---|---|---|---|
| medium | `api/src/peritus/core/config.py` | Hand-rolled `Settings` with `int()`/`float()` at import: `DB_POOL_MAX_SIZE=ten` crashes with a bare `ValueError` before logging exists; enum-valued settings (`BUILD_EXECUTION_DEFAULT`, `PICTURE_RANKER`, `CHAT_EFFORT`, `DISCOVERY_LOOP`) are unvalidated strings checked (or not) at their point of use. `pydantic-settings` is already a dependency. | Port to `pydantic_settings.BaseSettings` with `Literal[...]` types and validators; keep the field names and the comments. `settings = Settings()` stays the public surface. |
| medium | `api/.env.example` | Ten settings exist in code but not here: `COMPOSITION_ABSTRACT_SHARE_CAP`, `COMPOSITION_TERTIARY_SHARE_CAP`, `DISCOVERY_LOOP`, `OPENALEX_MAILTO`, `RELEVANCE_FLOOR`, `RELEVANCE_MIN_PASSAGES`, `SCREENING_CAPTURE_DIR`, `SOURCE_FETCH_TIMEOUT`, `VALIDATE_REVIEW_MODEL`, `VALIDATE_SECOND_OPINION`. | Add them with their code comments. Add a unit test that diffs `.env.example` keys against `Settings` fields so this cannot drift again. |
| low | `.env.example` vs `config.py` | `GRAPH_BATCH_SIZE` is 15 in the example and 10 in code (the code comment explains why 10). | Make the example 10. |
| low | `api/src/peritus/api/app.py:85` | `FastAPI(version="1.0.0")` while `pyproject.toml` and the git tag say 2.0.0. | `importlib.metadata.version("peritus")`. |
| low | `.env.example`, `config.py` | `CORS_ALLOW_ORIGINS` default is `localhost:3000,localhost:8000` in code and `localhost:3000,127.0.0.1:3000` in the example. | Pick one (the example's is the useful one). |

### G. Python API

**Structure**

| Sev | Where | Problem | Fix |
|---|---|---|---|
| high | `experts/builder.py` (3,851 lines) | One module holds: 59 imports, 55 module constants, the research-plan tool schema and system prompt (`_plan_tool` 151 lines, `_plan_system`), `BuildResult`, `ExpertBuilder` (lines 660–2547), `DiscoveryOutcome`, plan normalisation (`_normalise_plan/_facets/_figures/_work`), entity reconciliation (`_reconcile_claims`, `_resolve_entities`), persona generation, retrieval-method stamping (`_stamp_retrieval_method` 92 lines), and event emission. Inside the class: `_run_discovery` 259 lines, `_discovery_round` 251, `_build` 201, `_fetch_with_refill` 167, `_enrich_and_finish` 135, `_plan_round` 132, `_persist_sources` 110. Ruff: 33 `C901`, 29 `PLR0913`, 12 `PLR0912`, 11 `PLR0915` across the package, concentrated here. | Split by stage with no behaviour change (see Phase 5 for the module map). |
| medium | `api/routes/*.py` | The "load this expert for this user or 404" helper is written four times: `audit.py:55 _readable_expert`, `conversations.py:88 _get_readable_expert`, `sources.py:50 _owned_expert`, `sharing.py:52 _owned_expert`. | One `deps.py` with `readable_expert` / `owned_expert` FastAPI dependencies taking `slug` and `user`. |
| medium | `api/routes/*.py` (56 sites) | Services and repositories are constructed inline per handler (`AuditService(get_pool())`, `ExpertRepository(pool)`), so every handler knows the pool and nothing can be substituted in tests without monkeypatching. | Provide them as dependencies (`Depends(get_audit_service)`); tests override with `app.dependency_overrides`. |
| medium | `api/routes/experts.py:373` `build_expert` | 130 lines orchestrating `ExpertRepository`, `JobRepository` and entitlements (create/queue/enqueue/hold/cancel-on-insufficient-credits) inside the route. | Move to `ExpertService.request_build(...)` returning a result the route maps to HTTP. Same for `update_expert_catalog` (54 lines) and `set_expert_avatar` (47). |
| medium | `jobs/worker.py:302–446` and `446–536` | `_run_job` and `_run_ingest_job` each define their own `heartbeat_loop` and `on_event` closures and the same try/finally choreography. | One `_supervise(job, coro)` helper that owns heartbeat, meter flush, cancellation and cleanup; the two callers pass only what differs. |
| low | `chat/renderer.py` | Rich console rendering (a CLI concern) lives in the `chat` domain package and is imported only by `cli/chat.py`. | Move to `cli/render.py`. |

**Correctness and robustness**

| Sev | Where | Problem | Fix |
|---|---|---|---|
| medium | 27 `httpx.AsyncClient(...)` construction sites (`fetchers/web.py` ×3, `openalex.py` ×3, `fulltext.py`, `wikipedia.py`, `pubmed.py`, `pdf.py`, `gutenberg.py`, `canonical.py` ×2 each, …) | A client per call: no connection reuse across a discovery round that hits the same hosts hundreds of times, and per-site timeout/header/redirect settings that have already diverged. | One `infrastructure/http.py` factory that returns a shared client per (base settings) with the timeouts, `follow_redirects` and the SSRF guard from §E applied once. Fetchers take it in `__init__`. |
| low | 101 `except Exception` sites (builder 12, `sources/fulltext.py` 6, `jobs/worker.py` 6) | Most log and continue, which is right for fetchers. Six swallow silently: `cli/build.py:208`, `sources/preview.py:86`, `sources/fetchers/youtube.py:86,95`, `sources/fetchers/pdf.py:150`, `jobs/worker.py:162`. | Add a `logger.debug` with the reason to each; narrow the type where the intent is one failure mode (`httpx.HTTPError`, `json.JSONDecodeError`). |
| low | `api/src/peritus` (306 `Any`, 27 `type: ignore`, 13 of them `[call-overload]`) | `Any` clusters in tool-call JSON handling (`builder.py`, `sources/triage.py`, `graph/extractor.py`) where a `TypedDict` per tool schema would type the boundary once. | Define `TypedDict`s next to the tool schemas; enable `disallow_untyped_defs` per package as it becomes true (`billing`, `jobs`, `api` first). |

**Dead code** (zero references in `src` and `tests`)

`experts/builder.py:3756 _deduplicate_by_url`, `experts/repository.py:637 update_config`,
`experts/service.py:134 remove_picture`, `billing/repository.py:98 set_spend_cap_override`,
`graph/domain.py:90 edge_property`, `sources/domain.py:286 with_identifiers`,
`sources/dedup.py:212 add_url`, `infrastructure/gutenberg_catalogue.py:271 set_catalogue`,
`core/exceptions.py:52 FetchError`, `api/schemas/audit.py:97 AuditPage`, `api/app.py:118 keygen`
(only reachable via the `python -c` snippet in `.env.example`).

**Referenced only from tests** (dead in production; decide keep-as-API or delete with the test):
`chat/grounding.py:276 strip_dangling_citations`, `experts/picture_repository.py:89 get_candidates`,
`sources/fulltext.py:302 is_paid_path`, `experts/avatar.py:104 default_seed`,
`experts/repository.py:244 delete_for_user`, `core/exceptions.py:56 ValidationError`.

**Logging**

| Sev | Where | Problem | Fix |
|---|---|---|---|
| low | `core/logging.py` | Plain-text format; `structlog` is declared and unused. Request ids are correlated for the API but a build's log lines carry only `-`. | Either drop `structlog` (simplest) or adopt it for JSON in production. Bind `job_id`/`expert_id` in the worker's context var the way `request_id` is bound in the API, so a build is greppable. |
| low | `core/logging.py:44` | `setup_logging(log_file="peritus.log")` default writes into CWD. | Default `None`. |

### H. Database schema and migrations

| Sev | Where | Problem | Fix |
|---|---|---|---|
| medium | `migrations/001–004, 006` | Create `books`, `chunks`, `specialties`, `specialty_books`, `api_keys` and their indexes. Zero references in `src/`. `001` also creates an HNSW index on `chunks.embedding` that (per `019`'s own comment) never worked at 3,072 dimensions. | Add `032_drop_legacy_tables.sql` that `DROP TABLE IF EXISTS` each one (after confirming they are empty in production — `SELECT count(*)` on each first). Leave the old files; `apply.py` is filename-keyed and re-running them is a no-op. Add a header comment to `001` pointing at `032`. |
| low | `migrations/apply.py` | No `--dry-run`/`--list` and no lock, so two concurrent release commands could race (Fly runs one, so this is theoretical). | `pg_advisory_lock` around the loop; a `--status` flag. |
| low | `migrations/` | 13 data-migrating `UPDATE`/`DELETE` statements (010, 013, 018, 024, 031) rely on the transaction wrapper for idempotence — correct, but undocumented. | One sentence in `api/README.md` under Migrations. |

### I. Python tests

957 tests: 741 unit (58 files), 67 integration (9), 149 API (12). The suite is fast (14s) and green.

| Sev | Where | Problem | Fix |
|---|---|---|---|
| medium | `tests/**` | Fixture helpers re-implemented per file: `_expert` ×14, `_candidate` ×7, `_validated` ×5, `_make_expert` ×5, `_source` ×4, `_hit` ×4. | `tests/factories.py` (or `conftest.py` fixtures) with one builder each. |
| medium | coverage (no DB) | `audit/service.py` 24%, `jobs/worker.py` 36%, `experts/repository.py` 40%, total 63%. With the DB tests the numbers are higher but nobody sees them. | Report coverage in CI (§C); target the three files. |
| medium | `tests/**` | Not referenced by any test at all: the whole `cli/` package (`catalog.py` 378, `build.py` 304, `credits.py` 211, `display.py` 186, `main.py` 154, `chat.py`, `credentials.py`, `session.py`), the whole `eval/` package, fetchers `pdf.py`, `exa.py`, `reddit.py`, `youtube.py`, `wikipedia.py`, plus `ingestion/contextualizer.py` (204), `ingestion/pipeline.py` (175), `chat/faithfulness.py` (98), `sources/capture.py` (133). (Routes in `sources.py` are exercised through the app; the heuristic misses those.) | Typer's `CliRunner` for the CLI commands' argument parsing and output shape; `respx` for the five fetchers' HTTP contracts; direct tests for contextualizer/pipeline with a stubbed model. |
| low | `tests/**` | 27 imports of underscore-private names from `src`; 4 `monkeypatch.setattr("dotted.path")` strings; 13 `sleep` calls. | Promote the imported privates to public names or test through the public seam; replace sleeps with event/condition waits. |
| low | `Justfile`, `api/README.md`, `docs/development.md` | Say "54" / "around 50" DB-backed tests; the actual skip count is 81. | Say "the DB-backed tests" and stop counting, or count from `pytest -q` in a doc test. |

### J. Web app

The BFF layer (`lib/api/route.ts`, `server.ts`, `proxy.ts`, `errors.ts`, `sse.ts`) is well built:
thin handlers, one place that talks to FastAPI, refresh-once, a real CSRF guard, allowlisted query
forwarding, correct null-body statuses, streaming without buffering. Server loaders are memoised
with React `cache()`. Type safety is strict (zero `any`, zero `@ts-ignore`).

| Sev | Where | Problem | Fix |
|---|---|---|---|
| medium | 21 `fetch('/api/…')` sites across 12 client files (`add-source-dialog.tsx`, `chat-view.tsx`, `verify-card.tsx` ×2 each; `use-start-chat.ts`, `use-start-build.ts`, `use-leave-expert.ts`, `use-chat-stream.ts`, `open-shared-expert.tsx`, `expert-settings-page.tsx`, `admin-page.tsx`, `account-settings-page.tsx`, …) with 19 hand-written `if (!res.ok)` branches and 28 `toast.*` calls. | `lib/api/client.ts` with `apiJson<T>(path, init)` / `apiVoid` that decode FastAPI's `{detail}` shape once, throw a typed `ClientApiError`, and a `useApiAction` hook that pairs it with the toast + `router.refresh()` pattern (27 sites). |
| medium | `web/proxy.ts:90`, `lib/api/proxy.ts:44`, `lib/auth/cookies.ts:74` | The httpOnly/secure/sameSite/path cookie spec is written three times; `lib/api/proxy.ts` exports `refreshSession` "for `proxy.ts`" but `proxy.ts` inlines its own call. | `proxy.ts` and `lib/api/proxy.ts` iterate `sessionCookies(session)` from `cookies.ts`; delete the duplicate literals; have `proxy.ts` use `refreshSession` or drop the export. |
| medium | `components/experts/overview-page.tsx` (516 lines, one `useState`) | Almost entirely JSX: header + identity, properties list, coverage, recent chats, composer, notices. | Split into `overview-header.tsx`, `overview-properties.tsx`, `overview-coverage.tsx`; keep the page as composition. |
| medium | `components/graph/graph-canvas.tsx` (489 lines, 15 `useRef`, 7 `useEffect`) | Canvas lifecycle, simulation worker messaging, zoom/pan, hit-testing and painting in one component. | Extract `useGraphSimulation` (worker + node positions), `useCanvasZoom` (d3-zoom binding) and `paintGraph(ctx, state)` as a pure function that can be unit-tested. |
| medium | `components/shell/expert-sidebar.tsx` (463), `components/ledger/ledger-page.tsx` (460), `components/chat/assistant-card.tsx` (443), `components/build/build-view.tsx` (350), `components/chat/chat-view.tsx` (349), `components/build/build-log.tsx` (335) | Each mixes two or three concerns (list + filters + dialogs; card + citations + actions; view + timeline + cost). | Extract the second concern from each into a sibling file; no behaviour change. |
| medium | `lib/api/types.ts` (1,078 hand-maintained lines) | No codegen from FastAPI's `/openapi.json`; the fixture tests are the only drift check. | Generate with `openapi-typescript` into `lib/api/generated.ts` (checked in, regenerated by a `just types` recipe and verified unchanged in CI); keep `types.ts` for the hand-written unions (`BuildEvent`, `ChatEvent`) that the OpenAPI schema cannot express. |
| low | `components/experts/new-expert-form.tsx:84–85` | `react-hooks/incompatible-library` warning on `form.watch()`; `ledger-page.tsx:194,201` and `account-settings-page.tsx:58` use `window.location` for internal navigation. | `useWatch({ control })`; `router.push` / `router.replace` (the settings case is a post-logout full reload — if that is intentional, add the eslint-disable with the reason). |
| low | `app/(app)/chats/[id]/page.tsx:16,32` | `getExpertIfReadable` and `getExpertConversations` both depend only on `conversation.expert_slug` and run sequentially. | `Promise.all` for the pair. |
| low | `tests/` | No unit tests for `lib/access.ts`, `lib/api/data.ts`, `lib/api/server.ts` (`decodeError`, `throwForStatus`), `lib/graph/simulation.worker.ts`. | Add them; `decodeError` and `access` are pure and cheap. |
| low | `app/globals.css` (523 lines) | 80 custom properties; `--backdrop`, `--ease-in`, `--font-mono`, `--radius-row` and `--spacing-*` appear defined and unreferenced (the `--color-*` set is consumed by Tailwind `@theme`, so the naive grep over-reports — verify each before removing). | Remove confirmed-unused tokens; group the remaining by role with a comment header per group. |
| low | `e2e/mock-api/server.mjs` (1,037 lines) | Fixtures, routing and SSE emulation in one file. | Split into `routes/*.mjs` + `sse.mjs` + `state.mjs`; keep the entry point. |
| low | `next.config.ts` | `X-Frame-Options: DENY` without a `Content-Security-Policy` (`frame-ancestors 'none'` is the modern form, and a CSP would also cover script sources). | Add a CSP in report-only mode first; the app has no third-party scripts, so a strict one is achievable. |

### K. Rust CLI

Zero `unwrap`/`expect`/`panic!` in non-test code (all 36 are inside `#[cfg(test)]`); the config store
sets `0600`; the SSE parser buffers on `\n` and is UTF-8 safe. Solid.

| Sev | Where | Problem | Fix |
|---|---|---|---|
| medium | `src/tui/screens/build.rs` (1,491 lines) | `tick()` is 436 lines (382–818): event dispatch for every build event kind plus state mutation; twelve `render_*_content` functions follow. | `tick` → `apply_event(&mut self, ev)` with one `match` arm per event delegating to `on_plan_ready`, `on_source_reviewed`, …; move `render_*` into `build/render.rs`. |
| medium | `src/tui/screens/home.rs` (839), `src/tui/app.rs` (786), `src/tui/screens/chat.rs` (636) | Same shape: input handling, state, and rendering in one file each. | Split `render` out of each. |
| low | `src/api/sse.rs` | Handles `id:` and `data: ` only. No multi-line `data:` joining, no `event:` field, `data:` without a space is dropped, `retry:` ignored. Fine for this server, wrong for the spec. | Implement the four-field event block properly (`~40 lines`) and add tests; the parser is the piece most worth testing. |
| low | `src/config/store.rs:67` | `fs::write` then `set_permissions` — the file exists world-readable between the two calls, and a crash mid-write truncates it. | Write to `path.with_extension("tmp")` with `OpenOptions.mode(0o600)`, then `rename`. |
| low | `src/api/types.rs:6,74,100,300` | Four `#[allow(dead_code)]` hide fields the TUI never reads. | Delete the fields (serde ignores unknown keys) or read them. |
| low | `Cargo.toml` | `crossterm 0.28` beside `ratatui-crossterm`'s 0.29 (two copies compiled); `tokio` `full`; no `[profile.release]`; no `[lints]`; `edition = "2021"`. | See §D. |
| low | `cli/` | No `rustfmt.toml`/`clippy.toml`; pedantic shows 85 `uninlined_format_args`, ~20 lossy casts (`u64 as f64`, `usize as u16`), 8 identical match arms. | `cargo clippy --fix` for the mechanical ones; review the casts (they are progress-bar arithmetic; `u16::try_from(...).unwrap_or(u16::MAX)`). |

### L. Documentation

The docs are accurate to a degree that is rare: `docs/api-reference.md` matches the 57 implemented
routes exactly (its one "extra" is the `?after=N` annotation on the events stream); the README's
"eleven fetchers", tier table and six CI jobs all match the code; `web/AGENTS.md` is a genuine
record of decisions.

| Sev | Where | Problem | Fix |
|---|---|---|---|
| medium | `docs/plans/README.md` "Proposed, not shipped" | Lists `web-production.md`, `web-implementation.md`, `web-design.md`, `corpus-quality.md`, `retrieval-quality.md` as unshipped. The web app is in production; corpus-quality phases 0–7 and retrieval changes R1–R12 shipped in September. | Move all five to the "Shipped as" table with their code pointers, or move fully-shipped plans to `docs/plans/archive/`. |
| low | `Justfile:24`, `api/README.md`, `docs/development.md` | "54 DB-backed tests" / "around 50"; actual is 81. | Remove the number. |
| low | `api/.env.example` | Missing ten settings (§F). | Add. |
| low | `docs/configuration.md` | Fine, but has no pointer to the settings that exist only in code. | Regenerate the table from `Settings` (a tiny script) so it cannot drift. |
| low | `README.md` "Status" | "There is no payment provider" is right; "pre-1.0" sits beside a `v2.0.0` tag and `version = "2.0.0"`. | Pick a versioning story (0.x until the API is stable, or drop the "pre-1.0" line). |

---

## Things that look wrong but are deliberate

Do not "fix" these; each has a recorded reason.

- **No `SameSite=Strict`** — the Google OAuth callback needs `Lax` (`lib/auth/cookies.ts:60`).
- **`/api/vitals` has no origin guard** — beacons fire on unload where a 403 is invisible (`vitals/route.ts:10`).
- **`readiness`, not `status`, gates chat**; `null` counts are never coerced to zero; enrichment
  failures degrade rather than fail; a closed SSE stream is not a finished build (`CONTRIBUTING.md`).
- **Vitest is node-only, no component rendering** — Playwright covers the browser (`vitest.config.mts`).
- **`next start` is never reused in Playwright** — stale build manifests (`playwright.config.ts:83`).
- **No stream abort on unmount** — Strict Mode double-mount (`web/AGENTS.md`).
- **`hidden md:flex` dual rendering** instead of `useMediaQuery` deciding the tree (`web/AGENTS.md`).
- **`statement_cache_size=0`** — Supabase transaction pooler (`database.py:47`).
- **`hnsw.iterative_scan` is a correctness setting**, not tuning (`database.py:66`).
- **Worker memory is 2 GB** for a reason measured in production (`fly.toml`).
- **Migrations are forward-only** and run as the release command (`docs/development.md`).
- **`@dicebear/core` stays at 9.4.3** — `collection` 9.4 peers on core `^9` (`web/AGENTS.md`).
- **Fixture type annotations are the schema check** until codegen exists (`web/tests/fixtures.test.ts`).

---

## The plan

Each phase is one or a few PRs. Every phase ends green on `just check` plus whatever gate the phase
adds. Phases 0–3 change no application behaviour and can land in a day; 4–8 are ordered by
value-per-risk and can be interleaved with feature work.

Effort: **S** under an hour, **M** an afternoon, **L** a day or more.

### Phase 0 — Repository hygiene (one PR, no code changes)

| # | Task | Effort | Done when |
|---|---|---|---|
| 0.1 | `git rm --cached web/127_0_0_1-*.report.* web/manifest.json`; add `/manifest.json` to `web/.gitignore`. | S | `git ls-files web \| grep -c report` is 0; `git count-objects -vH` after `gc` is under 5 MB. |
| 0.2 | Delete root `.env` (rotate keys not present in `api/.env`); delete `api/peritus.log`. | S | `ls -a` at the root shows no `.env`. |
| 0.3 | `git worktree remove` the two `.claude/worktrees/*`; `git branch -d` the four merged branches; `git push origin --delete claude/expert-builder-process-length-uk60yv feat/supabase-auth web` (once `web` is no longer the working branch). | S | `git branch -a` shows `main` and open work only. |
| 0.4 | Decide `thomism.json`: commit under `eval/golden/retrieval/` (recommended) or add to `.gitignore`. | S | `git status` clean. |
| 0.5 | Add `LICENSE` (all rights reserved, matching README). | S | GitHub shows a licence. |
| 0.6 | (Optional) `git filter-repo --invert-paths --path node_modules` to drop the committed `node_modules` from history; force-push; every collaborator re-clones. Only worth it if clone time matters. | M | — |

### Phase 1 — Format everything once, then enforce it

Land the formatting commits **immediately after** Phase 0 and before any refactor, so no open PR
carries reformatting noise.

| # | Task | Effort | Done when |
|---|---|---|---|
| 1.1 | `cd api && ruff format src tests` — one commit titled `style: apply ruff format`. Add `ruff format --check src tests` to `just lint` and the `api` CI job. | S | CI fails on an unformatted file. |
| 1.2 | `cd cli && cargo fmt` — one commit. Add `rustfmt.toml` (`max_width = 100`, `edition`), `cargo fmt --check` to CI. | S | Same. |
| 1.3 | Add Prettier to `web/` (`.prettierrc`: `semi: false`, `singleQuote: true`, `printWidth: 100`, `trailingComma: 'es5'`, `plugins: [prettier-plugin-tailwindcss]`); `eslint-config-prettier` to stop rule clashes; `npx prettier --write .` in one commit; `prettier --check` in `just lint-web` and CI. | M | Same. |
| 1.4 | Pins: `api/.python-version` = `3.12`; `web/.nvmrc` = `22`; `package.json` `"engines": {"node": ">=22"}`; `cli/rust-toolchain.toml` = `stable`; `.editorconfig` (utf-8, lf, 2/4 spaces, final newline). Recreate the venv on 3.12. | S | `python --version` in the venv is 3.12.x. |
| 1.5 | `.github/dependabot.yml`: pip (`/api`), npm (`/web`), cargo (`/cli`), github-actions; weekly; grouped minor/patch. `.github/CODEOWNERS` with the maintainer. | S | First Dependabot PRs appear. |
| 1.6 | `.pre-commit-config.yaml`: ruff, ruff-format, prettier, `cargo fmt`, gitleaks. Document `pre-commit install` in `docs/development.md`. | S | A commit with an unformatted file is refused locally. |
| 1.7 | Widen ruff in two steps: first `select` += `["C4", "RET", "PT", "RUF", "ASYNC", "PL" subset (PLR0402, PLR1714, PLW…)]` with `--fix`; second, enable `C901`/`PLR09xx` with a high threshold and ratchet down as Phase 5 lands. | M | `ruff check` green with the wider set. |
| 1.8 | `Cargo.toml`: `[profile.release] lto = "thin", codegen-units = 1, strip = true`; `[lints.clippy] pedantic = "warn"` with the noisy ones allowed; `cargo clippy --fix` for `uninlined_format_args`. | S | `cargo clippy --all-targets -- -D warnings` clean. |

### Phase 2 — Security and dependency fixes

| # | Task | Effort | Done when |
|---|---|---|---|
| 2.1 | **SSRF guard.** `infrastructure/http.py`: `async def assert_public_host(url)` resolving via `loop.getaddrinfo` and rejecting any address where `not ip.is_global`; a shared `httpx.AsyncClient` factory whose `event_hooks["request"]` re-checks on every redirect hop. Use it in `uploads/extract.py`, `fetchers/web.py`, `fetchers/pdf.py`, `sources/fulltext.py`. Tests: loopback, RFC1918, link-local, IPv6 ULA, a redirect from public to private. | M | Tests pass; `curl -d '{"url":"http://169.254.169.254/"}' …/sources/url` is rejected with a clear 422. |
| 2.2 | **Client IP.** `ratelimit._client_ip`: prefer `Fly-Client-IP`, else last `X-Forwarded-For` hop, else socket peer; honour headers only when `settings.TRUST_PROXY_HEADERS` (default `IS_PRODUCTION`). Test both branches. | S | A spoofed first-hop XFF no longer changes the bucket. |
| 2.3 | Unset `SUPABASE_JWT_SECRET` in Fly (`fly secrets unset`); startup warning when both a URL and a secret are configured. | S | `/auth/status` still healthy; JWKS path in use. |
| 2.4 | `uv lock --upgrade-package cryptography`; add `pip-audit` to CI (§3). | S | `pip-audit` clean. |
| 2.5 | Remove `wikipedia-api`, `tenacity`, `structlog` (and `pydantic-settings` unless Phase 4.1 adopts it); `uv lock`. | S | `uv lock --check` passes; app boots. |
| 2.6 | Web: move `@types/d3-*` to `devDependencies`; pin the six d3 packages exactly; `target: ES2022`. | S | `npm ci && npm run build` green. |
| 2.7 | `@lhci/cli`: bump if a clean release exists; otherwise run it via `npx --yes @lhci/cli@0.15.1` from `scripts/lighthouse.mjs` and drop it from `devDependencies`, so `npm audit` on the install set is clean and the tool is still pinned. | S | `npm audit` 0 with dev deps installed. |
| 2.8 | `crossterm = "0.29"`; enumerate tokio features; `cargo audit` in CI. | S | One `crossterm` in `Cargo.lock`. |
| 2.9 | Separate PRs, later: `anthropic` 0.112 → 1.x and `openai` 2.x → 3.x. Read each changelog; exercise `anthropic_batch.py`, streaming in `chat/streaming.py`, and `embeddings.py` end to end against a real key before merging. | L | A real lite build and a chat turn succeed on the new SDKs. |
| 2.10 | Remove `CREATE EXTENSION` from `database._init_connection`. Clamp and sanitise the strings logged by `/api/vitals`. Share one `httpx.AsyncClient` in `supabase_auth.py`. | S | Tests green. |

### Phase 3 — CI hardening

| # | Task | Effort | Done when |
|---|---|---|---|
| 3.1 | `cli` job: `cargo fmt --check`, `cargo clippy --locked --all-targets -- -D warnings`, `cargo test --locked`, `cargo audit`. | S | The 26 Rust tests run on every PR. |
| 3.2 | `api` job: `ruff format --check`, `pip-audit`, `pytest --cov=src/peritus --cov-report=xml --cov-fail-under=<current>`; upload `coverage.xml` as an artifact. | S | Coverage visible on each run. |
| 3.3 | `web` job: `prettier --check`, `npm audit --omit=dev --audit-level=high`. | S | — |
| 3.4 | `timeout-minutes` on every job; pin `superfly/flyctl-actions/setup-flyctl` to a tag; let Dependabot move actions to SHAs. | S | — |
| 3.5 | `release.yml`: gate on `ci.yml` via `workflow_call` before building binaries. | S | A tag on a red commit does not publish. |
| 3.6 | `pull_request.paths-ignore: ['docs/**', '**/*.md']` on `ci.yml`; cache Playwright browsers. | S | A docs-only PR runs no jobs. |
| 3.7 | Update `just check` to run every gate CI runs (`format`, `audit`, `clippy`, `cargo test`), and add `just format` and `just audit` recipes so the Justfile and CI stop drifting. | S | `just check` green ⇔ CI green (minus the DB tests). |

### Phase 4 — Configuration and schema

| # | Task | Effort | Done when |
|---|---|---|---|
| 4.1 | Port `core/config.py` to `pydantic_settings.BaseSettings`: same field names, `Literal` types for the enum-valued settings, validators for the ranges (`DB_POOL_MAX_SIZE ≥ MIN`, `CHAT_EFFORT ∈ {…}`), `model_config = SettingsConfigDict(env_file=".env")`. Keep every comment. Startup error lists *all* invalid settings at once. | M | `DB_POOL_MAX_SIZE=ten` produces one readable error naming the field; all tests green. |
| 4.2 | Add the ten missing settings to `.env.example`; fix `GRAPH_BATCH_SIZE` and `CORS_ALLOW_ORIGINS`; add `tests/unit/test_env_example.py` that asserts `.env.example` keys ⊇ `Settings` fields. | S | Test passes and would fail on the next drift. |
| 4.3 | `FastAPI(version=importlib.metadata.version("peritus"))`. | S | `/openapi.json` says 2.0.0. |
| 4.4 | `032_drop_legacy_tables.sql`: verify the five tables are empty in production (`SELECT count(*)`), then `DROP TABLE IF EXISTS … CASCADE`. Header comment in `001_initial.sql` pointing to it. | S | Fresh `apply.py` run creates only live tables; CI `api-image` job passes. |
| 4.5 | `apply.py`: `pg_advisory_lock(…)` around the loop; `--status` flag listing applied/pending. | S | — |
| 4.6 | Regenerate the table in `docs/configuration.md` from `Settings` (a 30-line script under `api/scripts/`), and note the rule in `docs/development.md`. | S | — |

### Phase 5 — API structure

The builder split is the one refactor with real risk. Do it as a pure move first (no logic changes,
`git mv`-style diffs, tests untouched and green), and only then touch the long functions.

| # | Task | Effort | Done when |
|---|---|---|---|
| 5.1 | **Builder split, mechanical.** New package `experts/build/`: `constants.py` (the 55 constants, `OUTCOME_*`, `STOP_*`, `_FETCHER_NAMES`), `planning.py` (`_plan_tool`, `_plan_system`, `_plan_research`, `_normalise_*`, `_clean_concepts`, `plan_user_message`), `discovery.py` (`_run_discovery`, `_plan_round`, `_discovery_round`, `_fetch_with_refill`, `_validate_round`, `DiscoveryOutcome`, `_priority_reservation`, `_fetch_sort_key`, `_safe_search`, `_safe_fetch_candidate`, `_stamp_retrieval_method`), `reconcile.py` (`_reconcile_claims`, `_resolve_entities`, `_merge`), `persona.py` (`generate_persona`, `_generate_persona`, `_persona_digest`, `corpus_tier_warning`), `events.py` (`_emit_event`, `_log_event`, `_clip`), `estimates.py` (`_metered_spend`, `_ingest_estimate`, `_prefetch_cost_estimate`, `_cap_usd`, `resolve_execution`, `discovery_loop_enabled`). `builder.py` keeps `ExpertBuilder`, `BuildResult`, `_build`, `_resume`, `_enrich_and_finish`, `_graph_stage`, `_persist_sources` and re-exports the public names so `from peritus.experts.builder import X` still works for `jobs/worker.py`, the tests and the CLI. | L | Every file under 800 lines; `pytest` green with no test edits; `ruff` `C901` count unchanged (it moves, it does not grow). |
| 5.2 | **Builder, long functions.** `_run_discovery` (259) → loop driver + `_should_stop(round_state) -> StopReason`; `_discovery_round` (251) → `_search`, `_triage`, `_fetch`, `_validate` calls it already makes, with the round's bookkeeping in a small `RoundState` dataclass; `_build` (201) → stage list executed by a `for stage in STAGES` with each stage a method. | L | `C901`/`PLR0915` in the package under 10 each; integration tests (`test_build_loop`, `test_build_degradation`, `test_builder_tiers`) unchanged and green. |
| 5.3 | `api/deps.py`: `readable_expert(slug, user)` and `owned_expert(slug, user)` dependencies; delete the four local copies. Provide `get_expert_repo`, `get_audit_service`, … as dependencies; tests use `dependency_overrides` instead of monkeypatching. | M | Zero `get_pool()` calls in `api/routes/`. |
| 5.4 | `ExpertService.request_build(...)` (from `build_expert`), `.update_catalog(...)`, `.set_avatar(...)`; routes become "validate, call, map". | M | `routes/experts.py` under 500 lines; every handler under 40. |
| 5.5 | `jobs/worker.py`: `_supervise()` shared by `_run_job` and `_run_ingest_job`. | M | Two nested `heartbeat_loop` definitions become one. |
| 5.6 | Shared HTTP client factory (from 2.1) adopted by every fetcher; delete the 27 per-call constructions. | M | `grep -c "httpx.AsyncClient(" src` ≤ 3. |
| 5.7 | Delete the eleven confirmed-dead symbols; decide the six test-only ones. Move `chat/renderer.py` to `cli/`. | S | `vulture --min-confidence 80` clean. |
| 5.8 | Log the six silent `except Exception` sites; narrow the exception type where one failure mode is meant. | S | — |
| 5.9 | Bind `job_id`/`expert_id` into the logging context var in the worker so build logs are greppable; `setup_logging` default `log_file=None`. Drop `structlog` (or adopt it — decide in 2.5). | S | A build's log lines carry `[job=…]`. |
| 5.10 | `TypedDict`s for the tool-call payloads (`_plan_tool`, triage, graph extraction); `disallow_untyped_defs = true` for `billing`, `jobs`, `api` via `[[tool.mypy.overrides]]`. | M | `Any` count under 150; the 13 `[call-overload]` ignores gone. |

### Phase 6 — Web app structure

| # | Task | Effort | Done when |
|---|---|---|---|
| 6.1 | `lib/api/client.ts` (`apiJson`, `apiVoid`, `ClientApiError`) and `hooks/use-api-action.ts` (pending state, toast on error, optional `router.refresh()`); migrate the 21 fetch sites. | M | `grep -rc "fetch('/api" components hooks` is 0; `if (!res.ok)` count is 0 outside `lib/`. |
| 6.2 | Cookie spec: `proxy.ts` and `lib/api/proxy.ts` use `sessionCookies()`; delete the duplicate literals and the dead `refreshSession` export (or use it). | S | One place defines the cookie shape; `tests/cookies.test.ts` and `proxy.test.ts` green. |
| 6.3 | `openapi-typescript` → `lib/api/generated.ts` from `http://localhost:8000/openapi.json`; `just types` recipe; CI step that regenerates and `git diff --exit-code`s. `types.ts` keeps only the SSE unions and re-exports the rest. | M | A renamed Python field fails CI in the web job. |
| 6.4 | Component splits: `overview-page` → header/properties/coverage; `graph-canvas` → `useGraphSimulation`, `useCanvasZoom`, pure `paintGraph`; then `expert-sidebar`, `ledger-page`, `assistant-card`, `build-view`, `chat-view`, `build-log` one concern each. Playwright is the regression net. | L | No component over 300 lines; `npx playwright test` green on all seven projects. |
| 6.5 | Fix the five eslint warnings (`useWatch`, `router.replace`); `Promise.all` in `chats/[id]/page.tsx`. | S | `eslint .` prints nothing. |
| 6.6 | Unit tests for `lib/access.ts`, `lib/api/server.ts` (`decodeError`, `throwForStatus`), `lib/api/data.ts` (memoisation), `simulation.worker.ts` (a tick is deterministic with a fixed seed). | M | Coverage on `lib/**` reported by `vitest --coverage`. |
| 6.7 | `globals.css`: verify and remove unused tokens; group with headers. `e2e/mock-api/server.mjs` → `routes/`, `sse.mjs`, `state.mjs`. | M | — |
| 6.8 | CSP in report-only mode (`default-src 'self'; script-src 'self' 'nonce-…'; img-src 'self' data:; frame-ancestors 'none'`), then enforce once the console is quiet for a week. | M | No CSP reports in production for a week; header enforced. |

### Phase 7 — Rust CLI

| # | Task | Effort | Done when |
|---|---|---|---|
| 7.1 | `build.rs`: `tick` → `apply_event` + one method per event kind; `render_*` → `screens/build/render.rs`. Same split for `home.rs`, `app.rs`, `chat.rs`. | L | No file over 700 lines; `cargo test` green. |
| 7.2 | `sse.rs`: spec-complete event parsing (`event:`, multi-line `data:`, `data:` without space, `retry:`), with tests covering each and a CRLF case. | S | Tests. |
| 7.3 | `store.rs`: temp file with `mode(0o600)` + `rename`. | S | Test that the written file is 0600 and a simulated failure leaves the old file intact. |
| 7.4 | Delete the four `#[allow(dead_code)]` fields; fix the lossy casts; `cargo clippy --fix` the rest. | S | Pedantic-clean under the `[lints]` table. |

### Phase 8 — Tests and docs

| # | Task | Effort | Done when |
|---|---|---|---|
| 8.1 | `tests/factories.py` with `make_expert`, `make_candidate`, `make_validated`, `make_source`, `make_hit`; replace the 35+ local copies. | M | `grep -rc "def _expert" tests` is 0. |
| 8.2 | Tests for the untested modules: Typer `CliRunner` over `cli/main.py` commands; `respx` contracts for `pdf`, `exa`, `reddit`, `youtube`, `wikipedia`; `contextualizer` and `pipeline` with a stubbed model; `audit/service.py` and `experts/repository.py` against the test DB. | L | Coverage floor raised to 75% (with DB). |
| 8.3 | Replace the 13 sleeps with condition waits; promote the 27 underscore imports to public names or test via the public seam. | M | — |
| 8.4 | `docs/plans/README.md`: move the five shipped plans to "Shipped as"; optionally `docs/plans/archive/`. Remove the "54 tests" numbers from `Justfile`, `api/README.md`, `docs/development.md`. Regenerate `docs/configuration.md` (4.6). Add the pre-commit and `just format`/`just audit` recipes to `docs/development.md`. | S | — |
| 8.5 | Decide the version story (0.x vs 2.x) and make `pyproject`, the FastAPI title, the tag and the README agree. | S | — |

---

## Verification

After every phase:

```bash
just check                       # ruff, ruff format, mypy, pytest, eslint, prettier, tsc, vitest, next build
just test-db postgresql://postgres:postgres@localhost:5432/peritus_test
just build-web && just e2e-web   # after any web change
cd cli && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test
```

And before merging Phase 5.1/5.2 specifically: one real `lite` build and one chat turn against a
scratch expert, with the build log compared event-for-event against a build from `main` (the
`build_events` table makes that a SQL diff).

---

## Appendix: how the numbers were produced

All commands were run from the repository root on 2026-09-16 at `29bb5ae`.

```bash
# formatting
cd api && ruff format --check src tests | tail -1        # 168 files would be reformatted
cd cli && cargo fmt --check | grep -c '^Diff in'         # 285

# repo weight
git ls-files web | grep -cE '\.report\.(html|json)$'     # 132
git ls-files -z web | grep -zE '\.report\.' | xargs -0 du -ch | tail -1   # 64M
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
  | awk '$1=="blob"' | sort -k3 -nr | head            # node_modules blobs at the top

# dependencies
cd web && npm audit --omit=dev; npm audit --json | jq .metadata.vulnerabilities
cd api && uv export --frozen --no-dev --no-hashes --no-emit-project -o /tmp/req.txt \
  && uvx --python 3.12 pip-audit -r /tmp/req.txt
cd api && uv pip list --outdated
grep -A1 '^name = "crossterm"' cli/Cargo.lock

# code shape
cd api && ruff check --select C901,PLR0915,PLR0913,PLR0912 --statistics src
grep -rc 'except Exception' api/src --include='*.py' | sort -t: -k2 -rn | head
grep -rn 'httpx.AsyncClient(' api/src --include='*.py' | wc -l          # 27
uvx --python 3.12 vulture api/src --min-confidence 60                    # then grep-verified each hit
cd api && python -m pytest --cov=src/peritus --cov-report=term | tail

# drift
# (documented endpoints in docs/api-reference.md diffed against @router.* decorators — 57 of 58 match)
# (os.getenv keys in core/config.py diffed against .env.example — 10 missing, 1 default differs)
```
