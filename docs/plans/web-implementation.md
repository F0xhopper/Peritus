# Peritus Web — implementation plan

Companion to [web-production.md](web-production.md), which lists the pages. This document
covers how to build them: project setup, the auth and proxy layer, data wiring, streaming,
tests, and deployment. Nothing here is about appearance.

---

## 1. Project setup

Versions below were checked against the npm registry on 2026-09-09. Pin them in
`package.json`; do not take "latest" blindly, two of the latest majors are not usable here.

| Package | Use | Why this one |
|---|---|---|
| `next` 16.3.4 | framework | Current stable (3 Aug 2026). Needs Node ≥ 20.9. |
| `react`, `react-dom` 19.3.0 | | Current stable; Next 16.3 peer range `^19`. |
| `typescript` **6.0.3**, not 7 | | TypeScript 7 (the Go compiler) is out and Next 16.3 can type-check with it, but `typescript-eslint` 8.70 pins `typescript >=4.8.4 <6.1.0`, and `eslint-config-next` depends on it. Stay on 6.0.x until typescript-eslint supports 7. `create-next-app` still scaffolds `^5`; bump to 6.0.3 after scaffold. |
| `tailwindcss`, `@tailwindcss/postcss` 4.3.3 | styling | |
| `shadcn` 4.21.0 (CLI) | components | v4 CLI (Mar 2026). Base UI has been the default since Jul 2026, so `npx shadcn init` gives Base UI with no flag. |
| `@base-ui/react` 1.8.0 | primitives | pulled in by shadcn |
| `lucide-react` 1.43.0 | icons | |
| `next-themes` 0.4.6 | theme | |
| `react-hook-form` 7.87.0, `@hookform/resolvers` 5.9.1, `zod` 4.6.0 | forms | resolvers 5.x supports zod 4 |
| `sonner` 2.0.8 | toasts | |
| `react-markdown` 10.1.0, `remark-gfm` 4.0.1 | answers | |
| `d3-force` 3.0.0, `@types/d3-force` 3.0.10 | graph page | |
| `eslint` 10.10.0, `eslint-config-next` 16.3.4 | lint | config-next peer `eslint >=9`, so ESLint 10 is fine |
| `vitest`, `@vitest/coverage-v8` **5.0.0** | unit tests | Major released; needs Node ≥ 22.12 (this machine runs 26). Nothing here relied on the v4 APIs that changed, so start on 5. |
| `@playwright/test` 1.63.0, `@next/playwright` 16.3.4 | e2e | `@next/playwright` ships the `instant()` navigation helper |
| `msw` 2.15.0 | API mocks in tests | |
| `@types/node` 22.x, `@types/react`, `@types/react-dom` 19.3.0 | | |

Not used: `@tanstack/react-query` (5.102). Server components plus `router.refresh()` cover
this app; add it only if client-side caching becomes a measured problem.

```
npx create-next-app@16.3.4 web --ts --app --tailwind --eslint --src-dir=false --import-alias "@/*"
cd web
npm i typescript@6.0.3 -D                 # scaffold gives ^5
npx shadcn@4.21.0 init                    # Base UI by default
npm i react-hook-form@7.87.0 @hookform/resolvers@5.9.1 zod@4.6.0 sonner@2.0.8 \
      react-markdown@10.1.0 remark-gfm@4.0.1 d3-force@3.0.0 next-themes@0.4.6
npm i -D vitest@5.0.0 @vitest/coverage-v8@5.0.0 @playwright/test@1.63.0 @next/playwright@16.3.4 \
      msw@2.15.0 @types/d3-force@3.0.10
```

- `web/AGENTS.md`: Next 16.3's `next dev` now writes and maintains a version-matched
  AGENTS.md block pointing at the bundled docs in `node_modules/next/dist/docs/`. Keep that
  block and add the project gotchas under it: route `params` are async; `proxy.ts`
  replaces `middleware.ts`; Base UI `Button` needs `nativeButton={false}` with `render`;
  error boundaries (see §9).
- Env (`web/.env.example`): `PERITUS_API_URL` (server-only, default
  `http://localhost:8000`), `NEXT_PUBLIC_APP_URL` (for OAuth redirect), `NODE_ENV`.
- Justfile already has `web`, `lint-web`, `build-web`; keep them working. CI runs
  `npx eslint . && npx tsc --noEmit && npx next build`.

## 2. Directory layout

