# Peritus Web — design

Companion to [web-production.md](web-production.md) (pages) and
[web-implementation.md](web-implementation.md) (how). This file is the look and feel.

**Reference:** the [Peritus Pinterest board](https://uk.pinterest.com/foxhopperjr/peritus/)
(9 pins, reviewed 2026-09-09) and Obsidian.

---

## 1. What the board says

Every pin is the same family: Obsidian, Linear, Notion-dark, Perplexity's Memory page,
Readwise, a Frappe activity log, a command palette, and one data dashboard ("mount"). What
they share:

- **Near-black canvas, panels one step lighter, hairline borders.** No shadows, no
  gradients. Depth comes from two or three flat surface levels and 1px lines.
- **Three-column shell.** Left sidebar with a collapsible tree, a wide centre, and an
  optional right panel (thread, calendar, details). Tabs along the top of the centre.
- **Text hierarchy by grey, not size.** Body ~13–14px, labels ~11–12px uppercase-ish
  muted, headings only slightly bigger. Most of the screen is mid-grey text on dark.
- **Colour is rare and means something.** Status dots, tags, avatars, chart series.
  Never decorative. In the "mount" pin the only saturated colour is the data.
- **Dense but calm.** Lists with counts on the right (Readwise "Books 519"), small
  avatars in-line with names, timelines with a thin vertical rule.
- **A command palette** as a first-class surface (⌘K / ⌘F).
- **Small graph views** are used as a texture: Perplexity's memory shows a tiny dotted
  node map; "mount" shows a topographic ring. The knowledge graph fits this language.

Obsidian specifically adds: the file-tree sidebar with chevrons, tabs that hold documents,
a right sidebar for backlinks/outline, purple as its single brand accent, and a
monospace-leaning editor feel. Peritus should feel like Obsidian for research: experts are
vaults, chats are notes, the ledger is a table view, the graph is Graph View.

## 1b. Second reference: the writing-studio layout

A second reference (a dark AI writing studio: notes panel left, manuscript centre, chat
right) adds a pattern the board only hints at, and it fits Peritus better than a plain
dashboard:

- **Left: structured knowledge, not navigation.** Collapsible sections with a count badge
  and a `+` on each header (*Overview*, *Entities 3*, *Relationships*, *Moments 14*).
  Each entity row expands in place to show its description. For Peritus this becomes
  the expert's knowledge panel: *Overview* (persona bio), *Concepts n*, *Sources n*,
  *Contradictions n* (or "not analysed yet"), *Chats n*. A concept row expands to its
  coverage strength and the sources that cover it.
- **Centre: one reading surface.** A document with a title, a chapter heading, and
  generous line length, with a floating outline popover for jumping between sections. The
  bottom-left pill ("150,794 words") is a persistent stat. For Peritus the centre is
  whatever is being read: the conversation, a source's text, the ledger, the graph. The
  pill shows "34 sources · 412 passages".
- **Right: the conversation, alongside.** Chat / Reviews / Audio tabs, then a stack of
  response cards each with a small action row (thumbs up/down, copy, regenerate) and the
  user's prompt between them as plain text. The composer sits at the bottom with an
  attachments count. For Peritus this means chat is a panel that can sit next to a
  source or the graph, not only a full page: ask about a passage while reading it.
- **Inline highlights with accept / reject.** Suggested edits are green-highlighted in
  the text with a small ✓ ✗ toolbar above the selection. Peritus uses the same treatment
  for evidence: hovering a citation chip in an answer highlights the cited span in the
  source panel in `--expert-soft`, and a source's key claims are shown as highlighted
  spans a reader can jump between.
- **Top bar breadcrumb** ("My Story / Meridian", star, Share). Peritus:
  "Experts / Dr. Elena Vasquez", with the expert avatar in place of the star.

The treatment is the same as the board (near-black, hairlines, grey hierarchy, 13px
text), so no new tokens are needed. The left "knowledge" sections live on the Overview
page and the expert sidebar rather than as a third column; see §5.

## 1c. Third reference: the document page

A third reference (a Notion-style dark project page: rounded window, soft rounded sidebar
rows, a document with an icon, a big title, a description line, inline properties, and
long-form sections) sets the balance between rounded and serious. Its seriousness comes
from document structure and typography, not from sharp corners, so the chrome can be
rounded while the content reads like a well-set page. Three rules follow from it:

- **Rounded fills instead of rules.** The active sidebar row is a soft rounded fill with
  no left bar. Grouping is done by rounded surfaces, so there are fewer borders overall.
- **Colour as text, not chips.** Labels are coloured words with no background ("High" in
  red, "Planned" in blue, "Marketing" in green). Colour reads as annotation, not tagging.
- **The centre is a document.** Icon, 24px title, one-line description, a properties
  block of inline label:value rows, then prose sections with nested lists and bold
  lead-ins. This is the model for the Overview page (§6).

## 2. Tokens

Dark is the primary theme and is what the board shows. Light exists (system default) but
is derived from the same tokens; design dark first.

```
Surface
  --bg          #0e0e10   canvas
  --panel       #141416   sidebar, cards, right panel
  --raised      #1b1b1e   hover rows, inputs, popovers
  --border      #26262a   hairlines (1px, never thicker)
  --border-soft #1f1f22   dividers inside panels

Text
  --fg          #ececee   headings, primary
  --fg-2        #a1a1a8   body
  --fg-3        #6b6b73   labels, timestamps, placeholders
  --fg-4        #45454c   disabled, decorative rules

Brand accent (one)
  --accent      #8b7cf6   soft violet, Obsidian-adjacent. Focus rings, primary button,
                          active nav item, links. Used sparingly.

Status (the only other fixed colours)
  --ok          #5cc47a   ready / accepted
  --warn        #e0b24a   building / degraded / thin coverage
  --bad         #e05c5c   failed / rejected
  --info        #5aa9e6   queued / chat-ready-but-graph-pending

Expert accent
  --expert      set per expert from its persona (see §4). Overrides --accent inside
                that expert's pages.
```

Light theme: invert the surface ramp (`#fafafa / #ffffff / #f2f2f4 / #e4e4e8`), keep
status and accent hues, darken text. Do not design anything that only works on dark.

## 3. Type, spacing, shape

- **Typeface:** Inter (variable) for everything except numbers, identifiers, the build
  log and citations, which use Geist Mono. One sans, one mono. No display face.
- **Sizes, chrome:** 13px in sidebars, tables, and controls; 12px secondary; 11px
  labels (letter-spacing 0.04em, `--fg-3`).
- **Sizes, reading surface:** 24px medium page title; one-line description in `--fg-2`
  under it; 16px medium section headings with generous space above; 14px body at 1.6
  line-height on a 680px measure; nested lists with bold lead-ins.
- **Optional serif.** Answer bodies and source text may use Source Serif 4 at 15px, with
  Inter everywhere else, to mark the reading surface as reading. Off at first; add it if
  the sans reads as a dashboard.
- **Numbers** are tabular (`font-variant-numeric: tabular-nums`) everywhere.
- **Spacing:** 4px grid. Row height 32px in lists, 28px in dense tables. Panel padding
  12–16px.
- **Radius scale:** 6px chips, inputs, small buttons · 8px sidebar rows, list rows,
  active-state fills · 10px rail avatars, cards, the sidebar header wash · 12px panels,
  popovers, the command palette, and the app window in marketing screenshots · full for
  status dots and the account avatar.
- **Rounded fills over rules.** Active and hover states are a `--raised` rounded fill,
  never a border or a side bar. The accent appears only on the rail's active bar, links,
  focus rings, and the primary button. Fewer borders overall; rounded surfaces do the
  grouping.
- **Colour as text.** Concepts, source types, tiers, and status words are coloured text
  with no background (`--expert`, `--ok`, `--warn`, `--bad`, `--info`). Filled chips are
  reserved for citation markers `[n]` and the ledger's decision column.
- **Shadows** only on popovers and the command palette.
- **Motion:** three durations and two easings, defined in §9 with the full catalogue of
  what moves; `prefers-reduced-motion` is honoured everywhere.

## 4. Expert identity

Every expert gets a persistent visual identity derived from its persona so that a list of
experts reads like a list of people, and every page inside an expert is unmistakably that
expert's.

**Source of truth: the persona name.** `persona_name` is stable after the persona stage,
so the monogram and its seed are derived deterministically on the client. The API *does*
now store an avatar recipe (`experts.avatar`, migration 026) when the owner picks one.

**Accent colour — superseded.** This section originally hashed the persona name to one of
the twelve hues below. It was built that way and then changed, for two reasons found by
looking at it: with a handful of experts the hashes cluster (five personas landing in the
blues made the entire product read as blue), and a colour nobody chose carries no meaning
anyway. **Every expert is monochrome until its owner picks a hue in the avatar picker**,
and the chrome — the primary button included — is ink on paper. The twelve hues survive
as the palette the picker offers:

```
violet 262   indigo 240   blue 214   cyan 190   teal 172   green 145
lime 95      amber 40     orange 24  rose 350   pink 325   plum 290
```

Each hue has two tints: `--expert` (saturated, for the avatar, active tab, chart
series, graph nodes) and `--expert-soft` (12% alpha, for the persona header wash, chip
backgrounds, hovered rows). Contrast against `--bg` and `--panel` must pass 4.5:1 for
text uses; the palette is tuned once and stored as OKLCH values, not recomputed.

**Avatar.** A found, licensed picture of the *subject* by default; a generated sigil
otherwise. Never an uploaded photo, never a generated face, never a living person.
Three levels, in precedence order:

1. **The owner's recipe**, if they chose one. `experts.avatar` (migration 026) stores
   `{style, seed, hue}`: the monogram sigil, or one of the abstract DiceBear
   collections, tinted with the expert hue. Authoritative over everything below it —
   the build writes to `expert_pictures`, never here.
2. **The found picture** (migration 027). What a freshly built expert arrives with: the
   lead image of the Wikipedia article on its topic, fetched during the build,
   licence-checked, stored in Postgres and served same-origin under a content-hashed
   URL. Free licences only (public domain, CC0, CC BY, CC BY-SA); no flags, maps, logos
   or seals; **no living people**. Rendered in the same rounded square with
   `object-fit: cover` — never a circular crop, which would read as a headshot of the
   persona.
3. **The monogram sigil.** A rounded square in `--expert-soft` with a 1px `--expert`
   ring, the persona's initials (honorific stripped, using the existing
   `personaInitials` rule) in `--expert`, and a small deterministic geometric mark
   behind the letters (2–3 overlapping shapes seeded from the name hash, at 20% alpha).
   Self-contained SVG, no dependency, renders at 16px to 96px.

