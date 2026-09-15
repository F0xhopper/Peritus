# Peritus Web — production site plan

**Status:** proposal, September 2026.

Four rules that apply everywhere:

1. **Gate chat on `readiness`, not `status`.** Chat works at `chat_ready`.
2. **`null` means "not recorded", never zero.**
3. **No checkout exists.** The only credit remedy is "request credits". Never show a fake upgrade.
4. **Every page works at 360px and under reduced motion.** The layout tiers are in
   [web-design.md](web-design.md) §8 and the motion catalogue in §9. Neither is optional
   per page, and the build flow in [web-implementation.md](web-implementation.md) §13 has a
   phone check at the end of every phase.

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
| `/experts` | Home. My experts | Topic composer at top ("Build an expert on…"), list of experts with status/readiness, credit balance. `GET /experts`, `GET /billing/me` |
| `/experts/new` | Build form | Topic, tier (Auto default; lite/standard/pro with credit cost), submit. On 402 render `detail.message` + `remedy`. Navigate to the slug from the `created` event. `POST /experts/build` |
| `/experts/[slug]` | Expert overview | Persona header, **Chat** (readiness-gated), stat tiles, key concepts, source types, error/retry if failed. Sidebar rows: Overview · Sources · Graph · Settings, plus the chat list |
| `/experts/[slug]/build` | Live build | Stage timeline, event log (keep/drop rows with scores + reason), reconnect with `?after=seq`, cancel, cap-exceeded state ("credits refunded"), "Chat now" on `chat_ready`. `GET …/build/events`, `/build/status`, `/build/usage`, `POST …/build/cancel` |
| `/chats/[id]` | Conversation | Streaming answer, `[n]` citations opening a passage panel, stop, status line, list of this expert's chats, rename/delete. `POST /experts/{slug}/conversations`, `POST /conversations/{id}/messages` |
| `/chats` | All conversations | List, continue, delete. `GET /conversations` |
| `/experts/[slug]/sources` | The ledger | Table of every source, kept or dropped: title, type, quality, relevance, drop reason, discovered via, concepts. Filter All/Accepted/Rejected. **Export CSV / RIS.** Add source (PDF, text, URL). Delete source. `GET …/corpus-report`, `…/corpus-report/export`, `POST …/sources/upload`, `…/sources/url` |
| `/experts/[slug]/graph` | Knowledge graph | Force-directed graph of concepts and relationships (d3-force on canvas). Node size by degree, click a node to see its label, type and linked passages, search to focus a node, limit slider. If `computed` is false show "graph still building", never an empty graph. `GET /experts/{slug}/graph?limit=` |
| `/experts/[slug]/settings` | Manage | Rebuild at a tier (warn it rebuilds clean), delete. `POST /experts/build`, `DELETE /experts/{slug}` |
| `/settings` | Account | Email, sign out, credits: balance, held, ledger, "Request credits" (mailto). `GET /auth/me`, `/billing/me`, `/billing/ledger` |
| `/admin` | Operator (bootstrap admin only) | Grant credits by email. `POST /admin/credits/grant` |

Deliberately **not** pages: public catalog, evidence report, answer audits, method page, plans page, changelog, CLI page. Add later if users ask.

---

## Page by page

Layout terms (rail, expert sidebar, centre, right panel, tokens) are defined in
[web-design.md](web-design.md). Endpoints are in the tables above and in
[web-implementation.md](web-implementation.md).

### `/` — Landing

**Design.** Marketing shell, no rail. Dark canvas, 640px reading column, 32px headline,
document typography. The hero's right side is a real build log replaying from a captured
event stream: keep/drop rows in monospace with scores and reasons scrolling in. No
imagery, no gradients.

**Features.** Headline and one-sentence job statement; primary button *Sign in*, secondary
*How it works* (anchor). Six-step "what happens when you type a topic" strip. "What gets
recorded" rendered with the ledger table component (question / what is recorded). Short
FAQ (what a tier is, how citations work, which source kinds are searched, what it is not).
Footer with Privacy, Terms, GitHub.

### `/login` and `/login/verify`

**Design.** Centered 360px card on the canvas, 12px radius, the wordmark above it.
Nothing else on the page.

**Features.** Email field and *Continue* → OTP request. *Continue with Google* button
under a divider. Verify step: six-cell code input (autofocus, paste fills all cells,
submits on the sixth digit), *Resend* with a cooldown, *Use a different email*. Errors as
a rounded `--bad` tinted notice inside the card: wrong code, expired code, rate limited
(countdown), signups disabled (invite-only message). On success redirect to `next` or
`/experts`.

### `/privacy`, `/terms`

**Design.** Marketing shell, document typography, 680px measure. Static.

### `/experts` — Home

**Design.** Rail has Home selected. Expert sidebar shows *All experts*, *Recent chats*,
*Credits*. Centre is a document-style page titled with the user's first name or "Home".

