"""Tests for activation.py — spreading activation engine."""
import pytest
from dory import activation as act
from dory.schema import NodeType, EdgeType


# --- find_seeds ---

def test_find_seeds_returns_matching_node_ids(populated_graph):
    graph, n1, n2, n3, n4 = populated_graph
    seeds = act.find_seeds("AllergyFind", graph)
    assert n1.id in seeds


def test_find_seeds_returns_empty_for_no_match(graph):
    graph.add_node(NodeType.ENTITY, "something unrelated")
    seeds = act.find_seeds("xyzqwerty", graph)
    assert seeds == []


def test_find_seeds_on_empty_graph(graph):
    seeds = act.find_seeds("anything", graph)
    assert seeds == []


def test_find_seeds_deduplicates(populated_graph):
    """A node matching via multiple paths should appear only once."""
    graph, n1, *_ = populated_graph
    seeds = act.find_seeds("AllergyFind project", graph)
    assert seeds.count(n1.id) == 1


# --- spread ---

def test_spread_seeds_have_full_activation(graph):
    n = graph.add_node(NodeType.ENTITY, "seed node")
    activated = act.spread([n.id], graph)
    assert activated[n.id] == 1.0


def test_spread_propagates_to_neighbors(graph):
    n1 = graph.add_node(NodeType.ENTITY, "source")
    n2 = graph.add_node(NodeType.ENTITY, "neighbor")
    graph.add_edge(n1.id, n2.id, EdgeType.RELATED_TO, weight=0.8)

    activated = act.spread([n1.id], graph)
    assert n2.id in activated
    assert activated[n2.id] < activated[n1.id]  # activation decays across hops


def test_spread_activation_decays_with_depth(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    n3 = graph.add_node(NodeType.ENTITY, "C")
    graph.add_edge(n1.id, n2.id, EdgeType.RELATED_TO, weight=1.0)
    graph.add_edge(n2.id, n3.id, EdgeType.RELATED_TO, weight=1.0)

    activated = act.spread([n1.id], graph, depth_decay=0.5)
    assert activated.get(n3.id, 0) < activated.get(n2.id, 0)


def test_spread_respects_threshold(graph):
    n1 = graph.add_node(NodeType.ENTITY, "root")
    n2 = graph.add_node(NodeType.ENTITY, "distant")
    # Very weak edge — activation won't clear default threshold
    graph.add_edge(n1.id, n2.id, EdgeType.RELATED_TO, weight=0.01)

    activated = act.spread([n1.id], graph, depth_decay=0.5, threshold=0.05)
    # n2 receives 1.0 * 0.01 * 0.5 = 0.005 < 0.05 threshold
    assert n2.id not in activated


def test_spread_records_activation_count(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.9)

    before = n2.activation_count
    act.spread([n1.id], graph)
    assert n2.activation_count > before


def test_spread_reinforces_traversed_edges(graph):
    """Spreading activation should increment activation_count on traversed edges."""
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    edge = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.9)

    before_count = edge.activation_count
    before_activated = edge.last_activated

    act.spread([n1.id], graph)

    assert edge.activation_count > before_count
    assert edge.last_activated >= before_activated


def test_spread_caps_activation_at_one(graph):
    """A node receiving activation from multiple paths shouldn't exceed 1.0."""
    root = graph.add_node(NodeType.ENTITY, "root")
    target = graph.add_node(NodeType.ENTITY, "target")
    mid1 = graph.add_node(NodeType.ENTITY, "mid1")
    mid2 = graph.add_node(NodeType.ENTITY, "mid2")
    graph.add_edge(root.id, mid1.id, EdgeType.RELATED_TO, weight=1.0)
    graph.add_edge(root.id, mid2.id, EdgeType.RELATED_TO, weight=1.0)
    graph.add_edge(mid1.id, target.id, EdgeType.RELATED_TO, weight=1.0)
    graph.add_edge(mid2.id, target.id, EdgeType.RELATED_TO, weight=1.0)

    activated = act.spread([root.id], graph)
    assert activated.get(target.id, 0) <= 1.0


def test_spread_on_disconnected_graph(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    graph.add_node(NodeType.ENTITY, "B")  # no edge

    activated = act.spread([n1.id], graph)
    assert len(activated) == 1
    assert n1.id in activated


# --- serialize ---

def test_serialize_returns_string(graph):
    n = graph.add_node(NodeType.ENTITY, "test node")
    result = act.serialize({n.id: 1.0}, graph)
    assert isinstance(result, str)
    assert "test node" in result


def test_serialize_empty_returns_placeholder(graph):
    result = act.serialize({}, graph)
    assert result == "(no relevant memories found)"


def test_serialize_includes_edge_relationships(graph):
    n1 = graph.add_node(NodeType.ENTITY, "project X")
    n2 = graph.add_node(NodeType.CONCEPT, "technology Y")
    graph.add_edge(n1.id, n2.id, EdgeType.USES)

    result = act.serialize({n1.id: 1.0, n2.id: 0.5}, graph)
    assert "USES" in result
    assert "project X" in result
    assert "technology Y" in result


def test_serialize_marks_core_nodes(graph):
    n = graph.add_node(NodeType.ENTITY, "core thing")
    n.is_core = True

    result = act.serialize({n.id: 1.0}, graph)
    assert "[CORE]" in result


def test_serialize_respects_max_nodes(graph):
    nodes = [graph.add_node(NodeType.CONCEPT, f"concept {i}") for i in range(10)]
    activated = {n.id: 1.0 for n in nodes}

    result = act.serialize(activated, graph, max_nodes=3)
    # Should include only 3 nodes' content lines
    content_lines = [l for l in result.split("\n") if l.startswith("- [")]
    assert len(content_lines) == 3
