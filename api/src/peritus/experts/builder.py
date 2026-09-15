"""Build pipeline coordinator — orchestrates all 5 stages with progress callbacks.

Stages:
  0. PLAN    — Claude produces a research brief: per-fetcher queries + budget
               weights, key concepts the corpus must cover, must-have works
  1-2. DISCOVER — an iterating loop, not a single pass. Each round runs:
       search: planned fetchers over-search (~3× budget) for cheap candidates
       dedup:  identity → URL → (after fetch) content fingerprint
       triage: Haiku ranks candidates against the brief; junk and near-dups drop
       fetch:  top candidates get full content, refilling from lower ranks on failure
       validate: Claude scores each source and tags the key concepts it covers
       coverage: measure the corpus against the tier's per-concept targets
     Round 0's queries come from the plan. Later rounds read the corpus that
     exists — the concepts furthest from target become feedback queries in the
     field's own vocabulary, and the accepted scholarly sources are snowballed
     forwards and backwards through their citations. The loop stops when the
     targets are met, the rounds run out, the discovery budget is spent, a round
     finds nothing new, or acceptance collapses — and it says which.
  3. CHUNK + EMBED — chunk, contextualise, embed, store each validated source
                     ── the expert becomes chat-ready here ──
  4. GRAPH EXTRACT — Claude reads chunks in batches, extracts concept graph
  4b. RESOLVE — merge semantically duplicate graph nodes via embedding similarity
  5. PERSONA — Claude generates expert persona from corpus digest

Two cross-cutting decisions live here rather than in the stages:

**Execution policy.** A build declares once, up front, whether its Claude calls
run live (fast, full price) or through the Message Batches API (half price, up
to ~1h of queueing per batched stage). Every stage inherits it — see
:mod:`peritus.infrastructure.anthropic_batch`.

**Readiness.** Retrieval needs chunks, not the concept graph, so the expert is
published as chat-ready at the end of stage 3 and upgraded to graph-ready after
stage 4b — see :mod:`peritus.search.readiness`.

**Budget.** Discovery is bounded twice: by a count of sources (a ceiling that
rarely binds) and by an estimate of what the sources it has committed to will
cost to ingest, against the tier's discovery budget. The count is a safety rail;
the money is the real limit, because cost scales with characters and a corpus of
sixty mixed sources and a corpus of a hundred and fifty open-access papers can
cost the same.
"""

import asyncio
import contextlib
import json
import math
import time
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import asyncpg

from peritus.billing.domain import discovery_budget_usd
from peritus.billing.metering import current_meter
from peritus.billing.pricing import estimated_ingest_cost_usd, estimated_ocr_pages
from peritus.core.config import settings
from peritus.core.exceptions import BuildError, IncompleteBuildError
from peritus.core.logging import get_logger
from peritus.experts.composition import (
    apply_composition_caps,
    corpus_composition,
    top_concept_shares,
)
from peritus.experts.coverage import (
    NAMED_MISSING,
    ConceptCoverage,
    CoverageReport,
    compute_coverage,
)
from peritus.experts.domain import Expert, ExpertTier
from peritus.experts.feedback import feedback_queries, suggest_primary_texts
from peritus.experts.picture import PictureSkipped, find_picture
from peritus.experts.picture_repository import ExpertPictureRepository
from peritus.experts.repository import ExpertRepository
from peritus.graph.extractor import extract_graph_from_chunks
from peritus.graph.reconciler import ReconcileStats, reconcile_claims
from peritus.graph.repository import GraphRepository, node_embedding_text
from peritus.graph.resolution import (
    RESOLVE_THRESHOLD,
    RESOLVE_THRESHOLD_SAME_HEAD,
    canonical_merge_plan,
    pair_threshold,
)
from peritus.infrastructure.anthropic_batch import (
    BuildExecution,
    build_execution,
    current_execution,
    provider_error_message,
    record_provider_error,
    terminal_provider_error,
)
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.infrastructure.embeddings import embed_in_batches
from peritus.infrastructure.wikimedia import WikimediaClient
from peritus.ingestion.chunker import TextChunk
from peritus.ingestion.pipeline import ingest_sources
from peritus.search.readiness import Readiness, set_readiness
from peritus.sources.canonical import (
    FOUND_SECTIONS,
    FOUND_WHOLE,
    SCOPE_CONCEPT,
    SCOPE_FIGURE,
    SCOPE_OVERALL,
    WORK_KINDS,
    ArchiveTextFetcher,
    MustHaveWork,
    WorkResolution,
    archive_identifier,
    concept_named_texts,
    figure_outcomes,
    must_have_outcomes,
    resolve_works,
    title_key,
)
from peritus.sources.capture import capture_for_screening
from peritus.sources.dedup import (
    SeenSet,
    deduplicate_by_url,
    deduplicate_candidates,
    deduplicate_sources_by_content,
)
from peritus.sources.domain import (
    DroppedSource,
    RawSource,
    SourceCandidate,
    SourceType,
    ValidatedSource,
)
from peritus.sources.fetchers.arxiv import ArxivFetcher
from peritus.sources.fetchers.base import (
    HEALTHY_STATUSES,
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_SKIPPED,
    TRANSIENT_STATUSES,
    SearchOutcome,
    begin_search_note,
    end_search_note,
    worst_status,
)
from peritus.sources.fetchers.exa import ExaFetcher
from peritus.sources.fetchers.gutenberg import GutenbergFetcher
from peritus.sources.fetchers.openalex import OpenAlexFetcher
from peritus.sources.fetchers.pdf import PdfFetcher
from peritus.sources.fetchers.pubmed import PubmedFetcher
from peritus.sources.fetchers.reddit import RedditFetcher
from peritus.sources.fetchers.thought_leaders import ThoughtLeadersFetcher
from peritus.sources.fetchers.web import WebFetcher
from peritus.sources.fetchers.wikipedia import WikipediaFetcher
from peritus.sources.fetchers.youtube import YoutubeFetcher
from peritus.sources.fulltext import (
    PAID_METHODS,
    FullTextHints,
    default_method_for,
    expected_method,
)
from peritus.sources.language import is_expected_language
from peritus.sources.orientation import OrientationPack, build_orientation_pack
from peritus.sources.snowball import snowball
from peritus.sources.substance import substance_of
from peritus.sources.triage import (
    MIN_TRIAGE_SCORE,
    TRIAGE_SNIPPET_CHARS,
    TriagedCandidate,
    rank_candidates,
    triage_candidates,
)
from peritus.sources.validator import RUBRIC_VERSION, validate_sources

logger = get_logger(__name__)

EventCallback = Callable[[dict], Coroutine[Any, Any, None]]

# Fetchers a later discovery round may use. Query-driven only: the
# identify-then-fetch fetchers (gutenberg, thought_leaders) answer a broad
# "who matters here" question that a narrow concept query cannot ask, and the
# noisy ones (reddit, youtube) return worse results the narrower the query gets.
# Round 0 still runs all of them.
_LOOP_FETCHERS = ("exa", "web", "wikipedia", "arxiv", "pdf", "pubmed", "openalex")
# …plus, in any later round, every fetcher whose last search *failed* rather
# than came back empty. A Gutendex timeout in round 0 used to mean no classic
# primary text for that build, ever. The identify-then-fetch fetchers re-run
# with their round-0 plan queries, since a concept query is not what they answer.
_PLAN_QUERY_FETCHERS = frozenset({"gutenberg", "thought_leaders"})
# Weak concepts a single round tries to close. More than this and each gets too
# little of the round's budget to reach a target.
_LOOP_MAX_CONCEPTS = 4
# A later round may add at most this share of the initial corpus, so no single
# round can double the build.
_LOOP_ROUND_BUDGET_SHARE = 0.5
# Below this acceptance rate a round is telling you the search space is
# exhausted: it fetched things, and validation wanted almost none of them.
# Another round would be spend without return.
_ACCEPTANCE_COLLAPSE = 0.2
# Rounds smaller than this are not evidence of collapse, just small.
_ACCEPTANCE_MIN_SAMPLE = 5
# Tiers that guarantee a feedback round keep this share of the discovery budget
# out of round 0's reach. Round 0 committed $2.10 of the Thomism build's $3.00
# and left the loop about fifteen sources' worth of money, which made it a
# one-shot however strict the target. The fetch floor usually stops round 0
# short of the share on its own; this is the backstop.
_ROUND0_BUDGET_SHARE = Decimal("0.65")
# Round 0 relaxes the fetch floor when fewer than this many candidates reach it
# — max(this, budget // 4) — so a thin topic cannot produce an empty round.
_FLOOR_RELAX_MIN = 8

# Fetch outcomes recorded per candidate in the screening ledger.
OUTCOME_FETCHED = "fetched"
OUTCOME_FAILED = "failed"
OUTCOME_CAPPED = "capped"
OUTCOME_BELOW_FLOOR = "below_floor"
OUTCOME_NEAR_DUPLICATE = "near_duplicate"
OUTCOME_BUDGET = "budget"
OUTCOME_NOT_REACHED = "not_reached"
OUTCOME_CONTENT_DUPLICATE = "content_duplicate"
OUTCOME_NOT_ENGLISH = "not_english"

# Candidate metadata that must survive into the fetched source, whatever the
# fetcher copies: it is how the corpus summary knows which sources are the
# must-have works, and how the ledger and `sources` agree on a triage score.
_CARRIED_METADATA = (
    "discovered_via",
    "fetch_priority",
    "must_have_title",
    "must_have_extent",
    "must_have_sections",
    "canonical_route",
    "must_have_scope",
    "must_have_concepts",
    "must_have_figure",
    "sections_matched",
    "triage_score",
)

# Why the loop stopped. Recorded in experts.build_summary and emitted on
# `discovery_done`, because "the build stopped looking" is only a defensible
# statement if it comes with the reason.
STOP_TARGETS_MET = "targets_met"
STOP_MAX_ROUNDS = "max_rounds"
STOP_BUDGET_EXHAUSTED = "budget_exhausted"
# The count ceiling, which is a different thing from the money running out and
# must not be reported as it. A live PRO build stopped with "budget_exhausted"
# while $4.71 of its $7.00 discovery budget was unspent — the count had simply
# filled. Two limits sharing one reason makes the stop reason a false statement,
# and the stop reason is the whole surface this loop publishes.
STOP_SOURCE_LIMIT = "source_limit"
STOP_NO_NEW_CANDIDATES = "no_new_candidates"
STOP_ACCEPTANCE_COLLAPSED = "acceptance_collapsed"
STOP_LOOP_DISABLED = "loop_disabled"

# Rough text length by source type, for ordering the fetch queue by expected
# cost *before* anything is downloaded. Deliberately coarse: the
# ordering only needs to know that a paper is two orders of magnitude more
# expensive to ingest than a forum thread, which these numbers say.
_EXPECTED_CHARS: dict[SourceType, int] = {
    SourceType.ARXIV: 60_000,
    SourceType.PUBMED: 40_000,
    SourceType.OPENALEX: 40_000,
    SourceType.PDF: 60_000,
    SourceType.GUTENBERG: 120_000,
    SourceType.WIKIPEDIA: 25_000,
    SourceType.EXA: 15_000,
    SourceType.WEB: 10_000,
    SourceType.THOUGHT_LEADER: 12_000,
    SourceType.YOUTUBE: 25_000,
    SourceType.REDDIT: 6_000,
}
_DEFAULT_EXPECTED_CHARS = 15_000
# Floor under the cost divisor when ranking by value per dollar, so a free
# 800-character page does not outrank a paper by dividing by almost nothing.
_VALUE_COST_FLOOR = Decimal("0.01")

# Two-phase discovery: the tier multiplier scales the final corpus budget;
# searching is cheap so candidates are gathered at _SEARCH_OVERFETCH× budget
# and triage picks which ones are worth full downloads. Per-type caps keep a
# single source type from flooding the corpus even if it triages well.
# The count budget is a ceiling, not the budget. Since the discovery loop
# spends against an estimate of ingest cost in dollars, a count that binds first
# defeats the point — on a live PRO build round 0 used 56 of a 60-source count
# and left round 1 able to add four sources while $4.75 of its money budget was
# still unspent. Doubled so the money is what actually stops the search, which
# is what makes "sixty mixed sources" and "a hundred and fifty open-access
# papers" cost the same. Per-tier ceilings become 30 / 60 / 120.
_BASE_FETCH_BUDGET = 60
_SEARCH_OVERFETCH = 3
_FETCH_CONCURRENCY = 6
# In-stage retries for persona generation before the build is declared incomplete.
_PERSONA_ATTEMPTS = 3
# A single fetcher's search taking longer than this is worth a warning: discovery
# waits on all of them, so one slow fetcher is the stage's duration.
_SLOW_SEARCH_SECONDS = 30.0
# No single source type may take more than this multiple of its *planned share*
# of the corpus. The plan's per-fetcher weights already decide how much of the
# search each type gets; this is the backstop that stops one type dominating the
# result anyway, and triage decides everything in between.
#
# It replaces a fixed `quota × 2`, which was sized for a 30-source budget and
# became the real limit once the budget grew: on a live STANDARD build, four of
# the six productive types hit their cap at 43 sources while the count ceiling
# (60) and the money budget ($1.58 of $3.00) were both untouched. A cap that
# does not scale with the budget makes budgeting by cost decorative.
#
# Because the caps sum to `headroom × budget`, they constrain the *mix* and
# never the total — which is the division of labour intended: the money says how
# much corpus, the caps say how varied it has to be.
_TYPE_CAP_HEADROOM = 2.0
# Floor, so a fetcher with a small quota can still contribute a few sources on a
# small build rather than being capped at one.
_TYPE_CAP_MIN = 4

# Floor under the search phase, per query. Quotas scale down with tier, but the
# costs that tiers exist to bound — full fetch, OCR, validation, chunking,
# graph — are all capped by the fetch budget, not by how many candidates triage
# looks at; a search-API call is free and triage is a Haiku pass over
# title+snippet. Without the floor, a lite build's overfetch worked out to 1–2
# results per query, so triage picked winners out of ~50 candidates and could
# not afford to be choosy. Quality comes from selectivity, and selectivity
# needs a pool worth selecting from.
_MIN_RESULTS_PER_QUERY = 10

_FETCHER_SOURCE_TYPES: dict[str, SourceType] = {
    "wikipedia": SourceType.WIKIPEDIA,
    "gutenberg": SourceType.GUTENBERG,
    "arxiv": SourceType.ARXIV,
    "pdf": SourceType.PDF,
    "youtube": SourceType.YOUTUBE,
    "exa": SourceType.EXA,
    "web": SourceType.WEB,
    "reddit": SourceType.REDDIT,
    "thought_leaders": SourceType.THOUGHT_LEADER,
    "pubmed": SourceType.PUBMED,
    "openalex": SourceType.OPENALEX,
}

_FETCHER_NAMES: tuple[str, ...] = (
    "wikipedia",
    "gutenberg",
    "arxiv",
    "pdf",
    "youtube",
    "exa",
    "web",
    "reddit",
    "thought_leaders",
    "pubmed",
    "openalex",
)

# Public alias: the API layer validates BuildRequest.sources against this so an
# unknown fetcher name is rejected at the door instead of producing an empty
# discovery round minutes later.
FETCHER_NAMES: tuple[str, ...] = _FETCHER_NAMES
_MAX_QUERIES_PER_FETCHER = 3

_FETCHER_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": _MAX_QUERIES_PER_FETCHER,
            "description": "1–3 search queries, together spanning different facets of the topic.",
        },
        "weight": {
            "type": "number",
            "description": (
                "Budget weight, 0–2. 0 = this source type would add noise for this "
                "topic and must be skipped; 1 = normal; 2 = this source type is "
                "especially valuable here."
            ),
        },
    },
    "required": ["queries", "weight"],
}

