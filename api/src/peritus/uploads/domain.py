"""User-supplied sources — the payload a user hands the pipeline directly.

Discovery can only find what is publicly indexable. For many subjects that
excludes precisely the material that matters: anything still in copyright, plus
private notes, internal documents, and papers behind a login. The investing
expert that prompted this work was built almost entirely from reader reviews and
study guides because Graham and Fisher are not on Gutenberg — the user owns the
books, and there was no way to hand one over.

An upload is *trusted*. It is never quality-gated and never dropped: the owner
chose it deliberately, and telling someone their own book failed validation is
not a defensible thing for the product to do. It is still tagged, so it takes
part in concept coverage and gap-fill like anything else in the corpus.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

# What an upload is recorded as, so a citation can be traced to the person who
# supplied it. Mirrors `sources.discovered_via` (migration 012), which takes
# 'plan' | 'snowball' | 'gapfill:<concept>' for discovery-found material.
DISCOVERED_VIA_UPLOAD = "upload"

# Uploaded material is the work itself, not commentary on it — that is the whole
# reason to accept it. Recorded as primary so the tertiary-corpus warning
# (builder._corpus_tier_warning) counts it correctly.
UPLOAD_SOURCE_TIER = "primary"


class UploadKind(StrEnum):
    """How the payload arrived, which decides how text is extracted from it."""

    PDF = "pdf"      # raw bytes → Mistral OCR
    TEXT = "text"    # decoded text/markdown, already usable
    URL = "url"      # fetched and extracted at ingest time


@dataclass
class PendingUpload:
    """An accepted payload waiting for a worker to ingest it.

    Held in Postgres rather than memory because the worker is a different
    process from the request handler that accepted it. ``content`` and
    ``text_content`` are cleared once ingestion succeeds — the text lives on as
    chunks, and a second copy of every uploaded book would grow unbounded.
    """

    id: int
    expert_id: int
    owner_id: str | None
    kind: UploadKind
    title: str
    author: str | None = None
    filename: str | None = None
    url: str | None = None
    media_type: str | None = None
    byte_size: int | None = None
    content: bytes | None = None
    text_content: str | None = None
    created_at: datetime | None = None
