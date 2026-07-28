"""Reconstruct the discovery/screening funnel from the durable build event log.

The build pipeline already writes a per-stage event log to ``build_events``
(migration 010) so clients can reconnect to a running build. Those events are
also the only persisted record of what happened BEFORE validation — how many
candidates each fetcher returned, how many survived triage, how many were
actually downloaded. This module reads that log back.

Everything below is a pure function over a list of events, so the funnel logic
is testable without a database and without a build.

**What this module will not do:** infer a count it cannot see. Several numbers a
reviewer would want — why each candidate lost at triage, how many full fetches
failed — are simply not written down anywhere today. Those come back as ``None``
with an ``unavailable_reason``. See :data:`UNPERSISTED` for the full list and
``docs/audit-api.md`` for what it would take to persist each one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from peritus.jobs.domain import BuildEventRow

# Counts that no code path currently persists, with the reason surfaced to the
# client. Each entry is a promise: the API returns null here rather than a
# number that would look authoritative and be made up.
UNPERSISTED: dict[str, str] = {
    "triage_exclusion_reasons": (
        "Triage drops a candidate either for scoring below the minimum expected "
        "value or for having a near-duplicate title, but the ranker records only "
        "how many survived, not which rule removed each candidate. The split is "
        "not persisted, so it is not reported."
    ),
    "fetch_failures": (
        "The fetch stage refills from lower-ranked candidates when a download or "
        "OCR fails, and emits only the final fetched count. Failures are logged "
        "but not counted into the event log, so they cannot be separated from "
        "candidates that were never reached because the budget filled first."
    ),
    "per_fetcher_attribution_after_triage": (
        "Candidate counts are recorded per fetcher at search time. Triage, "
        "fetching and validation all operate on one pooled, de-duplicated list, "
        "so later stages cannot be attributed back to the fetcher that found "
        "each item. Per-fetcher numbers are therefore reported for the identify "
        "stage only."
    ),
    "gapfill_candidates_identified": (
        "The gap-fill round searches and fetches directly, bypassing the "
        "instrumented triage path, so it emits no per-fetcher candidate counts — "
        "only how many of its results survived validation."
    ),
}


# Event types the funnel reads. Anything else in the log is ignored here.
_EV_BUILD_STARTED = "build_started"
_EV_DISCOVERY_STARTED = "discovery_started"
_EV_FETCHER_DONE = "fetcher_done"
_EV_TRIAGE_DONE = "triage_done"
_EV_FETCH_DONE = "fetch_done"
_EV_SNOWBALL_DONE = "snowball_done"
_EV_VALIDATE_DONE = "validate_done"
_EV_COVERAGE_GAPS = "coverage_gaps"
_EV_GAPFILL_DONE = "gapfill_done"
_EV_STAGE = "stage"


@dataclass
class FetcherIdentified:
    """One fetcher's contribution to the candidate pool, as it reported it."""

    name: str
    candidates: int
    queries: int | None
    skipped: bool
    skip_reason: str | None


@dataclass
class DiscoveryFunnel:
    """Pre-validation funnel, reconstructed from one build attempt's event log."""

    fetchers_planned: list[str] = field(default_factory=list)
    fetchers_active: list[str] = field(default_factory=list)
    identified_by_fetcher: list[FetcherIdentified] = field(default_factory=list)
    identified_total: int | None = None
    screened_at_triage: int | None = None
    duplicates_removed_before_triage: int | None = None
    passed_triage: int | None = None
    excluded_at_triage: int | None = None
    fetch_budget: int | None = None
    fetched_full_text: int | None = None
    ranked_not_fetched: int | None = None
    snowballed_added: int | None = None
    gapfill_attempted: bool | None = None
    gapfill_concepts: list[str] = field(default_factory=list)
    gapfill_accepted: int | None = None
    gapfill_still_uncovered: list[str] = field(default_factory=list)
    # First-round validation totals as the pipeline reported them. The
    # authoritative validation numbers come from the `sources` table; these are
    # kept so a mismatch between log and table is visible rather than hidden.
    reported_validated_passed: int | None = None
    reported_validated_dropped: int | None = None
    stage_timings: list[dict[str, Any]] = field(default_factory=list)
    events_seen: int = 0


def latest_attempt(events: list[BuildEventRow]) -> list[BuildEventRow]:
    """Trim the log to the final attempt of a job.

    A job that retries keeps every attempt's events under the same ``job_id``
    (the worker appends a fresh ``build_started`` each time). Summing across
    attempts would double-count the funnel, so only the last attempt counts —
    it is the one whose output is in the database.
    """
    last_start = -1
    for i, ev in enumerate(events):
        if ev.type == _EV_BUILD_STARTED:
            last_start = i
    return events[last_start:] if last_start >= 0 else events


def _last(events: list[BuildEventRow], type_: str) -> dict[str, Any] | None:
    """Payload of the last event of a type, or None. Last wins: gap-fill and
    retry paths can emit the same event type more than once per attempt."""
    for ev in reversed(events):
        if ev.type == type_:
            return ev.payload
    return None


