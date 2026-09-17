"""DB-backed tests for the passage window.

A window is a range over `sequence_n` found from a chunk *id*, and the two
things a mock cannot check are that the range is clipped at the ends of a source
and that a chunk belonging to another source is not found. Requires
PERITUS_TEST_DATABASE_URL; skips otherwise via the db_pool fixture.
"""

import pytest

from peritus.experts.domain import ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.uploads.repository import UploadRepository

OWNER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


async def _expert(db_pool, name="beekeeping"):
    return await ExpertRepository(db_pool).create(
        name=name, topic=name, tier=ExpertTier.LITE, owner_id=OWNER
    )


async def _source_with_chunks(db_pool, expert_id, count, title="A source", source_type="web"):
    async with db_pool.acquire() as conn:
        source_id = await conn.fetchval(
            """
            INSERT INTO sources (expert_id, source_type, url, title, passed, full_text_method)
            VALUES ($1, $2, $3, $4, true, 'full_text') RETURNING id
            """,
            expert_id,
            source_type,
            f"https://example.org/{title}",
            title,
        )
        ids = []
        for n in range(count):
            ids.append(
                await conn.fetchval(
                    """
                    INSERT INTO source_chunks
                        (expert_id, source_id, sequence_n, text, chunk_meta)
                    VALUES ($1, $2, $3, $4, $5::jsonb) RETURNING id
                    """,
                    expert_id,
                    source_id,
                    n,
                    f"Paragraph {n}.",
                    f'{{"section": "One", "paragraph_n": {n + 1}}}',
                )
            )
    return source_id, ids


@pytest.mark.asyncio
async def test_a_window_is_centred_on_the_cited_chunk(db_pool):
    expert = await _expert(db_pool)
    source_id, ids = await _source_with_chunks(db_pool, expert.id, 9)
    repo = UploadRepository(db_pool)

    source, rows = await repo.passage_window(expert.id, source_id, around=ids[4], before=2, after=2)

    assert source is not None and source["passage_count"] == 9
    assert [r["sequence_n"] for r in rows] == [2, 3, 4, 5, 6]


@pytest.mark.asyncio
async def test_a_window_at_the_start_or_end_is_clipped_not_wrapped(db_pool):
    expert = await _expert(db_pool)
    source_id, ids = await _source_with_chunks(db_pool, expert.id, 4)
    repo = UploadRepository(db_pool)

    _, first = await repo.passage_window(expert.id, source_id, around=ids[0], before=2, after=2)
    _, last = await repo.passage_window(expert.id, source_id, around=ids[-1], before=2, after=2)

    assert [r["sequence_n"] for r in first] == [0, 1, 2]
    assert [r["sequence_n"] for r in last] == [1, 2, 3]


@pytest.mark.asyncio
async def test_a_wide_enough_window_is_the_whole_source(db_pool):
    expert = await _expert(db_pool)
    source_id, ids = await _source_with_chunks(db_pool, expert.id, 12)
    repo = UploadRepository(db_pool)

    _, rows = await repo.passage_window(expert.id, source_id, around=ids[3], before=500, after=500)

    assert len(rows) == 12


@pytest.mark.asyncio
async def test_a_chunk_from_another_source_is_not_found(db_pool):
    # What a citation from before a re-ingest looks like: the source is there,
    # the chunk is not. The route turns this into a 404 rather than a window
    # centred on something arbitrary.
    expert = await _expert(db_pool)
    wanted, _ = await _source_with_chunks(db_pool, expert.id, 3, title="Wanted")
    _, other_ids = await _source_with_chunks(db_pool, expert.id, 3, title="Other")

    source, rows = await UploadRepository(db_pool).passage_window(
        expert.id, wanted, around=other_ids[0], before=2, after=2
    )
    assert source is not None
    assert rows == []


@pytest.mark.asyncio
async def test_a_source_from_another_expert_is_not_readable(db_pool):
    mine = await _expert(db_pool, name="mine")
    theirs = await _expert(db_pool, name="theirs")
    source_id, ids = await _source_with_chunks(db_pool, theirs.id, 3)

    source, rows = await UploadRepository(db_pool).passage_window(
        mine.id, source_id, around=ids[0], before=2, after=2
    )
    assert source is None and rows == []
