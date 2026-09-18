"""User-supplied sources — add your own material to an existing expert.

Discovery finds what is publicly indexable. These routes exist for everything
else: books still in copyright, private notes, internal documents, papers behind
a login. The user has the file; this is how they hand it over.

Mutation here is **owner-only**, and deliberately stricter than reading. The
audit routes let anyone who can read an expert inspect its corpus; adding to that
corpus, or deleting from it, is the owner's alone — a public expert that any
reader could add documents to would be an expert nobody could trust.

Ingest is durable: the payload is stored, a job is queued, and a worker does the
work. Progress rides the existing ``/experts/{slug}/build/events`` SSE stream, so
clients get upload progress without a second event transport.

One route here is **read-scoped and the odd one out**: ``/passages`` serves the
text around a cited passage. It belongs beside the sources it reads rather than
in the audit routes — it is what an answer's evidence *says*, not an account of
how the corpus was assembled — and it is gated like every other read of a
corpus, because a share grant that lets someone chat has to let them read what
the chat cites.
"""

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from peritus.api.deps import CurrentUser, Jobs, OwnedExpert, ReadableExpert, Uploads
from peritus.api.schemas.sources import (
    MAX_TEXT_BYTES,
    MAX_UPLOAD_BYTES,
    TITLE_MAX_CHARS,
    AddUrlRequest,
    PassageOut,
    PassageSourceOut,
    PassageWindowOut,
    SourceOut,
    UploadAcceptedOut,
)
from peritus.audit.domain import decode_json_field
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.ingestion.chunker import last_sentence
from peritus.jobs.domain import JobType
from peritus.jobs.repository import JobRepository
from peritus.uploads.domain import UploadKind
from peritus.uploads.extract import decode_text_upload

logger = get_logger(__name__)

router = APIRouter(prefix="/experts", tags=["sources"])

# Extensions accepted as plain text. Anything else with a text-ish media type is
# still accepted — the extension list is a hint for the error message, not the
# gate — but these are what the UI advertises.
_TEXT_SUFFIXES = (".txt", ".md", ".markdown", ".text")
_PDF_SUFFIXES = (".pdf",)


async def _guard_no_active_build(expert: Expert, jobs: JobRepository) -> None:
    """Refuse an ingest while a build is running.

    A build wipes and re-fetches the corpus underneath. Uploads survive that
    (``reset_build_state``), but a document landing *mid-build* could be ingested
    after the reset and before the graph stage, or after the graph stage and
    never reach the graph at all. Making the user wait is far better than either.
    """
    active = await jobs.get_active_job(expert.id, job_type=JobType.BUILD)
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="This expert is building. Add sources once the build finishes.",
        )


async def _queue(
    jobs: JobRepository, expert: Expert, upload_id: int, title: str, kind: UploadKind
) -> int:
    job = await jobs.enqueue(
        expert_id=expert.id,
        tier=str(expert.tier),
        source_filter=None,
        max_attempts=settings.WORKER_MAX_ATTEMPTS,
        job_type=JobType.INGEST_SOURCE,
        payload={"upload_id": upload_id},
    )
    logger.info(
        "Queued ingest job %d for expert %d (upload=%d, kind=%s)",
        job.id,
        expert.id,
        upload_id,
        kind,
    )
    return job.id


def _clean_title(raw: str | None, fallback: str) -> str:
    title = (raw or "").strip() or fallback
    return title[:TITLE_MAX_CHARS]