_WORK_PROPERTIES: dict[str, Any] = {
    "title": {"type": "string", "description": "The title as scholarship or the field cites it."},
    "author": {"type": "string"},
    "kind": {
        "type": "string",
        "enum": list(WORK_KINDS),
        "description": (
            "text = a primary text (a treatise, scripture, a classic, a founding "
            "document); book = a monograph; paper = a journal article or preprint; "
            "standard = a specification, guideline, statute or official document."
        ),
    },
    "public_domain": {
        "type": "boolean",
        "description": (
            "True only if an English text of it is in the public domain (published "
            "roughly 95+ years ago, or released openly) — it decides whether Project "
            "Gutenberg and the Internet Archive are searched for it."
        ),
    },
    "sections": {
        "type": "string",
        "description": (
            "For a long work, the numbered parts that matter, in the work's own "
            "numbering: 'qq. 90–97', 'Book II, chapters 1–10', 'sections 3–5', "
            "'Lectures 4–6'. Empty if the work is short or matters whole."
        ),
    },
    "open_text": {
        "type": "boolean",
        "description": (
            "True if an authorised full English text is freely online although the "
            "work is not public domain: an open-access edition, the publisher's free "
            "text, the author's own site. False for an ordinary in-copyright book."
        ),
    },
}

# A work the planner names in place of one that cannot be had: same fields, no
# substitute of its own.
_SUBSTITUTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": _WORK_PROPERTIES,
    "required": ["title", "kind", "public_domain"],
    "description": (
        "Only for a work that is neither public_domain nor open_text: a work with a "
        "free English text that teaches the same thing, looked for if this one "
        "cannot be had."
    ),
}

_WORK_SCHEMA_PROPERTIES: dict[str, Any] = {**_WORK_PROPERTIES, "substitute": _SUBSTITUTE_SCHEMA}

# Facets and concepts: docs/plans/syllabus.md, phase 2.
_MAX_FACETS = 5
_MAX_CONCEPTS_PER_FACET = 4
# Figures: phase 3.A.
_MAX_FIGURES = 6


def _plan_tool(max_concepts: int) -> dict[str, Any]:
    return {
        "name": "create_research_plan",
        "description": (
            "Create a research plan: targeted queries and a budget weight per source "
            "fetcher, the facets and key concepts the corpus must cover, the figures "
            "whose own writing is primary, and must-have canonical works."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "orientation_note": {
                    "type": "string",
                    "description": (
                        "Only if an overview you were shown is about something adjacent "
                        "rather than this topic: say which, and that you relied on it "
                        "less. Otherwise empty."
                    ),
                },
                "fetcher_plans": {
                    "type": "object",
                    "description": (
                        "A plan for each fetcher, with queries tuned to what that source "
                        "type does best and a weight steering how much of the source budget "
                        "it deserves for this topic."
                    ),
                    "properties": {name: _FETCHER_PLAN_SCHEMA for name in _FETCHER_NAMES},
                },
                "facets": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": _MAX_FACETS,
                    "description": (
                        "The topic's major facets, each with the concepts under it an "
                        f"expert must be able to teach: 2–{_MAX_FACETS} facets, "
                        f"2–{_MAX_CONCEPTS_PER_FACET} concepts each, at most "
                        f"{max_concepts} concepts in all. The corpus is checked against "
                        "every concept and gaps are re-searched facet by facet. The count "
                        "scales with the topic's actual breadth — see the system prompt."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "concepts": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                                "maxItems": _MAX_CONCEPTS_PER_FACET,
                            },
                        },
                        "required": ["name", "concepts"],
                    },
                },
                "key_concepts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": max_concepts,
                    "description": (
                        "Legacy flat list of the concepts. Leave empty when facets are given."
                    ),
                },
                "primary_source_definition": {
                    "type": "string",
                    "description": (
                        "One or two sentences: what counts as a PRIMARY source for this "
                        "topic, as opposed to analysis of it. For a thinker or school: their "
                        "own writings (and, for a tradition, its major figures' own works). For "
                        "a science: original research reports, datasets, trials. For a craft: "
                        "practitioners' first-hand accounts and technical standards. For "
                        "history: documents from the period. Used to classify every source."
                    ),
                },
                "figures": {
                    "type": "array",
                    "maxItems": _MAX_FIGURES,
                    "description": (
                        "People whose own writing is primary for this topic by your "
                        "definition. For each, one work of theirs with a freely available "
                        "English text: public domain, open access, or published by them "
                        "online (a blog, a lecture transcript, a preprint). Set obtainable "
                        "false and leave work out when nothing of theirs is freely "
                        "available — name them anyway."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "why": {"type": "string", "description": "One line: why their own voice matters here."},
                            "work": {
                                "type": "object",
                                "properties": _WORK_PROPERTIES,
                                "required": ["title", "kind", "public_domain"],
                            },
                            "obtainable": {"type": "boolean"},
                        },
                        "required": ["name", "why", "obtainable"],
                    },
                },
                "must_have_works": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": _WORK_SCHEMA_PROPERTIES,
                        "required": ["title", "kind", "public_domain"],
                    },
                    "maxItems": 4,
                    "description": (
                        "Named canonical works (books, papers, essays, standards) an expert "
                        "corpus on this topic as a whole should contain, if any exist."
                    ),
                },
                "concept_primary_texts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "concept": {
                                "type": "string",
                                "description": "The key concept, copied verbatim from facets.",
                            },
                            **_WORK_SCHEMA_PROPERTIES,
                        },
                        "required": ["concept", "title", "kind", "public_domain"],
                    },
                    "maxItems": 16,
                    "description": (
                        "For each key concept, the one or two primary texts (as defined in "
                        "primary_source_definition) where that concept is actually set out — "
                        "with the sections that set it out when the text is long. Name a "
                        "text only if you are confident it exists and teaches the concept; "
                        "leave a concept out rather than guess."
                    ),
                },
            },
            "required": ["fetcher_plans", "facets", "primary_source_definition"],
        },
    }


_ORIENTATION_PROMPT = (
    "You may be shown how one or two reference overviews structure this topic — their "
    "opening paragraphs and section outlines. Use them as a checklist of the topic's "
    "facets, not as the syllabus: every major facet they treat should be represented in "
    "your concepts unless it is clearly outside what an expert on this topic must teach, "
    "and you should add what they omit. Take the field's own terms and names from them "
    "for your queries. If an overview is about something adjacent rather than this "
    "topic, say so in orientation_note and rely on it less."
)


def _plan_system(max_concepts: int) -> str:
    return (
        _PLAN_SYSTEM
        + "\n\n"
        + _ORIENTATION_PROMPT
        + "\n\n"
        f"Group the concepts under facets — the topic's major areas (for a tradition: its "
        "doctrines, its history and schools, its modern debates; for a science: its "
        "theory, its methods, its applications). The concept count must scale with how "
        "much ground the topic actually covers — this is a judgment call, not a quota. A "
        "narrow or single-threaded topic (one thinker, one event, one narrow technique) "
        "genuinely has fewer concepts worth naming as separate teaching points; padding it "
        "out means inventing overlapping or trivial ones. A broad field (a whole "
        f"discipline, a wide practice, a tradition) earns more, up to {max_concepts}. "
        "Default to the number the topic actually supports, not the maximum allowed.\n\n"
        "Name the figures whose own writing is primary by your definition, and one work of "
        "each that can be had freely in English. A corpus that defines a tradition's "
        "commentators as primary and contains none of them in their own voice has not "
        "found the tradition. For a canonical work still in copyright, mark public_domain "
        "and open_text honestly and name a substitute with a free English text: name both, "
        "never silently swap one for the other."
    )


_PLAN_SYSTEM = (
    "You are planning the research for building a grounded AI expert. The sources this "
    "plan discovers are the ONLY material the expert will ever know, so plan for breadth "
    "(every major facet of the topic gets searched) and depth (primary and advanced "
    "material, not just introductions). Tune queries to each source type: arxiv gets "
    "STEM preprints (physics, math, CS), openalex gets peer-reviewed scholarship in "
    "ANY discipline — it is the academic channel for humanities, social science, law, "
    "economics, psychology, education, business and everything else arxiv and pubmed "
    "don't reach — pubmed gets biomedical and clinical literature, gutenberg gets "
    "classic public-domain primary texts, pdf gets open-access published papers, "
    "thought_leaders finds the field's leading practitioners and their own writing, "
    "reddit gets practitioner discussion, youtube gets lectures and talks, wikipedia "
    "gets encyclopedic overviews, exa and web get high-quality articles and essays. "
    "Give weight 0 to source types that would add noise for this topic (e.g. gutenberg "
    "for modern technology, arxiv for a non-academic craft, pubmed for anything "
    "non-biomedical) and weight 2 to the ones that carry it. Every topic has some "
    "scholarly literature — a craft has ergonomics and materials-science studies, a "
    "cuisine has food chemistry and anthropology — so before zeroing openalex, ask "
    "what the adjacent research field is and query that.\n\n"
    "A corpus that only contains material ABOUT its subject answers second-hand. So say "
    "what counts as primary for this topic, name the works canonical for the topic as a "
    "whole (must_have_works), and for each key concept name the primary text that "
    "actually sets it out (concept_primary_texts). Works are looked for by title and cut "
    "to the sections you name, so name them precisely: the title as the field cites it, "
    "the author, and — for a long work — the numbered parts in the work's own numbering. "
    "Mark public_domain honestly; it decides whether Project Gutenberg and the Internet "
    "Archive are searched. The corpus is in English, so name works as English editions "
    "cite them. For a long work named in must_have_works, leave sections empty unless "
    "one part matters most for the topic as a whole — the concept entries say which "
    "parts each concept needs."
)


@dataclass
class BuildResult:
    expert_id: int
    source_count: int
    dropped_count: int
    chunk_count: int
    node_count: int
    edge_count: int
    avg_quality: float | None
    persona_name: str | None


