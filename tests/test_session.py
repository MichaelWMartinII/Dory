"""Tests for session.py — high-level session API."""
import pytest
from dory import session, store
from dory.schema import NodeType, EdgeType


def test_observe_adds_node(graph):
    node_id = session.observe("Michael uses Python", NodeType.PREFERENCE, graph)
    assert graph.get_node(node_id) is not None
    assert graph.get_node(node_id).content == "Michael uses Python"


def test_observe_returns_node_id(graph):
    node_id = session.observe("some fact", NodeType.CONCEPT, graph)
    assert isinstance(node_id, str)
    assert len(node_id) > 0


def test_observe_with_tags(graph):
    node_id = session.observe("tagged fact", NodeType.ENTITY, graph, tags=["a", "b"])
    assert graph.get_node(node_id).tags == ["a", "b"]


def test_link_creates_edge(graph):
    n1 = graph.add_node(NodeType.ENTITY, "Dory")
    n2 = graph.add_node(NodeType.CONCEPT, "memory graph")
    session.link(n1.id, n2.id, EdgeType.USES, graph)

    edges = graph.edges_for_node(n1.id)
    assert len(edges) == 1
    assert edges[0].type == EdgeType.USES


def test_write_turn_logs_to_observations(db_path):
    from dory.graph import Graph
    g = Graph(path=db_path)
    obs_id = session.write_turn("hello world", g, role="user", session_id="s1")

    rows = store.get_observations(db_path, session_id="s1")
    assert len(rows) == 1
    assert rows[0]["content"] == "hello world"
    assert rows[0]["role"] == "user"
    assert rows[0]["id"] == obs_id


def test_write_turn_returns_obs_id(graph):
    obs_id = session.write_turn("some turn", graph)
    assert isinstance(obs_id, str)


def test_query_returns_string(populated_graph):
    graph, n1, *_ = populated_graph
    result = session.query("AllergyFind", graph)
    assert isinstance(result, str)


def test_query_includes_relevant_content(populated_graph):
    graph, n1, *_ = populated_graph
    result = session.query("AllergyFind", graph)
    assert "AllergyFind" in result


def test_query_no_match_returns_placeholder(graph):
    result = session.query("xyzqwerty", graph)
    assert "no" in result.lower()


def test_end_session_returns_stats(graph):
    result = session.end_session(graph)
    assert "pruned_edges" in result
    assert "promoted_core" in result
    assert "demoted_core" in result