The picture is a picture of the *subject*, not a headshot of the persona — a bust of
Zeno illustrates Stoicism the way a book cover does. That is what keeps the original
rule true: the persona is a voice, not a claim that a real person wrote the answers.
Do not use face-style avatars, and do not introduce an upload: a user-supplied image
beside cited answers is an unmoderated surface, which a found file with a recorded
licence and a named artist is not.

**Where the identity shows.**

| Surface | Treatment |
|---|---|
| Rail | 40px rounded-square avatar; active gets a 3px `--expert` edge bar |
| Expert sidebar header | 32px avatar, persona name, topic, `--expert-soft` wash |
| Experts home cards | 32px avatar, persona name, topic under it, `--expert` 2px left rule on the card |
| Overview page header | 48px avatar, persona name in `--fg`, bio in `--fg-2`, and — while the found picture is what is shown — a `--fg-3` credit line naming the work, the artist and the licence, linking to the file page |
| Breadcrumb | 20px avatar before the persona name |
| Chat | Assistant messages carry the 20px avatar; citation chips use `--expert-soft` with `--expert` text; the composer focus ring is `--expert` |
| Build page | Stage timeline progress in `--expert`; keep/drop rows still use `--ok` / `--bad` |
| Sources ledger | Unchanged, status colours only; the header carries the identity |
| Graph | Nodes in `--expert` at varying alpha by degree, edges in `--border`, selected node in `--fg` |
| Command palette | 16px avatar before each expert row |
| Expert settings | 48px avatar, the picker, and the same credit line as the Overview header |
| Persona voice | `persona_style` (a short phrase from the API) shown under the bio as an italic `--fg-3` line, e.g. "measured, cites primary sources" |