def _int(payload: dict[str, Any] | None, key: str) -> int | None:
    if not payload:
        return None
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _str_list(payload: dict[str, Any] | None, key: str) -> list[str]:
    if not payload:
        return []
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]


def derive_discovery_funnel(events: list[BuildEventRow]) -> DiscoveryFunnel | None:
    """Rebuild the pre-validation funnel, or ``None`` if the log cannot support it.

    ``None`` means "this expert has no retained discovery record" — it predates
    the durable job queue, its events were pruned, or its build never reached
    discovery. The caller reports that as an explicit gap; it must not be
    confused with a build that found nothing.
    """
    events = latest_attempt(events)
    if not events:
        return None

    fetcher_events = [e for e in events if e.type == _EV_FETCHER_DONE]
    triage = _last(events, _EV_TRIAGE_DONE)
    fetch = _last(events, _EV_FETCH_DONE)
    if not fetcher_events and triage is None and fetch is None:
        return None

    funnel = DiscoveryFunnel(events_seen=len(events))

    discovery = _last(events, _EV_DISCOVERY_STARTED)
    funnel.fetchers_planned = _str_list(discovery, "fetchers")
    funnel.fetchers_active = _str_list(discovery, "active")

    for ev in fetcher_events:
        payload = ev.payload
        name = payload.get("name")
        if not isinstance(name, str):
            continue
        reason = payload.get("reason")
        funnel.identified_by_fetcher.append(
            FetcherIdentified(
                name=name,
                candidates=_int(payload, "count") or 0,
                queries=_int(payload, "queries"),
                skipped=bool(payload.get("skipped")),
                skip_reason=reason if isinstance(reason, str) and reason else None,
            )
        )
    funnel.identified_by_fetcher.sort(key=lambda f: (-f.candidates, f.name))

    if fetcher_events:
        funnel.identified_total = sum(f.candidates for f in funnel.identified_by_fetcher)

    funnel.screened_at_triage = _int(triage, "candidates")
    funnel.passed_triage = _int(triage, "ranked")
    funnel.fetch_budget = _int(triage, "budget") or _int(fetch, "budget")

    # Fetchers de-duplicate by URL within themselves; the pooled list is
    # de-duplicated again across fetchers before triage. The difference between
    # the two is a real, derivable count of cross-fetcher overlap.
    if funnel.identified_total is not None and funnel.screened_at_triage is not None:
        delta = funnel.identified_total - funnel.screened_at_triage
        funnel.duplicates_removed_before_triage = delta if delta >= 0 else None

    if funnel.screened_at_triage is not None and funnel.passed_triage is not None:
        excluded = funnel.screened_at_triage - funnel.passed_triage
        funnel.excluded_at_triage = excluded if excluded >= 0 else None

    funnel.fetched_full_text = _int(fetch, "fetched")
    if funnel.passed_triage is not None and funnel.fetched_full_text is not None:
        remainder = funnel.passed_triage - funnel.fetched_full_text
        funnel.ranked_not_fetched = remainder if remainder >= 0 else None

    snowball = _last(events, _EV_SNOWBALL_DONE)
    if snowball is not None:
        funnel.snowballed_added = _int(snowball, "added")
    elif fetch is not None:
        # The pipeline emits snowball_done only when it added something, and it
        # runs immediately after fetching. A completed fetch stage with no
        # snowball event therefore means zero were added — not "unknown".
        funnel.snowballed_added = 0

    gaps = _last(events, _EV_COVERAGE_GAPS)
    gapfill = _last(events, _EV_GAPFILL_DONE)
    validate = _last(events, _EV_VALIDATE_DONE)
    if gaps is not None or gapfill is not None:
        funnel.gapfill_attempted = True
        funnel.gapfill_concepts = _str_list(gaps, "gaps")
        funnel.gapfill_accepted = _int(gapfill, "added")
        funnel.gapfill_still_uncovered = _str_list(gapfill, "still_uncovered")
    elif validate is not None:
        # Validation finished and no gap-fill events followed: every key concept
        # was already covered, so the round was skipped outright.
        funnel.gapfill_attempted = False
        funnel.gapfill_accepted = 0

    funnel.reported_validated_passed = _int(validate, "passed")
    funnel.reported_validated_dropped = _int(validate, "dropped")
    funnel.stage_timings = _stage_timings(events)
    return funnel


def _stage_timings(events: list[BuildEventRow]) -> list[dict[str, Any]]:
    """Wall-clock span of each pipeline stage, from consecutive `stage` events.

    The final stage's end is the last event in the log (usually ``done``), which
    is the closest thing to a finish time the log records.
    """
    marks: list[tuple[str, datetime]] = []
    for ev in events:
        if ev.type != _EV_STAGE:
            continue
        name = ev.payload.get("name")
        if isinstance(name, str) and (not marks or marks[-1][0] != name):
            marks.append((name, ev.created_at))
    if not marks:
        return []

    end = events[-1].created_at
    timings: list[dict[str, Any]] = []
    for i, (name, started) in enumerate(marks):
        finished = marks[i + 1][1] if i + 1 < len(marks) else end
        timings.append(
            {
                "stage": name,
                "started_at": started,
                "seconds": round(max(0.0, (finished - started).total_seconds()), 1),
            }
        )
    return timings
