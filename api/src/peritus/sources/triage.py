"""Candidate triage — ranks cheap search hits before paying full-fetch costs.

Discovery over-searches (several multiples of the fetch budget — 3× the
per-fetcher quota with a floor of 10 results per query, see
builder._search_breadth), then a fast Claude pass scores every candidate's
expected value against the research brief. Only the ranked winners get fully
downloaded/OCR'd, so the pipeline considers far more candidates than it
fetches.

The model score is combined with a **domain prior**. Title and snippet alone
cannot distinguish a work from a summary of that work: "Meditations by Marcus
Aurelius" reads identically whether it is the text or a reader's review of it,
and a corpus assembled from review sites answers questions in the voice of a
review site. Where the source *came from* is the cheapest available signal about
what it is, and unlike the model's judgement it costs nothing and never varies.
"""

import difflib
import re
from dataclasses import dataclass
from typing import Any

from anthropic.types import Message

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_batch import gather_claude_calls
from peritus.infrastructure.anthropic_client import tool_input
from peritus.sources.canonical import classify_extent, matching_work, title_key
from peritus.sources.domain import SourceCandidate, SourceType
from peritus.sources.hosts import host_and_path, suffix_matches
from peritus.sources.subject import (
    SUBJECT_CANON,
    SUBJECT_PRACTICE,
    SUBJECT_RESEARCH_FRONT,
    normalise_subject_kind,
    recency_adjustment,
)

logger = get_logger(__name__)

_TRIAGE_BATCH_SIZE = 20
# Sizes a failed or partly-scored batch is re-asked at, for its unscored
# candidates only. Smaller batches are where a model stops skipping entries.
_REASK_BATCH_SIZES: tuple[int, ...] = (10, 5)
_SNIPPET_CHARS = 400
# Public: the screening ledger stores exactly what triage was shown.
TRIAGE_SNIPPET_CHARS = _SNIPPET_CHARS
# Below this expected value a candidate isn't worth a full fetch at all.
MIN_TRIAGE_SCORE = 3.0
_NEAR_DUP_TITLE_RATIO = 0.85

# What a triage score rests on, recorded per candidate in the screening ledger.
#
# There is deliberately no neutral fallback score any more. A failed batch used
# to give every candidate in it 5.0, which outranked every honest 3 and 4: the
# Thomism build (job 53) fetched an actress, a disambiguation page and an OCR'd
# visual-analytics paper that a live re-run scored 0.0–1.5. An outage now costs
# candidates, never a corpus full of junk.
STATUS_SCORED = "scored"
STATUS_REASKED = "reasked"
STATUS_UNSCORED = "unscored"
STATUS_MUST_HAVE = "must_have"
STATUS_PRIORITY = "priority"

# Source types that can carry a work's title and never be the work: an
# encyclopedia article named "Summa Theologica", a lecture, a forum thread.
# They are triaged on their merits; they are not must-have hits.
_NOT_THE_WORK_TYPES = frozenset({SourceType.WIKIPEDIA, SourceType.YOUTUBE, SourceType.REDDIT})

_TRIAGE_TOOL: dict[str, Any] = {
    "name": "triage_candidates",
    "description": "Score each candidate source's expected value for the expert corpus.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "description": "One entry per candidate, each naming the candidate it scores.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": (
                                "The candidate's tag, copied exactly — e.g. "
                                "'candidate_3' for <candidate_3>."
                            ),
                        },
                        "expected_value": {
                            "type": "number",
                            "description": (
                                "0–10. How valuable this source is likely to be: "
                                "relevance to the topic and key concepts, depth, "
                                "authority, and whether it adds something the other "
                                "candidates don't."
                            ),
                        },
                    },
                    "required": ["id", "expected_value"],
                },
            }
        },
        "required": ["scores"],
    },
}

_SYSTEM = (
    "You triage search results for a research corpus. Only titles, URLs and "
    "snippets are available — judge expected value, not final quality.\n"
    "\n"
    "Rank highest: the primary material itself (the work, the original paper, "
    "the dataset, the standard, the practitioner's own writing), and substantive "
    "analysis of it with an argument of its own.\n"
    "\n"
    "Rank low, however well the title matches the topic: reader reviews and "
    "ratings of a work, plot or chapter summaries, study and revision guides, "
    "quote collections, book-summary services, listicles ('10 tips for…', "
    "'best X of 2024'), SEO explainers that restate a definition without adding "
    "anything, and pages that mainly link elsewhere. A page *about* an important "
    "work is not the important work, and a corpus of such pages can only produce "
    "second-hand answers.\n"
    "\n"
    "Score 0–1, however well the title matches the topic: institutional pages "
    "(a college, a society, a parish), biographies of people who merely share a "
    "name with the subject, disambiguation pages, library catalogue records, "
    "tables of contents, and one-paragraph book reviews. None of them contain "
    "the subject.\n"
    "\n"
    "The URL is evidence: judge the publisher, not just the headline."
)