class ExpertBuilder:
    def __init__(
        self,
        pool: asyncpg.Pool,
        source_filter: list[str] | None = None,
        execution: BuildExecution | None = None,
        job_id: int | None = None,
    ) -> None:
        """``execution=None`` resolves per build (see :func:`resolve_execution`);
        pass a mode explicitly to force one — e.g. a scheduled refresh that should
        always take the half-price path regardless of what the expert looks like.

        ``job_id`` is only used to name screening capture files (see
        :mod:`peritus.sources.capture`); the builder does not otherwise know or
        care that it is running under a job."""
        self._pool = pool
        self._repo = ExpertRepository(pool)
        self._graph_repo = GraphRepository(pool)
        self._source_filter = source_filter
        self._execution = execution
        self._job_id = job_id
        # Sources dropped by content fingerprinting rather than by the
        # validator. Held here so they reach the ledger as explicit drops with a
        # reason instead of disappearing between fetching and validation.
        self._content_duplicates: list[DroppedSource] = []
        # The picture finder, started off `plan_ready` and awaited before the
        # persona stage. Held on the instance so the `finally` in `build` can
        # cancel it when the build is cancelled or fails.
        self._picture_task: asyncio.Task | None = None
        # Discovery's working state, reset at the start of every discovery run:
        # each fetcher's last search outcome, what the canonical-work resolver
        # found, and the expert the screening ledger is being written for.
        self._fetcher_status: dict[str, str] = {}
        self._canonical: list[WorkResolution] = []
        self._ledger_expert_id: int | None = None
        # From the research plan: what counts as primary for this topic (handed
        # to the validator), and the text ceilings for resolved works.
        self._primary_definition: str = ""
        self._text_ceilings: dict[str, int] = {}

    def _build_fetchers(
        self,
        multiplier: float,
        source_filter: list[str] | None,
        weights: dict[str, float] | None = None,
    ):
        weights = weights or {}
        all_fetchers = {
            "wikipedia": (WikipediaFetcher(), 3),
            "gutenberg": (GutenbergFetcher(), 4),
            "arxiv": (ArxivFetcher(), 2),
            "pdf": (PdfFetcher(), 3),
            "youtube": (YoutubeFetcher(), 3),
            "exa": (ExaFetcher(), 5),
            "web": (WebFetcher(), 3),
            # 2, not 5: forum threads are not as valuable as curated web results
            # by default. The planner can still weight it up for a practitioner
            # topic.
            "reddit": (RedditFetcher(), 2),
            "thought_leaders": (ThoughtLeadersFetcher(), 3),
            "pubmed": (PubmedFetcher(), 2),
            "openalex": (OpenAlexFetcher(), 3),
        }

        active: dict[str, tuple[Any, int]] = {}
        for name, (fetcher, base) in all_fetchers.items():
            weight = weights.get(name, 1.0)
            if source_filter:
                if name not in source_filter:
                    continue
                # An explicit source filter is a user decision — the planner may
                # tune the budget but not zero out a requested fetcher.
                weight = max(weight, 1.0)
            elif weight <= 0:
                continue
            active[name] = (fetcher, max(1, round(base * multiplier * weight)))
        return active

    async def build(
        self,
        expert: Expert,
        on_event: EventCallback | None = None,
    ) -> BuildResult:
        """Run the pipeline under this build's execution policy.

        The policy is fixed here, for the whole build, and every stage inherits
        it — a build cannot half-batch. Readiness is also reset here: the worker
        has just deleted the previous corpus, so an expert being rebuilt must
        stop advertising itself as chattable until its new chunks land.
        """
        await set_readiness(self._pool, expert.id, Readiness.PENDING)
        return await self._run(expert, on_event, lambda: self._build(expert, on_event))

    async def resume(
        self,
        expert: Expert,
        from_readiness: Readiness,
        on_event: EventCallback | None = None,
    ) -> BuildResult:
        """Finish a build whose corpus an earlier attempt already paid for.

        A retry used to start from nothing: the worker wiped the corpus before
        every attempt, so a persona call that failed four seconds into its stage
        destroyed a finished PRO build (66 sources, 2,921 graph nodes) and then
        re-ran planning into the same provider refusal. Readiness is recorded
        as each stage lands, so a retry can start where the last attempt got to:

        - ``graph_ready`` — only the persona is missing; run that and the gate.
        - ``chat_ready``  — chunks are embedded; rebuild the graph from them
          (whatever part of it the failed attempt wrote is discarded first),
          then the persona.

        Readiness is *not* reset to pending here: the corpus stays chattable
        for the whole resumed attempt, which is the point.
        """
        if from_readiness is Readiness.PENDING:
            return await self.build(expert, on_event)
        await _emit_event(
            on_event, {"type": "build_resumed", "from_readiness": from_readiness.value}
        )
        return await self._run(
            expert, on_event, lambda: self._resume(expert, from_readiness, on_event)
        )

    async def _run(
        self,
        expert: Expert,
        on_event: EventCallback | None,
        body: Callable[[], Coroutine[Any, Any, BuildResult]],
    ) -> BuildResult:
        """The execution policy, fixed for the whole run, around a build body."""
        execution = self._execution or resolve_execution(expert)
        await _emit_event(
            on_event,
            {
                "type": "execution_mode",
                "mode": execution.value,
                "batched": execution is BuildExecution.BACKGROUND
                and settings.ANTHROPIC_BATCH_ENABLED,
            },
        )
        logger.info(
            "Building expert %d (%r) with execution=%s", expert.id, expert.name, execution.value
        )
        try:
            with build_execution(execution):
                return await body()
        finally:
            # A cancelled or failed build must not leave an HTTP client and a
            # pending write behind it. Cancelling a task that already finished
            # is a no-op, which is the common case.
            task = self._picture_task
            self._picture_task = None
            if task is not None and not task.done():
                task.cancel()

    async def _build(
        self,
        expert: Expert,
        on_event: EventCallback | None = None,
    ) -> BuildResult:
        topic = expert.topic

        # Stage 0: Research planning
        await _emit_event(on_event, {"type": "stage", "stage": 0, "name": "plan"})
        plan = await _plan_research(topic, getattr(expert.config, "max_key_concepts", 8))
        _route_must_have_works(plan)
        key_concepts = plan["key_concepts"]
        if not key_concepts:
            # Stop here rather than proceeding on the raw-topic fallback. The
            # concepts are the syllabus: triage scores against them, validation
            # scores against them, and gap-fill exists to close holes in them.
            # A build without them cannot produce a ready expert, so running the
            # rest is spending money on a foregone conclusion — one such attempt
            # reached the graph stage and $1.70 before failing.
            _raise_if_provider_down("Research planning")
            raise IncompleteBuildError(["key concepts (research planning failed)"])
        await self._repo.update_key_concepts(expert.id, key_concepts)
        await _quietly(
            "store the research plan", self._repo.update_research_plan(expert.id, plan)
        )
        # The whole plan, not only the concepts: the queries, the weights and the
        # must-have works used to exist only in a worker log line, so a build's
        # search could not be reproduced or argued with afterwards. Clients read
        # `key_concepts` and ignore the rest.
        await _emit_event(
            on_event,
            {
                "type": "plan_ready",
                "key_concepts": key_concepts,
                "facets": plan.get("facets", []),
                "fetcher_plans": plan["fetcher_plans"],
                "must_have_works": plan["must_have_works"],
                "concept_primary_texts": plan.get("concept_primary_texts", []),
                "primary_source_definition": plan.get("primary_source_definition", ""),
                "figures": plan.get("figures", []),
                "orientation": plan.get("orientation") or {"overviews": [], "note": ""},
            },
        )

        # The expert's picture. Started here, the moment the topic and the key
        # concepts both exist, so the rail's tile stops being a monogram within
        # seconds rather than at the end of a build that takes minutes. It runs
        # beside discovery, never blocks it, and cannot fail it — see
        # `_find_and_store_picture`.
        self._picture_task = asyncio.create_task(
            self._find_and_store_picture(expert, topic, key_concepts, on_event)
        )

        weights = {name: p["weight"] for name, p in plan["fetcher_plans"].items()}
        self._fetchers = self._build_fetchers(
            expert.config.source_multiplier,
            self._source_filter,
            weights,
        )

        # Stages 1–2: the discovery loop (search → dedup → triage → fetch →
        # validate → coverage, repeated until the targets are met or the money
        # or the rounds run out).
        outcome = await self._run_discovery(expert, topic, plan, on_event)
        passed, dropped = outcome.passed, outcome.dropped
        await self._repo.update_build_summary(expert.id, outcome.summary())

        if not passed:
            # Before blaming the corpus, check whether the validator ever ran.
            # An empty `passed` means either "the model judged everything below
            # threshold" or "the model was unreachable", and only the first is
            # about the topic. Telling someone with an empty credit balance to
            # pick a different topic sends them to debug the wrong thing.
            _raise_if_provider_down("Source validation")
            raise BuildError("All sources failed validation. Try a different topic or sources.")

        # Corpus composition, while the user is still watching the build. A
        # weak-but-passing corpus is not a build failure, so this is a warning
        # event rather than a raise — but it has to arrive before they start
        # trusting the expert's answers.
        warning = corpus_tier_warning(passed)
        if warning:
            logger.warning(
                "Expert %d corpus is %d/%d tertiary",
                expert.id, warning["tertiary"], warning["classified"],
            )
            await _emit_event(on_event, warning)

        source_db_ids = await self._persist_sources(expert.id, passed, dropped)
        await _quietly(
            "link the screening ledger to its sources",
            self._repo.link_candidate_screenings(expert.id, self._job_id),
        )
        avg_quality = _avg_quality(passed)

        # Stage 3: Chunk + Embed. All sources are chunked up front so their
        # contextualisation runs as one Message Batch (half price) when enabled.
        await _emit_event(
            on_event, {"type": "stage", "stage": 3, "name": "chunk", "total": len(passed)}
        )
        all_chunk_ids: list[int] = []
        all_chunks_for_graph: list[tuple[TextChunk, int]] = []
        ingested_total = 0

        async def _on_ingested(vsource: ValidatedSource, chunk_ids: list[int]) -> None:
            nonlocal ingested_total
            ingested_total += len(chunk_ids)
            await _emit_event(
                on_event,
                {
                    "type": "source_ingested",
                    "title": vsource.title,
                    "chunks": len(chunk_ids),
                    "total_chunks": ingested_total,
                },
            )

        ingested = await ingest_sources(
            passed,
            expert.id,
            source_db_ids,
            self._pool,
            on_ingested=_on_ingested,
        )
        graph_skipped = 0
        for chunk_ids, raw_chunks in ingested:
            all_chunk_ids.extend(chunk_ids)
            # Everything is embedded; only the first chunks of a very long source
            # go to graph extraction — see GRAPH_MAX_CHUNKS_PER_SOURCE.
            kept = _graph_chunk_limit(len(chunk_ids))
            graph_skipped += len(chunk_ids) - kept
            all_chunks_for_graph.extend(zip(raw_chunks[:kept], chunk_ids[:kept], strict=True))
        if graph_skipped:
            logger.info(
                "Graph extraction skips %d chunk(s) past %d per source; they are embedded "
                "and retrievable, and not read for concepts",
                graph_skipped, settings.GRAPH_MAX_CHUNKS_PER_SOURCE,
            )

        if not all_chunk_ids:
            raise BuildError("No chunks were embedded — ingestion failed for all sources.")

        # User-supplied sources survive `reset_build_state`, so on a rebuild their
        # chunks are already in the table and were never ingested by this run.
        # They still have to reach the graph stage: the graph was wiped whole and
        # is rebuilt whole, and leaving them out would quietly drop the owner's
        # own material out of the concept graph on every rebuild.
        preserved = await self._load_upload_chunks(expert.id)
        all_chunks_for_graph.extend(preserved)

        # ── Chat-ready ───────────────────────────────────────────────────────
        # Everything retrieval needs now exists. Hybrid search reads only
        # source_chunks + sources, and graph expansion is a no-op while the
        # graph is empty, so the expert can already give a grounded, cited
        # answer. Publish it now instead of after the graph and persona stages,
        # and write the counts so the expert doesn't read as empty in the UI.
        # Counts include the preserved uploads, which this run did not ingest but
        # which are part of the corpus the expert answers from.
        #
        # No preserved chunks means no upload sources to count: `ingest_upload`
        # deletes the sources row when nothing embeds, so an upload always has at
        # least one chunk. Skipping the query on that path keeps the common case
        # (an expert with no uploads) at zero extra round-trips.
        total_sources = len(passed)
        if preserved:
            total_sources += await self._count_upload_sources(expert.id)
        total_chunks = len(all_chunk_ids) + len(preserved)
        await self._repo.update_counts(
            expert.id,
            source_count=total_sources,
            chunk_count=total_chunks,
            node_count=0,
            edge_count=0,
            avg_quality=avg_quality,
        )
        await set_readiness(self._pool, expert.id, Readiness.CHAT_READY)
        await _emit_event(
            on_event,
            {
                "type": "chat_ready",
                "sources": total_sources,
                "chunks": total_chunks,
                "graph_expanded": False,
            },
        )

        return await self._enrich_and_finish(
            expert,
            chunks_for_graph=all_chunks_for_graph,
            persona_sources=[
                (vs.title, vs.content_type, vs.quality_score, vs.key_claims) for vs in passed
            ],
            total_sources=total_sources,
            total_chunks=total_chunks,
            avg_quality=avg_quality,
            dropped_count=len(dropped),
            on_event=on_event,
        )

    async def _resume(
        self,
        expert: Expert,
        from_readiness: Readiness,
        on_event: EventCallback | None,
    ) -> BuildResult:
        """The enrichment stages only, off the corpus already in the database."""
        current = await self._repo.get_by_id(expert.id) or expert
        persona_sources = await self._repo.passed_source_digest(expert.id)
        if not persona_sources:
            raise IncompleteBuildError(["a corpus (nothing to resume from)"])

        chunks_for_graph: list[tuple[TextChunk, int]] | None = None
        if from_readiness is Readiness.CHAT_READY:
            # A graph stage that died part-way may have written some of its
            # nodes. The graph is built whole, so it is cleared whole.
            await self._graph_repo.delete_graph(expert.id)
            chunks_for_graph = await self._load_chunks(expert.id)
            if not chunks_for_graph:
                raise IncompleteBuildError(["chunks (nothing to resume from)"])

        logger.info(
            "Resuming expert %d from %s: %d source(s), %d chunk(s)",
            expert.id, from_readiness.value, current.source_count, current.chunk_count,
        )
        return await self._enrich_and_finish(
            expert,
            chunks_for_graph=chunks_for_graph,
            persona_sources=persona_sources,
            total_sources=current.source_count,
            total_chunks=current.chunk_count,
            avg_quality=current.avg_quality,
            dropped_count=0,
            on_event=on_event,
            existing_graph=(current.node_count, current.edge_count),
        )

    async def _enrich_and_finish(
        self,
        expert: Expert,
        *,
        chunks_for_graph: list[tuple[TextChunk, int]] | None,
        persona_sources: list[tuple[str, str, float | None, list[str]]],
        total_sources: int,
        total_chunks: int,
        avg_quality: float | None,
        dropped_count: int,
        on_event: EventCallback | None,
        existing_graph: tuple[int, int] = (0, 0),
    ) -> BuildResult:
        """Graph, persona and the completeness gate, for a chat-ready corpus.

        ``chunks_for_graph=None`` means the graph already exists (a resume from
        ``graph_ready``) and ``existing_graph`` carries its counts.
        """
        topic = expert.topic

        # ── Enrichment ───────────────────────────────────────────────────────
        # From here on the expert already answers questions. Each stage below
        # degrades rather than raising, so the corpus keeps the readiness it has
        # reached; the completeness gate at the end decides whether the build
        # succeeded. A retry of a build that fails the gate resumes from that
        # readiness (see `resume`) rather than refetching the corpus.

        node_count, edge_count = existing_graph
        graph_built = chunks_for_graph is None
        if chunks_for_graph is not None:
            node_count, edge_count, graph_built = await self._graph_stage(
                expert, chunks_for_graph, on_event
            )

        await self._repo.update_counts(
            expert.id,
            source_count=total_sources,
            chunk_count=total_chunks,
            node_count=node_count,
            edge_count=edge_count,
            avg_quality=avg_quality,
        )

        if graph_built and chunks_for_graph is not None:
            # ── Graph-ready ──────────────────────────────────────────────────
            # Retrieval transparently upgrades from here: the same chat request
            # now finds anchor nodes for its hits, so passages arrive with
            # neighbouring concepts, relationships, and contradiction flags. On
            # a degraded graph the expert simply stays chat-ready.
            await set_readiness(self._pool, expert.id, Readiness.GRAPH_READY)
            await _emit_event(
                on_event,
                {
                    "type": "graph_ready",
                    "nodes": node_count,
                    "edges": edge_count,
                    "graph_expanded": True,
                },
            )

        # In any real build this finished minutes ago, during discovery. The
        # await exists so `picture_ready` is in the durable log before `done`,
        # which is what a client replaying the log from seq 0 depends on.
        await self._await_picture()

        await _emit_event(on_event, {"type": "stage", "stage": 5, "name": "persona"})
        persona_name: str | None = None
        # Retried in place. The persona is one cheap call, and it is now required
        # for the expert to be ready — so letting a single blip here condemn a
        # finished corpus to a full rebuild would be absurdly expensive. The
        # graph stage above is not retried this way: its calls already retry
        # individually inside gather_claude_calls, and re-running all of it costs
        # more than re-running the build.
        for attempt in range(1, _PERSONA_ATTEMPTS + 1):
            try:
                top_nodes = await self._graph_repo.get_top_nodes(expert.id, 20)
                persona = await _generate_persona(topic, persona_sources, top_nodes)
                await self._repo.update_persona(
                    expert.id,
                    persona_name=persona["name"],
                    persona_bio=persona["bio"],
                    persona_style=persona["style"],
                )
                persona_name = persona["name"]
                await _emit_event(on_event, {"type": "persona_ready", "name": persona_name})
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                record_provider_error(exc)
                logger.warning(
                    "Persona generation attempt %d/%d failed for expert %d (%s: %s)",
                    attempt, _PERSONA_ATTEMPTS, expert.id, type(exc).__name__, exc,
                    exc_info=attempt == _PERSONA_ATTEMPTS,
                )
                if attempt < _PERSONA_ATTEMPTS:
                    await asyncio.sleep(2 ** (attempt - 1))

        # ── Completeness gate ────────────────────────────────────────────────
        # An expert is "ready" only with all three: concepts, a concept graph,
        # and a persona. Short of that the job does not report success, so the
        # expert is never advertised as ready on a half-finished build. The
        # corpus survives the raise only because the worker's retry resumes from
        # the recorded readiness instead of resetting — it used to reset, and a
        # four-second persona failure wiped a finished PRO build that way.
        #
        # A persona that failed because the provider refused every request is
        # not worth a retry at all: the retry meets the same refusal. That
        # raises BuildError, which the worker does not retry, and says why.
        missing: list[str] = []
        if not graph_built or node_count <= 0:
            missing.append("a concept graph")
        if not persona_name:
            missing.append("a persona/description")
        if missing:
            logger.error(
                "Expert %d built %d source(s) and %d chunk(s) but is INCOMPLETE: "
                "missing %s — not marking ready",
                expert.id, total_sources, total_chunks, " and ".join(missing),
            )
            if not persona_name:
                _raise_if_provider_down("Persona generation")
            raise IncompleteBuildError(missing)

        return BuildResult(
            expert_id=expert.id,
            source_count=total_sources,
            dropped_count=dropped_count,
            chunk_count=total_chunks,
            node_count=node_count,
            edge_count=edge_count,
            avg_quality=avg_quality,
            persona_name=persona_name,
        )

    async def _graph_stage(
        self,
        expert: Expert,
        chunks_for_graph: list[tuple[TextChunk, int]],
        on_event: EventCallback | None,
    ) -> tuple[int, int, bool]:
        """Extract, resolve and reconcile the concept graph.

        Returns ``(node_count, edge_count, built)``. Degrades rather than
        raising: a graph failure leaves a chat-ready corpus standing, and the
        completeness gate decides what that means for the build.
        """
        # Stage 4: Graph extraction
        total_batches = math.ceil(len(chunks_for_graph) / settings.GRAPH_BATCH_SIZE)
        await _emit_event(
            on_event, {"type": "stage", "stage": 4, "name": "graph", "total_batches": total_batches}
        )

        chunks_only = [c for c, _ in chunks_for_graph]
        ids_only = [i for _, i in chunks_for_graph]

        async def _on_graph_batch(labels: list[str], edge_count: int) -> None:
            await _emit_event(
                on_event, {"type": "graph_batch_done", "labels": labels, "edges": edge_count}
            )

        node_count = edge_count = 0
        try:
            extractions = await extract_graph_from_chunks(
                expert.topic, chunks_only, ids_only, on_batch=_on_graph_batch
            )
            node_count, edge_count = await self._graph_repo.bulk_insert_from_extractions(
                expert.id, extractions, embedder=embed_in_batches
            )

            # Entity resolution: merge semantically duplicate graph nodes
            await _emit_event(on_event, {"type": "stage", "stage": 4, "name": "resolve"})
            merged_count = await _resolve_entities(expert.id, self._graph_repo, on_event)
            if merged_count:
                await _emit_event(on_event, {"type": "entities_resolved", "merged": merged_count})
                node_count = max(0, node_count - merged_count)

            # Reconciliation: which claims support, contradict or qualify which.
            # Deliberately after entity resolution — it groups claims by the
            # concept they are `about`, and before the merge that concept is
            # still several near-duplicate nodes, each holding one source's view
            # of it. It is also the only pass that sees more than one source at
            # a time, which is why the per-batch extractor no longer guesses at
            # these relations at all.
            await _emit_event(on_event, {"type": "stage", "stage": 4, "name": "reconcile"})
            relation_count = await _reconcile_claims(
                expert.topic, expert.id, self._graph_repo, on_event
            )
            edge_count += relation_count

            # Edge ordering is evidence counted off the corpus, not a weight the
            # model asserted, so it is computed here once the graph is final.
            await self._graph_repo.recompute_edge_evidence(expert.id)
            return node_count, edge_count, True
        except asyncio.CancelledError:
            raise  # cancellation/shutdown is the worker's business, not a degrade
        except Exception as exc:
            logger.warning("Graph extraction failed for expert %d: %s", expert.id, exc)
            await _emit_event(
                on_event,
                {
                    "type": "stage_degraded",
                    "stage": "graph",
                    "message": (
                        "Concept-graph extraction failed. The corpus is retrievable, "
                        "but an expert is not ready without its graph — this build "
                        f"will be retried. ({exc})"
                    ),
                },
            )
        return node_count, edge_count, False

    # ── the expert's picture ────────────────────────────────────────────────

    async def _find_and_store_picture(
        self,
        expert: Expert,
        topic: str,
        key_concepts: list[str],
        on_event: EventCallback | None,
    ) -> None:
        """Find a licensed picture of the subject and store it. Never raises.

        Everything about this is deliberately outside the build's contract. It
        is not a stage, it does not participate in the completeness gate, and
        the only trace it leaves either way is one durable event — so the build
        log says which picture was chosen and why, or why there is none, and an
        expert with no picture is simply an expert that still shows its
        monogram.

        The one exception re-raised is ``CancelledError``: cancellation is the
        worker shutting the build down, and swallowing it would leave this
        coroutine running after the build it belongs to has gone.
        """
        if not settings.PICTURE_ENABLED:
            await _emit_event(
                on_event, {"type": "picture_skipped", "reason": "disabled"}
            )
            return

        pictures = ExpertPictureRepository(self._pool)
        try:
            # A rebuild does not re-find: the topic has not changed, and the
            # owner may have chosen this one. Only an explicit refresh does.
            if await pictures.exists(expert.id):
                return

            async with WikimediaClient() as client:
                found = await find_picture(client, topic, key_concepts)
            await pictures.upsert(expert.id, found, chosen_by="build")
        except asyncio.CancelledError:
            raise
        except PictureSkipped as skip:
            await _emit_event(
                on_event, {"type": "picture_skipped", "reason": skip.reason}
            )
            return
        except Exception as exc:
            logger.warning(
                "Picture search failed for expert %d (%s: %s)",
                expert.id, type(exc).__name__, exc,
            )
            await _emit_event(
                on_event, {"type": "picture_skipped", "reason": "provider_unavailable"}
            )
            return

        logger.info(
            "Picture for expert %d (%r): %s from %s (%s)",
            expert.id, expert.name, found.file_name, found.page_title, found.license,
        )
        await _emit_event(on_event, {
            "type": "picture_ready",
            "provider": found.provider,
            "title": found.page_title,
            "page_url": found.page_url,
            "license": found.license,
            "version": found.version,
        })

    async def _await_picture(self) -> None:
        """Let the picture task finish, but never wait on it indefinitely.

        ``find_picture`` already carries its own deadline, so this second bound
        only covers the write and exists so a wedged task cannot hold a finished
        build open. A timeout here abandons the task; the `finally` in `build`
        cancels it.
        """
        task = self._picture_task
        if task is None or task.done():
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(task), timeout=settings.PICTURE_TIMEOUT)

    # ── the discovery loop ──────────────────────────────────────────────────

    async def _run_discovery(
        self,
        expert: Expert,
        topic: str,
        plan: dict,
        on_event: EventCallback | None,
    ) -> "DiscoveryOutcome":
        """Search, screen and validate until the corpus meets its targets.

        Round 0 is the plan's own queries over every active fetcher, plus the
        canonical works the plan named, looked for by title. Every round after it
        reads the corpus that exists: the concepts furthest from target become
        feedback queries in the field's own vocabulary, and the round's accepted
        scholarly sources are snowballed through their citations.

        The loop never re-plans. Round 0's brief — its key concepts and
        must-have works — is the standard the corpus is held to, and later
        rounds may only add queries against it. A loop allowed to rewrite its
        own syllabus can always declare itself finished.
        """
        config = expert.config
        target = config.coverage_target()
        key_concepts: list[str] = plan["key_concepts"]
        facets: list[dict] = plan.get("facets") or []
        figures: list[dict] = plan.get("figures") or []
        must_have_titles = [w["title"] for w in plan["must_have_works"]]
        works = _planned_works(plan, config)
        self._primary_definition = plan.get("primary_source_definition") or ""
        self._suggested_works: list[MustHaveWork] = []
        self._text_ceilings = _primary_text_ceilings(expert.tier)
        self._ranked_urls: set[str] = set()
        self._figures = figures
        thought_leaders = (self._fetchers.get("thought_leaders") or (None, 0))[0]
        if figures and isinstance(thought_leaders, ThoughtLeadersFetcher):
            # The channel searches for the plan's figures in their own voice
            # rather than asking a second, blind model call who matters here.
            thought_leaders.use_figures(figures, topic)

        def _measure() -> CoverageReport:
            named = concept_named_texts(self._all_works(plan, config), _outcome_metadata(passed))
            return compute_coverage(
                key_concepts, passed, target, facets,
                {concept: entry["status"] for concept, entry in named.items()},
            )

        base_budget = max(5, round(_BASE_FETCH_BUDGET * config.source_multiplier))
        budget_usd = Decimal(str(discovery_budget_usd(expert.tier, cap_usd=self._cap_usd())))
        batched = (
            current_execution() is BuildExecution.BACKGROUND
            and settings.ANTHROPIC_BATCH_ENABLED
        )
        loop_enabled = discovery_loop_enabled()
        max_rounds = target.max_rounds if loop_enabled else 0
        min_rounds = min(target.min_rounds, max_rounds)

        _log_previous_build(expert, batched)
        await _quietly(
            "clear the previous attempt's screening ledger",
            self._repo.clear_candidate_screenings(expert.id, self._job_id),
        )
        self._ledger_expert_id = expert.id
        self._fetcher_status = {}
        self._canonical = []
        self._queued_substitutes: list[MustHaveWork] = []

        # Caps are computed once, from the whole build's ceiling, and their counts
        # persist across rounds — a cap applied per round would let a type take
        # its full share again in every one of them, which is the flooding the
        # cap exists to prevent.
        caps = _type_caps(self._fetchers, base_budget)
        type_counts: dict[SourceType, int] = {}

        seen = SeenSet()
        passed: list[ValidatedSource] = []
        dropped: list[DroppedSource] = []
        coverage = _measure()
        committed_usd = Decimal(0)
        remaining_count = base_budget
        stop_reason = STOP_MAX_ROUNDS if max_rounds else STOP_LOOP_DISABLED
        round_n = 0
        # Rounds that actually fetched and validated something. Distinct from
        # ``round_n``, which is the index of the round being *set up* — a round
        # that finds no new candidates and breaks before running must not be
        # reported as a round that ran.
        rounds_run = 0

        while True:
            round_budget_usd = budget_usd - committed_usd
            if round_n == 0:
                queries_by_fetcher = {
                    name: list(plan["fetcher_plans"].get(name, {}).get("queries") or [topic])
                    for name in self._fetchers
                }
                extra_candidates = await self._resolve_canonical(works, on_event, round_n)
                round_budget = base_budget
                weakest: list[ConceptCoverage] = []
                if min_rounds:
                    # Money for the guaranteed round: see _ROUND0_BUDGET_SHARE.
                    round_budget_usd = min(round_budget_usd, budget_usd * _ROUND0_BUDGET_SHARE)
            else:
                # Every target met, and the round runs anyway because the tier
                # guarantees it: it searches for depth where the corpus is
                # thinnest instead of for targets it has already reached. Either
                # way the concepts are taken a facet at a time, so one heavy
                # facet's neighbours cannot take the whole round.
                weakest = coverage.weakest_by_facet(
                    _LOOP_MAX_CONCEPTS
                ) or coverage.thinnest_by_facet(_LOOP_MAX_CONCEPTS)
                queries_by_fetcher, extra_candidates = await self._plan_round(
                    topic, weakest, passed, seen, config, on_event, round_n, plan, key_concepts
                )
                if round_n == 1:
                    extra_candidates += await self._retry_canonical(works, passed, on_event)
                round_budget = min(
                    remaining_count,
                    math.ceil(_LOOP_ROUND_BUDGET_SHARE * base_budget),
                )
                if not queries_by_fetcher and not extra_candidates:
                    stop_reason = STOP_NO_NEW_CANDIDATES
                    break

            # A stage event per round, not once for the whole loop: the meter
            # attributes spend to whichever stage was last announced, and
            # round N's triage happens after round N-1's `validate`.
            await _emit_event(
                on_event, {"type": "stage", "stage": 1, "name": "discover", "round": round_n}
            )
            await _emit_event(
                on_event,
                {
                    "type": "round_started",
                    "round": round_n,
                    "budget": round_budget,
                    "budget_usd": float(budget_usd),
                    "round_budget_usd": float(round_budget_usd),
                    "targets": target.as_dict(),
                    "weakest": [c.concept for c in weakest],
                },
            )

            raw_sources, round_cost = await self._discovery_round(
                topic,
                plan,
                queries_by_fetcher,
                _boosted_must_have_titles(must_have_titles, round_n, self._canonical, passed),
                round_budget,
                round_budget_usd,
                seen,
                extra_candidates,
                caps,
                type_counts,
                on_event,
                round_n,
                batched,
            )
            committed_usd += round_cost
            remaining_count -= len(raw_sources)

            if not raw_sources:
                stop_reason = (
                    STOP_NO_NEW_CANDIDATES if round_n else stop_reason
                )
                if round_n == 0:
                    raise BuildError(
                        "No sources discovered. Check API keys and network access."
                    )
                break

            round_passed, round_dropped = await self._validate_round(
                expert, topic, raw_sources, key_concepts, on_event, round_n
            )
            unjudged = sum(
                1 for d in round_dropped
                if d.drop_reason in ("validation error", "missing validation")
            )
            if unjudged and not round_passed:
                _raise_if_provider_down("Source validation")
            passed.extend(round_passed)
            dropped.extend(round_dropped)
            for source in raw_sources:
                seen.add_source(source)

            # Give back the budget reserved for sources validation rejected.
            # The estimate is made at fetch time, when nothing is known about
            # which sources will survive, so it necessarily covers everything
            # fetched — but only the accepted ones are ever ingested. Holding
            # the rejected ones' cost against the budget stops the loop about a
            # rejection-rate early: on a live STANDARD build it reserved $3.04
            # of a $3.00 budget for 60 fetched sources when the 48 that passed
            # were the only ones that would ever cost anything to ingest.
            ingested_cost = sum(
                _ingest_estimate(vs.raw, batched) for vs in round_passed
            )
            committed_usd -= round_cost - ingested_cost

            rounds_run += 1
            coverage = _measure()
            spent_usd = _metered_spend()
            await _emit_event(
                on_event,
                {
                    "type": "coverage_report",
                    "round": round_n,
                    "spent_usd": float(spent_usd),
                    "committed_usd": float(committed_usd),
                    "budget_usd": float(budget_usd),
                    **coverage.as_dict(),
                },
            )

            # ── stop conditions, in the order they become knowable ───────────
            # Over the sources the validator actually judged: an errored batch
            # says nothing about whether the search space is exhausted.
            judged = len(raw_sources) - unjudged
            acceptance = len(round_passed) / judged if judged else 1.0
            if coverage.met and key_concepts and round_n >= min_rounds:
                stop_reason = STOP_TARGETS_MET
                break
            if round_n >= max_rounds:
                stop_reason = STOP_LOOP_DISABLED if max_rounds == 0 else STOP_MAX_ROUNDS
                break
            if spent_usd + committed_usd >= budget_usd:
                stop_reason = STOP_BUDGET_EXHAUSTED
                break
            if remaining_count <= 0:
                stop_reason = STOP_SOURCE_LIMIT
                break
            if (
                judged >= _ACCEPTANCE_MIN_SAMPLE
                and acceptance < _ACCEPTANCE_COLLAPSE
            ):
                # The search space is exhausted: this round fetched real
                # sources and validation wanted almost none of them. Another
                # round buys more of the same.
                stop_reason = STOP_ACCEPTANCE_COLLAPSED
                break
            round_n += 1

        all_dropped = dropped + self._content_duplicates
        all_works = self._all_works(plan, config)
        accepted_metadata = _outcome_metadata(passed)
        must_have = must_have_outcomes(all_works, self._canonical, accepted_metadata)
        outcome = DiscoveryOutcome(
            passed=passed,
            dropped=all_dropped,
            coverage=coverage,
            rounds=rounds_run,
            stop_reason=stop_reason,
            spent_usd=float(_metered_spend()),
            committed_usd=float(committed_usd),
            budget_usd=float(budget_usd),
            corpus=corpus_composition(
                passed, all_dropped, key_concepts, must_have,
                named_texts=concept_named_texts(all_works, accepted_metadata),
                figures=figure_outcomes(figures, all_works, accepted_metadata),
            ),
            channels={
                name: status
                for name, status in self._fetcher_status.items()
                if status not in HEALTHY_STATUSES
            },
        )
        await _emit_event(on_event, {"type": "discovery_done", **outcome.summary()})
        return outcome

    async def _resolve_canonical(
        self,
        works: list[MustHaveWork],
        on_event: EventCallback | None,
        round_n: int,
    ) -> list[SourceCandidate]:
        """Look for the plan's must-have works by title. Never raises.

        The candidates it returns enter triage like any other, already marked
        ``fetch_priority`` — they do not depend on a score — and carry whether
        each one is the whole work or a section of it.
        """
        if not works:
            return []
        exa = ExaFetcher() if settings.EXA_API_KEY else None
        try:
            resolutions = await resolve_works(
                works,
                exa_search=exa.search if exa is not None else None,
                max_chars=getattr(self, "_text_ceilings", None),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Canonical work resolution failed: %s", exc, exc_info=True)
            return []
        by_key = {r.work.key: r for r in self._canonical}
        for resolution in resolutions:
            by_key[resolution.work.key] = resolution
        self._canonical = list(by_key.values())
        await _emit_event(
            on_event,
            {
                "type": "canonical_resolved",
                "round": round_n,
                "works": [r.as_dict() for r in resolutions],
            },
        )
        candidates = [c for r in resolutions for c in r.candidates]

        # A work that cannot legally be had, and was not found whole: its
        # substitute is looked for as a work of its own (docs/plans/syllabus.md,
        # 3.B). Resolved after, not beside, so a substitute is only paid for
        # when the work it stands in for is out of reach.
        queued = {w.key for w in self._substitutes()}
        substitutes = [
            r.work.substitute for r in resolutions
            if r.work.substitute is not None and not r.work.obtainable and not r.whole
            and r.work.substitute.key not in queued
        ]
        if substitutes:
            self._queued_substitutes = [*self._substitutes(), *substitutes]
            candidates += await self._resolve_canonical(substitutes, on_event, round_n)

        return _merge_same_volume(
            candidates, getattr(self, "_text_ceilings", {}).get(SCOPE_OVERALL)
        )

    def _substitutes(self) -> list[MustHaveWork]:
        """Substitute works queued for lookup so far in this discovery run."""
        return list(getattr(self, "_queued_substitutes", []))

    async def _retry_canonical(
        self,
        works: list[MustHaveWork],
        passed: list[ValidatedSource],
        on_event: EventCallback | None,
    ) -> list[SourceCandidate]:
        """Round 1 looks again for works round 0 could not find whole.

        Two reasons qualify. A route that timed out or errored — one that
        answered "nothing" is not asked again; that is the canonical-work half
        of retrying failed channels in later rounds. And a work whose every hit
        was dropped before fetch: before triage stopped treating a work's
        volumes as near-duplicates of each other, the Summa's second part was
        found and dropped that way, and nothing looked for it again. Dropped hits
        never entered the seen set, so looking again finds them again.
        """
        ranked: set[str] = getattr(self, "_ranked_urls", set())
        failed = {r.work.title for r in self._canonical if r.route_errors} | {
            r.work.title
            for r in self._canonical
            if r.candidates and not any(_url_key(c.url) in ranked for c in r.candidates)
        }
        if not failed:
            return []
        found = {
            o["title"]
            for o in must_have_outcomes(
                works, self._canonical, _outcome_metadata(passed)
            )
            if o["status"] in (FOUND_WHOLE, FOUND_SECTIONS)
        }
        retry = [w for w in works if w.title in failed and w.title not in found]
        return await self._resolve_canonical(retry, on_event, 1) if retry else []

    def _cap_usd(self) -> float | None:
        """The hard spend cap this build is running under, if the meter knows it."""
        meter = current_meter()
        if meter is None or meter.cap_usd is None:
            return None
        return float(meter.cap_usd)

    async def _plan_round(
        self,
        topic: str,
        weakest: list[ConceptCoverage],
        passed: list[ValidatedSource],
        seen: SeenSet,
        config,
        on_event: EventCallback | None,
        round_n: int,
        plan: dict | None = None,
        key_concepts: list[str] | None = None,
    ) -> tuple[dict[str, list[str]], list[SourceCandidate]]:
        """Queries and citation candidates for a follow-up round."""
        queries_by_fetcher: dict[str, list[str]] = {}
        author_candidates: list[SourceCandidate] = []
        if weakest:
            works = self._all_works(plan or {}, config)
            accepted_metadata = _outcome_metadata(passed)
            named = concept_named_texts(works, accepted_metadata)
            figures = getattr(self, "_figures", None) or (plan or {}).get("figures") or []
            per_concept = await feedback_queries(
                topic,
                weakest,
                passed,
                top_concept_shares(passed, key_concepts or []) if key_concepts else None,
                facet_of={
                    concept: facet["name"]
                    for facet in (plan or {}).get("facets") or []
                    for concept in facet.get("concepts") or []
                },
                missing_texts={
                    concept: entry["texts"]
                    for concept, entry in named.items()
                    if entry["status"] == NAMED_MISSING
                },
                voiceless_figures=[
                    f["name"]
                    for f in figure_outcomes(figures, works, accepted_metadata)
                    if f["status"] != "own_voice"
                ],
            )
            authors = list(getattr(per_concept, "authors", []) or [])
            if authors:
                author_candidates = await self._search_authors(authors, topic, on_event, round_n)
            flat: list[str] = []
            for concept in weakest:
                for query in per_concept.get(concept.concept, []):
                    if query not in flat:
                        flat.append(query)
            status = getattr(self, "_fetcher_status", {})
            loop_fetchers = [
                n for n in self._fetchers
                if n in _LOOP_FETCHERS or status.get(n) in TRANSIENT_STATUSES | {STATUS_ERROR}
            ]
            retried = [n for n in loop_fetchers if n not in _LOOP_FETCHERS]
            queries_by_fetcher = {
                name: (
                    list((plan or {}).get("fetcher_plans", {}).get(name, {}).get("queries") or [topic])
                    if name in _PLAN_QUERY_FETCHERS
                    else list(flat)
                )
                for name in loop_fetchers
            }
            await _emit_event(
                on_event,
                {
                    "type": "feedback_queries",
                    "round": round_n,
                    "concepts": [c.concept for c in weakest],
                    "without_primary": [c.concept for c in weakest if not c.has_primary],
                    "authors": authors,
                    "queries": flat,
                    "fetchers": loop_fetchers,
                    "retried_fetchers": retried,
                },
            )

        # Primary texts for the concepts that still have none, looked up by
        # title. The queries above go to search engines, which answer with
        # scholarship about a subject far more readily than with its own texts.
        primary_candidates: list[SourceCandidate] = []
        lacking = [c.concept for c in weakest if not c.has_primary]
        limit = getattr(config, "concept_primary_texts", 0)
        if lacking and limit > 0 and getattr(config, "coverage_require_primary", False):
            tried = [r.work.title for r in getattr(self, "_canonical", [])]
            suggestions = await suggest_primary_texts(
                topic, getattr(self, "_primary_definition", ""), lacking, tried
            )
            new_works = [MustHaveWork.from_plan(t, SCOPE_CONCEPT) for t in suggestions][:limit]
            if new_works:
                await _emit_event(
                    on_event,
                    {
                        "type": "primary_texts_suggested",
                        "round": round_n,
                        "concepts": lacking,
                        "texts": suggestions[: len(new_works)],
                    },
                )
                self._suggested_works = [*getattr(self, "_suggested_works", []), *new_works]
                primary_candidates = await self._resolve_canonical(new_works, on_event, round_n)

        # Snowball from what the corpus has already accepted. Seeded from every
        # accepted scholarly source, not just this round's, so a two-hop tier
        # reaches the references of references without extra machinery.
        candidates: list[SourceCandidate] = []
        if config.snowball_max_per_round > 0 and round_n <= config.snowball_hops:
            try:
                candidates = await snowball(
                    passed, seen, max_candidates=config.snowball_max_per_round
                )
            except Exception as exc:
                logger.warning("Snowball failed in round %d: %s", round_n, exc)
                candidates = []
            if candidates:
                await _emit_event(
                    on_event,
                    {
                        "type": "snowball_done",
                        "round": round_n,
                        "added": len(candidates),
                        "backward": sum(
                            1 for c in candidates
                            if c.metadata.get("discovered_via") == "snowball:backward"
                        ),
                        "forward": sum(
                            1 for c in candidates
                            if c.metadata.get("discovered_via") == "snowball:forward"
                        ),
                    },
                )
        return queries_by_fetcher, primary_candidates + author_candidates + candidates

    def _all_works(self, plan: dict, config) -> list[MustHaveWork]:
        """Every work this discovery run has looked for: planned, suggested, substituted."""
        return (
            _planned_works(plan, config)
            + list(getattr(self, "_suggested_works", []))
            + self._substitutes()
        )

    async def _search_authors(
        self,
        authors: list[str],
        topic: str,
        on_event: EventCallback | None,
        round_n: int,
    ) -> list[SourceCandidate]:
        """Writing *by* the authors the corpus cites and does not contain. Never raises.

        Through the thought-leader search, which excludes the encyclopedias and
        summary services and drops pages titled as entries about a person — raw
        web search answered an author's name with exactly those pages.
        """
        if "thought_leaders" not in getattr(self, "_fetchers", {}):
            return []
        try:
            found = await ThoughtLeadersFetcher.search_people(
                [{"name": name, "why": "cited by the corpus, not yet in it"} for name in authors],
                topic,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Author search failed in round %d: %s", round_n, exc)
            return []
        for candidate in found:
            candidate.metadata.setdefault("discovered_via", "feedback:author")
        await _emit_event(
            on_event,
            {"type": "authors_searched", "round": round_n, "authors": authors, "added": len(found)},
        )
        return found

    async def _discovery_round(
        self,
        topic: str,
        plan: dict,
        queries_by_fetcher: dict[str, list[str]],
        must_have_titles: list[str],
        budget: int,
        budget_usd: Decimal,
        seen: SeenSet,
        extra_candidates: list[SourceCandidate],
        caps: dict[SourceType, int],
        type_counts: dict[SourceType, int],
        on_event: EventCallback | None,
        round_n: int,
        batched: bool,
    ) -> tuple[list[RawSource], Decimal]:
        """One round: search → dedup → triage → budgeted fetch → content dedup.

        Returns the fetched sources and the estimated ingest cost the round
        committed to, which is what the loop spends against its budget. Writes
        the round's screening ledger on the way out.
        """
        active = set(queries_by_fetcher)
        if round_n == 0:
            await _emit_event(
                on_event,
                {
                    "type": "discovery_started",
                    "fetchers": list(_FETCHER_NAMES),
                    "active": list(active),
                },
            )

        # One query for the identify-then-fetch fetchers: each query is a model
        # call that names books or people, and three of them per build asked the
        # same question three ways.
        _SINGLE_QUERY_FETCHERS = {"thought_leaders", "gutenberg"}
        status_by_fetcher: dict[str, str] = getattr(self, "_fetcher_status", None) or {}
        self._fetcher_status = status_by_fetcher

        async def _search_one(
            name: str, fetcher, quota: int, attempt: int = 0
        ) -> tuple[str, SearchOutcome]:
            queries = queries_by_fetcher.get(name) or [topic]
            if name in _SINGLE_QUERY_FETCHERS:
                queries = queries[:1]
            per_query = _search_breadth(quota, len(queries))
            started = time.monotonic()
            outcomes = await asyncio.gather(
                *[_safe_search(name, fetcher, query, per_query) for query in queries]
            )
            candidates = deduplicate_by_url([c for o in outcomes for c in o.candidates])
            skipped, reason = _is_skipped(name, candidates)
            if candidates:
                status, error = STATUS_OK, ""
            elif skipped:
                status, error = STATUS_SKIPPED, reason
            else:
                status = worst_status([o.status for o in outcomes])
                error = next((o.error for o in outcomes if o.status == status and o.error), "")
            status_by_fetcher[name] = status
            await _emit_event(
                on_event,
                {
                    "type": "fetcher_done",
                    "round": round_n,
                    "name": name,
                    "count": len(candidates),
                    "skipped": skipped,
                    "reason": reason or error,
                    "status": status,
                    "error": error,
                    "attempt": attempt,
                    "elapsed": round(time.monotonic() - started, 1),
                    "queries": len(queries),
                },
            )
            return name, SearchOutcome(candidates, status, error)

        searched = dict(
            await asyncio.gather(
                *[
                    _search_one(name, fetcher, quota)
                    for name, (fetcher, quota) in self._fetchers.items()
                    if name in active
                ]
            )
        )
        # A channel that timed out or was rate-limited gets one more try, one at
        # a time so a retry is not itself another burst against a rate limit.
        # Gutendex timing out twice is then a status the loop can act on rather
        # than a coincidence.
        for name, outcome in list(searched.items()):
            if not outcome.transient:
                continue
            fetcher, quota = self._fetchers[name]
            await _emit_event(
                on_event,
                {"type": "fetcher_retried", "round": round_n, "name": name, "after": outcome.status},
            )
            _, searched[name] = await _search_one(name, fetcher, quota, attempt=1)

        # Extra candidates first: URL de-duplication keeps the first copy it
        # sees, and a canonical work's or a co-cited snowball find's copy
        # carries what the plain search hit for the same URL does not — that it
        # is a must-have, whether it is the whole work, that it is a priority.
        pooled = list(extra_candidates) + [c for o in searched.values() for c in o.candidates]
        if not pooled:
            return [], Decimal(0)

        # Identity → URL, against everything the build has already considered.
        # This is where the same paper found as an arXiv preprint, a journal DOI
        # and a Semantic Scholar OA PDF becomes one candidate rather than three.
        candidates, dedup = deduplicate_candidates(pooled, seen)
        await _emit_event(
            on_event, {"type": "dedup_done", "round": round_n, **dedup.as_event()}
        )
        if not candidates:
            return [], Decimal(0)

        # Triage — the same brief every round; only the queries change.
        triaged = await triage_candidates(
            topic,
            plan["key_concepts"],
            must_have_titles,
            candidates,
        )
        if triaged and all(t.model_score is None for t in triaged):
            # Nothing scored at all. If the provider refused the calls (an empty
            # credit balance, a revoked key) that is not a finding about the
            # candidates, and carrying on would build a corpus from priority
            # candidates alone and report it as a quality collapse.
            _raise_if_provider_down("Source triage")
        ranked = rank_candidates(triaged)
        ranked_urls = getattr(self, "_ranked_urls", None)
        for item in ranked:
            seen.add_candidate(item.candidate)
            if ranked_urls is not None:
                ranked_urls.add(_url_key(item.candidate.url))

        floor = settings.FETCH_SCORE_FLOOR
        reaching = sum(
            1 for t in ranked if t.score >= floor or t.candidate.metadata.get("fetch_priority")
        )
        needed = max(_FLOOR_RELAX_MIN, budget // 4)
        if round_n == 0 and reaching < needed and floor > settings.FETCH_SCORE_FLOOR_RELAXED:
            # A thin topic must not produce an empty round 0. Later rounds never
            # relax: by then the corpus exists, and an empty round is an answer.
            await _emit_event(
                on_event,
                {
                    "type": "floor_relaxed",
                    "round": round_n,
                    "floor": floor,
                    "relaxed_to": settings.FETCH_SCORE_FLOOR_RELAXED,
                    "reaching": reaching,
                    "needed": needed,
                },
            )
            floor = settings.FETCH_SCORE_FLOOR_RELAXED

        await _emit_event(
            on_event,
            {
                "type": "triage_done",
                "round": round_n,
                "candidates": len(candidates),
                "ranked": len(ranked),
                "budget": budget,
                "floor": floor,
                "above_floor": sum(
                    1 for t in ranked
                    if t.score >= floor or t.candidate.metadata.get("fetch_priority")
                ),
                "unscored": sum(1 for t in triaged if t.model_score is None),
            },
        )

        outcomes: dict[int, tuple[int | None, str]] = {}
        sources, committed = await self._fetch_with_refill(
            ranked, budget, caps, type_counts, budget_usd, batched, on_event, round_n,
            floor=floor, outcomes=outcomes,
        )

        # Content fingerprinting, on text that now exists. This is the
        # preprint-versus-published case that identity misses when one side has
        # no DOI: two records, no shared id, the same document.
        sources, duplicates = deduplicate_sources_by_content(sources, seen)
        duplicate_urls = {source.url for source, _ in duplicates}
        for source, of_url in duplicates:
            # Visible as a drop with a reason, not silently gone. A source that
            # disappears between fetching and validation is exactly the kind of
            # hole the screening ledger exists to close.
            self._content_duplicates.append(
                DroppedSource(
                    raw=source,
                    quality_score=0.0,
                    relevance_score=0.0,
                    drop_reason=f"duplicate of {of_url}",
                )
            )
        await _emit_event(
            on_event,
            {
                "type": "fetch_done",
                "round": round_n,
                "fetched": len(sources),
                "content_duplicates": len(duplicates),
                "budget": budget,
                "estimated_ingest_usd": float(committed),
                "outcomes": _count_outcomes(outcomes.values()),
            },
        )

        ranked_ids = {id(t.candidate) for t in ranked}
        rows = []
        for item in triaged:
            c = item.candidate
            if id(c) in outcomes:
                rank, fetch_outcome = outcomes[id(c)]
            elif id(c) in ranked_ids:
                rank, fetch_outcome = None, OUTCOME_NOT_REACHED
            elif item.score < MIN_TRIAGE_SCORE:
                rank, fetch_outcome = None, OUTCOME_BELOW_FLOOR
            else:
                rank, fetch_outcome = None, OUTCOME_NEAR_DUPLICATE
            if fetch_outcome == OUTCOME_FETCHED and c.url in duplicate_urls:
                fetch_outcome = OUTCOME_CONTENT_DUPLICATE
            rows.append(
                {
                    "round": round_n,
                    "source_type": c.source_type.value,
                    "url": c.url,
                    "title": c.title or c.url,
                    "author": c.author,
                    "snippet": (c.snippet or "")[:TRIAGE_SNIPPET_CHARS],
                    "discovered_via": c.metadata.get("discovered_via")
                    or ("plan" if round_n == 0 else "feedback"),
                    "model_score": item.model_score,
                    "domain_adjustment": item.domain_adjustment,
                    "triage_score": item.score,
                    "triage_status": item.status,
                    "fetch_rank": rank,
                    "fetch_outcome": fetch_outcome,
                }
            )
        expert_id = getattr(self, "_ledger_expert_id", None)
        if expert_id is not None:
            await _quietly(
                "write the screening ledger",
                self._repo.insert_candidate_screenings(expert_id, self._job_id, rows),
            )
        return sources, committed

    async def _validate_round(
        self,
        expert: Expert,
        topic: str,
        raw_sources: list[RawSource],
        key_concepts: list[str],
        on_event: EventCallback | None,
        round_n: int,
    ) -> tuple[list[ValidatedSource], list[DroppedSource]]:
        """Validate one round's sources, capturing them first when asked to.

        The capture wraps the call rather than living inside the validator, so
        every path that validates — round 0, a later round, a future re-screen —
        is captured by construction.

        The composition caps apply here, per round, after the validator's
        verdict: abstract-only and tertiary sources beyond their share are
        dropped with a reason (see experts/composition.py).
        """
        await _emit_event(
            on_event,
            {
                "type": "stage",
                "stage": 2,
                "name": "validate",
                "round": round_n,
                "total": len(raw_sources),
            },
        )
        capture_for_screening(expert, self._job_id, raw_sources, topic, key_concepts, round_n)
        passed, dropped = await validate_sources(
            topic,
            raw_sources,
            key_concepts,
            primary_definition=getattr(self, "_primary_definition", "") or None,
            on_result=lambda r: _emit_event(
                on_event, {"type": "source_validated", "round": round_n, **r}
            ),
            on_reviewed=lambda r: _emit_event(
                on_event, {"type": "source_reviewed", "round": round_n, **r}
            ),
        )
        passed, capped = apply_composition_caps(passed)
        if capped:
            dropped = dropped + capped
            await _emit_event(
                on_event,
                {
                    "type": "composition_capped",
                    "round": round_n,
                    "dropped": [
                        {"title": d.raw.title, "reason": d.drop_reason} for d in capped
                    ],
                },
            )
        await _emit_event(
            on_event,
            {
                "type": "validate_done",
                "round": round_n,
                "passed": len(passed),
                "dropped": len(dropped),
                "capped": len(capped),
            },
        )
        return passed, dropped

    async def _load_upload_chunks(
        self, expert_id: int
    ) -> list[tuple[TextChunk, int]]:
        """Chunks belonging to user-supplied sources that survived the reset."""
        return await self._load_chunks(expert_id, uploads_only=True)

    async def _load_chunks(
        self, expert_id: int, uploads_only: bool = False
    ) -> list[tuple[TextChunk, int]]:
        """Stored chunks, as ``(TextChunk, chunk_db_id)`` pairs for the graph stage.

        ``context_text`` is not needed — graph extraction reads the chunk text —
        so it is not selected.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id, c.source_id, c.text, c.sequence_n, c.chunk_meta
                FROM source_chunks c
                JOIN sources s ON s.id = c.source_id
                WHERE c.expert_id = $1
                  AND (NOT $2 OR s.discovered_via = 'upload')
                ORDER BY c.source_id, c.sequence_n
                """,
                expert_id, uploads_only,
            )
        out: list[tuple[TextChunk, int]] = []
        per_source: dict[int, int] = {}
        for r in rows:
            seen_for_source = per_source.get(r["source_id"], 0)
            per_source[r["source_id"]] = seen_for_source + 1
            if seen_for_source >= _graph_chunk_limit(seen_for_source + 1):
                continue
            meta = r["chunk_meta"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            out.append((
                TextChunk(
                    text=r["text"],
                    sequence_n=r["sequence_n"],
                    chunk_meta=meta or {},
                ),
                r["id"],
            ))
        return out

    async def _count_upload_sources(self, expert_id: int) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                """
                SELECT COUNT(*) FROM sources
                WHERE expert_id = $1 AND passed = true AND discovered_via = 'upload'
                """,
                expert_id,
            ) or 0

    async def _fetch_with_refill(
        self,
        ranked: list[TriagedCandidate],
        budget: int,
        caps: dict[SourceType, int],
        counts: dict[SourceType, int] | None = None,
        budget_usd: Decimal = Decimal(0),
        batched: bool = False,
        on_event: EventCallback | None = None,
        round_n: int = 0,
        *,
        floor: float = 0.0,
        outcomes: dict[int, tuple[int | None, str]] | None = None,
    ) -> tuple[list[RawSource], Decimal]:
        """Fetch full content for ranked candidates until a budget is met.

        Two budgets bind here, and the money one is the real one. The count is a
        ceiling that keeps a pathological round from running forever; the
        estimated ingest cost of what has been fetched is what actually stops
        the wave, because a 120,000-character monograph and a 2,000-character
        blog post are one unit each to a count and two orders of magnitude apart
        in what they cost to ingest.

        Beside both sits a quality bar: a candidate scored under ``floor`` is not
        fetched, however much count and money are left, unless something other
        than its score vouches for it (``fetch_priority``). Without the bar the
        queue walked down the ranked tail once the good types capped out and
        filled the last third of the Thomism corpus from it.

        Order is by triage score, with estimated cost as the tiebreaker and a
        reserved front rank for works the pipeline has independent evidence
        about — see :func:`_fetch_sort_key`, which explains why ordering by
        value per dollar emptied a Thomism corpus of Aquinas.

        Works down the ordered list in concurrent waves; failed fetches free
        their slot so lower-ranked candidates get a chance. Per-type caps are
        enforced on successful fetches; a must-have work is exempt from them.

        ``outcomes``, when passed, is filled with ``id(candidate) → (fetch rank,
        outcome)`` for the screening ledger.

        A ``fetch_progress`` event goes out after every wave. This used to be the
        build's one long silence — dozens of network fetches between
        ``triage_done`` and ``fetch_done``, with nothing in between — which made
        a dead worker and a working one look identical for as long as anyone
        cared to watch. One event per wave bounds that silence to a single wave,
        which SOURCE_FETCH_TIMEOUT in turn bounds in wall-clock time.
        """
        fetcher_by_type = {
            _FETCHER_SOURCE_TYPES[name]: fetcher for name, (fetcher, _) in self._fetchers.items()
        }
        ordered = sorted(ranked, key=lambda t: _fetch_sort_key(t, batched))
        record = outcomes if outcomes is not None else {}
        results: list[RawSource] = []
        # Shared with the caller across rounds when one is passed; a lone caller
        # (a test) gets a fresh tally.
        counts = {} if counts is None else counts
        committed = Decimal(0)
        idx = 0
        attempted = 0
        rank = 0
        stopped_on_money = False
        priority_committed = Decimal(0)
        reserved: dict[int, Decimal] = {}
        priority_ceiling = budget_usd * _PRIORITY_BUDGET_SHARE if budget_usd > 0 else None

        def _is_priority(candidate: SourceCandidate) -> bool:
            if not candidate.metadata.get("fetch_priority"):
                return False
            return priority_ceiling is None or priority_committed < priority_ceiling

        while len(results) < budget and idx < len(ordered):
            if budget_usd > 0 and committed >= budget_usd:
                stopped_on_money = True
                logger.info(
                    "Round %d stopped fetching at %d source(s): committed $%.3f of a "
                    "$%.3f estimated-ingest budget",
                    round_n, len(results), float(committed), float(budget_usd),
                )
                break
            wave: list[TriagedCandidate] = []
            while idx < len(ordered) and len(wave) < min(_FETCH_CONCURRENCY, budget - len(results)):
                item = ordered[idx]
                candidate = item.candidate
                idx += 1
                priority = _is_priority(candidate)
                if item.score < floor and not priority:
                    record[id(candidate)] = (None, OUTCOME_BELOW_FLOOR)
                    continue
                rank += 1
                # A must-have work neither needs a slot in its type's share nor
                # takes one: the plan named it, and a Gutenberg volume must not
                # crowd out the Gutenberg texts triage chose.
                capped_type = not candidate.metadata.get("must_have_title")
                if capped_type:
                    cap = caps.get(candidate.source_type, budget)
                    if counts.get(candidate.source_type, 0) >= cap:
                        record[id(candidate)] = (rank, OUTCOME_CAPPED)
                        continue
                    counts[candidate.source_type] = counts.get(candidate.source_type, 0) + 1
                if priority:
                    # Reserved at admission, not at completion: a wave admits up
                    # to six candidates before any of them has a length.
                    reserved[id(candidate)] = _priority_reservation(candidate, batched)
                    priority_committed += reserved[id(candidate)]
                record[id(candidate)] = (rank, OUTCOME_NOT_REACHED)
                wave.append(item)
            if not wave:
                break
            fetched = await asyncio.gather(
                *[
                    _safe_fetch_candidate(
                        _fetcher_for(t.candidate, fetcher_by_type), t.candidate
                    )
                    for t in wave
                ]
            )
            attempted += len(wave)
            for item, source in zip(wave, fetched, strict=True):
                candidate = item.candidate
                position = record[id(candidate)][0]
                held = reserved.pop(id(candidate), Decimal(0))
                priority_committed -= held
                if source is None:
                    if not candidate.metadata.get("must_have_title"):
                        counts[candidate.source_type] -= 1
                    record[id(candidate)] = (position, OUTCOME_FAILED)
                elif not is_expected_language(source.text):
                    if not candidate.metadata.get("must_have_title"):
                        counts[candidate.source_type] -= 1
                    logger.info(
                        "Not %s: %r (%s) — dropped before validation",
                        settings.CORPUS_LANGUAGE, candidate.title, candidate.url,
                    )
                    record[id(candidate)] = (position, OUTCOME_NOT_ENGLISH)
                else:
                    _carry_candidate_metadata(candidate, source, item.score)
                    _enforce_ceiling(candidate, source)
                    results.append(source)
                    cost = _ingest_estimate(source, batched)
                    committed += cost
                    if held:
                        priority_committed += cost
                    record[id(candidate)] = (position, OUTCOME_FETCHED)
            await _emit_event(
                on_event,
                {
                    "type": "fetch_progress",
                    "round": round_n,
                    "fetched": len(results),
                    "attempted": attempted,
                    "budget": budget,
                    "estimated_ingest_usd": float(committed),
                },
            )
        for item in ordered[idx:]:
            candidate = item.candidate
            if id(candidate) in record:
                continue
            if item.score < floor and not _is_priority(candidate):
                record[id(candidate)] = (None, OUTCOME_BELOW_FLOOR)
            else:
                record[id(candidate)] = (
                    None, OUTCOME_BUDGET if stopped_on_money else OUTCOME_NOT_REACHED
                )
        return results, committed

    async def _persist_sources(
        self,
        expert_id: int,
        passed: list[ValidatedSource],
        dropped: list[DroppedSource],
    ) -> list[int]:
        """Write all sources to DB. Returns DB IDs for passed sources only.

        ``validator_model`` comes off each row's own verdict rather than from
        settings: with a borderline-band reviewer running, two models judge
        different sources in one build, and a column filled in from
        configuration would attribute both to whichever model the config names.
        """
        passed_ids: list[int] = []
        async with self._pool.acquire() as conn, conn.transaction():
            for vs in passed:
                ids = vs.identifiers
                meta = vs.raw.metadata
                row = await conn.fetchrow(
                    """
                        INSERT INTO sources
                            (expert_id, source_type, url, title, author,
                             quality_score, relevance_score, content_type,
                             difficulty, key_claims, passed,
                             validator_model, rubric_version,
                             covered_concepts, discovered_via, source_tier,
                             doi, arxiv_id, identifiers,
                             full_text_method, text_chars,
                             review_model, first_pass_quality, first_pass_relevance,
                             snowball_seed_urls, triage_score, substance, concept_depths)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,true,$11,$12,$13::jsonb,
                                $14,$15,$16,$17,$18::jsonb,$19,$20,$21,$22,$23,$24::jsonb,
                                $25,$26,$27::jsonb)
                        RETURNING id
                        """,
                    expert_id,
                    vs.source_type.value,
                    vs.url,
                    vs.title,
                    vs.author,
                    vs.quality_score,
                    vs.relevance_score,
                    vs.content_type,
                    vs.difficulty,
                    json.dumps(vs.key_claims),
                    vs.validator_model or settings.FAST_MODEL,
                    RUBRIC_VERSION,
                    json.dumps(vs.covered_concepts),
                    meta.get("discovered_via", "plan"),
                    # NULL when the validator didn't classify it — see migration 020.
                    vs.source_tier,
                    ids.doi,
                    ids.arxiv_id,
                    json.dumps(ids.to_dict()) if not ids.is_empty() else None,
                    meta.get("full_text_method"),
                    len(vs.text),
                    vs.review_model,
                    vs.first_pass_quality,
                    vs.first_pass_relevance,
                    json.dumps(meta["snowball_seed_urls"])
                    if meta.get("snowball_seed_urls") else None,
                    _as_score(meta.get("triage_score")),
                    vs.substance or substance_of(vs.raw),
                    json.dumps(vs.concept_depths) if vs.concept_depths else None,
                )
                passed_ids.append(row["id"])

            for ds in dropped:
                ids = ds.identifiers
                meta = ds.raw.metadata
                await conn.execute(
                    """
                        INSERT INTO sources
                            (expert_id, source_type, url, title, author,
                             quality_score, relevance_score, passed, drop_reason,
                             validator_model, rubric_version, discovered_via,
                             doi, arxiv_id, identifiers,
                             full_text_method, text_chars,
                             review_model, first_pass_quality, first_pass_relevance,
                             triage_score, substance)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,false,$8,$9,$10,$11,
                                $12,$13,$14::jsonb,$15,$16,$17,$18,$19,$20,$21)
                        """,
                    expert_id,
                    ds.raw.source_type.value,
                    ds.raw.url,
                    ds.raw.title,
                    ds.raw.author,
                    ds.quality_score,
                    ds.relevance_score,
                    ds.drop_reason,
                    ds.validator_model or settings.FAST_MODEL,
                    RUBRIC_VERSION,
                    meta.get("discovered_via", "plan"),
                    ids.doi,
                    ids.arxiv_id,
                    json.dumps(ids.to_dict()) if not ids.is_empty() else None,
                    meta.get("full_text_method"),
                    len(ds.raw.text),
                    ds.review_model,
                    ds.first_pass_quality,
                    ds.first_pass_relevance,
                    _as_score(meta.get("triage_score")),
                    substance_of(ds.raw),
                )

        return passed_ids


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


# Character ceilings for resolved works, per tier and scope. Ingest costs about
# $0.27 per 100,000 characters, so a 200,000-character canonical work is about
# $0.54 and a 60,000-character concept text about $0.16. The fetchers cut the
# named sections first (sources/sections.py), so the ceiling is spent on the
# parts the plan asked for rather than on a work's opening.
# A figure's work gets a concept text's ceiling: it is there for the voice, and
# six long books must not take the round's money.
_PRIMARY_TEXT_CHARS: dict[ExpertTier, dict[str, int]] = {
    ExpertTier.LITE: {SCOPE_OVERALL: 200_000, SCOPE_CONCEPT: 40_000, SCOPE_FIGURE: 40_000},
    ExpertTier.STANDARD: {SCOPE_OVERALL: 200_000, SCOPE_CONCEPT: 60_000, SCOPE_FIGURE: 60_000},
    ExpertTier.PRO: {SCOPE_OVERALL: 400_000, SCOPE_CONCEPT: 100_000, SCOPE_FIGURE: 100_000},
}
# Priority candidates skip the score floor and the queue. Past this share of a
# round's money they stop doing so and compete on their scores, so a plan that
# names many long texts cannot starve the rest of the corpus.
_PRIORITY_BUDGET_SHARE = Decimal("0.5")


def _priority_reservation(candidate: SourceCandidate, batched: bool) -> Decimal:
    """What a priority candidate is expected to cost, before it is fetched.

    A resolved work carries its text ceiling, which is the honest upper bound;
    anything else falls back to its source type's typical length.
    """
    ceiling = candidate.metadata.get("text_max_chars")
    if isinstance(ceiling, int) and ceiling > 0:
        return estimated_ingest_cost_usd(ceiling, 0, batch=batched)
    return _prefetch_cost_estimate(candidate, batched)


def _outcome_metadata(passed: list[ValidatedSource]) -> list[tuple[str, dict]]:
    """Accepted sources as the must-have outcome reads them: metadata plus tier."""
    return [(vs.url, {**vs.raw.metadata, "source_tier": vs.source_tier}) for vs in passed]


def _merge_same_volume(
    candidates: list[SourceCandidate], ceiling: int | None = None
) -> list[SourceCandidate]:
    """One candidate per URL, carrying every concept's sections for it.

    Two concepts can point at one volume — the Five Ways and the soul are both in
    the first part of a long work — and URL de-duplication would keep only the
    first lookup's sections. Merged here, the fetch cuts both.
    """
    by_url: dict[str, SourceCandidate] = {}
    kept: list[SourceCandidate] = []
    for candidate in candidates:
        key = candidate.url.rstrip("/").lower()
        first = by_url.get(key)
        if first is None:
            by_url[key] = candidate
            kept.append(candidate)
            continue
        meta, other = first.metadata, candidate.metadata
        sections = [p for p in (meta.get("must_have_sections"), other.get("must_have_sections")) if p]
        if sections:
            meta["must_have_sections"] = "; ".join(dict.fromkeys(sections))
        concepts = list(dict.fromkeys([*meta.get("must_have_concepts", []), *other.get("must_have_concepts", [])]))
        if concepts:
            meta["must_have_concepts"] = concepts
        if other.get("fetch_priority"):
            meta["fetch_priority"] = True
            meta["priority_rank"] = min(meta.get("priority_rank", 2), other.get("priority_rank", 2))
        ceilings = [c for c in (meta.get("text_max_chars"), other.get("text_max_chars")) if c]
        if ceilings:
            # Two concepts' passages from one volume share one fetch, so the
            # ceiling grows with them — but never past one canonical work's
            # ceiling. Uncapped, three concept lookups on one Summa volume
            # summed to 600,000 characters on a live build, and the reservation
            # for that one volume starved the natural-law volume out of the
            # round.
            grown = sum(ceilings)
            meta["text_max_chars"] = min(grown, ceiling) if ceiling else max(ceilings)
    return kept


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
    quotas = {
        _FETCHER_SOURCE_TYPES[name]: quota for name, (_, quota) in fetchers.items()
    }
    total = sum(quotas.values()) or 1
    return {
        source_type: max(
            _TYPE_CAP_MIN,
            math.ceil(budget * (quota / total) * _TYPE_CAP_HEADROOM),
        )
        for source_type, quota in quotas.items()
    }


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
    method = expected_method(
        candidate.identifiers, FullTextHints.from_candidate(candidate)
    )
    pages = estimated_ocr_pages(chars) if method in PAID_METHODS else 0
    return estimated_ingest_cost_usd(chars, pages, batch=batched)


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
        logger.warning(
            "Unknown BUILD_EXECUTION_DEFAULT=%r — falling back to 'auto'", configured
        )
    return BuildExecution.BACKGROUND if expert.persona_name else BuildExecution.INTERACTIVE


def plan_user_message(topic: str, orientation: OrientationPack | None) -> str:
    """The planner's input: the topic, then whatever the orientation pack read."""
    if orientation is None or orientation.empty:
        return f"Topic: {topic}"
    return f"Topic: {topic}\n\n{orientation.render()}"


async def _plan_research(topic: str, max_concepts: int = 8) -> dict:
    """One call on the strong model — the brief shapes the whole corpus.

    The planner reads a reference overview or two first (sources/orientation.py)
    and is shown how they structure the topic. That lookup never fails the plan:
    without it, the plan is written from the topic alone, as it always was.

    Always returns a normalised plan: every fetcher has non-empty queries and a
    clamped weight, even when the model call fails (fallback = raw topic, weight 1).
    """
    orientation = await build_orientation_pack(topic)
    if orientation.empty:
        logger.info("Orientation for %r: nothing read — planning from the topic alone", topic)
    else:
        logger.info(
            "Orientation for %r: read %s",
            topic,
            "; ".join(f"{o.source} {o.title!r} ({len(o.headings)} headings)" for o in orientation.overviews),
        )

    raw_plan: dict = {}
    try:
        client = get_anthropic_client()
        resp = await client.messages.create(  # type: ignore[call-overload]
            model=settings.PLAN_MODEL,
            max_tokens=4000,
            system=_plan_system(max_concepts),
            tools=[_plan_tool(max_concepts)],
            tool_choice={"type": "tool", "name": "create_research_plan"},
            messages=[{"role": "user", "content": plan_user_message(topic, orientation)}],
        )
        block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
        raw_plan = dict(block.input)
    except Exception as exc:
        logger.warning(
            "Research planning failed (%s: %s) — falling back to raw topic. The build "
            "continues DEGRADED: no key concepts, one query per fetcher instead of "
            "several, and no coverage gap-fill.",
            type(exc).__name__, exc, exc_info=True,
        )

    plan = _normalise_plan(raw_plan, topic, max_concepts)
    plan["orientation"] = orientation.record(plan.pop("orientation_note", ""))
    logger.info(
        "Research plan for %r: facets=[%s] weights={%s} must_have=[%s] figures=[%s]",
        topic,
        "; ".join(f"{f['name']}: {', '.join(f['concepts'])}" for f in plan["facets"]),
        ", ".join(f"{n}:{p['weight']:g}" for n, p in plan["fetcher_plans"].items()),
        "; ".join(w["title"] for w in plan["must_have_works"]),
        ", ".join(f["name"] for f in plan["figures"]),
    )
    if not plan["key_concepts"]:
        # Reachable without an exception too — a model can return a well-formed
        # plan with an empty concept list. Either way every downstream stage that
        # takes key_concepts (triage, validation, gap-fill) is now working blind,
        # and until this line said so the only evidence was an empty list buried
        # in the plan_ready event.
        logger.warning(
            "Research plan for %r has NO key concepts — triage, validation and "
            "gap-fill will all run without a syllabus to score against",
            topic,
        )
    return plan


def _normalise_plan(raw_plan: dict, topic: str, max_concepts: int = 8) -> dict:
    """Coerce a model-produced plan into a safe, complete shape.

    ``facets`` is the syllabus's two levels; ``key_concepts`` is the same
    concepts flattened in facet order, which is what every downstream reader
    (triage, validation, coverage, feedback, both clients) keeps reading.
    """
    fetcher_plans: dict[str, dict] = {}
    raw_fetcher_plans = raw_plan.get("fetcher_plans") or {}
    for name in _FETCHER_NAMES:
        raw = raw_fetcher_plans.get(name) or {}
        queries: list[str] = []
        for q in raw.get("queries") or []:
            if (
                isinstance(q, str)
                and q.strip()
                and q.strip().casefold() not in {d.casefold() for d in queries}
            ):
                queries.append(q.strip())
        try:
            weight = float(raw.get("weight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        fetcher_plans[name] = {
            "queries": queries[:_MAX_QUERIES_PER_FETCHER] or [topic],
            "weight": min(max(weight, 0.0), 2.0),
        }

    facets = _normalise_facets(raw_plan, topic, max_concepts)
    key_concepts = [c for facet in facets for c in facet["concepts"]]

    must_have_works = [
        work
        for raw in raw_plan.get("must_have_works") or []
        if isinstance(raw, dict) and (work := _normalise_work(raw)) is not None
    ]

    canonical_concepts = {c.casefold(): c for c in key_concepts}
    concept_texts = []
    for raw in raw_plan.get("concept_primary_texts") or []:
        if not isinstance(raw, dict):
            continue
        work = _normalise_work(raw)
        concept = canonical_concepts.get(str(raw.get("concept") or "").strip().casefold())
        if work is None or concept is None:
            continue
        concept_texts.append({"concept": concept, **work})

    definition = raw_plan.get("primary_source_definition")
    note = raw_plan.get("orientation_note")
    return {
        "fetcher_plans": fetcher_plans,
        "facets": facets,
        "key_concepts": key_concepts,
        "primary_source_definition": definition.strip() if isinstance(definition, str) else "",
        "must_have_works": must_have_works[:4],
        # At most two per concept: a third text for one concept is budget another
        # concept's primary text does not get.
        "concept_primary_texts": _at_most_per_concept(concept_texts, 2)[:16],
        "figures": _normalise_figures(raw_plan.get("figures")),
        "orientation_note": note.strip() if isinstance(note, str) else "",
    }


def _clean_concepts(raw: Any) -> list[str]:
    return [c.strip() for c in raw or [] if isinstance(c, str) and c.strip()] if isinstance(raw, list) else []


def _normalise_facets(raw_plan: dict, topic: str, max_concepts: int) -> list[dict]:
    """Facets with their concepts, de-duplicated across facets and capped.

    A model that ignores ``facets`` and returns only ``key_concepts`` gets one
    facet named after the topic, and a concept listed in ``key_concepts`` but in
    no facet joins a facet of its own rather than vanishing. The cap trims from
    the largest facet first, so trimming never empties a facet.
    """
    seen: set[str] = set()
    facets: list[dict] = []

    def _take(concepts: list[str]) -> list[str]:
        kept = []
        for concept in concepts:
            if concept.casefold() not in seen:
                seen.add(concept.casefold())
                kept.append(concept)
        return kept

    for raw in raw_plan.get("facets") or [] if isinstance(raw_plan.get("facets"), list) else []:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        concepts = _take(_clean_concepts(raw.get("concepts"))[:_MAX_CONCEPTS_PER_FACET])
        if concepts:
            facets.append({
                "name": name.strip() if isinstance(name, str) and name.strip() else f"Facet {len(facets) + 1}",
                "concepts": concepts,
            })
        if len(facets) >= _MAX_FACETS:
            break

    orphans = _take(_clean_concepts(raw_plan.get("key_concepts")))
    if orphans:
        facets.append({"name": topic if not facets else "Other", "concepts": orphans})

    limit = max(1, max_concepts)
    while sum(len(f["concepts"]) for f in facets) > limit:
        largest = max(range(len(facets)), key=lambda i: (len(facets[i]["concepts"]), i))
        if len(facets[largest]["concepts"]) > 1:
            facets[largest]["concepts"].pop()
        else:
            facets.pop()
    return facets


def _normalise_figures(raw: Any) -> list[dict]:
    """Up to six named figures, each with one obtainable work or none."""
    figures: list[dict] = []
    seen: set[str] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip() or name.strip().casefold() in seen:
            continue
        seen.add(name.strip().casefold())
        why = entry.get("why")
        work = _normalise_work(entry["work"]) if isinstance(entry.get("work"), dict) else None
        obtainable = entry.get("obtainable") is True and work is not None
        if work is not None:
            work.pop("substitute", None)
            work["author"] = work["author"] or name.strip()
        figures.append({
            "name": name.strip(),
            "why": why.strip() if isinstance(why, str) else "",
            "work": work if obtainable else None,
            "obtainable": obtainable,
        })
        if len(figures) >= _MAX_FIGURES:
            break
    return figures


def _normalise_work(work: dict, allow_substitute: bool = True) -> dict | None:
    title = work.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    author = work.get("author")
    kind = work.get("kind")
    sections = work.get("sections")
    normalised: dict[str, Any] = {
        "title": title.strip(),
        "author": author.strip() if isinstance(author, str) else "",
        "kind": kind if kind in WORK_KINDS else "book",
        "public_domain": work.get("public_domain") is True,
        "sections": sections.strip() if isinstance(sections, str) else "",
        "open_text": work.get("open_text") is True,
    }
    substitute = work.get("substitute")
    if allow_substitute and isinstance(substitute, dict):
        normalised_substitute = _normalise_work(substitute, allow_substitute=False)
        if (
            normalised_substitute is not None
            and title_key(normalised_substitute["title"]) != title_key(normalised["title"])
        ):
            normalised["substitute"] = normalised_substitute
    return normalised


def _at_most_per_concept(texts: list[dict], limit: int) -> list[dict]:
    counts: dict[str, int] = {}
    kept = []
    for text in texts:
        counts[text["concept"]] = counts.get(text["concept"], 0) + 1
        if counts[text["concept"]] <= limit:
            kept.append(text)
    return kept


def _route_must_have_works(plan: dict) -> None:
    """Add exact-title queries for named works to the fetchers that answer them.

    Works are looked for by the canonical resolver (sources/canonical.py), which
    searches the Gutenberg catalogue, the Internet Archive and Exa by title and
    records whether it found the whole work. What is left for the planned search:

    - **papers** also go to OpenAlex, the scholarly channel, as a title query;
    - **without an Exa key** the resolver's Exa routes cannot run, so every work
      goes to the web fetcher as a quoted title, as before.

    Each extra query gets at least one result slot in the fan-out, so a must-have
    work costs little budget but is actively looked for.
    """
    works = plan["must_have_works"]
    if not works:
        return

    def _add(target: str, selected: list[dict]) -> None:
        queries = [f'"{w["title"]}" {w.get("author", "")}'.strip() for w in selected]
        if not queries:
            return
        fetcher_plan = plan["fetcher_plans"][target]
        existing = {q.casefold() for q in fetcher_plan["queries"]}
        fetcher_plan["queries"] += [q for q in queries if q.casefold() not in existing]
        fetcher_plan["weight"] = max(fetcher_plan["weight"], 1.0)

    if not settings.EXA_API_KEY:
        _add("web", works)
    _add("openalex", [w for w in works if w.get("kind") == "paper"])


async def _reconcile_claims(
    topic: str,
    expert_id: int,
    graph_repo: GraphRepository,
    on_event: EventCallback | None = None,
) -> int:
    """Relate the claims different sources make about the same concept.

    Best-effort inside a stage that is itself best-effort: a graph with claims,
    concepts and an index between them is already useful, so a failure here
    leaves that standing rather than degrading the whole stage and sending the
    build back through the worker's retry loop.

    ``claims_reconciled`` is emitted on every run, including the ones that
    insert nothing. It used to fire only when a relation was inserted, and
    production reconciliation has never inserted one: the church-fathers build
    spent 23 seconds in this stage — too short for ~120 model calls to have
    run, and four seconds before the API refused its persona call — and the
    log could not say whether the calls failed, returned nothing, or returned
    relations that were all rejected. The event now says which.
    """
    stats = ReconcileStats()
    groups: list = []
    inserted = 0
    error: str | None = None
    try:
        groups = await graph_repo.claims_by_concept(expert_id)
        if groups:
            relations = await reconcile_claims(topic, groups, stats=stats)
            inserted = await graph_repo.insert_relations(expert_id, relations)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("Claim reconciliation failed for expert %d: %s", expert_id, exc)

    parsed = stats.relations_returned - sum(stats.rejected.values())
    event: dict[str, Any] = {
        "type": "claims_reconciled",
        "concepts": len(groups),
        "relations": inserted,
        **stats.as_event(),
        # Parsed but refused at insert (endpoint types, missing property).
        "relations_refused_at_insert": max(0, parsed - inserted),
    }
    if error:
        event["error"] = error
    await _emit_event(on_event, event)

    if stats.concepts_examined and stats.calls_failed == stats.concepts_examined:
        provider = terminal_provider_error()
        logger.error(
            "Reconciliation for expert %d: every one of %d call(s) failed%s",
            expert_id, stats.calls_failed,
            f" — {provider_error_message(provider)}" if provider else "",
        )
    logger.info(
        "Reconciliation for expert %d: %d concept group(s), %d eligible, %d examined, "
        "%d call(s) failed, %d relation(s) returned, %d rejected %s, %d inserted",
        expert_id, len(groups), stats.concepts_eligible, stats.concepts_examined,
        stats.calls_failed, stats.relations_returned, sum(stats.rejected.values()),
        dict(stats.rejected), inserted,
    )
    return inserted


async def _resolve_entities(
    expert_id: int,
    graph_repo: GraphRepository,
    on_event: EventCallback | None = None,
) -> int:
    """Merge duplicate graph nodes: by canonical label, then by embedding.

    See :mod:`peritus.graph.resolution` for the rules and why cosine alone was
    not enough.
    """
    try:
        import numpy as np
    except ImportError:
        logger.debug("numpy not available — skipping entity resolution")
        return 0

    nodes = await graph_repo.get_all_nodes(expert_id)
    if len(nodes) < 2:
        return 0

    merge_count = 0

    async def _merge(keep: dict, drop: dict, how: str) -> None:
        nonlocal merge_count
        await graph_repo.merge_nodes(expert_id, keep["id"], drop["id"])
        merge_count += 1
        logger.debug("Merged node %r → %r (%s)", drop["label"], keep["label"], how)
        if on_event and merge_count % 25 == 0:
            await _emit_event(on_event, {"type": "resolve_progress", "merged": merge_count})

    # 1. Same concept by label: "Varroa mites" / "Varroa mite",
    #    "Deformed Wing Virus (DWV)" / "DWV (Deformed Wing Virus)".
    label_merged: set[int] = set()
    for keep, drops in canonical_merge_plan(nodes):
        for drop in drops:
            await _merge(keep, drop, "canonical label")
            label_merged.add(drop["id"])
    by_label = merge_count
    nodes = [n for n in nodes if n["id"] not in label_merged]
    if len(nodes) < 2:
        return merge_count

    # 2. Same thing by meaning. Node embeddings are persisted at insert time;
    # only nodes that missed embedding (e.g. an API blip during insert) get
    # re-embedded here. Batched so a graph whose embeddings all failed at insert
    # can't overflow one call.
    missing = [i for i, n in enumerate(nodes) if n.get("embedding") is None]
    if missing:
        texts = [
            node_embedding_text(nodes[i]["label"], nodes[i].get("description")) for i in missing
        ]
        try:
            fresh = await embed_in_batches(texts)
        except Exception as exc:
            logger.warning("Entity resolution embedding failed: %s", exc)
            return merge_count
        for i, emb in zip(missing, fresh, strict=True):
            nodes[i]["embedding"] = emb

    matrix = np.array([np.asarray(n["embedding"], dtype=np.float32) for n in nodes])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    normalized = matrix / norms
    sim = normalized @ normalized.T  # (N, N)

    # Candidate pairs at C speed (upper triangle, i < j) at the lowest threshold
    # any pair could use; the per-pair rule then decides. The old pure-Python
    # O(N²) double loop had no ``await`` on the common no-merge path, so on a
    # large graph it blocked the event loop — starving the job heartbeat — for
    # the whole pass. np.where keeps row-major order (increasing i, then j).
    floor = min(RESOLVE_THRESHOLD, RESOLVE_THRESHOLD_SAME_HEAD)
    rows, cols = np.where(np.triu(sim >= floor, k=1))

    merged_away: set[int] = set()
    for i, j in zip(rows.tolist(), cols.tolist(), strict=True):
        keep, drop = nodes[i], nodes[j]
        if keep["id"] in merged_away or drop["id"] in merged_away:
            continue
        threshold = pair_threshold(keep, drop)
        if threshold is None or sim[i, j] < threshold:
            continue
        await _merge(keep, drop, f"sim={float(sim[i, j]):.3f}")
        merged_away.add(drop["id"])

    if merge_count:
        logger.info(
            "Entity resolution: merged %d duplicate nodes for expert %d "
            "(%d by label, %d by embedding)",
            merge_count, expert_id, by_label, merge_count - by_label,
        )
    return merge_count


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
            name, query, elapsed, type(exc).__name__, exc,
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
        name, query, len(results), elapsed,
        " — slow, this holds up the whole discovery stage"
        if elapsed > _SLOW_SEARCH_SECONDS else "",
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


def _carry_candidate_metadata(
    candidate: SourceCandidate, source: RawSource, score: float
) -> None:
    """Copy the selection facts a fetcher may not have onto the fetched source."""
    carried = {**candidate.metadata, "triage_score": round(score, 2)}
    for key in _CARRIED_METADATA:
        if key in carried and key not in source.metadata:
            source.metadata[key] = carried[key]
    source.metadata["triage_score"] = round(score, 2)


def _url_key(url: str) -> str:
    return (url or "").rstrip("/").lower()


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
            for w in (plan.get("concept_primary_texts") or [])[
                : getattr(config, "concept_primary_texts", 0)
            ]
        ]
        + _figure_works(plan.get("figures") or [], getattr(config, "figure_texts", 0))
    )


def _figure_works(figures: list[dict], limit: int) -> list[MustHaveWork]:
    """One lookup per named figure with an obtainable work, up to the tier's limit."""
    works: list[MustHaveWork] = []
    for figure in figures:
        if len(works) >= limit:
            break
        if not figure.get("obtainable") or not isinstance(figure.get("work"), dict):
            continue
        work = MustHaveWork.from_plan(figure["work"], SCOPE_FIGURE)
        if not work.title:
            continue
        work.figure = str(figure.get("name") or "")
        work.author = work.author or work.figure
        works.append(work)
    return works


def _enforce_ceiling(candidate: SourceCandidate, source: RawSource) -> None:
    """Cut a fetched text to the ceiling its candidate was stamped with.

    The fetchers that cut named sections apply the ceiling themselves, and a
    live Thomism build still stored the Summa's first part at 584,000
    characters against a 200,000 ceiling — a third of the round's estimated
    ingest in one volume. Whichever path skipped it, the ceiling is enforced
    here, where every fetch arrives, and the log names the fetcher so the next
    build says which path it was.
    """
    ceiling = candidate.metadata.get("text_max_chars")
    if not isinstance(ceiling, int) or ceiling <= 0 or len(source.text) <= ceiling:
        return
    logger.warning(
        "ceiling_enforced: %s returned %d chars for %r against a %d ceiling — cut",
        candidate.metadata.get("canonical_fetcher") or candidate.source_type.value,
        len(source.text), candidate.title, ceiling,
    )
    source.text = source.text[:ceiling]
    source.metadata["truncated"] = True
    source.metadata["ceiling_enforced"] = True


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
            settings.SOURCE_FETCH_TIMEOUT, candidate.source_type.value, candidate.url,
        )
        return None
    except Exception as exc:
        logger.warning(
            "Full fetch failed for %s %r (%s: %s)",
            candidate.source_type.value, candidate.url, type(exc).__name__, exc,
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


_PERSONA_TOOL: dict[str, Any] = {
    "name": "generate_persona",
    "description": "Generate a named expert persona grounded in the corpus.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                # The UI titles any persona that comes back bare (see
                # web/lib/persona.ts), so an untitled name is not a broken
                # build — asking here just means the stored name and the
                # displayed one agree.
                "description": (
                    "Expert's full name, prefixed with the honorific 'Dr.' — "
                    "e.g. 'Dr. Elena Vasquez'."
                ),
            },
            "bio": {
                "type": "string",
                "description": (
                    "2-3 SHORT sentences, scannable in five seconds: what they "
                    "specialize in and their angle on it. Plain and concrete — "
                    "no compound sentences stacking multiple clauses, no "
                    "throat-clearing ('with a career spanning...', 'has spent "
                    "years...'), no restating the topic name back. Write it "
                    "the way a conference program blurbs a speaker, not the "
                    "way an academic CV opens."
                ),
            },
            "style": {
                "type": "string",
                "description": (
                    "A system-prompt block, in the second person, describing how "
                    "this expert TEACHES: how they open an explanation, the "
                    "framings and analogies they characteristically reach for, "
                    "the kind of worked example they use, what they insist "
                    "matters most and what they consider a distraction, and how "
                    "they talk to someone new to the subject. Positive voice "
                    "instructions only — write what they do, never a list of "
                    "rules about sourcing, citation, hedging, or uncertainty."
                ),
            },
        },
        "required": ["name", "bio", "style"],
    },
}

