"""Unit tests for ExpertTier / ExpertConfig."""

import dataclasses
import json

import pytest

from peritus.experts.domain import ExpertConfig, ExpertTier, _TIER_DEFAULTS


def test_tier_defaults_are_correct():
    lite = ExpertConfig.from_tier(ExpertTier.LITE)
    assert lite.source_multiplier == 0.5
    assert lite.retrieval_top_k == 5
    assert lite.max_subqueries == 2
    assert lite.graph_hops == 1
    assert lite.coverage_extra_k == 3
    assert lite.max_context_passages == 8
    assert lite.max_response_tokens == 1024

    std = ExpertConfig.from_tier(ExpertTier.STANDARD)
    assert std.source_multiplier == 1.0
    assert std.retrieval_top_k == 10
    assert std.max_subqueries == 4
    assert std.graph_hops == 1
    assert std.coverage_extra_k == 5
    assert std.max_context_passages == 15
    assert std.max_response_tokens == 2048

    pro = ExpertConfig.from_tier(ExpertTier.PRO)
    assert pro.source_multiplier == 2.0
    assert pro.retrieval_top_k == 20
    assert pro.max_subqueries == 6
    assert pro.graph_hops == 2
    assert pro.coverage_extra_k == 10
    assert pro.max_context_passages == 25
    assert pro.max_response_tokens == 4096


def test_monotonicity():
    lite = ExpertConfig.from_tier(ExpertTier.LITE)
    std  = ExpertConfig.from_tier(ExpertTier.STANDARD)
    pro  = ExpertConfig.from_tier(ExpertTier.PRO)

    for field in dataclasses.fields(ExpertConfig):
        l_val = getattr(lite, field.name)
        s_val = getattr(std, field.name)
        p_val = getattr(pro, field.name)
        assert l_val <= s_val, f"{field.name}: LITE({l_val}) > STANDARD({s_val})"
        assert s_val <= p_val, f"{field.name}: STANDARD({s_val}) > PRO({p_val})"


def test_serialisation_roundtrip():
    for tier in ExpertTier:
        cfg = ExpertConfig.from_tier(tier)
        serialised = json.dumps(dataclasses.asdict(cfg))
        restored = ExpertConfig(**json.loads(serialised))
        assert restored == cfg


def test_empty_config_fallback():
    """_row_to_expert must derive config from tier when stored config is empty."""
    from peritus.experts.repository import _row_to_expert
    from datetime import datetime, timezone

    class _FakeRow:
        def keys(self):
            return [
                "id", "name", "topic", "status", "tier", "config",
                "persona_name", "persona_bio", "persona_style",
                "source_count", "chunk_count", "node_count", "edge_count",
                "avg_quality", "key_concepts", "error", "created_at", "updated_at",
            ]

        def __getitem__(self, key):
            _now = datetime.now(timezone.utc)
            return {
                "id": 1,
                "name": "test",
                "topic": "test topic",
                "status": "ready",
                "tier": "standard",
                "config": {},          # empty — should fall back to STANDARD defaults
                "persona_name": None,
                "persona_bio": None,
                "persona_style": None,
                "source_count": 0,
                "chunk_count": 0,
                "node_count": 0,
                "edge_count": 0,
                "avg_quality": None,
                "key_concepts": None,
                "error": None,
                "created_at": _now,
                "updated_at": _now,
            }[key]

    expert = _row_to_expert(_FakeRow())
    assert expert.config == ExpertConfig.from_tier(ExpertTier.STANDARD)


def test_unknown_tier_rejected():
    with pytest.raises(ValueError):
        ExpertTier("ultra")
