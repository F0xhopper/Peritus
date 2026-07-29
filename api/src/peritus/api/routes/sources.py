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
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from peritus.api.auth import AuthUser, require_user
from peritus.api.schemas.sources import (
    MAX_TEXT_BYTES,
    MAX_UPLOAD_BYTES,
    TITLE_MAX_CHARS,
    AddUrlRequest,
    SourceOut,
    UploadAcceptedOut,
)
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.experts.repository import ExpertRepository
from peritus.infrastructure.database import get_pool
from peritus.jobs.domain import JobType
from peritus.jobs.repository import JobRepository
from peritus.uploads.domain import UploadKind
from peritus.uploads.extract import decode_text_upload
from peritus.uploads.repository import UploadRepository

logger = get_logger(__name__)

router = APIRouter(prefix="/experts", tags=["sources"])

# Extensions accepted as plain text. Anything else with a text-ish media type is
# still accepted — the extension list is a hint for the error message, not the
# gate — but these are what the UI advertises.
_TEXT_SUFFIXES = (".txt", ".md", ".markdown", ".text")
_PDF_SUFFIXES = (".pdf",)


async def _owned_expert(slug: str, user: AuthUser) -> Expert:
    """Resolve an expert the caller may *mutate*, or 404.

    404 rather than 403 for anything out of scope, matching the rest of the API:
    an expert's existence is not disclosed to someone who cannot act on it.
    """
    expert = await ExpertRepository(get_pool()).get_owned_for_user(
        slug, user.id, include_unowned=user.is_admin
    )
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    return expert


async def _guard_no_active_build(expert: Expert) -> None:
    """Refuse an ingest while a build is running.

    A build wipes and re-fetches the corpus underneath. Uploads survive that
    (``reset_build_state``), but a document landing *mid-build* could be ingested
    after the reset and before the graph stage, or after the graph stage and
    never reach the graph at all. Making the user wait is far better than either.
    """
    active = await JobRepository(get_pool()).get_active_job(
        expert.id, job_type=JobType.BUILD
    )
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="This expert is building. Add sources once the build finishes.",
        )


async def _queue(expert: Expert, upload_id: int, title: str, kind: UploadKind) -> int:
    job = await JobRepository(get_pool()).enqueue(
        expert_id=expert.id,
        tier=str(expert.tier),
        source_filter=None,
        max_attempts=settings.WORKER_MAX_ATTEMPTS,
        job_type=JobType.INGEST_SOURCE,
        payload={"upload_id": upload_id},
    )
    logger.info(
        "Queued ingest job %d for expert %d (upload=%d, kind=%s)",
        job.id, expert.id, upload_id, kind,
    )
    return job.id


def _clean_title(raw: str | None, fallback: str) -> str:
    title = (raw or "").strip() or fallback
    return title[:TITLE_MAX_CHARS]


@router.post("/{slug}/sources/upload", response_model=UploadAcceptedOut, status_code=202)
async def upload_source(
    slug: str,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    author: str | None = Form(None),
    user: AuthUser = Depends(require_user),
) -> UploadAcceptedOut:
    """Accept a PDF or text/markdown file and queue it for ingestion.

    202, not 201: the source does not exist yet. What exists is a durable
    payload and a queued job, and the response says which job to watch.
    """
    expert = await _owned_expert(slug, user)
    await _guard_no_active_build(expert)

    filename = (file.filename or "").strip()
    lowered = filename.lower()
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    repo = UploadRepository(get_pool())
    resolved_title = _clean_title(title, filename or "Untitled upload")

    if lowered.endswith(_PDF_SUFFIXES) or file.content_type == "application/pdf":
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"PDF is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
            )
        upload = await repo.create(
            expert_id=expert.id, owner_id=user.id, kind=UploadKind.PDF,
            title=resolved_title, author=author, filename=filename or None,
            media_type=file.content_type, content=data,
        )
        kind = UploadKind.PDF
    elif lowered.endswith(_TEXT_SUFFIXES) or (file.content_type or "").startswith("text/"):
        if len(data) > MAX_TEXT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File is larger than the {MAX_TEXT_BYTES // (1024 * 1024)} MB limit.",
            )
        upload = await repo.create(
            expert_id=expert.id, owner_id=user.id, kind=UploadKind.TEXT,
            title=resolved_title, author=author, filename=filename or None,
            media_type=file.content_type, text_content=decode_text_upload(data),
        )
        kind = UploadKind.TEXT
    else:
        raise HTTPException(
            status_code=415,
            detail="Only PDF, .txt and .md files can be uploaded. For a web page, use the URL field.",
        )

    job_id = await _queue(expert, upload.id, resolved_title, kind)
    return UploadAcceptedOut(
        upload_id=upload.id, job_id=job_id, title=resolved_title, kind=str(kind)
    )


@router.post("/{slug}/sources/url", response_model=UploadAcceptedOut, status_code=202)
async def add_url_source(
    slug: str,
    req: AddUrlRequest,
    user: AuthUser = Depends(require_user),
) -> UploadAcceptedOut:
    """Accept a web page by URL and queue it for ingestion.

    The page is fetched in the worker, not here: a slow or hanging site must not
    hold an HTTP request open, and a fetch failure should land in the job's event
    log next to everything else about that document.
    """
    expert = await _owned_expert(slug, user)
    await _guard_no_active_build(expert)

    title = _clean_title(req.title, req.url)
    upload = await UploadRepository(get_pool()).create(
        expert_id=expert.id, owner_id=user.id, kind=UploadKind.URL,
        title=title, author=req.author, url=req.url,
    )
    job_id = await _queue(expert, upload.id, title, UploadKind.URL)
    return UploadAcceptedOut(
        upload_id=upload.id, job_id=job_id, title=title, kind=str(UploadKind.URL)
    )


@router.get("/{slug}/sources", response_model=list[SourceOut])
async def list_sources(
    slug: str, user: AuthUser = Depends(require_user)
) -> list[SourceOut]:
    """Every source in this expert's corpus, newest first.

    Owner-scoped like the mutations rather than read-scoped like the audit
    routes: this list is the management view that the delete button acts on, and
    the audit surface already serves the public "what is this made of" question.
    """
    expert = await _owned_expert(slug, user)
    rows = await UploadRepository(get_pool()).list_sources(expert.id)
    return [SourceOut(**r) for r in rows]


@router.delete("/{slug}/sources/{source_id}", status_code=204)
async def delete_source(
    slug: str, source_id: int, user: AuthUser = Depends(require_user)
) -> None:
    """Remove a source and its chunks from the corpus.

    Applies to any source, not only uploads: a build that pulled in something the
    owner does not want their expert citing should be correctable without a full
    rebuild.
    """
    expert = await _owned_expert(slug, user)
    removed = await UploadRepository(get_pool()).delete_source(expert.id, source_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Source not found")
    logger.info("Deleted source %d from expert %d", source_id, expert.id)