**Naming.** Keep the existing rule: persona names are titled ("Dr.") unless they already
carry an honorific. The topic is always visible next to the persona name so an expert is
never identified by the invented name alone.

## 5. Shell

Two sidebars, then the reading surface, then an optional right panel. Experts are the
top-level unit, the way servers are in Discord, so the outermost navigation is a rail of
expert avatars and everything else belongs to the selected expert.

```
| rail | expert sidebar |         centre          | right panel |
| 56px |     260px      |          flex           |   360px     |
```

- **Rail, 56px, always visible.**
  - Top: Home button (wordmark mark).
  - Then one 40px rounded-square avatar per expert (10px radius, the sigil from §4).
    Active expert: a 3px `--expert` bar on the rail's left edge and full-opacity avatar;
    inactive avatars at 70% opacity. Building: a pulsing `--warn` ring. Failed: a small
    `--bad` dot at the corner. Hover shows the persona name and topic in a tooltip,
    since the rail has no text. Scrolls when it overflows.
  - A `+` square to build a new expert.
  - Bottom: settings gear and the account avatar.
- **Expert sidebar, 260px, collapsible.** Contents depend on what the rail has selected.
  - *An expert selected:* header with the 32px avatar, persona name, topic, status dot,
    and the `--expert-soft` wash. Then plain rows: Overview, Sources, Graph, Settings
    (active row a `--raised` rounded fill, no rule). Then a **Chats** section
    header with a count and a `+` (new chat), a filter field, and the chat list (title,
    relative time, most recent first). Overview absorbs the concept and source counts
    that the earlier knowledge panel held.
  - *Home selected:* All experts (list with avatars and status), Recent chats across
    experts, Credits (balance, held), and the topic composer for a new build.
