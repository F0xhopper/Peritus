"""Turn a pending upload into a :class:`RawSource` the ingestion pipeline accepts.

One entry point, :func:`extract`, dispatching on :class:`UploadKind`. Everything
downstream of here — chunking, contextualisation, embedding, graph extraction —
already works on ``RawSource`` and needs no knowledge that a human supplied it.

Every failure raises :class:`IngestionError` with a message written for the
person who uploaded the file, because that string is what the UI shows them. A
worker-shaped message ("NoneType has no attribute decode") is useless to someone
deciding whether to re-export their PDF.
"""

from peritus.core.exceptions import IngestionError
from peritus.core.logging import get_logger
from peritus.infrastructure.pdf_parser import parse_pdf_bytes
from peritus.sources.domain import RawSource, SourceCandidate, SourceType
from peritus.sources.fetchers.web import WebFetcher
from peritus.uploads.domain import PendingUpload, UploadKind

logger = get_logger(__name__)

# Below this many characters there is nothing worth embedding — a chunk or two of
# boilerplate that would dilute retrieval rather than inform it. Usually means a
# scanned PDF that OCR'd to nothing, or a URL that returned a cookie wall.
_MIN_USABLE_CHARS = 200

# Matches the ceiling the PDF fetcher applies to discovered documents. A very
# long book still ingests; it is simply truncated rather than allowed to run up
# an unbounded contextualisation and embedding bill in one job.
_MAX_CHARS = 500_000


async def extract(upload: PendingUpload) -> RawSource:
    """Extract text for one pending upload.

    Raises ``IngestionError`` with a user-facing message if the payload yields
    nothing usable.
    """
    match upload.kind:
        case UploadKind.PDF:
            text = await _extract_pdf(upload)
        case UploadKind.TEXT:
            text = _extract_text(upload)
        case UploadKind.URL:
            text = await _extract_url(upload)
        case _:  # pragma: no cover — the enum and the DB CHECK both exclude it
            raise IngestionError(f"Unsupported upload kind: {upload.kind}")

    text = text.strip()
    if len(text) < _MIN_USABLE_CHARS:
        raise IngestionError(
            f"Could only read {len(text)} characters from this "
            f"{_describe(upload.kind)} — too little to be useful. "
            "If it is a scanned document, check the scan is legible; if it is a "
            "web page, the site may require sign-in."
        )
    if len(text) > _MAX_CHARS:
        logger.info(
            "Upload %d truncated from %d to %d chars", upload.id, len(text), _MAX_CHARS
        )
        text = text[:_MAX_CHARS]

    return RawSource(
        source_type=SourceType.UPLOAD,
        # A file has no URL. The column is nullable, and an empty string keeps
        # citation rendering from printing a broken link.
        url=upload.url or "",
        title=upload.title,
        author=upload.author,
        text=text,
        metadata={
            "upload_id": upload.id,
            "upload_kind": str(upload.kind),
            "filename": upload.filename,
        },
    )


async def _extract_pdf(upload: PendingUpload) -> str:
    if not upload.content:
        raise IngestionError("The uploaded PDF was empty.")
    try:
        return await parse_pdf_bytes(upload.content)
    except Exception as exc:
        logger.warning("PDF extraction failed for upload %d: %s", upload.id, exc)
        raise IngestionError(
            "Could not read this PDF. It may be encrypted, corrupt, or larger "
            "than the 20 MB limit."
        ) from exc


def _extract_text(upload: PendingUpload) -> str:
    if upload.text_content is None:
        raise IngestionError("The uploaded file was empty.")
    return upload.text_content


async def _extract_url(upload: PendingUpload) -> str:
    if not upload.url:
        raise IngestionError("No URL was provided.")
    candidate = SourceCandidate(
        source_type=SourceType.WEB,
        url=upload.url,
        title=upload.title,
        author=upload.author,
        snippet="",
    )
    raw = await WebFetcher().fetch(candidate)
    if raw is None:
        raise IngestionError(
            "Could not fetch that page. It may be unreachable, or it may block "
            "automated readers."
        )
    return raw.text


def _describe(kind: UploadKind) -> str:
    return {
        UploadKind.PDF: "PDF",
        UploadKind.TEXT: "file",
        UploadKind.URL: "page",
    }.get(kind, "upload")


def decode_text_upload(data: bytes) -> str:
    """Decode an uploaded text/markdown file.

    ``utf-8-sig`` is tried *before* ``utf-8``, not after: plain UTF-8 decodes a
    byte-order mark quite happily into a leading U+FEFF, so trying it first
    means a BOM-prefixed file — which is what Windows editors produce — never
    reaches the sig codec and carries an invisible character into the first
    chunk of the document. On input without a BOM the two behave identically.

    The last resort is lossy rather than an error: a handful of mangled
    characters in a long document costs the user nothing, while refusing the
    upload costs them the document.
    """
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
