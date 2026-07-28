"""Reconstructing the screening funnel from the durable build event log.

The properties under test are mostly about restraint: the funnel must reproduce
what the log recorded, refuse to report what it did not, and never double-count
a retried build.
"""

from datetime import UTC, datetime, timedelta

from peritus.audit.screening import (
    UNPERSISTED,
    derive_discovery_funnel,
    latest_attempt,
)
from peritus.jobs.domain import BuildEventRow

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def _ev(seq: int, type_: str, payload: dict | None = None, offset: int = 0) -> BuildEventRow:
    body = {"type": type_, **(payload or {})}
    return BuildEventRow(
        seq=seq, job_id=1, type=type_, payload=body,
        created_at=T0 + timedelta(seconds=offset),
    )


def _full_build() -> list[BuildEventRow]:
    """A healthy build: two fetchers, triage, a budgeted fetch, validation."""
    return [
        _ev(1, "build_started", {"attempt": 1, "max_attempts": 3}, 0),
        _ev(2, "stage", {"stage": 0, "name": "plan"}, 0),
        _ev(3, "stage", {"stage": 1, "name": "discover"}, 10),
        _ev(4, "discovery_started", {"fetchers": ["wikipedia", "arxiv", "reddit"],
                                     "active": ["wikipedia", "arxiv"]}, 10),
        _ev(5, "fetcher_done", {"name": "wikipedia", "count": 18, "skipped": False,
                                "reason": "", "queries": 3}, 20),
        _ev(6, "fetcher_done", {"name": "arxiv", "count": 12, "skipped": False,
                                "reason": "", "queries": 2}, 20),
        # 30 identified, 28 after cross-fetcher URL de-duplication.
        _ev(7, "triage_done", {"candidates": 28, "ranked": 16, "budget": 10}, 30),
        _ev(8, "fetch_done", {"fetched": 10, "budget": 10}, 60),
        _ev(9, "stage", {"stage": 2, "name": "validate", "total": 10}, 60),
        _ev(10, "validate_done", {"passed": 7, "dropped": 3}, 90),
        _ev(11, "done", {"source_count": 7}, 120),
    ]


# ── retries must not double-count ──

def test_latest_attempt_trims_to_the_final_build_started():
    events = [
        _ev(1, "build_started"),
        _ev(2, "fetcher_done", {"name": "wikipedia", "count": 5}),
        _ev(3, "retry", {"attempt": 1}),
        _ev(4, "build_started"),
        _ev(5, "fetcher_done", {"name": "wikipedia", "count": 9}),
    ]
    trimmed = latest_attempt(events)
    assert [e.seq for e in trimmed] == [4, 5]


def test_retried_build_reports_only_the_surviving_attempt():
    """The first attempt's corpus was wiped before the second started, so
    summing both attempts would describe rows that no longer exist."""
    events = [
        _ev(1, "build_started"),
        _ev(2, "fetcher_done", {"name": "wikipedia", "count": 5, "queries": 1}),
        _ev(3, "triage_done", {"candidates": 5, "ranked": 2, "budget": 4}),
        _ev(4, "retry", {"attempt": 1}),
        _ev(5, "build_started"),
        _ev(6, "fetcher_done", {"name": "wikipedia", "count": 20, "queries": 3}),
        _ev(7, "triage_done", {"candidates": 20, "ranked": 11, "budget": 4}),
    ]
    funnel = derive_discovery_funnel(events)
    assert funnel is not None
    assert funnel.identified_total == 20
    assert funnel.screened_at_triage == 20
    assert funnel.passed_triage == 11


# ── the counts the log does support ──

def test_funnel_counts_match_the_log():
    funnel = derive_discovery_funnel(_full_build())
    assert funnel is not None
    assert funnel.identified_total == 30
    assert funnel.screened_at_triage == 28
    assert funnel.duplicates_removed_before_triage == 2
    assert funnel.passed_triage == 16
    assert funnel.excluded_at_triage == 12
    assert funnel.fetched_full_text == 10
    assert funnel.fetch_budget == 10
    assert funnel.ranked_not_fetched == 6
    assert funnel.reported_validated_passed == 7
    assert funnel.reported_validated_dropped == 3