- **Centre.** The reading surface: the conversation, a source's text, the ledger, or the
  graph. Max width 720px for conversations and source text, full width for the ledger
  and the graph. Persistent stat pill bottom-left ("34 sources · 412 passages"). Top bar
  is a 40px breadcrumb: avatar, persona name, then the page or chat title.
- **Right panel, 360px, optional.** On a chat it holds the cited passage. On Sources and
  Graph it holds the chat, so a user can ask about what they are looking at; the composer
  carries an "about: {source or node}" chip when opened from a row or node. On the build
  page it holds cost by stage.
- **Command palette.** ⌘K. Centered, 560px, `--raised` surface, the only shadowed
  element. Sections: Experts, Chats, Actions. Rows 36px with avatar, name, `--fg-3` hint.

Narrower screens collapse the shell in tiers; §8 defines them and what each page does
at each width.

**Limits.** The rail is fine to about fifteen experts and then relies on scrolling and
the Home list; that matches a product where builds cost credits. Recognition in the rail
depends on the avatars being distinct, which is why §4 recommends the monogram sigil
(initials plus colour) over purely abstract shapes.

## 6. Components

- **Status dot:** 8px circle. queued `--info` pulse, building `--warn` pulse, chat-ready
  `--ok` outline, ready `--ok` filled, failed `--bad`.
- **Chips:** 20px tall, 6px radius, `--raised` background, `--fg-2` text. Used only for
  citation markers and ledger decisions; everything else is coloured text.
- **Tables:** 28px rows, `--border-soft` row dividers, sticky header in `--fg-3` labels,
  right-aligned tabular numbers, hover row `--raised`. Score cells show the number and a
  4px-wide inline bar in `--ok` / `--bad`.
- **Build log:** monospace, 12px, each row `[time] [stage] message`, keep rows prefixed
  with a `--ok` ✓ and drop rows with a `--bad` ×, scores at the right edge.
- **Chat message:** no bubbles. Assistant answers are cards on `--panel` with a
  1px `--border`, the 20px avatar and name on the first line, body text, and a
  bottom action row in `--fg-3` icons (copy, regenerate, trail). User prompts are plain
  `--fg-2` text between cards, no card. Citations as superscript `[n]` chips.