# The persona is the expert's teaching voice, and nothing else. It used to be
# asked for "how the expert cites, qualifies claims, and handles uncertainty",
# which reliably produced personas whose defining trait was hedging — a voice
# that then argued with the answer-shape rules on every turn. Sourcing
# discipline belongs to the grounding contract (chat/grounding.py), which is
# absolute and needs no help from the persona; what the persona is for is the
# thing a contract cannot supply, which is how a good teacher explains.
_PERSONA_SYSTEM = (
    "You are creating a named expert persona that will be the voice of a "
    "grounded AI tutor. The persona must reflect what this corpus actually "
    "contains — a specialist in these particular materials, not a generic "
    "authority. Name them as a doctor of the subject ('Dr. <given> <family>'), "
    "since every expert here is addressed by name and title.\n\n"
    "Write the style block as a teacher's profile: how they explain a hard idea "
    "to a newcomer, the analogies and framings they return to, the worked "
    "examples they favour, what they emphasise and what they cut. Make it "
    "concrete and specific to this corpus — a reader should be able to tell "
    "this expert from any other expert in the same field.\n\n"
    "Do not write anything about citation, sourcing, evidence quality, "
    "qualifying claims, or handling uncertainty. Separate absolute rules govern "
    "all of that, and duplicating them here produces a hedging, evasive voice "
    "instead of a teaching one.\n\n"
    "The bio and the style block have different jobs and should not read alike. "
    "The bio is what a reader skims in five seconds to decide if this is the "
    "right expert — keep it short and plain. The style block is what actually "
    "governs how the expert teaches, so it can be as thorough as that job "
    "requires; length there is not the problem the bio has."
)


