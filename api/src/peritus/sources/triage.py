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
from urllib.parse import urlsplit

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_batch import gather_claude_calls
from peritus.sources.domain import SourceCandidate

logger = get_logger(__name__)

_TRIAGE_BATCH_SIZE = 20
_SNIPPET_CHARS = 400
# Below this expected value a candidate isn't worth a full fetch at all.
MIN_TRIAGE_SCORE = 3.0
# Neutral score assumed when a triage batch fails — keeps candidates usable
# without letting an outage promote junk above genuinely scored items.
_FALLBACK_SCORE = 5.0
_NEAR_DUP_TITLE_RATIO = 0.85

_TRIAGE_TOOL: dict[str, Any] = {
    "name": "triage_candidates",
    "description": "Score each candidate source's expected value for the expert corpus.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "description": "One entry per candidate, in the same order as the input.",
                "items": {
                    "type": "object",
                    "properties": {
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
                    "required": ["expected_value"],
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
    (re.compile(r"\d+[-_](?:best|top|tips|ways|rules|habits|lessons|things|secrets|quotes)\b"), -2.0),
    (re.compile(r"(?:book|chapter|plot)[-_]summar(?:y|ies)"), -2.5),
    (re.compile(r"summary[-_]of[-_]"), -2.0),
    (re.compile(r"/(?:study|revision)[-_]guide"), -2.0),
    (re.compile(r"/(?:quotes|quotations)(?:/|$)"), -1.5),
    (re.compile(r"/(?:tag|tags|category|categories)/"), -1.0),
    (re.compile(r"/(?:review|reviews)/"), -1.5),
)


def domain_adjustment(url: str) -> float:
    """The score adjustment this URL's provenance earns, before clamping.

    Pure and total: an unparseable or unknown URL scores 0.0 and the model's
    judgement stands alone.
    """
    if not url:
        return 0.0
    try:
        parts = urlsplit(url if "//" in url else f"//{url}")
    except ValueError:
        return 0.0

    host = (parts.hostname or "").lower().removeprefix("www.")
    path = (parts.path or "").lower()

    # One host rule, the most specific — matches don't stack, so adding a host
    # to the table can never silently double an existing TLD adjustment.
    host_delta = 0.0
    best_len = -1
    for pattern, delta in _HOST_ADJUSTMENTS:
        target = f"{host}{path}" if "/" in pattern else host
        if _suffix_matches(target, pattern) and len(pattern) > best_len:
            host_delta, best_len = delta, len(pattern)

    path_deltas = [d for rx, d in _PATH_ADJUSTMENTS if rx.search(path)]
    return host_delta + (min(path_deltas) if path_deltas else 0.0)


def _suffix_matches(target: str, pattern: str) -> bool:
    """Domain-suffix match on a label boundary, so ``notgoodreads.com`` is not
    penalised for containing ``goodreads.com``. Patterns containing a slash
    (e.g. ``linkedin.com/pulse``) are matched as a prefix of host+path instead."""
    if "/" in pattern:
        return target.startswith(pattern)
    p = pattern.lstrip(".")
    return target == p or target.endswith(f".{p}")


@dataclass
class TriagedCandidate:
    candidate: SourceCandidate
    score: float


async def triage_candidates(
    topic: str,
    key_concepts: list[str],
    must_have_titles: list[str],
    candidates: list[SourceCandidate],
) -> list[TriagedCandidate]:
    """Score all candidates in batched Haiku calls. Order is preserved.

    Calls run through the Message Batches API (half price) when enabled, else
    as concurrent live calls.
    """
    if not candidates:
        return []

    batches = [
        candidates[i: i + _TRIAGE_BATCH_SIZE]
        for i in range(0, len(candidates), _TRIAGE_BATCH_SIZE)
    ]

    responses = await gather_claude_calls(
        [_triage_params(topic, key_concepts, b) for b in batches],
        live_concurrency=settings.VALIDATE_CONCURRENCY,
        description="triage",
    )

    batch_scores: list[list[float]] = []
    for batch, resp in zip(batches, responses, strict=True):
        if resp is None:
            logger.warning("Triage batch failed (%d candidates)", len(batch))
            batch_scores.append([_FALLBACK_SCORE] * len(batch))
            continue
        try:
            batch_scores.append(_parse_triage_response(resp, len(batch)))
        except Exception as exc:
            logger.warning("Triage batch unparseable (%d candidates): %s", len(batch), exc)
            batch_scores.append([_FALLBACK_SCORE] * len(batch))

    triaged: list[TriagedCandidate] = []
    for batch, scores in zip(batches, batch_scores, strict=True):
        for candidate, score in zip(batch, scores, strict=True):
            # Provenance prior, then clamp back onto the model's own scale.
            score = min(max(score + domain_adjustment(candidate.url), 0.0), 10.0)
            # A must-have work found by search should never lose the triage —
            # applied last, so a canonical text hosted somewhere unglamorous
            # still survives its domain's prior.
            if _matches_must_have(candidate.title, must_have_titles):
                score = max(score, 9.0)
            triaged.append(TriagedCandidate(candidate=candidate, score=score))
    return triaged


def rank_candidates(
    triaged: list[TriagedCandidate],
    min_score: float = MIN_TRIAGE_SCORE,
) -> list[TriagedCandidate]:
    """Rank by score, drop junk, and drop near-duplicate titles.

    Returns the full ranked list (not cut to budget) so the fetch stage can
    refill from lower ranks when a download fails.
    """
    ranked = sorted(triaged, key=lambda t: t.score, reverse=True)
    kept: list[TriagedCandidate] = []
    kept_titles: list[str] = []
    for item in ranked:
        if item.score < min_score:
            continue
        title = item.candidate.title.casefold().strip()
        if any(
            difflib.SequenceMatcher(None, title, seen).ratio() >= _NEAR_DUP_TITLE_RATIO
            for seen in kept_titles
        ):
            continue
        kept.append(item)
        kept_titles.append(title)
    return kept


def _matches_must_have(title: str, must_have_titles: list[str]) -> bool:
    t = title.casefold().strip()
    for wanted in must_have_titles:
        w = wanted.casefold().strip()
        if not w:
            continue
        if w in t or difflib.SequenceMatcher(None, w, t).ratio() >= 0.7:
            return True
    return False


def _triage_params(
    topic: str,
    key_concepts: list[str],
    batch: list[SourceCandidate],
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
        "Key concepts the corpus must cover:\n"
        + "\n".join(f"- {c}" for c in key_concepts)
        + "\n\n"
        if key_concepts else ""
    )
    return {
        "model": settings.FAST_MODEL,
        "max_tokens": 64 * len(batch) + 256,
        "system": _SYSTEM,
        "tools": [_TRIAGE_TOOL],
        "tool_choice": {"type": "tool", "name": "triage_candidates"},
        "messages": [{
            "role": "user",
            "content": (
                f"Topic: {topic}\n\n"
                f"{concepts_block}"
                f"{candidates_block}\n\n"
                f"Score all {len(batch)} candidates above."
            ),
        }],
    }


def _parse_triage_response(resp: Any, batch_len: int) -> list[float]:
    block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
    raw_scores = list(block.input.get("scores", []))
    scores: list[float] = []
    for entry in raw_scores[:batch_len]:
        try:
            value = float(entry.get("expected_value", _FALLBACK_SCORE))
        except (TypeError, ValueError, AttributeError):
            value = _FALLBACK_SCORE
        scores.append(min(max(value, 0.0), 10.0))
    while len(scores) < batch_len:
        scores.append(_FALLBACK_SCORE)
    return scores
