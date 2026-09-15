"""The screening ledger and the stored plan, against a real database.

"A rebuilt Thomism can be queried for every candidate triage saw, its score,
whether it was fetched and why not; the plan is on the expert."
(docs/plans/source-selection.md §4, done-when.)
"""

import json

import pytest

from peritus.experts.builder import ExpertBuilder
from peritus.experts.repository import ExpertRepository
from peritus.sources.domain import RawSource, SourceType, ValidatedSource

pytestmark = pytest.mark.asyncio


def _row(url: str, outcome: str, score: float, rank: int | None) -> dict:
    return {
        "round": 0,
        "source_type": "web",
        "url": url,
        "title": url.rsplit("/", 1)[-1],
        "discovered_via": "plan",
        "model_score": score,
        "domain_adjustment": 0.0,
        "triage_score": score,
        "triage_status": "scored",
        "fetch_rank": rank,
        "fetch_outcome": outcome,
    }


async def test_the_ledger_records_every_candidate_and_links_what_was_kept(db_pool):
    repo = ExpertRepository(db_pool)
    expert = await repo.create("thomism-ledger", "Thomism")
    await repo.update_research_plan(expert.id, {"must_have_works": [{"title": "Summa"}]})

    await repo.insert_candidate_screenings(
        expert.id,
        None,
        [
            _row("https://x.test/summa", "fetched", 9.0, 1),
            _row("https://x.test/tracie-thoms", "below_floor", 0.0, None),
        ],
    )

    source = ValidatedSource(
        raw=RawSource(
            SourceType.WEB, "https://x.test/summa", "Summa", None, "x" * 3000,
            metadata={"triage_score": 9.0, "full_text_method": "web_html"},
        ),
        quality_score=9, relevance_score=9, content_type="reference", difficulty=4,
        key_claims=[], source_tier="primary", substance="full",
    )
    builder = ExpertBuilder(db_pool)
    [source_id] = await builder._persist_sources(expert.id, [source], [])
    await repo.link_candidate_screenings(expert.id, None)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT title, fetch_outcome, triage_score, source_id FROM candidate_screenings "
            "WHERE expert_id = $1 ORDER BY triage_score DESC",
            expert.id,
        )
        stored = await conn.fetchrow(
            "SELECT triage_score, substance FROM sources WHERE id = $1", source_id
        )
        plan = await conn.fetchval("SELECT research_plan FROM experts WHERE id = $1", expert.id)

    assert [(r["title"], r["fetch_outcome"]) for r in rows] == [
        ("summa", "fetched"), ("tracie-thoms", "below_floor"),
    ]
    assert rows[0]["source_id"] == source_id
    assert rows[1]["source_id"] is None
    assert stored["triage_score"] == 9.0
    assert stored["substance"] == "full"
    plan = json.loads(plan) if isinstance(plan, str) else plan
    assert plan["must_have_works"][0]["title"] == "Summa"


async def test_a_retried_job_does_not_double_its_ledger(db_pool):
    repo = ExpertRepository(db_pool)
    expert = await repo.create("thomism-retry", "Thomism")
    await repo.insert_candidate_screenings(expert.id, None, [_row("https://x.test/a", "fetched", 8, 1)])
    await repo.clear_candidate_screenings(expert.id, None)
    await repo.insert_candidate_screenings(expert.id, None, [_row("https://x.test/a", "fetched", 8, 1)])

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM candidate_screenings WHERE expert_id = $1", expert.id
        )
    assert count == 1
