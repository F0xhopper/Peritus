"""What kind of subject an expert is on, and what "current" means for it.

The corpus a build can fetch whole and free is public-domain books (before the
copyright cutoff) and open-access research papers, and both rank as primary.
For a *canon* — Aquinas, Aristotle, Bede, where the texts are the subject — that
is exactly the right corpus. For a *practice* (a craft, a how-to field) or a
*research front* (a fast-moving technical field) it is the wrong one. Expert 41,
Beekeeping, was two virology papers (61% of its chunks), Langstroth's manual of
1853 and three nineteenth-century editions of *The ABC and XYZ of Bee Culture*,
and it lost every how-to question to a closed-book model trained on the modern
web (docs/plans/beating-closed-book.md, §3.12).

So the research brief names the subject's kind once, on the plan model, and the
kind decides three things downstream: a coverage target for current material
(experts/coverage.py), a recency weight in triage (sources/triage.py), and a cap
on the share of the corpus one narrow paper may take (experts/composition.py).
A canon — and a plan that predates the field, or a field the model got wrong —
changes nothing: :data:`SUBJECT_CANON` is today's behaviour.

"Current" is read off what discovery and the validator already record. No model
call is spent on it, and no year is guessed where none was recorded.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from peritus.sources.domain import SourceType, ValidatedSource

# The texts are the subject. Old is not worse; the oldest text is often the one.
SUBJECT_CANON = "canon"
# A craft, a how-to field: what is authoritative is what practitioners do now.
SUBJECT_PRACTICE = "practice"
# A fast-moving technical or scientific field: the recent literature is the field.
SUBJECT_RESEARCH_FRONT = "research_front"
SUBJECT_KINDS: tuple[str, ...] = (SUBJECT_CANON, SUBJECT_PRACTICE, SUBJECT_RESEARCH_FRONT)


def normalise_subject_kind(value: Any) -> str:
    """The subject kind, or :data:`SUBJECT_CANON` for anything missing or unknown.

    Canon is the safe default because it is what every build did before the
    field existed: an old stored plan, a planner call that failed, or a value
    outside the enum all build exactly as they used to.
    """
    if isinstance(value, str) and value.strip().casefold() in SUBJECT_KINDS:
        return value.strip().casefold()
    return SUBJECT_CANON


def subject_kind_of(plan: dict | None) -> str:
    """The kind a stored or fresh research plan names, canon when it names none."""
    return normalise_subject_kind((plan or {}).get("subject_kind"))


def wants_current(subject_kind: str) -> bool:
    """Whether this kind of subject is judged partly by how current its corpus is."""
    return normalise_subject_kind(subject_kind) != SUBJECT_CANON


# ── publication year ─────────────────────────────────────────────────────────

# Where a year is recorded, by fetcher: OpenAlex, Europe PMC (pubmed) and
# Semantic Scholar (pdf) put an integer ``year`` on the candidate; arXiv puts a
# ``published`` timestamp. The fetchers that build their metadata from the
# candidate's carry it onto the fetched source. Wikipedia, Gutenberg, Exa, web,
# thought leaders, Reddit and YouTube record no date at all — Exa returns one and
# the fetcher does not keep it — so for those the year is unknown, and unknown
# is what this returns rather than a guess from the title.
_YEAR_FIELDS = ("year", "published")
_YEAR_RE = re.compile(r"\b(1[4-9]\d\d|20\d\d)\b")


def publication_year(metadata: dict | None, today: int | None = None) -> int | None:
    """The year a source was published, where its fetcher recorded one."""
    meta = metadata if isinstance(metadata, dict) else {}
    latest = (today or datetime.date.today().year) + 1
    for name in _YEAR_FIELDS:
        value = meta.get(name)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int):
            year: int | None = value
        else:
            match = _YEAR_RE.search(str(value))
            year = int(match.group(1)) if match else None
        if year is not None and 1400 <= year <= latest:
            return year
    return None


# ── recency ──────────────────────────────────────────────────────────────────

# A source this many years old or younger is current. Ten years is about one
# edition of a standard handbook and about the life of a review article in a
# moving field; varroa management, the thing expert 41 could not answer, has
# changed more than once in that time.
RECENT_YEARS = 10
# A dated source older than this is history, for a practice or a research front.
# Thirty years, not the public-domain cutoff: a 1980s manual predates every
# current varroa treatment as surely as an 1853 one does.
OLD_YEARS = 30

# Where a text comes from that says it is old without any date. Every Project
# Gutenberg book is public domain, which in English almost always means
# published before the cutoff (see sources/canonical.public_domain_cutoff_year).
_ALWAYS_OLD_TYPES = frozenset({SourceType.GUTENBERG})

# Research channels. A single paper here is a finding, not practice.
SCHOLARLY_TYPES = frozenset(
    {SourceType.ARXIV, SourceType.PUBMED, SourceType.OPENALEX, SourceType.PDF}
)


def age_class(
    source_type: SourceType, metadata: dict | None, today: int | None = None
) -> str | None:
    """``recent`` | ``old`` | ``None`` (dated in between, or not dated at all)."""
    if source_type in _ALWAYS_OLD_TYPES:
        return "old"
    year = publication_year(metadata, today)
    if year is None:
        return None
    now = today or datetime.date.today().year
    if now - year <= RECENT_YEARS:
        return "recent"
    if now - year > OLD_YEARS:
        return "old"
    return None


# The triage prior, on the model's 0–10 scale. Modest on purpose: the domain
# priors run from −5 to +2.5, and this is a nudge in the order, not a filter. An
# old manual the model scores 8 still ranks at 7 and is still fetched — it stays
# welcome as history; it just stops outranking a current guide it ties with. A
# must-have work is lifted to 9 after every prior, so a named classic is never
# touched. For a practice the boost for recency is half the research front's:
# a recent *paper* is not practitioner material, and the undated web guides that
# are cannot be boosted by a year they do not carry (the triage prompt says what
# counts instead — see sources/triage.py).
_RECENCY_PRIOR: dict[str, dict[str, float]] = {
    SUBJECT_PRACTICE: {"recent": 0.5, "old": -1.0},
    SUBJECT_RESEARCH_FRONT: {"recent": 1.0, "old": -1.0},
}


def recency_adjustment(
    source_type: SourceType,
    metadata: dict | None,
    subject_kind: str,
    today: int | None = None,
) -> float:
    """The triage score adjustment a candidate's age earns for this kind of subject."""
    prior = _RECENCY_PRIOR.get(normalise_subject_kind(subject_kind))
    if not prior:
        return 0.0
    age = age_class(source_type, metadata, today)
    return prior.get(age, 0.0) if age else 0.0