# Domain priors, applied after the model's score. Deliberately a plain table of
# (host-or-TLD suffix, adjustment) so it can be read, argued with, and extended
# without touching any logic — the numbers are on the same 0–10 scale as the
# model's own score, and the result is clamped back into it.
#
# Longest matching suffix wins, so a specific host overrides the TLD class it
# sits in (``plato.stanford.edu`` is better than ``.edu`` generally).
_HOST_ADJUSTMENTS: tuple[tuple[str, float], ...] = (
    # ── Penalised: describes a work rather than being one ──────────────────
    # Reader reviews, study guides, summary services, quote farms. These pass
    # title-and-snippet triage effortlessly, which is exactly the problem.
    ("goodreads.com", -3.5),
    ("sparknotes.com", -3.5),
    ("cliffsnotes.com", -3.5),
    ("shmoop.com", -3.5),
    ("gradesaver.com", -3.5),
    ("bookrags.com", -3.5),
    ("supersummary.com", -3.5),
    ("litcharts.com", -3.0),
    ("enotes.com", -3.0),
    ("blinkist.com", -3.5),
    ("getabstract.com", -3.0),
    ("fourminutebooks.com", -3.5),
    ("brainyquote.com", -4.0),
    ("azquotes.com", -4.0),
    ("quotefancy.com", -4.0),
    # Homework/answer farms and slide dumps.
    ("coursehero.com", -3.5),
    ("studocu.com", -3.5),
    ("quizlet.com", -3.0),
    ("answers.com", -3.5),
    ("chegg.com", -3.0),
    ("slideshare.net", -2.0),
    ("scribd.com", -2.0),
    # Content farms and social aggregation. Not worthless — a good practitioner
    # post lives on Medium — so these are a nudge, not a veto.
    ("ehow.com", -3.0),
    ("wikihow.com", -2.0),
    ("buzzfeed.com", -3.0),
    ("pinterest.com", -4.0),
    ("quora.com", -2.5),
    ("linkedin.com/pulse", -1.5),
    ("medium.com", -1.0),
    # Library catalogue records. They carry a title, a subject heading and
    # sometimes a publisher's blurb, which passes both triage and validation as
    # "a scholarly book" — twelve of the 43 sources kept by the Thomism build
    # were records like these, at 300–4,500 characters each.
    ("ci.nii.ac.jp", -4.0),
    ("bvbr.bib-bvb.de", -4.0),
    ("catalog.loc.gov", -4.0),
    ("worldcat.org", -4.0),
    # Pirate mirrors of books and papers. Their copies are unlicensed, often
    # incomplete, and a corpus built on them cites a download site. A live
    # rebuild kept a "PDF Free Download" copy of an in-copyright monograph.
    ("docplayer.net", -5.0),
    ("dokumen.pub", -5.0),
    ("dokumen.tips", -5.0),
    ("pdfcoffee.com", -5.0),
    ("epdf.pub", -5.0),
    ("ebin.pub", -5.0),
    ("vdoc.pub", -5.0),
    ("docslib.org", -5.0),
    ("pdfdrive.com", -5.0),
    ("oceanofpdf.com", -5.0),
    ("z-lib.org", -5.0),
    ("annas-archive.org", -5.0),
    ("libgen.is", -5.0),
    ("libgen.rs", -5.0),
    ("vdocuments.net", -5.0),
    ("idoc.pub", -5.0),
    ("studylib.net", -3.5),
    # Overview mills that passed validation as tertiary on the same build.
    ("studyguides.com", -3.0),
    ("philosophystudent.org", -3.0),
    ("handwiki.org", -3.0),
    # ── Boosted: primary texts, canonical publishers, standards bodies ─────
    ("gutenberg.org", 2.0),
    ("archive.org", 1.5),
    ("perseus.tufts.edu", 2.0),
    ("plato.stanford.edu", 2.5),
    ("iep.utm.edu", 1.5),
    ("arxiv.org", 1.5),
    ("pubmed.ncbi.nlm.nih.gov", 2.0),
    ("ncbi.nlm.nih.gov", 1.5),
    ("europepmc.org", 1.5),
    # A DOI resolver URL is almost always a published scholarly work.
    ("doi.org", 1.5),
    ("openalex.org", 1.0),
    ("jstor.org", 1.5),
    ("nature.com", 2.0),
    ("science.org", 2.0),
    ("sciencedirect.com", 1.5),
    ("link.springer.com", 1.5),
    ("cambridge.org", 2.0),
    ("oup.com", 2.0),
    ("academic.oup.com", 2.0),
    ("tandfonline.com", 1.5),
    ("wiley.com", 1.5),
    ("mitpress.mit.edu", 2.0),
    ("hbr.org", 1.0),
    # Standards bodies, regulators, and official statistics — the source of
    # record for anything they publish.
    ("nist.gov", 2.0),
    ("ietf.org", 2.0),
    ("w3.org", 2.0),
    ("iso.org", 1.5),
    ("sec.gov", 2.0),
    ("federalreserve.gov", 2.0),
    ("bis.org", 1.5),
    ("imf.org", 1.5),
    ("worldbank.org", 1.5),
    ("oecd.org", 1.5),
    ("who.int", 1.5),
    ("loc.gov", 1.5),
    # TLD classes, as a floor under anything not named above.
    (".edu", 1.5),
    (".gov", 1.5),
    (".ac.uk", 1.5),
    (".edu.au", 1.5),
    (".ac.jp", 1.0),
    (".int", 1.0),
)