def test_fetchers_are_reported_with_their_query_counts_and_skips():
    events = _full_build() + [
        _ev(12, "fetcher_done", {"name": "pdf", "count": 0, "skipped": True,
                                 "reason": "no MISTRAL_API_KEY", "queries": 2}, 20),
    ]
    funnel = derive_discovery_funnel(events)
    assert funnel is not None
    by_name = {f.name: f for f in funnel.identified_by_fetcher}
    assert by_name["wikipedia"].candidates == 18
    assert by_name["wikipedia"].queries == 3
    assert by_name["pdf"].skipped is True
    assert by_name["pdf"].skip_reason == "no MISTRAL_API_KEY"
    assert funnel.fetchers_planned == ["wikipedia", "arxiv", "reddit"]
    assert funnel.fetchers_active == ["wikipedia", "arxiv"]


def test_absent_snowball_event_after_a_completed_fetch_is_zero():
    """The pipeline emits snowball_done only when it added something, and it
    runs right after fetching — so silence there is a real zero."""
    funnel = derive_discovery_funnel(_full_build())
    assert funnel is not None
    assert funnel.snowballed_added == 0


def test_snowball_count_is_read_when_present():
    events = _full_build() + [_ev(12, "snowball_done", {"added": 3}, 55)]
    funnel = derive_discovery_funnel(events)
    assert funnel is not None
    assert funnel.snowballed_added == 3


def test_gapfill_round_is_reported_with_its_concepts():
    events = _full_build() + [
        _ev(12, "coverage_gaps", {"gaps": ["Stoic physics", "oikeiosis"]}, 95),
        _ev(13, "gapfill_done", {"added": 1, "still_uncovered": ["oikeiosis"]}, 110),
    ]
    funnel = derive_discovery_funnel(events)
    assert funnel is not None
    assert funnel.gapfill_attempted is True
    assert funnel.gapfill_concepts == ["Stoic physics", "oikeiosis"]
    assert funnel.gapfill_accepted == 1
    assert funnel.gapfill_still_uncovered == ["oikeiosis"]


def test_no_gapfill_events_after_validation_means_no_gaps():
    funnel = derive_discovery_funnel(_full_build())
    assert funnel is not None
    assert funnel.gapfill_attempted is False
    assert funnel.gapfill_accepted == 0


def test_stage_timings_are_derived_from_consecutive_stage_marks():
    funnel = derive_discovery_funnel(_full_build())
    assert funnel is not None
    timings = {t["stage"]: t["seconds"] for t in funnel.stage_timings}
    assert timings["plan"] == 10.0
    assert timings["discover"] == 50.0
    # The final stage runs to the last event in the log.
    assert timings["validate"] == 60.0


# ── the counts the log does not support ──

def test_no_events_yields_no_funnel_rather_than_zeros():
    """An expert with no retained log has an unknown funnel, not an empty one."""
    assert derive_discovery_funnel([]) is None
    assert derive_discovery_funnel([_ev(1, "build_started"), _ev(2, "done")]) is None


def test_unpersisted_counts_are_documented_not_guessed():
    for key in (
        "triage_exclusion_reasons",
        "fetch_failures",
        "per_fetcher_attribution_after_triage",
        "gapfill_candidates_identified",
    ):
        assert key in UNPERSISTED
        assert len(UNPERSISTED[key]) > 40  # an actual explanation, not a label


def test_impossible_arithmetic_is_dropped_rather_than_reported_negative():
    """A truncated or out-of-order log must not produce a negative count."""
    events = [
        _ev(1, "build_started"),
        _ev(2, "fetcher_done", {"name": "wikipedia", "count": 3, "queries": 1}),
        _ev(3, "triage_done", {"candidates": 9, "ranked": 12, "budget": 4}),
        _ev(4, "fetch_done", {"fetched": 20, "budget": 4}),
    ]
    funnel = derive_discovery_funnel(events)
    assert funnel is not None
    assert funnel.duplicates_removed_before_triage is None
    assert funnel.excluded_at_triage is None
    assert funnel.ranked_not_fetched is None


def test_missing_triage_event_leaves_its_counts_none():
    events = [
        _ev(1, "build_started"),
        _ev(2, "fetcher_done", {"name": "wikipedia", "count": 7, "queries": 1}),
    ]
    funnel = derive_discovery_funnel(events)
    assert funnel is not None
    assert funnel.identified_total == 7
    assert funnel.screened_at_triage is None
    assert funnel.passed_triage is None
    assert funnel.excluded_at_triage is None
    # No completed fetch stage, so snowballing is unknown rather than zero.
    assert funnel.snowballed_added is None
