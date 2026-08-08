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
    from peritus.api.auth import AuthUser, require_user

    app = create_app()
    # Auth is verified elsewhere (test_auth.py); these contract tests run as a
    # fixed admin user so they don't depend on tokens or Supabase env.
    app.dependency_overrides[require_user] = lambda: AuthUser(
        id="00000000-0000-0000-0000-000000000000", email="admin@test", is_admin=True
    )
    return app


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


def test_default_tier_is_unset_so_the_server_resolves_it():
    """A bare topic names no tier: the route asks EntitlementService.resolve_tier
    for the deepest tier the caller's plan allows and balance affords, so
    `{"topic": ...}` alone is always a buildable request."""
    from peritus.api.schemas.experts import BuildRequest
    req = BuildRequest(topic="stoicism")
    assert req.tier is None


# ── build enqueues a job and streams the durable event log ──

@pytest.mark.asyncio
async def test_build_enqueues_and_streams(client):
    expert = _make_expert(ExpertTier.LITE, name="stoicism")

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
        patch("peritus.api.routes.experts.JobRepository") as MockJobs,
        patch("peritus.api.routes.experts.EntitlementService") as MockEntitlements,
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

        # Builds are credit-gated at enqueue; an entitled caller passes both the
        # pre-check and the hold.
        mock_entitlements = AsyncMock()
        MockEntitlements.return_value = mock_entitlements

        resp = await client.post("/experts/build", json={"topic": "stoicism", "tier": "lite"})

    assert resp.status_code == 200
    assert "done" in resp.text
    mock_jobs.enqueue.assert_awaited_once()
    # Authorised before anything was created, then charged once the job existed.
    mock_entitlements.authorize_build.assert_awaited_once()
    mock_entitlements.hold_for_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_denied_without_credits(client):
    """A denial is a structured 402 the client can render, not prose."""
    from peritus.billing.domain import FREE, InsufficientCredits

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
        patch("peritus.api.routes.experts.JobRepository") as MockJobs,
        patch("peritus.api.routes.experts.EntitlementService") as MockEntitlements,
    ):
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=None)
        MockRepo.return_value = mock_repo
        MockJobs.return_value = AsyncMock()

        mock_entitlements = AsyncMock()
        mock_entitlements.authorize_build = AsyncMock(
            side_effect=InsufficientCredits(
                required=1, available=0, tier=ExpertTier.LITE, plan=FREE
            )
        )
        MockEntitlements.return_value = mock_entitlements

        resp = await client.post("/experts/build", json={"topic": "stoicism", "tier": "lite"})

    assert resp.status_code == 402
    body = resp.json()["detail"]
    assert body["code"] == "insufficient_credits"
    assert body["required_credits"] == 1
    assert body["available_credits"] == 0
    assert body["remedy"]["kind"] == "request_credits"
    # Nothing was created for a build that was never authorised.
    mock_repo.create.assert_not_awaited()


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
        # Delete is a mutation, so it resolves the expert via get_owned_for_user
        # (owner-only) rather than the wider read-visibility lookup — a public
        # catalog expert must not be deletable by everyone who can read it.
        mock_repo.get_owned_for_user = AsyncMock(return_value=expert)
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
        mock_repo.get_for_user = AsyncMock(return_value=expert)
        MockRepo.return_value = mock_repo

        resp = await client.get("/experts/stoicism")

    assert resp.status_code == 200
    assert resp.json()["tier"] == "lite"


# ── topic-only creation: server resolves the tier ──

@pytest.mark.asyncio
async def test_topic_only_build_resolves_tier_from_plan(client):
    """`{"topic": ...}` with no tier asks the entitlement service which tier
    this account can actually build, instead of 402ing on a fixed default."""
    expert = _make_expert(ExpertTier.LITE, name="stoicism")

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
        patch("peritus.api.routes.experts.JobRepository") as MockJobs,
        patch("peritus.api.routes.experts.EntitlementService") as MockEntitlements,
    ):
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=None)
        mock_repo.create = AsyncMock(return_value=expert)
        MockRepo.return_value = mock_repo

        mock_jobs = AsyncMock()
        mock_jobs.enqueue = AsyncMock(return_value=_make_job())
        mock_jobs.read_events = AsyncMock(return_value=[_done_event()])
        MockJobs.return_value = mock_jobs

        mock_entitlements = AsyncMock()
        mock_entitlements.resolve_tier = AsyncMock(return_value=ExpertTier.LITE)
        MockEntitlements.return_value = mock_entitlements

        resp = await client.post("/experts/build", json={"topic": "stoicism"})

    assert resp.status_code == 200
    mock_entitlements.resolve_tier.assert_awaited_once()
    mock_entitlements.authorize_build.assert_awaited_once_with(
        "00000000-0000-0000-0000-000000000000", ExpertTier.LITE, "admin@test"
    )
    assert mock_jobs.enqueue.await_args.kwargs["tier"] == "lite"
    assert mock_repo.create.await_args.kwargs["tier"] is ExpertTier.LITE


