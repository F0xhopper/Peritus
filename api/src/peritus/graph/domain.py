"""The graph vocabulary, and the rules that make it mean something.

Five relationship types, and each one is only well-formed between particular
kinds of node. That constraint is the point: `contradicts` between two
*concepts* is a category error — two concepts can differ, only two propositions
can be incompatible — and roughly half of every contradiction the old six-type
vocabulary produced was exactly that. So the endpoint rule is data, not prose,
and :func:`edge_is_valid` is applied at ingest rather than trusted to the model.

  contradicts  claim → claim    the two propositions cannot both be true
  supports     claim → claim    a second source asserts, or evidences, the same
  qualifies    claim → claim    true, but only under a stated condition
  about        claim → concept  the concept a claim is a claim about
  part_of      concept → concept  the one hierarchy edge between concepts

`contradicts` and `qualifies` each carry a required property — the point in
dispute, the condition that narrows — because "these two disagree" without
saying about what is not something a reader can check.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class NodeType(StrEnum):
    CONCEPT = "concept"
    CLAIM = "claim"


class EdgeType(StrEnum):
    CONTRADICTS = "contradicts"
    SUPPORTS = "supports"
    QUALIFIES = "qualifies"
    ABOUT = "about"
    PART_OF = "part_of"


#: Relations between two propositions. These are the edges the product reports
#: on, and the only ones the reconciliation pass produces.
CLAIM_RELATIONS: frozenset[EdgeType] = frozenset({
    EdgeType.CONTRADICTS, EdgeType.SUPPORTS, EdgeType.QUALIFIES,
})

#: The (from, to) node types each edge type is well-formed between.
EDGE_ENDPOINTS: dict[EdgeType, tuple[NodeType, NodeType]] = {
    EdgeType.CONTRADICTS: (NodeType.CLAIM, NodeType.CLAIM),
    EdgeType.SUPPORTS: (NodeType.CLAIM, NodeType.CLAIM),
    EdgeType.QUALIFIES: (NodeType.CLAIM, NodeType.CLAIM),
    EdgeType.ABOUT: (NodeType.CLAIM, NodeType.CONCEPT),
    EdgeType.PART_OF: (NodeType.CONCEPT, NodeType.CONCEPT),
}

#: The property an edge type is meaningless without, and the key it is stored
#: under in ``expert_edges.properties``.
EDGE_REQUIRED_PROPERTY: dict[EdgeType, str] = {
    EdgeType.CONTRADICTS: "point",
    EdgeType.QUALIFIES: "condition",
}

#: Node property vocabulary. The old schema declared these as enums in the tool
#: definition and enforced nothing, so `content_type` filled up with edge type
#: names; anything outside the set is dropped at ingest.
CONTENT_TYPES: frozenset[str] = frozenset({
    "definition", "theorem", "example", "argument", "counterargument",
})


def coerce_node_type(raw: object) -> NodeType | None:
    """The NodeType this value names, or None if it names nothing."""
    try:
        return NodeType(str(raw).strip().lower())
    except ValueError:
        return None


def coerce_edge_type(raw: object) -> EdgeType | None:
    try:
        return EdgeType(str(raw).strip().lower())
    except ValueError:
        return None


def edge_is_valid(
    edge_type: EdgeType, from_type: NodeType, to_type: NodeType
) -> bool:
    """Whether this relation is well-formed between these two kinds of node."""
    return EDGE_ENDPOINTS[edge_type] == (from_type, to_type)


def edge_property(edge_type: EdgeType, properties: dict | None) -> str | None:
    """The stated point or condition for an edge, if its type requires one."""
    key = EDGE_REQUIRED_PROPERTY.get(edge_type)
    if key is None or not properties:
        return None
    value = properties.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


@dataclass
class Node:
    id: int
    expert_id: int
    node_type: NodeType
    label: str
    description: str | None
    properties: dict = field(default_factory=dict)
    chunk_ids: list[int] = field(default_factory=list)


@dataclass
class Edge:
    id: int
    expert_id: int
    from_node_id: int
    to_node_id: int
    edge_type: EdgeType
    #: Distinct sources behind the two endpoints' passages. Counted from the
    #: corpus, not asserted by a model — the old `weight` was a number the model
    #: invented, sat above 0.8 three quarters of the time, and ordered nothing.
    evidence: int = 0
    properties: dict = field(default_factory=dict)
