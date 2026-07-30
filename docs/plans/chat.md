# Peritus — Stateful Expert Chats: Production Plan

Status: planning document. Covers backend (FastAPI + Postgres) and web
(Next 16 dashboard). Goal: conversations with an expert are **persisted,
resumable, listed in the sidebar as recents, and startable from any expert
page** — replacing the current fire-and-forget chat where history lives only
in the client's memory.

Related docs: `web/DASHBOARD_PLAN.md` (§5.8 sketched stateless chat UI; this
plan supersedes that section), memories `peritus-auth`,
`peritus-cost-optimization`.

---

## 0. Current state (verified, don't re-derive)

**Backend — chat exists but is stateless.**
`POST /experts/{slug}/chat` (`api/src/peritus/api/routes/chat.py`) takes
`{question, history[]}`, runs retrieval (`ChatAgent.retrieve`), streams SSE
events, and forgets everything. Nothing is written to Postgres.

SSE event protocol today (keep it — the web client will speak the same one):

| event `type` | payload | meaning |
|---|---|---|
| `status` | `message: str` | retrieval progress ("Searching graph…") |
| `token` | `text: str` | one streamed answer fragment |
| `sources` | `citations: [{n, label, source_id}]`, `has_contradiction: bool` | passages the answer actually cited, numbered to match inline `[n]` |
| `done` | — | stream complete |
| `error` | `message: str` | generation failed |

**Prompt-cache economics** (must survive this change): system prompt is
byte-identical per expert with a `cache_control` breakpoint
(`build_cached_system`); history is capped at `CHAT_HISTORY_MAX_MESSAGES`
and carries a breakpoint on the last history message
(`build_composition_messages`). Follow-up turns bill prior context at ~0.1×.
Loading history from Postgres instead of the request body changes none of
this — the messages sent to Anthropic are the same shape.

**Ownership model**: experts are owner-scoped (`experts.owner_id`, enforced
in app code via `_visibility_clause` in `experts/repository.py`, RLS is
bypassed by the service connection). Conversations must follow the identical
pattern. Others' conversations → **404, not 403** (same convention).

**Clients**: the Rust TUI and Python CLI use the stateless endpoint. It
**stays untouched** — stateful chat is additive, web-only for now.

**Web**: dashboard shell + auth cookies work, but every dashboard page still
renders `MOCK_EXPERTS` from `lib/mock-data.ts`. There is **no** react-query
(planned in DASHBOARD_PLAN but never installed), no generic authed proxy for
`/experts*`, and no SSE helper. `next` is 16.2.10 (`proxy.ts`, not
middleware; read `node_modules/next/dist/docs/` before writing route code —
see `web/AGENTS.md`).

Migrations: next free number is **`014`**.

---

## 1. Product behavior (what we're building)

- Every chat with an expert is a **conversation**: created when the user
  sends their first message, titled from that message, persisted with all
  turns and citations.
- **Sidebar "Recent chats"** section, **replacing** the current "Recent
  experts" list: the user's most recent conversations across all experts —
  title + expert name + relative time; click resumes exactly where they
  left off. Experts keep a single "Experts" nav entry as their hub; access
  frequency drives sidebar space, and post-chat the re-opened object is the
  conversation, not the expert (each chat row names its expert anyway, and
  ⌘K already jumps to any expert by name).
- **Start points**: a primary "Chat" button on the expert detail page, a
  chat tab/page per expert showing that expert's past conversations + a new
  chat composer, and a row action in the experts table. Disabled (with
  tooltip) unless `status == ready`.
- Conversations can be **renamed** and **deleted**. Deleting an expert
  cascades to its conversations.
- Refreshing or navigating away mid-answer must not lose the exchange: the
  answer streamed so far is persisted and marked interrupted.

Non-goals (explicitly out of scope, revisit later): sharing/public links,
full-text search over chats, regenerate/edit-message, branching, TUI/CLI
adoption of stateful chat, per-message feedback, retention policies.

---

## 2. Data model — migration `api/migrations/014_conversations.sql`

