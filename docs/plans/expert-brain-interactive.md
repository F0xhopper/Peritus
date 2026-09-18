# The brain you add to — and a build that grows it

**Date:** 2026-09-18
**Status:** proposed, nothing built. Companion to
[expert-brain.md](expert-brain.md); read that first — the layers, the layout,
the motion rule and the `/map` API are all defined there and not repeated here.
**Questions answered:** is the brain a picture *of* the expert, or the place an
owner works *on* the expert? And should a build look like the brain growing?
**Against:** `main` at `af303e5`, plus a working tree in which phase 0 of
expert-brain.md is under way (`api/migrations/034_node_key_concepts.sql` and
`api/src/peritus/graph/key_concepts.py` exist; neither the builder nor the
upload path calls them yet). Evidence is the build's event vocabulary, the
upload service, and the build and Sources pages.

## The short answer

**The brain is the interactive expert.** Not a visualisation that sits beside
the product: the one place where an owner sees what the expert knows, sees what
it lacks, and changes it. The rule this file adds to the map:

> Everything that changes what an expert knows **starts on the map and lands on
> the map.**

Add a source from the gap it fills and watch it take its place on the orbit.
Remove one and see which concepts go with it. Later: send Peritus to find a
missing text, and add a line to the syllabus.

**And yes — the build should be the brain growing.** expert-brain.md has it as
phase 8, "stretch, last because nothing depends on it". That undersells it, for
one reason found while reading the code: *growing* is not a build-page feature.
Adding one source already runs a job that is "deliberately shaped like a very
short build" and writes the same events to the same durable log. A reducer that
turns those events into a growing map is written once and used three times —
every build, every added source, and the replay of any finished build. So it
moves up, and the smallest use of it (one added source) ships first.

Two limits, both about honesty. The log stays: it is the evidence for a build
somebody paid for, and the brain sits above it, not instead of it. And the brain
draws **only what the event log says is true at that moment** — which today is
less than it needs (below), and rules out the most tempting effect, concepts
twinkling into the cloud while extraction runs.

No new model spend for any of the growing. Two of the later actions (find a
text, extend the syllabus) do spend, and are marked.

## What "adding to it" is today (verified)

**Three owner actions change what an expert knows:** add a source
(`AddSourceDialog` — a file up to 20 MB, pasted text, or a URL — queues an
`ingest_source` job), remove a source (`DELETE`, from `row-detail.tsx`), and
rebuild (Settings). Viewers have none of them.

**An ingest is a short build and says so.** `uploads/service.py` runs extract →
tag → embed → graph and emits `stage`, `upload_extracted`, `upload_embedded`,
and a terminal `done` whose summary carries `source_id`, `chunks`, `nodes` and
`edges`. When the expert is `graph_expanded`, `_extend_graph` extracts concepts
from the new passages and merges them into the live graph.

**The web throws all of that away.** `ledger-page.tsx` tails the job with
`useBuildEvents` and uses exactly one thing from it — `onTerminal`, to call
`router.refresh()`. The person who just taught their expert something sees a
toast that says "Reading…", and some time later a new table row.

**An upload's tags are coarser than a built source's.** `_tag_document` writes
`covered_concepts` and no `concept_depths`, so on the map every tag of an
uploaded source is `treats`. (`source_tier` is stored; the orbit's shape rule
works unchanged.)

**New concepts arrive without a sector.** `_extend_graph` does not assign
`key_concept_idx` — nothing does yet. Once phase 0 is wired into the builder it
must be wired here too, or everything a user adds lands in the unassigned arc.

**Removing a source leaves its concepts behind.** `delete_source` cascades the
chunks and, by design, keeps the graph nodes: "the node's `chunk_ids` simply
stop resolving". For retrieval that is harmless. For the map it means `/map`
must derive `source_ids` from a live join (it does, by design) **and drop any
node with no resolving chunk**, or removed knowledge lingers as orphan dots. The
correct consequence — a concept falls below the two-source bar and leaves the
cloud — is worth showing, not hiding.

**What the build log can draw today:**