**Features.** Topic composer at the top of the centre ("Build an expert on…", Enter
submits at Auto tier; a small *Options* link opens the tier picker inline). Four stat
tiles: experts, ready, building, credits (hidden when not enforced). *Building now* card
for any queued/building expert with stage and elapsed time, live from the build stream,
clicking opens the build page. Expert cards grid: sigil, persona name, topic, status as
coloured text, sources and quality as tabular numbers; card menu with Chat, Sources,
Settings, Delete. Recent chats list (title, expert sigil, relative time). Empty state
for a new account: one sentence and the composer focused.

### `/experts/new` — Build

**Design.** Centre only, 560px column, document title "New expert". Opened from the rail
`+` or the Home composer with the topic carried over.

**Features.** Topic (1–300 chars) with three example topics as clickable text. Tier
picker: *Auto* selected, then lite / standard / pro as rounded cards showing source
budget, passages per answer, credit cost, spend cap; tiers outside `allowed_tiers`
disabled with the reason. Cost line: "holds N credits, you have M". *Build* button. On
402, the form stays and a rounded notice shows `detail.message` with the single
`remedy.label` action. On success, navigate to the new slug's build page using the
server's slug from the `created` event.

### `/experts/[slug]` — Overview

**Design.** The document page from web-design.md §6: sigil, persona name as title, topic
as description, properties block, prose sections. Right panel closed by default.

**Features.** *Chat* primary button in the top bar, enabled when readiness is not
pending; while building it reads "Building…" and links to the build page. Properties:
Tier, Status, Readiness, Sources (accepted / considered), Quality, Built, each value as
coloured text. Sections: About (bio and voice line), Key concepts (coloured words linking
to the ledger filtered by concept), How this corpus was assembled (method statement,
acceptance rate, rubric version, stop reason), Source types (inline counts). Failed
build: `--bad` notice above the properties with the error and a *Rebuild* button.
Degraded persona: `--warn` notice saying the corpus is usable and the persona can be
regenerated by rebuilding.

### `/experts/[slug]/build` — Build log

**Design.** Centre is the log: monospace, 12px, full width. A stage timeline runs across
the top as a row of rounded segments that fill in `--expert` as stages complete. Right
panel holds cost by stage once available. The rail avatar pulses while this runs.

**Features.** Rows in order with time, stage, message; keep rows with ✓ in `--ok`, drop
rows with × in `--bad`, scores right-aligned; search queries and triage results as
collapsed groups per fetcher. Live tail with auto-scroll and a "jump to latest" pill when
scrolled up. Reconnects on drop with a "reconnecting" line, resuming from the last
sequence. *Cancel* in the top bar with confirmation. Terminal states rendered
distinctly: done (link to Chat), failed (error and *Retry*), cancelled, cap exceeded
("stopped at the spend cap, credits refunded, retrying unchanged will not help"),
degraded (warning row, expert still usable). *Chat now* appears the moment `chat_ready`
arrives while later stages continue.

### `/chats/[id]` — Conversation

**Design.** Centre is the transcript at 720px: assistant answers as rounded cards with
the 20px sigil, user prompts as plain text between them. Composer pinned to the bottom,
focus ring in `--expert`. Right panel shows the cited passage when a citation is
selected. Expert sidebar highlights this chat in its list.

**Features.** Streaming answer with a status line (planning → searching → checking
coverage → composing) above the growing card. Citations as `[n]` chips; hover previews
the passage, click opens it in the right panel with source title, type, scores, and a
link to its ledger row. Card action row: copy, regenerate, show trail (subqueries,
follow-ups, coverage verdict). *Stop* replaces *Send* while streaming. Interrupted
answers keep the partial text with a *Retry* link. Busy (409) shows "still answering"
and re-enables after the claim window. Rename via the title in the top bar, delete from
the sidebar row menu. Readiness pending: composer disabled with a link to the build.
Chat-ready but graph pending: a one-line note under the composer.

### `/chats` — All conversations

**Design.** Centre list, grouped by expert with the sigil as the group header.

**Features.** Title, expert, last message time; search by title; row menu with Continue,
Rename, Delete. Empty state points at the experts on the rail.

### `/experts/[slug]/sources` — Ledger

**Design.** Full-width table in the centre, 28px rows, sticky header, `--border-soft`
dividers. Decision filter as a segmented control above the table. Right panel holds the
chat by default so a user can ask about a row; selecting a row puts its detail in the
right panel instead, with a toggle back to chat.

