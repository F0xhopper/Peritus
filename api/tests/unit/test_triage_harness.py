"""The triage harness: sampling for labelling, and the report it computes."""

from unittest.mock import patch

import pytest

from peritus.eval import triage as harness
from peritus.eval.metrics import spearman
from peritus.sources.triage import TriagedCandidate


def test_spearman_handles_ties_and_constants():
    assert spearman([1, 2, 3], [0, 1, 1]) == pytest.approx(0.866, abs=1e-3)
    assert spearman([1, 2, 3], [3, 2, 1]) == -1.0
    assert spearman([1, 1, 1], [0, 1, 0]) == 0.0


def test_the_sample_over_represents_the_band_and_is_deterministic():
    screenings = [{"triage_score": float(i % 10), "round": 0, "url": f"u{i}"} for i in range(300)]
    one = harness.sample_for_labelling(screenings, size=30, seed=1)
    two = harness.sample_for_labelling(screenings, size=30, seed=1)
    assert one == two
    in_band = sum(1 for s in one if 3.0 <= s["triage_score"] < 8.0)
    assert in_band == 20


@pytest.mark.asyncio
async def test_the_report_compares_the_current_code_with_what_the_build_fetched(tmp_path):
    golden = harness.TriageGolden(
        topic="Thomism",
        key_concepts=[],
        must_have_titles=[],
        job_id=53,
        candidates=[
            harness.LabelledCandidate(
                "https://a", "Summa", "web", ledger_outcome="fetched", keep=True
            ),
            harness.LabelledCandidate(
                "https://b", "Tracie Thoms", "wikipedia", ledger_outcome="fetched", keep=False
            ),
            harness.LabelledCandidate(
                "https://c", "Aeterni Patris", "web", ledger_outcome="below_floor", keep=True
            ),
            harness.LabelledCandidate("https://d", "Unlabelled", "web"),
        ],
    )
    path = tmp_path / "golden.json"
    golden.dump(path)

    scores = {"Summa": 9.0, "Tracie Thoms": 0.0, "Aeterni Patris": 7.0}

    async def _triage(topic, concepts, must, candidates):
        return [
            TriagedCandidate(c, scores[c.title], model_score=scores[c.title]) for c in candidates
        ]

    with patch.object(harness, "triage_candidates", _triage):
        report = await harness.run(path, floor=6.0)

    assert report.labelled == 3
    assert report.now["precision"] == 1.0 and report.now["recall"] == 1.0
    assert report.at_build["precision"] == 0.5
    assert report.spearman_score_vs_keep > 0.8
    assert report.labelled_drops_fetched_below_3 == []
    assert "keep rate by score band" in report.render()
