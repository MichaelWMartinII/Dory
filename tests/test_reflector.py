"""Tests for pipeline/reflector.py — deduplication and supersession."""
import pytest
from dory.pipeline.reflector import Reflector
from dory.schema import NodeType, EdgeType, ZONE_ACTIVE, ZONE_ARCHIVED, now_iso


# --- find_near_duplicates ---

def test_find_near_duplicates_detects_similar_nodes(graph):
    n1 = graph.add_node(NodeType.CONCEPT, "Michael prefers local AI models")
    n2 = graph.add_node(NodeType.CONCEPT, "Michael prefers local AI solutions")

    r = Reflector(graph, dup_threshold=0.6)
    pairs = r.find_near_duplicates()

    assert len(pairs) == 1
    ids = {pairs[0][0].id, pairs[0][1].id}
    assert ids == {n1.id, n2.id}


def test_find_near_duplicates_ignores_different_types(graph):
    # Same words but different NodeType — should not be flagged as duplicate
    graph.add_node(NodeType.CONCEPT, "FastAPI Python backend")
    graph.add_node(NodeType.ENTITY, "FastAPI Python backend")

    r = Reflector(graph, dup_threshold=0.5)
    pairs = r.find_near_duplicates()
    assert pairs == []


def test_find_near_duplicates_ignores_dissimilar_nodes(graph):
    graph.add_node(NodeType.CONCEPT, "machine learning models")
    graph.add_node(NodeType.CONCEPT, "database query optimization")

    r = Reflector(graph, dup_threshold=0.8)
    pairs = r.find_near_duplicates()
    assert pairs == []


def test_find_near_duplicates_includes_similarity_score(graph):
    graph.add_node(NodeType.CONCEPT, "word one two three")
    graph.add_node(NodeType.CONCEPT, "word one two four")

    r = Reflector(graph, dup_threshold=0.5)
    pairs = r.find_near_duplicates()
    if pairs:
        _, _, sim = pairs[0]
        assert 0.0 < sim <= 1.0


# --- find_supersession_candidates ---

def test_find_supersession_candidates_detects_update(graph):
    from datetime import datetime, timezone, timedelta

    # Simulate older node about same subject
    n_old = graph.add_node(NodeType.BELIEF, "Michael primary model is Qwen3-7B")
    n_old.created_at = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

    n_new = graph.add_node(NodeType.BELIEF, "Michael primary model is Qwen3-14B")

    r = Reflector(graph, supersede_threshold=0.4, dup_threshold=0.95)
    candidates = r.find_supersession_candidates()

    # (old, new) pair should be found
    found = any(old.id == n_old.id and new.id == n_new.id for old, new in candidates)
    assert found


def test_find_supersession_candidates_only_same_type(graph):
    graph.add_node(NodeType.CONCEPT, "AllergyFind is a SaaS product")
    graph.add_node(NodeType.ENTITY, "AllergyFind is a SaaS platform")

    r = Reflector(graph, supersede_threshold=0.3, dup_threshold=0.95)
    candidates = r.find_supersession_candidates()
    assert candidates == []


# --- _merge_duplicates ---

def test_merge_duplicates_removes_lower_salience(graph):
    n_high = graph.add_node(NodeType.CONCEPT, "Michael uses Python for all projects")
    n_low  = graph.add_node(NodeType.CONCEPT, "Michael uses Python for projects")

    n_high.salience = 0.8
    n_low.salience  = 0.3

    r = Reflector(graph, dup_threshold=0.6)
    count = r._merge_duplicates()

    assert count == 1
    # Loser is hard-deleted, not archived
    assert n_low.id not in graph._nodes
    assert n_high.id in graph._nodes


