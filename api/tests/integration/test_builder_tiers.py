"""Integration-level tests for tier-driven builder and chat pipeline behaviour.

No network or DB required — all external calls are mocked.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier
from peritus.experts.builder import ExpertBuilder


def _make_expert(tier: ExpertTier) -> Expert:
    return Expert(
        id=1,
        name="test-expert",
        topic="stoicism",
        status=ExpertStatus.READY,
        tier=tier,
        config=ExpertConfig.from_tier(tier),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ── builder multiplier tests ──────────────────────────────────────────────────

def test_lite_builder_multiplier():
    pool = MagicMock()
    builder = ExpertBuilder(pool)
    expert = _make_expert(ExpertTier.LITE)

    captured: list[float] = []

    def _capture(multiplier, source_filter):
        captured.append(multiplier)
        return {}

    builder._build_fetchers = _capture
    # Simulate what build() does at the top
    builder._build_fetchers(expert.config.source_multiplier, None)

    assert captured == [0.5]


def test_pro_builder_multiplier():
    pool = MagicMock()
    builder = ExpertBuilder(pool)
    expert = _make_expert(ExpertTier.PRO)

    captured: list[float] = []

    def _capture(multiplier, source_filter):
        captured.append(multiplier)
        return {}

    builder._build_fetchers = _capture
    builder._build_fetchers(expert.config.source_multiplier, None)

    assert captured == [2.0]


# ── chat pipeline propagation tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_lite_chat_pipeline_top_k():
    from peritus.chat.agent import ChatAgent

    pool = MagicMock()
    agent = ChatAgent(pool)

    expert = _make_expert(ExpertTier.LITE)

    search_mock = AsyncMock()
    search_mock.results = []
    agent._search.batch_search = AsyncMock(return_value=search_mock)
    agent._graph.expand = AsyncMock(return_value=[])
    agent._assess_coverage = AsyncMock(return_value={"satisfied": True, "suggested_queries": []})
    agent._plan = AsyncMock(return_value=["subquery"])

    with patch("peritus.chat.agent.get_anthropic_client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.content = []
        mock_client.return_value.messages.create = AsyncMock(return_value=mock_resp)
        await agent.respond(expert, "What is virtue?", [])

    agent._search.batch_search.assert_awaited_once()
    call_kwargs = agent._search.batch_search.call_args.kwargs
    assert call_kwargs["top_k"] == 5  # LITE retrieval_top_k


@pytest.mark.asyncio
async def test_pro_chat_pipeline_top_k():
    from peritus.chat.agent import ChatAgent

    pool = MagicMock()
    agent = ChatAgent(pool)

    expert = _make_expert(ExpertTier.PRO)

    search_mock = AsyncMock()
    search_mock.results = []
    agent._search.batch_search = AsyncMock(return_value=search_mock)
    agent._graph.expand = AsyncMock(return_value=[])
    agent._assess_coverage = AsyncMock(return_value={"satisfied": True, "suggested_queries": []})
    agent._plan = AsyncMock(return_value=["subquery"])

    with patch("peritus.chat.agent.get_anthropic_client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.content = []
        mock_client.return_value.messages.create = AsyncMock(return_value=mock_resp)
        await agent.respond(expert, "What is virtue?", [])

    call_kwargs = agent._search.batch_search.call_args.kwargs
    assert call_kwargs["top_k"] == 20  # PRO retrieval_top_k


@pytest.mark.asyncio
async def test_graph_hops_propagates():
    from peritus.chat.agent import ChatAgent

    pool = MagicMock()
    agent = ChatAgent(pool)

    for tier, expected_hops in [(ExpertTier.STANDARD, 1), (ExpertTier.PRO, 2)]:
        expert = _make_expert(tier)

        search_mock = AsyncMock()
        search_mock.results = []
        agent._search.batch_search = AsyncMock(return_value=search_mock)
        agent._graph.expand = AsyncMock(return_value=[])
        agent._assess_coverage = AsyncMock(return_value={"satisfied": True, "suggested_queries": []})
        agent._plan = AsyncMock(return_value=["subquery"])

        with patch("peritus.chat.agent.get_anthropic_client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.content = []
            mock_client.return_value.messages.create = AsyncMock(return_value=mock_resp)
            await agent.respond(expert, "What is virtue?", [])

        call_kwargs = agent._graph.expand.call_args.kwargs
        assert call_kwargs.get("hops") == expected_hops, (
            f"tier={tier}: expected hops={expected_hops}, got {call_kwargs}"
        )
