"""User-supplied sources against a real DB.

Needs PERITUS_TEST_DATABASE_URL (skips otherwise).

The invariant most worth pinning here is that a rebuild does **not** destroy
uploaded material. It is the one part of a corpus the pipeline cannot
reconstruct — usually the whole reason it was uploaded — and the delete that
would lose it lives in a method whose entire job is wiping the corpus.
"""

import pytest

from peritus.experts.domain import ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.jobs.domain import JobStatus, JobType
from peritus.jobs.repository import JobRepository
from peritus.uploads.domain import UploadKind
from peritus.uploads.repository import UploadRepository

pytestmark = pytest.mark.asyncio


async def _expert(pool, name: str):
    return await ExpertRepository(pool).create(
        name=name, topic=name, tier=ExpertTier.LITE
    )


async def _source(pool, expert_id: int, title: str, *, upload: bool) -> int:
    """Insert a passing source, as either an upload or a discovery find."""
    repo = UploadRepository(pool)
    if upload:
        return await repo.insert_source(
            expert_id=expert_id, source_type="upload", url="", title=title,
            author=None, content_type="textbook", difficulty=3,
            key_claims=["a claim"], covered_concepts=[], uploaded_by="user-1",
        )
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO sources (expert_id, source_type, url, title, passed,
                                 discovered_via, quality_score, relevance_score)
            VALUES ($1, 'web', 'https://e.test/x', $2, true, 'plan', 8.0, 8.0)
            RETURNING id
            """,
            expert_id, title,
        )
    return row["id"]


async def _chunk(pool, expert_id: int, source_id: int, n: int = 0) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO source_chunks (expert_id, source_id, sequence_n, text, chunk_meta)
            VALUES ($1, $2, $3, 'chunk text', '{}'::jsonb)
            RETURNING id
            """,
            expert_id, source_id, n,
        )
    return row["id"]


# ── the rebuild invariant ───────────────────────────────────────────────────

async def test_rebuild_preserves_uploads_and_wipes_discovered(db_pool):
    expert = await _expert(db_pool, "reset-preserve")
    uploaded = await _source(db_pool, expert.id, "My Book", upload=True)
    found = await _source(db_pool, expert.id, "Some Blog", upload=False)
    await _chunk(db_pool, expert.id, uploaded)
    await _chunk(db_pool, expert.id, found)

    await ExpertRepository(db_pool).reset_build_state(expert.id)

    async with db_pool.acquire() as conn:
        ids = [r["id"] for r in await conn.fetch(
            "SELECT id FROM sources WHERE expert_id = $1", expert.id
        )]
        chunk_sources = [r["source_id"] for r in await conn.fetch(
            "SELECT source_id FROM source_chunks WHERE expert_id = $1", expert.id
        )]
    assert ids == [uploaded]
    assert chunk_sources == [uploaded]
    assert found not in ids


async def test_reset_recounts_rather_than_zeroing_when_uploads_survive(db_pool):
    """source_count/chunk_count must describe what is actually left, or the UI
    shows an empty expert that still answers questions."""
    expert = await _expert(db_pool, "reset-counts")
    uploaded = await _source(db_pool, expert.id, "My Book", upload=True)
    await _chunk(db_pool, expert.id, uploaded, 0)
    await _chunk(db_pool, expert.id, uploaded, 1)

    await ExpertRepository(db_pool).reset_build_state(expert.id)

    reloaded = await ExpertRepository(db_pool).get_by_id(expert.id)
    assert reloaded.source_count == 1
    assert reloaded.chunk_count == 2
    # The graph is still wiped whole — it is rebuilt whole.
    assert reloaded.node_count == 0
    assert reloaded.edge_count == 0


async def test_reset_still_zeroes_an_expert_with_no_uploads(db_pool):
    expert = await _expert(db_pool, "reset-plain")
    found = await _source(db_pool, expert.id, "Some Blog", upload=False)
    await _chunk(db_pool, expert.id, found)

    await ExpertRepository(db_pool).reset_build_state(expert.id)

    reloaded = await ExpertRepository(db_pool).get_by_id(expert.id)
    assert reloaded.source_count == 0
    assert reloaded.chunk_count == 0


# ── job typing ──────────────────────────────────────────────────────────────

async def test_ingest_jobs_queue_alongside_a_running_build(db_pool):
    """The one-active-job index is build-scoped, so a user is not blocked from
    queueing documents by an unrelated build, and two documents do not collapse
    into one job."""
    expert = await _expert(db_pool, "jobs-parallel")
    jobs = JobRepository(db_pool)

    build = await jobs.enqueue(expert.id, "lite", None, 3)
    first = await jobs.enqueue(
        expert.id, "lite", None, 3, JobType.INGEST_SOURCE, {"upload_id": 1}
    )
    second = await jobs.enqueue(
        expert.id, "lite", None, 3, JobType.INGEST_SOURCE, {"upload_id": 2}
    )

    assert len({build.id, first.id, second.id}) == 3
    assert first.job_type is JobType.INGEST_SOURCE
    assert first.payload == {"upload_id": 1}
    assert build.is_build


