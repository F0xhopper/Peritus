"""API contract tests for the expert build endpoints and tier field exposure.

DB and queue are mocked so no infrastructure is required.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier
from peritus.jobs.domain import BuildEventRow, BuildJob, JobStatus


def _make_expert(tier: ExpertTier = ExpertTier.STANDARD, name: str = "stoicism") -> Expert:
    return Expert(
        id=1,
        name=name,
        topic=name,
        status=ExpertStatus.QUEUED,
        tier=tier,
        config=ExpertConfig.from_tier(tier),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_job(status: JobStatus = JobStatus.QUEUED) -> BuildJob:
    now = datetime.now(UTC)
    return BuildJob(
        id=1, expert_id=1, status=status, tier="lite", source_filter=None,
        attempts=1, max_attempts=3, available_at=now, locked_by=None,
        heartbeat_at=None, last_error=None, created_at=now, updated_at=now,
    )


def _done_event() -> BuildEventRow:
    return BuildEventRow(
        seq=1, job_id=1, type="done",
        payload={"type": "done", "expert_id": 1, "source_count": 3,
                 "chunk_count": 10, "node_count": 5, "edge_count": 4},
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def app():
    from peritus.api.app import create_app
    return create_app()


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── tier validation (no mocks needed — Pydantic validates first) ──

@pytest.mark.asyncio
async def test_invalid_tier_rejected(client):
    with patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()):
        resp = await client.post("/experts/build", json={"topic": "stoicism", "tier": "ultra"})
    assert resp.status_code == 422


def test_default_tier_is_standard():
    from peritus.api.schemas.experts import BuildRequest
    req = BuildRequest(topic="stoicism")
    assert req.tier == ExpertTier.STANDARD


# ── build enqueues a job and streams the durable event log ──

@pytest.mark.asyncio
async def test_build_enqueues_and_streams(client):
    expert = _make_expert(ExpertTier.LITE, name="stoicism")

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
        patch("peritus.api.routes.experts.JobRepository") as MockJobs,
    ):
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=None)
        mock_repo.create = AsyncMock(return_value=expert)
        MockRepo.return_value = mock_repo

        mock_jobs = AsyncMock()
        mock_jobs.enqueue = AsyncMock(return_value=_make_job())
        # First poll returns a terminal 'done' event so the SSE stream closes.
        mock_jobs.read_events = AsyncMock(return_value=[_done_event()])
        MockJobs.return_value = mock_jobs

        resp = await client.post("/experts/build", json={"topic": "stoicism", "tier": "lite"})

    assert resp.status_code == 200
    assert "done" in resp.text
    mock_jobs.enqueue.assert_awaited_once()


# ── reconnect endpoint replays from a cursor ──

@pytest.mark.asyncio
async def test_build_events_reconnect(client):
    expert = _make_expert(ExpertTier.LITE, name="stoicism")

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
        patch("peritus.api.routes.experts.JobRepository") as MockJobs,
    ):
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=expert)
        MockRepo.return_value = mock_repo

        mock_jobs = AsyncMock()
        mock_jobs.get_latest_job = AsyncMock(return_value=_make_job(JobStatus.RUNNING))
        mock_jobs.read_events = AsyncMock(return_value=[_done_event()])
        MockJobs.return_value = mock_jobs

        resp = await client.get("/experts/stoicism/build/events?after=0")

    assert resp.status_code == 200
    assert "done" in resp.text


# ── delete cancels any in-flight build then removes the expert ──

@pytest.mark.asyncio
async def test_delete_cancels_then_deletes(client):
    expert = _make_expert(name="stoicism")

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
        patch("peritus.api.routes.experts.JobRepository") as MockJobs,
    ):
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=expert)
        mock_repo.delete = AsyncMock()
        MockRepo.return_value = mock_repo

        mock_jobs = AsyncMock()
        mock_jobs.request_cancel = AsyncMock(return_value=True)
        MockJobs.return_value = mock_jobs

        resp = await client.delete("/experts/stoicism")

    assert resp.status_code == 204
    mock_jobs.request_cancel.assert_awaited_once_with(expert.id)
    mock_repo.delete.assert_awaited_once_with(expert.id)


# ── tier surfaced in GET response ──

@pytest.mark.asyncio
async def test_tier_in_get_response(client):
    expert = _make_expert(ExpertTier.LITE, name="stoicism")

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
    ):
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=expert)
        MockRepo.return_value = mock_repo

        resp = await client.get("/experts/stoicism")

    assert resp.status_code == 200
    assert resp.json()["tier"] == "lite"
