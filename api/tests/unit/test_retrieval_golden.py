"""Retrieval golden-set scoring (R12) — pure, no database, no model."""

from peritus.eval.retrieval import GoldItem, same_passage, score

_GOLD = (
    "Aquinas holds that the ultimate end of man is beatitude, which consists in the "
    "contemplation of God. Created goods cannot satisfy the will, because the will's "
    "object is the universal good. Happiness in this life is therefore imperfect."
)


def _item(text=_GOLD, url="https://example.org/st"):
    return GoldItem("What is the end of man?", 1, 1, url, "ST", text)


def test_same_passage_survives_rechunking():
    first_half = _GOLD[: len(_GOLD) // 2]
    assert same_passage(_GOLD, first_half + " and something the rebuild appended.")
    assert same_passage(first_half, _GOLD)
    assert not same_passage(_GOLD, "Varroa mites feed on the fat body of honey bee larvae.")


def test_score_reports_recall_mrr_and_source_recall():
    items = [_item(), _item(url="https://example.org/other"), _item(url=None)]
    retrieved = [
        [("unrelated text about bees and mites in winter colonies", None), (_GOLD, "https://example.org/st")],
        [("unrelated text about bees and mites in winter colonies", "https://example.org/other")],
        [],
    ]
    report = score(items, retrieved, k=10)
    assert [r.hit_rank for r in report.per_question] == [2, None, None]
    assert report.recall_at_k == round(1 / 3, 4)
    assert report.mrr == round(0.5 / 3, 4)
    # The second item found its source, not its passage.
    assert [r.source_hit for r in report.per_question] == [True, True, False]


def test_score_respects_k():
    report = score([_item()], [[("noise words " * 5, None), (_GOLD, None)]], k=1)
    assert report.recall_at_k == 0.0