- **Highlight:** cited or selected spans get a `--expert-soft` background with no
  border; a small floating toolbar (✓ ✗ or open / copy) appears 4px above the span.
- **Overview page (document):** the sigil at 48px where the reference has its emoji,
  the persona name as the 24px title, the topic as the description line. Then a
  **Properties** block of inline rows, label in `--fg-3` and value as coloured text:
  Tier, Status, Readiness, Sources (accepted / considered), Quality (mean), Built. Then
  prose sections: *About* (persona bio and style), *Key concepts* (coloured words in
  `--expert`, each linking to the ledger filtered by that concept), *How this corpus was
  assembled* (method statement, acceptance rate, rubric version, stop reason as one
  paragraph), *Source types* (a one-line list with counts). Error and retry, when the
  build failed, sit above the properties as a rounded `--bad` tinted notice.
- **Stat tile:** used only on Home. Label in `--fg-3` uppercase, value 20px tabular.
  Rounded `--panel` fill, no border.
- **Empty state:** icon at `--fg-4`, one sentence, one button.
- **Graph:** canvas on `--bg`, faint dotted grid like Perplexity's memory map, nodes as
  filled circles, labels on hover and for the top-degree nodes, a search field floating
  top-left, node detail in the right panel.

## 7. Marketing pages

Same tokens, more air. Landing uses the app's dark canvas, 640px reading column, 32px
headline, and a real build log replay as the hero rather than an illustration. The
"what gets recorded" table renders as the same table component the ledger uses. No
gradients, no glow, no stock imagery.

## 8. Responsive layout

The shell in §5 is the wide layout. It collapses in tiers by available width, never by
device sniffing. Design the centre column for 360px first, then let the tiers add chrome
around it. The tiers are Tailwind's default `md` / `lg` / `xl` breakpoints, so nothing
custom is needed.

### Tiers

| Tier | Width | Rail | Expert sidebar | Right panel | Top bar |
|---|---|---|---|---|---|
| Desktop | ≥ 1280 (`xl`) | inline, 56px | inline, 260px | inline, 360px | 40px breadcrumb |
| Laptop, iPad landscape | 1024–1279 (`lg`) | inline | inline | overlay from the right, 360px, with a backdrop | 40px breadcrumb |
| iPad portrait | 768–1023 (`md`) | inline | left drawer over the centre | bottom sheet | 40px breadcrumb, menu button |
| Phone | < 768 | folded into the nav drawer | nav drawer | bottom sheet | 44px: menu · sigil · title · one action |

Phone shell, in detail:

- **Top bar, 44px.** Menu button, the 20px sigil, the persona name and page title truncated
  with an ellipsis, then one action for the page (*Chat* on Overview, *Cancel* on Build,
  *Export* on Sources, *Search* on Graph). Anything else goes in a ⋯ overflow menu.
- **Nav drawer.** 85vw, max 320px. The rail becomes a horizontal strip of avatars across
  the top (Home first, `+` last); under it the expert sidebar's content unchanged (pages,
  then Chats); settings and account at the bottom. Opens from the menu button or an edge
  swipe from the left 20px. Closes on backdrop tap, swipe, Escape, the Android back
  gesture, or any navigation.
- **Bottom sheet.** The right panel's phone form. Two snap points, 50% and 92% of the
  viewport, a drag handle, and the sheet's own content scrolls only at 92%. At 50% the
  page behind stays visible so a cited passage can be read next to the answer. On the
  graph the first snap is 40% so the canvas stays usable.
- **Pinned bottom elements** (the composer, a sticky *Build* button) sit above
  `env(safe-area-inset-bottom)`. The app is `100dvh`, never `100vh`.
- **No bottom tab bar.** The nav drawer is the one navigation surface, as in Obsidian
  mobile. The reading surface stays as tall as possible.

### Rules at every tier

- Nothing scrolls horizontally except a table inside its own scroll container, the build
  page's stage strip, and the graph canvas.
- Under `(pointer: coarse)`: list rows 44px, table rows 40px, icon buttons 40px, chips
  28px tall, and every input at 16px type so iOS does not zoom on focus.
