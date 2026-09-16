# Peritus web

The Next.js 16 app: build an expert and watch it happen, chat with it, and read the evidence
behind every answer. It is a **backend-for-frontend** — the browser never talks to the FastAPI
server directly, which is what lets that server keep CORS closed and the session out of JavaScript.

For the system this is a client of, start at [`../docs/README.md`](../docs/README.md).
For the conventions and the gotchas that have already bitten, read [`AGENTS.md`](AGENTS.md) —
it is the authoritative contributor guide for this directory.

## Running it

```bash
cp .env.example .env.local     # PERITUS_API_URL + NEXT_PUBLIC_APP_URL
npm ci
npm run dev                    # http://localhost:3000
```

The app needs the API running (`just dev-solo` from the repository root, on `:8000`). For UI work
that does not need real data, the Playwright mock API serves captured fixtures and streams real
SSE:

```bash
npm run mock-api               # :8787 — point PERITUS_API_URL at it
```

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Development server |
| `npm run build` | Production build |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | Vitest unit suite |
| `npm run e2e` | Playwright, all seven device projects (needs a build) |
| `npm run lighthouse` | Performance budgets on the public and app pages (needs a build) |
| `npm run mock-api` | The fixture server the e2e suite runs against |

From the repository root, `just lint-web` runs exactly what the web CI job runs, so a green local
run means a green CI run.

## Layout

```
app/
  (app)/          Authenticated shell: experts, chats, settings, admin
  (marketing)/    Public: landing, share links, privacy, terms
  api/            One thin route handler per backend endpoint
  login/          Email one-time code and Google SSO
components/       auth · build · chat · experts · graph · identity · ledger ·
                  marketing · settings · share · shell · ui
hooks/            SSE build events, chat streaming, media queries, preferences
lib/
  api/            proxy.ts — the only thing that talks to FastAPI
  auth/           Cookie shaping and session handling
  build/          Build-event reducer
  graph/          Force-simulation and canvas helpers
proxy.ts          Route gate + edge session refresh (Next 16's middleware)
e2e/              Playwright specs and the mock API
tests/            Vitest unit suite and captured API fixtures
```

## Four rules this code enforces

These come from [`../docs/plans/web-production.md`](../docs/plans/web-production.md) and are held
in code, not in copy.

1. **Gate chat on `readiness`, never on `status`.** An expert answers from `chat_ready`, a whole
   stage before its build job finishes. Reading `status` hides a working expert for the length of
   graph extraction.
2. **`null` means "not recorded", never zero.** Every count the API does not persist comes back as
   null with a reason. `lib/format.ts` renders those as an em dash and never coerces.
3. **There is no checkout.** The only credit remedy anywhere is "request credits", as a `mailto:`.
   Never add a button that implies payment.
4. **Every page works at 360px and under reduced motion.** Both are asserted in `e2e/` across seven
   Playwright projects, on every route.

## Architecture notes

- **`proxy.ts`** (not `middleware.ts` — renamed in Next 16) gates the `(app)` routes and refreshes
  the session at the edge, because a server component cannot write cookies.
- **`lib/api/proxy.ts`** attaches the bearer, refreshes once on a 401 and retries, and
  distinguishes a dead refresh token (sign in again) from an unreachable auth server (do *not*
  sign the user out).
- **The browser holds no token in JavaScript.** Two httpOnly cookies carry the session, and only
  the server reads them.
- **There is no codegen between the Python schemas and `lib/api/types.ts`.** The fixture tests in
  `tests/` are the schema check: a payload that drifts fails in CI rather than in a user's browser.

## Deployment

Vercel, built in GitHub Actions and uploaded prebuilt — Vercel's Git integration is off, so a push
can never produce a production deployment that skipped CI. Environment and Supabase specifics are
in [`docs/deploy.md`](docs/deploy.md); the pipeline is in
[`../docs/deployment.md`](../docs/deployment.md).

Before shipping anything that touches layout or input, walk
[`docs/real-device-checklist.md`](docs/real-device-checklist.md) on a real phone. The emulator does
not reproduce the keyboard, the URL bar or momentum scrolling.
