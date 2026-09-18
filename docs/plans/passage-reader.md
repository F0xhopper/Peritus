# The passage in its source — reading a citation in context

**Date:** 2026-09-17
**Status:** proposed, nothing built.
**Question answered:** should a citation open the actual source in a panel and
highlight where the passage came from?
**Against:** `main` at `ea98b77`, the day after the Sources and chat review
(`sources-chat-review.md`) shipped its C1 fix — citations now carry the
passage text and the panel quotes it.

## The short answer

Yes, in one specific form, and there is a bug to fix first.

- **Fix first (phase 0):** the passage text a citation carries is lost the
  moment the chat is reloaded. The stream sends it and the panel shows it; the
  conversation read path strips it. Every reopened chat shows the "saved before
  passages were kept" fallback, including chats answered today.
- **Build (phase 1):** the cited passage *in context* — the paragraphs before
  and after it from the same source, the cited one highlighted, in the panel
  that already opens on a citation. One read-only route, no new storage.
- **Build (phase 2):** the whole extracted text of a source for the kinds we
  may reproduce, opened at the cited passage. A page, not a panel.
- **Do not build:** the original PDF or web page with a highlight drawn on it.
  We keep no originals and no coordinates; it is a multi-week feature that
  mostly serves one of twelve source kinds.

The product's claim is that the evidence is inspectable. A quote with a
bibliography entry is a claim; the quote with the paragraph before and after it
is the evidence. It is also where the answer audit becomes visible: a citation
that does not support its sentence is obvious once the reader can see what
surrounds it.

## What exists on `main` today (verified)

