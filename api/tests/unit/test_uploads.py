"""Unit tests for user-supplied source ingestion.

Pure and offline: extraction dispatch, decoding, and the job-type plumbing. The
network-touching paths (Mistral OCR, the web fetcher) are stubbed — what is under
test is that the right extractor is chosen and that failures come back as
messages a person could act on.
"""

import pytest

from peritus.core.exceptions import IngestionError
from peritus.jobs.domain import BuildJob, JobStatus, JobType
from peritus.sources.domain import SourceType
from peritus.uploads import extract as extract_mod
from peritus.uploads.domain import (
    DISCOVERED_VIA_UPLOAD,
    UPLOAD_SOURCE_TIER,
    PendingUpload,
    UploadKind,
)
from peritus.uploads.extract import decode_text_upload, extract


def _upload(kind: UploadKind, **kw) -> PendingUpload:
    return PendingUpload(
        id=1, expert_id=7, owner_id="user-1", kind=kind,
        title=kw.pop("title", "A Document"), **kw,
    )


# ── text decoding ───────────────────────────────────────────────────────────

def test_decode_prefers_utf8():
    assert decode_text_upload("margin of safety — Graham".encode()) == (
        "margin of safety — Graham"
    )


def test_decode_strips_utf8_bom():
    """Windows editors emit a BOM. Plain UTF-8 decodes it into a leading U+FEFF
    rather than failing, so the sig codec has to be tried first or an invisible
    character rides into the first chunk of every such document."""
    assert decode_text_upload(b"\xef\xbb\xbfhello") == "hello"
    assert "﻿" not in decode_text_upload("hello".encode("utf-8-sig"))


def test_decode_falls_back_to_cp1252():
    # 0x92 is a curly apostrophe in cp1252 and invalid UTF-8.
    assert decode_text_upload(b"Graham\x92s rule") == "Graham’s rule"


def test_decode_never_raises_on_binary():
    """Lossy beats refusing the document — a few mangled characters in a long
    file cost the user nothing; a hard failure costs them the upload."""
    assert isinstance(decode_text_upload(bytes(range(256))), str)


# ── extraction dispatch ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_text_returns_raw_source():
    body = "Margin of safety means buying below intrinsic value. " * 20
    raw = await extract(_upload(UploadKind.TEXT, text_content=body))
    assert raw.source_type is SourceType.UPLOAD
    assert raw.title == "A Document"
    assert raw.text.startswith("Margin of safety")
    assert raw.metadata["upload_id"] == 1


@pytest.mark.asyncio
async def test_extract_rejects_content_too_short_to_use():
    with pytest.raises(IngestionError, match="too little to be useful"):
        await extract(_upload(UploadKind.TEXT, text_content="hi"))


@pytest.mark.asyncio
async def test_extract_truncates_a_very_long_document():
    body = "x" * (extract_mod._MAX_CHARS + 5_000)
    raw = await extract(_upload(UploadKind.TEXT, text_content=body))
    assert len(raw.text) == extract_mod._MAX_CHARS


@pytest.mark.asyncio
async def test_extract_pdf_uses_the_ocr_parser(monkeypatch):
    seen: dict = {}

    async def fake_parse(data: bytes) -> str:
        seen["bytes"] = data
        return "Extracted book text. " * 40

    monkeypatch.setattr(extract_mod, "parse_pdf_bytes", fake_parse)
    raw = await extract(_upload(UploadKind.PDF, content=b"%PDF-1.7 fake"))
    assert seen["bytes"] == b"%PDF-1.7 fake"
    assert raw.text.startswith("Extracted book text.")


@pytest.mark.asyncio
async def test_extract_pdf_failure_is_user_facing(monkeypatch):
    """The raised message reaches the UI, so it must mean something to a person."""
    async def boom(data: bytes) -> str:
        raise RuntimeError("HTTP 502 from ocr backend")

    monkeypatch.setattr(extract_mod, "parse_pdf_bytes", boom)
    with pytest.raises(IngestionError) as exc:
        await extract(_upload(UploadKind.PDF, content=b"%PDF"))
    assert "encrypted, corrupt" in str(exc.value)
    assert "502" not in str(exc.value)


@pytest.mark.asyncio
async def test_extract_url_reports_an_unfetchable_page(monkeypatch):
    class _Fetcher:
        async def fetch(self, candidate):
            return None

    monkeypatch.setattr(extract_mod, "WebFetcher", _Fetcher)
    with pytest.raises(IngestionError, match="Could not fetch that page"):
        await extract(_upload(UploadKind.URL, url="https://example.test/a"))


@pytest.mark.asyncio
async def test_extract_url_uses_the_fetched_text(monkeypatch):
    class _Raw:
        text = "A long article about value investing. " * 20

    class _Fetcher:
        async def fetch(self, candidate):
            assert candidate.url == "https://example.test/a"
            return _Raw()

    monkeypatch.setattr(extract_mod, "WebFetcher", _Fetcher)
    raw = await extract(_upload(UploadKind.URL, url="https://example.test/a"))
    assert raw.url == "https://example.test/a"
    assert "value investing" in raw.text


@pytest.mark.asyncio
async def test_extract_pdf_has_no_url():
    """A file has no address. Empty, not a broken link, so citation rendering
    does not produce one."""
    async def fake_parse(data: bytes) -> str:
        return "Book text. " * 40

    import peritus.uploads.extract as m
    m.parse_pdf_bytes = fake_parse
    raw = await extract(_upload(UploadKind.PDF, content=b"%PDF"))
    assert raw.url == ""


# ── provenance constants ────────────────────────────────────────────────────

def test_upload_provenance_is_primary_and_marked():
    """Uploaded material is the work itself, and the tertiary-corpus warning
    counts on it being recorded that way."""
    assert DISCOVERED_VIA_UPLOAD == "upload"
    assert UPLOAD_SOURCE_TIER == "primary"


# ── job typing ──────────────────────────────────────────────────────────────

def _job(**kw) -> BuildJob:
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    base = dict(
        id=1, expert_id=7, status=JobStatus.QUEUED, tier="standard",
        source_filter=None, attempts=0, max_attempts=3, available_at=now,
        locked_by=None, heartbeat_at=None, last_error=None,
        created_at=now, updated_at=now,
    )
    base.update(kw)
    return BuildJob(**base)


def test_job_defaults_to_build_so_pre_migration_rows_read_correctly():
    assert _job().job_type is JobType.BUILD
    assert _job().is_build is True
    assert _job().payload is None


def test_ingest_job_carries_its_upload():
    job = _job(job_type=JobType.INGEST_SOURCE, payload={"upload_id": 42})
    assert job.is_build is False
    assert job.payload["upload_id"] == 42
