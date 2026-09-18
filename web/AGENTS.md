<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Peritus web

The three design documents are in `docs/plans/`: `web-production.md` (the pages),
`web-design.md` (look, tiers, motion) and `web-implementation.md` (how). Where a
plan and this code disagree, **the code is right** — several things in the plans
were checked against a slightly older Next and Base UI. The corrections are
listed at the bottom of this file.

## The four rules

These come from `web-production.md` and are enforced in code, not in copy.

1. **Gate chat on `readiness`, never on `status`.** An expert answers from
   `chat_ready`, a whole stage before its build job finishes. Reading `status`
   hides a working expert for the length of graph extraction.
2. **`null` means "not recorded", never zero.** Every count the API does not
   persist comes back as null with a reason. `lib/format.ts` renders those as an
   em dash and never coerces; a fabricated zero in an evidence record is worse
   than a visible gap.
3. **There is no checkout.** The only credit remedy anywhere is "request
   credits", as a `mailto:`. Never add a button that implies payment.
4. **Every page works at 360px and under reduced motion.** Both are asserted in
   `e2e/` across seven Playwright projects, on every route.

## Architecture

- **`proxy.ts`** (not `middleware.ts` — renamed in Next 16) gates the `(app)`
  routes and **refreshes the session at the edge**, because a server component
  cannot write cookies. Without that the app would refresh on every request and
  never persist the result.
- **`lib/api/proxy.ts`** is the only thing that talks to FastAPI. It attaches the
  bearer, refreshes **once** on a 401 and retries, and distinguishes a dead
  refresh token (`NotAuthenticatedError` → sign in) from an unreachable auth
  server (`ApiError` 503 → do _not_ sign the user out).
- **`app/api/*`** is one thin route handler per backend endpoint. Mutating ones
  call `guardOrigin`. Streaming ones use `forwardStream` and set
  `dynamic = 'force-dynamic'`.
- The browser holds **no token in JavaScript**: two httpOnly cookies carry the
  session and only the server reads them.

## Gotchas that have already bitten

- **Route `params` are async.** `const { slug } = await params`. Run
  `npx next typegen` after adding a route.
- **`error.tsx` receives `retry`, not `unstable_retry`.** It was `unstable_` in
  16.2 and became stable in 16.3 — the plan predates that.
- **`ViewTransition` is a stable export from `react`** in React 19.3, and needs
  no `experimental` flag in `next.config.ts`. The plan's
  `unstable_ViewTransition` and `experimental.viewTransition` are both stale.
- **Never abort a stream fetch on unmount.** Strict Mode double-mounts, so an
  abort in the cleanup kills the first request and looks exactly like a flaky
  backend. `useBuildEvents` abandons the connection via a generation counter
  instead. Only the Stop button aborts a chat.
- **A closed SSE stream is not a finished build.** Only `done`, `error` or
  `cancelled` ends a tail; anything else means reconnect with `after=<lastSeq>`.
- **Do not await `body.cancel()`** on a discarded streaming response — it may not
  settle until the far end closes, which makes a retry wait on the request it is
  replacing.
