"""Stages 1–2: the pieces of a discovery round that need no coordinator.

`ExpertBuilder` next door drives the loop — how many rounds, what each round
searches for, when to stop. What lives here is everything a round does to one
candidate or one fetcher, and the two wrappers that decide what a failure means.

`_safe_search` and `_safe_fetch_candidate` are the load-bearing pair.
Discovery talks to eleven third-party services, and any of them can be down,
rate-limited, or simply slow. One fetcher failing must cost that fetcher's
results and nothing else — but a failure that is *silent* is worse than one that
stops the build, because it produces a thin corpus nobody can explain. Both
record what happened, in the vocabulary the audit surface reads back.

`_raise_if_provider_down` is the exception: some failures are not this
fetcher's, they are "the LLM was never reachable", and retrying those costs three
builds' worth of fetching to arrive at the same place.
"""

import asyncio
import time
from dataclasses import dataclass

from peritus.core.config import settings
from peritus.core.exceptions import BuildError
from peritus.core.logging import get_logger
from peritus.experts.build.constants import (
    _CARRIED_METADATA,
    _SLOW_SEARCH_SECONDS,
)
from peritus.experts.coverage import CoverageReport
from peritus.infrastructure.anthropic_batch import (
    provider_error_message,
    terminal_provider_error,
)
from peritus.sources.canonical import (
    FOUND_WHOLE,
    SCOPE_CONCEPT,
    SCOPE_FIGURE,
    SCOPE_OVERALL,
    ArchiveTextFetcher,
    MustHaveWork,
    WorkResolution,
    archive_identifier,
    must_have_outcomes,
    title_key,
)
from peritus.sources.domain import (
    DroppedSource,
    RawSource,
    SourceCandidate,
    SourceType,
    ValidatedSource,
)
from peritus.sources.fetchers.base import (
    STATUS_EMPTY,
    STATUS_OK,
    SearchOutcome,
    begin_search_note,
    end_search_note,
    worst_status,
)
from peritus.sources.fetchers.exa import ExaFetcher
from peritus.sources.fetchers.gutenberg import GutenbergFetcher
from peritus.sources.fetchers.openalex import OpenAlexFetcher
from peritus.sources.fulltext import default_method_for
from peritus.sources.sections import apply_sections
from peritus.sources.validator import RUBRIC_VERSION

logger = get_logger(__name__)


@dataclass
class DiscoveryOutcome:
    """What the discovery loop produced, and why it stopped.

    Stored on ``experts.build_summary`` and emitted as ``discovery_done``. The
    stop reason is the part that matters: "the corpus has 34 sources" is not a
    claim anyone can check, and "the corpus met its coverage targets in two
    rounds" or "the corpus stopped at the discovery budget with two concepts
    short" both are.
    """

    passed: list[ValidatedSource]
    dropped: list[DroppedSource]
    coverage: CoverageReport
    rounds: int
    stop_reason: str
    spent_usd: float
    committed_usd: float
    budget_usd: float
    # What the corpus is made of — tier shares, abstract-only share, junk
    # fetched, concept shares, must-have works found whole or in part. The
    # numbers docs/plans/source-selection.md is judged by.
    corpus: dict | None = None
    # Channels whose last search failed rather than came back empty, by status.
    channels: dict[str, str] | None = None

    def summary(self) -> dict:
        return {
            "rounds": self.rounds,
            "stop_reason": self.stop_reason,
            "accepted": len(self.passed),
            "rejected": len(self.dropped),
            "spent_usd": round(self.spent_usd, 4),
            "estimated_ingest_usd": round(self.committed_usd, 4),
            "budget_usd": round(self.budget_usd, 4),
            "rubric_version": RUBRIC_VERSION,
            "coverage": self.coverage.as_dict(),
            "corpus": self.corpus or {},
            "failed_channels": self.channels or {},
        }


def _outcome_metadata(passed: list[ValidatedSource]) -> list[tuple[str, dict]]:
    """Accepted sources as the must-have outcome reads them: metadata plus tier."""
    return [(vs.url, {**vs.raw.metadata, "source_tier": vs.source_tier}) for vs in passed]


def _is_skipped(name: str, results: list) -> tuple[bool, str]:
    if results:
        return False, ""
    if name in ("youtube", "exa") and not settings.EXA_API_KEY:
        return True, "no EXA_API_KEY"
    if name == "pdf" and not settings.MISTRAL_API_KEY:
        return True, "no MISTRAL_API_KEY"
    return False, ""