```sql
CREATE TABLE conversations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    expert_id        BIGINT NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    owner_id         UUID,                -- soft FK to auth.users, same as experts.owner_id
    title            TEXT,                -- NULL until first message sets it
    message_count    INT  NOT NULL DEFAULT 0,
    -- optimistic claim so only one answer streams per conversation at a time
    streaming_started_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_message_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_conversations_owner_recent
    ON conversations (owner_id, last_message_at DESC);
CREATE INDEX idx_conversations_expert_recent
    ON conversations (expert_id, last_message_at DESC);

CREATE TABLE conversation_messages (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content          TEXT NOT NULL,
    citations        JSONB,               -- assistant only: [{n, label, source_id}]
    has_contradiction BOOLEAN NOT NULL DEFAULT false,
    interrupted      BOOLEAN NOT NULL DEFAULT false,  -- stream died before `done`
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_conversation
    ON conversation_messages (conversation_id, id);
```

Decisions baked in:

- **UUID conversation ids** — they appear in URLs; sequential ids leak
  volume and invite enumeration (ownership checks make enumeration safe,
  but UUIDs are free). `gen_random_uuid()` is built-in on PG13+ and on
  Supabase, so local Postgres still migrates (same constraint that shaped
  `011_expert_owners.sql`).
- **Message ordering by `id`** — one writer per conversation (enforced by
  the streaming claim), so BIGSERIAL order is chronological. No `seq`
  column needed.
- **Citations stored on the message** as the exact `used_citations` shape
  the stream already emits — the UI renders history and live messages from
  one shape, no re-derivation.
- **`streaming_started_at` claim** instead of advisory locks: advisory
  locks are per-connection and our pool doesn't pin a connection for the
  stream duration. Claim with
  `UPDATE … SET streaming_started_at = now() WHERE id = $1 AND
  (streaming_started_at IS NULL OR streaming_started_at < now() - interval
  '3 minutes') RETURNING id` — a crashed worker self-heals after the stale
  window; clear it in a `finally`. Concurrent send → **409**.
- `message_count` is denormalized so the sidebar/list queries never join
  messages; maintained in the same transaction that inserts messages. Also
  lets recents filter out empty conversations (`message_count > 0`).

---

## 3. Backend API surface

New module `api/src/peritus/api/routes/conversations.py` + repository
`api/src/peritus/chat/conversation_repository.py` + schemas
`api/src/peritus/api/schemas/conversations.py`. All routes
`Depends(require_user)`, owner-scoped with the `_visibility_clause`
pattern (admins additionally see legacy `owner_id IS NULL` rows).

| Method & path | Purpose | Notes |
|---|---|---|
| `POST /experts/{slug}/conversations` | create conversation | 404 unless caller owns the expert; **409 unless `status == ready`**. Body empty. Returns `ConversationSummary` (untitled). |
| `GET /conversations?limit=20` | cross-expert recents (sidebar) | joins expert `name/topic/persona_name/status`; `message_count > 0` only; ordered `last_message_at DESC`; `limit` clamped ≤ 50. |
| `GET /experts/{slug}/conversations` | per-expert history (chat tab) | same row shape. |
| `GET /conversations/{id}` | conversation + all messages + expert summary | messages ASC by id. No pagination v1 — conversations are short (`CHAT_HISTORY_MAX_MESSAGES` bounds what the model sees anyway); add `?before=<id>` paging only if real data demands it. |
| `PATCH /conversations/{id}` | rename | body `{title}`, 1–120 chars, stripped. |
| `DELETE /conversations/{id}` | delete | 204; cascade removes messages. |
| `POST /conversations/{id}/messages` | **the stateful chat stream** | body `{question}` (validated: stripped, 1–4000 chars). SSE response, protocol below. |

### 3.1 Message-stream lifecycle (`POST /conversations/{id}/messages`)

1. Resolve conversation for user (404), load its expert (409 if not
   `ready` — an expert can regress to `building` on rebuild).
2. Take the streaming claim (409 `"An answer is already streaming"` on
   conflict).
