"""Unit tests for the pure evaluation metrics and citation parsing."""

from peritus.chat.grounding import Passage, parse_cited_indices, used_citation_labels
from peritus.eval import metrics


def _passage(i: int, source_id: int = 0) -> Passage:
    return Passage(index=i, citation=f"Src {i}", source_id=source_id, text=f"text {i}")


def test_parse_cited_indices_only_valid():
    text = "Claim one [1]. Claim two [3][5]. Bogus [99]."
    assert parse_cited_indices(text, num_passages=5) == {1, 3, 5}


def test_used_citation_labels_filters_to_cited():
    passages = [_passage(1), _passage(2), _passage(3)]
    labels = used_citation_labels(passages, cited={1, 3})
    assert labels == ["Src 1", "Src 3"]


def test_recall_at_k():
    assert metrics.recall_at_k([5, 9, 2, 7], gold_chunk_ids=[2, 7], k=4) == 1.0
    assert metrics.recall_at_k([5, 9, 2, 7], gold_chunk_ids=[2, 7], k=2) == 0.0
    assert metrics.recall_at_k([5, 2], gold_chunk_ids=[2, 7], k=2) == 0.5
    assert metrics.recall_at_k([], gold_chunk_ids=[], k=5) == 1.0


def test_citation_validity():
    assert metrics.citation_validity("Grounded [1] and [2].", num_passages=2) == 1.0
    assert metrics.citation_validity("Half [1] bad [9].", num_passages=2) == 0.5
    assert metrics.citation_validity("No citations here.", num_passages=2) == 0.0


def test_cited_supporting_sources():
    text = "Answer [1] and [2]."
    passage_source_ids = {1: 12, 2: 99}
    # gold source 12 is cited (via passage 1); recall = 1.0
    assert metrics.cited_supporting_sources(text, passage_source_ids, [12]) == 1.0
    # gold source 50 is never cited; recall = 0.0
    assert metrics.cited_supporting_sources(text, passage_source_ids, [50]) == 0.0


def test_looks_like_refusal():
    assert metrics.looks_like_refusal("The passages do not cover this topic.")
    assert metrics.looks_like_refusal("I don't have enough information to answer.")
    assert not metrics.looks_like_refusal("The dichotomy of control [1] means...")


def test_aggregate():
    assert metrics.aggregate([1.0, 0.0, 0.5]) == 0.5
    assert metrics.aggregate([]) == 0.0


# --- helpfulness metrics ---------------------------------------------------
#
# The excerpt below is condensed from the answer that prompted the overhaul: an
# investing expert asked for beginner tips that reviewed its own retrieval set
# instead of answering. It is the regression these metrics exist to catch.
_SOURCE_TOUR = (
    "Let me walk through what the passages actually offer here. One summary "
    "frames Graham's advice as a middle path [1]. One guide calls diversification "
    "the only free lunch in finance [6]. What's missing from these passages: "
    "there is nothing on the efficient market hypothesis. Most of this is "
    "secondary summary rather than the primary texts [1]."
)

_GOOD_ANSWER = (
    "Buy shares only when they trade well below what the business is worth, and "
    "keep enough spread across holdings that any single mistake is survivable. "
    "That gap between price and worth is what Graham called a margin of safety — "
    "the buffer that means a flawed estimate still need not lose you money [2]. "
    "In practice he screened on a trailing price-to-earnings ratio under 15 [1]. "
    "Diversification does the complementary job, reducing the risk attached to "
    "any one company, though it cannot protect against a market-wide fall [6]."
)


def test_sentence_count_never_zero():
    assert metrics.sentence_count("") == 1
    assert metrics.sentence_count("One. Two. Three.") == 3
    assert metrics.sentence_count("No terminator") == 1


def test_citation_density_counts_markers_not_passages():
    # Two markers on one sentence is density 2.0 — the reader sees two.
    assert metrics.citation_density("A claim [2][5].") == 2.0
    assert metrics.citation_density("No citations at all.") == 0.0