- **Base UI `Menu.GroupLabel` throws outside a `Menu.Group`** (production error
  #31, which is unreadable in a built app). `MenuLabel` wraps both.
- **Do not put Base UI's `Button` behind `render`** on an anchor or a trigger.
  `nativeButton={false}` sets `role="button"`, which overrides an anchor's link
  role. `ButtonLink` is a plain `next/link` with the button classes, and menu
  triggers take `buttonStyles()` directly.
- **One `h1` per page.** The top bar's title is a `<p>`: it is a breadcrumb leaf,
  and the page below it owns the heading.
- **The `(app)` layout owns the rail, the sidebar and the recents.** After
  deleting an expert or a chat, call `router.refresh()` as well as navigating, or
  the deleted thing lingers in the shell.
- **`useMediaQuery` may not decide what to render at first paint.** Its server
  snapshot is `false`, so both forms of every region are in the HTML and toggled
  with `hidden md:flex`. It decides _behaviour_ only — drawer or inline. The one
  exception is `Dialog`, which is closed on first paint and so has nothing to get
  wrong.
- **Never trust a pending `requestAnimationFrame` id as "a frame is coming".**
  A hidden, occluded or mid-view-transition document simply does not run the
  callback, so `if (frame.current) return` wedged the graph canvas permanently:
  the simulation kept ticking, every repaint request was swallowed, and the page
  showed a live node count over an empty canvas. `graph-canvas.tsx` cancels and
  re-arms, and repaints on `visibilitychange`.
- **Adjust state during render, not in an effect**, when it has to follow a prop
  (the dialogs that reset on open). `react-hooks/set-state-in-effect` catches the
  wrong form.
- **`Intl` is not stable across engines, so no rendered date may come from it.**
  `toLocaleDateString('en-GB', { month: 'short' })` is "Sept" in Node and
  Chromium and "Sep" in WebKit, which made every server-rendered date a
  hydration text mismatch in iOS Safari. `lib/format.ts` writes the month names
  out; `tests/format.test.ts` asserts the exact strings.
- **A hydration mismatch is not a warning.** React discards the server HTML for
  that subtree and re-renders it, and on the expert page that was enough to take
  the page down in Safari. Timestamps that are _meant_ to differ (a relative
  time, a local-time date) go through `RelativeTime`/`DateText`, which carry the
  instant in `<time dateTime>` and suppress the check deliberately.
- **`components/history-guard.tsx` must stay mounted in the root layout.** Next's
  app router syncs its state through `history.replaceState` from an effect; if a
  `router.refresh()` commits after a reload or navigation has been committed,
  WebKit throws `SecurityError` from the History API and — because the throw is
  inside the router, above every boundary this app can declare — Next replaces
  the document with its built-in "This page couldn't load" screen. The guard
  swallows exactly that error, and is installed at module scope because the
  router captures `replaceState` before any effect of ours could run.
- **`md:` is not "desktop".** An iPad is wide _and_ touch, so a width-only
  breakpoint hands a tablet the mouse-sized control. Density overrides that
  exist for a pointer use `pointer-fine:md:`; sizes that must grow for a thumb
  come from the coarse-pointer token block.

## What the plans say that this code does not do

- **`motion` and `input-otp` are not installed.** Base UI 1.8 ships `Drawer`
  (swipe, snap points, focus trap, scroll lock, Android back) and `OTPField`
  (`one-time-code`, paste-fills-all, numeric keypad), both driven by CSS
  transitions on `data-*` attributes rather than JavaScript timers. That is
  fewer dependencies and interruptible animations for free. The rail's active bar
  is a CSS `translateY` transition rather than a `layoutId`.
- **`@dicebear/core` is 9.4.3, not 10.7.** `@dicebear/collection` 9.4 peers on
  core `^9`; the pairing in the plan does not install.
- **shadcn was not run.** `components/ui/*` is a small hand-written set on Base
  UI, because the design's rules (rounded fills instead of rules, colour as text,
  no shadows except popovers) fight shadcn's defaults more than they share them.
  The exception is shape, not styling: `ui/field.tsx` and `ui/card.tsx` are
  shadcn's `Field` and `Card` APIs ported onto these tokens, and the auth forms
  follow shadcn's `login-03` block. Use them for new forms; do not install the
  CLI, whose theme variables would fight `globals.css`.
- **The avatar is a stored recipe, not a client-side derivation.** See below.
- **There are no per-expert colours.** web-design.md §4's twelve expert hues are
  not used — neither hashed from a name nor offered in the picker. See _Colour_.
- **The `StatPill` is gone.** It floated over the Overview's own prose at wide
  widths, and every number on it was already in the properties list two
  paragraphs above.

## Colour

**The chrome is monochrome. Colour is information.** The only hues in the app are
**status**: `--ok`, `--warn`, `--bad` say what state a build, a source or a
readiness is in.

**There are no per-expert colours.** Experts are told apart by their avatar — the
found picture, a generated drawing, or the monogram — never by a tint. The picker
used to offer twelve hues; they were removed, the API now discards any `hue` it is
sent (the key stays in the stored shape, always null, for older clients), and
`resolveRecipe` ignores a hue an older row still carries.