**Features.** Columns: title, type, decision (chip), quality, relevance (number plus a
4px inline bar), drop reason, discovered via, concepts, rubric version, DOI; column
picker. Filter All / Accepted / Rejected with true totals. Sort by decision, quality,
relevance, title, type, discovered via, added. Pagination. Row detail: key claims,
difficulty, content type, first-pass vs review scores, snowball trail, full-text method,
identifiers, link out; *Ask about this source* pre-fills the chat composer. *Export*
menu: CSV, RIS. *Add source* opens a rounded dialog with three tabs: PDF (drop zone, 20 MB
limit, OCR note), Text or Markdown, URL; progress shown until the ingest event arrives,
then the row appears with discovered-via "upload". Delete with confirmation. Provenance
banner when older builds lack fields, stating which and why.

### `/experts/[slug]/graph` — Knowledge graph

**Design.** Centre is a canvas on `--bg` with a faint dotted grid. Nodes filled in
`--expert` with alpha by degree, edges in `--border`, selected node in `--fg`. A
floating search field top-left and a limit slider top-right, both on rounded `--raised`
surfaces. Right panel shows the selected node.

**Features.** Force layout, pan and zoom, hover labels, permanent labels for the
top-degree nodes. Click a node: right panel shows label, type, degree, linked passages,
and *Ask about this* which pre-fills the chat. Search focuses and centres a node. Limit
slider re-fetches. Not computed: full-centre state "graph still building" with readiness
and a link to the build page, never an empty canvas.

### `/experts/[slug]/settings` — Expert settings

**Design.** Centre, 560px column, document title "Settings", sections separated by
space, no cards.

**Features.** *Rebuild*: tier picker (same component as New expert), cost line, warning
that a rebuild deletes sources, passages, and graph and rebuilds clean, then *Rebuild*.
*Danger zone*: delete with the persona name typed to confirm.

### `/settings` — Account

**Design.** Rail settings gear selected; expert sidebar shows Account and Credits as
rows. Centre, 560px column.

**Features.** Account: email, sign-in provider, member since, theme (system / light /
dark), *Sign out everywhere*. Credits: plan, balance, held (labelled "reserved by a
running build"), tier price table, ledger table (type, delta, tier, job link to the
build page, reason, real cost), *Request credits* mailto. The credits section is hidden
when not enforced.

### `/admin` — Operator

**Design.** Only present for the bootstrap admin; same layout as Settings with an
*Admin* row.

**Features.** Grant or claw back credits: email or id, amount, reason, optional plan
change, with the result shown inline. Nothing else until the API exposes more.

## Shell

- Two sidebars (see [web-design.md](web-design.md) §5): a 56px **rail** of expert avatars (Home at top, `+` to build, settings and account at the bottom), then a 260px **expert sidebar** with the selected expert's pages (Overview, Sources, Graph, Settings) and its chat list. Home shows all experts, recent chats, and credits (hidden if `credits_enforced` is false).
- Expert pages are sidebar rows, not tabs. A building expert shows a pulse on its rail avatar.
- ⌘K palette to jump to an expert or chat.
- Light and dark, system default.
- Collapses by width: three columns at 1280px and up; the right panel overlays at
  1024–1279; the expert sidebar becomes a drawer at 768–1023; below 768 the rail folds
  into a nav drawer, the right panel becomes a bottom sheet, and dialogs become sheets.
  Per-page behaviour at each width is in [web-design.md](web-design.md) §8; every
  animation is in §9.
- Per-segment `loading.tsx`, `error.tsx`, `not-found.tsx`. Others' experts are 404.

## Stack

Next 16 App Router, React 19, TypeScript, Tailwind v4, shadcn/ui (Base UI), react-hook-form + zod, sonner, react-markdown, d3-force (graph page only).

Auth: backend-for-frontend. Next route handlers under `/api/*` hold the session in httpOnly cookies, add the bearer, refresh once on 401, and pass SSE through. `middleware.ts` redirects unauthenticated app routes to `/login?next=`.

Known gotchas: SSE frames end with `\r\n\r\n`; don't abort fetches on unmount (Strict Mode); Base UI `Button` needs `nativeButton={false}` with `render={<Link/>}`; `error.tsx` receives `unstable_retry`, not `reset`; async route `params`, run `next typegen`.

Tests: Vitest for the SSE parser, the proxy refresh, and 402 rendering; Playwright for
login → build → chat → export across desktop, iPad and phone projects, plus a
reduced-motion pass and Lighthouse budgets on the four main pages.

---

## Backend gaps (don't fake these)

| Gap | What the site does |
|---|---|
| No checkout | "Request credits" mailto |
| No account deletion, rename, or persona regeneration | Not offered |
| No build-complete email | User checks back; the log is durable |

---

## Build order

The phase-by-phase flow, with a done-when check per phase, is
[web-implementation.md](web-implementation.md) §13. In short: foundations → auth →
shell → home, new expert and build page → chat → ledger → graph → settings and admin →
landing and legal → hardening and release. Responsive behaviour and motion are built inside
each phase, not in a pass at the end.
