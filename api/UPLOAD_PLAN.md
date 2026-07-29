# User-supplied sources — implementation plan

Let a user add their own material to an existing expert: a PDF, a text/markdown
file, or a web page by URL. This is the direct fix for the corpus problem behind
the answer-quality work — Graham and Fisher are in copyright, so the good
material is not on Gutenberg and discovery can never find it. The user has the
book; the pipeline just needs a way to accept it.

## Decisions (taken by the user)

| | |
|---|---|
| **Inputs** | PDF upload, plain text / Markdown upload, web page by URL. No DOCX/EPUB. |
| **Validation** | Trusted, never rejected. `passed=true`, `discovered_via='upload'`, `source_tier='primary'`, `quality_score=NULL`. Still tagged for `key_claims` / `covered_concepts` so gap-fill and coverage see it. |
| **Processing** | Durable: extend `build_jobs` with a `job_type`, reuse the existing worker, retries, and SSE event tail. |

## Decisions I am taking, and why

**Uploads survive a rebuild.** `ExpertRepository.reset_build_state` currently
deletes every source for the expert (`repository.py:396-400`), so a rebuild would
silently destroy material the user supplied by hand. It will now preserve
`discovered_via='upload'` sources and their chunks, and the rebuild's graph stage
will include the preserved chunks so the concept graph still covers them.
Discovery-found sources are still wiped, exactly as now.

**Pending payloads are persisted, not held in memory.** The worker is a separate
process, so the bytes have to survive the HTTP request. A new `source_uploads`
table holds the raw payload (bytes for PDF, text for txt/md, URL for a page)
until the job completes, then the payload column is cleared. There is no S3/blob
store configured in this project and 20 MB is already the OCR ceiling, so
Postgres `BYTEA` is the right size of solution here.

**One active *build* per expert, several ingests allowed.** The existing partial
unique index `idx_build_jobs_one_active` is over `expert_id` regardless of type;
it becomes build-only. Ingest jobs may queue in parallel with each other, but the
API refuses an ingest while a build is active — a build wipes and rebuilds the
corpus underneath it.

**Uploads do not consume build credits** in this pass. A single document costs
far less than a build, and the metering path is wired to tier economics and spend
caps that only make sense for a build. Flagged as an open question below rather
than guessed at.

## Work

### 1. Migration `021_source_uploads.sql`
- `build_jobs ADD COLUMN job_type TEXT NOT NULL DEFAULT 'build'` + CHECK in
  (`build`, `ingest_source`), and `ADD COLUMN payload JSONB`.
- Replace `idx_build_jobs_one_active` with a build-only partial unique index.
- New index for claiming by type.
- `CREATE TABLE source_uploads` — id, expert_id, owner_id, kind, title, filename,
  url, media_type, byte_size, content BYTEA, text_content TEXT, created_at.
- `sources ADD COLUMN uploaded_by TEXT` so a source records who supplied it.

### 2. Domain + repository
- `jobs/domain.py`: `JobType` enum; `BuildJob.job_type`, `BuildJob.payload`.
- `jobs/repository.py`: `enqueue(..., job_type, payload)`, `_row_to_job` updated,
  `get_active_job` gains a type filter so build-cancel logic is unaffected.
- `sources/domain.py`: `SourceType.UPLOAD`.
- New `uploads/` module: `domain.py` (UploadKind, PendingUpload), `repository.py`.

### 3. Text extraction — `uploads/extract.py`
- PDF → existing `infrastructure/pdf_parser.parse_pdf_bytes` (Mistral OCR).
- text/markdown → decode UTF-8 with a lenient fallback.
- URL → existing `sources/fetchers/web.WebFetcher`.
- One `extract(pending) -> RawSource` entry point; raises `IngestionError` with a
  usable message on empty or undecodable input.

### 4. Ingest service — `uploads/service.py`
The worker-side job body:
1. Load the pending upload.
2. Extract text.
3. Tag it (one `FAST_MODEL` call → `key_claims`, `covered_concepts`,
   `content_type`, `difficulty`). Never gates admission; a tagging failure
   degrades to empty tags and the document is still ingested.
4. Insert the `sources` row (`passed=true`, `source_tier='primary'`,
   `discovered_via='upload'`).
5. `ingest_sources` for chunk → contextualise → embed → store.
6. Graph-extract the new chunks and merge into the existing graph.
7. Bump `experts.source_count` / `chunk_count`; clear the payload.
Emits the same event shapes the build SSE already speaks.

### 5. Worker dispatch — `jobs/worker.py`
`_run_job` branches on `job.job_type`. The build path is untouched. The ingest
path skips metering/entitlements (no credit hold), does **not** call
`update_status(BUILDING)` or `reset_build_state`, and must never leave the expert
in a non-ready state — an ingest failure is a failed job, not a broken expert.

### 6. API — `routes/sources.py`
- `POST /experts/{slug}/sources/upload` — multipart, owner-only, size-capped.
- `POST /experts/{slug}/sources/url` — JSON body.
- `GET  /experts/{slug}/sources` — list, with `discovered_via` so the UI can mark
  user-supplied material.
- `DELETE /experts/{slug}/sources/{id}` — remove a source and its chunks.
- Refuse while a build is active; refuse if the expert is not owned by the caller.
- Reuse the existing `/experts/{slug}/build/events` SSE tail for progress.

### 7. Web
- Upload panel on the expert detail page: drag-drop / file picker / URL field.
- Source list showing which sources the user supplied, with delete.
- Progress via the existing build-events SSE stream.

### 8. Tests
- Extraction dispatch and failure modes (pure, no network).
- `reset_build_state` preserves uploads and wipes discovered sources.
- Job type round-trips through the repository; the build-only active index
  permits a queued ingest alongside a running build.
- Route auth: non-owner refused, oversize refused, ingest-during-build refused.

## Status — implemented (2026-07-29)

Migration 021 applied. `ruff` clean, `tsc` clean, `eslint` clean, `next build`
passes, **421 passed / 54 skipped** (the 11 new DB-backed tests skip without
`PERITUS_TEST_DATABASE_URL`).

Verified against the live schema inside rolled-back transactions, since there is
no local Postgres and `DATABASE_URL` points at Supabase (the test fixture
`TRUNCATE`s, so it must never be aimed there):

- uploads preserved by `reset_build_state`; `'plan'` **and** `NULL`
  `discovered_via` both wiped — the `IS DISTINCT FROM` predicate matters, a plain
  `<> 'upload'` would have preserved every legacy NULL row
- recount leaves `source_count=1 chunk_count=1` with one upload surviving
- `source_uploads` payload CHECK rejects a `pdf` with no bytes, and an unknown kind
- one build + two ingests coexist; a second active build is still blocked; an
  unknown `job_type` is rejected

Placement note: the manager sits on the expert **detail** page, not the audit
`/sources` page. The audit surface is documented read-only ("Nothing here mutates
a corpus"), and management already lives on the detail page alongside
`ExpertMenu`. Worth revisiting if you'd rather it lived under the Sources tab.

## Open question for the user

Should uploads cost credits? Currently free. If they should, the natural shape is
a small fixed charge per document settled against actual metered spend, reusing
`EntitlementService`.