# URL-shape priors, independent of host: the same content farm patterns show up
# on domains no list can enumerate. Worst single match applies.
_PATH_ADJUSTMENTS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"/(?:top|best)[-_]?\d+"), -2.0),
    (
        re.compile(r"\d+[-_](?:best|top|tips|ways|rules|habits|lessons|things|secrets|quotes)\b"),
        -2.0,
    ),
    (re.compile(r"(?:book|chapter|plot)[-_]summar(?:y|ies)"), -2.5),
    (re.compile(r"summary[-_]of[-_]"), -2.0),
    (re.compile(r"/(?:study|revision)[-_]guide"), -2.0),
    (re.compile(r"/(?:quotes|quotations)(?:/|$)"), -1.5),
    (re.compile(r"/(?:tag|tags|category|categories)/"), -1.0),
    (re.compile(r"/(?:review|reviews)/"), -1.5),
    # Library of Congress tables of contents. Before this rule they collected
    # the `.gov` boost and scored 4.5 for being on a government site.
    (re.compile(r"/catdir/toc/"), -4.0),
)

# DOI-prefix priors, for publishers whose DOIs name something that is not a work.
# Matched against the path of a ``doi.org`` URL, after the resolver's own boost.
_DOI_PREFIX_ADJUSTMENTS: tuple[tuple[str, float], ...] = (
    # Choice book reviews: one paragraph, and +1.5 as a DOI until this line.
    ("/10.5860/choice", -3.0),
)

# Wiki software on a host that is not one of the real wikis is almost always a
# mirror or a fork of an encyclopedia article — the same text, less maintained.
_WIKI_PATH = re.compile(r"/wiki/")
_REAL_WIKI_HOSTS: tuple[str, ...] = ("wikipedia.org", "wikisource.org", "wikiquote.org")
_WIKI_MIRROR_ADJUSTMENT = -1.0


def domain_adjustment(url: str) -> float:
    """The score adjustment this URL's provenance earns, before clamping.

    Pure and total: an unparseable or unknown URL scores 0.0 and the model's
    judgement stands alone.
    """
    host, path = host_and_path(url)
    if not host:
        return 0.0

    # One host rule, the most specific — matches don't stack, so adding a host
    # to the table can never silently double an existing TLD adjustment.
    host_delta = 0.0
    best_len = -1
    for pattern, delta in _HOST_ADJUSTMENTS:
        if suffix_matches(host, path, pattern) and len(pattern) > best_len:
            host_delta, best_len = delta, len(pattern)

    # Path rules add to the host rule rather than replacing it, so a catalogue
    # page on a `.gov` host nets −2.5, not +1.5.
    path_deltas = [d for rx, d in _PATH_ADJUSTMENTS if rx.search(path)]
    if host == "doi.org" or host.endswith(".doi.org"):
        path_deltas += [d for prefix, d in _DOI_PREFIX_ADJUSTMENTS if path.startswith(prefix)]
    if _WIKI_PATH.search(path) and not any(
        suffix_matches(host, path, wiki) for wiki in _REAL_WIKI_HOSTS
    ):
        path_deltas.append(_WIKI_MIRROR_ADJUSTMENT)
    return host_delta + (min(path_deltas) if path_deltas else 0.0)