async def _safe_search(name: str, fetcher, query: str, max_results: int) -> SearchOutcome:
    """One search call, and why it came back with what it did. Never raises.

    ``empty`` means the channel answered and had nothing; ``timeout``,
    ``rate_limited`` and ``error`` mean it did not answer — whether the fetcher
    raised or swallowed the failure and noted it (see fetchers/base.py).
    """
    from peritus.sources.fetchers.exa import classify_search_error

    started = time.monotonic()
    note, token = begin_search_note()
    try:
        results = await fetcher.search(query, max_results)
    except Exception as exc:
        elapsed = time.monotonic() - started
        logger.warning(
            "Fetcher %r search failed for %r after %.1fs (%s: %s)",
            name,
            query,
            elapsed,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        status, error = classify_search_error(exc, name)
        return SearchOutcome([], status, error, elapsed)
    finally:
        end_search_note(token)
    elapsed = time.monotonic() - started
    # Discovery gathers every fetcher, so the slowest one sets the stage's floor.
    # Naming it at WARNING is what turns "discovery took five minutes" into
    # "gutenberg took four and a half of them".
    log = logger.warning if elapsed > _SLOW_SEARCH_SECONDS else logger.debug
    log(
        "Fetcher %r search %r: %d result(s) in %.1fs%s",
        name,
        query,
        len(results),
        elapsed,
        " — slow, this holds up the whole discovery stage"
        if elapsed > _SLOW_SEARCH_SECONDS
        else "",
    )
    if results:
        return SearchOutcome(list(results), STATUS_OK, "", elapsed)
    if note.failures:
        status = worst_status([status for status, _ in note.failures])
        error = next(err for st, err in note.failures if st == status)
        logger.warning("Fetcher %r search %r returned nothing: %s (%s)", name, query, status, error)
        return SearchOutcome([], status, error, elapsed)
    return SearchOutcome([], STATUS_EMPTY, "", elapsed)


def _fetcher_for(candidate: SourceCandidate, fetcher_by_type: dict):
    """The fetcher that can download this candidate.

    Canonical-work candidates can come from routes no planned fetcher covers — an
    Internet Archive item, a Gutenberg volume when the planner weighted
    gutenberg to 0 — and must still be fetchable.
    """
    # Any archive.org item, however it was found: its catalogue page is not its
    # text, and only the archive fetcher checks the item may be reused.
    if candidate.metadata.get("canonical_fetcher") == "archive" or archive_identifier(
        candidate.url
    ):
        return ArchiveTextFetcher()
    fetcher = fetcher_by_type.get(candidate.source_type)
    if fetcher is None and candidate.metadata.get("canonical_route"):
        if candidate.source_type is SourceType.GUTENBERG:
            return GutenbergFetcher()
        if candidate.source_type is SourceType.EXA:
            return ExaFetcher()
        if candidate.source_type is SourceType.OPENALEX:
            return OpenAlexFetcher()
    return fetcher


def _carry_candidate_metadata(candidate: SourceCandidate, source: RawSource, score: float) -> None:
    """Copy the selection facts a fetcher may not have onto the fetched source."""
    for key in _CARRIED_METADATA:
        if key in candidate.metadata and key not in source.metadata:
            source.metadata[key] = candidate.metadata[key]
    source.metadata["triage_score"] = round(score, 2)


def _planned_works(plan: dict, config) -> list[MustHaveWork]:
    """The works the plan names, as many as the tier affords.

    The topic's canonical works, then the primary text for each concept, then a
    work in each named figure's own voice. A work named at more than one scope
    is resolved once (sources/canonical.py, merge_works).
    """
    return (
        [MustHaveWork.from_plan(w, SCOPE_OVERALL) for w in plan.get("must_have_works") or []]
        + [
            MustHaveWork.from_plan(w, SCOPE_CONCEPT)
            for w in (plan.get("concept_primary_texts") or [])[: config.concept_primary_texts]
        ]
        + _figure_works(plan.get("figures") or [], config.figure_texts)
    )


def _figure_works(figures: list[dict], limit: int) -> list[MustHaveWork]:
    """One lookup per named figure with an obtainable work, up to the tier's limit."""
    works: list[MustHaveWork] = []
    for figure in figures:
        if len(works) >= limit:
            break
        # The plan keeps a work only for an obtainable figure, with the figure as
        # its author when none was given (_normalise_figures).
        if isinstance(figure.get("work"), dict):
            work = MustHaveWork.from_plan(figure["work"], SCOPE_FIGURE)
            work.figure = str(figure.get("name") or "")
            works.append(work)
    return works


def _enforce_ceiling(candidate: SourceCandidate, source: RawSource) -> None:
    """Cut a fetched text to the ceiling its candidate was stamped with.

    The fetchers that cut named sections apply the ceiling themselves, and a
    live Thomism build still stored the Summa's first part at 584,000
    characters against a 200,000 ceiling — a third of the round's estimated
    ingest in one volume. Whichever path skipped it, the ceiling is enforced
    here, where every fetch arrives, and the log names the fetcher so the next
    build says which path it was. The cut is the same one the fetchers make —
    the named sections first, then the ceiling — so a path that skipped it keeps
    the passages the plan asked for rather than the work's opening.
    """
    ceiling = candidate.metadata.get("text_max_chars")
    if not isinstance(ceiling, int) or ceiling <= 0 or len(source.text) <= ceiling:
        return
    logger.warning(
        "ceiling_enforced: %s returned %d chars for %r against a %d ceiling — cut",
        candidate.metadata.get("canonical_fetcher") or candidate.source_type.value,
        len(source.text),
        candidate.title,
        ceiling,
    )
    source.text, selected = apply_sections(source.text, candidate.metadata, ceiling)
    source.metadata.update(selected, truncated=True, ceiling_enforced=True)


def _boosted_must_have_titles(
    titles: list[str],
    round_n: int,
    resolutions: list[WorkResolution],
    passed: list[ValidatedSource],
) -> list[str]:
    """The must-have titles a round's triage still lifts to the front of the queue.

    Not a work already found whole. The boost exists so a canonical work found by
    search is not lost to its score; once the work is in hand it only lifts pages
    that share its name. Round 1 of a live Thomism build fetched five boosted
    hits with the Summa's first part already in the corpus, three of them not
    the work.

    Round 0 has no corpus yet, so a work the resolver found whole (its
    candidate already jumps the queue) is dropped from the boost; later rounds
    drop a work once it is found whole in the accepted corpus — which keeps the
    boost for a work whose whole copy failed to download.
    """
    if round_n == 0:
        whole = {title_key(r.work.title) for r in resolutions if r.whole}
    else:
        whole = {
            title_key(o["title"])
            for o in must_have_outcomes(
                [MustHaveWork(t) for t in titles], resolutions, _outcome_metadata(passed)
            )
            if o["status"] == FOUND_WHOLE
        }
    return [t for t in titles if title_key(t) not in whole]


def _count_outcomes(outcomes) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _rank, outcome in outcomes:
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


def _as_score(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _quietly(what: str, awaitable) -> None:
    """Await a record-keeping write that must never fail the build it records.

    The ledger, the stored plan and their links are for auditing selection
    afterwards. A database blip there costs the audit trail for one build, and
    says so in the log; it must not cost the build.
    """
    try:
        await awaitable
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Could not %s (%s: %s)", what, type(exc).__name__, exc)


async def _safe_fetch_candidate(fetcher, candidate: SourceCandidate) -> RawSource | None:
    """Fetch one candidate's full content, or None. Never raises, never hangs.

    The wall-clock cap matters as much as the exception handling. Each fetcher
    sets httpx timeouts, but httpx's are per-operation: a server that sends a
    byte before every read deadline satisfies all of them forever. One such URL
    inside a fetch wave stalls the wave, and the fetch stage is the longest
    event-silent stretch of the build — so the symptom is a build that simply
    stops, with a full progress bar and nothing to say why.
    """
    if fetcher is None:
        return None
    try:
        source = await asyncio.wait_for(
            fetcher.fetch(candidate), timeout=settings.SOURCE_FETCH_TIMEOUT
        )
        if source is not None:
            _stamp_retrieval_method(source)
        return source
    except TimeoutError:
        logger.warning(
            "Full fetch timed out after %.0fs for %s %r — abandoning candidate",
            settings.SOURCE_FETCH_TIMEOUT,
            candidate.source_type.value,
            candidate.url,
        )
        return None
    except Exception as exc:
        logger.warning(
            "Full fetch failed for %s %r (%s: %s)",
            candidate.source_type.value,
            candidate.url,
            type(exc).__name__,
            exc,
        )
        return None


def _stamp_retrieval_method(source: RawSource) -> None:
    """Record how this source's text was obtained, for fetchers that don't.

    The scholarly fetchers go through the full-text resolver and record the step
    it took. The rest have exactly one way of getting text, so the value is
    known — and leaving it NULL would say "unknown" about a retrieval that was
    never in doubt, both in the ledger and in the preview the validator reads.
    """
    if source.metadata.get("full_text_method"):
        return
    method = default_method_for(source.source_type.value)
    if method:
        source.metadata["full_text_method"] = method


def _raise_if_provider_down(stage: str) -> None:
    """Fail with the provider's own words when the LLM was never reachable.

    A ``BuildError`` deliberately: the worker treats those as non-retryable, and
    an empty credit balance or a rejected key will fail identically on every
    attempt. Retrying costs three builds' worth of fetching to reach the same
    place, and buries the one sentence that says how to fix it.
    """
    exc = terminal_provider_error()
    if exc is None:
        return
    message = provider_error_message(exc)
    logger.error("%s could not run — terminal provider error: %s", stage, message)
    raise BuildError(f"{stage} could not run — the Anthropic API rejected every request: {message}")