- Every hover-only affordance has a tap form: rail tooltips become the names in the
  drawer, card hover menus become a visible ⋯, citation hover previews become a tap that
  opens the sheet, row hover actions become the row's detail sheet.
- Body text in the centre goes from 14px to 15px below 768px. Chrome stays 13px. The
  reading measure is the column minus 16px gutters.
- Components that live in more than one container (the chat panel, ledger rows, stat
  tiles) size themselves with container queries, not viewport queries, so the chat panel
  is right at 360px inside the right panel and at full width on a phone with one
  stylesheet.
- Dialogs are bottom sheets below 768px. Confirm buttons sit above the safe area.
- Sticky: the top bar, table headers inside their scroll container, the composer.
  Nothing else.

### Page by page

| Page | ≥ 1024 | 768–1023 | < 768 |
|---|---|---|---|
| Landing | 640px column, the replay beside the headline | single column, the replay under the headline at 280px tall | same; the six steps stack; the ledger table scrolls in its container |
| Login | 360px card | same | card fills the width inside 24px gutters; OTP cells 40px; `autocomplete="one-time-code"` |
| Home | four tiles, cards in three columns | four tiles, cards in two columns | tiles 2×2, cards in one column, *Building now* first, composer full width |
| New expert | 560px column, tiers in one row | tiers 2×2 | tiers stacked; the cost line and *Build* pinned to the bottom |
| Overview | document page, properties as label · value rows | same | properties stack label over value below 480px |
| Build | timeline row, log full width, cost in the right panel | timeline row, cost in the sheet | timeline is a scroll-snap strip with the active stage centred; log rows wrap the message under time · stage; scores stay right-aligned |
| Chat | 720px transcript, passage in the right panel | full-width transcript, passage in the sheet | same; composer above the keyboard; cards at 12px padding |
| Chats | grouped list | same | 44px rows with a ⋯ menu |
| Ledger | full table, detail in the right panel | table scrolls horizontally with the title column sticky | card list: title, decision chip, two inline bars, drop reason; sort is a select; detail is a sheet |
| Graph | canvas, search top-left, slider top-right, node in the right panel | same, node in the sheet | canvas full-bleed under the top bar; search is a top-bar icon; the slider lives in the sheet header; pinch to zoom, one finger to pan, tap to select |
| Settings, expert settings, admin | 560px column | same | one column; destructive dialogs as sheets |

### What must be true at 360px

Nothing overflows the viewport. Every control is reachable with a thumb. The keyboard
never covers the composer or a form's submit button. The whole product is usable with one
hand except the graph.

## 9. Motion

Motion confirms a state change: something appeared, moved, or is in progress. It never
decorates. The reference shells in §1 move very little, and a product whose main surfaces
are a log and a transcript should feel steady while content streams in.

### Tokens

```
--dur-1   120ms   hover, press, colour, focus rings
--dur-2   200ms   small things entering: menus, tooltips, rows, notices, chips
--dur-3   320ms   surfaces: drawers, sheets, the palette, timeline fills
--ease-out   cubic-bezier(0.2, 0, 0, 1)   entrances and movement
--ease-in    cubic-bezier(0.4, 0, 1, 1)   exits
spring       bounce 0, visual duration 0.3s   drag-driven surfaces only
```

Exits are shorter than entrances (a menu enters in 200ms and leaves in 120ms) and never
move, only fade. Nothing takes longer than 400ms except progress indicators. Nothing loops
except four pulses (the queued dot, the building dot, the building ring on the rail, the
streaming caret) and the skeleton fade.

### Rules

1. Only `transform` and `opacity` animate on anything larger than a button. Colour
   transitions at `--dur-1` are fine on buttons, rows and chips. Never animate height,
   width, position, shadow or filter. Collapsibles animate `grid-template-rows` from
   `0fr` to `1fr`, the one accepted layout animation, and only for things under about
   300px tall.
2. State changes use CSS transitions, not keyframes, so they reverse cleanly when
   interrupted. Keyframes are for loops and one-shot entrances only.