def penalised_hosts(threshold: float = -2.5) -> list[str]:
    """Hosts the prior penalises at least this hard — the ones not worth searching.

    Handed to search APIs that accept a domain exclusion list (Exa), so results
    triage would score down anyway are never paid for in triage tokens or slots.
    Patterns with a path are left out: an exclusion list takes domains only.
    """
    return [
        pattern
        for pattern, delta in _HOST_ADJUSTMENTS
        if delta <= threshold and "/" not in pattern and not pattern.startswith(".")
    ]


@dataclass
class TriagedCandidate:
    candidate: SourceCandidate
    # What the fetch queue sorts on: the model's score plus the domain prior,
    # clamped, and lifted for a must-have work.
    score: float
    # The model's own number, before any prior. ``None`` when the model never
    # scored this candidate — which is recorded, not papered over.
    model_score: float | None = None
    domain_adjustment: float = 0.0
    status: str = STATUS_SCORED
    # The recency prior for a practice or a research front (sources/subject.py);
    # 0.0 for a canon, where age is not a demerit.
    recency_adjustment: float = 0.0


async def triage_candidates(
    topic: str,
    key_concepts: list[str],
    must_have_titles: list[str],
    candidates: list[SourceCandidate],
    subject_kind: str = SUBJECT_CANON,
) -> list[TriagedCandidate]:
    """Score all candidates in batched Haiku calls. Order is preserved.

    ``subject_kind`` (sources/subject.py) is what the research plan said this
    subject is. For a canon — and for every caller that does not pass it — triage
    is exactly what it was. For a practice or a research front the model is told
    what counts as authoritative there, and a modest recency prior is added next
    to the domain prior: a dated recent source gains a little, a Gutenberg text or
    a source dated more than thirty years ago loses a point. Old material is
    reordered, never excluded; a must-have work is lifted past both.

    Calls run through the Message Batches API (half price) when enabled, else
    as concurrent live calls. Scores are matched to candidates by the id the
    model echoes back, never by position: a response that skips one entry in
    the middle used to shift every later score onto the wrong candidate.

    A candidate the first pass did not score is re-asked in smaller batches
    (see :data:`_REASK_BATCH_SIZES`). One still unscored after that gets 0.0 and
    ``status = unscored`` — it fails closed, and is fetched only if something
    other than its score vouches for it (a must-have title, a snowball priority).
    """
    if not candidates:
        return []

    model_scores: dict[int, float] = {}
    reasked: set[int] = set()

    pending = list(range(len(candidates)))
    sizes = (_TRIAGE_BATCH_SIZE, *_REASK_BATCH_SIZES)
    for attempt, size in enumerate(sizes):
        if not pending:
            break
        if attempt:
            logger.warning(
                "Triage: re-asking %d unscored candidate(s) in batches of %d",
                len(pending),
                size,
            )
            reasked.update(pending)
        batches = [pending[i : i + size] for i in range(0, len(pending), size)]
        responses = await gather_claude_calls(
            [
                _triage_params(topic, key_concepts, [candidates[j] for j in b], subject_kind)
                for b in batches
            ],
            live_concurrency=settings.VALIDATE_CONCURRENCY,
            description="triage" if attempt == 0 else "triage-reask",
        )
        for batch, resp in zip(batches, responses, strict=True):
            if resp is None:
                logger.warning("Triage batch failed (%d candidates)", len(batch))
                continue
            try:
                scores = _parse_triage_response(resp, len(batch))
            except Exception as exc:
                logger.warning("Triage batch unparseable (%d candidates): %s", len(batch), exc)
                continue
            if len(scores) < len(batch):
                logger.warning(
                    "Triage batch scored %d of %d candidates",
                    len(scores),
                    len(batch),
                )
            for local, value in scores.items():
                model_scores[batch[local]] = value
        pending = [j for j in pending if j not in model_scores]

    if pending:
        logger.warning(
            "Triage: %d of %d candidate(s) were never scored — they fail closed at 0.0",
            len(pending),
            len(candidates),
        )

    triaged: list[TriagedCandidate] = []
    for index, candidate in enumerate(candidates):
        model = model_scores.get(index)
        adjustment = domain_adjustment(candidate.url)
        recency = recency_adjustment(candidate.source_type, candidate.metadata, subject_kind)
        if model is None:
            score, status = 0.0, STATUS_UNSCORED
        else:
            # Provenance and recency priors, then clamp back onto the model's
            # own scale.
            score = min(max(model + adjustment + recency, 0.0), 10.0)
            status = STATUS_REASKED if index in reasked else STATUS_SCORED
        # A must-have work found by search should never lose the triage —
        # applied last, so a canonical text hosted somewhere unglamorous
        # still survives its domain's prior.
        #
        # Marked as well as scored. A score can be traded away by whatever
        # the fetch stage divides it by; a flag says what is actually meant,
        # which is "the research plan named this work, do not come back
        # without it". Whether the hit is the whole work or one section of it
        # is recorded too: a single question of the Summa is worth fetching,
        # and is not the Summa.
        wanted = (
            None
            if candidate.source_type in _NOT_THE_WORK_TYPES
            else matching_work(candidate.title, must_have_titles, candidate.url)
        )
        if wanted is not None:
            score = max(score, 9.0)
            status = STATUS_MUST_HAVE
            candidate.metadata["fetch_priority"] = True
            candidate.metadata.setdefault("must_have_title", wanted)
            candidate.metadata.setdefault(
                "must_have_extent", classify_extent(candidate.title, candidate.url)
            )
        elif candidate.metadata.get("fetch_priority"):
            status = STATUS_PRIORITY
        triaged.append(
            TriagedCandidate(
                candidate=candidate,
                score=score,
                model_score=model,
                domain_adjustment=adjustment,
                status=status,
                recency_adjustment=recency,
            )
        )
    return triaged


