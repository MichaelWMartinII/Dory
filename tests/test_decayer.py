"""Tests for pipeline/decayer.py — zone-based memory decay."""
import pytest
from datetime import datetime, timezone, timedelta

from dory.pipeline.decayer import Decayer, DecayConfig, score_node
from dory.schema import NodeType, EdgeType, ZONE_ACTIVE, ZONE_ARCHIVED, ZONE_EXPIRED, now_iso


def _past_iso(days: float) -> str:
    past = datetime.now(timezone.utc) - timedelta(days=days)
    return past.isoformat()


# --- score_node ---

def test_score_node_returns_value_in_unit_interval(graph):
    n = graph.add_node(NodeType.ENTITY, "test node")
    cfg = DecayConfig()
    score = score_node(n, cfg)
    assert 0.0 <= score <= 1.0


def test_score_node_recent_activation_scores_higher(graph):
    cfg = DecayConfig()
    n_fresh = graph.add_node(NodeType.ENTITY, "fresh node")
    n_old = graph.add_node(NodeType.ENTITY, "old node")
    n_old.last_activated = _past_iso(60)
    n_old.activation_count = n_fresh.activation_count

    # Both have same salience since they're in the same graph
    # Recency component should make n_fresh score higher
    score_fresh = score_node(n_fresh, cfg)
    score_old = score_node(n_old, cfg)
    assert score_fresh > score_old


def test_score_node_high_frequency_scores_higher(graph):
    cfg = DecayConfig()
    n_freq = graph.add_node(NodeType.ENTITY, "frequent node")
    n_rare = graph.add_node(NodeType.ENTITY, "rare node")
    n_freq.activation_count = 100
    n_rare.activation_count = 1

    # Same recency — frequency drives the difference
    max_act = 100
    score_freq = score_node(n_freq, cfg, max_activations=max_act)
    score_rare = score_node(n_rare, cfg, max_activations=max_act)
    assert score_freq > score_rare


# --- Decayer.run ---

def test_decayer_run_returns_stats(graph):
    d = Decayer(graph)
    stats = d.run()
    assert "scored" in stats
    assert "archived" in stats
    assert "expired" in stats
    assert "restored" in stats


def test_decayer_archives_low_score_node(graph):
    cfg = DecayConfig(active_floor=0.9)  # very high floor → most nodes archived
    n = graph.add_node(NodeType.ENTITY, "old node")
    n.last_activated = _past_iso(90)   # 3 months ago
    n.activation_count = 5             # enough to be eligible

    d = Decayer(graph, config=cfg)
    stats = d.run()

    assert n.zone == ZONE_ARCHIVED
    assert stats["archived"] >= 1


def test_decayer_expires_very_low_score_node(graph):
    cfg = DecayConfig(active_floor=0.9, archive_floor=0.8)
    n = graph.add_node(NodeType.ENTITY, "ancient node")
    n.last_activated = _past_iso(365)  # 1 year ago
    n.activation_count = 10

    d = Decayer(graph, config=cfg)
    stats = d.run()

    assert n.zone == ZONE_EXPIRED
    assert stats["expired"] >= 1


def test_decayer_restores_recently_activated_archived_node(graph):
    n = graph.add_node(NodeType.ENTITY, "was archived")
    n.zone = ZONE_ARCHIVED
    n.last_activated = now_iso()  # just activated

    d = Decayer(graph)
    stats = d.run()

    assert n.zone == ZONE_ACTIVE
    assert stats["restored"] >= 1


def test_decayer_skips_low_activation_count_nodes(graph):
    cfg = DecayConfig(active_floor=0.9, min_activations_before_archive=3)
    n = graph.add_node(NodeType.ENTITY, "new node")
    n.last_activated = _past_iso(90)
    n.activation_count = 1  # below min_activations_before_archive

    d = Decayer(graph, config=cfg)
    d.run()

    assert n.zone == ZONE_ACTIVE  # should not be archived


def test_core_shield_protects_node_from_archival(graph):
    # Without shield: active_floor=0.9 would archive this node.
    # With core_shield=0.1, effective floor = 0.9 * 0.1 = 0.09, well below score.
    cfg = DecayConfig(active_floor=0.9, core_shield=0.1)
    n = graph.add_node(NodeType.ENTITY, "core node")
    n.is_core = True
    n.last_activated = _past_iso(30)
    n.activation_count = 5

    d = Decayer(graph, config=cfg)
    d.run()

    assert n.zone == ZONE_ACTIVE


def test_decayer_scores_returns_list(graph):
    graph.add_node(NodeType.ENTITY, "node A")
    graph.add_node(NodeType.ENTITY, "node B")

    d = Decayer(graph)
    scores = d.scores()
    assert isinstance(scores, list)
    assert len(scores) == 2
    assert all("id" in s and "score" in s and "zone" in s for s in scores)


def test_decayer_scores_sorted_descending(graph):
    nodes = [graph.add_node(NodeType.ENTITY, f"node {i}") for i in range(5)]
    d = Decayer(graph)
    scores = d.scores()
    score_vals = [s["score"] for s in scores]
    assert score_vals == sorted(score_vals, reverse=True)


def test_decayer_empty_graph_returns_zeroed_stats(graph):
    d = Decayer(graph)
    stats = d.run()
    assert stats == {"scored": 0, "archived": 0, "expired": 0, "restored": 0}