def _persona_digest(sources: list[tuple[str, str, float | None, list[str]]]) -> str:
    """One line per source: title, kind, quality, and its leading claims.

    Takes plain tuples rather than ``ValidatedSource`` so a persona can be
    regenerated from the ``sources`` table long after the build that produced it.
    """
    lines = []
    for title, content_type, quality, claims in sources[:15]:
        q = f"Q:{quality:.1f}" if quality is not None else "Q:—"
        lines.append(f"- {title} ({content_type}, {q}): " + "; ".join(claims[:2]))
    return "\n".join(lines)


async def generate_persona(
    topic: str,
    sources: list[tuple[str, str, float | None, list[str]]],
    top_nodes: list[dict],
) -> dict:
    """Generate ``{name, bio, style}`` from a corpus digest.

    Public because personas outlive the build that made them: an expert built
    under an older persona prompt can be re-voiced without re-fetching,
    re-validating and re-embedding its whole corpus. See
    ``ExpertService.regenerate_persona``.
    """
    concept_list = ", ".join(n["label"] for n in top_nodes[:20])

    client = get_anthropic_client()
    resp = await client.messages.create(  # type: ignore[call-overload]
        model=settings.CLAUDE_MODEL,
        # 1024 was enough when `style` was a sentence about how the expert cites.
        # A teaching profile is several paragraphs, and `style` is the last field
        # in the schema — too small a budget truncates the tool call and returns
        # {name, bio} with no style at all, which is a KeyError at the call site
        # rather than a degraded persona.
        max_tokens=3072,
        system=_PERSONA_SYSTEM,
        tools=[_PERSONA_TOOL],
        tool_choice={"type": "tool", "name": "generate_persona"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Topic: {topic}\n\n"
                    f"Sources ingested:\n{_persona_digest(sources)}\n\n"
                    f"Top concepts extracted: {concept_list}"
                ),
            }
        ],
    )
    block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
    persona = dict(block.input)

    # A tool call cut off by the token budget still parses — it just arrives
    # missing its trailing fields. Catching it here names the cause; letting it
    # through surfaces as a KeyError three frames away, at whichever caller
    # happened to read `persona["style"]` first.
    missing = [k for k in ("name", "bio", "style") if not persona.get(k)]
    if missing:
        raise RuntimeError(
            f"Persona generation returned no {', '.join(missing)} "
            f"(stop_reason={resp.stop_reason!r}). Raise max_tokens if this is "
            "'max_tokens'."
        )
    return persona


