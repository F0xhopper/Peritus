"""Request/response models for user-supplied sources."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Matches the ceiling `infrastructure/pdf_parser` already enforces on a PDF, so a
# file that would fail OCR is refused at the door with a clear message rather
# than accepted, queued, and failed minutes later in a worker.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# Generous — a long book is legitimate — but bounded, since the whole payload is
# held in memory while it is read and written to Postgres.
MAX_TEXT_BYTES = 10 * 1024 * 1024

TITLE_MAX_CHARS = 300


class AddUrlRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2000)
    title: str | None = Field(None, max_length=TITLE_MAX_CHARS)
    author: str | None = Field(None, max_length=200)

    @field_validator("url")
    @classmethod
    def _must_be_http(cls, v: str) -> str:
        """Only http(s). Without this the fetcher would happily be pointed at
        ``file://`` or an internal address, turning an upload box into a
        server-side request forgery primitive."""
        v = v.strip()
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class SourceOut(BaseModel):
    """One source in an expert's corpus, with enough provenance for the UI to
    distinguish what the owner supplied from what discovery found."""

    id: int
    source_type: str
    url: str | None
    title: str
    author: str | None
    quality_score: float | None
    content_type: str | None
    discovered_via: str | None
    source_tier: str | None
    chunk_count: int
    created_at: datetime

    @property
    def is_user_supplied(self) -> bool:
        return self.discovered_via == "upload"


class UploadAcceptedOut(BaseModel):
    """Returned the moment a payload is durably stored and queued.

    ``job_id`` is what the client tails on ``/experts/{slug}/build/events`` —
    ingest progress rides the same event stream as a build.
    """

    upload_id: int
    job_id: int
    title: str
    kind: str