async def test_duplicate_builds_still_collapse(db_pool):
    expert = await _expert(db_pool, "jobs-dedup")
    jobs = JobRepository(db_pool)
    first = await jobs.enqueue(expert.id, "lite", None, 3)
    second = await jobs.enqueue(expert.id, "lite", None, 3)
    assert first.id == second.id


async def test_cancelling_a_build_leaves_queued_ingests_alone(db_pool):
    """A user cancelling a build never asked to throw away documents they had
    queued, and those documents cannot be recovered once cancelled."""
    expert = await _expert(db_pool, "jobs-cancel")
    jobs = JobRepository(db_pool)
    build = await jobs.enqueue(expert.id, "lite", None, 3)
    ingest = await jobs.enqueue(
        expert.id, "lite", None, 3, JobType.INGEST_SOURCE, {"upload_id": 9}
    )

    await jobs.request_cancel(expert.id, job_type=JobType.BUILD)

    assert (await jobs.get_job(build.id)).status is JobStatus.CANCELLED
    assert (await jobs.get_job(ingest.id)).status is JobStatus.QUEUED


async def test_deleting_an_expert_cancels_everything(db_pool):
    expert = await _expert(db_pool, "jobs-cancel-all")
    jobs = JobRepository(db_pool)
    build = await jobs.enqueue(expert.id, "lite", None, 3)
    ingest = await jobs.enqueue(
        expert.id, "lite", None, 3, JobType.INGEST_SOURCE, {"upload_id": 9}
    )

    await jobs.request_cancel(expert.id)  # unscoped

    assert (await jobs.get_job(build.id)).status is JobStatus.CANCELLED
    assert (await jobs.get_job(ingest.id)).status is JobStatus.CANCELLED


# ── upload payload storage ──────────────────────────────────────────────────

async def test_pending_upload_round_trips(db_pool):
    expert = await _expert(db_pool, "upload-roundtrip")
    repo = UploadRepository(db_pool)
    created = await repo.create(
        expert_id=expert.id, owner_id="user-1", kind=UploadKind.PDF,
        title="The Intelligent Investor", filename="tii.pdf",
        media_type="application/pdf", content=b"%PDF-1.7 body",
    )
    loaded = await repo.get(created.id)
    assert loaded.kind is UploadKind.PDF
    assert loaded.content == b"%PDF-1.7 body"
    assert loaded.byte_size == len(b"%PDF-1.7 body")

    await repo.clear_payload(created.id)
    cleared = await repo.get(created.id)
    assert cleared.content is None
    # The row survives — it records that a person supplied this material.
    assert cleared.title == "The Intelligent Investor"


async def test_upload_source_is_recorded_as_unscored_and_primary(db_pool):
    """An upload is admitted, not judged. Writing a flattering quality score
    would corrupt avg_quality with a judgement nothing actually made."""
    expert = await _expert(db_pool, "upload-source-row")
    source_id = await _source(db_pool, expert.id, "My Book", upload=True)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT passed, quality_score, relevance_score, discovered_via,
                      source_tier, uploaded_by
               FROM sources WHERE id = $1""",
            source_id,
        )
    assert row["passed"] is True
    assert row["quality_score"] is None
    assert row["relevance_score"] is None
    assert row["discovered_via"] == "upload"
    assert row["source_tier"] == "primary"
    assert row["uploaded_by"] == "user-1"


async def test_delete_source_removes_chunks_and_recounts(db_pool):
    expert = await _expert(db_pool, "upload-delete")
    repo = UploadRepository(db_pool)
    keep = await _source(db_pool, expert.id, "Keep", upload=True)
    drop = await _source(db_pool, expert.id, "Drop", upload=True)
    await _chunk(db_pool, expert.id, keep)
    await _chunk(db_pool, expert.id, drop)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE experts SET source_count = 2, chunk_count = 2 WHERE id = $1",
            expert.id,
        )

    assert await repo.delete_source(expert.id, drop) is True
    assert await repo.delete_source(expert.id, drop) is False  # already gone

    reloaded = await ExpertRepository(db_pool).get_by_id(expert.id)
    assert reloaded.source_count == 1
    assert reloaded.chunk_count == 1


async def test_list_sources_exposes_provenance(db_pool):
    expert = await _expert(db_pool, "upload-list")
    await _source(db_pool, expert.id, "My Book", upload=True)
    await _source(db_pool, expert.id, "Some Blog", upload=False)

    rows = await UploadRepository(db_pool).list_sources(expert.id)
    by_title = {r["title"]: r for r in rows}
    assert by_title["My Book"]["discovered_via"] == "upload"
    assert by_title["Some Blog"]["discovered_via"] == "plan"
