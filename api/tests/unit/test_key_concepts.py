"""Placing concept nodes in the syllabus (docs/plans/expert-brain.md, phase 0)."""

import pytest

from peritus.graph.key_concepts import (
    KEY_CONCEPT_FLOOR,
    TIEBREAK_MARGIN,
    assign_key_concepts,
    choose_key_concept,
)


def test_the_nearest_key_concept_above_the_floor_wins():
    assert choose_key_concept([0.41, 0.62, 0.50]) == (1, 0.62)


def test_below_the_floor_a_node_is_unassigned_but_keeps_its_best_similarity():
    index, sim = choose_key_concept([0.21, KEY_CONCEPT_FLOOR - 0.01])
    assert index is None
    assert sim == pytest.approx(KEY_CONCEPT_FLOOR - 0.01)


def test_the_floor_itself_is_assigned():
    assert choose_key_concept([KEY_CONCEPT_FLOOR]) == (0, KEY_CONCEPT_FLOOR)


def test_a_near_tie_goes_to_the_key_concept_the_nodes_sources_set_out():
    sims = [0.55, 0.55 - TIEBREAK_MARGIN / 2]
    assert choose_key_concept(sims)[0] == 0
    assert choose_key_concept(sims, sets_out={1})[0] == 1


def test_a_clear_winner_is_not_overridden_by_the_sources_tags():
    assert choose_key_concept([0.60, 0.50], sets_out={1})[0] == 0


def test_the_tiebreak_never_picks_a_key_concept_under_the_floor():
    sims = [KEY_CONCEPT_FLOOR + 0.005, KEY_CONCEPT_FLOOR - 0.005]
    assert choose_key_concept(sims, sets_out={1})[0] == 0


def test_no_key_concepts_means_no_assignment():
    assert choose_key_concept([]) == (None, None)


class _Store:
    def __init__(self, rows):
        self.rows = rows
        self.written = None
        self.asked_for = None

    async def key_concept_similarities(self, expert_id, vectors, key_concepts):
        self.asked_for = (expert_id, len(vectors), key_concepts)
        return self.rows

    async def write_key_concepts(self, expert_id, assignments):
        self.written = (expert_id, assignments)


@pytest.mark.asyncio
async def test_assignment_embeds_each_key_concept_once_and_writes_every_node():
    embedded: list[list[str]] = []

    async def embedder(texts):
        embedded.append(texts)
        return [[1.0, 0.0] for _ in texts]

    store = _Store([(10, [0.7, 0.2], set()), (11, [0.1, 0.2], set())])
    stats = await assign_key_concepts(store, 5, ["virtue", "fate"], embedder)

    assert embedded == [["virtue", "fate"]]
    assert store.asked_for == (5, 2, ["virtue", "fate"])
    assert store.written == (5, [(10, 0, 0.7), (11, None, 0.2)])
    assert (stats.nodes, stats.assigned, stats.unassigned) == (2, 1, 1)


@pytest.mark.asyncio
async def test_a_plan_with_no_key_concepts_clears_every_assignment_without_embedding():
    async def embedder(texts):  # pragma: no cover - must not be called
        raise AssertionError("embedded with nothing to embed")

    store = _Store([])
    stats = await assign_key_concepts(store, 5, [], embedder)
    assert store.written == (5, [])
    assert stats.nodes == 0
