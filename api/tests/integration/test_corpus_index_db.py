"""DB-backed: structural tails, the section index, and routing a broad question.

What a mock cannot check is the SQL: that held chunks land with their notes and
loci, that the section index groups and stores runs, that ``search_sections``
takes one section per source, and that ``best_in_spans`` stays inside each span.
Embeddings and the summariser are stubbed. Requires PERITUS_TEST_DATABASE_URL.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from peritus.core.config import settings
from peritus.experts.domain import ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.ingestion.structural import TailWork, ingest_tails
from peritus.ingestion.summaries import build_section_index, search_sections
from peritus.search.service import SearchService

OWNER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_PROSE = (
    "It seems that the soul is a body, for the soul is the moving principle of the body, and "
    "nothing moves unless it is moved. But the contrary is true of the thing as it is. "
)


def _vector(seed: float) -> list[float]:
    v = [0.0] * settings.EMBED_DIM
    v[0], v[1] = 1.0, seed
    return v


async def _fake_embed(texts):
    # Soul texts point one way, everything else another.
    return [_vector(1.0 if "soul" in t.casefold() else -1.0) for t in texts]


async def _fake_summaries(params_list, **_kwargs):
    return [
        SimpleNamespace(content=[SimpleNamespace(text="On the soul and its powers.")])
        for _ in params_list
    ]


async def _setup(db_pool):
    expert = await ExpertRepository(db_pool).create(
        name="thomism", topic="Thomism", tier=ExpertTier.STANDARD, owner_id=OWNER
    )
    async with db_pool.acquire() as conn:
        source_id = await conn.fetchval(
            """
            INSERT INTO sources (expert_id, source_type, url, title, passed, full_text_method)
            VALUES ($1, 'gutenberg', 'https://g/1', 'Summa Theologica, Part I', true,
                    'gutenberg_text') RETURNING id
            """,
            expert.id,
        )
    return expert, source_id


@pytest.mark.asyncio
async def test_a_tail_is_held_indexed_and_routed(db_pool):
    expert, source_id = await _setup(db_pool)
    close = "Front matter.\n\n" + _PROSE * 5
    tail = "".join(
        f"\nQUESTION {n}\nOF {'THE SOUL' if n % 2 else 'THE ANGELS'}\n\n"
        f"FIRST ARTICLE [I, Q. {n}, Art. 1]\n\nWhether it is so?\n\n{_PROSE * 12}\n"
        for n in range(75, 81)
    )
    full = close + tail
    with patch("peritus.ingestion.structural.embed_in_batches", _fake_embed):
        report = await ingest_tails(
            db_pool,
            expert.id,
            [TailWork(source_id, "Summa Theologica, Part I", full, [(0, len(close))], 0)],
            ["The soul"],
            budget_chars=len(tail),
        )
    assert report.chunks > 0 and report.works == 1
    rows = await db_pool.fetch(
        "SELECT sequence_n, context_text, chunk_meta FROM source_chunks WHERE expert_id = $1 "
        "ORDER BY sequence_n",
        expert.id,
    )
    metas = [json.loads(r["chunk_meta"]) for r in rows]
    assert all(m["ingest"] == "structural" for m in metas)
    assert any(m.get("locus", "").startswith("I, q. 7") for m in metas)
    assert rows[0]["context_text"].startswith("From Summa Theologica, Part I")

    with (
        patch("peritus.ingestion.summaries.gather_claude_calls", _fake_summaries),
        patch("peritus.ingestion.summaries.embed_in_batches", _fake_embed),
    ):
        written = await build_section_index(db_pool, expert.id)
        again = await build_section_index(db_pool, expert.id)
    assert written > 0 and again == 0  # idempotent per source

    hits = await search_sections(db_pool, expert.id, [_vector(1.0)], k=3)
    assert len(hits) == 1 and hits[0].source_id == source_id  # one per source

    spans = [(source_id, hits[0].seq_start, hits[0].seq_end)]
    [found] = await SearchService(db_pool).best_in_spans(expert.id, spans, _vector(1.0), 2)
    assert 1 <= len(found) <= 2
    assert all(hits[0].seq_start <= r.sequence_n <= hits[0].seq_end for r in found)