```
web/
  app/
    (marketing)/           layout, page (landing), privacy, terms
    login/                 page, verify/page
    (app)/                 layout (shell), experts/, chats/, settings/, admin/
    api/                   route handlers (BFF proxy) — see §4
    error.tsx global-error.tsx not-found.tsx
  lib/
    api/   server.ts proxy.ts data.ts sse.ts types.ts
    auth/  cookies.ts session.ts refresh.ts
  components/            ui/ (shadcn) + feature folders
  hooks/
  proxy.ts               auth gate for (app) routes
  tests/                 vitest unit tests
  e2e/                   playwright
```

Reuse the previous site's `lib/api/*` and `lib/auth/*` from git history
(`git show ea26fa0:web/lib/...`). They were correct; the rest of the old site is not
needed.

## 3. Auth layer (backend-for-frontend)

The browser never holds a Supabase token. Two httpOnly cookies carry the session:
`peritus_access_token` (max-age = `expires_in` − 60 s) and `peritus_refresh_token`
(30 days). Both `Secure` in production, `SameSite=Lax`, `path=/`.

Route handlers, each a thin call to FastAPI:

| Handler | Calls | Effect |
|---|---|---|
| `POST /api/auth/otp` | `POST /auth/otp {email}` | pass through 429 / signup-disabled |
| `POST /api/auth/verify` | `POST /auth/verify {email, token}` | set cookies |
| `POST /api/auth/refresh` | `POST /auth/refresh {refresh_token}` | rotate cookies |
| `POST /api/auth/logout` | `POST /auth/logout` | clear cookies (global revoke) |
| `GET  /api/auth/me` | `GET /auth/me` | `{id, email, is_admin}` |
| `GET  /api/auth/google/start` | `GET /auth/oauth/authorize?provider=google&redirect_to=…` | generate PKCE verifier (43–128 chars), store in `peritus_pkce_verifier` cookie (10 min), store `next` in `peritus_login_next`, 302 to the returned URL |
| `GET  /api/auth/callback` | `POST /auth/oauth/exchange {auth_code, code_verifier}` | set cookies, clear PKCE cookies, 302 to `next` |

`proxy.ts` (Next 16 middleware): for `(app)` paths, if neither cookie exists → 302
`/login?next=<path>`. If only the refresh cookie exists, call refresh here and write the
rotated cookies onto the response, because server components cannot write cookies.

`lib/api/proxy.ts`: `proxyFetch(path, init)` attaches the bearer, on 401 refreshes once and
retries, throws `NotAuthenticatedError` when the refresh token is dead. `proxyJson<T>`
decodes and throws `ApiError(status, message)` on non-2xx. Structured `detail` objects
(the 402 payload) are preserved on the error as `detail`, not flattened to text.

`lib/api/data.ts`: server-component fetchers (`getExperts`, `getExpert(slug)`, …). Each
catches `NotAuthenticatedError` → `redirect('/login?next=')`, and 404 → `notFound()`.
Any wrapper that swallows errors must rethrow errors whose `digest` starts with `NEXT_`.

## 4. Proxy route handlers

One route handler per backend endpoint the browser needs. Each is `proxyFetch` plus
body/query pass-through; streaming ones return `new Response(res.body, {headers})`.

| Handler | Upstream |
|---|---|
| `GET /api/experts` | `GET /experts` |
| `POST /api/experts/build` | `POST /experts/build` (streams SSE) |
| `GET /api/experts/[slug]` | `GET /experts/{slug}` |
| `DELETE /api/experts/[slug]` | `DELETE /experts/{slug}` |
| `GET /api/experts/[slug]/build/events?after=` | `GET …/build/events` (streams) |
| `GET /api/experts/[slug]/build/status` | `GET …/build/status` |
| `POST /api/experts/[slug]/build/cancel` | `POST …/build/cancel` |
| `GET /api/experts/[slug]/sources` | `GET …/corpus-report` (decision, sort, limit, offset) |
| `GET /api/experts/[slug]/sources/export?format=` | `GET …/corpus-report/export` (stream file, forward `Content-Disposition`) |
| `POST /api/experts/[slug]/sources/upload` | `POST …/sources/upload` (multipart pass-through, 20 MB cap) |
| `POST /api/experts/[slug]/sources/url` | `POST …/sources/url` |
| `DELETE /api/experts/[slug]/sources/[id]` | `DELETE …/sources/{source_id}` |
| `GET /api/experts/[slug]/graph?limit=` | `GET …/graph` |
| `POST /api/experts/[slug]/conversations` | `POST /experts/{slug}/conversations` |
| `GET /api/experts/[slug]/conversations` | `GET /experts/{slug}/conversations` |
| `GET /api/conversations` | `GET /conversations` |
| `GET/PATCH/DELETE /api/conversations/[id]` | same |
| `POST /api/conversations/[id]/messages` | `POST …/messages` (streams) |
| `GET /api/billing/me`, `GET /api/billing/ledger` | `GET /experts/billing/me`, `…/ledger` |
| `POST /api/admin/credits/grant` | `POST /experts/admin/credits/grant` |

