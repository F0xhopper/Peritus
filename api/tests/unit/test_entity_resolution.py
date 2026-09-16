"""Entity resolution rules (R5) — pure, no database."""

from peritus.graph.resolution import (
    RESOLVE_THRESHOLD,
    RESOLVE_THRESHOLD_SAME_HEAD,
    canonical_label,
    canonical_merge_plan,
    pair_threshold,
)


def _concept(node_id, label, chunks=1, node_type="concept"):
    return {"id": node_id, "label": label, "node_type": node_type, "chunk_ids": list(range(chunks))}


def test_canonical_label_flattens_inflection_articles_and_punctuation():
    assert canonical_label("Varroa mites")[0] == "varroa mite"
    assert canonical_label("The Varroa-mite.")[0] == "varroa mite"
    assert canonical_label("Honey bee colonies")[0] == "honey bee colony"
    assert canonical_label("Boxes")[0] == "box"
    # Not plurals.
    assert canonical_label("Deformed wing virus")[0] == "deformed wing virus"
    assert canonical_label("Nosema ceranae analysis")[0] == "nosema ceranae analysis"
    assert canonical_label("Stoic ethics")[0] == "stoic ethics"


def test_acronym_parentheticals_become_aliases_either_way_round():
    assert canonical_label("Deformed Wing Virus (DWV)") == ("deformed wing virus", "dwv")
    assert canonical_label("DWV (Deformed Wing Virus)") == ("deformed wing virus", "dwv")
    # A parenthetical that is not an acronym is part of the label.
    assert canonical_label("Summa (first part)")[1] is None
    # Nor is a bracketed qualifier that does not abbreviate the label.
    assert canonical_label("Vision Domain Evaluation (CIFAR10)") == (
        "vision domain evaluation (cifar10)".replace("(", "").replace(")", ""),
        None,
    )
    assert canonical_label("Long non-coding RNAs (lncRNAs)") == ("long non coding rna", "lncrna")


def test_the_varroa_and_dwv_families_merge():
    nodes = [
        _concept(1, "Varroa destructor", 59),
        _concept(2, "Varroa destructor mite", 11),
        _concept(3, "Varroa destructor mites", 9),
        _concept(4, "Varroa mite", 25),
        _concept(5, "Varroa mites", 15),
        _concept(6, "Deformed Wing Virus (DWV)", 8),
        _concept(7, "DWV (Deformed Wing Virus)", 3),
        _concept(8, "DWV", 2),
    ]
    plan = {
        keep["id"]: sorted(d["id"] for d in drops) for keep, drops in canonical_merge_plan(nodes)
    }
    # The best-evidenced spelling survives.
    assert plan == {2: [3], 4: [5], 6: [7, 8]}


def test_claims_are_never_canonicalised():
    nodes = [
        _concept(1, "Varroa suppresses immunity", node_type="claim"),
        _concept(2, "Varroa suppress immunity", node_type="claim"),
    ]
    assert canonical_merge_plan(nodes) == []


def test_pair_threshold_is_lower_for_a_shared_head_noun_and_absent_across_types():
    mite = _concept(1, "Varroa mite")
    assert (
        pair_threshold(mite, _concept(2, "Varroa destructor mites")) == RESOLVE_THRESHOLD_SAME_HEAD
    )
    assert pair_threshold(mite, _concept(3, "Varroa destructor")) == RESOLVE_THRESHOLD
    assert pair_threshold(mite, _concept(4, "Varroa mite", node_type="claim")) is None
