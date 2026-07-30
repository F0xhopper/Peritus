"""Ingest one user-supplied document into an existing expert.

The body of an ``ingest_source`` job. Deliberately shaped like a very short
build — extract, tag, store, chunk/embed, graph — because that is what it is,
and because emitting the same event vocabulary means the SSE tail and the web
build log render an upload's progress without either of them changing.

What it is *not* is a build. It never touches ``experts.status``, never resets
build state, and never wipes anything. A failed ingest leaves the expert exactly
as it was, still answering questions from the corpus it already had.
"""

from typing import Any

import asyncpg

from peritus.core.config import settings
from peritus.core.exceptions import IngestionError
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.graph.extractor import extract_graph_from_chunks
from peritus.graph.repository import GraphRepository
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.infrastructure.embeddings import embed_in_batches
from peritus.ingestion.pipeline import ingest_sources
from peritus.sources.domain import RawSource, ValidatedSource
from peritus.uploads.extract import extract
from peritus.uploads.repository import UploadRepository

logger = get_logger(__name__)

_TAG_TOOL: dict[str, Any] = {
    "name": "tag_document",
    "description": "Describe an uploaded document so it fits the corpus index.",
    "input_schema": {
        "type": "object",
        "properties": {
            "content_type": {
                "type": "string",
                "enum": ["textbook", "paper", "tutorial", "reference",
                         "opinion", "transcript", "other"],
            },
            "difficulty": {
                "type": "integer",
                "description": "1 (introductory) to 5 (specialist).",
            },
            "key_claims": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3–5 substantive claims the document actually makes.",
            },
            "covered_concepts": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Which of the expert's key concepts this document covers. "
                    "Use the exact strings given; omit any it does not cover."
                ),
            },
        },
        "required": ["content_type", "difficulty", "key_claims", "covered_concepts"],
    },
}

# Note what this prompt does *not* ask for: a quality or relevance score. The
# document is already admitted. Asking a model to score it would invite the
# obvious next step of acting on the score, which is the behaviour this feature
# exists to avoid.
_TAG_SYSTEM = (
    "You are indexing a document that the owner of a subject-matter corpus has "
    "supplied themselves. It is already accepted — do not judge whether it "
    "belongs, and do not score it. Describe only what it contains, so retrieval "
    "and concept-coverage can place it correctly."
)

_TAG_PREVIEW_CHARS = 6000

# Tagging failure must not cost the user their document, so every failure path
# below degrades to this rather than raising.
_UNTAGGED: dict[str, Any] = {
    "content_type": "other",
    "difficulty": 3,
    "key_claims": [],
    "covered_concepts": [],
}


async def ingest_upload(
    pool: asyncpg.Pool,
    expert: Expert,
    upload_id: int,
    on_event: Any = None,
) -> dict[str, Any]:
    """Run the full ingest for one pending upload. Returns a summary dict.

    Raises ``IngestionError`` when the document yields nothing usable — the
    worker turns that into a failed job with the message shown to the user.
    """
    repo = UploadRepository(pool)
    upload = await repo.get(upload_id)
    if upload is None:
        raise IngestionError("This upload is no longer available.")

    async def emit(event: dict[str, Any]) -> None:
        if on_event:
            await on_event(event)

    # 1. Extract.
    await emit({"type": "stage", "stage": 1, "name": "extract",
                "message": f"Reading {upload.title}…"})
    raw = await extract(upload)
    await emit({"type": "upload_extracted", "title": raw.title, "chars": len(raw.text)})

    # 2. Tag. Never gates admission.
    await emit({"type": "stage", "stage": 2, "name": "tag",
                "message": "Indexing against the expert's concepts…"})
    tags = await _tag_document(raw, expert)

    # 3. The sources row.
    source_db_id = await repo.insert_source(
        expert_id=expert.id,
        source_type=raw.source_type.value,
        url=raw.url,
        title=raw.title,
        author=raw.author,
        content_type=tags["content_type"],
        difficulty=tags["difficulty"],
        key_claims=tags["key_claims"],
        covered_concepts=tags["covered_concepts"],
        uploaded_by=upload.owner_id,
    )

    # 4. Chunk → contextualise → embed → store. `ingest_sources` takes
    #    ValidatedSource; the scores on it are never read for an upload (the row
    #    above already stored NULLs), only `raw` is.
    await emit({"type": "stage", "stage": 3, "name": "embed",
                "message": "Chunking and embedding…"})
    validated = ValidatedSource(
        raw=raw,
        quality_score=0.0,
        relevance_score=0.0,
        content_type=tags["content_type"],
        difficulty=tags["difficulty"],
        key_claims=tags["key_claims"],
        covered_concepts=tags["covered_concepts"],
        source_tier="primary",
    )
    results = await ingest_sources([validated], expert.id, [source_db_id], pool)
    chunk_ids, chunks = results[0] if results else ([], [])
    if not chunk_ids:
        # The source row exists but nothing embedded — it would be invisible to
        # retrieval and would still inflate source_count. Remove it.
        await repo.delete_source(expert.id, source_db_id)
        raise IngestionError(
            "Nothing could be indexed from this document. It may contain no "
            "extractable text."
        )
    await emit({"type": "upload_embedded", "chunks": len(chunk_ids)})

    # 5. Graph. Best-effort: an expert whose new document is searchable but not
    #    yet in the concept graph is strictly better than a failed ingest, and
    #    the next rebuild will pick it up regardless.
    nodes = edges = 0
    if expert.graph_expanded:
        await emit({"type": "stage", "stage": 4, "name": "graph",
                    "message": "Extracting concepts…"})
        try:
            nodes, edges = await _extend_graph(pool, expert, chunks, chunk_ids)
        except Exception:
            logger.exception("Graph extension failed for upload %d", upload_id)
            await emit({"type": "graph_skipped",
                        "message": "Indexed, but concept extraction failed."})

    # 6. Counts, then drop the stored payload.
    await _bump_counts(pool, expert.id)
    await repo.clear_payload(upload_id)

    summary = {
        "source_id": source_db_id,
        "title": raw.title,
        "chunks": len(chunk_ids),
        "nodes": nodes,
        "edges": edges,
    }
    logger.info("Ingested upload %d into expert %d: %s", upload_id, expert.id, summary)
    return summary


