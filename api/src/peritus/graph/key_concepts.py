"""Which line of the syllabus each concept node belongs to.

The expert's map (docs/plans/expert-brain.md) draws the key concepts as a fixed
ring and pulls every concept node toward the one it belongs to. Nothing recorded
that join: a key concept is a line of the plan ("Being, essence, and existence
(act/potency)") and a node is what extraction found in a passage ("Divine
simplicity"), and not one label in five experts matched.

So the join is made by embedding. Every node already carries one (label plus
description, :func:`peritus.graph.repository.node_embedding_text`); each key
concept is embedded once with the same model, and a node takes its nearest key
concept above :data:`KEY_CONCEPT_FLOOR`. Below it the node is unassigned, which
is honest: some concepts belong to the topic and to no line of its syllabus.

**The floor was chosen from a hand-check, not from a textbook.** On 2026-09-18
fifty assignments on Thomism and fifty on beekeeping were read against their
key concepts (expert-brain.md, "Phase 0 — measured"). 0.40 gave 41/50 and 38/50
right, counting an unassigned node as right when no line of the syllabus fits
it; 0.35 and 0.45 were both worse on Thomism and no better on beekeeping. Do
not move it without repeating that check — the similarities are stored
(``key_concept_sim``) so a new floor needs no re-embedding.

Where two key concepts are within :data:`TIEBREAK_MARGIN` of each other, the one
the node's own sources *set out* wins: the validator read those sources against
the syllabus, which is better evidence than a hundredth of cosine.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from peritus.core.logging import get_logger

logger = get_logger(__name__)

#: Cosine similarity below which a node belongs to no key concept.
KEY_CONCEPT_FLOOR = 0.40
#: Two key concepts this close are a tie, broken by the node's sources' tags.
TIEBREAK_MARGIN = 0.02

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


def choose_key_concept(
    sims: list[float],
    sets_out: Iterable[int] = (),
    floor: float = KEY_CONCEPT_FLOOR,
    margin: float = TIEBREAK_MARGIN,
) -> tuple[int | None, float | None]:
    """``(key concept index or None, its similarity)`` for one node.

    ``sims`` is the node's cosine similarity to each key concept, in the
    expert's order; ``sets_out`` the indexes its sources were judged to set out.
    The similarity returned is the best one even when the node is unassigned,
    so the stored value says how far below the floor it fell.
    """
    if not sims:
        return None, None
    order = sorted(range(len(sims)), key=lambda i: (-sims[i], i))
    best = order[0]
    if sims[best] < floor:
        return None, sims[best]
    preferred = set(sets_out)
    close = [i for i in order if sims[best] - sims[i] <= margin and sims[i] >= floor]
    for index in close:
        if index in preferred:
            return index, sims[index]
    return best, sims[best]


@dataclass(frozen=True)
class AssignStats:
    nodes: int
    assigned: int

    @property
    def unassigned(self) -> int:
        return self.nodes - self.assigned


async def assign_key_concepts(
    graph_repo: KeyConceptStore,
    expert_id: int,
    key_concepts: list[str],
    embedder: Embedder,
) -> AssignStats:
    """Embed the key concepts, assign every concept node, and store the result.

    At most one embedding call per key concept (fourteen for a Pro plan), once
    per graph. Idempotent: every concept node is rewritten, so running it again
    after a source upload assigns the new nodes and leaves the rest as they were.
    """
    if not key_concepts:
        await graph_repo.write_key_concepts(expert_id, [])
        return AssignStats(nodes=0, assigned=0)
    vectors = await embedder(list(key_concepts))
    rows = await graph_repo.key_concept_similarities(expert_id, vectors, key_concepts)
    assignments = []
    for node_id, sims, sets_out in rows:
        index, sim = choose_key_concept(sims, sets_out)
        assignments.append((node_id, index, sim))
    await graph_repo.write_key_concepts(expert_id, assignments)
    assigned = sum(1 for _, index, _ in assignments if index is not None)
    logger.info(
        "Key concepts for expert %d: %d of %d concept nodes assigned (floor %.2f)",
        expert_id,
        assigned,
        len(assignments),
        KEY_CONCEPT_FLOOR,
    )
    return AssignStats(nodes=len(assignments), assigned=assigned)


class KeyConceptStore(Protocol):
    """What :func:`assign_key_concepts` needs from the graph repository."""

    async def key_concept_similarities(
        self, expert_id: int, vectors: list[list[float]], key_concepts: list[str]
    ) -> list[tuple[int, list[float], set[int]]]: ...

    async def write_key_concepts(
        self, expert_id: int, assignments: list[tuple[int, int | None, float | None]]
    ) -> None: ...