def rank_candidates(
    triaged: list[TriagedCandidate],
    min_score: float = MIN_TRIAGE_SCORE,
) -> list[TriagedCandidate]:
    """Rank by score, drop junk, and drop near-duplicate titles.

    Returns the full ranked list (not cut to budget) so the fetch stage can
    refill from lower ranks when a download fails.

    Titles are compared within a group. A candidate for a must-have work is
    compared only with candidates for the same work and the same named
    sections; everything else only with everything else. The resolver queues
    one lookup per volume of a multi-volume work on purpose, and the volumes'
    titles differ by a designator: "Summa Theologica, Part I-II" is 0.93 of
    "Summa Theologica, Part I", and a live Thomism build dropped Part I-II and
    Part III as near-duplicates of Part I — taking the treatise on law, the
    plan's named text for natural law, with them. Two copies of one volume from
    two routes still collapse, and volumes whose designators differ never do.
    """
    ranked = sorted(triaged, key=lambda t: t.score, reverse=True)
    kept: list[TriagedCandidate] = []
    # Per group: each kept title with its volume designators, computed once.
    kept_titles: dict[tuple[str, str] | None, list[tuple[str, set[str]]]] = {}
    for item in ranked:
        # A priority candidate (a must-have, a work several accepted sources
        # cite) does not depend on its score, so an unscored one still ranks.
        if item.score < min_score and not item.candidate.metadata.get("fetch_priority"):
            continue
        group = _dedup_group(item.candidate)
        title = item.candidate.title.casefold().strip()
        designators = _designators(title)
        seen = kept_titles.setdefault(group, [])
        if _near_duplicate(title, designators, seen, same_work=group is not None):
            continue
        kept.append(item)
        seen.append((title, designators))
    return kept


def _dedup_group(candidate: SourceCandidate) -> tuple[str, str] | None:
    """The work and sections a must-have candidate is for; ``None`` for anything else."""
    wanted = candidate.metadata.get("must_have_title")
    if not wanted:
        return None
    sections = " ".join(str(candidate.metadata.get("must_have_sections") or "").casefold().split())
    return title_key(str(wanted)), sections


# Numbered volume and part designators: "Part I-II", "Vol. 3", "Book II".
_DESIGNATOR = re.compile(
    r"\b(?:part|vol(?:ume)?|book|tome)\.?\s+([ivxlc]+(?:\s*-\s*[ivxlc]+)?|\d+)\b",
    re.IGNORECASE,
)


def _designators(title: str) -> set[str]:
    return {re.sub(r"\s+", "", m.group(1).casefold()) for m in _DESIGNATOR.finditer(title)}


