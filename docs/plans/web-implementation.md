# Peritus Web — implementation plan

Companion to [web-production.md](web-production.md), which lists the pages. This document
covers how to build them: project setup, the auth and proxy layer, data wiring, streaming,
responsive and motion mechanics, tests, deployment, and the phase-by-phase flow with a
done-when check per phase (§13). Appearance itself is in web-design.md.

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

The motion, virtualisation, graph zoom and OTP packages are listed with versions in
[web-design.md](web-design.md) §10; install them in the same step.

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
    build/ reducer.ts
    graph/ simulation.worker.ts
    persona.ts
  components/
    ui/        shadcn (Base UI)
    shell/     rail, expert-sidebar, top-bar, sheet, nav-drawer, context-panel, stat-pill
    identity/  sigil
    + one folder per feature (experts, build, chat, ledger, graph, settings, marketing)
  hooks/                 use-media-query, use-visual-viewport, use-build-events, use-chat-stream
  proxy.ts               auth gate for (app) routes
  tests/                 vitest unit tests
  e2e/                   playwright
```

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
| `GET /api/experts/[slug]/build/usage` | `GET …/build/usage` (cost by stage for the latest job; 404 until a job exists) |
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
| `GET /api/billing/me`, `GET /api/billing/ledger` | `GET /billing/me`, `GET /billing/ledger` |
| `POST /api/admin/credits/grant` | `POST /admin/credits/grant` |

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
| `/experts` | `GET /experts`, `GET /billing/me` | `POST /api/experts/build` from the composer |
| `/experts/new` | `GET /billing/me` (tiers, allowed_tiers) | `POST /api/experts/build`; on 402 read `error.detail` |
| `/experts/[slug]` | `GET /experts/{slug}` | `DELETE` |
| `/experts/[slug]/build` | `GET …/build/status` | build stream, `POST …/build/cancel`, `GET …/build/usage` once usage is reported |
| `/experts/[slug]/sources` | `GET …/corpus-report` with search params | upload, url, delete, export link |
| `/experts/[slug]/graph` | `GET …/graph?limit=` | re-fetch on limit change |
| `/experts/[slug]/settings` | `GET /experts/{slug}` | `POST /api/experts/build {topic, tier}` (rebuild), `DELETE` |
| `/chats` | `GET /conversations` | `DELETE` |
| `/chats/[id]` | `GET /conversations/{id}`, `GET /experts/{slug}`, `GET /experts/{slug}/conversations` | chat stream, `PATCH` rename, `DELETE` |
| `/settings` | `GET /auth/me`, `GET /billing/me`, `GET /billing/ledger` | `POST /api/auth/logout` |
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

## 12. Responsive and motion mechanics

The tiers, the rules and the animation catalogue are in
[web-design.md](web-design.md) §8–9. This section is how they are built.

**Viewport and shell.**

- The root layout exports `viewport = { width: 'device-width', initialScale: 1,
  viewportFit: 'cover', interactiveWidget: 'resizes-content' }`. `viewport-fit=cover`
  unlocks `env(safe-area-inset-*)`; `interactive-widget` makes Chrome on Android shrink the
  layout viewport for the keyboard. iOS ignores it; see the keyboard note below.
- Tailwind v4's default breakpoints are the tiers: `md` 768, `lg` 1024, `xl` 1280. No
  custom breakpoints.
- The `(app)` layout is one CSS grid at `h-dvh`: `grid-cols-[56px_260px_1fr_360px]` at
  `xl`, `[56px_260px_1fr]` at `lg`, `[56px_1fr]` at `md`, `[1fr]` below. Each column is its
  own scroll container (`min-h-0 overflow-y-auto overscroll-contain`). The window never
  scrolls inside the app; only the marketing pages scroll the window.
- Layout is decided by CSS first. Both forms of a region are in the HTML and toggled with
  `hidden lg:block`, so the server render is right at every width and there is no
  post-hydration jump. JavaScript decides behaviour only (drawer or inline) through
  `useMediaQuery`, built on `useSyncExternalStore` with a server snapshot of `false`.
- Container queries: `@container` on the chat panel root, the ledger row and the stat
  tile (Tailwind's `@container` and `@md:` variants, named `chat`, `row`, `tile`). These
  components never read the viewport.

**Drawer and sheet.** One `Sheet` component (`components/shell/sheet.tsx`) on Base UI
`Dialog` for the focus trap, scroll lock and Escape, with `motion`'s `drag` for the
gesture. `side="left"` is navigation, `side="bottom"` is context. Bottom sheets take
`snapPoints={[0.5, 0.92]}` (`[0.4, 0.92]` on the graph). A sheet closes on `usePathname`
change. Edge swipe below `md`: a 20px strip on the left edge with `touch-action: pan-y`
that starts the drag. On Android the drawer pushes a history entry on open and closes on
`popstate`, so the back gesture closes it instead of navigating. `will-change: transform`
is set only while a sheet is open.

`ContextPanel` wraps the right panel: an inline `<aside>` at `xl`, an overlay `Sheet` at
`lg`, a bottom `Sheet` below. Pages pass content only and never know which form is
showing. `NavDrawer` (below `md`) renders the rail as a horizontal avatar strip above the
expert sidebar's content.

**Touch.** `globals.css` sets `--row-h: 32px; --table-row-h: 28px; --icon-btn: 32px` and,
under `@media (pointer: coarse)`, 44px / 40px / 40px plus
`input, textarea, select { font-size: 16px }`. Lists are `touch-action: pan-y`; the graph
canvas is `touch-action: none`. Hover-only affordances check `(hover: none)` and render
their tap form.

**Keyboard on iOS.** Safari resizes the visual viewport, not the layout viewport. A
`useVisualViewport` hook writes `--vv-offset` (layout height minus
`visualViewport.height`) and the composer adds it to its bottom padding. When the
composer focuses, the transcript scrolls its last message into view after the resize
event, not before.

**Motion tokens.** In `globals.css` under `@theme`: `--dur-1`, `--dur-2`, `--dur-3`,
`--ease-out`, `--ease-in`. One media block:
`@media (prefers-reduced-motion: reduce) { :root { --dur-2: 0ms; --dur-3: 0ms } }`.
Loops (`animate-pulse-dot`, `animate-caret`, `animate-sweep`) are defined under
`motion-safe:` only and have a static `motion-reduce:` form. `tw-animate-css` is imported
after Tailwind. Base UI components expose `data-open`, `data-closed`,
`data-starting-style` and `data-ending-style`; enter and exit are CSS transitions keyed on
those attributes, with no JavaScript timers.

**Motion library.** `motion` is loaded through `LazyMotion` with the `domMax` feature set
(drag and layout animations need it) via a dynamic import, with `strict` on and the `m`
components, so the initial bundle carries none of it. It is used only for: `Sheet` (drag
and the spring settle), the rail active bar (`layoutId`), the ledger row expand, and
`AnimatePresence` on the jump-to-latest pill and the 402 notice. Everything else in the
catalogue is CSS.

**Route transitions.** `next.config.ts` sets `experimental.viewTransition: true` and the
`(app)` layout wraps the centre column's children in React's `ViewTransition` with
`default="vt-fade"`, a 150ms opacity transition defined in CSS. The sigil gets
`name={`sigil-${slug}`}` on the Home card and the Overview header for the shared-element
move. React 19.2 exported the component as `unstable_ViewTransition`; check the export
name in 19.3 at install. If the flag misbehaves under Strict Mode, remove the wrapper:
the instant swap with matching skeletons is the fallback, not a JavaScript crossfade.

**Streaming render discipline.**

- `useChatStream` appends tokens to a ref and flushes once per animation frame (one
  `setState` per `requestAnimationFrame`). `status` events update a separate state so the
  status line never re-renders the transcript.
- The answer body is split at blank lines. Completed blocks go through `react-markdown`
  in a memoised `Block` component keyed by index; the trailing block renders as escaped
  text in the same typography. On `done` the whole answer re-renders once as Markdown.
- Auto-scroll: `isAtBottom` is true when the transcript is within 48px of its end,
  tracked on scroll. New content scrolls only when it is true; otherwise a *new content*
  pill appears. `overflow-anchor: none` on the list, with anchoring done by hand, so a
  growing card cannot fight the browser's own anchor.
- The build log uses the same at-bottom rule and `useVirtualizer` with a fixed 20px row
  at `md` and `measureElement` below it, where rows wrap. Fetcher groups are collapsed by
  default and count as one row.

**Fonts.** `next/font/google` Inter (variable, `display: 'swap'`, `adjustFontFallback`
on) and `geist/font/mono`, both as CSS variables on `<html>`.

**Loading and layout stability.** Every `loading.tsx` is a skeleton with the same row
heights and column widths as the page it stands in for, and each feature folder keeps its
`Skeleton` next to the component. Fixed heights: top bar 40px (44px on phones), stat tile
72px, composer minimum 48px. Buttons that show a spinner keep their width with `min-w`.
No spinner is ever the whole content of a route.

**Prefetch and optimism.** `<Link>` prefetch is on for rail avatars and sidebar rows.
Rename and delete use `useOptimistic` and roll back on error with a toast. Ledger filter
and sort changes are wrapped in `startTransition` and show the pending state by dimming
the table to 60% opacity at `--dur-1`, not with a spinner.

**Testing at widths.** Playwright projects: `desktop` (Chromium, 1440×900), `laptop`
(Chromium, 1280×800), `ipad-portrait` and `ipad-landscape` (WebKit, the `iPad (gen 7)`
device), `iphone` (WebKit, `iPhone 15`), `pixel` (Chromium, `Pixel 7`). Shared helpers in
`e2e/helpers.ts`: `expectNoHorizontalOverflow(page)` asserts `scrollWidth <= clientWidth`
on `<html>` and on the app grid; `expectTapTargets(page)` checks that every
`button, a, [role=button]` in the viewport is at least 44px tall in the phone projects. A
reduced-motion pass runs the suite once more with
`page.emulateMedia({ reducedMotion: 'reduce' })`. Lighthouse CI (`@lhci/cli` 0.15.1) runs
the mobile preset on `/`, `/login`, `/experts` and a seeded `/chats/[id]` with the budgets
from web-design.md §9 — as **two** configs, because the public pages must be audited with
no session and `/login` with one redirects away, and with **`throttlingMethod:
"devtools"`** rather than the simulated default, which charges a streamed document's whole
transfer to whichever element arrives last in it and reported 2.9s for a landing-page
paragraph that a really-throttled Chrome paints at 0.85s.

## 13. Implementation flow, end to end

Ten phases in dependency order. Each phase ends with a merge to `main`; there is no
feature-flag system, so unfinished pages are simply not linked from the shell. Responsive
behaviour and motion are built inside each phase, not in a pass at the end: a page is not
done until it passes the checklist at the bottom of this section on a phone.

### Phase 0. Foundations

1. Scaffold per §1 and pin every version from §1 and web-design.md §10. Commit the
   lockfile.
2. `app/layout.tsx`: fonts through `next/font` (§12), `next-themes` with
   `attribute="data-theme"`, `defaultTheme="system"` and `disableTransitionOnChange`, the
   `viewport` export, and sonner's `<Toaster>` positioned per §12.
3. `app/globals.css`: the token ramps from web-design.md §2 as `@theme` variables (light on
   `:root`, dark under `prefers-color-scheme` and `[data-theme=dark]`), the type and radius
   scales from §3, the `--row-h` family with its `pointer: coarse` block, the motion tokens
   and the reduced-motion block, the container names, the `tw-animate-css` import, and
   `tabular-nums` on `body`.
4. `lib/persona.ts`: `expertHue(personaName)` returning one of the twelve OKLCH pairs, and
   `personaInitials` (honorific stripped). `components/identity/sigil.tsx`: the SVG monogram
   from web-design.md §4 at 16–96px, neutral grey when there is no persona.
5. Tooling: `eslint.config.mjs`, `vitest.config.ts` in `web/`, `playwright.config.ts` with
   the six projects from §12, `e2e/helpers.ts` with the overflow and tap-target assertions,
   `AGENTS.md` with the gotchas, `.env.example`.
6. CI: `lint-web` gains `npx vitest run`. A new `e2e-web` job runs `next start` with
   `PERITUS_API_URL` pointed at a small Node mock of FastAPI (msw `setupServer` behind an
   HTTP listener, serving the fixtures) and runs Playwright across the six projects.
   Lighthouse CI runs as a non-blocking job until the pages exist.
7. `lib/api/proxy.ts`, `lib/api/sse.ts`, `lib/api/server.ts` and `lib/auth/*` per §3 and §6,
   tests first: the SSE parser (LF, CRLF, a frame split across chunks, the `id:` cursor),
   refresh-once and dead-refresh, cookie shaping.

Done when `just lint-web build-web` and `vitest run` are green, and a placeholder `(app)`
page shows the fonts and tokens at 360, 768, 1024, 1280 and 1440 with no horizontal
overflow in any Playwright project.

### Phase 1. Auth

1. The route handlers from §3, one file each under `app/api/auth/`.
2. `proxy.ts`: the gate for `(app)` paths, refreshing at the edge when only the refresh
   cookie exists.
3. `/login`: the card (`w-full max-w-[360px]` inside `px-6`), the email form on
   react-hook-form and zod, *Continue with Google* under a divider, the wordmark above.
   Errors render inside the card in a slot with reserved `min-h` so the card never jumps;
   the notice enters with the dur-2 fade and rise.
4. `/login/verify`: `input-otp` with six cells (`autoComplete="one-time-code"`,
   `inputMode="numeric"`, autofocus, paste fills every cell, submit on the sixth digit); the
   button swaps its label for a spinner at a fixed width; *Resend* with a visible countdown;
   *Use a different email*. A 429 renders the countdown from `Retry-After`. Cells shrink to
   40px below 400px.
5. The Google start and callback handlers, with `next` carried in the
   `peritus_login_next` cookie.
6. `POST /api/auth/logout` and a `useSignOut` hook that clears client state and navigates
   to `/login`.

Done when the OTP and Google round-trips pass in Playwright on `desktop` and `iphone`, the
dead-refresh path lands on `/login?next=`, and the login card shows zero layout shift when
an error appears (CLS read from an injected `web-vitals` snippet).

### Phase 2. Shell

1. `app/(app)/layout.tsx`: the grid from §12. A server component that fetches
   `GET /experts` and `GET /auth/me` once for the rail and the account avatar.
2. `components/shell/rail.tsx`: Home, 40px avatars at 10px radius (opacity 70% → 100%),
   the `motion` `layoutId` active bar, the building ring pulse, the failed dot, `+`, the
   settings gear, the account avatar. Tooltips at `lg` and up only. Scrolls when it
   overflows.
3. `components/shell/expert-sidebar.tsx`: the header with the 32px sigil and the
   `--expert-soft` wash; the rows Overview · Sources · Graph · Settings; the Chats section
   with its count, `+`, filter field and list. The Home form: All experts, Recent chats,
   Credits (hidden when `credits_enforced` is false). The active row is the `--raised` fill.
4. `components/shell/top-bar.tsx`: the 40px breadcrumb (44px on phones): the menu button
   below `md`, the 20px sigil, the persona name, the page title truncated, one primary
   action slot, one overflow slot.
5. `components/shell/sheet.tsx`, `nav-drawer.tsx` and `context-panel.tsx` per §12. Test
   the drawer in the `pixel` project with CPU throttled 4× and read frame timing from a
   `PerformanceObserver` in the test: no frame over 50ms during open or close.
6. `components/shell/stat-pill.tsx`: bottom-left at `md` and up; inside the sidebar header
   below.
7. The command palette on shadcn's `command`: ⌘K on desktop; on phones a search icon in
   the top bar opens it as a full-height bottom sheet with the field focused. Sections
   Experts · Chats · Actions.
8. `loading.tsx`, `error.tsx` (`unstable_retry`) and `not-found.tsx` for `(app)`,
   `experts/[slug]` and `chats/[id]`. The skeletons match the shell.
9. The view-transition wrapper on the centre column (§12). Confirm the Strict Mode
   double-mount does nothing odd; if it does, remove the wrapper and note it in
   `AGENTS.md`.
10. Theme: the control lives on `/settings` and in the palette's Actions.

Done when the shell renders with fixture data in all six projects with no overflow, the
drawer passes the frame-time test, Escape, backdrop, swipe, back gesture and navigation all
close it with focus returning to the menu button, and the reduced-motion pass shows no
sliding.

### Phase 3. Experts home, new expert, build page

1. `lib/api/types.ts`: `ExpertSummary`, `ExpertDetail`, `CreditState`, `EntitlementDenial`
   and every build event type from §5. Capture fixtures from a real build into
   `tests/fixtures/` and type-check them.
2. `lib/api/data.ts`: `getExperts`, `getExpert`, `getBilling`, `getBuildStatus`,
   `getBuildUsage`. Route handlers for the same plus `POST /api/experts/build`,
   `…/build/events`, `…/build/cancel` and `…/build/usage`.
3. `/experts`: `TopicComposer` (Enter submits at Auto; *Options* expands the tier picker
   inline with a grid-rows collapse), four `StatTile`s in `grid-cols-2 lg:grid-cols-4`, a
   `BuildingNow` card driven by `useBuildEvents` for any queued or building expert, the
   `ExpertCard` grid in `grid-cols-1 md:grid-cols-2 xl:grid-cols-3` with the first-paint
   stagger, `RecentChats`, and the empty state with the composer focused. Card menus are a
   visible ⋯ under `(hover: none)`.
4. `/experts/new`: the form on zod (topic 1–300), example topics as buttons that fill the
   field, `TierPicker` (shared with expert settings) as rounded cards with disabled tiers
   carrying their reason, the cost line, *Build*. Below `md` the cost line and the button
   are a sticky footer above the safe area. On 402, render `detail.message` and
   `remedy.label` in a notice under `AnimatePresence` while the form keeps its height. On
   success read the slug from the `created` event and `router.push` to the build page;
   never slugify on the client.
5. `hooks/use-build-events.ts` (§6) and `lib/build/reducer.ts`: event →
   `{rows, stages, terminal, lastSeq, chatReady, costByStage}`; unknown types ignored;
   tested against the fixtures. Fetcher search and triage results fold into collapsed
   groups.
6. `/experts/[slug]/build`: `StageTimeline` (segments plan · discover · validate · chunk ·
   graph · persona filling with scaleX; on phones a `snap-x` strip with the active segment
   at `snap-center`), `BuildLog` on `useVirtualizer` with the at-bottom rule, the *jump to
   latest* pill, the reconnecting line, *Cancel* behind a confirm dialog (a sheet on
   phones), the terminal-state rows, `ChatNow` on `chat_ready` with the one-shot ring, and
   cost by stage from `GET …/build/usage` in the `ContextPanel` once the job reports usage.
   The rail ring reads the expert's status from the same reducer.
7. `/experts/[slug]`: the document page from web-design.md §6. *Chat* is gated on
   `readiness !== 'pending'`; the failed and degraded notices; the properties block stacks
   below 480px.

Done when a real topic builds from the composer to `chat_ready` on `desktop` and `iphone`
with the log following, a 3,000-row log scrolls with no frame over 50ms on the throttled
`pixel` profile, killing the API mid-build shows the reconnecting line and resumes from
`lastSeq`, the 402 fixture renders its remedy, and the Overview reads right at 360.

### Phase 4. Chat

1. The conversation handlers from §4, the `Conversation*` types, and one fixture per chat
   event type.
2. `hooks/use-chat-stream.ts`: the per-frame token batching and separate status state from
   §12, `meta` citations, `done` → `router.refresh()`, 409 busy with the claim-window
   retry, Stop aborts, and the `sessionStorage` handoff for a new conversation's first
   question. Unit-test the reducer against the fixtures.
3. `/chats/[id]`: `Transcript` (block-split Markdown, memoised blocks,
   `content-visibility: auto` on off-screen cards, at-bottom auto-scroll, the *new content*
   pill); `AssistantCard` (20px sigil, body, action row: copy, regenerate, trail);
   `StatusLine` crossfade; `CitationChip` with a hover popover at `lg` and up and
   tap-to-sheet below; `PassagePanel` in the `ContextPanel` with the cited span
   highlighted; `Composer` (textarea sized to content with `field-sizing: content` and a
   `scrollHeight` fallback, six lines max, Enter sends and Shift+Enter breaks on desktop,
   the send button is the only submit on phones, Stop replaces Send while streaming, the
   `--expert` focus ring, the keyboard inset from `useVisualViewport`). Readiness pending
   disables the composer with a link to the build; chat-ready with the graph pending shows
   the one-line note.
4. Rename from the top-bar title (click to edit, Enter saves, optimistic). Delete from the
   sidebar row menu, optimistic, with a five-second undo toast before the DELETE is sent.
5. `/chats`: the list grouped by expert with the sigil as header, search, row menu, empty
   state. Rows are 44px on touch.
6. `ChatPanel`: the transcript and composer as one container-query component, so it
   renders in the right panel on Sources and Graph with an "about: …" chip and at full
   width on `/chats/[id]`.

Done when a 2,000-token answer streams on the throttled `pixel` profile with no frame over
50ms and the transcript stays pinned to the bottom, opening the keyboard on `iphone` keeps
the last message and the composer visible, a citation tap opens the sheet at 50% with the
span highlighted, Stop leaves a retryable partial, and the reduced-motion pass shows no
caret blink or slide.

### Phase 5. Sources ledger

1. Handlers: corpus-report (decision, sort, limit, offset passed through), export
   (streamed, `Content-Type` and `Content-Disposition` forwarded), upload (size and type
   checked, multipart passed through), url, delete.
2. `LedgerTable` at `lg` and up: 28px rows (40px on touch), sticky header, sortable
   columns, column picker, pagination, decision chips, inline 4px score bars filling on
   first paint, row select → `RowDetail` in the `ContextPanel` with the chat toggle. At
   `md`: the same table in an `overflow-x-auto` container with the title column
   `sticky left-0`. Below `md`: `LedgerCards` (title, decision, two inline bars, drop
   reason; tap opens the sheet). The filter is a segmented control everywhere; sort is a
   `select` below `lg`. Filter and sort go through `startTransition`, the table dims to 60%
   while pending, rows crossfade, and the container holds its height.
3. `AddSourceDialog` (a sheet on phones): tabs PDF · Text · URL, a drop zone with a file
   input fallback (`accept="application/pdf,.md,.txt"`, which opens Files on iOS), the
   20MB check before upload, determinate progress from `XMLHttpRequest` upload events, then
   a wait for `source_ingested` on the build stream (`useBuildEvents` with `after` set to
   the current seq), then `router.refresh()` and the new row's one-shot wash.
4. The export menu: CSV and RIS. On phones the browser handles the download from the
   streamed response.
5. The provenance banner when the report carries `unavailable_reason`s; delete behind a
   confirm; *Ask about this source* pre-fills the `ChatPanel` composer with the about chip.

Done when a 500-row ledger filters with the pending dim and no jump, the export downloads
in Playwright on `desktop` and `iphone`, a PDF upload from the `iphone` project reaches the
ingested row, and the card list at 360 shows every field the table does except rubric
version and DOI, which live in the sheet.

### Phase 6. Graph

1. The handler for `GET …/graph?limit=`, a `GraphResponse` type with `computed` and
   `unavailable_reason`, and a fixture.
2. `lib/graph/simulation.worker.ts`: `d3-force` runs in a Web Worker and posts a
   `Float32Array` of positions per tick; the main thread never runs the simulation. Under
   reduced motion the worker runs 300 ticks before posting once.
3. `GraphCanvas`: a `<canvas>` sized to its container at `devicePixelRatio`, drawn in
   `requestAnimationFrame` only while the simulation is hot or a gesture is active;
   `d3-zoom` on the canvas (`touch-action: none`) for wheel, drag, pinch and the 250ms
   programmatic transitions; hit-testing with `d3-quadtree` (a dependency of `d3-force`
   already); nodes in `--expert` with alpha by degree; labels for the top-degree nodes
   always and for others on hover at `lg` and up; the selected node in `--fg` with the
   growing ring.
4. The floating search (top-left at `lg` and up, a top-bar icon below) that focuses and
   centres the matching node, and the limit slider (top-right at `lg` and up, in the sheet
   header below) that re-fetches while keeping existing positions and reheating.
5. `NodeDetail` in the `ContextPanel` (first snap at 40% on phones): label, type, degree,
   linked passages, *Ask about this* into the `ChatPanel`.
6. Not computed: the full-centre "graph still building" state with readiness and a link to
   the build page.

Done when 300 nodes pan and pinch at 60fps on the throttled `pixel` profile with the
simulation in the worker, search focus animates to the node, changing the limit does not
scatter existing nodes, and the reduced-motion pass shows a settled layout on first paint.

### Phase 7. Settings, expert settings, admin

1. `/experts/[slug]/settings`: *Rebuild* with the shared `TierPicker`, the cost line, the
   clean-rebuild warning, then `POST /api/experts/build {topic, tier}` and navigation to
   the build page. *Danger zone*: delete with the persona name typed to confirm, in a dialog
   that is a sheet on phones with the confirm button above the safe area.
2. `/settings`: account (email, provider, member since, theme, *Sign out everywhere*) and
   credits (plan, balance, held, tier prices, the ledger table becoming a card list below
   `md`, *Request credits* as a mailto). The credits section is absent when
   `credits_enforced` is false.
3. `/admin`: `notFound()` unless `is_admin`; the grant form with its inline result.

Done when each form is usable on `iphone` with the keyboard open and the submit button
visible, the delete dialog cannot be confirmed without the typed name, and the settings
ledger reads right at 360.

### Phase 8. Landing and legal

1. `(marketing)/layout.tsx` with the site nav and footer. The window scrolls here, not an
   app grid.
2. `/`: the headline, the one-sentence job, *Sign in* and *How it works*, `BuildLogReplay`
   from a captured event fixture (fade and rise per row, intervals compressed about 8×,
   paused off-screen with `IntersectionObserver`, the final frame under reduced motion), the
   six-step strip, the "what gets recorded" table rendered with `LedgerTable` inside an
   `overflow-x-auto` container, the FAQ as native `<details>` styled with the grid-rows
   collapse, the footer. One column below `lg`.
3. `/privacy` and `/terms` at the 680px measure.
4. Metadata: title, description, a static OG image in `public/`, `robots`.

Done when the mobile Lighthouse run on `/` reports LCP under 2.5s and CLS under 0.1, the
replay pauses off-screen, and nothing on the page moves on scroll.

### Phase 9. Hardening and release

1. Security headers in `next.config.ts` (§11), the `Origin` / `Sec-Fetch-Site` check on
   every mutating handler with a unit test, `dynamic = 'force-dynamic'` and `maxDuration`
   on the streaming handlers.
2. The full Playwright suite across the six projects plus the reduced-motion pass; the
   overflow and tap-target helpers run on every route in every project.
3. A real-device pass against a written checklist: iPhone Safari (safe areas, keyboard,
   pull-to-refresh not fighting the nav drawer, `100dvh` while the toolbar collapses);
   Android Chrome (keyboard resize, the back gesture closing the drawer); iPad Safari (the
   landscape overlay panel, Split View at 50%, external-keyboard shortcuts). The checklist
   is written, at `web/docs/real-device-checklist.md`, and is **the one item of this phase
   that is still open**: it needs hardware, not an emulator.
4. The Lighthouse CI budgets become blocking.
5. Deploy: the Vercel project with `PERITUS_API_URL` and `NEXT_PUBLIC_APP_URL`, the Supabase
   Google redirect allowlist, CORS still closed, and `useReportWebVitals` posting LCP, INP
   and CLS to `POST /api/vitals` for server-side logging, so regressions on real phones are
   visible after launch. The setup is written up at `web/docs/deploy.md`, including the
   failure mode of a missing allowlist entry — GoTrue substitutes the project's Site URL
   rather than refusing, so it looks like "sign-in works and lands on the wrong host".

Done when `just check` and the e2e job are green on `main`, the real-device checklist is
signed off, and the production URL passes the Lighthouse budgets.

### The checklist every page PR must pass

1. No horizontal overflow at 360px, and nothing hidden behind the keyboard, the safe area
   or a sticky element.
2. Every control is at least 44px tall under `(pointer: coarse)` and every hover-only
   affordance has a tap form.
3. The server-rendered HTML is right at every width; no post-hydration layout jump.
4. The `loading.tsx` skeleton matches the page's row heights; CLS under 0.1 on the page.
5. Only `transform` and `opacity` animate; every animation is in the web-design.md §9
   catalogue with its duration token; reduced motion verified in devtools.
6. Long lists are virtualised past 300 rows; streamed text renders once per frame.
7. INP under 200ms on the interaction the PR adds, measured on the throttled `pixel`
   profile.
8. Keyboard reachable with a visible focus ring; drawers and sheets trap focus and return
   it.
9. Container-query components were checked in both containers they live in.
10. Fixtures updated and type-checked if a payload shape was touched.