def test_citation_density_does_not_discriminate():
    """Density is a weak signal, and this pins that down so nobody re-derives it.

    Both samples sit under the ceiling, and the *good* answer scores higher than
    the tour — citing three real claims in four sentences is denser than a tour
    padded with uncited commentary about its own sources. Density catches only
    the pathological case; narration is what actually separates the two.
    """
    assert metrics.citation_density(_GOOD_ANSWER) == 0.75
    assert metrics.citation_density(_SOURCE_TOUR) == 0.6
    assert metrics.citation_density(_GOOD_ANSWER) > metrics.citation_density(_SOURCE_TOUR)
    assert metrics.density_penalty(metrics.citation_density(_GOOD_ANSWER)) == 1.0
    assert metrics.density_penalty(metrics.citation_density(_SOURCE_TOUR)) == 1.0


def test_citation_density_catches_the_per_sentence_tax():
    """What the ceiling is actually for: attribution welded to every sentence."""
    tax = "A claim [1]. Another [2]. A third [3][4]. A fourth [5]."
    assert metrics.citation_density(tax) > metrics.CITATION_DENSITY_CEILING
    assert metrics.density_penalty(metrics.citation_density(tax)) < 1.0


def test_source_narration_detects_the_tour():
    hits = metrics.source_narration_hits(_SOURCE_TOUR)
    assert len(hits) >= 4
    assert any("what's missing" in h for h in hits)
    assert any("the passages" in h for h in hits)


def test_source_narration_clean_on_a_good_answer():
    assert metrics.source_narration_hits(_GOOD_ANSWER) == []


def test_gap_fill_marking_is_not_penalised():
    """The contract *requires* this phrasing; flagging it would punish compliance."""
    text = (
        "Compounding means returns earning their own returns [1]. My sources "
        "don't cover index funds, but in general they track a whole market "
        "rather than picking shares."
    )
    assert metrics.source_narration_hits(text) == []


def test_narration_penalty_tolerates_one_hit():
    assert metrics.narration_penalty(0) == 1.0
    assert metrics.narration_penalty(1) == 1.0  # one inline gap sentence is allowed
    assert metrics.narration_penalty(3) == 0.5
    assert metrics.narration_penalty(20) == 0.0


def test_density_penalty_only_bites_above_ceiling():
    assert metrics.density_penalty(0.0) == 1.0
    assert metrics.density_penalty(metrics.CITATION_DENSITY_CEILING) == 1.0
    assert metrics.density_penalty(1.5) < 1.0
    assert metrics.density_penalty(10.0) == 0.0


def test_helpfulness_score_weights_and_clamps():
    perfect = dict.fromkeys(metrics.HELPFULNESS_WEIGHTS, 1.0)
    assert metrics.helpfulness_score(perfect) == 1.0
    assert metrics.helpfulness_score(dict.fromkeys(metrics.HELPFULNESS_WEIGHTS, 0.0)) == 0.0
    # Out-of-range judge output must not escape 0–1.
    assert metrics.helpfulness_score({"direct_answer": 4.0}) == 1.0
    assert metrics.helpfulness_score({"direct_answer": -2.0}) == 0.0


def test_helpfulness_score_renormalises_over_present_dimensions():
    """A partial judge response scores over what it returned, not over zeros."""
    assert metrics.helpfulness_score({"direct_answer": 1.0, "actionable": 1.0}) == 1.0
    assert metrics.helpfulness_score({"direct_answer": 1.0, "actionable": 0.0}) == round(
        0.25 / 0.45, 4
    )
    assert metrics.helpfulness_score({}) == 0.0
    assert metrics.helpfulness_score({"unknown_dimension": 1.0}) == 0.0


def test_answer_quality_penalties_compound_against_the_tour():
    judged = dict.fromkeys(metrics.HELPFULNESS_WEIGHTS, 1.0)
    # Identical judged dimensions; only the prose differs. The deterministic
    # checks must still separate them, so an articulate tour cannot score well.
    tour = metrics.answer_quality(judged, _SOURCE_TOUR)
    good = metrics.answer_quality(judged, _GOOD_ANSWER)
    assert good["overall"] == 1.0
    assert tour["overall"] < 0.5
    assert tour["narration_hits"] >= 4


def test_answer_quality_without_judge_still_reports_shape():
    """A judge outage must leave the deterministic numbers intact."""
    shape = metrics.answer_quality({}, _SOURCE_TOUR)
    assert shape["helpfulness"] == 0.0
    assert shape["narration_hits"] >= 4
    assert shape["citation_density"] > 0
