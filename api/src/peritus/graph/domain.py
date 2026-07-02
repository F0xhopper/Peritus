from dataclasses import dataclass, field
from enum import StrEnum


class NodeType(StrEnum):
    CONCEPT = "concept"
    CLAIM = "claim"


class EdgeType(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    BUILDS_ON = "builds_on"
    DEFINES = "defines"
    EXEMPLIFIES = "exemplifies"
    CITES = "cites"


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
    weight: float = 1.0
    properties: dict = field(default_factory=dict)
