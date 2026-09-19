"""Persistence for found expert pictures (migration 027).

Separate from :class:`ExpertRepository` for the same reason the table is
separate from ``experts``: this is the only place that touches image bytes, and
keeping it apart makes "no list query ever selects the blob" a property you can
see rather than one you have to remember. ``ExpertRepository`` joins the
*metadata* columns onto its existing queries; :meth:`get_blob` is the one read
that returns bytes, and only the endpoint that serves them calls it.
"""

import json

import asyncpg

from peritus.experts.domain import ExpertPicture
from peritus.experts.picture import FoundPicture

# Every column except the blob and the shortlist. Shared with
# ``ExpertRepository`` so a new field is added in one place and appears on the
# list, detail and catalog responses at once.
PICTURE_COLUMNS: tuple[str, ...] = (
    "provider",
    "file_url",
    "file_page_url",
    "license",
    "sha256",
    "width",
    "height",
    "byte_size",
    "file_name",
    "page_url",
    "page_title",
    "artist",
    "license_url",
    "query",
    "chosen_by",
    "found_at",
)

# The projection a joined query selects, prefixed so nothing collides with a
# column of `experts` and `_row_to_expert` can tell the two apart by name.
PICTURE_JOIN_COLUMNS = ",\n    ".join(
    f"p.{column} AS picture_{column}" for column in PICTURE_COLUMNS
)


def picture_join(expert_alias: str = "e") -> str:
    """The LEFT JOIN clause. Left, because most experts have no picture yet."""
    return f"LEFT JOIN expert_pictures p ON p.expert_id = {expert_alias}.id"


def row_to_picture(row: asyncpg.Record, keys: set[str]) -> ExpertPicture | None:
    """Map the ``picture_*`` projection back, or None when the join missed.

    ``sha256`` is the presence test rather than any nullable column: it is NOT
    NULL in the table, so a null here can only mean "this expert has no row".
    """
    if "picture_sha256" not in keys or not row["picture_sha256"]:
        return None
    return ExpertPicture(**{column: row[f"picture_{column}"] for column in PICTURE_COLUMNS})


class ExpertPictureRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_blob(self, expert_id: int) -> tuple[bytes, str, str] | None:
        """``(image, content_type, sha256)`` — the only read that returns bytes."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT image, content_type, sha256 FROM expert_pictures WHERE expert_id = $1",
                expert_id,
            )
        if not row:
            return None
        return bytes(row["image"]), row["content_type"], row["sha256"]

    async def get(self, expert_id: int) -> ExpertPicture | None:
        """The metadata for one expert, without the bytes."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {', '.join(PICTURE_COLUMNS)} FROM expert_pictures WHERE expert_id = $1",
                expert_id,
            )
        if not row:
            return None
        return ExpertPicture(**{c: row[c] for c in PICTURE_COLUMNS})

    async def get_candidates(self, expert_id: int) -> list[dict]:
        """The shortlist this picture was chosen from (phase 2's picker reads it)."""
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                "SELECT candidates FROM expert_pictures WHERE expert_id = $1", expert_id
            )
        if isinstance(raw, str):
            raw = json.loads(raw)
        return list(raw) if raw else []

    async def exists(self, expert_id: int) -> bool:
        async with self._pool.acquire() as conn:
            return bool(
                await conn.fetchval("SELECT 1 FROM expert_pictures WHERE expert_id = $1", expert_id)
            )

    async def wikipedia_source_titles(self, expert_id: int, limit: int = 3) -> tuple[str, ...]:
        """Titles of this expert's validated Wikipedia sources, best first.

        Search hints for the finder. They exist only once a corpus does, which
        is why the build's first look — seconds in, off the plan — has none and
        its second look, and every refresh, does. The validator has already
        judged them relevant to *this* expert, so on a topic string that is
        vague or oddly phrased they are a much better search than the topic is.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT title
                FROM sources
                WHERE expert_id = $1 AND passed = true AND source_type = 'wikipedia'
                ORDER BY quality_score DESC NULLS LAST
                LIMIT $2
                """,
                expert_id,
                limit,
            )
        return tuple(r["title"] for r in rows if r["title"])

    async def upsert(
        self, expert_id: int, found: FoundPicture, chosen_by: str = "build"
    ) -> ExpertPicture:
        """Write (or replace) this expert's picture.

        An upsert rather than an insert because both paths that produce one —
        the build's finder and an owner's refresh — are re-runnable, and the
        primary key is the expert.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO expert_pictures (
                    expert_id, image, content_type, width, height, byte_size, sha256,
                    provider, file_name, file_url, file_page_url, page_url, page_title,
                    artist, license, license_url, query, candidates, chosen_by, found_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                        $14, $15, $16, $17, $18::jsonb, $19, NOW())
                ON CONFLICT (expert_id) DO UPDATE SET
                    image = EXCLUDED.image,
                    content_type = EXCLUDED.content_type,
                    width = EXCLUDED.width,
                    height = EXCLUDED.height,
                    byte_size = EXCLUDED.byte_size,
                    sha256 = EXCLUDED.sha256,
                    provider = EXCLUDED.provider,
                    file_name = EXCLUDED.file_name,
                    file_url = EXCLUDED.file_url,
                    file_page_url = EXCLUDED.file_page_url,
                    page_url = EXCLUDED.page_url,
                    page_title = EXCLUDED.page_title,
                    artist = EXCLUDED.artist,
                    license = EXCLUDED.license,
                    license_url = EXCLUDED.license_url,
                    query = EXCLUDED.query,
                    candidates = EXCLUDED.candidates,
                    chosen_by = EXCLUDED.chosen_by,
                    found_at = NOW()
                """,
                expert_id,
                found.image,
                found.content_type,
                found.width,
                found.height,
                found.byte_size,
                found.sha256,
                found.provider,
                found.file_name,
                found.file_url,
                found.file_page_url,
                found.page_url,
                found.page_title,
                found.artist,
                found.license,
                found.license_url,
                found.query,
                json.dumps(found.candidates),
                chosen_by,
            )
        return ExpertPicture(
            provider=found.provider,
            file_url=found.file_url,
            file_page_url=found.file_page_url,
            license=found.license,
            sha256=found.sha256,
            width=found.width,
            height=found.height,
            byte_size=found.byte_size,
            file_name=found.file_name,
            page_url=found.page_url,
            page_title=found.page_title,
            artist=found.artist,
            license_url=found.license_url,
            query=found.query,
            chosen_by=chosen_by,
        )

    async def delete(self, expert_id: int) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM expert_pictures WHERE expert_id = $1", expert_id
            )
        return result.rsplit(" ", 1)[-1] != "0"

    async def list_missing(self, limit: int = 100) -> list[tuple[int, str, str]]:
        """``(id, slug, topic)`` for experts with no picture — the backfill's worklist.

        Ordered oldest first so a paced backfill works through the catalog in a
        stable order and a re-run after an interruption picks up where it left
        off rather than reshuffling.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT e.id, e.name, e.topic
                FROM experts e
                LEFT JOIN expert_pictures p ON p.expert_id = e.id
                WHERE p.expert_id IS NULL
                ORDER BY e.created_at ASC
                LIMIT $1
                """,
                limit,
            )
        return [(r["id"], r["name"], r["topic"]) for r in rows]
