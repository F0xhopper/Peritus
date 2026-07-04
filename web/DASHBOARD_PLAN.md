# Peritus Web — Landing Page + Dashboard Plan

Status: planning document, no code written yet. `web/` is currently a stock
`create-next-app` scaffold (Next 16.2, React 19, Tailwind v4, no shadcn/ui).
This plan turns it into the production frontend for Peritus, backed by the
real FastAPI service in `api/`.

## 0. Design language (from references)

The three reference screenshots (Lunor/Midday-style analytics dashboard,
invoice/finance dashboard, school analytics dashboard) share a language we're
borrowing, adapted to **monospace, dark-only**, per instruction:

- Near-black canvas (`#0a0a0a`), slightly-raised card surfaces (`#111113`),
  hairline borders (`zinc-800/60`) — no drop shadows, borders do the work.
- Grayscale-first UI. Color is reserved for data (chart series, status dots)
  and one small accent for primary actions — not decorative gradients.
- Dense stat-tile rows (icon + label + big number) above the fold on every
  data page, exactly like "Active Contracts / Pending signatures / Total
  contracts" in reference 1.
- A left sidebar: brand switcher at top, flat icon+label nav, a secondary
  "pinned items" list lower down (their "Company contracts / Onboarding
  templates" folder list → our "recent/pinned experts"), and a
  contextual card at the bottom (their "Upgrade to Premium" → our "usage /
  tier" card).
- Everything runs in a monospace typeface (headings, numbers, nav labels —
  not just code). Numbers get tabular-nums so tables/stat tiles don't jitter.
- Charts are minimal: single-hue bars/lines, dashed comparison series, no
  gridlines beyond faint axis lines — will follow the `dataviz` skill's
  palette/contrast rules when actually built, not invented ad hoc.

## 1. What already exists (don't rebuild)

**Frontend (`web/`):** default scaffold only — `app/layout.tsx`,
`app/page.tsx`, `app/globals.css`. Geist Sans + Geist Mono already wired as
CSS font variables. Tailwind v4 (`@theme inline` token style, no
`tailwind.config.ts`). No shadcn, no data fetching, no auth.

**Backend (`api/`), already built and working:**

| Concern | Endpoint(s) | Notes |
|---|---|---|
| Auth | `GET /auth/status`, `POST /auth/otp`, `POST /auth/verify`, `POST /auth/refresh`, `GET /auth/me`, `POST /auth/logout` | Email-OTP (6-digit code), backend-for-frontend — client never touches Supabase directly. See `peritus-auth` memory. |
| Experts | `GET /experts`, `GET /experts/{slug}`, `DELETE /experts/{slug}`, `POST /experts/build` | Owner-scoped list/detail/delete/create. |
| Build jobs | `GET /experts/{slug}/build/events` (SSE, resumable via `?after=<seq>`), `POST /experts/{slug}/build/cancel`, `GET /experts/{slug}/build/status` | Durable Postgres-queued jobs; survives disconnects. See `peritus-build-jobs` memory. |
| Chat | `POST /experts/{slug}/chat` | SSE streaming, numbered citations `[n]`. |
| Health | `GET /health`, `GET /ready` | |

**Expert domain model** (`api/src/peritus/experts/domain.py` +
`api/schemas/experts.py`) — this is what every dashboard card/table/detail
page is built from:

```
status: queued | building | ready | failed
tier:   lite | standard | pro
fields: name, topic, persona_name, persona_bio, persona_style,
        avg_quality, key_concepts[], source_count, chunk_count,
        node_count, edge_count, source_type_counts{}, error,
        created_at, updated_at
```

There is no pricing/billing system, no notifications system, and no
multi-workspace concept — owner-scoped experts per Supabase user is the
entire data model. The plan below does not invent features the backend
can't serve (e.g. no fake "Upgrade to Premium" — tier is chosen at build
time per expert, not a subscription).

## 2. Tech stack additions

- `npx shadcn@latest init` — style `new-york`, base color `zinc`, CSS
  variables on (Tailwind v4 compatible).
- Components to pull in as needed (not all up front):
  `sidebar`, `button`, `card`, `badge`, `table`, `tabs`, `dialog`, `sheet`,
  `dropdown-menu`, `command` (⌘K / `/` search), `input`, `input-otp` (login
  code), `label`, `form` (+ `zod` + `react-hook-form`), `select`, `textarea`,
  `avatar`, `separator`, `skeleton`, `sonner` (toasts), `tooltip`,
  `progress`, `chart` (recharts wrapper), `scroll-area`, `alert`, `popover`.
- `next-themes` — installed but **forced dark** (`defaultTheme="dark"
  forcedTheme="dark"`); keeps the door open for a future light mode without
  refactoring, matches user's "simple monospace dark" instruction.
- Data fetching: `@tanstack/react-query` for expert list/detail (cache,
  refetch, mutation invalidation) + hand-rolled SSE helpers for build
  events and chat (EventSource can't do custom headers/POST, so chat uses
  `fetch` + `ReadableStream`; build events can use `EventSource` with the
  `after=<seq>` cursor for reconnection, mirroring the Rust TUI's approach).
- Auth token storage: **httpOnly cookies via Next.js route handlers**, not
  localStorage — a `/api/auth/*` proxy layer in Next sets/clears cookies
  after calling the FastAPI `/auth/*` endpoints, and `middleware.ts` gates
  the dashboard route group on cookie presence. Avoids exposing
  access/refresh tokens to JS (XSS token theft).
- Font: drop Geist Sans entirely, use Geist Mono (already present) as the
  sole `--font-sans` too — one monospace typeface everywhere, per the
  design brief, rather than introducing a separate display font.

## 3. Sitemap

**Public (marketing shell, no sidebar):**
- `/` — landing page
- `/login` — email input, requests OTP
- `/login/verify` — 6-digit code entry, exchanges for session

**Authenticated (dashboard shell, persistent sidebar), route group `(dashboard)`:**
- `/dashboard` — overview: stat tiles, builds-over-time chart, recent
  experts table, "New expert" CTA
- `/experts` — full experts table: search, filter by status/tier, sort,
  bulk delete
- `/experts/new` — build form: topic, tier picker (lite/standard/pro with
  the real tradeoffs from `ExpertConfig`), optional fetcher allowlist →
  submits `POST /experts/build` → redirects to build progress
- `/experts/[slug]` — detail shell with tabs:
  - **Overview** — persona card, key concepts, quality score, source-type
    donut, node/edge/chunk counts
  - **Chat** — streaming chat UI with citation panel
  - **Sources** — table of ingested sources (type, quality) if/when the
    backend exposes a sources listing endpoint (currently only aggregate
    counts exist — flag as backend gap, don't fabricate)
  - **Build log** — `build/events` timeline (only shown/relevant while
    `status != ready`, otherwise shows the completed log collapsed)
- `/settings` — account: email (from `/auth/me`), sign out, session info,
  and a "Connect CLI/TUI" panel explaining login reuses the same session
- `/analytics` (phase 2, stretch) — cross-expert view: builds over time,
  aggregate source-type breakdown, quality distribution — same visual
  language as reference image 1's Analytics page, but only built once
  Phase 1–5 below are done, since it's aggregation over data already shown
  per-expert.

No pricing/billing pages, no team/workspace switcher — not real backend
concepts today. If that changes, revisit.

## 4. Layout & navigation

- Sidebar via shadcn's `sidebar` block (collapsible, icon-rail on collapse).
- Top of sidebar: "Peritus" wordmark, no workspace switcher (single-tenant
  per user today).
- Primary nav: Dashboard, Experts, Analytics (phase 2), Settings.
- `/` command palette (shadcn `command`) for jumping to any expert by name —
  fed by the same `GET /experts` list already cached by react-query.
- Secondary list below nav: 3–5 most-recently-built experts with a status
  dot (queued=gray pulse, building=amber pulse, ready=green, failed=red),
  mirroring reference 1's pinned-folder list — click jumps to
  `/experts/[slug]`.
- Bottom-of-sidebar card: current plan/tier usage context — e.g. count of
  experts by tier — not a fake upsell card, since there's no billing.
- Per-page header: small breadcrumb-style icon + page name (like "↑↓
  Analytics"), page title (H1), primary action button top-right (e.g. "New
  expert").

## 5. Data & auth flow detail

1. `/login` → `POST /auth/otp {email}` (via Next route handler proxy) →
   move to step 2.
2. `/login/verify` → shadcn `input-otp` (6 digits) → `POST /auth/verify` →
   Next route handler receives `{access_token, refresh_token}`, sets them
   as httpOnly `Secure` cookies, redirects to `/dashboard`.
3. `middleware.ts` checks for the session cookie on `(dashboard)` routes;
   redirects unauthenticated users to `/login`.
4. Client-side data layer calls **Next route handlers**, not the FastAPI
   host directly, so cookies stay server-side; route handlers attach the
   bearer token server-side when proxying to FastAPI and call
   `/auth/refresh` transparently on a 401 before retrying once.
5. Sign out: route handler calls `POST /auth/logout`, clears cookies.
6. Build creation (`/experts/new` submit) and delete are React Query
   mutations that invalidate the experts list query on success.
7. Build progress page opens an `EventSource` against a Next route handler
   that streams-proxies `GET /experts/{slug}/build/events?after=<seq>`,
   reconnecting with the last seen `seq` on drop (same contract the Rust
   TUI already relies on — don't diverge from it).
8. Chat page uses `fetch(..., {method: 'POST'})` with a readable-stream
   reader (SSE-over-POST), parsing `[n]` citation markers into a side panel
   as tokens arrive.

## 6. Landing page plan

Single scroll page, dark monospace, `/` route, no sidebar:

1. **Nav** — sticky, blurred on scroll: wordmark, links (Product, Pricing
   if applicable, Docs), "Sign in" + "Get started" buttons.
2. **Hero** — monospace headline + subhead, two CTAs, and a terminal-style
   animated panel replaying something like
   `peritus build "stoic philosophy"` streaming into a build log — ties
   directly to the real product instead of generic hero art.
3. **Feature grid** (3–4 cards) — graph-grounded RAG (PropertyGraph, not
   chunk retrieval), full citations on every answer, tiered experts
   (lite/standard/pro), CLI + TUI + web access.
4. **How it works** — 3 steps mapped to the real pipeline stages (Plan →
   Discover/Validate/Graph → Chat with citations), not invented marketing
   steps.
5. **Product preview** — a static, non-interactive render of the dashboard
   overview page (reuse the real components in a read-only demo state)
   instead of a mockup image.
6. **FAQ** — accordion, real questions (what's a tier, how citations work,
   data sources used).
7. **Footer** — links, copyright.

Skip fabricated social-proof logos/testimonials — nothing to back them yet.

## 7. Component & file structure (App Router)

```
web/
  app/
    (marketing)/
      page.tsx                # landing
      layout.tsx               # marketing nav/footer shell
    login/
      page.tsx
      verify/page.tsx
    (dashboard)/
      layout.tsx               # sidebar shell, auth-gated
      dashboard/page.tsx
      experts/
        page.tsx
        new/page.tsx
        [slug]/
          layout.tsx            # tab shell
          page.tsx              # overview tab
          chat/page.tsx
          build/page.tsx
      analytics/page.tsx        # phase 2
      settings/page.tsx
    api/
      auth/{otp,verify,refresh,logout}/route.ts
      experts/route.ts
      experts/[slug]/route.ts
      experts/[slug]/build-events/route.ts   # SSE proxy
      experts/[slug]/chat/route.ts           # SSE proxy
  components/
    ui/                        # shadcn-generated, don't hand-edit style
    sidebar/                   # app sidebar composition
    experts/                   # expert-card, status-badge, tier-badge, stat-tile
    charts/                    # thin recharts wrappers per dataviz skill
    chat/                      # message list, citation panel, composer
  lib/
    api/
      client.ts                # typed fetch wrapper
      types.ts                 # mirrors Pydantic schemas
      sse.ts                   # reconnecting SSE + fetch-stream helpers
    auth/
      session.ts               # cookie read/write helpers (server-only)
  middleware.ts
```

## 8. Phased delivery

1. **Setup** — shadcn init, Tailwind theme tokens (colors/radius/font),
   drop Geist Sans, forced-dark `next-themes`, base `(dashboard)` /
   `(marketing)` route groups.
2. **Auth** — `/login`, `/login/verify`, route-handler proxy + cookie
   session, `middleware.ts` gating.
3. **Dashboard shell** — sidebar, header pattern, `/dashboard` overview
   wired to real `GET /experts` (stat tiles + recent table first, chart
   once there's enough real data to show one honestly).
4. **Experts list + build flow** — `/experts` table, `/experts/new` form →
   `POST /experts/build`, `/experts/[slug]/build` live SSE progress +
   cancel.
5. **Expert detail + chat** — overview tab, chat tab with streaming +
   citations.
6. **Settings** — account info, sign out, CLI/TUI login note.
7. **Landing page** — marketing shell + sections above.
8. **Analytics (stretch)** + polish — loading/empty/error states across
   all pages, responsive pass, a11y pass (focus states, aria on sidebar/
   command palette), then `/verify` + a manual click-through before calling
   any phase "done."

Each phase should end in a runnable, reviewable state (`npm run dev`,
click through in browser) rather than landing all at once — flag to
revisit this plan file and check items off / amend as backend gaps are
found (e.g. no per-source listing endpoint yet, noted above).
