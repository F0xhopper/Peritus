"""Per-build execution policy: which builds pay full price for speed."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from peritus.core.config import settings
from peritus.experts.builder import resolve_execution
from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier
from peritus.infrastructure.anthropic_batch import (
    BuildExecution,
    build_execution,
    current_execution,
    gather_claude_calls,
    should_batch,
)


def _expert(persona_name: str | None = None) -> Expert:
    return Expert(
        id=1,
        name="test-expert",
        topic="stoicism",
        status=ExpertStatus.BUILDING,
        tier=ExpertTier.STANDARD,
        config=ExpertConfig.from_tier(ExpertTier.STANDARD),
        persona_name=persona_name,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def batch_on(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_BATCH_ENABLED", True)
    monkeypatch.setattr(settings, "ANTHROPIC_BATCH_MIN_REQUESTS", 4)


# ── policy resolution ────────────────────────────────────────────────────────

def test_auto_first_build_runs_interactive(monkeypatch):
    """No persona = never finished a build = a user is watching this one."""
    monkeypatch.setattr(settings, "BUILD_EXECUTION_DEFAULT", "auto")
    assert resolve_execution(_expert(persona_name=None)) is BuildExecution.INTERACTIVE


def test_auto_rebuild_runs_background(monkeypatch):
    monkeypatch.setattr(settings, "BUILD_EXECUTION_DEFAULT", "auto")
    assert resolve_execution(_expert(persona_name="Dr. Aurelia Vance")) is BuildExecution.BACKGROUND


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("interactive", BuildExecution.INTERACTIVE),
        ("background", BuildExecution.BACKGROUND),
    ],
)
def test_explicit_default_overrides_heuristic(monkeypatch, configured, expected):
    monkeypatch.setattr(settings, "BUILD_EXECUTION_DEFAULT", configured)
    assert resolve_execution(_expert(persona_name=None)) is expected
    assert resolve_execution(_expert(persona_name="Someone")) is expected


def test_unknown_default_falls_back_to_auto(monkeypatch):
    monkeypatch.setattr(settings, "BUILD_EXECUTION_DEFAULT", "nonsense")
    assert resolve_execution(_expert(persona_name=None)) is BuildExecution.INTERACTIVE


# ── the three gates on should_batch ──────────────────────────────────────────

def test_interactive_build_never_batches(batch_on):
    with build_execution(BuildExecution.INTERACTIVE):
        assert should_batch(100) is False


def test_background_build_batches(batch_on):
    with build_execution(BuildExecution.BACKGROUND):
        assert should_batch(100) is True


def test_env_kill_switch_beats_build_policy(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_BATCH_ENABLED", False)
    with build_execution(BuildExecution.BACKGROUND):
        assert should_batch(100) is False


def test_small_stages_stay_live(batch_on):
    with build_execution(BuildExecution.BACKGROUND):
        assert should_batch(settings.ANTHROPIC_BATCH_MIN_REQUESTS - 1) is False


def test_default_outside_a_build_is_background(batch_on):
    """Callers that never declared a policy keep the old env-driven behaviour."""
    assert current_execution() is BuildExecution.BACKGROUND
    assert should_batch(100) is True


def test_context_restores_previous_mode(batch_on):
    with build_execution(BuildExecution.INTERACTIVE):
        assert current_execution() is BuildExecution.INTERACTIVE
    assert current_execution() is BuildExecution.BACKGROUND


# ── isolation between concurrent builds ──────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_builds_do_not_leak_policy(batch_on):
    """Two builds in one worker process must not see each other's mode."""
    observed: dict[str, list[bool]] = {"interactive": [], "background": []}

    async def fake_build(mode: BuildExecution, key: str) -> None:
        with build_execution(mode):
            for _ in range(5):
                await asyncio.sleep(0)
                observed[key].append(should_batch(100))

    await asyncio.gather(
        fake_build(BuildExecution.INTERACTIVE, "interactive"),
        fake_build(BuildExecution.BACKGROUND, "background"),
    )

    assert observed["interactive"] == [False] * 5
    assert observed["background"] == [True] * 5


@pytest.mark.asyncio
async def test_policy_reaches_gather_claude_calls(batch_on):
    """The four stage call sites route through here; no signature carries the flag."""
    params = [{"model": "m", "messages": []} for _ in range(10)]

    with patch("peritus.infrastructure.anthropic_batch._run_live") as live, patch(
        "peritus.infrastructure.anthropic_batch._run_batch"
    ) as batch:
        live.side_effect = AsyncMock(return_value=[None] * 10)
        batch.side_effect = AsyncMock(return_value=[object()] * 10)

        with build_execution(BuildExecution.INTERACTIVE):
            await gather_claude_calls(params, description="triage")
        assert live.called and not batch.called

        live.reset_mock()
        with build_execution(BuildExecution.BACKGROUND):
            await gather_claude_calls(params, description="triage")
        assert batch.called
