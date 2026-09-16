"""Pure, dependency-free evaluation metrics.

Kept side-effect-free so they can be unit-tested in CI without a database, API
keys, or a live expert. The harness in ``runner.py`` wires these to real data.

Two families live here, and the split matters:

*Grounding* metrics (``recall_at_k``, ``citation_validity``,
``cited_supporting_sources``) ask whether an answer is **verifiable**. They were
the whole of this module, and that was the blind spot: an answer that toured its
own retrieval set — organised by source, a citation welded to every sentence, a
section auditing what the corpus lacked — scored ~1.0 on every one of them while
being close to useless to the person who asked. Optimising against them alone
actively rewards the failure.

*Screening* metrics (``screening_precision_recall``, ``cohen_kappa``,
``concept_jaccard``) ask a different question entirely: not whether an answer is
good, but whether the *corpus selection* was. They compare the validator's
keep/drop decisions against human labels, which is the only way to tell a rubric
change that improved screening from one that merely changed it. Kappa rather
than raw agreement, because a rubric that keeps 90% of everything agrees with a
human 90% of the time while exercising no judgement at all.

*Helpfulness* metrics (``citation_density``, ``source_narration_hits``,
``helpfulness_score``) ask whether an answer is **worth reading**. The first two
are deterministic and free, which is the point: they catch the exact regression
that prompted this work without an API call, so they can run in CI. The judged
dimensions they feed come from ``eval/helpfulness.py``.

Neither family is sufficient. A fabricated answer reads beautifully; a passage
tour is impeccably grounded.
"""

from __future__ import annotations

import re

from peritus.chat.grounding import parse_cited_indices

_CITATION_RE = re.compile(r"\[(\d{1,3})\]")

# Sentence split good enough for counting. Abbreviations ("e.g.", "Inc.") will
# occasionally over-split, which inflates the denominator and *understates*
# citation density — the safe direction for a metric used to detect over-citing.
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+(?:\s|$)|[^.!?]+$")


def recall_at_k(retrieved_chunk_ids: list[int], gold_chunk_ids: list[int], k: int) -> float:
    """Fraction of the gold supporting chunks present in the top-k retrieved."""
    gold = set(gold_chunk_ids)
    if not gold:
        return 1.0
    topk = set(retrieved_chunk_ids[:k])
    return len(gold & topk) / len(gold)


def citation_validity(answer_text: str, num_passages: int) -> float:
    """Fraction of bracketed citations in the answer that reference a real passage.

    A score below 1.0 means the model cited a number it was never given — i.e. a
    fabricated citation.
    """
    all_refs = [int(m.group(1)) for m in _CITATION_RE.finditer(answer_text)]
    if not all_refs:
        return 0.0  # an uncited answer is not verifiable
    valid = [n for n in all_refs if 1 <= n <= num_passages]
    return len(valid) / len(all_refs)


def cited_supporting_sources(
    answer_text: str,
    passage_source_ids: dict[int, int],
    gold_source_ids: list[int],
) -> float:
    """Did the answer cite passages from the sources that actually support it?

    ``passage_source_ids`` maps passage number → source_id; ``gold_source_ids`` are
    the source ids known to contain the answer. Returns recall over gold sources.
    """
    gold = set(gold_source_ids)
    if not gold:
        return 1.0
    cited = parse_cited_indices(answer_text, max(passage_source_ids, default=0))
    cited_sources = {passage_source_ids[n] for n in cited if n in passage_source_ids}
    return len(gold & cited_sources) / len(gold)


def looks_like_refusal(answer_text: str) -> bool:
    """Heuristic: did the expert decline for lack of evidence?"""
    t = answer_text.lower()
    cues = (
        "don't have enough",
        "do not have enough",
        "not enough information",
        "cannot answer",
        "can't answer",
        "no information",
        "isn't covered",
        "is not covered",
        "passages do not",
        "passages don't",
        "insufficient",
        "not addressed in",
        "outside the scope",
    )
    return any(c in t for c in cues)


def aggregate(scores: list[float]) -> float:
    return round(sum(scores) / len(scores), 4) if scores else 0.0


# ---------------------------------------------------------------------------
# Helpfulness — is the answer worth reading?
# ---------------------------------------------------------------------------

# Phrases that narrate the retrieval set instead of the subject. Every one of
# these is lifted from the answer that prompted this work ("one Goodreads
# summary frames…", "What's missing from these passages…", "most of this is
# secondary summary"), or is the same move in different words.
#
# Deliberately NOT listed: "my sources don't cover", "my sources do not cover"
# and their kin. The grounding contract explicitly endorses that phrasing for
# marking gap-fill, so flagging it would penalise exactly the behaviour the
# contract asks for. ``_GAP_FILL_RE`` below carves those out before matching.
_NARRATION_PATTERNS: tuple[str, ...] = (
    r"\bone (?:summary|guide|passage|source|reviewer|author) (?:says|notes|frames|calls|suggests|argues)\b",
    r"\b(?:these|the|my|our|its|this expert's) passages?\b",
    r"\bthe (?:sources|passages|materials|corpus) (?:disagree|agree|say|offer|provide|note|frame)\b",
    r"\bwhat(?:'s| is) missing\b",
    r"\baccording to (?:the|these) (?:passages|sources|materials)\b",
    r"\b(?:primary|secondary|tertiary) (?:summary|summaries|source material)\b",
    r"\bmost of (?:this|the material|what I have) is\b",
    r"\bthe (?:material|content) (?:I have|available|retrieved|provided)\b",
    r"\b(?:retrieved|provided|supplied) (?:passages|material|sources)\b",
    r"\bnothing (?:here|in these|in the passages)\b",
    r"\bthe corpus\b",
    r"\bsource \d+\b",
)
_NARRATION_RE = re.compile("|".join(_NARRATION_PATTERNS), re.IGNORECASE)