# ── current practitioner material ────────────────────────────────────────────

# What the validator calls a source that teaches how to do the thing: a guide or
# how-to (tutorial), a manual or reference work (reference), a handbook or
# course text (textbook). Extension-service leaflets, professional bodies'
# guidance and standard handbooks all land in these three.
PRACTICAL_CONTENT_TYPES = frozenset({"tutorial", "reference", "textbook"})

# An encyclopedia article is current and reference-shaped, and is still not
# practitioner guidance; a forum thread is practitioners, and is not guidance.
_NEVER_PRACTITIONER_TYPES = frozenset({SourceType.WIKIPEDIA, SourceType.REDDIT})

# A paper that surveys a field rather than reporting one finding. OpenAlex types
# its works (``work_type``, "review"); other channels only have the title.
_REVIEW_TITLE = re.compile(
    r"\b(?:review|overview|survey|guidelines?|best practices?|state of the art|"
    r"consensus|recommendations)\b",
    re.IGNORECASE,
)


def is_review(source: ValidatedSource) -> bool:
    """Whether a scholarly source is a review or guideline rather than one finding."""
    meta = source.raw.metadata or {}
    if str(meta.get("work_type") or "").casefold() == "review":
        return True
    return bool(_REVIEW_TITLE.search(source.title or ""))


def is_current_material(
    source: ValidatedSource, subject_kind: str, today: int | None = None
) -> bool:
    """Whether a source is the current practitioner material this subject needs.

    Read from what the pipeline already records — source type, the validator's
    content type, the publication year where a fetcher kept one:

    - never a Gutenberg text, or anything dated more than :data:`RECENT_YEARS`
      ago: that is history, welcome in the corpus, not what answers "how do I";
    - a scholarly source (arXiv, PubMed, OpenAlex, an open-access PDF) must be
      *dated* recent, and for a practice must also be a review or guideline —
      one virology paper is not beekeeping practice. For a research front a
      recent paper is the front, so any recent paper counts;
    - anything else (web, Exa, a thought leader's own writing, a talk, an
      upload) counts when the validator called it a tutorial, a reference work
      or a textbook — undated, because those channels record no date, and what
      they return is overwhelmingly the modern web. Wikipedia and Reddit never
      count.

    Always false for a canon: the notion does not apply there.
    """
    kind = normalise_subject_kind(subject_kind)
    if kind == SUBJECT_CANON:
        return False
    meta = source.raw.metadata or {}
    age = age_class(source.source_type, meta, today)
    if age == "old":
        return False
    year = publication_year(meta, today)
    now = today or datetime.date.today().year
    dated_recent = year is not None and now - year <= RECENT_YEARS
    if source.source_type in SCHOLARLY_TYPES or source.content_type == "paper":
        if not dated_recent:
            return False
        return kind == SUBJECT_RESEARCH_FRONT or is_review(source)
    if source.source_type in _NEVER_PRACTITIONER_TYPES:
        return False
    if year is not None and not dated_recent:
        return False
    return source.content_type in PRACTICAL_CONTENT_TYPES


def is_narrow_paper(source: ValidatedSource) -> bool:
    """A single research paper: one finding, which must not become the corpus.

    A review or guideline is not narrow — it is the survey the corpus wants — and
    a work the research plan named (``must_have_title``) is exempt: the plan
    asked for that text, whole.
    """
    meta = source.raw.metadata or {}
    if meta.get("must_have_title"):
        return False
    if source.source_type not in SCHOLARLY_TYPES and source.content_type != "paper":
        return False
    return not is_review(source)
