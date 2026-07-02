"""Unit tests for the reranker's graceful-fallback behaviour.

The reranker must never break search: when disabled, unconfigured, or given a
trivial input it returns the candidates in their original (RRF) order without
calling any model.
"""

from peritus.core.config import settings
from peritus.infrastructure import reranker


async def test_returns_identity_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-test")

    out = await reranker.rerank("q", ["a", "b", "c"], top_n=2)

    assert out == [(0, 0.0), (1, 0.0)]


async def test_returns_identity_without_any_key(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(settings, "COHERE_API_KEY", "")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")

    out = await reranker.rerank("q", ["a", "b", "c", "d"], top_n=10)

    # capped at the number of documents, original order preserved
    assert out == [(0, 0.0), (1, 0.0), (2, 0.0), (3, 0.0)]


async def test_returns_identity_for_single_document(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-test")

    out = await reranker.rerank("q", ["only one"], top_n=5)

    assert out == [(0, 0.0)]


async def test_falls_back_to_llm_when_cohere_fails(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(settings, "COHERE_API_KEY", "co-test")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-test")

    async def _cohere_none(query, documents, top_n):
        return None

    async def _llm(query, documents, top_n):
        return [(1, 0.9), (0, 0.1)]

    monkeypatch.setattr(reranker, "_cohere_rerank", _cohere_none)
    monkeypatch.setattr(reranker, "_llm_windowed_rerank", _llm)

    out = await reranker.rerank("q", ["a", "b"], top_n=2)

    assert out == [(1, 0.9), (0, 0.1)]
