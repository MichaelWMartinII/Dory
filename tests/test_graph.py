"""Tests for graph.py — Graph CRUD and salience computation."""
import pytest
from dory.graph import Graph
from dory.schema import NodeType, EdgeType, ZONE_ACTIVE, ZONE_ARCHIVED


# --- add_node ---

def test_add_node_returns_node(graph):
    node = graph.add_node(NodeType.CONCEPT, "FastAPI")
    assert node.id is not None
    assert node.type == NodeType.CONCEPT
    assert node.content == "FastAPI"


def test_add_node_with_tags(graph):
    node = graph.add_node(NodeType.ENTITY, "Dory project", tags=["memory", "python"])
    assert node.tags == ["memory", "python"]


def test_add_node_persisted(db_path):
    """Node should survive a reload from disk after explicit save."""
    g1 = Graph(path=db_path)
    node = g1.add_node(NodeType.ENTITY, "persisted node")
    node_id = node.id
    g1.save()

    g2 = Graph(path=db_path)
    assert g2.get_node(node_id) is not None
    assert g2.get_node(node_id).content == "persisted node"


def test_add_node_zone_defaults_to_active(graph):
    node = graph.add_node(NodeType.CONCEPT, "test")
    assert node.zone == ZONE_ACTIVE


def test_add_node_activation_count_starts_at_zero(graph):
    node = graph.add_node(NodeType.CONCEPT, "test")
    assert node.activation_count == 0


# --- get_node ---

def test_get_node_returns_none_for_missing(graph):
    assert graph.get_node("nonexistent") is None


def test_get_node_returns_correct_node(graph):
    n = graph.add_node(NodeType.ENTITY, "AllergyFind")
    assert graph.get_node(n.id) is n


# --- find_nodes ---

def test_find_nodes_substring_match(graph):
    graph.add_node(NodeType.ENTITY, "AllergyFind restaurant platform")
    graph.add_node(NodeType.CONCEPT, "unrelated concept here")
    results = graph.find_nodes("AllergyFind")
    assert len(results) == 1
    assert results[0].content == "AllergyFind restaurant platform"


def test_find_nodes_multi_term_requires_all(graph):
    graph.add_node(NodeType.CONCEPT, "FastAPI Python backend")
    graph.add_node(NodeType.CONCEPT, "FastAPI framework")
    results = graph.find_nodes("fastapi python")
    assert len(results) == 1
    assert "Python" in results[0].content


def test_find_nodes_searches_tags(graph):
    graph.add_node(NodeType.ENTITY, "some project", tags=["saas", "b2b"])
    results = graph.find_nodes("saas")
    assert len(results) == 1


def test_find_nodes_filters_by_zone(graph):
    n = graph.add_node(NodeType.CONCEPT, "archived concept")
    n.zone = ZONE_ARCHIVED
    graph.save()

    # Default: only active
    active_results = graph.find_nodes("archived concept")
    assert len(active_results) == 0

    # zone=None: all zones
    all_results = graph.find_nodes("archived concept", zone=None)
    assert len(all_results) == 1


# --- all_nodes ---

def test_all_nodes_returns_active_by_default(graph):
    n = graph.add_node(NodeType.CONCEPT, "active node")
    n2 = graph.add_node(NodeType.CONCEPT, "another")
    n2.zone = ZONE_ARCHIVED
    graph.save()

    active = graph.all_nodes()
    assert len(active) == 1
    assert active[0].id == n.id


def test_all_nodes_zone_none_returns_all(graph):
    n1 = graph.add_node(NodeType.CONCEPT, "node one")
    n2 = graph.add_node(NodeType.CONCEPT, "node two")
    n2.zone = ZONE_ARCHIVED
    graph.save()

    all_nodes = graph.all_nodes(zone=None)
    assert len(all_nodes) == 2


# --- add_edge ---

def test_add_edge_creates_edge(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    edge = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.7)

    assert edge.source_id == n1.id
    assert edge.target_id == n2.id
    assert edge.type == EdgeType.USES
    assert abs(edge.weight - 0.7) < 0.001


def test_add_edge_reinforces_existing(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    e1 = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.5)
    eid = e1.id

    e2 = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.5)

    # Should return the same edge, reinforced
    assert e2.id == eid
    assert e2.weight > 0.5
    assert e2.activation_count == 1
    # Should not create a duplicate
    assert len(graph.all_edges()) == 1


def test_add_edge_weight_caps_at_1(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.95)
    e = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.95)
    assert e.weight <= 1.0


def test_add_edge_different_type_creates_new(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    graph.add_edge(n1.id, n2.id, EdgeType.USES)
    graph.add_edge(n1.id, n2.id, EdgeType.RELATED_TO)
    assert len(graph.all_edges()) == 2


def test_add_edge_persisted(db_path):
    g1 = Graph(path=db_path)
    n1 = g1.add_node(NodeType.ENTITY, "X")
    n2 = g1.add_node(NodeType.ENTITY, "Y")
    e = g1.add_edge(n1.id, n2.id, EdgeType.PART_OF)
    g1.save()

    g2 = Graph(path=db_path)
    edges = g2.all_edges()
    assert len(edges) == 1
    assert edges[0].id == e.id


# --- edges_for_node ---

def test_edges_for_node_returns_connected_edges(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    n3 = graph.add_node(NodeType.ENTITY, "C")
    graph.add_edge(n1.id, n2.id, EdgeType.USES)
    graph.add_edge(n2.id, n3.id, EdgeType.PART_OF)

    edges_n2 = graph.edges_for_node(n2.id)
    assert len(edges_n2) == 2  # n2 is on both edges


def test_edges_for_node_returns_empty_for_isolated_node(graph):
    n = graph.add_node(NodeType.CONCEPT, "isolated")
    assert graph.edges_for_node(n.id) == []


# --- salience computation ---

def test_salience_increases_with_connectivity(graph):
    hub = graph.add_node(NodeType.ENTITY, "hub node")
    spoke1 = graph.add_node(NodeType.ENTITY, "spoke 1")
    spoke2 = graph.add_node(NodeType.ENTITY, "spoke 2")
    isolated = graph.add_node(NodeType.ENTITY, "isolated")

    graph.add_edge(hub.id, spoke1.id, EdgeType.RELATED_TO)
    graph.add_edge(hub.id, spoke2.id, EdgeType.RELATED_TO)

    # Salience is lazy — trigger recompute before reading
    graph._recompute_salience()

    # Hub has 2 edges, isolated has 0 → hub should have higher salience
    assert hub.salience > isolated.salience


def test_salience_is_in_unit_interval(graph):
    for i in range(5):
        graph.add_node(NodeType.CONCEPT, f"node {i}")
    graph._recompute_salience()
    for n in graph.all_nodes():
        assert 0.0 <= n.salience <= 1.0


# --- stats ---

def test_stats_counts_correctly(graph):
    graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.CONCEPT, "B")
    n2.zone = ZONE_ARCHIVED
    graph.save()

    s = graph.stats()
    assert s["nodes"] == 2
    assert s["active"] == 1
    assert s["archived"] == 1
    assert s["expired"] == 0
    assert s["core_nodes"] == 0