@router.post("/{slug}/sources/upload", response_model=UploadAcceptedOut, status_code=202)
async def upload_source(
    expert: OwnedExpert,
    user: CurrentUser,
    uploads: Uploads,
    jobs: Jobs,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    author: str | None = Form(None),
) -> UploadAcceptedOut:
    """Accept a PDF or text/markdown file and queue it for ingestion.

    202, not 201: the source does not exist yet. What exists is a durable
    payload and a queued job, and the response says which job to watch.
    """
    await _guard_no_active_build(expert, jobs)

    filename = (file.filename or "").strip()
    lowered = filename.lower()
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    resolved_title = _clean_title(title, filename or "Untitled upload")

    if lowered.endswith(_PDF_SUFFIXES) or file.content_type == "application/pdf":
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"PDF is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
            )
        upload = await uploads.create(
            expert_id=expert.id,
            owner_id=user.id,
            kind=UploadKind.PDF,
            title=resolved_title,
            author=author,
            filename=filename or None,
            media_type=file.content_type,
            content=data,
        )
        kind = UploadKind.PDF
    elif lowered.endswith(_TEXT_SUFFIXES) or (file.content_type or "").startswith("text/"):
        if len(data) > MAX_TEXT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File is larger than the {MAX_TEXT_BYTES // (1024 * 1024)} MB limit.",
            )
        upload = await uploads.create(
            expert_id=expert.id,
            owner_id=user.id,
            kind=UploadKind.TEXT,
            title=resolved_title,
            author=author,
            filename=filename or None,
            media_type=file.content_type,
            text_content=decode_text_upload(data),
        )
        kind = UploadKind.TEXT
    else:
        raise HTTPException(
            status_code=415,
            detail="Only PDF, .txt and .md files can be uploaded. For a web page, use the URL field.",
        )

    job_id = await _queue(jobs, expert, upload.id, resolved_title, kind)
    return UploadAcceptedOut(
        upload_id=upload.id, job_id=job_id, title=resolved_title, kind=str(kind)
    )


@router.post("/{slug}/sources/url", response_model=UploadAcceptedOut, status_code=202)
async def add_url_source(
    expert: OwnedExpert,
    req: AddUrlRequest,
    user: CurrentUser,
    uploads: Uploads,
    jobs: Jobs,
) -> UploadAcceptedOut:
    """Accept a web page by URL and queue it for ingestion.

    The page is fetched in the worker, not here: a slow or hanging site must not
    hold an HTTP request open, and a fetch failure should land in the job's event
    log next to everything else about that document.
    """
    await _guard_no_active_build(expert, jobs)

    title = _clean_title(req.title, req.url)
    upload = await uploads.create(
        expert_id=expert.id,
        owner_id=user.id,
        kind=UploadKind.URL,
        title=title,
        author=req.author,
        url=req.url,
    )
    job_id = await _queue(jobs, expert, upload.id, title, UploadKind.URL)
    return UploadAcceptedOut(
        upload_id=upload.id, job_id=job_id, title=title, kind=str(UploadKind.URL)
    )


@router.get("/{slug}/sources", response_model=list[SourceOut])
async def list_sources(expert: OwnedExpert, uploads: Uploads) -> list[SourceOut]:
    """Every source in this expert's corpus, newest first.

    Owner-scoped like the mutations rather than read-scoped like the audit
    routes: this list is the management view that the delete button acts on, and
    the audit surface already serves the public "what is this made of" question.
    """
    rows = await uploads.list_sources(expert.id)
    return [SourceOut(**r) for r in rows]