Mutating handlers check `Origin`/`Sec-Fetch-Site` is same-origin (CSRF guard on top of
`SameSite=Lax`). Run `npx next typegen` after adding routes so `RouteContext` unions are
current.

## 5. Types

`lib/api/types.ts` mirrors `api/src/peritus/api/schemas/*.py` by hand (no codegen step
exists). Keep these enums in sync with the API:

- `ExpertStatus` = queued | building | ready | failed
- `Readiness` = pending | chat_ready | graph_ready
- `ExpertTier` = lite | standard | pro
- Build events (`type` field): created, build_started, execution_mode, plan_ready,
  discovery_started, round_started, fetcher_done, triage_done, fetch_progress,
  fetch_done, dedup_done, resolve_progress, validate_done, source_validated,
  source_reviewed, source_ingested, snowball_done, feedback_queries, coverage_report,
  discovery_done, corpus_warning, stage, chat_ready, graph_batch_done,
  entities_resolved, claims_reconciled, graph_ready, persona_ready, stage_degraded,
  retry, error, cancelled, done. Unknown types must be ignored, not thrown.
- Chat events: status, token, meta (citations `{n, label}`), retrieval_audit, done.
- `EntitlementDenial` = `{code: 'insufficient_credits' | 'tier_not_in_plan', message,
  required_credits, available_credits, tier, plan, allowed_tiers?, remedy: {kind, label,
  detail}}`.

Capture one real payload per shape into `tests/fixtures/*.json` and type-check the
fixtures against the interfaces, so a schema drift fails `tsc`.

## 6. Streaming

`lib/api/sse.ts`: `streamSse<T>(path, init)` reads a fetch body through
`TextDecoderStream`, splits frames on `/\r?\n\r?\n/` (sse-starlette emits CRLF), parses
`id:` and `data:` lines, yields `{id, data}`. Never use `EventSource`: chat is a POST.

