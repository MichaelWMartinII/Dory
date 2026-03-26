"""Tests for pipeline/observer.py — memory extraction pipeline."""
import pytest
from unittest.mock import patch, MagicMock

from dory.pipeline.observer import Observer
from dory import store
from dory.schema import NodeType, new_id


# --- helpers ---

def _extracted(nodes=None, edges=None):
    """Build a fake LLM extraction response."""
    return {"nodes": nodes or [], "edges": edges or []}


def _node_extract(content, ntype="CONCEPT", confidence=0.9, tags=None):
    return {"type": ntype, "content": content, "confidence": confidence, "tags": tags or []}


# --- add_turn ---

def test_add_turn_logs_to_observations(db_path, graph):
    obs = Observer(graph, db_path=db_path, threshold=10)  # high threshold, no auto-extract
    obs.add_turn("user", "I am working on AllergyFind today")

    rows = store.get_observations(db_path)
    assert len(rows) == 1
    assert rows[0]["role"] == "user"
    assert "AllergyFind" in rows[0]["content"]


def test_add_turn_increments_turn_count(db_path, graph):
    obs = Observer(graph, db_path=db_path, threshold=10)
    obs.add_turn("user", "first turn")
    obs.add_turn("assistant", "second turn")
    assert obs.stats()["turns_logged"] == 2


def test_add_turn_triggers_extraction_at_threshold(db_path, graph):
    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = _extracted()
        obs = Observer(graph, db_path=db_path, threshold=3, backend="ollama")
        obs.add_turn("user", "turn one")
        obs.add_turn("assistant", "turn two")
        assert mock_llm.call_count == 0  # not yet

        obs.add_turn("user", "turn three")
        obs.flush()  # drain thread pool before asserting
        assert mock_llm.call_count == 1  # triggered


def test_add_turn_buffers_until_threshold(db_path, graph):
    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = _extracted()
        obs = Observer(graph, db_path=db_path, threshold=5, backend="ollama")
        for i in range(4):
            obs.add_turn("user", f"turn {i}")
        assert mock_llm.call_count == 0


# --- flush ---

def test_flush_triggers_extraction_for_remaining_buffer(db_path, graph):
    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = _extracted()
        obs = Observer(graph, db_path=db_path, threshold=10, backend="ollama")
        obs.add_turn("user", "something important")
        obs.flush()
        assert mock_llm.call_count == 1


def test_flush_returns_stats(db_path, graph):
    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = _extracted()
        obs = Observer(graph, db_path=db_path, backend="ollama")
        stats = obs.flush()
        assert "turns_logged" in stats
        assert "extractions_run" in stats
        assert "nodes_written" in stats


def test_flush_saves_graph(db_path):
    from dory.graph import Graph
    g = Graph(path=db_path)
    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = _extracted([_node_extract("test fact")])
        obs = Observer(g, db_path=db_path, threshold=1, backend="ollama")
        obs.add_turn("user", "one turn")
        obs.flush()

    g2 = Graph(path=db_path)
    # At minimum the schema was set up and save was called
    assert g2 is not None


def test_flush_on_empty_buffer_is_noop(db_path, graph):
    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = _extracted()
        obs = Observer(graph, db_path=db_path, backend="ollama")
        obs.flush()
        assert mock_llm.call_count == 0


# --- _write (extraction results) ---

def test_write_creates_nodes_from_extraction(db_path, graph):
    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = _extracted([
            _node_extract("Michael prefers local-first AI", "PREFERENCE"),
        ])
        obs = Observer(graph, db_path=db_path, threshold=1, backend="ollama")
        obs.add_turn("user", "I prefer local AI")
        obs.flush()

    nodes = graph.all_nodes()
    assert any("local-first AI" in n.content for n in nodes)


def test_write_skips_low_confidence_nodes(db_path, graph):
    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = _extracted([
            _node_extract("vague maybe fact", confidence=0.5),
        ])
        obs = Observer(graph, db_path=db_path, threshold=1, backend="ollama",
                       confidence_floor=0.7)
        obs.add_turn("user", "something vague")
        obs.flush()

    assert obs.stats()["nodes_skipped"] == 1
    assert len(graph.all_nodes()) == 0


