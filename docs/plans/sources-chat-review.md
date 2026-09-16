# Sources page and chat page — design review

**Date:** 2026-09-16
**Reviewed:** `/experts/[slug]/sources` (the Sources page: table, card list, row
detail, add/export) and `/chats/[id]` (the chat: transcript, answer card,
citations, passage panel, composer, top bar).
**Against:** the working tree on `main` after the same-day removal of the audit
surfaces (scores, rubric, screening prose, dropped-source views). That removal
is a recorded decision and this review does not argue with it; nothing below
asks for a score or a dropped row back.

## How this was reviewed

- **Code:** `components/ledger/*`, `app/(app)/experts/[slug]/sources/*`,
  `lib/source-kind.ts`, `components/chat/*`, `hooks/use-chat-stream.ts`,
  `components/shell/context-panel.tsx`, the two loading skeletons, and the
  intent in `docs/plans/web-production.md` (Ledger, Conversation) and
  `web-design.md` §6, §8. Two API files where a web symptom had an API cause:
  `api/src/peritus/search/domain.py` and `api/src/peritus/chat/grounding.py`.
- **Real data** on the dev server (`:3000`): the Beekeeping expert's 16 sources
  and its chat "What is the queen bee?", at 1440×900 dark. No message was sent
  against the real API.
- **Mock data** through a production build at desktop (dark and light) with a
  streamed turn, and at iPhone 15 and iPad portrait: the card list, the sort
  select, the detail sheet, the citation sheet, the add-source dialog.
- **Not re-litigated:** `web/AGENTS.md` decisions — per-answer citation
  numbering, the top-anchored transcript, one quiet top-bar action, no borders
  for definition, the audit-UI removal.

Effort: **S** under an hour, **M** an afternoon, **L** a day or more.

## Summary

| # | Finding | Priority | Effort |
|---|---|---|---|
| C1 | "Cited passage" shows a title plus "Exa · Q:8.5", never a passage | P1 | S (API) + S (web) |
| C2 | "Delete chat" deletes with no confirmation and no undo | P1 | S |
| R1 | The title column is capped at 22rem; every title is cut and the host is clipped with it | P1 | S |
| R2 | Titles carry HTML entities, ALL CAPS and three identical rows | P1 | S (API) |
| R3 | The concept filter shows the unfiltered count | P1 | S |
| C3 | Opening a citation at `xl` shifts the whole transcript sideways | P2 | S |
| C4 | The "how this was answered" trail vanishes on reload | P2 | S–M |
| C5 | "Disputed" sends the reader to find the disagreement themselves | P2 | S–M |
| C6 | A new chat is an empty column with a box | P2 | M |
| C7 | The cited-sources list is collapsed, and it is the only place source names appear | P2 | S |
| R4 | Rows open a detail but nothing says so (`cursor-default`, no chevron) | P2 | S |
| R5 | Sort by "Added" with no Added column; the arrow toggles nothing | P2 | S |
| R6 | No find-as-you-type filter over the sources | P2 | S |
| R7 | Three vocabularies for one fact: "Paper", "Openalex", "Exa"; "Difficulty 5" | P2 | S |
| R8 | The detail omits how much of the source was read | P2 | S |
| R9 | "Covers" concepts in the detail are not links | P2 | S |
| R10 | "Ask about this" leaves the page for the Overview composer | P2 | S |
| C12 | The passage panel's heading uses the passage index, not the number on the chip | P2 | S |
| R14 | On a phone the toolbar is three unlabelled controls; the sort says "Type" where the column says "Kind" | P2 | S |
| C8–C11, C13, R11–R13, R15 | Smaller items | P3 | S each |

## What works — keep it

- **The table is quiet and fast.** 28px rows, a sticky header, no borders,
  sort as URL state with a dimmed transition rather than a spinner. Rows take
  focus and open on Enter.
- **The card list below `md`** shows exactly what is scanned for — title, kind,
  host, passage count — and puts the rest in a sheet.