3. `prefers-reduced-motion: reduce` sets `--dur-2` and `--dur-3` to zero and keeps
   `--dur-1` for opacity: things still fade, nothing slides, scales, pulses or
   auto-scrolls smoothly. Pulses become static dots. The landing replay shows its final
   frame.
4. Skeletons, not spinners, for anything that is a page or a panel. Spinners live only
   inside buttons, at 16px, replacing the label in a fixed-width button so nothing
   shifts.
5. Entrance staggers are for first paint only: at most eight items, 40ms apart.
   Refreshes and re-sorts are instant.
6. Theme switches do not transition. Everything repaints at once.
7. Programmatic scrolls are smooth only when the distance is under one screen; longer
   jumps are instant.

### Catalogue

Every animation in the product. If it is not listed here, it does not animate.

**Shell**

| Where | What moves | Timing |
|---|---|---|
| Rail active bar | slides to the selected avatar (translateY) | dur-3, ease-out |
| Rail avatar | opacity 70% → 100% on hover and when active | dur-1 |
| Building expert | the `--warn` ring on the rail avatar and the status dot pulse opacity 0.4 → 1 | 2s loop; static under reduced motion |
| Sidebar rows | background on hover and active | dur-1; the fill does not slide between rows |
| Nav drawer, sidebar drawer | translateX from −100% with a backdrop fade; a drag follows the finger and settles on the spring; a flick past 30% or faster than 500px/s closes | dur-3, ease-out |
| Right panel, inline (≥ 1280) | no layout animation; the panel appears at once and its content fades in | dur-2 |
| Right panel, overlay (1024–1279) | translateX from 100% with a backdrop | dur-3 |
| Bottom sheet (< 1024) | translateY from 100%; snaps between 50% and 92%; drag handle; a flick down closes | spring |
| Command palette | opacity and scale 0.98 → 1; exit is a fade | dur-2 in, dur-1 out |
| Tooltips | opacity and a 2px translate toward the target; 300ms hover delay, none between siblings | dur-1 |
| Menus, popovers, selects | opacity and scale 0.98 → 1 from the anchor corner | dur-2 in, dur-1 out |
| Dialogs | backdrop fade; panel opacity and scale 0.98 → 1; sheets on phones | dur-2, dur-3 on phones |
| Toasts | sonner defaults; bottom-right on desktop, top-centre on phones so they never cover the composer | |
| Route change | the centre column crossfades; the rail and sidebar do not move; the sigil is a shared element from the Home card to the Overview header | 150ms |
| Skeleton | opacity 1 → 0.5 | 1.6s loop |
| Buttons | scale 0.98 while pressed; label ↔ spinner crossfade in a fixed-width button | dur-1 |
| Focus ring | fades in, `--accent` or `--expert` | dur-1 |

**Pages**