def _near_duplicate(
    title: str, designators: set[str], kept: list[tuple[str, set[str]]], same_work: bool
) -> bool:
    """Whether ``title`` is within the ratio of a kept title (differing volumes never are).

    The cheap upper bounds are checked before the full ratio: a round compares
    every candidate title with every kept one, and the full ratio is what cost.
    """
    matcher = difflib.SequenceMatcher(None, title)
    for other, other_designators in kept:
        if same_work and designators != other_designators:
            continue
        matcher.set_seq2(other)
        if (
            matcher.real_quick_ratio() >= _NEAR_DUP_TITLE_RATIO
            and matcher.quick_ratio() >= _NEAR_DUP_TITLE_RATIO
            and matcher.ratio() >= _NEAR_DUP_TITLE_RATIO
        ):
            return True
    return False


# What the model is told about a subject that is not a canon. Appended to the
# user message, never the system prompt, so a canon's request is byte-for-byte
# what it was. Without it an extension service's leaflet and an 1853 manual look
# alike from a title and a snippet — both are "a practical guide to X" — and the
# undated web guide, which the recency prior cannot see, has only this to lift it.
_SUBJECT_NOTES: dict[str, str] = {
    SUBJECT_PRACTICE: (
        "This subject is a practice — a craft or how-to field. What is authoritative "
        "is current practice: extension services, professional and trade bodies, "
        "standard handbooks, recent reviews and practitioners' own guidance. A "
        "century-old manual is history, worth having but not as the answer to 'how "
        "do I'; a narrow research paper is one finding, not practice."
    ),
    SUBJECT_RESEARCH_FRONT: (
        "This subject is a research front — a fast-moving field. What is "
        "authoritative is the recent literature and its reviews; older work matters "
        "as foundation, and is superseded where the field has moved."
    ),
}


def _triage_params(
    topic: str,
    key_concepts: list[str],
    batch: list[SourceCandidate],
    subject_kind: str = SUBJECT_CANON,
) -> dict[str, Any]:
    """Request params for one triage batch (consumed by gather_claude_calls)."""
    candidates_block = "\n\n".join(
        f"<candidate_{i}>\n"
        f"Type: {c.source_type.value}\n"
        f"Title: {c.title}\n"
        # The publisher is often the strongest available signal about what a
        # candidate actually is; before this the model never saw it at all.
        + (f"URL: {c.url}\n" if c.url else "")
        + (f"Author: {c.author}\n" if c.author else "")
        + f"Snippet: {c.snippet[:_SNIPPET_CHARS]}\n"
        f"</candidate_{i}>"
        for i, c in enumerate(batch)
    )
    concepts_block = (
        "Key concepts the corpus must cover:\n" + "\n".join(f"- {c}" for c in key_concepts) + "\n\n"
        if key_concepts
        else ""
    )
    note = _SUBJECT_NOTES.get(normalise_subject_kind(subject_kind))
    subject_block = f"{note}\n\n" if note else ""
    return {
        "model": settings.FAST_MODEL,
        "max_tokens": 64 * len(batch) + 256,
        "system": _SYSTEM,
        "tools": [_TRIAGE_TOOL],
        "tool_choice": {"type": "tool", "name": "triage_candidates"},
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Topic: {topic}\n\n"
                    f"{subject_block}"
                    f"{concepts_block}"
                    f"{candidates_block}\n\n"
                    f"Score all {len(batch)} candidates above."
                ),
            }
        ],
    }


_ID_RE = re.compile(r"(\d+)\s*>?\s*$")


def _parse_triage_response(resp: Message | None, batch_len: int) -> dict[int, float]:
    """``{position in batch: score}`` for the entries the model actually scored.

    Keyed by the id each entry names. An entry with no readable id, an id outside
    the batch, a repeat of an id already scored, or no numeric value is ignored —
    its candidate simply stays unscored, which the caller re-asks.
    """
    block = tool_input(resp) or {}
    raw_scores = block.get("scores", [])
    scores: dict[int, float] = {}
    for entry in raw_scores if isinstance(raw_scores, list) else []:
        if not isinstance(entry, dict):
            continue
        match = _ID_RE.search(str(entry.get("id", "")))
        if match is None:
            continue
        index = int(match.group(1))
        if not 0 <= index < batch_len or index in scores:
            continue
        try:
            value = float(entry["expected_value"])
        except (KeyError, TypeError, ValueError):
            continue
        scores[index] = min(max(value, 0.0), 10.0)
    return scores