3. Insert the **user message**; on the conversation's first message, set
   `title = question truncated to 60 chars` (word boundary, `…`). Bump
   `message_count`, `last_message_at`.
4. Load history: last `CHAT_HISTORY_MAX_MESSAGES` messages **excluding**
   the just-inserted question, mapped to `{role, content}` — feed the
   existing `build_composition_messages(history, question, context_block)`
   unchanged. Reuse `ChatAgent.retrieve` + `build_cached_system` exactly as
   `chat.py` does today (factor the shared streaming body into
   `peritus/chat/streaming.py` rather than copy-pasting `chat.py`).
5. Stream the same SSE events as the stateless endpoint, plus one addition:
   first event is `{"type": "meta", "conversation_id", "title"}` so the
   client can update the sidebar/URL without a second fetch.
6. On `done`: insert the assistant message (content + citations +
   `has_contradiction`), bump counters, clear the claim — one transaction.
7. On client disconnect or generation error mid-stream: persist whatever
   streamed as the assistant message with `interrupted = true` (so a
   refresh shows the partial answer with an "interrupted" marker instead of
   a hole), clear the claim. If *zero* tokens arrived, persist nothing —
   the orphaned user message is fine; the UI offers retry.
8. Logging: ids and timings only, **never message content** (matches the
   existing auth/chat logging discipline).

Title generation stays truncation-only. LLM titling (Haiku one-liner) is a
flagged stretch — it's a per-conversation cost and the memory
`peritus-cost-optimization` says default to cheap.

### 3.2 What does NOT change

- `POST /experts/{slug}/chat` — the TUI/CLI contract, byte-for-byte.
- `ChatAgent`, grounding, prompt-cache breakpoints, `CLAUDE_MODEL` config.
- Auth (`require_user`), rate limiting on unauthenticated routes.

---

## 4. Web implementation

### 4.1 Prerequisite: real data plumbing (the dashboard is still on mocks)

Chat cannot ship against `MOCK_EXPERTS`. Minimum de-mocking, scoped to what
chat touches (full de-mocking of dashboard/analytics is separate work):

- `lib/api/proxy.ts` — server-only helper for route handlers:
  `proxyJson(path, init)` attaches `Authorization: Bearer <access cookie>`,
  on 401 calls the existing `refreshSession()` once and retries, maps
  errors to `ApiError`. (The auth routes already do this dance ad hoc;
  centralize it.)
- Route handlers: `app/api/experts/route.ts` (GET list),
  `app/api/experts/[slug]/route.ts` (GET detail) — thin `proxyJson` passes.
