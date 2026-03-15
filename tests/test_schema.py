"""Tests for schema.py — Node/Edge dataclasses and helpers."""
import pytest
from dory.schema import (
    Node, Edge, NodeType, EdgeType,
    now_iso, new_id,
    ZONE_ACTIVE, ZONE_ARCHIVED, ZONE_EXPIRED,
)


# --- Helpers ---

def test_new_id_is_unique():
    ids = {new_id() for _ in range(100)}
    assert len(ids) == 100


def test_new_id_is_string():
    assert isinstance(new_id(), str)


def test_now_iso_is_string():
    ts = now_iso()
    assert isinstance(ts, str)
    assert "T" in ts  # ISO 8601 format


def test_now_iso_is_utc():
    ts = now_iso()
    assert ts.endswith("+00:00")


# --- NodeType enum ---

def test_node_type_values():
    assert NodeType.ENTITY.value == "ENTITY"
    assert NodeType.CONCEPT.value == "CONCEPT"
    assert NodeType.EVENT.value == "EVENT"
    assert NodeType.PREFERENCE.value == "PREFERENCE"
    assert NodeType.BELIEF.value == "BELIEF"
    assert NodeType.SESSION.value == "SESSION"


def test_node_type_from_string():
    assert NodeType("ENTITY") is NodeType.ENTITY


# --- EdgeType enum ---

def test_edge_type_covers_semantic_types():
    for name in ("WORKS_ON", "USES", "RELATED_TO", "PART_OF", "SUPERSEDES", "CO_OCCURS"):
        assert EdgeType(name) is not None


# --- Node roundtrip ---

def _make_node(**kwargs):
    defaults = dict(
        id="abc12345",
        type=NodeType.CONCEPT,
        content="test content",
        created_at=now_iso(),
        last_activated=now_iso(),
        activation_count=3,
        salience=0.42,
        is_core=True,
        tags=["a", "b"],
        zone=ZONE_ACTIVE,
        superseded_at=None,
    )
    defaults.update(kwargs)
    return Node(**defaults)


def test_node_to_dict_roundtrip():
    node = _make_node()
    d = node.to_dict()
    restored = Node.from_dict(d)

    assert restored.id == node.id
    assert restored.type == node.type
    assert restored.content == node.content
    assert restored.activation_count == node.activation_count
    assert abs(restored.salience - node.salience) < 0.001  # rounded to 4dp
    assert restored.is_core == node.is_core
    assert restored.tags == node.tags
    assert restored.zone == node.zone
    assert restored.superseded_at == node.superseded_at


def test_node_to_dict_type_is_string():
    node = _make_node()
    assert node.to_dict()["type"] == "CONCEPT"


def test_node_from_dict_defaults():
    """from_dict should handle missing optional fields gracefully."""
    minimal = {
        "id": "x",
        "type": "ENTITY",
        "content": "foo",
        "created_at": now_iso(),
        "last_activated": now_iso(),
    }
    node = Node.from_dict(minimal)
    assert node.activation_count == 0
    assert node.salience == 0.0
    assert node.is_core is False
    assert node.tags == []
    assert node.zone == ZONE_ACTIVE
    assert node.superseded_at is None


def test_node_archived_zone_preserved():
    node = _make_node(zone=ZONE_ARCHIVED, superseded_at="2025-01-01T00:00:00+00:00")
    restored = Node.from_dict(node.to_dict())
    assert restored.zone == ZONE_ARCHIVED
    assert restored.superseded_at == "2025-01-01T00:00:00+00:00"


# --- Edge roundtrip ---

def _make_edge(**kwargs):
    defaults = dict(
        id="eid12345",
        source_id="src00001",
        target_id="tgt00002",
        type=EdgeType.USES,
        weight=0.75,
        created_at=now_iso(),
        last_activated=now_iso(),
        activation_count=2,
        decay_rate=0.02,
    )
    defaults.update(kwargs)
    return Edge(**defaults)


def test_edge_to_dict_roundtrip():
    edge = _make_edge()
    d = edge.to_dict()
    restored = Edge.from_dict(d)

    assert restored.id == edge.id
    assert restored.source_id == edge.source_id
    assert restored.target_id == edge.target_id
    assert restored.type == edge.type
    assert abs(restored.weight - edge.weight) < 0.001
    assert restored.activation_count == edge.activation_count
    assert restored.decay_rate == edge.decay_rate


def test_edge_to_dict_type_is_string():
    edge = _make_edge()
    assert edge.to_dict()["type"] == "USES"


def test_edge_from_dict_defaults():
    minimal = {
        "id": "e1",
        "source_id": "s1",
        "target_id": "t1",
        "type": "RELATED_TO",
        "weight": 0.5,
        "created_at": now_iso(),
        "last_activated": now_iso(),
    }
    edge = Edge.from_dict(minimal)
    assert edge.activation_count == 0
    assert edge.decay_rate == 0.02