async def _generate_persona(
    topic: str,
    sources: list[tuple[str, str, float | None, list[str]]],
    top_nodes: list[dict],
) -> dict:
    """The build's persona call — a seam tests patch."""
    return await generate_persona(topic, sources, top_nodes)


# A corpus that is overwhelmingly tertiary answers everything second-hand: it
# can tell you what people say about a subject and never what the subject is.
# Below this share of classified sources, the expert is worth building but the
# user should know what they are getting *before* they chat with it — the failure
# it produces is subtle, and reads as the model being evasive rather than as the
# corpus being thin.
_TERTIARY_WARN_SHARE = 0.7
# Under this many classified sources the share is noise, not a finding.
_TERTIARY_WARN_MIN_CLASSIFIED = 3


def corpus_tier_warning(passed: list[ValidatedSource]) -> dict | None:
    """A build warning if the passing corpus is overwhelmingly second-hand.

    Pure, so the threshold is testable without a build. Sources the validator
    could not classify are counted separately and never held against the corpus:
    an unclassified source is unknown, not tertiary.
    """
    counts = {tier: 0 for tier in ("primary", "secondary", "tertiary")}
    unclassified = 0
    for vs in passed:
        if vs.source_tier in counts:
            counts[vs.source_tier] += 1
        else:
            unclassified += 1

    classified = sum(counts.values())
    if classified < _TERTIARY_WARN_MIN_CLASSIFIED:
        return None
    if counts["tertiary"] / classified < _TERTIARY_WARN_SHARE:
        return None

    return {
        "type": "corpus_warning",
        "reason": "mostly_tertiary",
        "primary": counts["primary"],
        "secondary": counts["secondary"],
        "tertiary": counts["tertiary"],
        "unclassified": unclassified,
        "classified": classified,
        "message": (
            f"{counts['tertiary']} of {classified} classified sources are "
            "summaries, reviews or overviews rather than primary texts or "
            "substantive analysis. This expert will answer second-hand. "
            "Rebuilding with more specific sources — the works themselves, "
            "original papers, or practitioners' own writing — would help."
        ),
    }