@router.delete("/{slug}/sources/{source_id}", status_code=204)
async def delete_source(expert: OwnedExpert, source_id: int, uploads: Uploads) -> None:
    """Remove a source and its chunks from the corpus.

    Applies to any source, not only uploads: a build that pulled in something the
    owner does not want their expert citing should be correctable without a full
    rebuild.
    """
    removed = await uploads.delete_source(expert.id, source_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Source not found")
    logger.info("Deleted source %d from expert %d", source_id, expert.id)


# The kinds whose text we may reproduce in full. A licence column would be
# better, and nothing writes one: `fulltext.py` sees an open-access flag and
# does not persist it. Until something does, the kind — plus an `oa_` full-text
# method, which *is* recorded and means an open-access copy was resolved — is
# the honest gate, and it is deliberately conservative. An upload is the
# owner's own document: whole for them, a window for anyone they shared with,
# because the rights warning at upload was shown to the uploader alone.
_WHOLE_TEXT_TYPES = frozenset({"gutenberg", "wikipedia", "arxiv"})

#: Wide enough for the whole of any source in the corpus (165 chunks is the
#: largest, and the fetch ceiling holds it there). Page when that stops being
#: true, not before.
_WHOLE_WINDOW = 500
_OWNER_ONLY_WHOLE_TYPES = frozenset({"upload"})


def _whole_text_allowed(source: dict[str, object], is_owner: bool) -> bool:
    source_type = str(source.get("source_type") or "")
    method = str(source.get("full_text_method") or "")
    if method == "abstract":
        # There is nothing beyond the window to read.
        return False
    if source_type in _OWNER_ONLY_WHOLE_TYPES:
        return is_owner
    return source_type in _WHOLE_TEXT_TYPES or method.startswith("oa_")


@router.get("/{slug}/sources/{source_id}/passages", response_model=PassageWindowOut)
async def source_passages(
    expert: ReadableExpert,
    source_id: int,
    user: CurrentUser,
    uploads: Uploads,
    around: int | None = Query(
        None, description="The chunk id a citation points at; the first chunk when omitted."
    ),
    before: int = Query(2, ge=0, le=20),
    after: int = Query(2, ge=0, le=20),
    whole: bool = Query(False, description="Ask for the whole source; the server decides."),
) -> PassageWindowOut:
    """The cited passage in context — the paragraphs either side of it.

    A quote with a bibliography entry is a claim; the quote with the paragraph
    before and after it is the evidence, and it is where a citation that does
    not support its sentence becomes obvious.

    **This is the text the expert read, not the original.** No original is kept
    (`source_uploads.content` is cleared once ingestion succeeds) and the
    extraction can drop a great deal — a table of contents, page chrome — so a
    client showing this must say which one it is showing.

    ``whole=true`` is a request, not an instruction: the server returns the
    whole text only for the kinds it may reproduce, and a window otherwise,
    with ``scope`` saying which happened.
    """
    source, rows = await uploads.passage_window(
        expert.id,
        source_id,
        # No citation to centre on — the Sources page opens a source at its
        # beginning, which is the first chunk rather than an arbitrary one.
        around=around,
        # The whole source, when it is allowed, is a window wide enough to hold
        # it: the largest source in the corpus is 165 chunks.
        before=_WHOLE_WINDOW if whole else before,
        after=_WHOLE_WINDOW if whole else after,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="That source is not part of this expert.")
    if not rows:
        # A citation from before a re-ingest: the source is here, that chunk is
        # not. Not an error the reader caused, and not something to invent a
        # passage for.
        raise HTTPException(status_code=404, detail="That passage is no longer in this source.")

    allowed = _whole_text_allowed(source, is_owner=expert.owner_id == user.id)
    whole_scope = whole and allowed
    return PassageWindowOut(
        source=PassageSourceOut.model_validate(source),
        scope="whole" if whole_scope else "window",
        whole_available=allowed,
        cited=around,
        passages=[_passage(row, previous=rows[i - 1] if i else None) for i, row in enumerate(rows)],
    )


def _passage(row: dict[str, Any], previous: dict[str, Any] | None) -> PassageOut:
    """One chunk, with the overlap sentence the chunker added taken back off.

    Each chunk after the first opens with the last sentence of the one before
    it, so that a referent survives the cut (`ingestion/chunker.py`). Read as
    running prose that sentence appears twice, so it is dropped — from the
    *later* chunk, and only when it really is the earlier one's tail.

    The chunker's own rule decides what counts as that tail, rather than a
    second implementation of it here: a one-sentence paragraph carried whole is
    a repeated paragraph, not overlap, and `last_sentence` already says so.
    """
    meta = decode_json_field(row.get("chunk_meta"), {}) or {}
    text = str(row["text"])
    if previous is not None:
        tail = last_sentence(str(previous["text"]))
        if tail and text.startswith(tail):
            text = text[len(tail) :].lstrip()
    section = meta.get("section")
    paragraph_n = meta.get("paragraph_n")
    return PassageOut(
        chunk_id=int(row["id"]),
        sequence_n=int(row["sequence_n"]),
        section=str(section) if section else None,
        paragraph_n=int(paragraph_n) if isinstance(paragraph_n, int) else None,
        text=text,
    )
