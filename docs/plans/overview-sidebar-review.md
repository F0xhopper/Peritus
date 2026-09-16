# Expert Overview and sidebar — design review

**Date:** 2026-09-16
**Reviewed:** `/experts/[slug]` (the Overview) and the shell's navigation as it
appears around it: the rail, the expert sidebar, the nav drawer and the top bar.
**Against:** the working tree on `main`, which includes the uncommitted change
that drops the corpus report (kept-of-screened, Quality, "How these sources were
chosen") from the Overview. Findings are about what renders now.

## How this was reviewed

- **Code:** `components/experts/overview-page.tsx` and `overview/*`,
  `components/shell/{rail,expert-sidebar,nav-drawer,top-bar,shell-context}.tsx`,
  `app/(app)/layout.tsx`, `components/ui/status-dot.tsx`,
  `components/chat/new-chat-composer.tsx`, the loading skeleton, and the design
  intent in `docs/plans/web-design.md` §1c, §5, §6 and `web-production.md`.
- **Real data** on the dev server (`:3000`, five experts: Thomism, Aristotelian
  logic, Production Machine Learning, Beekeeping, Epigenetics) at 1440×900, dark.
- **Mock data** (`e2e/mock-api`) through a production build at iPhone 15 and
  iPad portrait, dark and light, for the drawer and the phone layout.
- **Not re-litigated:** the decisions already recorded in `web/AGENTS.md` — no
  per-expert colour, no StatPill, no borders "for definition", one quiet action
  in the top bar, chat gated on `readiness`, and the eighteen items from the
  September review. Where a recommendation touches one of those it says so.

Effort: **S** under an hour, **M** an afternoon, **L** a day or more.

## Summary

| # | Finding | Priority | Effort |
|---|---|---|---|
| O1 | The voice line is written to the model ("You teach…"), not to the reader | P1 | S |
| O2 | An expert with no persona but a usable corpus gets no explanation (Thomism) | P1 | S |
| O3 | On a phone the six properties stack into twelve lines and take the first screen | P1 | S |
| O4 | A building expert shows "Sources 0 · Passages 0" — fabricated zeros | P1 | S |
| S1 | The sidebar's identity card and the Overview row are two fills for one destination | P1 | S |
| S2 | The phone drawer's expert strip has no names | P1 | S–M |
| O5 | Key concepts render as an underlined paragraph that cannot be scanned | P2 | S |
| O6 | The properties repeat the sidebar's numbers and link nowhere | P2 | S |
| O7 | "Depth" and "Built" are underspecified; Built is the creation date | P2 | S |
| O8 | The page no longer says how the sources were chosen — decided, no change | — | — |
| O9 | The chat list under the composer duplicates the sidebar and disagrees with it | P2 | S |
| S3 | Once a build finishes there is no route to its log or cost | P2 | S |
| S4 | "Graph 1125" is a count with no unit | P2 | S |
| S5 | Two different "Settings" share one gear icon | P2 | S |
| S6 | The sidebar cannot be collapsed | P2 | M |
| S7 | Switching expert depends on unlabelled tiles; monograms collide | P2 | M |
| S8 | On an iPad in portrait no expert list has names | P2 | (with S7) |
| O10–O13, S9–S12 | Smaller consistency items | P3 | S each |

## What works — keep it

- **The document model.** Sigil, 24px name, topic line, properties, prose
  sections. It reads as a page about a person, not a dashboard, which is the
  right register for something that answers with citations.
- **Grey hierarchy and colour-as-status.** The green "Ready · concept map
  built" is the only colour on the page and it means something.
- **Ask-first for a new expert**, and the composer creating the conversation on
  send rather than on arrival, so abandoned visits do not litter the chat list.
- **Readiness gating** and the "It can answer now" notice during graph
  extraction — a working expert is never hidden behind its build.
- **The owner's avatar pencil badge** appears on hover with a mouse and always
  on touch. The picture credit sits where the picture is the identity.
- **The sidebar belongs to the expert.** Chats are listed under the expert they
  belong to, the active chat is highlighted, and the column survives
  navigation.
- **The drawer exists up to 1023px**, so an iPad in portrait can reach every
  page. The light theme holds up: surfaces step correctly and the status
  colours stay legible.
- **The skeleton matches the page** closely enough that nothing jumps.

## Overview findings

### O1. The voice line is addressed to the model — P1, S

`OverviewHeader` prints the first sentence of `persona_style` in italics under
the topic. `persona_style` is a system-prompt instruction, so on real experts it
reads as a command to someone else:

> *You teach Aristotelian logic as a craft with moving parts, not a museum piece.*
> *You teach the way you keep bees: start at the hive entrance, not the genome.*

It has no label, so a reader cannot tell what it is. It is also the line most
likely to be quoted when someone shares the page.

**Recommend.** Either of these, and the second is the real fix:

1. Do not print `persona_style` raw. Move it out of the header and into
   *About* under a label ("How it answers"), rewritten on the client to third
   person only if the model reliably starts with "You" — otherwise omit.
2. Have the persona stage write a one-sentence third-person `voice` field ("She
   teaches logic as a craft…") alongside the prompt-facing style, and show that.
   Until then, fall back to the bio only.

### O2. A persona-less expert with a usable corpus gets no explanation — P1, S

Thomism on the real server: `status = building`, `build_active = false`,
`readiness = graph_ready`, no persona. `dotState` correctly shows it as
**Ready · concept map built**, but:

- `degradedPersona` in `overview-page.tsx` is `status === 'ready' && !persona_name`,
  so the "No voice was written for this expert" notice never appears.
- The header is the topic alone with nothing under it; *About* is absent; the
  section heading becomes **Ask Thomism**; the sidebar header is "Thomism" with
  no subtitle. The page has nothing to say about who it is.

**Recommend.** Derive the notice from the displayed state, not the raw status:
`const degradedPersona = state === 'ready' && !expert.persona_name`. Give the
persona-less heading a neutral form ("Ask a question" rather than "Ask
{topic}"). Separately, the API should reconcile rows stuck in `building` with no
job — the web is papering over that.

### O3. On a phone the properties take the first screen — P1, S

`Property` stacks label-over-value below 480px, so on an iPhone six properties
are twelve lines with a row gap each. On the 393×852 viewport, *Status* through
*Built* runs from y≈300 to y≈780 — most of the first screen — before *About* or
the composer appears.

The stacking was chosen "rather than squeezing two columns into 360px", but
every label is eight characters or fewer (*Passages* is the longest) and the
longest values ("Ready · concept map built", "1,125 concepts · 1,552 links")
are ~170px at 13px. Two columns fit at 360 with room to spare.

**Recommend.** Keep `grid-cols-[auto_1fr]` at every width and let values wrap.
If the phone still feels long, the Home page already has the pattern for this:
one line of `text-xs text-fg-3` under the header — "Standard · 21 sources · 412
passages · 187 concepts" — with the full block from `md`.

### O4. A building expert shows fabricated zeros — P1, S

While a build runs the properties read **Sources 0 · Passages 0**. The rule in
`web-production.md` is that null means "not recorded", never zero; here the
zero means "not yet", which is a different fact. `failed` already hides the
corpus rows for this reason; `building` does not.

**Recommend.** Hide the corpus rows while `state` is `queued` or `building`, as
for `failed`, or render an em dash with "counting" as a hint. When the build is
`chat_ready` the numbers are real and can show.

### O5. Key concepts are an underlined paragraph — P2, S (counts: M)

Real concepts are 40–120 characters each ("Historical development and legacy
(medieval scholastic logic, Łukasiewicz's modern reconstruction, comparison
with modern predicate logic)"). Eight to ten of them joined by middots make a
five-to-seven-line block of underlined text at 720px, and a concept that wraps
is indistinguishable from the next one. The reader cannot scan them, count
them, or see how well each is covered — which is what "key concepts" is for.

**Recommend.** A list, one concept per row, two columns from ~560px, no
underline (row hover + a trailing `→` or count), so each concept is a target.
The ledger already filters by `?concept=`, and `sources.covered_concepts`
exists on the API (migration 012), so a right-aligned "6 sources" per concept
is possible; if that needs the corpus-report fetch this change is removing,
ship the list first and the counts when they are cheap. The design's own
version of this section (web-design.md §1b) was rows that expand to their
coverage.

### O6. The properties repeat the sidebar and link nowhere — P2, S

Twenty pixels to the left the sidebar says *Sources 28* and *Graph 1125*; the
properties say *Sources 28*, *Passages 830*, *Concepts 1125 concepts · 1552
links*. None of the values is a link, so the numbers are dead ends, and the
value repeats its label ("Concepts — 1125 concepts").

**Recommend.**

- *Sources* → `/sources`; *Concepts* → `/graph`; *Built* → the build page when
  a job exists (see S3). Underline on hover only, as the concept links do.
- Value "1,125 · 1,552 links", not "1125 concepts · 1552 links".
- Thousands separators. `Intl` is banned for rendered text (AGENTS.md), so add
  a fixed `formatInt` to `lib/format.ts` and cover it in `tests/format.test.ts`.

### O7. "Depth" and "Built" are underspecified — P2, S

- **Depth: Standard** means nothing to someone who let *Auto* pick the tier.
  The tier picker knows the budget; say it here: "Standard · up to 30 sources".
- **Built: 23 Aug** is `created_at`, i.e. when the expert was created. After a
  rebuild it is wrong, and it never reflects when the corpus was finished.

**Recommend.** Label it *Last built* and read the succeeded job's
`updated_at` from `buildStatus`, falling back to `expert.updated_at`. Keep the
absolute date in the `title` (already done by `DateText`).

### O8. The page no longer says how the sources were chosen — decided, no change

The uncommitted diff removes "28 kept of 210 screened", the Quality row and the
"How these sources were chosen" section. After it, the Overview's only quality
signal is a count, and the product's checkable claim — sources were screened
and every drop has a recorded reason — lives only on the Sources page.

Not a case for restoring the paragraph. It would have been a case for one
line — "28 kept · 176 dropped" linking to the dropped rows — but the removal
was a deliberate, recorded decision the same day (the audit surfaces are UI
noise; the API keeps the data): **no scores, rubric, screening prose or
dropped-source views in the web app unless asked.** So: nothing here. Leave
*Sources* as a count that links to the Sources page (O6).

### O9. The chat list under the composer duplicates the sidebar — P2, S

From `lg` the sidebar lists this expert's chats (title · relative time). The
Overview lists the same chats under the composer (title · message count),
capped at six with no way to the rest. Two lists of the same things, twenty
pixels apart, choosing different secondary facts.

**Recommend.** Home already solves this: its *Recent chats* is `lg:hidden`
because the sidebar carries them from `lg`. Do the same here. Below `lg`, add
the relative time so the two agree, and a "See all *n* chats" row when there
are more than six.

### O10. "Kinds of source" mixes format and genre — P3, S

"Web page 13 · Paper 8 · Encyclopedia 4 · Expert writing 2 · PDF 1". *PDF* is
a file format; the others are genres. And nothing here is a link.

**Recommend.** Resolve PDF to what it is (paper, book, report) in
`lib/source-kind.ts` or at ingestion, and link each kind to
`/sources?type=…`.

### O11. Top bar: self-link, duplicate overflow, buried Share — P3, S

- The crumb's avatar + name links to the Overview — the page it is on.
- The overflow holds Sources, Graph, Share…, Settings. From `lg` the first,
  second and fourth are sidebar rows beside it; Share is the only thing that
  lives here and it is last.

**Recommend.** On the Overview, render the crumb's expert as text with
`aria-current`. Put *Share…* first in the overflow. If sharing is the way
experts spread, a quiet "Share" text link in the header block beside the name
is worth more than a menu item — it does not break the one-action rule
because it is content, not chrome.

### O12. The right half is empty from 1280 — P3, idea

The 720px document sits centred in a 1,129px main. That is fine for reading.
The design's "small graph views as texture" (web-design.md §1) is the one thing
that would earn the space: a 200px static thumbnail of the concept map beside
the properties, linking to Graph. Optional.

### O13. Skeleton has eight property rows; the page has six — P3, S

`loading.tsx` renders eight label · value rows; a ready expert has six and a
failed one three. Trim to six and the swap stops shifting *About* by two rows.

## Sidebar findings

### S1. Identity card and Overview row: two fills, one destination — P1, S

The header card (`bg-expert-soft`, links to the Overview) sits directly above
the *Overview* row (`bg-raised` when active, links to the Overview). On the
Overview both are lit, so the column opens with two stacked "active" surfaces;
on every other page the card is still washed, so it always looks selected.
Every screenshot shows it.

**Recommend.** Make the header card *be* the Overview link — active fill only
when the Overview is open, `aria-current` — and drop the Overview row. The
rows become Sources, Graph, Settings. This is the Notion/Linear pattern: the
page's own name is how you get back to it. If a labelled "Overview" row is
wanted for discoverability, then the header must lose its link and its wash.

### S2. The phone drawer's expert strip has no names — P1, S–M

Below `md` the drawer opens with a horizontal strip: Home, one 40px tile per
expert, `+`. The tiles have `aria-label`s but no visible text, the rail's
tooltip does not exist on touch, and this column "never lists the experts" —
so switching expert on a phone means tapping an unlabelled grey square. Two
monograms with the same initials are indistinguishable (the mock run produced
two "MB" tiles side by side; the real workspace has "CM" and "MO").

**Recommend.** Below `md`, replace the strip with rows — 24px avatar, name,
status dot — under a *Switch expert* label, with a *New expert* row, and the
selected expert's pages beneath as now. It costs one row per expert; with the
rail's own stated limit of about fifteen that is fine.

### S3. No route to the build log or cost once a build finishes — P2, S

`/experts/[slug]/build` is reachable from the Overview's "Building…" action
and its notice, Home's *Building now* card, and the graph and chat pages —
all only while a build is in flight. After it finishes, the log (kept/dropped
rows with reasons) and the cost-by-stage panel are orphaned.

Seen on the real server: `/experts/aristotelian-logic/build` shows **Build
finished** and, below it, **Waiting for Peritus to start this build…** on the
same screen — the empty-log placeholder does not know the build is over.

**Recommend.** A *Build* row in the sidebar (History icon) after Settings,
shown when `buildStatus` has a job; or link *Last built* (O7) to it. Fix the
placeholder copy: "No log was kept for this build" when the job has ended.

### S4. "Graph 1125" is a count with no unit — P2, S

*Sources 28* counts sources. *Graph 1125* counts… concepts, which the reader
has to guess. Also no thousands separator.

**Recommend.** The cheapest fix is `title`/`aria-label` "1,125 concepts" and a
separator. The better one is to call the row and page **Concepts** — the
Overview already uses that word for the same number — so the shell reads
Sources · Concepts · Settings.

### S5. Two different "Settings" share one gear — P2, S

The sidebar row *Settings* is the expert's (avatar, sharing, rebuild, delete).
The rail's gear directly below-left is the account's. The drawer's bottom row
shows the account email with the same gear. Same icon, same word, two things.

**Recommend.** Name the row *Expert settings* or give it `SlidersHorizontal`;
keep the gear for the account; label the drawer's bottom row *Account*.

### S6. The sidebar cannot be collapsed — P2, M

`web-design.md` §5 says "Expert sidebar, 260px, collapsible"; nothing in the
shell collapses it. On a 1280 laptop the ledger and the graph get 964px.

**Recommend.** A toggle at the Search row (`⌘\` / `Ctrl \`), state in
`localStorage` (per-viewer convenience, so that is the right store), the rail
unchanged. When collapsed, the top bar's menu button reappears so nothing
becomes unreachable.

### S7. Switching expert depends on unlabelled tiles — P2, M

The rail is the expert list and it has no text. Two of the five real experts
are grey monograms; the found pictures are dim at 40px and 70% opacity. The
design admits the limit ("recognition depends on the avatars being distinct").
The no-colour decision stands; within monochrome:

**Recommend.**

- A chevron on the sidebar's header card that opens a **switcher menu**:
  every expert with avatar, name, topic and status, plus *New expert*. One
  control answers "where do I switch?" on desktop and iPad alike.
- `⌘1`–`⌘9` for the first nine, listed in the palette.
- Inactive tiles at 85% opacity rather than 70%.
- Default new experts to a generated drawing (the picker already offers
  several styles) so fewer of them are two grey letters.

### S8. On an iPad in portrait no expert list has names — P2, with S7

Between 768 and 1023px the rail is visible (so the drawer hides its strip) and
the sidebar never lists experts. Hover does not exist on touch, so the rail's
tooltip names are unreachable. The only named list is Home. S7's switcher
menu fixes this at the same time.

### S9. Chats: unlabelled "+", no grouping, no row actions — P3, S–M

- The section's `+` has an `aria-label` but no tooltip, so a mouse user does
  not know it means "new chat". Wrap it in `Tooltip`. Keep its behaviour
  (focus the composer): creating a conversation on click would litter the
  list, since nothing prunes empty chats.
- Past twelve chats a filter field appears. Grouping by day (Today, Yesterday,
  This week, Older) is what readers expect and scans better than typing.
- Rename and Delete exist only in the chat page's overflow. A hover `⋯` on the
  row is the common expectation and costs little.

### S10. Home sidebar: "Credits 2" in the count slot — P3, S

Every other count in that column is a number of things in the row. A balance
in the same slot reads as "two credit items". Put it in the label: "Credits · 2",
or show it as `2 cr` with a `title`.

### S11. Rail: two active indicators — P3, S

Home's active state is a filled tile; an expert's is the edge bar with full
opacity. One indicator for both — the bar — keeps the rail to one rule.

### S12. Aria names differ between rail and drawer — P3, S

The rail labels a tile "{name} — {topic}" (`displayName` + `subtitle`); the
drawer strip labels it `persona_name ?? topic`. Use the rail's form in both.

## Prioritised plan

| Order | Change | Effort | Where |
|---|---|---|---|
| 1 | O2: notice keyed on `dotState`; neutral heading for persona-less experts | S | `overview-page.tsx` |
| 2 | O4: hide corpus rows while building | S | `overview/properties.tsx` |
| 3 | O3: two-column properties at every width | S | `overview/section.tsx` |
| 4 | S1: header card is the Overview link; drop the row | S | `expert-sidebar.tsx` |
| 5 | O1: stop printing `persona_style`; third-person voice at build time | S + API | `overview/header.tsx`, persona stage |
| 6 | S2: named expert rows in the phone drawer | S–M | `nav-drawer.tsx` |
| 7 | O6 + S4: linked properties, `formatInt`, "Concepts" row | S | `properties.tsx`, `expert-sidebar.tsx`, `lib/format.ts` |
| 8 | O5: concepts as a list | S | `overview/coverage.tsx` |
| 9 | O9: chat list `lg:hidden`, relative time, "see all" | S | `overview-page.tsx` |
| 10 | S3: Build row / Last-built link; empty-log copy | S | `expert-sidebar.tsx`, `build-log.tsx` |
| 11 | O7: Depth hint, Last built from the job | S | `properties.tsx` |
| 12 | S5: rename expert Settings / icon; drawer "Account" | S | `expert-sidebar.tsx`, `nav-drawer.tsx` |
| 13 | S7 + S8: switcher menu on the header card, `⌘1–9` | M | `expert-sidebar.tsx`, `command-palette.tsx` |
| 14 | S6: collapsible sidebar | M | `layout.tsx`, `shell-context.tsx` |
| 15 | O10–O13, S9–S12 | S each | as noted |

## Not recommended

- **Per-expert colour** to fix rail recognition — decided against in
  `web/AGENTS.md`, and the switcher (S7) solves the same problem without it.
- **Restoring "How these sources were chosen", kept/dropped counts or scores**
  — removed on purpose the same day, and the decision is recorded: the audit
  surfaces stay in the API and out of the UI unless asked (O8).
- **A stat pill or stat tiles** on the Overview — removed once for good reasons.
- **A bottom tab bar on phones** — the reading surface's height is the right
  priority; the drawer is the right answer, it just needs names (S2).
- **Borders on the identity card** to separate it from the rows — the fix is
  fewer fills, not more lines.

## Method notes for next time

- The Claude-in-Chrome tab reports `visibilityState: hidden`; View Transitions
  throw `InvalidStateError` there and lazy images and first-paint staggers do
  not run, so Home's expert cards and the header avatar can look blank. They
  are not. Judge motion and images headless.
- Playwright's desktop project times out on `waitForLoadState('networkidle')`
  on any page that tails a build — the SSE connection never idles. Wait on
  `load` plus a selector instead.
- `next build` while `next dev` runs is safe in Next 16 (`.next/dev` is
  separate), so a production build for screenshots does not disturb the dev
  server.