**Build stream.** Hook `useBuildEvents(slug)`:
1. Open `GET /api/experts/[slug]/build/events?after=<lastSeq>` (`lastSeq` starts at 0, or
   from the first event's `seq` when arriving via `POST /experts/build`).
2. Append events to state; track `lastSeq` from the SSE `id:`.
3. On stream close without a terminal event (`done`, `error`, `cancelled`), wait with
   backoff (1 s → 10 s) and reopen with `after=lastSeq`.
4. Stop on a terminal event; then `router.refresh()` so server data updates.
5. Do not abort on unmount (Strict Mode double-mounts kill the first request).

**Chat stream.** Hook `useChatStream(conversationId)`:
1. `POST /api/conversations/[id]/messages {question}`.
2. Concatenate `token` events; hold `meta` citations; on `done` call `router.refresh()`.
3. 409 → surface "busy", allow retry after the 3-minute claim window.
4. A Stop button aborts the controller; nothing else does. The server persists the
   partial as interrupted.
5. First message of a new conversation: create via `POST /api/experts/[slug]/conversations`,
   navigate to `/chats/[id]`, and hand the question off through `sessionStorage` (survives
   the navigation, avoids an unmount abort).

## 7. Page data wiring

Server components fetch first paint through `lib/api/data.ts`; client components mutate
through `/api/*` with `fetch` and then `router.refresh()`. No client cache library is
needed at this size.

| Page | Server fetch | Client calls |
|---|---|---|
| `/experts` | `GET /experts`, `GET /experts/billing/me` | `POST /api/experts/build` from the composer |
| `/experts/new` | `GET /experts/billing/me` (tiers, allowed_tiers) | `POST /api/experts/build`; on 402 read `error.detail` |
| `/experts/[slug]` | `GET /experts/{slug}` | `DELETE` |
| `/experts/[slug]/build` | `GET …/build/status` | build stream, `POST …/build/cancel` |
| `/experts/[slug]/sources` | `GET …/corpus-report` with search params | upload, url, delete, export link |
| `/experts/[slug]/graph` | `GET …/graph?limit=` | re-fetch on limit change |
| `/experts/[slug]/settings` | `GET /experts/{slug}` | `POST /api/experts/build {topic, tier}` (rebuild), `DELETE` |
| `/chats` | `GET /conversations` | `DELETE` |
| `/chats/[id]` | `GET /conversations/{id}`, `GET /experts/{slug}`, `GET /experts/{slug}/conversations` | chat stream, `PATCH` rename, `DELETE` |
| `/settings` | `GET /auth/me`, `GET /experts/billing/me`, `GET /experts/billing/ledger` | `POST /api/auth/logout` |
| `/admin` | `GET /auth/me` (403-equivalent: `notFound()` unless `is_admin`) | `POST /api/admin/credits/grant` |

Rules enforced in code, not copy:
- Chat entry is enabled when `readiness !== 'pending'`. Never read `status` for this.
- Build submit navigates to the slug from the `created` event. No client-side slugify.
- Graph and sources pages check `computed` / `unavailable_reason` before rendering counts.
- `credits_enforced === false` hides every credit element.
- Any 404 from the API on an expert or conversation becomes `notFound()`.

## 8. Uploads and export

- Upload handler reads `request.formData()`, checks size ≤ 20 MB and type ∈
  {pdf, text/plain, text/markdown}, forwards as multipart to FastAPI. Ingest runs on the
  worker; the sources page polls `GET …/build/status` (or reopens the build stream) until
  the `source_ingested` event, then refreshes.
- Export handler forwards `format=csv|ris`, streams the body, and passes
  `Content-Type` and `Content-Disposition` through unchanged.

## 9. Error handling

- Route-level `error.tsx` / `global-error.tsx` receive `unstable_retry`, not `reset`. For
  boundaries inside a page (the build log, the chat transcript) use Next 16.3's
  `catchError` from `next/error`: it does not swallow `notFound()` / `redirect()` and its
  `retry()` re-fetches the failed server components.
- `ApiError` → toast with `message`; 402 → structured panel from `detail`; 401 →
  `redirect('/login')`; 404 → `notFound()`; 409 → chat busy state; 429 → countdown from
  `Retry-After` when present.
- Server components wrap fetches in `safely()` that rethrows `NEXT_*` digests.

## 10. Tests

- **Vitest**: SSE frame parser (LF, CRLF, split-across-chunks, `id:` cursor); proxy
  refresh-once and dead-refresh path (msw mocks FastAPI); 402 detail preservation;
  cookie shaping (max-age margin, secure flag); readiness gate helper; build-event
  reducer ignores unknown types and detects terminal events.
- **Fixtures**: captured JSON for expert detail, corpus-report, graph, billing/me,
  ledger, 402 detail, one build event per type, one chat event per type. Type-checked.
- **Playwright** (against a local API with `AUTH_ENABLED` off, or a seeded test user):
  login by OTP, create expert → build page receives events → chat enabled at
  `chat_ready`, send a message and receive citations, ledger export downloads, delete.
- CI: `just check` runs lint, tsc, and `next build`; add `vitest run` to `lint-web`.
- Vitest 5 no longer searches parent directories for its config; keep `vitest.config.ts`
  in `web/`.

## 11. Deployment

- Web on Vercel (or the same host as the API behind a reverse proxy). Only
  `PERITUS_API_URL` and `NEXT_PUBLIC_APP_URL` are set per environment.
- API must list the web origin in `CORS_ALLOW_ORIGINS` only if the browser ever calls it
  directly; with the BFF it does not, so keep CORS closed.
- Supabase: enable Google provider, allowlist `https://<app>/api/auth/callback`, and keep
  `{{ .Token }}` in the magic-link template for OTP.
- `next.config.ts`: `turbopackFileSystemCache` is on by default in 16.3 (faster CI builds,
  cache `web/.next/cache`); `cacheComponents` / `partialPrefetching` stay off, this app is
  dynamic per user and gains nothing from them; `headers()` for HSTS, `X-Content-Type-Options`, `Referrer-Policy`,
  `X-Frame-Options: DENY`; `serverActions` unused; `images` unconfigured.
- Streaming route handlers need `export const dynamic = 'force-dynamic'` and, on Vercel,
  `maxDuration` set high enough for a build tail (builds run for minutes; the client
  reconnects, so 60 s per connection is acceptable).

## 12. Order of work

1. Scaffold, AGENTS.md, env, lint/CI. Restore `lib/auth/*`, `lib/api/proxy.ts`,
   `lib/api/sse.ts` from history with unit tests passing.
2. Auth handlers, `proxy.ts` gate, login pages, `/settings` sign-out.
3. Experts list, new expert with 402 handling, build stream hook and page.
4. Conversations handlers, chat stream hook, `/chats/[id]`, `/chats`.
5. Sources page: corpus-report table, export, upload, url, delete.
6. Graph handler and page.
7. Expert settings (rebuild, delete), admin grant.
8. Landing, privacy, terms; security headers; Playwright suite; deploy.
