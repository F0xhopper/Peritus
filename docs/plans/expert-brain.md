# The expert's brain — syllabus, concepts and sources in one map

**Date:** 2026-09-18
**Status:** proposed, nothing built.
**Question answered:** can Sources and Concepts become one thing — a knowledge
graph or "brain" per expert, showing the syllabus, the concepts and the sources
together — and can it look alive: orbiting, neurons firing?
**Against:** `main` at `af303e5`. Evidence is the code of both pages, the API
behind them, and the five experts in the production database (read-only).

## The short answer

Yes. One page, **Knowledge**, with two views of the same selection: a **Map**
(the brain) and a **List** (today's Sources table, kept whole).

The brain is **not** today's graph with sources added. Today's graph is 2,883
nodes for Thomism, two thirds of them sentences, and it is already unreadable.
The brain is a *layered* map of about 180 things:

- the expert at the centre,
- its **syllabus** — key concepts grouped by facet — as a fixed inner ring,
- the **concepts that more than one source discusses** as a neuron cloud,
- its **sources** on the outer orbit, feeding inward,
- and the **texts the plan named and the build never found** as hollow places
  on that orbit.

It looks alive when nobody is touching it (the plane tilts and the whole brain
turns slowly; a dendrite fires now and then) and it **flattens and holds still
the moment somebody engages**, because a map that moves under the pointer is a
toy. Every part of that motion is off under reduced motion, and none of it
carries information that is not also there when still.

Almost nothing here needs new model spend. The links the brain draws are already
in Postgres; the API throws them away on the way out.

## What is wrong today (verified)

**The two pages do not connect.** `node-detail.tsx` offers "Sources covering
this" only when a node's label equals a key concept. Across all five experts
that is **zero** matches — key concepts read "Being, essence, and existence
(act/potency)", nodes read "Divine simplicity". The button has never rendered.
Nothing on the Sources page points at the graph at all.

**The link exists and is dropped.** Every `expert_nodes` row carries
`chunk_ids`; a chunk has a `source_id`. `AuditRepository.full_graph` selects
`id, label, node_type` and a degree. It also drops `description`, and the
`point` / `condition` that migration 024 made mandatory on `contradicts` and
`qualifies` — the only thing that makes a dispute checkable.

**The graph as drawn is dots.**

| expert | kept sources | concept nodes | claim nodes | concepts with no edge | concepts in ≥2 sources | in ≥4 |
|---|---|---|---|---|---|---|
| thomism | 37 | 1,063 | 1,820 | 94 | 132 | 18 |
| aristotelian-logic | 28 | 765 | 360 | 242 | 136 | 23 |
| beekeeping | 16 | 424 | 182 | 200 | 20 | 3 |

At the default limit Thomism shows 400 nodes and **359** links — fewer links
than nodes. The busiest node is "Thomism" (174 links), which tells a reader of
the Thomism expert nothing. The sidebar's "Concepts 2,883" counts 1,820 claims —
whole sentences, elided to 32 characters when drawn.

**The syllabus is invisible.** `experts.research_plan` (migration 029) holds
facets, figures, must-have works and a named primary text per concept.
`build_summary.coverage.concepts[]` holds, per key concept, how many sources
cover it, at what depth (`sets_out` / `treats` / `mentions`, migration 030) and
whether its named text was `found`, `partial` or `missing`. The web shows the key
concepts as a list of links on the Overview and none of the rest. Thomism's
"Being, essence, and existence" is marked met while *On Being and Essence* — the
text the plan named for it — is `missing`. Nothing on screen says so.

**Disputes cannot lead the design yet.** Thomism has 2,606 `about` edges and
**zero** `supports` / `contradicts` / `qualifies`. That is
`retrieval-quality.md` F4 (the reconciler has produced no edges since it
shipped), still open. The brain marks disputes where they exist and must not
depend on them.

## The model: what is in the map

Four kinds of thing, and claims are not one of them.

| layer | what | count (Thomism) | from |
|---|---|---|---|
| nucleus | the expert | 1 | `experts` |
| syllabus | key concepts, grouped by facet | 10 in 5 facets | `experts.key_concepts`, `research_plan.facets`, `build_summary.coverage` |
| cloud | concept nodes found in ≥2 sources | 132 | `expert_nodes` via `chunk_ids → source_chunks.source_id` |
| orbit | kept sources | 37 | `sources` where `passed` |
| gaps | named texts / must-haves not in the corpus | 1 | `build_summary.coverage.concepts[].named_text`, `research_plan` |

Links:

| link | meaning | count (Thomism) | from | drawn at rest |
|---|---|---|---|---|
| source → key concept | the validator judged it to cover the concept, with a depth | ~100 | `sources.concept_depths`, else `covered_concepts` as `treats` | faint |
| source → concept | a passage of this source is where the concept was extracted | 374 | `chunk_ids` | **no** — lit on selection |
| concept → concept | `part_of` | 86 | `expert_edges` | faint |
| concept → key concept | which part of the syllabus a concept belongs to | — | **does not exist; phase 0** | never (it is position, not a line) |

**Claims stay out of the canvas.** They are sentences. They live in the concept
panel, each with its source and a way into the passage reader (PR #19).

**Thin corpora are topped up.** Beekeeping has 20 shared concepts, which is a
ring with nothing in it. Rule: if fewer than 60 concepts clear the two-source
bar, fill to 60 with the highest-degree single-source concepts, drawn at the
lowest alpha. A sector can be expanded to everything in it on demand
(`?expand=<key concept index>`), capped at 600 nodes on screen.

**Experts without a plan still get a brain.** Four of five experts today
predate `research_plan`. No facets means the ring has no sectors and key
concepts are spaced evenly in stored order; no named texts means no gaps;
`concept_depths` null means every tag is `treats`. Coverage numbers come from
`compute_coverage` over the kept sources rather than from `build_summary`, which
is also what keeps them right after a source is added or removed.

## The one missing join (phase 0)

A concept has to sit in a sector, so it needs a key concept. Two ways, and the
plan is to use both:

1. **By embedding.** Every node already has one (2,883 of 2,883 for Thomism).
   Embed each key-concept string with the same embedder
   (`node_embedding_text`) — at most 14 calls per expert, once — and assign each
   concept node its nearest key concept above a similarity floor. Below the
   floor it is *unassigned* and sits in a neutral arc, which is honest: some
   concepts belong to the topic and to no line of the syllabus.
2. **By source, as the tiebreak.** A node's sources carry graded key-concept
   tags. Where two key concepts are within a small margin by embedding, the one
   its sources `set_out` wins.

Stored, not computed per request: migration 034 adds
`expert_nodes.key_concept_idx SMALLINT NULL` and `key_concept_sim REAL NULL`.
Written at the end of graph extraction; a CLI backfill
(`peritus graph assign-key-concepts <slug>`) covers existing experts.

**This is the gate for everything visual.** Before phase 3, hand-check fifty
assignments on Thomism and fifty on beekeeping, pick the floor from what is
seen, and write the numbers into this document. If fewer than roughly four in
five are right, the sectors are decoration and the cloud should be laid out
without them (radial band only, no angular pull).

### Phase 0 — measured (2026-09-18)

Key concepts embedded with the node embedder (label only; nodes carry label +
description), cosine against the stored node embeddings, production data read
only. Fifty nodes per expert, sampled with seed 7: thirty of Thomism's 132
shared concepts plus twenty single-source ones, all twenty of beekeeping's
shared concepts plus thirty single-source ones. Each was judged against the
expert's key concepts by reading label and description. An unassigned node
counts as right when no line of the syllabus fits it ("Friendship", "Merit",
"Equity" in Thomism; "Root, E. R." in beekeeping).

| floor | Thomism right | beekeeping right | both |
|---|---|---|---|
| 0.35 | 35/50 | 38/50 | 73% |
| **0.40** | **41/50** | **38/50** | **79%** |
| 0.45 | 36/50 | — | — |
| 0.30 | — | 39/50 | — |

**Chosen: 0.40** (`KEY_CONCEPT_FLOOR`), tie margin 0.02 broken by the sources'
`sets_out` tags. Similarity spread: Thomism median best-match 0.43, beekeeping
0.46. The accuracy is at the gate, not comfortably over it, so the sectors are
kept but the angular pull is gentle (phase 3) — a concept a sector away from
where a reader would put it costs little when the pull is soft. Most errors
are *adjacent* sectors (a Varroa virus under "environmental threats" rather
than "pests and diseases"; "Thomas Aquinas" under the commentators), not
nonsense. Backfilled on a local copy: Thomism 651 of 1,063 concepts placed, 51
of the 132 drawn are unassigned; beekeeping 305 of 424.

## What it looks like

The chrome stays monochrome (`web/AGENTS.md`, *Colour*). Facets are **position,
never hue**. Tier is **shape and fill, never hue**. The only colour on the
canvas is `--warn`, on a dispute, because that is a status.

- **Nucleus.** The expert's avatar — picture, recipe or monogram — as a DOM
  element over the canvas centre, following the zoom transform, inside a soft
  halo. Not drawn into the canvas: `ExpertAvatar` already resolves the three
  levels and the picture credit.
- **Syllabus ring (R1).** Key concepts as the largest discs, `--fg`, always
  labelled. Size by how many sources cover them. Labels are the key concept with
  a trailing parenthetical dropped and elided at 28 characters ("Being, essence,
  and existence"); the panel has the whole string. Facet names sit as small caps
  at each sector's bisector, inside the ring. Hairline orbit in `--border`.
- **Cloud (band R2).** Concept nodes as small dots between the rings, pulled
  toward their key concept's angle. Alpha by number of sources (2 → 0.35,
  4+ → 0.8); the 4+ set — the spine, 18 nodes for Thomism — gets a soft glow and
  a permanent label within the existing collision-checked label budget.
- **Source orbit (R3).** Sources as rounded squares on a dashed outer orbit.
  Angle is the weighted circular mean of the key concepts a source covers
  (`sets_out` 3, `treats` 2, `mentions` 1), relaxed along the ring so none
  overlap; untagged sources share an arc at the foot. Primary tier filled,
  secondary outlined, tertiary outlined and smaller. Size by √passages. Labelled
  on hover and selection only — thirty-seven titles at once is the table's job.
- **Gaps.** A hollow dashed square on the source orbit at its concept's angle.
  Panel: "The plan named *On Being and Essence* (Thomas Aquinas) for this
  concept. It is not in this expert's sources." For an owner, **Add a source**
  beneath it — `AddSourceDialog` exists; a gap that leads to its own remedy is
  the single most useful thing on the page.
- **Dendrites.** Quadratic curves whose control point is pulled a fifth of the
  way toward the nucleus, so every link bows inward and the whole reads as
  radial and organic rather than as a net. Alpha tapers along the length.
- **Disputes.** A `--warn` ring on a concept whose claims carry a `contradicts`
  edge; the count and the `point` of each are in the panel.

The 24px grid goes. It says "diagram"; the rings already give the eye a frame.

### Motion

Three behaviours, one rule: **idle is alive, engaged is still.**

1. **Orbit (idle).** The layout is a flat 2D map — that never changes. When
   idle it is *drawn* tilted (y × 0.62, so rings become ellipses) and the whole
   scene turns as one rigid body about the nucleus, one revolution in eight
   minutes (under 5 px/s at the rim). Nodes on the near side are drawn slightly
   larger and brighter. Labels are always upright. Rings never turn
   independently: a source sits *near the concepts it covers*, and rotating one
   ring against another would destroy the only thing the angles mean.
2. **Flatten (engaged).** On the first pointer movement over the canvas, a
   touch, a keypress in the search, or any selection: tilt eases to 1.0 and
   rotation to its nearest rest angle over 400ms, and stays there. After six
   seconds with no pointer movement **and** no selection open, it eases back.
   Hit-testing inverts the live transform (unzoom → unscale y → unrotate) into
   layout space, where the quadtree already lives, so a click during the ease
   still lands.
3. **Firing.** Selecting a node sends one pulse down each of its dendrites
   (400–700ms, staggered by length); the links then stay lit and everything
   else drops to 15% alpha. Once, not looping. While idle, one random
   source → concept dendrite fires roughly every 800ms. That is the whole
   "thinking" effect and it costs one moving dot.

   On first load, pulses run **inward** — orbit to cloud to ring — once. It is
   the one moment the picture says what it is: sources feed concepts feed the
   syllabus.

Every visit opens on the same frame (rotation phase starts at zero, layout is
deterministic), so the map is learnable.

**Reduced motion:** always flat, never turns, no pulses, no entrance; selection
lighting is instant. The worker already settles before its first post.

**Cost.** Today a settled graph paints nothing per frame, and that stays true
whenever the brain is flat and nothing is firing. The idle loop runs at 30fps,
stops when `document.hidden` or the canvas is off-screen, and never uses
`shadowBlur` — glow is one pre-rendered sprite drawn with `drawImage`. Budget:
4ms per paint at 250 nodes and 700 links on a mid-range laptop; check the idle
loop on a real phone before phase 6 is called done
(`web/docs/real-device-checklist.md`).

### Considered and not chosen

- **A true 3D brain (three.js / WebGL sphere).** Half the nodes are behind the
  other half, labels occlude, there is no stable "where things are", a canvas
  test can no longer count pixels meaningfully, and it adds ~150 KB to draw 250
  dots. The tilt gives the depth cue for the price of one multiply.
- **Rings turning at different speeds.** Looks like a planetarium, means
  nothing, breaks source-near-its-concepts. Above.
- **Facet colours.** The product has no decorative hue anywhere and the reasons
  are in `AGENTS.md`. Twelve expert hues were removed for the same reason.
- **Claims as nodes, or sources added to the current graph.** 2,920 nodes.

## The page

**One sidebar row, "Knowledge",** replacing *Sources* and *Concepts*; count is
the source count. (*Brain* is the other candidate name. The product's vocabulary
is sober — Sources, Ask, passages — and *Knowledge* matches it; it is a
one-word change if that call goes the other way.)

- Route `/experts/[slug]/knowledge`. `?view=map|list`.
  `/experts/[slug]/sources` and `/graph` redirect to it with their params;
  `/sources/[id]/read` stays where it is.
- **Selection is URL state and shared by both views:** `?source=<id>` (exists),
  `?concept=<key concept>` (exists — keeps the Overview's links and its current
  meaning), `?node=<id>` (new, a cloud concept). Switching view keeps the
  selection; the table scrolls to the selected row, the map focuses the node.
- **One right-hand `ContextSlot`, three panels,** identical in both views:
  - *Source* — today's `RowDetail`, plus **Concepts from this source**.
  - *Concept* — `NodeDetail` rewritten: description, **Said by** (its sources,
    each opening `?source=`), its claims as sentences with the source and a
    link into the passage reader, disputes first with their `point`, then
    *Part of*. "Ask about this" stays.
  - *Key concept* — coverage in words: "12 sources; 5 set it out, 7 treat it",
    the named text and its status, its facet, **Show in list** (the existing
    concept filter), "Ask about this".
- **Defaults.** Map from `lg` with a fine pointer; List below. `useMediaQuery`
  may not choose at first paint (`AGENTS.md`), so with no `?view=` both are in
  the HTML behind `hidden lg:block` / `lg:hidden` — and **the canvas must not
  start its worker while it has no size**. Today it falls back to 800×600 and
  would run a simulation inside `display: none`.
- **The Nodes slider goes.** "400 of what?" is not a question a reader can
  answer. Its replacement is expanding a sector.
- **Search** finds across all three kinds — a source title, a concept, a key
  concept — and focuses it in whichever view is open.
- **Accessibility.** A canvas is opaque to a screen reader. The List *is* the
  accessible form of this page, the toggle sits beside the canvas, and the
  canvas is `role="img"` with a summary ("37 sources, 10 key concepts in 5
  facets, 132 concepts; 1 named text missing"). Search plus the panels' own
  links are the keyboard path through the map.
- **Viewers** (share links) see all of it except *Add a source* on a gap;
  `canManage` as everywhere else.

## API

Keep `GET /{slug}/graph` until the old page is deleted. Add:

**`GET /experts/{slug}/map`** → `computed`, and when true:

```
syllabus: {
  facets: [{ name, concepts: [index] }] | null,
  key_concepts: [{ index, label, facet, sources, depth_counts, met,
                   named_text: { status, title, author } | null }],
  gaps: [{ key_concept, title, author, kind }]
}
sources:  [{ id, title, kind, tier, passage_count,
             tags: [{ key_concept, depth }] }]
concepts: [{ id, label, key_concept | null, source_ids, degree,
             disputes, topped_up }]
links:    [{ from, to }]            # part_of, among returned concepts
totals:   { concepts, concepts_shown, claims, sources }
```

`computed: false` keeps its meaning and its full-centre "still being extracted"
state — but the ring and the orbit do not need the graph, so an expert at
`chat_ready` gets **syllabus and sources drawn, and an empty cloud with a line
saying concepts are still being extracted.** Rule 1 of the web (gate on
readiness) in its spirit: do not hide what is already true.

**`GET /experts/{slug}/map/concepts/{id}`** → description, every source, claims
(`claims_by_concept` exists) each with `source_id`, `chunk_id`, text, and its
relations with `point` / `condition`. Lazy, because it is the only heavy part
and only one concept is ever open.

Both under `ReadableExpert`. No claim text in the bulk payload.

## Phases

Each one ships alone and is worth having if the next never happens.

**0 — The join, measured.** Migration 034; key-concept embedding and assignment
at the end of graph extraction; backfill CLI; the hundred hand-checks above,
written into this file. *Done when* the floor is chosen from data and the
accuracy is stated.

**1 — The API.** `/map`, `/map/concepts/{id}`; live coverage through
`compute_coverage`; pytest for a planless expert, a `computed: false` expert, a
thin corpus top-up, a viewer. TS interfaces, `tests/fixtures/map*.json` bound in
`fixtures.test.ts`, mock-API routes including a `big-map`.

**2 — Fix the dead bridge on the pages that exist.** Concept panel gets
description, *Said by* and claims; source panel gets *Concepts from this
source*; the sidebar count stops calling claims concepts. Two days, no new page,
and the biggest single gain in the plan.

**3 — Layout.** `lib/brain/layout.ts`: ring anchors, source angles, gap
placement — pure and deterministic, snapshot-tested. The worker gains fixed
nodes (`fx`/`fy`), a radial band force and an angular pull for the cloud.
*Done when* the same payload gives byte-identical positions twice.

**4 — The still brain.** `lib/brain/paint.ts` (pure, unit-tested like
`paint.ts`): shapes, dendrite curves, labels, gaps, dispute rings, selection
lighting, the DOM nucleus. No tilt, no pulses. `graph-canvas.tsx` stops
initialising at zero size. E2E counts opaque pixels at the fixture and at
`big-map`, per the canvas rule in `AGENTS.md`.

**5 — One page.** `/knowledge`, Map | List, shared URL selection, the three
panels, redirects, sidebar, command palette, both top-bar overflow menus,
`navigation.spec`, `csp.spec`, `ledger.spec`, `graph-settings.spec`; 360px and
tap-target assertions on the new route in all seven projects. Delete
`graph-view.tsx` and the `/graph` web route; note it in `web/AGENTS.md`.

**6 — Life.** Tilt and orbit, flatten on engage, firing, the inward entrance.
Reduced-motion project asserts two screenshots a second apart are identical.
Paint budget measured; idle loop checked on a real phone.

**7 — The answer in the brain.** "Show in map" on an assistant message opens
`/knowledge?answer=<audit id>`: the cited sources light, their concepts light,
pulses run from the sources inward. Citations already carry `source_id`, and
source → concept is already in the `/map` payload, so this is web-only.

**8 — Watch it form.** On the build page the brain grows from the durable event
stream: `plan_ready` draws the ring, each `source_ingested` adds a square to the
orbit, `graph_ready` fills the cloud. No longer a stretch, and no longer planned
here: the same reducer also animates a single added source, so it is worked out
in [expert-brain-interactive.md](expert-brain-interactive.md) (phases G0–G4),
along with the map as the place an owner adds to and removes from the expert.

## What not to do

- Do not remove or demote the table. Find, sort, export, add and remove are its
  job, it is the form that works at 360px, and it is the accessible form.
- Do not float the key concepts in the simulation. They are the map's fixed
  points; a syllabus that lands somewhere new on each visit cannot be learned.
- Do not loop pulses, and do not animate anything while a panel is open.
- Do not design around disputes until `retrieval-quality.md` F4 is closed.
- Do not skip phase 0's hand-check. Sectors that are wrong a third of the time
  are worse than no sectors.

## Open questions

1. **Name:** *Knowledge* (proposed) or *Brain*.
2. **Figures.** `research_plan.figures` (six for Thomism, each with a work and a
   reason) are not in the map. They could be a fifth kind on the orbit — people
   rather than texts — but most of their works are already sources or gaps.
   Proposed: leave them out of v1, list them in the key-concept panel where
   relevant.
3. **Should the Overview carry a small, still brain** in place of the key
   concept list? Attractive, and a second consumer of `/map`. After phase 5.
