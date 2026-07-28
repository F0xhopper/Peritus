"""Pure domain rules for the audit surface — no I/O, so every rule is testable.

Everything here is deterministic: given the same persisted numbers it always
produces the same classification. That matters more than it sounds — a
researcher defending a corpus has to be able to say *why* a concept was called
"thin", and "an LLM decided" is not an answer. The thresholds below are the
answer, and they are published verbatim in ``docs/audit-api.md``.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

# ── discovery provenance ────────────────────────────────────────────────────

# sources.discovered_via values written by the build pipeline. 'gapfill' carries
# a ``:<concept>`` suffix naming the concept whose absence triggered the search.
DISCOVERY_PLAN = "plan"
DISCOVERY_SNOWBALL = "snowball"
DISCOVERY_GAPFILL = "gapfill"
DISCOVERY_UNKNOWN = "unknown"

KNOWN_DISCOVERY_METHODS = (DISCOVERY_PLAN, DISCOVERY_SNOWBALL, DISCOVERY_GAPFILL)


def parse_discovery_method(discovered_via: str | None) -> tuple[str, str | None]:
    """Split ``sources.discovered_via`` into (method, concept).

    ``"gapfill:Stoic cosmopolitanism"`` -> ``("gapfill", "Stoic cosmopolitanism")``
    ``"plan"``                          -> ``("plan", None)``
    ``None``                            -> ``("unknown", None)``

    ``None`` is not a defect in the data model: the column arrived in migration
    012, so sources ingested before it exist with no discovery provenance at
    all. Those are reported as ``unknown``, never silently folded into ``plan``.
    """
    if not discovered_via:
        return DISCOVERY_UNKNOWN, None
    method, _, concept = discovered_via.partition(":")
    method = method.strip() or DISCOVERY_UNKNOWN
    return method, (concept.strip() or None if concept else None)


# ── coverage strength ───────────────────────────────────────────────────────


class CoverageStrength(StrEnum):
    """How well the accepted corpus covers one key concept.

    ``ABSENT`` is deliberately distinct from ``THIN``: "you have two weak
    sources on this" and "you have nothing on this" call for different actions,
    and collapsing them would hide the second behind the first.
    """

    ABSENT = "absent"
    THIN = "thin"
    ADEQUATE = "adequate"
    STRONG = "strong"


# Published thresholds. Changing these changes what the API tells a researcher
# about their evidence base, so they live in one place and are documented.
THIN_MEAN_QUALITY = 6.0
STRONG_MIN_SOURCES = 4
STRONG_MEAN_QUALITY = 7.0
STRONG_MIN_SOURCE_TYPES = 2

COVERAGE_RULE = (
    "absent = no accepted source covers the concept; "
    f"thin = exactly one accepted source, or mean quality below {THIN_MEAN_QUALITY}; "
    f"strong = at least {STRONG_MIN_SOURCES} accepted sources with mean quality at "
    f"least {STRONG_MEAN_QUALITY} drawn from at least {STRONG_MIN_SOURCE_TYPES} "
    "distinct source types; adequate = everything else."
)


def classify_coverage(
    source_count: int,
    mean_quality: float | None,
    distinct_source_types: int,
) -> CoverageStrength:
    """Classify one concept's evidence base. See :data:`COVERAGE_RULE`.

    ``mean_quality is None`` means the covering sources predate scoring, so the
    quality gates cannot fire; count and type diversity still apply.
    """
    if source_count <= 0:
        return CoverageStrength.ABSENT
    if source_count == 1:
        return CoverageStrength.THIN
    if mean_quality is not None and mean_quality < THIN_MEAN_QUALITY:
        return CoverageStrength.THIN
    if (
        source_count >= STRONG_MIN_SOURCES
        and distinct_source_types >= STRONG_MIN_SOURCE_TYPES
        and (mean_quality is None or mean_quality >= STRONG_MEAN_QUALITY)
    ):
        return CoverageStrength.STRONG
    return CoverageStrength.ADEQUATE


# ── rejection buckets ───────────────────────────────────────────────────────

# Why a rejected source was rejected, derived from its PERSISTED SCORES rather
# than from the validator's free-text drop_reason. The text is a short phrase an
# LLM wrote and is reported verbatim elsewhere; these buckets are arithmetic on
# numbers, so they can be recomputed and checked by anyone with the same rows.
REJECTION_BUCKETS = {
    "quality_below_threshold": "Quality below the pass floor; relevance met it.",
    "relevance_below_threshold": "Relevance below the pass floor; quality met it.",
    "both_below_threshold": "Both quality and relevance below their pass floors.",
    "above_both_thresholds": (
        "Rejected despite meeting both CURRENT thresholds — the source was judged "
        "under a different rubric version, or validation errored and scored it 0. "
        "Check rubric_version on these rows."
    ),
    "unscored": (
        "No quality and/or relevance score persisted — the validation call failed "
        "for this source, or it predates score persistence."
    ),
}


# ── passage dispositions in an answer's retrieval trail ─────────────────────

DISPOSITION_CITED = "cited"
DISPOSITION_IN_CONTEXT_UNCITED = "in_context_uncited"
DISPOSITION_NOT_IN_CONTEXT = "not_in_context"

DISPOSITION_MEANINGS = {
    DISPOSITION_CITED: "Reached the model's prompt and the answer cited it by number.",
    DISPOSITION_IN_CONTEXT_UNCITED: (
        "Reached the model's prompt but the answer never cited it. This is a "
        "record of what the model could see, not a judgement that the passage "
        "was irrelevant."
    ),
    DISPOSITION_NOT_IN_CONTEXT: (
        "Retrieved but never shown to the model — it ranked below the tier's "
        "context-passage cap."
    ),
}

RETRIEVED_VIA_PRIMARY = "primary"
RETRIEVED_VIA_FOLLOWUP = "coverage_followup"


# ── small helpers ───────────────────────────────────────────────────────────


def decode_json_field(value: Any, fallback: Any) -> Any:
    """Decode a JSONB column that asyncpg may hand back as ``str``.

    The connection pool registers no JSONB codec (see
    ``infrastructure/database.py``), so jsonb columns arrive as text on some
    paths and as decoded objects on others. Everything that touches a jsonb
    column goes through here rather than guessing.
    """
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return fallback
    return value


def round_or_none(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


def safe_mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None