def _avg_quality(passed: list[ValidatedSource]) -> float | None:
    if not passed:
        return None
    scores = [vs.quality_score for vs in passed if vs.quality_score is not None]
    return round(sum(scores) / len(scores), 2) if scores else None


def _deduplicate_by_url[T: (RawSource, SourceCandidate)](items: list[T]) -> list[T]:
    """Remove items with duplicate URLs, keeping the first occurrence."""
    seen: set[str] = set()
    unique: list[T] = []
    for item in items:
        key = item.url.rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


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


async def _emit_event(cb: EventCallback | None, event: dict) -> None:
    _log_event(event)
    if cb:
        await cb(event)


# Wall-clock of the stage currently running, so each stage boundary can report
# how long the previous one took. A module-level single slot is enough: a build
# runs its stages in sequence, and concurrent builds each get their own copy
# through the same contextvar machinery the execution policy uses.
_stage_started: ContextVar[tuple[str, float] | None] = ContextVar(
    "peritus_stage_started", default=None
)

# Events worth a log line of their own. The rest (per-source validation, per-batch
# graph progress) are high-volume and already visible in the durable event log —
# logging those too would bury the ones that matter.
_LOGGED_EVENTS = frozenset({
    "stage", "plan_ready", "picture_ready", "picture_skipped",
    "discovery_started", "round_started", "canonical_resolved", "fetcher_retried",
    "floor_relaxed", "composition_capped",
    "feedback_queries", "dedup_done", "triage_done", "fetch_done",
    "validate_done", "coverage_report", "discovery_done", "snowball_done",
    "corpus_warning", "chat_ready", "graph_ready", "entities_resolved",
    "claims_reconciled", "build_resumed",
    "persona_ready", "stage_degraded", "error", "cancelled", "done",
})