**The stream carries the passage; the panel quotes it.** `used_citations()` in
`api/src/peritus/chat/grounding.py` sends `n`, `label` (the source's title),
`source_id`, `text` (the passage trimmed to 600 characters on a word boundary),
`disputed` and `dispute_points`. `components/chat/passage-panel.tsx` blockquotes
`citation.text`, heads the panel with the per-answer number, and names siblings
from the same source. The chip popover previews the same text.

**The read path drops it.** `Citation` in
`api/src/peritus/api/schemas/conversations.py` still declares only `n`, `label`
and `source_id`. `GET /conversations/{id}` builds `ConversationMessageOut` from
the stored JSONB through that model, and Pydantic discards the rest. Checked
directly:

```
Citation.model_validate({'n':1,'label':'x','source_id':1,'text':'the passage',
                         'disputed':True,'dispute_points':['a']}).model_dump()
→ {'n': 1, 'label': 'x', 'source_id': 1}
```

The JSONB row keeps the full dict (`conversation_repository.py` stores
`json.dumps(citations)` untouched), so nothing is lost on disk — only on the
way out. The e2e suite cannot see this: its mock seeds stored conversations with
`text` already present (`e2e/mock-api/seed.mjs`), so the reload test passes
against a shape the real API never returns. The generated
`lib/api/types.generated.ts` shows the truth: its `Citation` has three fields.

**A citation does not say which chunk it is.** `Passage` (the server-side
object) carries `chunk_id`; the citation dict does not. The retrieval audit
event does send `chunk_id` per step, but matching a citation to a step by
position is exactly what `audit_trail.py` refuses to assume. "Scroll to the
cited passage" needs the id on the citation.

**Retrieval returns lone chunks.** `EnrichedResult.context_block()` is one
chunk. No neighbours are fetched, so "the passage in context" is a new read,
not a pass-through of something already in hand.

**What is stored, per chunk.** `source_chunks(expert_id, source_id,
sequence_n, text, context_text, embedding, chunk_meta)`. `sequence_n` orders a
source's chunks; `chunk_meta` is `{"section", "paragraph_n"}` from the chunker;
`context_text` is the generated contextual note, kept separately from the
text and labelled "a note, not passage text" in the model's prompt. There are
no page numbers, no character offsets into the original, no bounding boxes.

**Chunks are ~1,000 characters with a one-sentence overlap.** `_split_paragraphs`
in `ingestion/chunker.py` opens each chunk with the *last sentence* of the
previous one, only when that sentence is ≤200 characters and the previous
paragraph had more than one sentence. So consecutive chunks are joined back
into running text by one rule: if chunk *n+1* begins with the final sentence of
chunk *n*, drop it from *n+1*. Sections and paragraph numbers survive in
`chunk_meta`.

**We keep no originals.** `source_uploads.content` / `text_content` are cleared
once ingestion succeeds (migrations 021, 023). Fetched pages and PDFs are never
stored; only the cleaned extraction is, and `clean_text` can drop a lot of it
(the Summa lost 94% as table of contents). The reader is honest only if it says
so: *the text the expert read*, not *the original*.

**What we know about a source, for gating.** Twelve `SourceType`s: wikipedia,
arxiv, youtube, exa, web, gutenberg, pdf, reddit, thought_leader, pubmed,
openalex, upload. `sources.full_text_method` says how the text was obtained
(`abstract`, `full_text`, `oa_pdf_url`, `oa_pdf_ocr`, `oa_landing_url`,
`oa_landing_html`, `landing_page_url`, `html`, `pdf`, `pdf_url`,
`exa_contents`, `wikipedia_extract`, `youtube_transcript`, `transcript`);
`substance` says how much (`full` / `partial` / `abstract`, API-side only);
`text_chars` says how long. There is **no licence column**; the open-access
flag `fulltext.py` sees is not persisted.

**Sources are small.** From the shared dev/prod database today:

| Kind | Sources | Avg chunks | Max chunks | Avg chars | Max chars |
|---|---|---|---|---|---|
| exa | 43 | 39 | 111 | 37k | 83k |
| openalex | 29 | 23 | 165 | 20k | 123k |
| web | 12 | 32 | 82 | 40k | 95k |
| wikipedia | 11 | 22 | 53 | 25k | 62k |
| thought_leader | 7 | 27 | 45 | 26k | 51k |
| pubmed | 7 | 4 | 17 | 5k | 18k |
| arxiv | 5 | 30 | 60 | 35k | 84k |
| gutenberg | 3 | 55 | 60 | 76k | 84k |
| pdf | 1 | 31 | 31 | 29k | 28k |

The largest source is 165 chunks, about 123 KB of text. The fetch-boundary
ceiling from the syllabus work keeps it that way. So the whole of any source
fits in one response, and the window-versus-whole question is not a
performance question at all. It is only a copyright question.

## Phase 0 — keep the passage on reload (a bug) — S

1. `api/src/peritus/api/schemas/conversations.py`: `Citation` gains
   `text: str | None = None`, `disputed: bool = False`,
   `dispute_points: list[str] = []`, and (for phase 1) `chunk_id: int | None
   = None`. The docstring already promises "the exact shape the SSE `sources`
   event emits and JSONB stores"; make it true.
2. `just types` — regenerate `api/openapi.json` and `types.generated.ts`.
   `web/tests/schema-parity.test.ts` checks field names between the two, and
   `lib/api/types.ts` already declares the optional fields by hand.
3. A unit test on the API that round-trips a stored citation dict through
   `ConversationMessageOut` and asserts `text` survives. This is the test that
   was missing: `test_grounding.py` covers what is *emitted*, nothing covers
   what is *returned*.
4. Make the e2e mock honest: its `GET /conversations/{id}` should serve exactly
   the fields the real schema serves. Today it forwards whatever the seed holds.

Done when: open a chat answered before the fix, reload, and the panel quotes
the passage rather than the fallback sentence.

## Phase 1 — the passage in context — M

**API.**

- `used_citations()` adds `"chunk_id": p.chunk_id`. Older stored answers have
  none and get no window; the panel falls back to the quote. Recovering a chunk
  by matching stored text is not worth it — an answer's passages were what
  they were, and a re-ingested source has different chunks.
- One route, read-scoped: `GET /experts/{slug}/sources/{source_id}/passages
  ?around=<chunk_id>&before=2&after=2`, on `ReadableExpert` (a share grant
  lets someone chat, so it must let them read what the chat cites — the same
  gate `corpus-report` uses, not the owner-only `list_sources`). It lives in
  `routes/sources.py` beside the owner routes with a docstring saying why it is
  the odd one out, or in `routes/audit.py` beside `corpus-report`; the former,
  because it is not an audit surface.
- Response:

  ```
  { "source": { "id", "title", "author", "url", "source_type",
                "full_text_method", "text_chars", "passage_count" },
    "scope": "window",
    "cited": <chunk_id>,
    "passages": [ { "chunk_id", "sequence_n", "section", "paragraph_n",
                    "text" }, … ] }
  ```

  `text` is the chunk with the leading overlap sentence removed when it
  duplicates the tail of the passage before it — reuse the chunker's
  last-sentence helper rather than a second implementation. The *cited* chunk
  is never trimmed; its successor is. `context_text` is not returned: it is a
  generated note about the passage, not the source, and the prompt already
  labels it as such.
- The query is one `SELECT … FROM source_chunks WHERE expert_id = $1 AND
  source_id = $2 AND sequence_n BETWEEN $3 AND $4 ORDER BY sequence_n`, with a
  first lookup of the cited chunk's `sequence_n`. Put it on `UploadRepository`
  beside `list_sources` and `delete_source`, which is already the sources
  repository in everything but name. 404 when the chunk is not in that source
  (a citation from before a re-ingest).
- Pydantic response model; `just types`; a parity entry.

**Web.**

- Proxy: `app/api/experts/[slug]/sources/[id]/passages/route.ts`, `forward()`
  with `pickParams(['around', 'before', 'after'])`, the same shape as the
  ledger route.
- In `passage-panel.tsx`, below the blockquote: an **In context** section that
  loads when the panel opens with a `chunk_id`, and renders the window as
  running prose in the reading face — the neighbours in `text-fg-3`, the cited
  passage in `text-fg` on the expert wash, a section label from `chunk_meta`
  above the first paragraph when there is one. No spinner: the quote is
  already there; the context arrives under it. On failure show nothing new.
- The heading gains the position when known: *Passage 2 of Langstroth on the
  Hive · Chapter 4, ¶ 12*.
- Below `lg` the panel is a bottom sheet at 50% then 92%; the window makes
  the 92% state worth having. Nothing else in the sheet changes.
- `numberCitations` and the per-answer numbering are untouched: the window is
  keyed by `chunk_id`, never by `n`.

**Tests.** API: the trim rule (duplicate tail dropped; a one-sentence
paragraph not treated as overlap; cited chunk whole), the window bounds at the
start and end of a source, the 404, and that a grantee can read. Web: a unit
test for the window component with and without a section; the e2e mock gets a
`/sources/:id/passages` handler and the seed gets `chunk_id`s; the citation
e2e opens a chip and sees the neighbour text.

Done when: click a chip, and the panel shows the quoted passage with the
paragraph before and after it from the same source, the quote highlighted, on
desktop and in the phone sheet.

## Phase 2 — the whole source, for the kinds we may show — M–L

The same route with `?whole=true`. The server decides, never the client:

- **Open** — the whole text is returned, `scope: "whole"`: `gutenberg`,
  `wikipedia`, `arxiv`; any source whose `full_text_method` starts with `oa_`
  (an open-access copy was resolved and read); and `upload`, but **for the
  expert's owner only** — the upload flow warns about rights rather than
  blocking, and that warning was made to the uploader, not to whoever they
  later share the expert with.
- **Everything else** — `exa`, `web`, `thought_leader`, `reddit`, `youtube`,
  `pdf`, and `openalex` / `pubmed` read through a non-OA route — gets the
  window regardless of `whole`, with `scope: "window"`. No error: the client
  simply does not offer "the whole source" when the panel's first response
  says the scope is a window.
- `abstract`-only sources (`full_text_method === 'abstract'`, which the panel
  already flags) have nothing beyond the window to read; the action is hidden.

A licence column would be better than a kind list. Nothing writes one today,
and adding one is a source-selection change, not a reader change; the kind list
is the honest gate we have and it is conservative.

**Web.** A page, not the panel — a whole book in a 50% sheet is not reading:
`app/(app)/experts/[slug]/sources/[id]/read/page.tsx`, `?at=<chunk_id>`.
Reading width, section headings from `chunk_meta`, every chunk an element with
`id="p-<chunk_id>"`, the cited one on the expert wash and scrolled into view
after mount. One line at the top: *This is the text the expert read, as
extracted. The original is at gutenberg.org* — with the external link. The
panel's "See the source" stays; a second quiet action, **Read the whole
source**, appears only when the scope is whole. The Sources row detail gets
the same action.

No paging: 165 chunks is the largest source in the database and the fetch
ceiling holds it there. If a source ever exceeds ~500 chunks, page then.

Done when: from a citation on a Gutenberg or arXiv source, one click opens
the whole text scrolled to the cited paragraph; from an Exa source the action
is absent and the window still shows.

## Not recommended

**The original document with a highlight drawn on it.** It needs the original
kept (every fetched PDF and page, for every source, forever), a position
carried from extraction through OCR and chunking to the chunk (page and
bounding box, or at least a character offset — none exist today), a PDF
renderer in the bundle, and acceptance that a web page fetched in March is not
the page in September. It benefits `pdf` and the OA-PDF paths; for a
transcript, an extract or an HTML page it is the same text we already have,
drawn worse. Weeks, for one kind. Revisit only if a licensed-document tier
(journals, textbooks) becomes the product.

**Sentence-level highlighting.** The model cites a passage index, and the
faithfulness audit (`chat/faithfulness.py`) judges each answer against whole
passages. Marking one sentence would claim a precision the system does not
have. Highlight the chunk.

**Showing the contextual note as the passage.** `context_text` was written
about the chunk for embedding; it is not a quotation, and the prompt says so.
It never appears in a blockquote.

**Persisting the neighbours with the citation.** Six chunks per citation would
multiply the stored size of an answer for something a read-only route serves
in one query. Fetch on demand.

## Effort and order

| Phase | What | Effort |
|---|---|---|
| 0 | Citation schema carries what is stored; parity; a round-trip test; honest mock | S |
| 1 | `chunk_id` on citations; the passages route with the trim rule; In context in the panel | M |
| 2 | Whole-source scope by kind; the reader page; the action in the panel and the row detail | M–L |

Phase 0 is worth shipping alone today. Phase 1 is the feature. Phase 2 is a
cheap extension of phase 1 whose only real decision is the kind list, and that
decision is recorded above so it does not have to be made in a code review.
