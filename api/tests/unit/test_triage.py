"""Unit tests for candidate triage ranking and the budgeted fetch-with-refill."""

import pytest

from peritus.experts.builder import ExpertBuilder
from peritus.sources.domain import RawSource, SourceCandidate, SourceType
from peritus.sources.triage import (
    TriagedCandidate,
    _matches_must_have,
    rank_candidates,
)


def _candidate(
    title: str,
    url: str,
    source_type: SourceType = SourceType.WEB,
) -> SourceCandidate:
    return SourceCandidate(
        source_type=source_type, url=url, title=title, author=None, snippet="",
    )


def _triaged(title: str, url: str, score: float, st: SourceType = SourceType.WEB) -> TriagedCandidate:
    return TriagedCandidate(candidate=_candidate(title, url, st), score=score)


# ── ranking ───────────────────────────────────────────────────────────────────

def test_rank_orders_by_score_and_drops_junk():
    ranked = rank_candidates([
        _triaged("low", "https://a.test", 2.9),
        _triaged("high", "https://b.test", 9.0),
        _triaged("mid", "https://c.test", 5.0),
    ])
    assert [t.candidate.title for t in ranked] == ["high", "mid"]


def test_rank_drops_near_duplicate_titles_keeping_higher_score():
    ranked = rank_candidates([
        _triaged("Introduction to Stoicism", "https://a.test", 7.0),
        _triaged("Introduction to Stoicism!", "https://b.test", 9.0),
        _triaged("Stoic physics and logic", "https://c.test", 5.0),
    ])
    titles = [t.candidate.title for t in ranked]
    assert titles == ["Introduction to Stoicism!", "Stoic physics and logic"]


def test_matches_must_have_fuzzy():
    assert _matches_must_have("Meditations", ["Meditations"])
    assert _matches_must_have("The Meditations of Marcus Aurelius", ["Meditations"])
    assert not _matches_must_have("A blog post about breakfast", ["Meditations"])
    assert not _matches_must_have("Anything", [])


# ── fetch with refill ─────────────────────────────────────────────────────────

class _FakeFetcher:
    """Returns a RawSource unless the candidate URL is marked to fail."""

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        if candidate.metadata.get("fail"):
            return None
        return RawSource(
            source_type=candidate.source_type,
            url=candidate.url,
            title=candidate.title,
            author=None,
            text="x" * 1000,
        )


def _builder_with_fake_fetchers() -> ExpertBuilder:
    builder = ExpertBuilder.__new__(ExpertBuilder)
    builder._fetchers = {
        "web": (_FakeFetcher(), 3),
        "exa": (_FakeFetcher(), 3),
    }
    return builder


@pytest.mark.asyncio
async def test_fetch_with_refill_stops_at_budget():
    builder = _builder_with_fake_fetchers()
    ranked = [
        _triaged(f"t{i}", f"https://x.test/{i}", 9 - i * 0.1) for i in range(10)
    ]
    results = await builder._fetch_with_refill(ranked, budget=4, caps={SourceType.WEB: 99})
    assert len(results) == 4
    # Highest-ranked candidates win the budget.
    assert [r.title for r in results] == ["t0", "t1", "t2", "t3"]


@pytest.mark.asyncio
async def test_fetch_with_refill_replaces_failures_from_lower_ranks():
    builder = _builder_with_fake_fetchers()
    failing = TriagedCandidate(
        candidate=SourceCandidate(
            source_type=SourceType.WEB, url="https://fail.test", title="fails",
            author=None, snippet="", metadata={"fail": True},
        ),
        score=9.5,
    )
    ranked = [failing] + [
        _triaged(f"t{i}", f"https://x.test/{i}", 8 - i * 0.1) for i in range(4)
    ]
    results = await builder._fetch_with_refill(ranked, budget=3, caps={SourceType.WEB: 99})
    assert len(results) == 3
    assert "fails" not in [r.title for r in results]


@pytest.mark.asyncio
async def test_fetch_with_refill_enforces_per_type_caps():
    builder = _builder_with_fake_fetchers()
    ranked = [
        _triaged(f"web{i}", f"https://w.test/{i}", 9 - i * 0.1, SourceType.WEB)
        for i in range(5)
    ] + [
        _triaged(f"exa{i}", f"https://e.test/{i}", 5 - i * 0.1, SourceType.EXA)
        for i in range(5)
    ]
    results = await builder._fetch_with_refill(
        ranked, budget=6, caps={SourceType.WEB: 2, SourceType.EXA: 99},
    )
    web_count = sum(1 for r in results if r.source_type == SourceType.WEB)
    assert web_count == 2
    assert len(results) == 6  # cap freed budget for the other type


@pytest.mark.asyncio
async def test_fetch_with_refill_handles_exhausted_ranked_list():
    builder = _builder_with_fake_fetchers()
    ranked = [_triaged("only", "https://x.test/1", 7.0)]
    results = await builder._fetch_with_refill(ranked, budget=5, caps={})
    assert len(results) == 1