| moment | event | carries | enough to draw? |
|---|---|---|---|
| the plan | `plan_ready` | `key_concepts`, `facets`, `concept_primary_texts`, `must_have_works`, `figures` | **yes** — the ring, its sectors, and every named text |
| the picture | `picture_ready` | — | yes — the nucleus swaps monogram for picture |
| a candidate judged | `source_validated` | `title`, `source_type`, `q`, `r`, `passed`, `drop_reason` | a speck that stays or fades; no id, no tags |
| a source kept | `source_ingested` | `title`, `chunks`, `total_chunks` | **no** — no id, tier or tags, so no angle on the orbit |
| coverage, per round | `coverage_report` | per-concept coverage | yes — the size of each key-concept disc |
| can answer | `chat_ready` | — | yes — the nucleus |
| extraction, per batch | `graph_batch_done` | `labels`, `edges` | a count; not *which sources* were read |
| graph done | `graph_ready` | `nodes`, `edges` | the cue to fetch `/map` |

So the ring and the ending are free, and the middle — sources taking their
places — needs two small additive fields (phase G0).

## The brain as the place you work

| action | where on the map | exists today | new |
|---|---|---|---|
| Add a source | toolbar; a gap; a key concept's panel; a file dropped on the canvas | API, dialog, job, events | the entry points; the landing |
| Remove a source | the source panel | API, confirm dialog | the preview of what goes with it; the fade |
| Find a missing text | the gap panel — "Look for it again" | the canonical-work resolver (`sources/canonical.py`) | a `find_work` job; **spends** |
| Extend the syllabus | a "+" at the end of a facet's arc | `_discovery_round`, per-concept feedback queries | an `extend` job; **spends**; its own plan |
| Rebuild | Settings, unchanged | — | — |

**Add, from where the need is.** Opened from a gap, the dialog arrives with the
named text's title and author filled in. Opened from a key concept, it says
which concept prompted it. Dropped on the canvas (fine pointer only; touch uses
the button), it arrives with the file taken — `takeFile` already exists. In all
three, **tagging stays automatic and the dialog must not promise where the
source will land.** `_tag_document` reads the document and decides what it
covers. If someone adds a book "for" divine simplicity and it lands under
ethics, that is the truth about the book.

**The landing.** One sequence, about 1.2 seconds in total, driven by the ingest
job's own events:

1. *Queued* — a hollow square with its title appears at the foot of the orbit,
   in the untagged arc, breathing slowly: it is being read.
2. `upload_embedded` — it fills.
3. `done` — the page refetches `/map`. The square travels along the orbit to its
   angle; its dendrites fire inward once; concepts it brought fade into the
   cloud; the key-concept discs it covers grow; **a gap it fills closes in
   place**, hollow to solid.

A failed ingest fades the square and shows the job's message, as today. Under
reduced motion all of it is instant, and a toast says what changed — "Added.
Covers 3 key concepts, 14 passages" — which is worth having in both modes and
is more than the product says now.

**Removal says what it costs first.** The confirm dialog computes, from the
`/map` payload already in hand, what the source holds up: "38 passages. 6
concepts will drop to a single source and leave the map. *On Being and Essence*
will be missing again." Then the square fades and the cloud thins.

**Find a missing text** *(later, spends)*. A gap's second action. The resolver
that the build uses for named works, run for one title: resolve → fetch →
validate → ingest, as a `find_work` job with the same event tail. A few cents a
try, and it can honestly fail — "not obtainable" is a status `syllabus.md`
already has.

**Extend the syllabus** *(later, spends, own plan)*. This is the one that
changes what the product is: an expert stops being the output of one build and
becomes something its owner grows. It is named here only so the map leaves room
for it, and for one constraint that has to be respected from the moment
migration 034 lands: **`experts.key_concepts` becomes append-only.**
`key_concept_idx` is an index into that array; reorder or delete a line and
every stored assignment points at the wrong disc. Appending is cheap — embed one
string, compare it with the node embeddings, and only nodes that are nearer the
new line move — and the ring takes an eleventh disc inside its facet's sector
with its neighbours easing over.

### Considered and not chosen