`--accent` (the primary button, the wordmark, the landing page's markers) is ink
on paper: near-white on the dark theme, near-black on the light one. It used to
be violet, and the primary button used to read `bg-expert` — which outside an
expert's own pages resolves to the _root_ hue, so every primary button in the
product was violet. Together with hues hashed from persona names (five experts
whose names landed in the blues) the whole app read as blue.

Two consequences worth knowing before changing this:

- `text-expert` and `bg-expert-soft` are a neutral grey. They are identity, not
  emphasis. Reach for `--fg` when something has to be the most visible thing on
  screen (the focus ring and the rail's active bar both do).
- **Depth is carried by the surface, not by rules.** Cards, the stat tiles, the
  build box, the chat cards and the assistant card have no borders — they are
  `bg-panel` on `bg-bg`, and the light theme's ground is a real grey (`#f4f4f5`)
  precisely so that step is visible. Borders are left only where an edge is the
  affordance: inputs, menus, popovers, dialogs, the tier radio cards and table
  cells. Do not put a border back on a container "for definition".

## Decisions from the September 2026 UX review

- **"Is it building?" reads `build_active`, never `status` alone.** The API
  computes it from whether a build job is really queued or running. An expert row
  can say `queued` with no job behind it; `dotState`/`isBuilding` in
  `components/ui/status-dot.tsx` treat that as not building (Ready if it can
  answer, "Build never started" if not), and the build page says the build never
  started. Every rail pulse, Home "Building now" card and status line goes
  through those two helpers.
- **The nav drawer and its menu button exist up to `lg` (1023px), not `md`.**
  Between 768 and 1023px the expert sidebar is hidden too; without the drawer an
  iPad in portrait had no route to an expert's pages. The drawer's horizontal
  avatar row is hidden from `md`, where the real rail is visible.
- **One name per build stage**, `STAGE_LABEL` in `lib/build/reducer.ts`, used by
  the timeline, the log's stage column, headline rows, Home and every notice.
- **Citations are numbered per answer** (`numberCitations`): 1, 2, 3 in order of
  first use. `n` stays the passage index for lookups; `display` is what shows.
- **The transcript is top-anchored.** Bottom-anchoring put a one-turn answer
  exactly where the cited-passage sheet opens on touch devices; a citation chip
  also scrolls itself to the top below `lg` before the sheet opens.
- **Asking comes first.** "Ask now" on the build page creates a conversation and
  lands in it (`useStartChat`); an expert with no chats shows its composer under
  the Overview header.
- **Vocabulary:** Sources (not ledger/corpus), kept/dropped, passages, Ask,
  "Peritus" (not the server or the worker). Source types render as kinds
  (`lib/source-kind.ts`); discovery keys and text-read methods as phrases.
- **Light-theme status colours are ≥4.5:1 as text** on ground, panel and
  raised (`--ok #1a7033`, `--warn #7f5808`, `--bad #b42d2d`). A higher-contrast
  surface ramp (near-black dark ground, bigger card step) was tried and
  reverted: the ground-to-sidebar step read as odd. Keep the surfaces as they are.
- **Contrast:** `--fg-3` meets 4.5:1 on ground, panel and raised in both themes;
  `--fg-4` is for decoration and disabled states only, never for text a reader
  needs.

## Accounts

The plan is `docs/plans/accounts.md`; the Supabase dashboard steps it depends on
are in `docs/deploy.md`. Rules for the web side:

- **Three ways in, one account:** Google, email + password (`/login`), and an
  emailed code (`/login/code`). Sign-up (`/signup`) and reset (`/login/forgot` →
  `/login/reset`) confirm by six-digit code, never by link.
- **Every flow that mints a session ends in `lib/auth/respond.ts`** (`signedIn`,
  `postForSession`), which turns the tokens into the two cookies and passes the
  browser's `User-Agent` on (`clientAgent`) — GoTrue labels a session with the
  agent of the request that made it, and before this every session read
  `python-httpx`.
- **Forms branch on `errorCode(error)`**, the API's `detail.code`, never on the
  English message.
- **A 204 endpoint is called with `apiVoid`**, not `apiSend` — `apiJson` treats an
  empty body as a failure.
- **Nothing reveals whether an email has an account.** Copy after sign-up, resend
  and forgot-password says "if there is an account" or moves on regardless.

## Sharing and the viewer

An owner shares an expert with a token link (`/share/{token}`); the design is in
`docs/sharing.md` at the repo root. Three rules for the web side:

- **Every management control goes through `canManage(expert)`** (`lib/access.ts`),
  which reads `expert.access`. A viewer — someone who opened a share link — gets the
  Overview, Sources, graph, build log and composer, and none of: the avatar picker,
  Settings (the route 404s), Share, Rebuild, Cancel, Cost, Add a source, Remove source,
  Delete. Their one action on the expert is "Remove from my experts". A new control
  that changes an expert must check it too; the API would refuse it anyway, and a
  button that cannot work is the bug.
- **Opening a link is a click (`OpenSharedExpert`), never a render side effect.** The
  share page is public so link previews can fetch it; a GET that recorded a grant would
  let any unfurler put an expert in someone's workspace.
- **A viewer's chat outlives the link.** When the expert is no longer readable, the chat
  page renders the transcript read-only from the conversation's own columns
  (`unavailable`) instead of a 404.

The share URL is built from `window.location.origin` through `useSyncExternalStore`
with an empty server snapshot, because the Settings page renders the panel on the
server and an origin read during render would be a hydration mismatch.

## The shell's two columns

The rail **is** the expert list. The second column never repeats it: on an
expert it shows that expert's pages and chats, and on Home it shows the
workspace nav and the chats — the one thing the rail cannot reach. Home's page
body therefore drops its own _Recent chats_ section from `lg` up (`lg:hidden`),
because below `lg` there is no sidebar and that section is the only route to a
chat.

## Avatar identity

**Three levels, and the precedence is the design.** `lib/avatar.ts#resolveRecipe`
resolves them in this order:

    experts.avatar (chosen)  →  expert_pictures (found)  →  monogram (derived)

- **The recipe** (`experts.avatar`, migration 026) is `{style, seed}` — not an
  image (`hue` is still in the stored shape and always null). NULL means "fall
  through", and choosing pins it, which also fixes the older annoyance that a
  rebuild wrote a new persona name and silently changed an expert's monogram.
- **The found picture** (`expert_pictures`, migration 027) is what a freshly built
  expert arrives with: the lead image of the Wikipedia article on its subject, found
  during the build, licence-checked, stored as bytes in Postgres and served by
  `GET /experts/{slug}/picture` under the same read rule as the expert itself. The
  `?v=` on that URL is the image's content hash, which is the only reason its
  `immutable` cache header is safe — always build it with `pictureUrl()`.
- **The monogram** is the fallback, and is what every expert looked like before either.

**The build never writes `experts.avatar`.** That is the whole reason the picture is a
separate table rather than a seventh avatar style: a style written by the builder would
be indistinguishable from one a person chose, and the next build would overwrite their
decision. It is also why `{"avatar": null}` — the picker's Reset — now means "back to
the picture", and why Remove (`DELETE …/picture`) is a _separate_ action from picking
the monogram in the style grid.

**Still nothing is uploaded.** A user cannot put an arbitrary image beside answers that
cite real sources: the recipe is drawn from a pure function, and the picture is a file
we fetched, licence-checked and stored ourselves — free licences only, no flags or
logos, and **no living people**, which beside an invented name is a worse
misrepresentation than a generated face would be. It is served same-origin, so there is
no third-party origin in anyone's browser and no link to rot when a file is renamed on
Commons. The style allowlist is still enforced **server-side**
(`api/src/peritus/experts/avatar.py`) and still excludes every face generator —
including `thumbs`, which looks abstract at thumbnail size but has `eyes` and `mouth`
options.

CC BY and CC BY-SA oblige attribution, so `PictureCredit` renders wherever the picture
is the identity of a page (the Overview header, expert settings) and deliberately
nowhere a 20px tile is only a navigational mark.

## Testing

- `npx vitest run` — the SSE frame parser, the build-event reducer, the proxy's
  refresh paths, cookie shaping, the avatar resolver, the readiness gate, and the
  fixtures. The **type annotations in `tests/fixtures.test.ts` are the schema
  check**: there is no codegen, so binding each captured payload to its interface
  is what turns an API rename into a `tsc` failure rather than an `undefined` in
  someone's browser.
- `npx playwright test` — seven projects (desktop, laptop, two iPads, iPhone,
  Pixel, and a reduced-motion pass) against `e2e/mock-api/server.mjs`, which
  serves the same fixtures and **streams real SSE with real `id:` cursors**. A
  real build costs money and takes minutes, so it can never be what CI runs.
- `e2e/helpers.ts` holds the two assertions that run on every route in every
  project: no horizontal overflow, and 44px tap targets on the touch projects.
  `fillField` waits for hydration first: `fill()` a millisecond early and the
  `input` event lands with no listener, React hydrates over a field whose value
  it does not know about and leaves it there, so the field _looks_ filled while
  the component's state is empty — and the failure then points at whatever was
  supposed to appear next.
- **A canvas test must assert that pixels were painted.** `graph-settings.spec`
  counts opaque pixels, at the fixture's six nodes and at four hundred
  (`big-graph` in the mock). Asserting a correctly sized canvas is not a test:
  a blank canvas is also correctly sized, which is how the wedged paint loop
  above stayed green.
- `npm run lighthouse` — the budgets from web-design.md §9 (LCP < 2.5s, CLS <
  0.1, TBT < 200ms as the lab stand-in for INP) on `/` and `/login` without a
  session and on `/experts` and a seeded chat with one, three runs each,
  asserted on the median. It runs with **`throttlingMethod: "devtools"`**: the
  simulated default charges a streamed document's whole transfer to whichever
  element arrives last in it, and reported 2.9s for a landing-page paragraph
  that a really-throttled Chrome paints at 0.85s.
- `docs/real-device-checklist.md` is the part no emulated run can sign off, and
  `docs/deploy.md` is the environment and Supabase setup.