# Contract-sanctioned gap-fill marking, removed before narration matching so a
# compliant answer is never charged for complying.
_GAP_FILL_RE = re.compile(
    r"\bmy sources (?:don't|do not|doesn't|does not)\s+\w+[^.]*\.",
    re.IGNORECASE,
)

# Above one marker per sentence, on average, an answer is paying a per-sentence
# tax rather than attributing claims — every sentence is carrying attribution,
# and some are carrying two.
#
# Calibrated against real samples, and the calibration is worth recording because
# it is counter-intuitive: a *good* four-sentence answer citing three distinct
# claims runs 0.75, which is higher than some source tours score. Density alone
# does not separate a tour from a good answer, so this is a weak secondary
# signal — it catches only the pathological case. ``source_narration_hits`` is
# the discriminating metric; see ``test_citation_density_does_not_discriminate``.
CITATION_DENSITY_CEILING = 1.0

# How many narration hits to forgive. The contract allows one plain inline
# sentence about a gap when it changes what the asker should do, so a single
# hit is not a failure; a running commentary is.
NARRATION_TOLERANCE = 1


def sentence_count(answer_text: str) -> int:
    """Number of sentences, floored at 1 so density is never divided by zero."""
    return max(1, len([s for s in _SENTENCE_RE.findall(answer_text) if s.strip()]))


def citation_density(answer_text: str) -> float:
    """Citation markers per sentence.

    A proxy for defensive citing. This deliberately counts *markers*, not
    distinct passages: ``[2][5]`` on one claim is two markers, because the cost
    being measured is what the prose looks like to a reader, not how many
    sources were consulted.

    Note this is a shape metric, not a grounding one — a high value is a smell,
    never proof of a defect. Read it next to ``citation_validity``.
    """
    return round(len(_CITATION_RE.findall(answer_text)) / sentence_count(answer_text), 4)


def source_narration_hits(answer_text: str) -> list[str]:
    """Phrases where the answer talks about its own retrieval instead of the subject.

    Returns the matched substrings (lowercased) so a failing eval names what it
    caught rather than just scoring low — when this fires, the useful output is
    the phrase to go and look at.
    """
    stripped = _GAP_FILL_RE.sub(" ", answer_text)
    return [m.group(0).strip().lower() for m in _NARRATION_RE.finditer(stripped)]


def narration_penalty(hit_count: int, tolerance: int = NARRATION_TOLERANCE) -> float:
    """1.0 when an answer stays on the subject, decaying as narration accumulates.

    Linear past the tolerance and floored at zero: four hits beyond the allowance
    is already a source tour, and grading degrees of tour past that point tells
    us nothing we would act on.
    """
    excess = max(0, hit_count - tolerance)
    return round(max(0.0, 1.0 - excess / 4), 4)


def density_penalty(density: float, ceiling: float = CITATION_DENSITY_CEILING) -> float:
    """1.0 up to the ceiling, then decaying — over-citing is a smell, not a crime.

    Halves by roughly one ceiling-width above the limit rather than dropping to
    zero, because a dense answer can still be a good one.
    """
    if density <= ceiling:
        return 1.0
    return round(max(0.0, 1.0 - (density - ceiling) / (2 * ceiling)), 4)


# What the judge scores, and what each dimension is worth. `direct_answer` and
# `subject_organised` carry the most weight because they are what separates an
# answer from a literature review; `terms_defined` matters only for a non-expert
# asker and the judge is told to return 1.0 when it does not apply.
HELPFULNESS_WEIGHTS: dict[str, float] = {
    "direct_answer": 0.25,
    "subject_organised": 0.25,
    "actionable": 0.20,
    "terms_defined": 0.15,
    "no_corpus_meta": 0.15,
}


def helpfulness_score(dimensions: dict[str, float]) -> float:
    """Weighted mean of the judged dimensions, over whichever ones are present.

    Renormalises across the dimensions actually supplied so a partial judge
    response degrades to a score over what it did return, rather than silently
    scoring the missing dimensions as zero and reporting a failure that did not
    happen. Values are clamped to 0–1: the judge is instructed to stay in range,
    but a metric that trusts a model's arithmetic is a metric that will one day
    report 1.4.
    """
    present = {
        k: max(0.0, min(1.0, float(v)))
        for k, v in dimensions.items()
        if k in HELPFULNESS_WEIGHTS and isinstance(v, (int, float))
    }
    if not present:
        return 0.0
    total_weight = sum(HELPFULNESS_WEIGHTS[k] for k in present)
    weighted = sum(HELPFULNESS_WEIGHTS[k] * v for k, v in present.items())
    return round(weighted / total_weight, 4)