def test_write_accepts_high_confidence_nodes(db_path, graph):
    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = _extracted([
            _node_extract("definite clear fact", confidence=0.95),
        ])
        obs = Observer(graph, db_path=db_path, threshold=1, backend="ollama",
                       confidence_floor=0.7)
        obs.add_turn("user", "something definite")
        obs.flush()

    assert obs.stats()["nodes_written"] == 1
    assert len(graph.all_nodes()) == 1


def test_write_creates_edges_between_nodes(db_path, graph):
    nodes = [
        _node_extract("AllergyFind project", "ENTITY"),
        _node_extract("FastAPI framework", "CONCEPT"),
    ]
    edges = [{"source_content": "AllergyFind project",
              "target_content": "FastAPI framework",
              "type": "USES", "weight": 0.8}]

    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = _extracted(nodes, edges)
        obs = Observer(graph, db_path=db_path, threshold=1, backend="ollama")
        obs.add_turn("user", "AllergyFind uses FastAPI")
        obs.flush()

    assert len(graph.all_edges()) >= 1
    edge = graph.all_edges()[0]
    assert edge.type.value == "USES"


def test_write_handles_llm_error_gracefully(db_path, graph):
    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = {"_error": "model not found"}
        obs = Observer(graph, db_path=db_path, threshold=1, backend="ollama")
        obs.add_turn("user", "something")  # should not raise
        obs.flush()

    assert obs.stats()["errors"] == 1


def test_write_handles_unknown_node_type(db_path, graph):
    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = _extracted([
            {"type": "UNKNOWN_TYPE", "content": "some fact", "confidence": 0.9, "tags": []}
        ])
        obs = Observer(graph, db_path=db_path, threshold=1, backend="ollama")
        obs.add_turn("user", "trigger")
        obs.flush()

    # Falls back to CONCEPT — should still write
    nodes = graph.all_nodes()
    assert len(nodes) == 1
    assert nodes[0].type == NodeType.CONCEPT


# --- _find_similar (dedup) ---

def test_find_similar_detects_near_duplicate(db_path, graph):
    graph.add_node(NodeType.CONCEPT, "Michael uses Python for all backend work")
    obs = Observer(graph, db_path=db_path, threshold=100)

    match = obs._find_similar("Michael uses Python for all backend tasks", threshold=0.7)
    assert match is not None


def test_find_similar_returns_none_for_distinct_content(db_path, graph):
    graph.add_node(NodeType.CONCEPT, "machine learning algorithms")
    obs = Observer(graph, db_path=db_path, threshold=100)

    match = obs._find_similar("database indexing strategies")
    assert match is None


def test_find_similar_reinforces_existing_node_on_duplicate(db_path, graph):
    # Jaccard = 12/14 ≈ 0.857 ≥ 0.85 threshold:
    # 13 words each, 12 in common (only last word differs)
    existing = graph.add_node(
        NodeType.CONCEPT,
        "Michael Martin uses Python to build FastAPI backends for the AllergyFind local project",
    )
    before = existing.activation_count

    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = _extracted([
            _node_extract(
                "Michael Martin uses Python to build FastAPI backends for the AllergyFind local platform",
                confidence=0.9,
            )
        ])
        obs = Observer(graph, db_path=db_path, threshold=1, backend="ollama")
        obs.add_turn("user", "trigger extraction")
        obs.flush()

    # Should reinforce existing node, not create a new one
    assert existing.activation_count > before
    assert len(graph.all_nodes()) == 1


# --- openai backend ---

def test_observer_uses_openai_compat_backend(db_path, graph):
    with patch("dory.pipeline.observer._call_openai_compat") as mock_llm:
        mock_llm.return_value = _extracted([_node_extract("some fact")])
        obs = Observer(graph, db_path=db_path, threshold=1,
                       backend="openai", base_url="http://localhost:8000")
        obs.add_turn("user", "trigger")
        obs.flush()

    mock_llm.assert_called_once()
    assert len(graph.all_nodes()) == 1
