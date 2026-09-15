# Expert picture — implementation plan

When an expert is created, give it a real picture of its subject: found, licensed,
stored, and shown everywhere the avatar shows today. Not generated. A Stoicism
expert gets the bust of Zeno that heads the Wikipedia article; a Thomism expert
gets the Gentile da Fabriano panel of Aquinas; a quantum electrodynamics expert
gets a Feynman diagram. The owner can still swap it for a sigil, pick a
different candidate, or remove it, exactly as they can pin a recipe today.

This plan builds on the avatar work already in the tree (migration 026,
`api/src/peritus/experts/avatar.py`, `web/components/identity/*`) and does not
replace it. The recipe stays the owner's override; the picture becomes the
default that a fresh expert arrives with.

## What exists today, precisely

- **The avatar is a recipe, not an image.** `experts.avatar` (migration 026) is
  `{style, seed, hue}` or NULL. NULL means "derive a monochrome monogram from
  the persona name". Six styles are allowed server-side (`AVATAR_STYLES`), none
  of them faces. There is no image column, no object store, no CDN.
- **The design forbids photos.** web-design.md §4: "A generated sigil, not a photo
  and not a cartoon face." web/AGENTS.md: "Nothing is uploaded: there is no
  storage, no CDN and no moderation problem." Both rules exist for two reasons:
  a generated face beside "Dr. Elena Vasquez" reads as a claim that a real
  person exists, and a user-uploaded image beside cited answers is an
  unmoderated surface. This plan keeps both reasons intact (see decisions).
- **One renderer.** `web/components/identity/avatar.tsx` draws every size from
  16px (command palette) to 64px (picker preview); the rail is 40px. It inlines
  an SVG into a `<span aria-hidden>` and never uses `<img>` or `next/image`.
  `web/lib/avatar.ts#resolveRecipe` decides what to draw. The picker
  (`avatar-picker.tsx`) writes `PUT /experts/{slug}/avatar`.
- **The build has a natural hook.** Stage 0 (PLAN) emits `plan_ready` with
  `key_concepts` a few seconds after `created`; stages after chat-ready follow a
  degrade-don't-raise contract and emit `stage_degraded`. Unknown build events
  are ignored by the web reducer (`default:` branch) and by the Rust TUI
  (`#[serde(other)] Unknown`), so new event types are safe to add.
- **Bytes already live in Postgres.** The uploads feature chose `BYTEA` over a
  blob store on purpose (user-supplied-sources.md); the same reasoning applies
  to a 50–150 KB thumbnail per expert.
- **The web proxies everything same-origin.** `web/lib/api/route.ts#forward`
  passes an `arrayBuffer()` body through with a fixed header allowlist
  (`content-type`, `cache-control`, `content-length`, …). Serving an image
  through it needs no `images.remotePatterns` and no third-party origin in the
  browser.
- **Wikipedia is already a fetcher.** `sources/fetchers/wikipedia.py` talks to
  the Action API over `httpx` with a `Peritus/2.0` user agent, and validated
  Wikipedia sources in a corpus carry their article URL.

## Decisions taken by the request

| | |
|---|---|
| **Found, not generated** | No image model. Every picture is an existing file with a known licence and a provenance record. |
| **Automatic at creation** | A new expert gets its picture during the build without the owner doing anything. It should appear in the rail while the build is still running. |
| **It is the profile picture** | It renders in the avatar tile on every surface in web-design.md §4's table, not as a banner or a separate "cover". |

## Decisions I am taking, and why

**The picture is of the subject, not of the persona.** A found image of Zeno is
an illustration of Stoicism, the way a book cover is; it is not a headshot of
"Dr. Elena Vasquez". That distinction is what keeps the design's original
reasoning true: the persona is a voice, and nothing here claims a real person
wrote the answers. Two consequences follow. The tile stays a rounded square
(`shape="circle"` is never used today and must not be introduced for this), because
a circular crop reads as an account avatar. And **no living person is ever the
picture**: a portrait of someone alive beside an invented name is a worse
misrepresentation than a generated face, and carries publicity-rights exposure a
bust of Marcus Aurelius does not. Historical figures are fine and often the best
picture available.