| Where | What moves | Timing |
|---|---|---|
| Home, expert cards | first-paint fade with a 4px rise, staggered 40ms, at most eight | dur-2 |
| Home, *Building now* | stage text crossfades on change; elapsed seconds tick with no motion | dur-2 |
| New expert, tier cards | ring colour on select, no scale | dur-1 |
| New expert, 402 notice | fade with a 4px rise; the form keeps its height | dur-2 |
| Build, stage timeline | each segment fills left to right (scaleX) as its stage completes; the active segment carries a 20%-wide sweep | dur-3; the sweep is a 1.2s loop, a static half-fill under reduced motion |
| Build, log rows | fade in only while the user is at the bottom; when scrolled up, rows append with no motion and the *jump to latest* pill rises in | dur-2 |
| Build, auto-scroll | smooth for under one screen, instant otherwise | |
| Build, `chat_ready` | *Chat now* fades and rises, then one 600ms `--ok` ring pulse; the rail ring stops | dur-2 |
| Build, terminal row | the done, failed, cancelled or cap-exceeded row fades in; the timeline's last segment fills or turns `--bad` | dur-3 |
| Chat, user prompt | appears at once, no motion; it is the user's own action | |
| Chat, assistant card | fades in empty and grows as text arrives with no per-token motion; tokens are painted once per frame | dur-2 |
| Chat, streaming caret | a 1px block at the end of the text blinks | 1s loop; static under reduced motion |
| Chat, status line | text crossfades between planning, searching and composing with a 4px rise | dur-2 |
| Chat, citation chip | background on hover; the passage preview popover; the cited span in the passage panel fades to `--expert-soft` | dur-1, dur-2, dur-2 |
| Chat, passage panel | content crossfades when a different citation is chosen | dur-2 |
| Chat, Stop ↔ Send | crossfade in place | dur-1 |
| Chat, composer growth | no animation; the textarea sizes to its content at once, up to six lines | |
| Chats, delete | the row collapses (grid rows) then unmounts | dur-2 |
| Ledger, filter change | rows crossfade; the container keeps its height until the new rows mount so the page does not jump | dur-2 |
| Ledger, sort and page | instant | |
| Ledger, score bars | fill (scaleX) on first paint only | dur-3 |
| Ledger, row select | the detail panel's content crossfades | dur-2 |
| Ledger, upload | a determinate bar in `--expert`; then the new row fades in with a `--expert-soft` wash that decays over 1.2s, once | dur-2 |
| Graph, first paint | the simulation settles over about 2s while nodes fade in over the first 300ms; under reduced motion the layout is computed before paint and shown settled | |
| Graph, pan and pinch | follow the gesture with no easing | |
| Graph, search focus and node click | pan and zoom to the node | 250ms, ease-out |
| Graph, hover label | fade | dur-1 |
| Graph, selected node | the ring grows from the node | dur-1 |
| Graph, limit change | existing nodes keep their positions, the simulation reheats to alpha 0.3, new nodes enter at their neighbours' centroid | |
| Landing, hero replay | rows fade and rise at the recorded intervals compressed about 8×; runs 20s then holds; paused off-screen | dur-2 |
| Landing, sections | no scroll-triggered motion | |
| Login, OTP cells | a filled cell's background; the sixth digit swaps the button label for a spinner | dur-1 |
| Login, error notice | fade with a 4px rise | dur-2 |

### Smooth is mostly not animating

What makes the product feel fast is rendering discipline, not effects:

- The build log and the ledger are virtualised past about 300 rows.
- Streaming answers render Markdown for completed paragraphs only and paint the paragraph
  in progress as text. Each completed block is memoised, so a token never re-parses the
  whole answer.
- Off-screen transcript cards and ledger rows use `content-visibility: auto` with an
  intrinsic size.
- Skeletons match the final layout's heights exactly. The top bar, stat tiles and composer
  have fixed heights. Fonts load through `next/font` with adjusted fallback metrics so
  text never reflows.
- Backdrops are flat 50% black. No blur.
- Routes prefetch on hover and in view. Renames and deletes are optimistic. Filter changes
  are transitions, so typing never stalls.
- Budget on a mid-range phone: LCP under 2.5s, INP under 200ms, CLS under 0.1, measured
  on `/`, `/login`, `/experts` and a seeded chat.

The mechanics (hooks, components, config, tests) are in
[web-implementation.md](web-implementation.md) §12.

## 10. Packages this adds

| Package | Version | For |
|---|---|---|
| `geist` | 1.7.2 | Geist Mono, loaded through `next/font` |
| `motion` | 13.2.0 | drawers, sheets, drag to dismiss and the few layout animations; loaded lazily, used in at most six components |
| `tw-animate-css` | 1.4.0 | the enter and exit utilities shadcn's Base UI components expect |
| `@tanstack/react-virtual` | 3.14.12 | the virtualised build log and ledger |
| `d3-zoom`, `@types/d3-zoom` | 3.0.0, 3.0.8 | graph pan, pinch and programmatic focus |
| `input-otp` | 1.5.0 | the six-cell code input (shadcn's `input-otp` wraps it) |
| `@dicebear/core`, `@dicebear/collection` | 10.7.0, 9.4.2 | only if option 2 in §4 is chosen |

Inter comes from `next/font/google`, which self-hosts it at build time with adjusted
fallback metrics, so no font package is needed for it. Everything else is in the
implementation plan. Versions were checked against npm on 2026-09-11.
