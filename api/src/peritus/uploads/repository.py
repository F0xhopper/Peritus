"""Persistence for user-supplied sources.

Two responsibilities that stay together because they are two ends of one
handover: storing a payload the request handler accepted, and reading it back in
the worker that ingests it.
"""

import json
from typing import Any

import asyncpg

from peritus.uploads.domain import (
    DISCOVERED_VIA_UPLOAD,
    UPLOAD_SOURCE_TIER,
    PendingUpload,
    UploadKind,
)


class UploadRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(
        self,
        expert_id: int,
        owner_id: str | None,
        kind: UploadKind,
        title: str,
        author: str | None = None,
        filename: str | None = None,
        url: str | None = None,
        media_type: str | None = None,
        content: bytes | None = None,
        text_content: str | None = None,
    ) -> PendingUpload:
        byte_size = (
            len(content)
            if content is not None
            else len(text_content.encode())
            if text_content is not None
            else None
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO source_uploads
                    (expert_id, owner_id, kind, title, author, filename, url,
                     media_type, byte_size, content, text_content)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                RETURNING *
                """,
                expert_id,
                owner_id,
                str(kind),
                title,
                author,
                filename,
                url,
                media_type,
                byte_size,
                content,
                text_content,
            )
        return _row_to_upload(row)

    async def get(self, upload_id: int) -> PendingUpload | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM source_uploads WHERE id = $1", upload_id)
        return _row_to_upload(row) if row else None

    async def clear_payload(self, upload_id: int) -> None:
        """Drop the stored bytes once the text has become chunks.

        The row itself stays: it is the record that this expert's corpus contains
        something a person supplied, and what its filename was. Only the payload
        goes, because keeping a copy of every uploaded book alongside its chunks
        would double the storage for no read that anything performs.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE source_uploads
                SET content = NULL, text_content = NULL, cleared_at = NOW()
                WHERE id = $1
                """,
                upload_id,
            )

    async def delete(self, upload_id: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM source_uploads WHERE id = $1", upload_id)

    # ── the sources row an ingested upload becomes ──────────────────────────

    async def insert_source(
        self,
        expert_id: int,
        source_type: str,
        url: str,
        title: str,
        author: str | None,
        content_type: str,
        difficulty: int,
        key_claims: list[str],
        covered_concepts: list[str],
        uploaded_by: str | None,
    ) -> int:
        """Insert the ``sources`` row for an upload and return its id.

        ``quality_score`` and ``relevance_score`` are deliberately left NULL
        rather than given a flattering number. The upload was never scored, and
        writing a 10 would corrupt ``experts.avg_quality`` and the source-quality
        column in the audit trail with a judgement nothing actually made.
        ``passed`` is unconditionally true — an upload is not admitted on merit.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO sources
                    (expert_id, source_type, url, title, author,
                     content_type, difficulty, key_claims, passed,
                     covered_concepts, discovered_via, source_tier, uploaded_by)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,true,$9::jsonb,$10,$11,$12)
                RETURNING id
                """,
                expert_id,
                source_type,
                url,
                title,
                author,
                content_type,
                difficulty,
                json.dumps(key_claims),
                json.dumps(covered_concepts),
                DISCOVERED_VIA_UPLOAD,
                UPLOAD_SOURCE_TIER,
                uploaded_by,
            )
        return row["id"]

    async def list_sources(self, expert_id: int) -> list[dict[str, Any]]:
        """Every passing source for an expert, newest first, with its provenance.

        Powers the UI's source list, where the point is to let the owner see what
        they supplied apart from what discovery found.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.id, s.source_type, s.url, s.title, s.author,
                       s.quality_score, s.content_type, s.discovered_via,
                       s.source_tier, s.uploaded_by, s.created_at,
                       COUNT(c.id) AS chunk_count
                FROM sources s
                LEFT JOIN source_chunks c ON c.source_id = s.id
                WHERE s.expert_id = $1 AND s.passed = true
                GROUP BY s.id
                ORDER BY s.created_at DESC, s.id DESC
                """,
                expert_id,
            )
        return [dict(r) for r in rows]

    async def passage_window(
        self, expert_id: int, source_id: int, around: int | None, before: int, after: int
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """A source, and the chunks either side of one of its chunks.

        Two queries rather than one: the cited chunk's ``sequence_n`` is not
        known to the caller — a citation carries a chunk id — and a window is a
        range over that ordering. ``(None, [])`` when the chunk is not in that
        source, which is what a citation from before a re-ingest looks like.

        The whole source is a legitimate window: the largest source in the
        database is 165 chunks, so ``before``/``after`` bound the response for
        the panel's sake, not the database's.
        """
        async with self._pool.acquire() as conn:
            source = await conn.fetchrow(
                """
                SELECT s.id, s.title, s.author, s.url, s.source_type,
                       s.full_text_method, s.text_chars,
                       COUNT(c.id)::int AS passage_count
                FROM sources s
                LEFT JOIN source_chunks c ON c.source_id = s.id
                WHERE s.id = $1 AND s.expert_id = $2 AND s.passed = true
                GROUP BY s.id
                """,
                source_id,
                expert_id,
            )
            if source is None:
                return None, []

            centre = (
                await conn.fetchval(
                    """
                SELECT sequence_n FROM source_chunks
                WHERE id = $1 AND source_id = $2 AND expert_id = $3
                """,
                    around,
                    source_id,
                    expert_id,
                )
                if around is not None
                else await conn.fetchval(
                    """
                SELECT MIN(sequence_n) FROM source_chunks
                WHERE source_id = $1 AND expert_id = $2
                """,
                    source_id,
                    expert_id,
                )
            )
            if centre is None:
                return dict(source), []

            rows = await conn.fetch(
                """
                SELECT id, sequence_n, text, chunk_meta
                FROM source_chunks
                WHERE expert_id = $1 AND source_id = $2
                  AND sequence_n BETWEEN $3 AND $4
                ORDER BY sequence_n
                """,
                expert_id,
                source_id,
                centre - before,
                centre + after,
            )
        return dict(source), [dict(r) for r in rows]

    async def delete_source(self, expert_id: int, source_id: int) -> bool:
        """Remove a source and everything derived from it. Returns False if absent.

        Chunks cascade from ``sources``. Graph nodes are not deleted: a concept
        can be anchored in several sources, and unpicking one source's
        contribution from a merged node is not something the schema supports.
        The node's ``chunk_ids`` simply stop resolving for the deleted chunks,
        which the retriever already tolerates.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            result = await conn.execute(
                "DELETE FROM sources WHERE id = $1 AND expert_id = $2",
                source_id,
                expert_id,
            )
            if result.endswith(" 0"):
                return False
            await conn.execute(
                """
                UPDATE experts SET
                    source_count = GREATEST(source_count - 1, 0),
                    chunk_count = (SELECT COUNT(*) FROM source_chunks WHERE expert_id = $1),
                    updated_at = NOW()
                WHERE id = $1
                """,
                expert_id,
            )
        return True


def _row_to_upload(row: asyncpg.Record) -> PendingUpload:
    return PendingUpload(
        id=row["id"],
        expert_id=row["expert_id"],
        owner_id=row["owner_id"],
        kind=UploadKind(row["kind"]),
        title=row["title"],
        author=row["author"],
        filename=row["filename"],
        url=row["url"],
        media_type=row["media_type"],
        byte_size=row["byte_size"],
        content=row["content"],
        text_content=row["text_content"],
        created_at=row["created_at"],
    )