def _clip(value: Any, limit: int = 160) -> str:
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}…(+{len(text) - limit} chars)"


def _log_event(event: dict) -> None:
    """Mirror significant build events into the process log.

    The durable event log is per-job and only readable through the API, which is
    exactly the wrong place to look when the question is "what was this worker
    doing when it died". These lines put the build's shape into the same stream
    as the errors, so a worker log alone tells the story.
    """
    kind = event.get("type")
    if kind not in _LOGGED_EVENTS:
        return

    if kind == "stage":
        now = time.monotonic()
        previous = _stage_started.get()
        if previous:
            logger.info("Stage %r finished in %.1fs", previous[0], now - previous[1])
        name = str(event.get("name", "?"))
        _stage_started.set((name, now))
        logger.info("── Stage %d: %s ──", event.get("stage", -1), name)
        return

    # Values are model output (concept lists, warning prose) and can run to
    # hundreds of characters. Truncated per field so one verbose event cannot
    # push a whole build's worth of real log lines off the screen.
    detail = ", ".join(
        f"{k}={_clip(v)}" for k, v in event.items() if k != "type"
    )
    if kind in ("error", "cancelled"):
        logger.error("Build event %s: %s", kind, detail)
    elif kind in ("stage_degraded", "corpus_warning"):
        logger.warning("Build event %s: %s", kind, detail)
    else:
        logger.info("Build event %s: %s", kind, detail)