**Wikipedia page images first; free licences only.** The lead image of a
Wikipedia article is chosen by editors to represent the subject, is almost
always free (the API can refuse non-free files outright with `pilicense=free`),
and comes with machine-readable licence and attribution metadata. That is the
whole "good and relevant" problem mostly solved by someone else, and it needs
no API key. Accepted licences: public domain, CC0, CC BY, CC BY-SA. Rejected:
anything NC or ND, any file with a non-empty `Restrictions` field (trademark,
personality rights, insignia), and any file the API will not label. Wikimedia
Commons search and Openverse widen the pool later (phase 3) under the same
licence rule.

**Store the bytes in Postgres and serve them same-origin.** Hotlinking
`upload.wikimedia.org` would put a third-party request in every user's browser
(the app currently has none), break when a file is renamed or deleted on
Commons, and lean on a service that asks not to be hotlinked at volume. A
512px thumbnail as Wikimedia serves it is 30–150 KB; one row per expert in a
new table, cached immutably in the browser under a versioned URL. There is
no Pillow and no resizing: the thumbnail service already produced the size we
want, the client crops to a square with `object-fit: cover`, and the only
server-side check is magic bytes plus a size cap.

**A separate table, not a new avatar style written by the build.** `avatar`
non-null means "the owner chose this" and the build must never overwrite an
owner's choice. So the found picture lives in `expert_pictures`, and the
resolver's precedence becomes: owner's recipe → found picture → derived sigil.
One new recipe style, `picture`, exists only so an owner can pin a hue while
keeping the picture; `{"avatar": null}` (the picker's Reset) now means "back to
the picture if there is one".

**Run early, never fail the build, survive rebuilds.** The finder starts as a
background task the moment `plan_ready` fires, so the topic and key concepts
are both available and the rail updates within seconds. It has its own
timeout, emits `picture_ready` or `picture_skipped`, and can never raise into
the build. A rebuild does not re-find (the topic has not changed and the owner
may have chosen a candidate); only an explicit refresh does. Expert deletion
cascades.

**Attribution is shown, not just stored.** CC BY and CC BY-SA require it.
Wherever the picture is the identity of a page (the overview header, expert
settings) a credit line names the work, the artist and the licence and links
to the file page. The rail and the chat tile do not carry a credit; the
overview page, one click away, does.

**Colour stays chosen.** It would be easy to pull a dominant hue from the
picture and tint the expert with it. The colour rule (web/AGENTS.md, "Colour is
information") says a hue nobody chose carries no meaning, and that reasoning
does not change because the hue came from a JPEG. Experts stay monochrome
until the owner picks.

**Heuristic pick first, model pick second.** Phase 1 chooses by rank order and
cheap filters, which is already right most of the time because the top
Wikipedia article for a topic usually has the right lead image. Phase 2 adds
one `FAST_MODEL` call that looks at up to six candidate thumbnails and picks
the one that represents the subject, reads at 40px, is not a map, flag, logo,
diagram or wall of text, is not a living person, and suits a general audience.
That call is also the content gate before public catalog exposure.

## How a picture is found

All requests go through one `WikimediaClient` (`infrastructure/wikimedia.py`)
with a descriptive user agent that carries a contact address (Wikimedia's API
policy asks for one; the current fetcher's `Peritus/2.0 (research corpus builder)`
lacks it and should share the new constant). Five or six HTTP requests per
build, no key, one overall deadline (`PICTURE_TIMEOUT`, default 20 s).

1. **Queries.** `[topic] + key_concepts[:4]`, plus, when re-finding for an
   existing expert, the titles of its validated Wikipedia sources ordered by
   quality (those are already judged relevant to the corpus).
2. **Articles.** `list=search`, three hits per query, deduplicated, capped at
   eight titles. The topic's own hits rank first.
3. **Page images and identity, one batched call.**
   `prop=pageimages|pageprops&piprop=thumbnail|name|original&pithumbsize=512&pilicense=free&ppprop=wikibase_item|disambiguation`.
   Drop disambiguation pages, pages with no free image, and originals whose
   shorter side is under 240px.
4. **Marks, not pictures.** Drop file names matching
   `\b(flag|map|logo|icon|seal|coat[_ ]of[_ ]arms|emblem|signature|locator|banner)\b`
   and `.svg`. These are what an article's lead image is when the subject is a
   country, company or organisation, and they are unreadable at 40px.
5. **Living people.** For the remaining articles, `wbgetentities` on Wikidata
   with `props=claims`: if P31 (instance of) contains Q5 (human) and there is no
   P570 (date of death), drop it.
6. **Licence and credit.** `prop=imageinfo&iiprop=extmetadata|mime|size|url&iiurlwidth=512`
   on the `File:` title. Keep only files whose `LicenseShortName` is in the
   allowlist and whose `Restrictions` is empty. Record `Artist` (HTML stripped),
   `LicenseShortName`, `LicenseUrl`, `Credit`, the file page URL and the
   article URL.
7. **Rank and pick.** Article order first (a title equal to the topic, case and
   punctuation aside, ranks above everything), then JPEG over PNG (photographs
   and paintings over rendered diagrams), then larger originals. Phase 1 takes
   the first; the top six are kept as `candidates` for the picker. Phase 2 hands
   the six to the model.
8. **Fetch and store.** Download `thumburl`, refuse anything over
   `PICTURE_MAX_BYTES` (400 KB) or whose magic bytes are not JPEG, PNG, WebP or
   GIF, and upsert the row.

The outcome is one durable event either way, so the build log says which
picture was chosen and why, or why none was:

```
{"type": "picture_ready", "provider": "wikipedia", "title": "Zeno of Citium",
 "page_url": "https://en.wikipedia.org/wiki/Stoicism", "license": "Public domain",
 "version": "9f3a1c2b7d4e"}
{"type": "picture_skipped", "reason": "no_candidate" | "provider_unavailable" | "timeout" | "too_large" | "disabled"}
```

## Work

### 1. Migration `027_expert_pictures.sql`

```sql
CREATE TABLE IF NOT EXISTS expert_pictures (
    expert_id      INTEGER PRIMARY KEY REFERENCES experts(id) ON DELETE CASCADE,
    image          BYTEA        NOT NULL,
    content_type   TEXT         NOT NULL,
    width          INTEGER      NOT NULL,
    height         INTEGER      NOT NULL,
    byte_size      INTEGER      NOT NULL CHECK (byte_size > 0 AND byte_size <= 400000),
    sha256         TEXT         NOT NULL,
    provider       TEXT         NOT NULL CHECK (provider IN ('wikipedia', 'commons', 'openverse')),
    file_name      TEXT,                          -- 'File:Zeno_of_Citium.jpg'
    file_url       TEXT         NOT NULL,         -- the thumbnail that was fetched
    file_page_url  TEXT         NOT NULL,         -- where the licence is stated
    page_url       TEXT,                          -- the article it illustrates
    page_title     TEXT,
    artist         TEXT,
    license        TEXT         NOT NULL,
    license_url    TEXT,
    query          TEXT,                          -- the query that found it
    candidates     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    chosen_by      TEXT         NOT NULL DEFAULT 'build' CHECK (chosen_by IN ('build', 'owner')),
    found_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

The header comment states the precedence rule (recipe → picture → sigil) and
notes that migration 026's "non-null avatar is the owner's choice" stays true
because the build writes here, never to `experts.avatar`. `candidates` holds
metadata only (title, file name, thumbnail URL, licence, artist), never bytes.
`ExpertRepository.reset_build_state` does not touch this table.

### 2. Domain and repository

- `experts/domain.py`: `ExpertPicture` dataclass with every column except
  `image` and `candidates`, plus `version` (`sha256[:12]`) and
  `attribution_required` (false for public domain and CC0). `Expert.picture:
  ExpertPicture | None`.
- `experts/repository.py`: the list, detail and catalog queries gain
  `LEFT JOIN expert_pictures p ON p.expert_id = e.id` selecting the metadata
  columns only; `_row_to_expert` maps them when present. Never select `image`
  in a list query.
- New `experts/picture_repository.py`: `get_blob(expert_id) -> (bytes,
  content_type, sha256) | None`, `upsert(expert_id, found: FoundPicture,
  chosen_by)`, `delete(expert_id)`, `list_missing(limit)` for the backfill,
  `get_candidates(expert_id)`.
- `chat/conversation_repository.py`: the existing `JOIN experts e` gains the
  expert slug and picture version so `ConversationSummary` can render the tile.
  Today `recent-chats.tsx` and `chats-list-page.tsx` synthesise `avatar: null`
  because the summary carries only `expert_persona_name` and `expert_topic`.

### 3. The finder — `experts/picture.py` and `infrastructure/wikimedia.py`

- `infrastructure/wikimedia.py`: `WikimediaClient` (one `httpx.AsyncClient`,
  shared user agent, per-request timeout, retries on 429/5xx via `tenacity`)
  with `search_articles`, `page_images`, `wikidata_claims`, `image_info`,
  `download`. Thin and mockable: every method returns plain dicts, and tests
  feed it recorded JSON.
- `experts/picture.py`: the policy as pure functions, each independently
  testable — `is_free_license(extmetadata) -> bool`, `looks_like_a_mark(file_name)
  -> bool`, `is_living_human(claims) -> bool`, `rank(candidates) ->
  list[Candidate]`, `sniff(bytes) -> str | None`; and one orchestrator,
  `find_picture(client, topic, key_concepts, hints=()) -> FoundPicture | None`,
  that applies the steps above under the deadline and returns the pick with
  its shortlist. `FoundPicture` carries the bytes, the metadata row, and
  `candidates`.
- `PICTURE_RANKER=model` (phase 2): `rank_with_model(candidates, topic,
  key_concepts)` sends the thumbnails as image blocks to `FAST_MODEL` through
  the existing Anthropic client wrapper (so it is metered and capped like every
  other stage), forced to a `choose_picture` tool that returns a per-candidate
  `suitable` flag and a `best` index. Any failure falls back to the heuristic
  order. The prompt states the rules from the decisions section verbatim.

### 4. Builder hook and events

- In `ExpertBuilder.build`, immediately after `plan_ready` (`builder.py` ~line
  487): if `settings.PICTURE_ENABLED` and the expert has no picture, start
  `self._picture_task = asyncio.create_task(self._find_and_store_picture(expert,
  topic, key_concepts, on_event))`. The coroutine catches everything except
  `CancelledError`, upserts on success, and emits `picture_ready` or
  `picture_skipped`. It does not participate in the completeness gate.
- Before the persona stage, `await` the task (it finished minutes ago in any
  real build; the `await` only exists so the event is in the log before
  `done`). On build cancellation or failure, cancel it in the existing
  `finally`.
- Add `picture_ready` and `picture_skipped` to `_LOGGED_EVENTS`.
- `docs/build-flow.md`: event vocabulary, a row in the failure table ("Picture:
  build continues, sigil shown; `picture_skipped {reason}`; recovery: refresh
  from settings"), and a provider row ("Wikimedia: optional; missing means no
  picture, nothing else").

### 5. Service, CLI, backfill

- `ExpertService.refresh_picture(name_or_id, *, hints_from_corpus=True) ->
  Expert`: builds the query list (topic, stored `key_concepts`, validated
  Wikipedia source titles), runs the finder, upserts with `chosen_by='build'`.
  Same shape as `regenerate_persona` and lazily imports for the same reason.
- `ExpertService.remove_picture(name_or_id)`.
- `cli/experts.py`: `refresh-picture <name>` beside `refresh-persona`, and
  `backfill-pictures [--limit N] [--sleep 1.0]` that walks `list_missing` with
  a pause between experts. The backfill is run once by an operator after
  deploy; it is not automatic, so a deploy never fires hundreds of requests at
  Wikimedia unattended.

### 6. API

- Schemas (`api/schemas/experts.py`): `ExpertPictureOut {version, width,
  height, provider, title, artist, license, license_url, page_url,
  file_page_url, attribution_required}`; `picture: ExpertPictureOut | None` on
  `ExpertSummary`, `ExpertWithCatalog` and `CatalogEntry`, present and null
  when absent, like `avatar`.
- `GET /experts/{slug}/picture` — the bytes. Same read rule as
  `GET /experts/{slug}` (owner, shared visibility, admin), so a private expert's
  picture is a 404 to anyone else. Headers: `Content-Type`, `Content-Length`,
  `ETag: "<sha256>"`, `Cache-Control: private, max-age=31536000, immutable`;
  `If-None-Match` returns 304. The `?v=` query is ignored server-side; it
  exists so the URL changes when the picture does and the immutable cache is
  safe.
- `POST /experts/{slug}/picture/refresh` — owner only; synchronous (a few
  seconds); returns the updated expert; throttled with the existing
  `api/ratelimit.py` at a handful per minute per user, because each call fans
  out to Wikimedia.
- `DELETE /experts/{slug}/picture` — owner only, 204; the expert falls back to
  the recipe or sigil. Distinct from picking a sigil style because Reset would
  otherwise bring the picture back.
- Phase 2: `GET /experts/{slug}/picture/candidates` (the shortlist metadata),
  `GET /experts/{slug}/picture/candidates/{n}` (that candidate's thumbnail,
  fetched on demand server-side and held in a small in-memory cache, so the
  picker never loads a third-party origin), `PUT /experts/{slug}/picture
  {"candidate": n}` (fetch, verify, store with `chosen_by='owner'`).
- `experts/avatar.py`: `"picture"` joins `AVATAR_STYLES`, with a comment that
  it renders the stored picture and exists to let an owner pin a hue alongside
  it. `normalise` needs no other change.
- `web-production.md` "Backend gaps": nothing to add; picture refresh and
  removal are offered.

### 7. Web

- `lib/api/types.ts`: `ExpertPicture`, `picture: ExpertPicture | null` on
  `ExpertSummary`; `expert_name` and `expert_picture` on
  `ConversationSummary`. `tests/fixtures/expert.json` gains a populated
  `picture` so `fixtures.test.ts` checks the shape.
- Route handlers: `app/api/experts/[slug]/picture/route.ts` (`GET` via
  `forward`, `DELETE`), `app/api/experts/[slug]/picture/refresh/route.ts`
  (`POST`). Add `etag` to `FORWARDED_HEADERS` in `lib/api/route.ts` and pass
  the request's `If-None-Match` upstream so 304s reach the browser.
- `lib/avatar.ts`: `AvatarStyle` gains `'picture'`; `AvatarSubject` gains
  `picture?: {version} | null`. `resolveRecipe`: no stored recipe and a picture
  → `{style: 'picture', seed, hue: null}`; a stored `picture` style with no
  picture → `sigil` (the same degrade as an unknown style). `isDerived` is
  unchanged: a picture with no recipe is still "derived".
- `components/identity/avatar.tsx`: a `picture` branch renders
  `<img src={`/api/experts/${name}/picture?v=${version}`} alt="" width={size}
  height={size} loading="lazy" decoding="async">` with `object-fit: cover`
  inside the same rounded span, keeping the hue ring when one is pinned and
  setting `data-avatar="picture"`. `alt` is empty because the root is already
  `aria-hidden` and the name is always adjacent. Sizes 16–20px keep the
  picture (a recognisable thumbnail beats a monogram at that size, and it costs
  nothing extra since the same bytes are cached).
- `components/identity/picture-credit.tsx`: a `--fg-3` line, "Picture: Zeno of
  Citium · Wikimedia Commons · Public domain", linking to `file_page_url`,
  rendered on the overview header under the bio and in expert settings, only
  while the picture is what is shown.
- `components/identity/avatar-picker.tsx`: the first option is "Picture"
  (present only when one exists), previewing the found image with its credit
  and two actions: "Find another" (phase 1: `POST …/refresh`; phase 2: the
  candidate strip from `…/candidates`) and "Remove" (`DELETE …/picture`, with
  the existing confirm pattern). The style grid and hue swatches are
  unchanged; Reset (`{"avatar": null}`) returns to the picture when one exists.
- `lib/build/reducer.ts` and `hooks/use-build-events.ts`: `picture_ready`
  writes a log line and triggers the same `router.refresh()` the terminal
  events do, so the rail's tile changes while the build runs.
  `picture_skipped` writes a quiet log line with the reason.
- Motion (web-design.md §9 catalogue): the tile crossfades sigil → picture on
  first paint at `dur-2`, static under reduced motion.
- `e2e/mock-api/server.mjs`: serve a fixture PNG at `/experts/:slug/picture`,
  give one fixture expert a `picture`, accept `picture` in the `PUT /avatar`
  allowlist, and implement `DELETE`/`refresh`. `e2e/avatar.spec.ts`: the rail
  and header show `[data-avatar="picture"] img` for that expert; Remove falls
  back to `data-derived="neutral"`; the credit line links out.
- Lighthouse budgets are unaffected in practice (one cached image per expert,
  lazy below the fold), but the app-page run in `npm run lighthouse` should be
  re-run once with pictures present.

### 8. Configuration

`core/config.py` and `api/.env.example`:

```
# ── Expert picture (found on Wikimedia at build time) ───────────────────────
PICTURE_ENABLED=true
PICTURE_TIMEOUT=20            # seconds for the whole search, per build
PICTURE_MAX_BYTES=400000      # refuse thumbnails larger than this
PICTURE_THUMB_WIDTH=512
PICTURE_RANKER=heuristic      # heuristic | model (one FAST_MODEL call per build)
PICTURE_PROVIDERS=wikipedia   # phase 3: wikipedia,commons,openverse
# Wikimedia's API policy asks for a contact in the User-Agent. Set an email or URL.
PERITUS_CONTACT=
```

`WikipediaFetcher` switches to the shared user agent constant in the same
change.

### 9. Documents to amend

- `web-design.md` §4 "Avatar": replace "A generated sigil, not a photo and not a
  cartoon face" with the new rule — a found, licensed picture of the subject by
  default; never an uploaded photo; never a generated face; never a living
  person; the sigil and the DiceBear styles remain as the owner's alternatives
  and as the fallback. Add the credit line to the "Where the identity shows"
  table for the overview header and settings.
- `web/AGENTS.md` "Avatar identity": the same amendment, keeping the sentence
  about why user uploads are still not allowed.
- `docs/plans/README.md`: a row under "Proposed, not shipped".
- Migration 026's header stays as written; 027's header carries the note.

## Phases, with a done-when check

**Phase 1 — find, store, serve, render.** Migration, domain, repository,
`WikimediaClient`, the heuristic finder, the builder hook and events, `GET`
and `DELETE` endpoints, the refresh endpoint, the CLI commands, web types,
route handlers, the `picture` branch of the avatar, the credit line, Remove and
Find-another in the picker, docs. *Done when:* building "Stoic philosophy" on a
clean database shows a non-generated picture in the rail before discovery
finishes; `GET /experts/{slug}` reports its provenance; Remove in the picker
returns the tile to the neutral monogram and Reset does not bring the picture
back; `just check` and `just test-db` are green; `backfill-pictures` has been
run against the existing experts and the result eyeballed in the rail.

**Phase 2 — the "good" part.** `PICTURE_RANKER=model`, the candidate endpoints,
the candidate strip in the picker, `chosen_by='owner'`. *Done when:* the model
picks differently from the heuristic on at least a handful of topics where the
lead image is a map, flag or diagram, and choosing a candidate survives a
rebuild.

**Phase 3 — breadth.** Wikimedia Commons file search (`gsrnamespace=6`) for
topics whose articles have no free lead image; Openverse as an optional keyed
provider; the credit rendered in the Rust TUI's catalog detail; a public
`GET /catalog/{slug}/picture` if the catalog ever renders tiles without a
session. *Done when:* the skip rate over the existing experts, measured from
`picture_skipped` events, drops to single digits.

## Failure modes

| Failure | Effect on the build | Event | Recovery |
|---|---|---|---|
| Wikimedia unreachable, 429, 5xx | none; sigil shown | `picture_skipped {reason: provider_unavailable}` | Find another in settings, or the backfill |
| No article with a free, non-mark, non-living image | none | `picture_skipped {reason: no_candidate}` | phase 3 widens the pool |
| Deadline passed | none | `picture_skipped {reason: timeout}` | as above |
| Thumbnail over the cap or not an image | none | `picture_skipped {reason: too_large}` | next candidate is tried first |
| `PICTURE_ENABLED=false` | none | `picture_skipped {reason: disabled}` | — |
| Build cancelled or fails | task cancelled with it | — | a rebuild finds again only if no picture was stored |

Nothing in this feature can make a build fail, mark an expert not-ready, or
touch `experts.avatar`.

## Cost and load

- Phase 1 costs no model tokens. Five or six HTTP requests to Wikimedia per
  build, well inside their public limits; the backfill is paced by hand.
- Storage: one row of 30–150 KB per expert. `GET /experts` never reads it.
- Phase 2 adds one `FAST_MODEL` call per build with up to six 512px images,
  metered through the build meter under the tier's spend cap like every other
  stage.

## Tests

API (`api/tests`):

- `unit/test_picture_policy.py`: the licence allowlist (every accepted string,
  and NC, ND, "Fair use", empty and missing all refused; a non-empty
  `Restrictions` refused); the mark regex on real Commons file names; the
  living-person rule on Wikidata claim fixtures (living, deceased, not human,
  no item); ranking determinism and the exact-title bonus; magic-byte sniffing
  including an HTML error page served with an image content type.
- `unit/test_picture_finder.py`: `find_picture` against a fake
  `WikimediaClient` fed recorded JSON for "Stoicism" (picks the bust), a
  disambiguation topic, a living-person topic (falls to the next article), an
  all-marks topic (returns `None`), a timeout (returns `None` inside the
  deadline). No network in the suite.
- `api/test_expert_picture_endpoint.py` (DB mocked, like the avatar endpoint
  tests): bytes with `ETag` and `Cache-Control`; 304 on `If-None-Match`; 404 for
  a private expert to a non-owner; 200 for a shared one; `DELETE` is 204 and
  owner-only; refresh is throttled; `picture` rides on list, detail and catalog
  and serialises as null when absent.
- `unit/test_picture_repository.py` (DB-gated): upsert, blob read, delete,
  cascade on expert delete, and survival of `reset_build_state`.
- `unit/test_builder_picture.py`: a finder that raises produces
  `picture_skipped` and a successful build; a finder that succeeds produces
  `picture_ready` before `done`.

Web (`web/tests`, `web/e2e`): `avatar.test.ts` resolver cases for the three
precedence levels and the missing-picture degrade; `fixtures.test.ts` for the
new shape; `build-reducer.test.ts` for both events; the e2e cases in §7.

## Open questions

1. **Living people are excluded outright.** If a topic *is* a living person
   (an expert on a working scientist's methods), the expert gets a sigil. The
   alternative, a picture of their best-known work or institution, needs phase 3.
   Confirm the exclusion is the intended default.
2. **Public catalog.** Should the picture be visible without a session on the
   catalog, and if so does the credit need to appear on the catalog card as
   well as the detail page? This plan defers the unauthenticated endpoint to
   phase 3.
3. **Sensitive topics.** Phase 1 relies on Wikipedia's editorial choice of lead
   image and the mark filter; it has no content classifier of its own. If the
   product wants a gate before phase 2, `PICTURE_RANKER=model` can be pulled
   into phase 1 at the cost of one cheap call per build.
4. **The persona prompt does not see the picture** and the picture does not
   influence the persona name. Keeping them independent is deliberate, but say
   so if the intent was for the two to agree.

## Rejected alternatives

- **Generated images.** Out by request, and would reopen the "invented person"
  problem the sigil rule exists to avoid.
- **Hotlinking Wikimedia thumbnails.** Third-party requests from the browser,
  links that rot when files move, and a service that asks not to be hotlinked
  at volume. Storing 100 KB per expert is cheaper than any of those.
- **Unsplash or Pexels.** Attractive stock that is about the mood of a topic,
  not the subject; an API key; and a licence that requires a live link back on
  every render.
- **Search-engine image APIs or scraping `og:image` from corpus sources.**
  Unknown licences on every result, and the corpus's top pages usually expose a
  logo or a banner, not a picture of the subject.
- **`next/image` with `remotePatterns`.** Adds a third-party origin to the
  browser for an image we already have to fetch server-side to check its
  licence.
- **Pillow.** Not needed while Wikimedia produces the size we want; revisit only
  if a second size (a 96px rail variant) is wanted.
- **Deriving the expert's hue from the picture.** Colour is chosen, never
  derived; see the decisions.
- **A circular crop.** Reads as a headshot of the persona, which the picture is
  explicitly not.
