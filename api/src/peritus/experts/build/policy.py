"""What a build is allowed to spend, and what it spends it on first.

Two questions, both answered before any money moves.

**Policy** — `resolve_execution` and `discovery_loop_enabled` decide, once per
build, whether Claude calls run live or batched and whether discovery may loop.
Both read `auto` off the build itself rather than off a fixed default, because
the right answer differs between a user watching their first build and a
scheduled rebuild nobody is waiting on.

**Priority** — `_fetch_sort_key` is the order the fetch queue runs in, and it is
value-per-dollar, not score. A cheap source scoring 7 is a better buy than an
expensive one scoring 8, and with a bounded budget the order *is* the selection:
whatever is at the back is what gets dropped.
"""

import math
from decimal import Decimal

from peritus.billing.metering import current_meter
from peritus.billing.pricing import estimated_ingest_cost_usd, estimated_ocr_pages
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.build.constants import (
    _DEFAULT_EXPECTED_CHARS,
    _EXPECTED_CHARS,
    _FETCHER_SOURCE_TYPES,
    _MIN_RESULTS_PER_QUERY,
    _PRIMARY_TEXT_CHARS,
    _SEARCH_OVERFETCH,
    _TYPE_CAP_HEADROOM,
    _TYPE_CAP_MIN,
    _VALUE_COST_FLOOR,
)
from peritus.experts.domain import Expert, ExpertTier
from peritus.infrastructure.anthropic_batch import BuildExecution, current_execution
from peritus.sources.domain import RawSource, SourceCandidate, SourceType
from peritus.sources.fulltext import PAID_METHODS, FullTextHints, expected_method
from peritus.sources.triage import TriagedCandidate

logger = get_logger(__name__)


def _metered_spend() -> Decimal:
    """What this build has actually spent so far, per the meter. 0 with no meter."""
    meter = current_meter()
    return Decimal(str(meter.spent_usd)) if meter is not None else Decimal(0)


def _ingest_estimate(source: RawSource, batched: bool) -> Decimal:
    """Forecast of what ingesting this fetched source will cost."""
    pages = (
        estimated_ocr_pages(len(source.text))
        if source.metadata.get("full_text_method") in PAID_METHODS
        else 0
    )
    return estimated_ingest_cost_usd(len(source.text), pages, batch=batched)


def _prefetch_cost_estimate(candidate: SourceCandidate, batched: bool) -> Decimal:
    """Forecast of a candidate's ingest cost *before* it is fetched.

    Length is a per-source-type prior (see :data:`_EXPECTED_CHARS`) rather than
    a measurement, which is the best that can be done before the download. It
    only has to be right about the order of magnitude, because all it decides is
    the order of the fetch queue.
    """
    chars = _EXPECTED_CHARS.get(candidate.source_type, _DEFAULT_EXPECTED_CHARS)
    method = expected_method(candidate.identifiers, FullTextHints.from_candidate(candidate))
    pages = estimated_ocr_pages(chars) if method in PAID_METHODS else 0
    return estimated_ingest_cost_usd(chars, pages, batch=batched)


def resolve_execution(expert: Expert) -> BuildExecution:
    """Pick the cost/latency policy for a build that didn't state one.

    ``BUILD_EXECUTION_DEFAULT=auto`` (the default) reads it off the expert: an
    expert that has never produced a persona has never finished a build, so
    somebody is sitting in front of the progress log waiting for their first
    expert — that build runs live. Anything else is a rebuild or a refresh of an
    expert that already works, which nobody is blocked on, so it takes the
    half-price batched path.

    ``reset_build_state`` deletes sources, chunks and the graph but leaves the
    persona, so this signal survives the reset the worker does immediately
    before calling us. A retry of a *failed* first build still reads as a first
    build, which is what we want: the user is still waiting.
    """
    configured = settings.BUILD_EXECUTION_DEFAULT
    if configured in (BuildExecution.INTERACTIVE, BuildExecution.BACKGROUND):
        return BuildExecution(configured)
    if configured != "auto":
        logger.warning("Unknown BUILD_EXECUTION_DEFAULT=%r — falling back to 'auto'", configured)
    return BuildExecution.BACKGROUND if expert.persona_name else BuildExecution.INTERACTIVE


def discovery_loop_enabled() -> bool:
    """Whether this build may run more than one discovery round.

    ``auto`` (the default) turns the loop on for interactive builds and off for
    batched ones: in BACKGROUND mode each round's validation is its own Message
    Batch that can queue for up to an hour, so three rounds of a PRO build could
    take most of a day for a saving nobody is waiting on.
    """
    configured = settings.DISCOVERY_LOOP
    if configured in ("true", "1", "yes", "on"):
        return True
    if configured in ("false", "0", "no", "off"):
        return False
    if configured != "auto":
        logger.warning("Unknown DISCOVERY_LOOP=%r — falling back to 'auto'", configured)
    return current_execution() is not BuildExecution.BACKGROUND


