from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class NodeType(str, Enum):
    ENTITY = "ENTITY"
    CONCEPT = "CONCEPT"
    EVENT = "EVENT"
    PREFERENCE = "PREFERENCE"
    BELIEF = "BELIEF"
    SESSION = "SESSION"
    PROCEDURE = "PROCEDURE"  # step-by-step process, workflow, skill, or algorithm
    SESSION_SUMMARY = "SESSION_SUMMARY"  # compressed episodic summary of a session
    WORKING = "WORKING"      # ephemeral session-scoped fact; auto-archived after consolidation if not reinforced


class EdgeType(str, Enum):
    # Explicit semantic edges
    WORKS_ON = "WORKS_ON"
    BACKGROUND_IN = "BACKGROUND_IN"
    INTERESTED_IN = "INTERESTED_IN"
    CAUSED = "CAUSED"
    CONTRADICTS = "CONTRADICTS"
    PART_OF = "PART_OF"
    INSTANCE_OF = "INSTANCE_OF"
    TRIGGERED = "TRIGGERED"
    PREFERS = "PREFERS"
    USES = "USES"
    RELATED_TO = "RELATED_TO"
    # Provenance edges (bi-temporal conflict resolution)
    SUPERSEDES = "SUPERSEDES"   # old value is wrong/replaced; old node archived
    REFINES = "REFINES"         # old value is still true; new value adds specificity
    # Implicit co-occurrence edges
    CO_OCCURS = "CO_OCCURS"
    # Episodic edges (SessionSummary layer)
    TEMPORALLY_AFTER = "TEMPORALLY_AFTER"    # summary → previous summary (chronological chain)
    TEMPORALLY_BEFORE = "TEMPORALLY_BEFORE"  # summary → next summary
    MENTIONS = "MENTIONS"                    # summary → entity/concept it references
    SUPPORTS_FACT = "SUPPORTS_FACT"          # summary → semantic node it grounds


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())[:8]


ZONE_ACTIVE   = "active"
ZONE_ARCHIVED = "archived"
ZONE_EXPIRED  = "expired"


@dataclass
class Node:
    id: str
    type: NodeType
    content: str
    created_at: str
    last_activated: str
    activation_count: int = 0
    salience: float = 0.0
    is_core: bool = False
    tags: list[str] = field(default_factory=list)
    zone: str = ZONE_ACTIVE          # active | archived | expired
    superseded_at: str | None = None # ISO timestamp when this node was superseded
    metadata: dict = field(default_factory=dict)  # arbitrary structured data
    distinct_sessions: int = 0       # how many distinct sessions have reinforced this node

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "content": self.content,
            "created_at": self.created_at,
            "last_activated": self.last_activated,
            "activation_count": self.activation_count,
            "salience": round(self.salience, 4),
            "is_core": self.is_core,
            "tags": self.tags,
            "zone": self.zone,
            "superseded_at": self.superseded_at,
            "metadata": self.metadata,
            "distinct_sessions": self.distinct_sessions,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Node:
        return cls(
            id=d["id"],
            type=NodeType(d["type"]),
            content=d["content"],
            created_at=d["created_at"],
            last_activated=d["last_activated"],
            activation_count=d.get("activation_count", 0),
            salience=d.get("salience", 0.0),
            is_core=d.get("is_core", False),
            tags=d.get("tags", []),
            zone=d.get("zone", ZONE_ACTIVE),
            superseded_at=d.get("superseded_at"),
            metadata=d.get("metadata", {}),
            distinct_sessions=d.get("distinct_sessions", 0),
        )


@dataclass
class Edge:
    id: str
    source_id: str
    target_id: str
    type: EdgeType
    weight: float
    created_at: str
    last_activated: str
    activation_count: int = 0
    decay_rate: float = 0.02

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "type": self.type.value,
            "weight": round(self.weight, 4),
            "created_at": self.created_at,
            "last_activated": self.last_activated,
            "activation_count": self.activation_count,
            "decay_rate": self.decay_rate,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Edge:
        return cls(
            id=d["id"],
            source_id=d["source_id"],
            target_id=d["target_id"],
            type=EdgeType(d["type"]),
            weight=d["weight"],
            created_at=d["created_at"],
            last_activated=d["last_activated"],
            activation_count=d.get("activation_count", 0),
            decay_rate=d.get("decay_rate", 0.02),
        )