- **The answer card.** Avatar and name, Markdown formatted as it streams,
  citation chips numbered 1, 2, 3 per answer, an invented marker rendered as
  dotted plain text with an explanation, a "Cut short" chip when an answer
  ends mid-sentence, and one row of quiet actions. No bubbles.
- **The passage sheet on touch** opens at 50% with the chip scrolled to the top
  first, so the sentence and its evidence are on screen together.
- **The composer**: one measure with the transcript, Stop replaces Send in
  place, grows to six lines, sits above the iOS keyboard, never autofocuses on
  touch.
- **Failure states are durable.** An unanswered question shows "No answer was
  recorded" with *Ask it again* after a reload, not a blank.

## Sources page findings

### R1. The title column is capped and the host is clipped with it — P1, S

`ledger-table.tsx` renders the title as `max-w-[22rem] truncate` (352px)
inside a table that is ~990px wide at 1440. Every real title is cut ("A
Virulent Strain of Deformed Wing Virus (DWV) of Hon…") while the middle 60% of
the table is empty. The host (`hostOf(url)`) is a suffix *inside* the same
truncated span, so it survives only on short titles: "Thomas Seeley
as.cornell.edu" shows it; every paper hides it.

**Recommend.** Let the title column take the width: drop the `max-w`, keep
`truncate` at the cell, keep `title=` for the full text. Put the host in its
own muted column (or under the title on the card list), so a reader can tell
a doi.org paper from a blog post without opening the row.

### R2. Titles carry markup, shouting and duplicates — P1, S (API)

Seen on the real table:

- `The symbiotic bacteria &lt;i&gt;Frischella perrara&lt;/i&gt;…` — HTML
  entities and tags stored in the title. Nothing in `api/src/peritus/sources/`
  unescapes them.
- `LANGSTROTH ON THE HIVE AND THE HONEY-BEE, A…` — an all-caps title from the
  source's own metadata.
- `The ABC and XYZ of bee culture…` three times, with nothing on the row to
  tell them apart.

**Recommend.** At ingest: `html.unescape`, strip tags, and title-case a title
that is more than ~80% capitals; a one-off migration for stored rows. On the
row: author or year beside the title (R1's host column does the rest). Merging
the three duplicates is the corpus-quality plan's job, not this page's.

### R3. The concept filter shows the unfiltered count — P1, S

`?concept=` filters client-side, but the toolbar's count is `total` from the
report page: "16 sources" over a table of 6 rows. The "clear" control is an
underlined word after the chip.

**Recommend.** "6 of 16 sources cover *Queen rearing…*" when a concept is set,
and an × inside the chip. Keep the chip's `bg-expert-soft`; it is a filter
token, which is close enough to a ledger decision to be a sanctioned chip.

### R4. Rows open a detail, but nothing says so — P2, S

`tr` has `cursor-default`, no chevron, no "details" affordance. A reader with
a mouse sees a hover fill and nothing else; the detail panel is discoverable
by accident.

**Recommend.** `cursor-pointer`, a trailing chevron column at `md`+, and
`aria-label="Open details"` on the row. On the card list the whole card is a
button already; add the chevron there too.

### R5. Sort by "Added" with no Added column — P2, S

The sort control offers Title / Type / Added, but the table has no date
column, so "Added" reorders rows by something the reader cannot see. The
`↓` on the active header suggests a direction toggle; clicking it re-sorts
the same way.

**Recommend.** Either an *Added* column (date, right-aligned, from
`created_at`) or drop that sort. If the API takes an order, a second click
flips it; if not, replace the arrow with a plain active state.

### R6. No find-as-you-type filter — P2, S

Thomism has 37 kept sources; a Pro build has up to 60. The only way to find
one is to read the list. The sidebar already has the pattern (a filter field
over loaded rows past twelve).

**Recommend.** A filter field in the toolbar, client-side over the loaded
page, matching title, author and host. Show it from about twenty rows.

### R7. Three vocabularies for one fact — P2, S

The table says **Kind: Paper**. The detail says **Type: Openalex** and
**Content: Paper**. The chat's passage panel says **Type: Exa**. Both panels
use `humanise(source_type)`, the raw fetcher key, while the table uses
`sourceKind`. Also **Difficulty: 5** — the validator's scale is 1
(introductory) to 5 (expert), which the reader is not told — and **Tier:
Primary** without the noun.

**Recommend.** One vocabulary: `sourceKind` everywhere the reader sees "what
is this"; "Found via OpenAlex" (`sourceProvider`) as a second line where
provenance matters. Difficulty as words ("Expert", "Introductory") with the
number in a `title`. "Primary source".

### R8. The detail omits how much of the source was read — P2, S

`full_text_method` exists and `describeTextRead` already phrases it
("Abstract only", "Full text", "Open-access PDF"). It is not shown. Whether a
paper's 1 passage came from its abstract or its full text is the single fact
that changes how far a reader trusts a citation from it — and it is a
reader-facing fact, not audit prose.

**Recommend.** One row in the detail: *Read · Abstract only*. Nothing else from
the removed set.

### R9. "Covers" concepts are plain text — P2, S

The detail lists the concepts a source covers; the page already filters by
`?concept=`. Each concept should be that link.

### R10. "Ask about this" leaves the page — P2, S

From a row's detail, *Ask about this* stashes a draft and navigates to the
Overview's composer. From the chat's passage panel the same words draft into
the composer in place. Two behaviours for one label, and the Sources one is a
round trip through a page the reader did not ask for.

**Recommend.** Start a chat directly with the drafted question
(`useStartChat` + `stashPendingQuestion`), landing in the new chat — the same
rule the build page follows ("Ask now lands in a chat").

### R11. Export is the action; Add a source is duplicated — P3, S

*Export* is the top bar's one action and *Add a source* sits in the toolbar
**and** the overflow. Keep Export where it is; drop *Add a source* from the
overflow, and keep the overflow to what is not on screen.

### R12. The skeleton has a border the table does not — P3, S

`sources/loading.tsx` draws the table container with `border border-border`;
the real table is a borderless `bg-panel`. The swap flashes a rule away.

### R13. Export formats — P3, S

CSV and RIS are right. BibTeX is the one people building a bibliography in
LaTeX will ask for; it is a small addition to the existing RIS writer.

### R14. The phone toolbar is three unlabelled controls — P2, S

Below `lg` the toolbar is a native select whose only visible text is
**Title**, a square **+**, and a bare download icon in the top bar. "Title"
reads as a filter or a column, not as "sorted by title"; nothing says what
`+` adds. The select's options are Title / **Type** / Added while the column
and the cards say **Kind**.

**Recommend.** Option labels "Sort: Title", "Sort: Kind", "Sort: Added" (the
select then labels itself), and the word *Add* beside the `+` from 360px —
there is room, the count on the right is short. Match "Kind" everywhere.

### R15. "Characters 48,210" in the detail — P3, S

Raw text length is not something a reader decides anything with. Replace the
row with *Read* (R8), which is.

## Chat page findings

### C1. "Cited passage" never shows a passage — P1, S (API) + S (web)

The panel is titled *Cited passage* and its blockquote is "the cited span
itself" in the expert's wash. On a real chat it reads:

> LANGSTROTH ON THE HIVE AND THE HONEY-BEE, A Bee Keeper's Manual, — Exa · Q:8.5

That is not a passage. `SearchResult.citation` in
`api/src/peritus/search/domain.py` builds the label as
`"{title} — {SourceType} · Q:{quality}"`, and `used_citations()` in
`chat/grounding.py` sends `n`, `label`, `source_id` — while `Passage.text` sits
on the same object and is never sent or stored. Consequences on the page:

- The panel shows the title three times (blockquote, source title, cited list)
  and the quote zero times.
- Citations [1] and [2] from the same source have identical labels; the
  reader cannot tell what either supports.
- "Exa · Q:8.5" — a fetcher name and a screening score — is in the blockquote,
  in the hover popover, in the cited list, and in every chip's `aria-label`.
  The audit removal took the scores off the Sources page; they are still
  spoken aloud on every citation.
- "Type: Exa" in the panel (see R7).

**Recommend.**

1. API: label = title only. Add `text` (the passage, or `context_text`
   trimmed to ~600 chars) to each citation in the `sources` event and to the
   persisted `citations` column (a migration; older rows stay text-less).
2. Web: blockquote the text; "Passage 1 of *Langstroth on the Hive…*" as the
   heading; when two citations share a source, say so ("also cited as [2]");
   fall back to today's layout when `text` is absent.
3. `aria-label` becomes "Citation 1: Langstroth on the Hive and the Honey-Bee".

### C2. Delete chat has no confirmation — P1, S

The top bar's overflow item *Delete chat* calls the DELETE on click. There is
no dialog and no undo; the expert's own delete and a source's *Remove* both
confirm.

**Recommend.** The same `ConfirmDelete` pattern ("Delete this chat? Its
messages go too."), or an undo toast that holds the request for five seconds.

### C3. Opening a citation at `xl` shifts the transcript — P2, S

At 1440 the inline panel is a grid column, so the moment a chip is clicked the
720px transcript re-centres 130px to the left, and jumps back on close. The
reader's eye is on the sentence they clicked; it moves.

**Recommend.** Keep the transcript's left edge fixed when the panel opens:
at `xl`, left-align the 720px column with a fixed gutter rather than
`mx-auto`, or treat the panel as an overlay up to `2xl` and inline only
beyond. The context panel already has an overlay form.

### C4. The retrieval trail is session-only — P2, S–M

The *Show how this was answered* action appears only on the streamed turn.
After a reload every answer loses it, although the API records an audit row
per answer (migration 028) and the card explicitly handles `audit`.

**Recommend.** Return the per-message audit summary on `GET /conversations/
{id}` (or fetch it lazily when the action is clicked) so the trail survives
the session.

### C5. "Disputed" says "go and look" — P2, S–M

The chip's popover reads "Open the citations to see which says what." The
reader has to open every chip to find the two that disagree.

**Recommend.** Have the `sources` event carry which passages disagree (the
reconciler knows) and mark those chips; until then, list the cited sources in
the popover so at least the candidates are one tap away.

### C6. A new chat is an empty column — P2, M

A chat with no messages is a bare centre and a composer. Nothing says who the
expert is or what it can be asked, and the reader has usually just come from
a page that did.

**Recommend.** Until the first message: the one-line bio, then "Ask about"
followed by three to five `key_concepts` as tappable chips that fill the
composer. All of that data is already on the expert.

### C7. The cited-sources list is collapsed — P2, S

"2 passages cited" is a closed `<details>`. It is the only place on the page
where the sources' names appear as text, and it is closed by default on every
answer.

**Recommend.** Open by default when there are three or fewer citations; above
that, a one-line "Sources: Langstroth; Seeley" summary with the numbers,
expanding to the list.

### C8. No timestamps in the transcript — P3, S

`created_at` exists on every message; nothing shows it. Someone returning to
a chat cannot tell whether it is from today or last month.

**Recommend.** A quiet day divider between turns on different days, and the
time in a `title` on the user turn.

### C9. Copy copies markers without references — P3, S

*Copy* puts the raw Markdown with `[1]` `[2]` on the clipboard and nothing
that says what they are.

**Recommend.** Append the cited list ("[1] Title — host") to the copied text.

### C10. "Cut short" is said three times — P3, S

The chip in the header, the sentence under the body ("This answer stops
mid-sentence. Ask again"), and the *Ask again* icon in the footer all prompt
the same action. Keep the sentence with its link; drop the chip or the
footer duplicate.

### C12. The panel's heading is the passage index, not the chip's number — P2, S

Chips and the cited list show the per-answer number (`display`: 1, 2, 3).
`passage-panel.tsx` heads the panel with `Passage {citation.n}` — the
retrieval index. For an answer whose second citation is passage 7, the chip
says **2** and the sheet that opens says **PASSAGE 7**, which is exactly the
"where is 2?" confusion the per-answer numbering was introduced to end.

**Recommend.** `Passage {citation.display ?? citation.n}`, and the same in the
hover popover.

### C13. The composer placeholder wraps on phones — P3, S

"Ask Dr. Marta Belen about Varroa mite control in temperate beekeeping…" is
two lines at 393px, so the empty composer is two lines tall before a word is
typed. Below `sm`, use "Ask {name}…" or "Ask a question…".

### C11. Newline hint and overflow duplicates — P3, S

The Overview's composer says "Enter to send"; the chat's says nothing about
Shift+Enter. Add the same `text-xs` hint on fine pointers. The overflow's
*Open the expert* and *Sources* duplicate the sidebar from `lg`, as on the
Overview.

## Prioritised plan

| Order | Change | Effort | Where |
|---|---|---|---|
| 1 | C1: title-only label, `text` in the sources event and stored citations; panel shows the quote | S + S | `search/domain.py`, `chat/grounding.py`, migration, `passage-panel.tsx`, `citations.tsx` |
| 2 | C2: confirm before deleting a chat | S | `chat-view.tsx` |
| 3 | R1: title column takes the width; host in its own column | S | `ledger-table.tsx`, `ledger-cards.tsx` |
| 4 | R3: filtered count and × on the chip | S | `ledger-page.tsx` |
| 5 | R2: unescape and de-shout titles at ingest; author/year on the row | S (API) | `sources/*`, a migration |
| 6 | R7 + R8 + R15: one vocabulary; Difficulty as words; *Read · Abstract only* instead of Characters | S | `row-detail.tsx`, `passage-panel.tsx` |
| 7 | C12: panel heading uses the chip's number | S | `passage-panel.tsx`, `citations.tsx` |
| 8 | R4 + R5 + R9 + R14: row affordance, Added column, concept links, labelled phone toolbar | S | `ledger-table.tsx`, `ledger-page.tsx`, `row-detail.tsx` |
| 9 | C3: transcript stays put when the panel opens | S | `transcript.tsx`, `context-panel.tsx` |
| 10 | C7: cited list open when ≤3 | S | `assistant-card.tsx` |
| 11 | R6: filter field over the sources | S | `ledger-page.tsx` |
| 12 | R10: *Ask about this* starts a chat | S | `ledger-page.tsx` |
| 13 | C6: starter concepts on an empty chat | M | `chat-view.tsx`, `transcript.tsx` |
| 14 | C4: audit trail on persisted answers | S–M | API conversations endpoint, `chat-view.tsx` |
| 15 | C5: mark the disagreeing chips | S–M | reconciler payload, `assistant-card.tsx` |
| 16 | C8–C11, C13, R11–R13 | S each | as noted |

## Not recommended

- **Scores, rubric versions, drop reasons or a kept/dropped filter** on the
  Sources page — removed on purpose the same day; the API keeps them.
- **Chat bubbles or a bottom-anchored transcript** — both were tried and the
  reasons against them are in `web/AGENTS.md`.
- **Virtualising the transcript** — tens of messages, `content-visibility`
  already does the work, and find-in-page would break.
- **A grounding percentage on answers** — no calibration behind it; the
  retrieval trail's counts are the honest form.
- **Column picker or wide tables** — three columns plus a host and a date is
  the right size for a page that is scanned, not analysed.

## Method notes

- The Claude-in-Chrome tab is `visibilityState: hidden`, so the answer card's
  entrance fade never runs and the transcript looks empty. Forcing
  `animation: none; opacity: 1` on `article` in the page shows it; judge
  motion headless.
- The mock streams a whole answer in well under a second, so a "mid-stream"
  screenshot is the finished card. Slow the mock's token cadence if the
  status line needs to be seen.
- If `next start` logs `ENOENT … pages/500.html`, the `.next` build on disk was
  clobbered by a later build or dev run; rebuild before trusting any frame.
- Below `lg` a `text=…` locator can resolve first to the *hidden* sidebar
  row (both forms of every region are in the HTML, toggled by `hidden
  lg:flex`), and a `waitForSelector` on it waits forever. Scope such waits to
  `main` or to the visible element's exact text.