def _log_previous_build(expert: Expert, batched: bool) -> None:
    """Note what the last build of this expert concluded, before starting over.

    A stub, deliberately. A rebuild currently wipes the corpus and runs round 0
    blind, which means it re-discovers everything the previous build already
    established and re-pays for all of it — and in BACKGROUND mode each round
    queues its own Message Batch on top. The fix is a rebuild that starts from
    the stored summary and reports what is *new* since the last build, which is
    the "living review" follow-on in docs/plans/corpus-quality.md. Until then
    this at least puts the previous conclusion in the log next to the new one,
    so the two can be compared without querying the database.
    """
    summary = getattr(expert, "build_summary", None)
    if not isinstance(summary, dict) or not summary:
        return
    logger.info(
        "Rebuilding %r: the previous build ran %s round(s) and stopped with %r, "
        "accepting %s source(s)%s. This build starts from nothing — the corpus was "
        "wiped — so that work is being redone.",
        expert.name,
        summary.get("rounds"),
        summary.get("stop_reason"),
        summary.get("accepted"),
        " (and this one batches each round separately)" if batched else "",
    )


def _priority_reservation(candidate: SourceCandidate, batched: bool) -> Decimal:
    """What a priority candidate is expected to cost, before it is fetched.

    A resolved work carries its text ceiling, which is the honest upper bound;
    anything else falls back to its source type's typical length.
    """
    ceiling = candidate.metadata.get("text_max_chars")
    if isinstance(ceiling, int) and ceiling > 0:
        return estimated_ingest_cost_usd(ceiling, 0, batch=batched)
    return _prefetch_cost_estimate(candidate, batched)


def _fetch_sort_key(triaged: TriagedCandidate, batched: bool) -> tuple[int, float, float]:
    """The order the fetch stage works through its ranked candidates.

    Quality first, cost as the tiebreaker — **not** value per dollar.

    Ordering by ``score / cost`` is what phase 6.C of the plan asked for, and it
    is wrong in a way that only shows up in the finished corpus: cost scales
    with length, the longest texts are the primary sources, so the rule
    systematically strips a corpus of the material it most needs. Measured on a
    live build of "Thomism": a Reddit thread scoring 4 outranked the Summa
    Theologica scoring 9 by seven to one, Project Gutenberg's three hits were
    buried below the fetch budget, and the finished expert contained no work by
    Aquinas at all — while the research plan had correctly named the Summa a
    must-have and weighted gutenberg at 2.0. The corpus came out 17 tertiary to
    2 primary.

    So the primary key is the triage score, which is the judgement about worth,
    and cost only separates candidates the scoring could not tell apart. That
    still buys what cost-awareness was for: between two equally-rated papers the
    one with free full text is fetched first and OCR is paid for last.

    Rank 0 is reserved for candidates the pipeline has independent evidence
    about — a work the research plan named as canonical, or one that two or more
    accepted sources both cite. Those are fetched before anything else, at any
    price, because a corpus missing them is wrong in a way no saving repairs.

    Scores are rounded to whole points first: the model's scale is not precise
    to a tenth, and without rounding the gap between a 7.2 and a 7.0 would
    decide the order ahead of a real difference in cost.
    """
    if triaged.candidate.metadata.get("fetch_priority"):
        # Among priority candidates: the topic's canonical works, then concept
        # primary texts, then co-cited snowball finds.
        return (0, float(triaged.candidate.metadata.get("priority_rank", 2)), 0.0)
    cost = max(_prefetch_cost_estimate(triaged.candidate, batched), _VALUE_COST_FLOOR)
    return (1, -round(triaged.score), float(cost))


def _graph_chunk_limit(chunk_count: int) -> int:
    limit = settings.GRAPH_MAX_CHUNKS_PER_SOURCE
    return chunk_count if limit <= 0 else min(chunk_count, limit)


def _primary_text_ceilings(tier: ExpertTier) -> dict[str, int]:
    return dict(_PRIMARY_TEXT_CHARS.get(tier, _PRIMARY_TEXT_CHARS[ExpertTier.STANDARD]))


def _type_caps(fetchers: dict, budget: int) -> dict[SourceType, int]:
    """The most of each source type one corpus may contain.

    A type's cap is :data:`_TYPE_CAP_HEADROOM` times its *planned share* of the
    budget — the share the research plan's own per-fetcher weights imply. So the
    caps scale with the budget instead of being fixed at a number sized for a
    30-source build, and they sum to ``headroom × budget``, which means they
    shape the mix of the corpus and never cap its size. Deciding size is the
    money's job.
    """
    quotas = {_FETCHER_SOURCE_TYPES[name]: quota for name, (_, quota) in fetchers.items()}
    total = sum(quotas.values()) or 1
    return {
        source_type: max(
            _TYPE_CAP_MIN,
            math.ceil(budget * (quota / total) * _TYPE_CAP_HEADROOM),
        )
        for source_type, quota in quotas.items()
    }


def _search_breadth(quota: int, query_count: int) -> int:
    """Results to request per search query for a fetcher with this fetch quota.

    Overfetch scales with the quota so a heavily-weighted fetcher hands triage
    proportionally more to choose from, but never drops below
    ``_MIN_RESULTS_PER_QUERY`` — see the note on that constant.
    """
    return max(
        _MIN_RESULTS_PER_QUERY,
        math.ceil(quota * _SEARCH_OVERFETCH / max(1, query_count)),
    )
