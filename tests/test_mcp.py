"""Tests for dory/mcp_server.py — MCP tool functions called directly."""
import pytest

mcp = pytest.importorskip("mcp", reason="mcp package not installed")


@pytest.fixture
def mcp_db(tmp_path, monkeypatch):
    """Redirect MCP tools to a fresh temp DB."""
    db_path = tmp_path / "mcp_test.db"
    monkeypatch.setenv("DORY_DB_PATH", str(db_path))
    return db_path


def test_dory_stats_returns_string(mcp_db):
    from dory.mcp_server import dory_stats

    result = dory_stats()
    assert isinstance(result, str)
    assert "Nodes:" in result
    assert "Edges:" in result


def test_dory_observe_stores_node(mcp_db):
    from dory.mcp_server import dory_observe, dory_stats

    result = dory_observe("Michael prefers local-first AI", "PREFERENCE")
    assert "Stored" in result
    assert "PREFERENCE" in result

    stats = dory_stats()
    assert "Nodes: 1" in stats


def test_dory_observe_concept_default_type(mcp_db):
    from dory.mcp_server import dory_observe

    result = dory_observe("spreading activation is a memory retrieval technique")
    assert "Stored" in result
    assert "CONCEPT" in result


def test_dory_observe_invalid_type_returns_error(mcp_db):
    from dory.mcp_server import dory_observe

    result = dory_observe("some content", "NOT_A_TYPE")
    assert "Invalid" in result


def test_dory_query_returns_string(mcp_db):
    from dory.mcp_server import dory_observe, dory_query

    dory_observe("Michael uses Python for all projects", "CONCEPT")
    result = dory_query("Python development")
    assert isinstance(result, str)


def test_dory_query_empty_graph(mcp_db):
    from dory.mcp_server import dory_query

    result = dory_query("anything")
    assert isinstance(result, str)


def test_dory_consolidate_returns_summary(mcp_db):
    from dory.mcp_server import dory_consolidate

    result = dory_consolidate()
    assert "Consolidation complete" in result
    assert "Pruned edges" in result
    assert "Duplicates merged" in result


def test_dory_stats_reflects_observed_nodes(mcp_db):
    from dory.mcp_server import dory_observe, dory_stats

    dory_observe("AllergyFind is a B2B allergen platform", "ENTITY")
    dory_observe("FastAPI is the web framework used", "CONCEPT")

    stats = dory_stats()
    assert "Nodes: 2" in stats


def test_dory_observe_multiple_nodes_accumulate(mcp_db):
    from dory.mcp_server import dory_observe, dory_stats

    for i in range(5):
        dory_observe(f"distinct memory item number {i}", "CONCEPT")

    stats = dory_stats()
    assert "Nodes: 5" in stats
