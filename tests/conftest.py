import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dory.graph import Graph
from dory.schema import NodeType, EdgeType


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def graph(db_path):
    return Graph(path=db_path)


@pytest.fixture
def populated_graph(graph):
    """Graph with a few nodes and edges for integration-style tests."""
    n1 = graph.add_node(NodeType.ENTITY, "AllergyFind project", tags=["project"])
    n2 = graph.add_node(NodeType.CONCEPT, "FastAPI backend framework", tags=["tech"])
    n3 = graph.add_node(NodeType.PREFERENCE, "Michael prefers local-first AI")
    n4 = graph.add_node(NodeType.BELIEF, "Open models are now viable for most tasks")
    graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.8)
    graph.add_edge(n1.id, n3.id, EdgeType.RELATED_TO, weight=0.6)
    return graph, n1, n2, n3, n4