- **Notes or corrections pinned to a concept.** Pasted text is already a kind of
  source, chunked and cited like any other. A second kind of knowledge that an
  answer cannot cite breaks the one promise the product makes.
- **Dragging nodes to rearrange the map.** Position is meaning (a source sits
  near what it covers), and a map that differs per owner cannot be shared.
- **Editing, merging or deleting concepts by hand.** They are extraction output;
  a rebuild writes over them, and the edit would silently vanish.
- **Chat inside the map.** "Ask about this" goes to chat; phase 7 of
  expert-brain.md brings the answer back as lit sources. One link each way.

## The build as the brain growing

### Why it is worth doing

- **The build page is the product's first impression, and it is a log.** A stage
  timeline, a counts line, rows of text — accurate, and what a new user stares
  at for the whole of their first build, which with the Batch API on by default
  is not short.
- **It is not a metaphor.** A build forms the brain in the order the map is
  layered: the plan is the ring, the sources are the orbit, extraction is the
  cloud. expert-brain.md's one-second inward entrance is a re-enactment of this;
  the build page is the real thing.
- **It teaches the map.** Someone who watched the ring appear, sources gather
  round it and concepts fill the space between needs no legend on `/knowledge`.
- **Gaps get a better meaning.** At `plan_ready` every named text appears as a
  hollow square: *the texts this build is looking for*. The build fills them.
  What is still hollow at the end is the gap list — same mark, same meaning, and
  the reader saw how it came about.
- **Replay comes free.** The log is durable and ordered, so any finished build
  can be folded again, fast.

### The sequence

The brain stays **flat and unrotated for the whole build**. Growth is the
motion; turning the scene as well would have arriving sources chase a moving
target. It tilts into its idle orbit once, at `done`.

0. **Queued.** The nucleus alone — monogram, then the picture when
   `picture_ready` lands.
1. **`plan_ready`.** The ring draws disc by disc, facet by facet; facet names
   settle on their bisectors; the named texts appear hollow on the orbit.
2. **Discovery, triage, fetch, validation.** The longest stretch, and without
   something here nothing moves for minutes. Each `source_validated` may show a
   speck at the rim, outside the orbit: passed, it drifts onto the orbit as a
   faint square; dropped, it fades. **At most six in flight** — a build judges
   hundreds of candidates and the rest are counted, not drawn; "41 kept · 212
   dropped" stays as text. A faint square is *not yet a source*: composition
   caps can still drop it after validation.
3. **`source_ingested`.** The square goes solid at its angle, sized by
   √passages, and sends one pulse inward to the key concepts it covers. A named
   text that was found fills its hollow square instead of adding a new one.
   `coverage_report` resizes the ring's discs at the end of each round.
4. **`chat_ready`.** The nucleus's halo comes up, and "Ask now" rings once as it
   already does. The brain is visibly unfinished and already answers — rule 1 of
   the web, drawn.
5. **Graph extraction.** Per `graph_batch_done`, the sources in that batch pulse
   inward — they are being read — and a line counts "312 concepts found".
   **The cloud does not appear yet.** Which concepts clear the two-source bar,
   and what merges into what, is not known until entity resolution has run;
   dots that twinkle in and then vanish or jump would be showing something that
   was never true.
6. **`graph_ready`, then `done`.** Fetch `/map`. The cloud fades in sector by
   sector, the layout eases into exactly the frame `/knowledge` opens on, and it
   tilts. Whatever is still hollow is a gap.

### Rules for the growing

- **The reducer is a pure fold; only live events animate.** Opening the page
  mid-build, or reconnecting with `after=<seq>`, folds the replayed prefix to
  the current picture at once and animates nothing. The same prefix always gives
  the same picture.
- **A source's angle comes from its own tags** (the weighted circular mean in
  expert-brain.md), so later arrivals only nudge neighbours through the overlap
  relaxation. The ring never moves after `plan_ready`.
- **A retry empties the orbit.** `build-view.tsx` already knows a replayed log
  can hold a `chat_ready` "from an attempt whose corpus a later retry wiped".
  On `retry` the fold clears sources and coverage and keeps the ring.
