"""Tests for consolidation.py — decay, strengthen, prune, promote/demote."""
import pytest
from datetime import datetime, timezone, timedelta

from dory import consolidation
from dory.schema import NodeType, EdgeType


def _past_iso(days: float) -> str:
    """Return an ISO timestamp N days in the past."""
    past = datetime.now(timezone.utc) - timedelta(days=days)
    return past.isoformat()


# --- strengthen ---

def test_strengthen_increases_edge_weight(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    edge = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.5)
    original_weight = edge.weight

    consolidation.strengthen([edge.id], graph, delta=0.1)
    assert edge.weight > original_weight


def test_strengthen_caps_at_one(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    edge = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.99)

    consolidation.strengthen([edge.id], graph, delta=0.1)
    assert edge.weight <= 1.0


def test_strengthen_increments_activation_count(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    edge = graph.add_edge(n1.id, n2.id, EdgeType.USES)
    before = edge.activation_count

    consolidation.strengthen([edge.id], graph)
    assert edge.activation_count == before + 1


def test_strengthen_ignores_non_traversed_edges(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    edge = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.5)
    original = edge.weight

    consolidation.strengthen([], graph)  # no edges traversed
    assert edge.weight == original


# --- decay ---

def test_decay_reduces_old_edge_weight(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    edge = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.8)

    # Simulate edge that hasn't been activated in 30 days
    edge.last_activated = _past_iso(30)

    before = edge.weight
    consolidation.decay(graph)
    assert edge.weight < before


def test_decay_does_not_go_below_zero(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    edge = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.01)
    edge.last_activated = _past_iso(365)  # 1 year old

    consolidation.decay(graph)
    assert edge.weight >= 0.0


def test_decay_recently_activated_edge_loses_little(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    edge = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.8)
    # Just activated — delta_days ≈ 0

    before = edge.weight
    consolidation.decay(graph)
    # Should lose very little (decay_rate * ~0 days ≈ 0)
    assert abs(edge.weight - before) < 0.01


def test_decay_multi_cycle_does_not_compound(graph):
    """Running decay twice should NOT double-subtract; last_activated resets after each pass."""
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    edge = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.8)
    edge.last_activated = _past_iso(10)

    consolidation.decay(graph)
    after_first = edge.weight

    # Second decay: last_activated was reset to ~now, so delta ≈ 0 days
    consolidation.decay(graph)
    after_second = edge.weight

    # Second pass should subtract nearly nothing
    assert abs(after_second - after_first) < 0.01


# --- prune ---

def test_prune_removes_weak_edges(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    edge = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.03)

    removed = consolidation.prune(graph, min_weight=0.05)
    assert removed == 1
    assert len(graph.all_edges()) == 0


def test_prune_keeps_strong_edges(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.8)

    removed = consolidation.prune(graph, min_weight=0.05)
    assert removed == 0
    assert len(graph.all_edges()) == 1


def test_prune_returns_count_of_removed(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    n3 = graph.add_node(NodeType.ENTITY, "C")
    graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.01)  # weak
    graph.add_edge(n1.id, n3.id, EdgeType.USES, weight=0.9)   # strong

    removed = consolidation.prune(graph, min_weight=0.05)
    assert removed == 1


# --- promote_core ---

def test_promote_core_flags_high_salience_nodes(graph):
    n = graph.add_node(NodeType.ENTITY, "high salience")
    n.salience = 0.9

    promoted = consolidation.promote_core(graph, threshold=0.65)
    assert n.id in promoted
    assert n.is_core is True


def test_promote_core_ignores_already_core(graph):
    n = graph.add_node(NodeType.ENTITY, "already core")
    n.salience = 0.9
    n.is_core = True

    promoted = consolidation.promote_core(graph, threshold=0.65)
    assert n.id not in promoted  # already core, not re-promoted


def test_promote_core_ignores_low_salience(graph):
    n = graph.add_node(NodeType.ENTITY, "low salience")
    n.salience = 0.2

    promoted = consolidation.promote_core(graph, threshold=0.65)
    assert n.id not in promoted
    assert n.is_core is False


# --- demote_core ---

def test_demote_core_removes_flag_from_low_salience(graph):
    n = graph.add_node(NodeType.ENTITY, "formerly core")
    n.is_core = True
    n.salience = 0.1

    demoted = consolidation.demote_core(graph, threshold=0.25)
    assert n.id in demoted
    assert n.is_core is False


def test_demote_core_keeps_high_salience_core(graph):
    n = graph.add_node(NodeType.ENTITY, "still core")
    n.is_core = True
    n.salience = 0.8

    demoted = consolidation.demote_core(graph, threshold=0.25)
    assert n.id not in demoted
    assert n.is_core is True


# --- run (full consolidation) ---

def test_run_returns_stats_dict(graph):
    result = consolidation.run(graph)
    assert "pruned_edges" in result
    assert "promoted_core" in result
    assert "demoted_core" in result


def test_run_prunes_weak_edges(graph):
    n1 = graph.add_node(NodeType.ENTITY, "A")
    n2 = graph.add_node(NodeType.ENTITY, "B")
    edge = graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.03)
    edge.last_activated = _past_iso(100)  # old, will decay further

    result = consolidation.run(graph)
    assert result["pruned_edges"] >= 1


def test_run_saves_graph(db_path):
    from dory.graph import Graph
    g = Graph(path=db_path)
    n1 = g.add_node(NodeType.ENTITY, "X")
    n2 = g.add_node(NodeType.ENTITY, "Y")
    g.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.9)

    consolidation.run(g)

    g2 = Graph(path=db_path)
    assert len(g2.all_nodes()) >= 1  # graph was persisted