def answer_quality(
    dimensions: dict[str, float],
    answer_text: str,
) -> dict[str, float]:
    """Combine the judged dimensions with the two deterministic shape checks.

    The deterministic penalties multiply rather than average in: they detect a
    specific, known regression, and an answer exhibiting it should not be able
    to average its way back to a good score on the strength of being articulate.
    """
    judged = helpfulness_score(dimensions)
    density = citation_density(answer_text)
    hits = source_narration_hits(answer_text)
    d_pen = density_penalty(density)
    n_pen = narration_penalty(len(hits))
    return {
        "helpfulness": judged,
        "citation_density": density,
        "narration_hits": float(len(hits)),
        "density_penalty": d_pen,
        "narration_penalty": n_pen,
        "overall": round(judged * d_pen * n_pen, 4),
    }


# ---------------------------------------------------------------------------
# Screening — was the corpus selected, or merely collected?
# ---------------------------------------------------------------------------


def screening_precision_recall(predicted: list[bool], actual: list[bool]) -> dict[str, float | int]:
    """Precision, recall and F1 of the ``keep`` decision against human labels.

    ``predicted`` is what the validator decided, ``actual`` what a human said.
    Both are keep=True.

    The two errors are not symmetric and the pair of numbers is what says which
    one a rubric change traded away. Low precision means junk in the corpus, and
    the expert answers confidently from bad material. Low recall means good
    sources thrown away, which is invisible in the product — nobody sees the
    paper that was not kept — and is the failure a single accuracy number hides.
    """
    if len(predicted) != len(actual):
        raise ValueError("predicted and actual must be the same length")
    tp = sum(1 for p, a in zip(predicted, actual, strict=True) if p and a)
    fp = sum(1 for p, a in zip(predicted, actual, strict=True) if p and not a)
    fn = sum(1 for p, a in zip(predicted, actual, strict=True) if not p and a)
    tn = sum(1 for p, a in zip(predicted, actual, strict=True) if not p and not a)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    total = tp + fp + fn + tn
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round((tp + tn) / total, 4) if total else 0.0,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "n": total,
    }


def cohen_kappa(predicted: list[bool], actual: list[bool]) -> float:
    """Agreement above chance, in [-1, 1].

    The number to publish. Raw agreement flatters any rubric whose class balance
    matches the labeller's: a validator that kept everything would agree with a
    human 80% of the time on a set that is 80% keeps, while making no decisions
    at all. Kappa subtracts exactly that.

    Returns 0.0 when chance agreement is total — every label identical on both
    sides — since "above chance" is then undefined and claiming perfect
    agreement would be the flattering reading.
    """
    if len(predicted) != len(actual):
        raise ValueError("predicted and actual must be the same length")
    n = len(predicted)
    if n == 0:
        return 0.0
    observed = sum(1 for p, a in zip(predicted, actual, strict=True) if p == a) / n
    p_keep = sum(predicted) / n
    a_keep = sum(actual) / n
    expected = p_keep * a_keep + (1 - p_keep) * (1 - a_keep)
    if expected >= 1.0:
        return 0.0
    return round((observed - expected) / (1 - expected), 4)


def concept_jaccard(predicted: list[str], actual: list[str]) -> float:
    """Overlap between the concepts the validator tagged and the ones a human did.

    Coverage-driven gap-filling and the whole discovery loop key on these tags,
    so a validator that scores a source correctly but mis-tags what it covers
    sends the next round looking for the wrong thing. Two empty sets agree.
    """
    left = {c.casefold().strip() for c in predicted if c and c.strip()}
    right = {c.casefold().strip() for c in actual if c and c.strip()}
    if not left and not right:
        return 1.0
    union = left | right
    return round(len(left & right) / len(union), 4) if union else 1.0


def spearman(xs: list[float], ys: list[float]) -> float:
    """Rank correlation, with tied values given their average rank.

    Used between a triage score and a human keep/drop label (1/0): it asks
    whether the candidates people want to keep are the ones triage ranks higher,
    which is the only thing a score that orders a fetch queue has to get right.
    0.0 when either side is constant, where the correlation is undefined.
    """
    if len(xs) != len(ys):
        raise ValueError("spearman: inputs must be the same length")
    n = len(xs)
    if n < 2:
        return 0.0

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: values[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and values[order[j + 1]] == values[order[i]]:
                j += 1
            average = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = average
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mean_x, mean_y = sum(rx) / n, sum(ry) / n
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry, strict=True))
    var_x = sum((a - mean_x) ** 2 for a in rx)
    var_y = sum((b - mean_y) ** 2 for b in ry)
    if var_x == 0 or var_y == 0:
        return 0.0
    return round(cov / (var_x * var_y) ** 0.5, 4)
