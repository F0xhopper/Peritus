"""The numbers and the vocabulary a build is tuned by.

Two kinds of thing live here, and the comments distinguish them because the
distinction matters when someone changes one.

**Calibrated constants** — the budget shares, the acceptance-collapse threshold,
the expected character counts, the type-cap headroom. Every one of these was set
against real builds, and several are recorded as *measured*, not chosen. Reading
one and thinking "that looks arbitrary, 0.5 would be tidier" is how a build that
works becomes a build that costs twice as much and finds less.

**Vocabulary** — `OUTCOME_*` (why a candidate did or did not become a source)
and `STOP_*` (why the discovery loop ended). These are written into
`build_events` and read back by the audit surface, so they are a wire format:
renaming one silently reinterprets every build already recorded.
"""

from decimal import Decimal

from peritus.experts.domain import ExpertTier
from peritus.sources.canonical import SCOPE_CONCEPT, SCOPE_FIGURE, SCOPE_OVERALL
from peritus.sources.domain import SourceType

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


# Characters of long works held past their close-read ceiling, embed-only
# (ingestion/structural.py), per build. Bounded by storage rather than money: a
# held chunk costs ~$0.00003 to embed and ~29 KB of Postgres with its vector and
# indexes, and the database is on a 500 MB plan — 1,000,000 characters is about
# 1,100 chunks, ~32 MB. Spent on the tail sections nearest the key concepts.
_STRUCTURAL_TAIL_CHARS: dict[ExpertTier, int] = {
    ExpertTier.LITE: 250_000,
    ExpertTier.STANDARD: 1_000_000,
    ExpertTier.PRO: 3_000_000,
}


# Priority candidates skip the score floor and the queue. Past this share of a
# round's money they stop doing so and compete on their scores, so a plan that
# names many long texts cannot starve the rest of the corpus.
_PRIORITY_BUDGET_SHARE = Decimal("0.5")
