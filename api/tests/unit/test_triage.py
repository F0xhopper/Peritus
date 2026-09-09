"""Unit tests for candidate triage ranking and the budgeted fetch-with-refill."""

import asyncio

import pytest

from peritus.core.config import settings
from peritus.experts.builder import ExpertBuilder, _safe_fetch_candidate
from peritus.sources.domain import RawSource, SourceCandidate, SourceType
from peritus.sources.triage import (
    TriagedCandidate,
    _matches_must_have,
    domain_adjustment,
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
    results, _committed = await builder._fetch_with_refill(ranked, budget=4, caps={SourceType.WEB: 99})
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
    results, _committed = await builder._fetch_with_refill(ranked, budget=3, caps={SourceType.WEB: 99})
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
    results, _committed = await builder._fetch_with_refill(
        ranked, budget=6, caps={SourceType.WEB: 2, SourceType.EXA: 99},
    )
    web_count = sum(1 for r in results if r.source_type == SourceType.WEB)
    assert web_count == 2
    assert len(results) == 6  # cap freed budget for the other type


@pytest.mark.asyncio
async def test_fetch_with_refill_handles_exhausted_ranked_list():
    builder = _builder_with_fake_fetchers()
    ranked = [_triaged("only", "https://x.test/1", 7.0)]
    results, _committed = await builder._fetch_with_refill(ranked, budget=5, caps={})
    assert len(results) == 1


@pytest.mark.asyncio
async def test_fetch_with_refill_reports_progress_between_waves():
    """The fetch stage must never go dark.

    Between `triage_done` and `fetch_done` this stage does all its network work
    and used to emit nothing at all, so a wedged worker and a busy one looked
    identical for as long as anyone watched. Every wave now reports.
    """
    builder = _builder_with_fake_fetchers()
    events: list[dict] = []

    async def on_event(e: dict) -> None:
        events.append(e)

    ranked = [_triaged(f"t{i}", f"https://x.test/{i}", 9 - i * 0.1) for i in range(12)]
    results, _committed = await builder._fetch_with_refill(
        ranked, budget=12, caps={SourceType.WEB: 99}, on_event=on_event,
    )

    progress = [e for e in events if e["type"] == "fetch_progress"]
    assert len(progress) >= 2, "a multi-wave fetch must report more than once"
    # Monotonic, and the last one agrees with what was actually returned.
    assert [e["fetched"] for e in progress] == sorted(e["fetched"] for e in progress)
    assert progress[-1]["fetched"] == len(results)
    assert progress[-1]["attempted"] >= progress[-1]["fetched"]
    assert all(e["budget"] == 12 for e in progress)


@pytest.mark.asyncio
async def test_safe_fetch_candidate_bounds_a_hanging_fetcher(monkeypatch):
    """A fetcher that never returns costs one slot, not the build.

    httpx's timeouts are per-operation, so a server that dribbles a byte before
    every read deadline satisfies all of them indefinitely. Only a wall-clock cap
    catches that, and without one the whole wave — and the stage — stops.
    """
    monkeypatch.setattr(settings, "SOURCE_FETCH_TIMEOUT", 0.05)

    class _HangingFetcher:
        async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
            await asyncio.sleep(3600)
            raise AssertionError("unreachable")

    result = await asyncio.wait_for(
        _safe_fetch_candidate(_HangingFetcher(), _candidate("hangs", "https://slow.test")),
        timeout=5,
    )
    assert result is None


@pytest.mark.asyncio
async def test_fetch_with_refill_refills_past_a_hanging_candidate(monkeypatch):
    """The abandoned slot goes to the next candidate down, like any other failure."""
    monkeypatch.setattr(settings, "SOURCE_FETCH_TIMEOUT", 0.05)

    class _MixedFetcher:
        async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
            if "hang" in candidate.url:
                await asyncio.sleep(3600)
            return RawSource(
                source_type=candidate.source_type,
                url=candidate.url,
                title=candidate.title,
                author=None,
                text="x" * 1000,
            )

    builder = ExpertBuilder.__new__(ExpertBuilder)
    builder._fetchers = {"web": (_MixedFetcher(), 3)}

    ranked = [_triaged("hangs", "https://hang.test", 9.9)] + [
        _triaged(f"t{i}", f"https://x.test/{i}", 8 - i * 0.1) for i in range(4)
    ]
    results, _committed = await asyncio.wait_for(
        builder._fetch_with_refill(ranked, budget=3, caps={SourceType.WEB: 99}),
        timeout=10,
    )
    assert len(results) == 3
    assert "hangs" not in [r.title for r in results]


# --- domain priors ---------------------------------------------------------
#
# The signal that title-and-snippet triage cannot provide: a page *about* a work
# reads exactly like the work. These are a hand-maintained table, so the tests
# pin the matching rules rather than every entry — a wrong suffix match is the
# failure mode that would quietly mis-score a whole class of sources.


def test_domain_adjustment_penalises_summary_and_review_hosts():
    assert domain_adjustment("https://www.goodreads.com/book/show/1234") < 0
    assert domain_adjustment("https://sparknotes.com/lit/meditations/") < 0
    assert domain_adjustment("https://brainyquote.com/authors/seneca") < 0


def test_domain_adjustment_boosts_primary_and_scholarly_hosts():
    assert domain_adjustment("https://www.gutenberg.org/ebooks/2680") > 0
    assert domain_adjustment("https://plato.stanford.edu/entries/stoicism/") > 0
    assert domain_adjustment("https://arxiv.org/abs/2401.00001") > 0


def test_domain_adjustment_matches_on_label_boundary():
    """``notgoodreads.com`` must not inherit ``goodreads.com``'s penalty."""
    assert domain_adjustment("https://notgoodreads.com/x") == 0.0
    assert domain_adjustment("https://mygoodreads.com.example.test/x") == 0.0
    # A genuine subdomain still matches.
    assert domain_adjustment("https://m.goodreads.com/book/1") < 0


def test_domain_adjustment_most_specific_host_wins_and_does_not_stack():
    """Longest matching pattern wins; host rules never sum."""
    specific = domain_adjustment("https://plato.stanford.edu/entries/stoicism/")
    generic = domain_adjustment("https://cs.stanford.edu/some/page")
    assert specific != generic
    # Stacking would exceed any single entry in the table; it must not.
    assert specific == max(specific, generic, key=abs)


def test_domain_adjustment_path_rules_apply_to_neutral_hosts():
    neutral = domain_adjustment("https://example.test/article")
    reviewish = domain_adjustment("https://example.test/reviews/the-book")
    assert neutral == 0.0
    assert reviewish < neutral


def test_domain_adjustment_is_total_on_bad_input():
    """Never raises: an unparseable URL just means the model's score stands."""
    assert domain_adjustment("") == 0.0
    assert domain_adjustment("not a url") == 0.0
    assert domain_adjustment("gutenberg.org/ebooks/1") > 0  # scheme-less still parses


# ── fetch ordering ──────────────────────────────────────────────────────────
#
# The regression these pin was found in a finished corpus, not in the code. A
# STANDARD build of "Thomism" produced 48 sources containing no work by Aquinas,
# 17 tertiary to 2 primary, while its research plan had correctly named the
# Summa Theologica a must-have and weighted Project Gutenberg at 2.0. The cause
# was ordering the fetch queue by `triage_score / estimated_cost`: cost scales
# with length, the longest texts are the primary sources, and so the rule
# removed exactly the material the corpus most needed.


def _ordered(*items):
    from peritus.experts.builder import _fetch_sort_key

    return [t.candidate.title for t in sorted(items, key=lambda t: _fetch_sort_key(t, False))]


def _c(source_type, score, title, priority=False):
    t = _triaged(title, "https://x.test/" + title.replace(" ", "-"), score)
    t.candidate.source_type = source_type
    if priority:
        t.candidate.metadata["fetch_priority"] = True
    return t


def test_a_primary_text_is_not_outranked_by_a_forum_post_for_being_long():
    """The exact inversion that emptied a Thomism corpus of Aquinas."""
    summa = _c(SourceType.GUTENBERG, 9.0, "Summa Theologica")
    reddit = _c(SourceType.REDDIT, 4.0, "a Reddit thread")
    assert _ordered(reddit, summa)[0] == "Summa Theologica"


def test_quality_decides_the_order_and_cost_only_breaks_ties():
    """Cost-awareness was for choosing between comparable candidates — free full
    text before paid OCR — not for choosing what the corpus is made of."""
    cheap_low = _c(SourceType.WEB, 5.0, "a mediocre web page")
    dear_high = _c(SourceType.GUTENBERG, 8.0, "a classic text")
    assert _ordered(cheap_low, dear_high) == ["a classic text", "a mediocre web page"]

    # Equal score: the cheaper one goes first, which is the phase 2.C behaviour.
    paper = _c(SourceType.OPENALEX, 7.0, "a journal paper")
    book = _c(SourceType.GUTENBERG, 7.0, "a long book")
    assert _ordered(book, paper) == ["a journal paper", "a long book"]


def test_a_must_have_work_is_fetched_before_anything_else():
    """The score-9 override exists so a work the plan named cannot be lost. It
    is a flag as well as a score, because a score can be divided away."""
    must_have = _c(SourceType.GUTENBERG, 9.0, "Summa Theologica", priority=True)
    excellent = _c(SourceType.OPENALEX, 10.0, "a superb cheap paper")
    assert _ordered(excellent, must_have)[0] == "Summa Theologica"


def test_triage_marks_a_must_have_work_not_merely_scores_it():
    from peritus.sources.triage import _matches_must_have

    assert _matches_must_have("Summa Theologica", ["Summa Theologica"])
    # And the marking is what the fetch stage keys on, so it must survive onto
    # the candidate rather than living only in the score.
    marked = _c(SourceType.GUTENBERG, 9.0, "Summa Theologica", priority=True)
    assert marked.candidate.metadata["fetch_priority"] is True


def test_scores_are_bucketed_so_noise_does_not_beat_a_real_cost_difference():
    """A 7.2 and a 7.0 are the same judgement; the cheaper one should win."""
    noisy_dear = _c(SourceType.GUTENBERG, 7.2, "a long book")
    clean_cheap = _c(SourceType.WEB, 7.0, "a cheap article")
    assert _ordered(noisy_dear, clean_cheap) == ["a cheap article", "a long book"]