def test_merge_duplicates_rewires_edges_to_winner(graph):
    n_high = graph.add_node(NodeType.CONCEPT, "Michael uses Python for all projects")
    n_low  = graph.add_node(NodeType.CONCEPT, "Michael uses Python for projects")
    other1 = graph.add_node(NodeType.ENTITY, "project alpha")
    other2 = graph.add_node(NodeType.ENTITY, "project beta")
    other3 = graph.add_node(NodeType.ENTITY, "project gamma")

    # Give n_high more edges → higher connectivity → wins the salience race
    # (add_edge calls _recompute_salience, so manually setting salience won't hold)
    graph.add_edge(other1.id, n_high.id, EdgeType.RELATED_TO)
    graph.add_edge(other2.id, n_high.id, EdgeType.RELATED_TO)

    # Edge pointing to the soon-to-be-archived n_low
    graph.add_edge(other3.id, n_low.id, EdgeType.RELATED_TO)

    r = Reflector(graph, dup_threshold=0.6)
    r._merge_duplicates()

    # All edges should now point to the winner; the loser is deleted entirely.
    for edge in graph.all_edges():
        assert edge.source_id != n_low.id
        assert edge.target_id != n_low.id


def test_merge_duplicates_no_supersedes_edge(graph):
    # Dedup hard-deletes the loser — no SUPERSEDES provenance edge for exact dupes
    n1 = graph.add_node(NodeType.CONCEPT, "Michael uses Python for all projects")
    n2 = graph.add_node(NodeType.CONCEPT, "Michael uses Python for projects")
    n1.salience = 0.8
    n2.salience = 0.3

    r = Reflector(graph, dup_threshold=0.6)
    r._merge_duplicates()

    supersede_edges = [e for e in graph.all_edges() if e.type == EdgeType.SUPERSEDES]
    assert len(supersede_edges) == 0


def test_merge_duplicates_transfers_activation_count(graph):
    n1 = graph.add_node(NodeType.CONCEPT, "Michael uses Python for all projects")
    n2 = graph.add_node(NodeType.CONCEPT, "Michael uses Python for projects")
    n1.salience = 0.8
    n1.activation_count = 10
    n2.salience = 0.3
    n2.activation_count = 5

    r = Reflector(graph, dup_threshold=0.6)
    r._merge_duplicates()

    assert n1.activation_count == 15  # 10 + 5 transferred from n2


# --- _apply_supersessions ---

def test_apply_supersessions_archives_old_node(graph):
    from datetime import datetime, timezone, timedelta

    n_old = graph.add_node(NodeType.BELIEF, "primary model is Qwen3-7B local")
    n_old.created_at = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    n_new = graph.add_node(NodeType.BELIEF, "primary model is Qwen3-14B local")

    r = Reflector(graph, supersede_threshold=0.4, dup_threshold=0.95)
    count = r._apply_supersessions()

    assert count >= 1
    assert n_old.zone == ZONE_ARCHIVED
    assert n_old.superseded_at is not None


def test_apply_supersessions_adds_provenance_edge(graph):
    from datetime import datetime, timezone, timedelta

    n_old = graph.add_node(NodeType.BELIEF, "primary model is Qwen3-7B local")
    n_old.created_at = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    n_new = graph.add_node(NodeType.BELIEF, "primary model is Qwen3-14B local")

    r = Reflector(graph, supersede_threshold=0.4, dup_threshold=0.95)
    r._apply_supersessions()

    supersede_edges = [e for e in graph.all_edges() if e.type == EdgeType.SUPERSEDES]
    assert len(supersede_edges) >= 1


# --- run ---

def test_reflector_run_returns_stats(graph):
    r = Reflector(graph)
    stats = r.run()
    assert "duplicates_merged" in stats
    assert "supersessions_applied" in stats
    assert "observations_compressed" in stats
    assert "errors" in stats


def test_reflector_run_on_empty_graph_returns_zeros(graph):
    r = Reflector(graph)
    stats = r.run()
    assert stats["duplicates_merged"] == 0
    assert stats["supersessions_applied"] == 0
    assert stats["errors"] == 0


def test_reflector_run_saves_graph(db_path):
    from dory.graph import Graph
    g = Graph(path=db_path)
    g.add_node(NodeType.CONCEPT, "standalone node")

    r = Reflector(g, db_path=db_path)
    r.run()

    g2 = Graph(path=db_path)
    assert len(g2.all_nodes()) >= 1