- **Failed and cancelled builds keep what they grew**, stilled, under the
  existing notice. "Anything already found and screened is kept" becomes
  something a person can see.
- **Read-only while building.** Hover gives a title. Working on the expert is
  what `/knowledge` is for, and its data is not final until `done`.
- **The log, the timeline, the cost panel and every notice stay.** From `lg` the
  brain is a panel above the log. Below that it is a square capped at 280px with
  labels off, above the timeline — presence, not a workspace — and the log is
  the page, as now.
- **Reduced motion:** no specks, no pulses, no travel; the picture simply
  updates at each event. It is still there.
- **Accessibility:** `role="img"` with a summary that updates at stage
  boundaries only (`aria-live="polite"`), never per event. The log is the
  accessible form.
- **Cost:** paint only when an event arrives or an effect is in flight; the
  same 4ms budget; stop when `document.hidden`.

## Phases

Lettered, so they do not collide with expert-brain.md's numbers. G1 needs that
plan's phases 3–4 (layout, paint); G2 needs its phase 5 (the page).

**G0 — Events, and the two joins that are missing.** `source_ingested` gains
`source_id`, `tier` and `tags: [{ key_concept, depth }]`; `graph_batch_done`
gains `source_ids`. Both additive — `lib/build/reducer.ts` and the CLI ignore
keys they do not know. Key-concept assignment runs in the builder **before**
`graph_ready` is emitted, and in `_extend_graph`. `/map` drops nodes with no
resolving chunk. pytest on the payloads; fixtures and the mock API's SSE build
script gain the fields.

**G1 — The growth reducer.** `lib/brain/grow.ts`: a pure fold from the build
vocabulary (including the upload events) to a partial `/map` payload plus a list
of transient effects — arrive, settle, pulse, fade. Unit-tested against the
captured build log; the same prefix gives the same state.

**G2 — Add and remove on the map.** The four entry points, the landing, the
removal preview and fade, the "what changed" toast. **First, because it is the
smallest use of G1** — one source, a few events, no build to mock — and the one
an owner meets most often. *Done when* an added source lands at the angle
`/knowledge` gives it after a reload.

**G3 — The build page grows a brain.** The panel, the sequence, flat until
`done`; retry, failed and cancelled; the 280px form; reduced motion. E2E, per
the canvas rule in `web/AGENTS.md`: across the mocked SSE build the opaque-pixel
count never falls except on `retry`, and the last frame equals `/knowledge`'s
still frame for the same fixture. Replaces phase 8 of expert-brain.md.

**G4 — Replay.** "Replay" on a finished build's log: the stored events through
G1 at about 30×. Offered only where the log has G0's fields; older builds keep
the log alone.

**G5 — Find a missing text.** The `find_work` job and the gap's second action.
Needs a decision on how it is charged.

**G6 — Extend the syllabus.** Its own plan. The append-only rule above applies
from migration 034 onward whether or not this is ever built.

## What not to do

- Do not replace the build log with the brain, or hide it behind a tab.
- Do not draw concepts before `graph_ready`.
- Do not rotate or tilt while the build is running.
- Do not animate a replayed prefix on load or reconnect.
- Do not let the add dialog promise which concept a source will land on, and do
  not pass the tagger a hint to make it come true.
- Do not reorder or delete `key_concepts` once `key_concept_idx` is stored.
- Do not add a second kind of knowledge (notes) that answers cannot cite.

## Open questions

1. **Candidates as specks (step 2): show them or not?** Proposed: show, capped
   at six. Without them the longest part of a build is a still ring. The
   alternative is kept sources only, and a ring that waits.
2. **How are *find a text* and *extend* charged?** Credits per try, or inside a
   small allowance that comes with the build? There is no checkout (rule 3), so
   whatever is chosen has to work with "request credits".
3. **Below `lg`: the 280px brain, or nothing?** Proposed: the small brain. Check
   it on a real phone beside the idle-loop check in expert-brain.md phase 6.
4. **Should the landing be on the List view too?** Proposed: the toast and the
   new row only — the table is the still form of this page.