- `app/(dashboard)/experts/[slug]/page.tsx` switches from `MOCK_EXPERTS`
  to the real detail fetch (server component calling FastAPI via the same
  helper directly — server components don't need the `/api/*` hop).
- `lib/api/types.ts` gains `ConversationSummary`, `ConversationDetail`,
  `ChatMessage`, `Citation`, `ChatStreamEvent` mirroring the Pydantic
  schemas (same file already mirrors experts).

### 4.2 SSE-over-POST client — `lib/api/sse.ts`

`EventSource` can't POST, so: `fetch` + `ReadableStream` +
`TextDecoderStream`, split on `\n\n`, parse `data:` lines to typed
`ChatStreamEvent`s, delivered through an async generator. Takes an
`AbortSignal` (Stop button + unmount cleanup). No reconnection logic for
chat (a broken answer is completed server-side as `interrupted`; the client
just refetches the conversation).

### 4.3 Routes & proxies

```
app/(dashboard)/
  chats/[id]/page.tsx            # resume a conversation (server component:
                                 #   fetches detail, renders <ChatView>)
  experts/[slug]/chat/page.tsx   # new-chat screen: composer + this expert's
                                 #   past conversations list
app/api/
  conversations/route.ts                  # GET recents (sidebar)
  conversations/[id]/route.ts             # GET / PATCH / DELETE
  conversations/[id]/messages/route.ts    # POST → streams FastAPI SSE back
                                          #   (pipe upstream body through,
                                          #    content-type text/event-stream)
  experts/[slug]/conversations/route.ts   # GET list + POST create
```

URL scheme decision: conversations live at **`/chats/[id]`**, not nested
under the expert — the sidebar recents span experts, and a flat URL keeps
resume-links stable even if expert slugs ever change. The page breadcrumbs
back to its expert.

First-message flow (no empty-conversation litter): the composer on
`/experts/[slug]/chat` holds the draft → on submit `POST …/conversations`
→ `router.replace(/chats/{id})` with the question handed off via
`sessionStorage` (survives the navigation, dies with the tab) → the chat
view auto-sends it as the first message. One extra round-trip, zero
half-created state in URLs.

### 4.4 Components — `components/chat/`

```
chat-view.tsx        # client container: messages state, send/stop, status
                     #   machine (idle → creating → streaming → done|error)
use-chat-stream.ts   # hook wrapping lib/api/sse.ts: optimistic user append,
                     #   token accumulation, sources/error/meta handling
message-list.tsx     # scroll region; sticks to bottom only while already
                     #   at bottom (don't yank scroll during streaming)
message.tsx          # user: plain bubble. assistant: markdown render,
                     #   [n] → superscript citation chips, "interrupted"
                     #   marker, contradiction badge
citation-list.tsx    # per-message footer: [n] label rows; chip click
                     #   scrolls/highlights the entry
status-line.tsx      # retrieval status events as a shimmering line above
                     #   the incoming answer
composer.tsx         # autosizing textarea, Enter=send / Shift+Enter=newline,
                     #   Stop while streaming, disabled while claim held
conversation-menu.tsx# rename (dialog + PATCH) / delete (confirm + DELETE)
```

Markdown: add **`react-markdown` + `remark-gfm`** (new deps — the only ones
this plan introduces). No raw-HTML pass-through (`rehype-raw` explicitly
NOT included) — model output stays escaped, which also closes the XSS
question. Citation chips are produced by a custom text renderer matching
`\[(\d+)\]`, mapped against the message's stored citations.

State management stays dependency-light (no react-query, matching what's
actually installed): chat state is local to `ChatView`; list/recents are
server components refreshed via `router.refresh()` after mutations
(create/rename/delete/first-message-title).

### 4.5 Sidebar recents + entry points

Final sidebar order: primary nav (Dashboard / Experts / Analytics /
Settings) → **building-now indicator** (transient) → **Recent chats** →
usage card.

- `components/sidebar/nav-recent-chats.tsx` — server-fetched last 8
  conversations (`GET /conversations?limit=8` via the proxy helper):
  title (truncate), expert `persona_name ?? topic` as the secondary line,
  active-state by pathname. Empty state: render nothing (no placeholder
  noise).
- `components/sidebar/nav-recent-experts.tsx` is **removed** in the same
  change — a permanent expert list duplicates the Experts hub and ⌘K, and
  competes with chats for the same rows.
- `components/sidebar/nav-building-expert.tsx` — the one moment an expert
  deserves ambient sidebar presence: any expert with `status ∈ {queued,
  building}` renders as a status row (amber pulse dot, links to its build
  page) and disappears at `ready`/`failed`-acknowledged. Fed by the same
  experts list fetch; no polling in v1 — it refreshes with normal
  navigation/`router.refresh()`, live SSE-driven updates are a stretch.
- Expert detail page (`experts/[slug]/page.tsx`): primary **"Chat"**
  button in the `PageHeader` action slot → `/experts/[slug]/chat`;
  disabled with tooltip "Available when the expert is ready" unless
  `status == ready`. Replaces the chat line of the `ComingSoon` block.
- Experts table (`components/experts/experts-table.tsx`): "Chat" row
  action, same gating.
- Command palette (`sidebar/command-menu.tsx`): "Chat with <expert>"
  entries — stretch, only after core lands.

### 4.6 UX details that make it feel production-grade

- Optimistic user bubble immediately on send; status line while retrieval
  events arrive; token-by-token answer; citations appear as a footer when
  the `sources` event lands.
- Stop button aborts the fetch → server persists partial with
  `interrupted = true`; the bubble gets an "answer interrupted" caption and
  the composer re-enables.
- Error event → inline error bubble with a Retry button (re-sends the same
  question; the orphaned user message is reused, not duplicated —
  client-side check: if last message is `user`, retry streams against it).
- History window honesty: if a conversation exceeds
  `CHAT_HISTORY_MAX_MESSAGES`, show a subtle divider "older messages aren't
  visible to the expert" at the cutoff — the full transcript renders, but
  we don't pretend the model sees all of it.
- Busy conflict (409 from double-tab): toast "This chat is already
  answering in another window."
- Loading states: skeleton message list on `/chats/[id]`; disabled
  composer until the detail fetch resolves.

---

## 5. Delivery phases (each ends runnable + reviewable)

**Phase 1 — Backend foundation**
Migration 014; repository + schemas; CRUD routes; message-stream route with
persistence, claim, interruption handling; shared streaming module factored
out of `chat.py`. Contract tests (mock GoTrue/Anthropic/agent, style of
`tests/api/test_auth_oauth.py` / `test_build_endpoint.py`):
ownership 404s, not-ready 409, busy-claim 409, title truncation, assistant
persistence incl. citations + interrupted path, cascade delete, recents
ordering/filtering. `ruff` + `mypy` clean, full suite green.

**Phase 2 — Web plumbing**
`lib/api/proxy.ts`, experts + conversations route handlers, SSE client,
types, expert detail page on real data. Verifiable with `curl` against the
Next routes.

**Phase 3 — Chat core**
`/experts/[slug]/chat` + `/chats/[id]`, `ChatView` and friends, streaming
render with citations, stop/retry/interrupted states. Manual click-through:
create → stream → refresh mid-answer → resume → rename → delete.

**Phase 4 — Surfacing**
Sidebar rework (recent chats in, recent experts out, building-now
indicator), expert-page Chat button, table row action, `router.refresh()`
wiring so recents update on create/rename/delete.

**Phase 5 — Hardening & polish**
Empty/loading/error states across all new surfaces; a11y pass (focus
management on send, `aria-live="polite"` on the streaming region, labeled
icon buttons); responsive pass (chat usable at 375px); `npm run build` +
`tsc` + eslint clean; browser click-through of the full matrix (new chat
from all three entry points, resume from sidebar, double-tab 409, not-ready
gating).

---

## 6. Risks & edge cases (decided handling)

| Case | Handling |
|---|---|
| Client disconnects mid-stream | Persist partial as `interrupted`; claim cleared in `finally`. |
| Server crashes mid-stream | Claim self-heals after 3-min stale window; user message survives, retry offered. |
| Expert rebuilt/deleted under a conversation | Not-ready → 409 on send with clear message; deleted → cascade removes chats (sidebar refresh drops them). |
| Access token expires mid-stream | Token validated at stream start only; streams are minutes-long max — acceptable. Proxy refreshes before opening. |
| Two tabs send simultaneously | Second gets 409 via claim; toast. |
| Prompt-cache regression | History mapping is byte-identical to today's client-sent history; verify with a before/after log of request shape in dev (not content). |
| Model output injection | react-markdown without raw HTML; citations rendered from stored JSONB, not parsed HTML. |
| Empty-conversation litter | Creation only on first send; recents filter `message_count > 0`; empties are invisible and harmless. |

## 7. Open questions (defaults chosen; flag if you disagree)

1. **LLM-generated titles** — default OFF (truncation). Turn on later as
   `CHAT_TITLE_MODEL` opt-in?
2. **Per-user rate limit on messages** — none in v1 (authed, owner-scoped,
   cost-bounded by `max_response_tokens`). Add if abuse appears.
3. **`/experts/[slug]` tab shell** (DASHBOARD_PLAN §3) — this plan links
   out to `/experts/[slug]/chat` instead of building the full tab layout;
   tabs can absorb these pages later without URL changes.