@pytest.mark.asyncio
async def test_explicit_tier_skips_resolution(client):
    expert = _make_expert(ExpertTier.PRO, name="stoicism")

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
        patch("peritus.api.routes.experts.JobRepository") as MockJobs,
        patch("peritus.api.routes.experts.EntitlementService") as MockEntitlements,
    ):
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=None)
        mock_repo.create = AsyncMock(return_value=expert)
        MockRepo.return_value = mock_repo

        mock_jobs = AsyncMock()
        mock_jobs.enqueue = AsyncMock(return_value=_make_job())
        mock_jobs.read_events = AsyncMock(return_value=[_done_event()])
        MockJobs.return_value = mock_jobs

        mock_entitlements = AsyncMock()
        MockEntitlements.return_value = mock_entitlements

        resp = await client.post("/experts/build", json={"topic": "stoicism", "tier": "pro"})

    assert resp.status_code == 200
    mock_entitlements.resolve_tier.assert_not_awaited()
    mock_entitlements.authorize_build.assert_awaited_once_with(
        "00000000-0000-0000-0000-000000000000", ExpertTier.PRO, "admin@test"
    )


# ── slug collisions step over other users' experts instead of 404ing ──

@pytest.mark.asyncio
async def test_slug_collision_autosuffixes(client):
    """Another user already owns 'stoicism': the build lands on 'stoicism-2'
    rather than revealing (or 404ing on) the taken slug."""
    theirs = _make_expert(name="stoicism")
    theirs.owner_id = "11111111-1111-1111-1111-111111111111"
    mine = _make_expert(ExpertTier.LITE, name="stoicism-2")
    mine.owner_id = "00000000-0000-0000-0000-000000000000"

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
        patch("peritus.api.routes.experts.JobRepository") as MockJobs,
        patch("peritus.api.routes.experts.EntitlementService") as MockEntitlements,
    ):
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(side_effect=[theirs, None])
        mock_repo.create = AsyncMock(return_value=mine)
        MockRepo.return_value = mock_repo

        mock_jobs = AsyncMock()
        mock_jobs.enqueue = AsyncMock(return_value=_make_job())
        mock_jobs.read_events = AsyncMock(return_value=[_done_event()])
        MockJobs.return_value = mock_jobs

        mock_entitlements = AsyncMock()
        mock_entitlements.resolve_tier = AsyncMock(return_value=ExpertTier.LITE)
        MockEntitlements.return_value = mock_entitlements

        resp = await client.post("/experts/build", json={"topic": "stoicism"})

    assert resp.status_code == 200
    assert mock_repo.create.await_args.kwargs["name"] == "stoicism-2"


# ── source filter is validated at the door ──

@pytest.mark.asyncio
async def test_unknown_source_type_is_rejected(client):
    with patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()):
        resp = await client.post(
            "/experts/build", json={"topic": "stoicism", "sources": ["wikipedia", "tiktok"]}
        )
    assert resp.status_code == 400
    assert "tiktok" in resp.json()["detail"]
    assert "wikipedia" in resp.json()["detail"]  # valid names are listed back


@pytest.mark.asyncio
async def test_empty_source_list_is_rejected(client):
    with patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()):
        resp = await client.post(
            "/experts/build", json={"topic": "stoicism", "sources": []}
        )
    assert resp.status_code == 400


# ── rebuild at a different tier moves tier + config with it ──

@pytest.mark.asyncio
async def test_rebuild_at_new_tier_updates_expert(client):
    expert = _make_expert(ExpertTier.LITE, name="stoicism")
    expert.owner_id = "00000000-0000-0000-0000-000000000000"

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
        patch("peritus.api.routes.experts.JobRepository") as MockJobs,
        patch("peritus.api.routes.experts.EntitlementService") as MockEntitlements,
    ):
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=expert)
        MockRepo.return_value = mock_repo

        mock_jobs = AsyncMock()
        mock_jobs.get_active_job = AsyncMock(return_value=None)
        mock_jobs.enqueue = AsyncMock(return_value=_make_job())
        mock_jobs.read_events = AsyncMock(return_value=[_done_event()])
        MockJobs.return_value = mock_jobs

        MockEntitlements.return_value = AsyncMock()

        resp = await client.post(
            "/experts/build", json={"topic": "stoicism", "tier": "standard"}
        )

    assert resp.status_code == 200
    mock_repo.update_tier.assert_awaited_once_with(expert.id, ExpertTier.STANDARD)


# ── the stream announces which expert it belongs to ──

@pytest.mark.asyncio
async def test_build_appends_created_event(client):
    expert = _make_expert(ExpertTier.LITE, name="stoicism")

    with (
        patch("peritus.api.routes.experts.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.experts.ExpertRepository") as MockRepo,
        patch("peritus.api.routes.experts.JobRepository") as MockJobs,
        patch("peritus.api.routes.experts.EntitlementService") as MockEntitlements,
    ):
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=None)
        mock_repo.create = AsyncMock(return_value=expert)
        MockRepo.return_value = mock_repo

        mock_jobs = AsyncMock()
        mock_jobs.enqueue = AsyncMock(return_value=_make_job())
        mock_jobs.read_events = AsyncMock(return_value=[_done_event()])
        MockJobs.return_value = mock_jobs

        mock_entitlements = AsyncMock()
        mock_entitlements.resolve_tier = AsyncMock(return_value=ExpertTier.LITE)
        MockEntitlements.return_value = mock_entitlements

        resp = await client.post("/experts/build", json={"topic": "stoicism"})

    assert resp.status_code == 200
    created_calls = [
        c for c in mock_jobs.append_event.await_args_list if c.args[1] == "created"
    ]
    assert len(created_calls) == 1
    payload = created_calls[0].args[2]
    assert payload["slug"] == "stoicism"
    assert payload["expert_id"] == expert.id
    assert payload["tier"] == "lite"
