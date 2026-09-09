# Peritus Web — production site plan

**Status:** proposal, September 2026. Replaces the removed `web/`.

Three rules that apply everywhere:

1. **Gate chat on `readiness`, not `status`.** Chat works at `chat_ready`.
2. **`null` means "not recorded", never zero.**
3. **No checkout exists.** The only credit remedy is "request credits". Never show a fake upgrade.

---

## Pages

### Public

| Route | Purpose | Features |
|---|---|---|
| `/` | Explain the product, get people to sign in | Headline, how it works (6 steps), what gets recorded (the ledger table), FAQ, sign-in button |
| `/login` | Sign in | Email → 6-digit OTP, Google button. Handles 429 and invite-only. |
| `/privacy`, `/terms` | Required for Google OAuth and production | Static text |

### App (sidebar shell)

| Route | Purpose | Features |
|---|---|---|
| `/experts` | Home. My experts | Topic composer at top ("Build an expert on…"), list of experts with status/readiness, credit balance. `GET /experts`, `GET /experts/billing/me` |
| `/experts/new` | Build form | Topic, tier (Auto default; lite/standard/pro with credit cost), submit. On 402 render `detail.message` + `remedy`. Navigate to the slug from the `created` event. `POST /experts/build` |
| `/experts/[slug]` | Expert overview | Persona header, **Chat** (readiness-gated), stat tiles, key concepts, source types, error/retry if failed. Tabs: Overview · Chat · Sources · Graph · Settings |
| `/experts/[slug]/build` | Live build | Stage timeline, event log (keep/drop rows with scores + reason), reconnect with `?after=seq`, cancel, cap-exceeded state ("credits refunded"), "Chat now" on `chat_ready`. `GET …/build/events`, `/build/status`, `POST …/build/cancel` |
| `/chats/[id]` | Conversation | Streaming answer, `[n]` citations opening a passage panel, stop, status line, list of this expert's chats, rename/delete. `POST /experts/{slug}/conversations`, `POST /conversations/{id}/messages` |
| `/chats` | All conversations | List, continue, delete. `GET /conversations` |
| `/experts/[slug]/sources` | The ledger | Table of every source, kept or dropped: title, type, quality, relevance, drop reason, discovered via, concepts. Filter All/Accepted/Rejected. **Export CSV / RIS.** Add source (PDF, text, URL). Delete source. `GET …/corpus-report`, `…/corpus-report/export`, `POST …/sources/upload`, `…/sources/url` |
| `/experts/[slug]/graph` | Knowledge graph | Force-directed graph of concepts and relationships (d3-force on canvas). Node size by degree, click a node to see its label, type and linked passages, search to focus a node, limit slider. If `computed` is false show "graph still building", never an empty graph. `GET /experts/{slug}/graph?limit=` |
| `/experts/[slug]/settings` | Manage | Rebuild at a tier (warn it rebuilds clean), delete. `POST /experts/build`, `DELETE /experts/{slug}` |
| `/settings` | Account | Email, sign out, credits: balance, held, ledger, "Request credits" (mailto). `GET /auth/me`, `/experts/billing/me`, `/experts/billing/ledger` |
| `/admin` | Operator (bootstrap admin only) | Grant credits by email. `POST /experts/admin/credits/grant` |

Deliberately **not** pages: public catalog, evidence report, answer audits, method page, plans page, changelog, CLI page. Add later if users ask.

---

## Shell

- Sidebar: Experts, Chats, Settings (Admin if admin). "Building now" tile while a build runs. Recent chats. Credit balance at the bottom (hidden if `credits_enforced` is false).
- ⌘K palette to jump to an expert or chat.
- Light and dark, system default.
- Per-segment `loading.tsx`, `error.tsx`, `not-found.tsx`. Others' experts are 404.

---

## Stack

Next 16 App Router, React 19, TypeScript, Tailwind v4, shadcn/ui (Base UI), react-hook-form + zod, sonner, react-markdown, d3-force (graph page only).

Auth: backend-for-frontend. Next route handlers under `/api/*` hold the session in httpOnly cookies, add the bearer, refresh once on 401, and pass SSE through. `middleware.ts` redirects unauthenticated app routes to `/login?next=`.

Known gotchas from the previous site: SSE frames end with `\r\n\r\n`; don't abort fetches on unmount (Strict Mode); Base UI `Button` needs `nativeButton={false}` with `render={<Link/>}`; `error.tsx` receives `unstable_retry`, not `reset`; async route `params`, run `next typegen`.

Tests: Vitest for the SSE parser, the proxy refresh, and 402 rendering; Playwright for login → build → chat → export.

---

## Backend gaps (don't fake these)

| Gap | What the site does |
|---|---|
| No checkout | "Request credits" mailto |
| No account deletion, rename, or persona regeneration | Not offered |
| No build-complete email | User checks back; the log is durable |

---

## Build order

1. Shell, auth, proxy, error/loading conventions.
2. New expert + build page + experts home.
3. Chat.
4. Sources ledger with export.
5. Graph.
6. Settings, admin, landing, legal.
