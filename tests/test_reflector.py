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


# --- contradiction handling -------------------------------------------------
# A correction only reaches the graph if it survives three gates: the subject
# check, the similarity band, and deduplication. Each of these cases failed one
# of them, which is how a renamed project and a replaced model stayed "true"
# for months.

from dory.pipeline.reflector import (
    _containment, _is_contradiction, _is_substitution,
    _jaccard, _polarity_differs, _shared_subject,
)


def test_shared_subject_survives_a_rename():
    # The old first-two-words rule failed here: the rename changes word one.
    assert _shared_subject(
        "Engram is a session-based graph memory system",
        "Dory is a session-based graph memory system",
    )


def test_shared_subject_survives_a_negation():
    # "does not" shifts every following word, breaking a positional rule.
    assert _shared_subject(
        "Elwin uses Qwen3-14B as its primary local model",
        "Elwin does not use Qwen3-14B as its primary local model",
    )


def test_shared_subject_rejects_unrelated_statements():
    assert not _shared_subject(
        "Michael prefers local-first inference",
        "The Daytona 24h was won by Porsche Penske",
    )


def test_containment_sees_what_jaccard_misses():
    terse = "Uses Qwen3-14B as primary local model for inference"
    detailed = (
        "Elwin Ransom does not use Qwen3-14B any more; since April it runs "
        "gemma4-free on Ollama as its primary local model for inference"
    )
    # Jaccard divides by the union, so the longer the correction the lower it
    # scores — the opposite of what a careful correction deserves.
    assert _jaccard(terse, detailed) < 0.45
    assert _containment(terse, detailed) >= 0.6


def test_polarity_differs_detects_negation():
    assert _polarity_differs("Elwin uses Qwen3-14B", "Elwin does not use Qwen3-14B")
    assert _polarity_differs("She still runs it", "She no longer runs it")
    assert not _polarity_differs("Elwin uses Qwen3-14B", "Elwin uses gemma4")


def test_substitution_distinguished_from_elaboration():
    # Each side carries a word the other lacks → a value was replaced.
    assert _is_substitution("The project is called Engram", "The project is called Dory")
    # One side merely adds a word → same claim, safe to merge.
    assert not _is_substitution(
        "Michael uses Python for projects",
        "Michael uses Python for all projects",
    )


def test_is_contradiction_covers_both_shapes():
    assert _is_contradiction("Michael lives in Murfreesboro", "Michael lives in Alexandria")
    assert _is_contradiction("Elwin uses Qwen3-14B", "Elwin does not use Qwen3-14B")
    assert not _is_contradiction(
        "Michael uses Python for projects",
        "Michael uses Python for all projects",
    )


def test_rename_supersedes_instead_of_being_merged(graph):
    # Jaccard here is ~0.82 — right at dup_threshold, where dedup would have
    # hard-deleted one side and kept whichever had more salience.
    old = graph.add_node(NodeType.CONCEPT, "The project is called Engram and it ships on PyPI")
    new = graph.add_node(NodeType.CONCEPT, "The project is called Dory and it ships on PyPI")

    r = Reflector(graph)
    merged = r._merge_duplicates()
    assert merged == 0, "a renamed fact must never be merged away"

    assert r._apply_supersessions() == 1
    assert graph._nodes[old.id].zone == ZONE_ARCHIVED
    assert graph._nodes[new.id].zone == ZONE_ACTIVE


def test_negation_supersedes_the_positive_claim(graph):
    old = graph.add_node(NodeType.PREFERENCE, "Elwin uses Qwen3-14B as its primary local model")
    new = graph.add_node(NodeType.PREFERENCE, "Elwin does not use Qwen3-14B as its primary local model")

    r = Reflector(graph)
    assert r._apply_supersessions() == 1
    assert graph._nodes[old.id].zone == ZONE_ARCHIVED

    edges = [e for e in graph.all_edges() if e.type == EdgeType.SUPERSEDES]
    assert len(edges) == 1
    assert edges[0].source_id == new.id and edges[0].target_id == old.id


def test_detailed_correction_supersedes_terse_fact(graph):
    old = graph.add_node(NodeType.PREFERENCE, "Uses Qwen3-14B as primary local model for inference")
    new = graph.add_node(
        NodeType.PREFERENCE,
        "Elwin Ransom does not use Qwen3-14B any more; since April it runs "
        "gemma4-free on Ollama as its primary local model for inference",
    )

    r = Reflector(graph)
    assert r._apply_supersessions() == 1
    assert graph._nodes[old.id].zone == ZONE_ARCHIVED


def test_entrenched_wrong_fact_loses_to_fresh_correction(graph):
    """The real failure: a months-old fact with high salience versus a
    brand-new correction with none. Dedup picked by salience and hard-deleted
    the loser, so the wrong memory won and the correction was destroyed."""
    stale = graph.add_node(NodeType.CONCEPT, "Michael lives in Murfreesboro and works remotely")
    fresh = graph.add_node(NodeType.CONCEPT, "Michael lives in Alexandria and works remotely")
    stale.salience, stale.activation_count = 0.66, 39
    fresh.salience, fresh.activation_count = 0.36, 0

    r = Reflector(graph)
    r._merge_duplicates()
    assert fresh.id in graph._nodes, "the correction must not be deleted"

    r._apply_supersessions()
    assert graph._nodes[stale.id].zone == ZONE_ARCHIVED
    assert graph._nodes[fresh.id].zone == ZONE_ACTIVE


def test_true_duplicates_still_merge(graph):
    """Regression guard: elaborations are not contradictions and must still
    collapse, or dedup stops doing its job."""
    a = graph.add_node(NodeType.CONCEPT, "Michael uses Python for all projects")
    b = graph.add_node(NodeType.CONCEPT, "Michael uses Python for projects")
    a.salience, b.salience = 0.8, 0.3

    r = Reflector(graph, dup_threshold=0.6)
    assert r._merge_duplicates() == 1
    assert b.id not in graph._nodes


def test_short_node_is_not_swallowed_by_a_long_paragraph(graph):
    """Guard found by running against a real graph: a one-word node is wholly
    contained in any text that mentions it, scoring a perfect 1.0. Without a
    minimum-length rule this archived every short concept node in the graph."""
    short = graph.add_node(NodeType.CONCEPT, "SQLite")
    graph.add_node(
        NodeType.CONCEPT,
        "Dory stores its graph in SQLite and does not require a vector database; "
        "the schema covers nodes, edges and a full-text index",
    )

    r = Reflector(graph)
    assert (short.content, ) and all(
        old.id != short.id for old, _ in r.find_supersession_candidates()
    )
    assert _containment("SQLite", "Dory stores its graph in SQLite") == 0.0


def test_generic_word_overlap_does_not_supersede(graph):
    """Two unrelated facts sharing only common technical words must not match."""
    graph.add_node(NodeType.CONCEPT, "Menu allergen data API endpoint")
    graph.add_node(
        NodeType.CONCEPT,
        "Cloudflare Browser Rendering crawl endpoint entered open beta, exposing "
        "a data API for rendered page content",
    )

    r = Reflector(graph)
    assert r.find_supersession_candidates() == []