async def _tag_document(raw: RawSource, expert: Expert) -> dict[str, Any]:
    """One fast-model call describing the document. Degrades to untagged."""
    if not settings.ANTHROPIC_API_KEY:
        return dict(_UNTAGGED)
    concepts = expert.key_concepts or []
    concept_block = (
        "The expert's key concepts:\n" + "\n".join(f"- {c}" for c in concepts) + "\n\n"
        if concepts else ""
    )
    try:
        client = get_anthropic_client()
        resp = await client.messages.create(  # type: ignore[call-overload]
            model=settings.FAST_MODEL,
            max_tokens=1024,
            system=_TAG_SYSTEM,
            tools=[_TAG_TOOL],
            tool_choice={"type": "tool", "name": "tag_document"},
            messages=[{
                "role": "user",
                "content": (
                    f"Corpus topic: {expert.topic}\n\n"
                    f"{concept_block}"
                    f"Document title: {raw.title}\n"
                    f"Opening text:\n{raw.text[:_TAG_PREVIEW_CHARS]}"
                ),
            }],
        )
        block = next(
            (b for b in resp.content if getattr(b, "type", None) == "tool_use"), None
        )
        if block is None:
            return dict(_UNTAGGED)
        data = dict(block.input)
        # Only concepts the expert actually declares may be recorded, or
        # coverage statistics start counting concepts nothing ever planned for.
        allowed = set(concepts)
        return {
            "content_type": data.get("content_type") or "other",
            "difficulty": int(data.get("difficulty") or 3),
            "key_claims": list(data.get("key_claims") or []),
            "covered_concepts": [
                c for c in (data.get("covered_concepts") or []) if c in allowed
            ],
        }
    except Exception as exc:
        logger.warning("Tagging failed for %r: %s", raw.title, exc)
        return dict(_UNTAGGED)


async def _extend_graph(
    pool: asyncpg.Pool,
    expert: Expert,
    chunks: list,
    chunk_ids: list[int],
) -> tuple[int, int]:
    """Extract concepts from the new chunks and merge them into the live graph.

    ``bulk_insert_from_extractions`` resolves an extracted label against the
    expert's existing nodes, so a document about something the corpus already
    covers deepens that concept rather than creating a rival copy of it. Only
    exact (case- and whitespace-normalised) label matches resolve here; merging
    near-duplicates needs embedding similarity and stays a build-time pass.
    """
    extractions = await extract_graph_from_chunks(expert.topic, chunks, chunk_ids)
    return await GraphRepository(pool).bulk_insert_from_extractions(
        expert.id, extractions, embedder=embed_in_batches
    )


async def _bump_counts(pool: asyncpg.Pool, expert_id: int) -> None:
    """Recount from the tables rather than incrementing.

    An increment drifts the moment anything else touches the corpus — a delete, a
    concurrent ingest, a partially-failed source. These counts are what the
    catalog and the expert page display, so they are cheap to recompute and
    expensive to have wrong.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE experts SET
                source_count = (SELECT COUNT(*) FROM sources
                                WHERE expert_id = $1 AND passed = true),
                chunk_count  = (SELECT COUNT(*) FROM source_chunks WHERE expert_id = $1),
                node_count   = (SELECT COUNT(*) FROM expert_nodes  WHERE expert_id = $1),
                edge_count   = (SELECT COUNT(*) FROM expert_edges  WHERE expert_id = $1),
                updated_at   = NOW()
            WHERE id = $1
            """,
            expert_id,
        )


def summary_event(summary: dict[str, Any]) -> dict[str, Any]:
    """The terminal ``done`` event for an ingest job.

    Shares the ``done`` type with a build so a client tailing the event stream
    stops cleanly without needing to know which kind of job it was watching.
    """
    return {"type": "done", "kind": "ingest_source", **summary}
