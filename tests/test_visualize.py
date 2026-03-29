"""Tests for dory/visualize.py — HTML knowledge graph generation."""
import pytest
from pathlib import Path

from dory.schema import NodeType, EdgeType


def test_render_html_returns_string(graph):
    from dory.visualize import render_html

    graph.add_node(NodeType.ENTITY, "test node")
    html = render_html(graph, zones=["active"])
    assert isinstance(html, str)
    assert "<html" in html.lower()


def test_render_html_embeds_node_content(graph):
    from dory.visualize import render_html

    graph.add_node(NodeType.ENTITY, "AllergyFind platform")
    html = render_html(graph, zones=["active"])
    assert "AllergyFind platform" in html


def test_render_html_empty_graph(graph):
    from dory.visualize import render_html

    html = render_html(graph, zones=["active"])
    assert isinstance(html, str)
    assert len(html) > 100


def test_render_html_safe_default_omits_remote_d3(graph):
    from dory.visualize import render_html

    graph.add_node(NodeType.CONCEPT, "spreading activation")
    html = render_html(graph, zones=["active"])
    assert "https://d3js.org/d3.v7.min.js" not in html
    assert "Local-only mode" in html


def test_render_html_remote_mode_includes_d3(graph):
    from dory.visualize import render_html

    graph.add_node(NodeType.CONCEPT, "spreading activation")
    html = render_html(graph, zones=["active"], allow_remote_js=True)
    assert "https://d3js.org/d3.v7.min.js" in html


def test_open_visualization_writes_file(tmp_path, graph):
    from dory.visualize import open_visualization

    out = tmp_path / "test_graph.html"
    graph.add_node(NodeType.CONCEPT, "visualization test node")
    result_path = open_visualization(graph, output_path=out, zones=["active"], open_browser=False)
    assert Path(result_path).exists()
    content = Path(result_path).read_text()
    assert "visualization test node" in content


def test_open_visualization_returns_path(tmp_path, graph):
    from dory.visualize import open_visualization

    out = tmp_path / "graph.html"
    graph.add_node(NodeType.ENTITY, "test entity")
    result = open_visualization(graph, output_path=out, zones=["active"], open_browser=False)
    assert result is not None


def test_render_html_multiple_node_types(graph):
    from dory.visualize import render_html

    graph.add_node(NodeType.ENTITY, "project alpha")
    graph.add_node(NodeType.CONCEPT, "Python programming language")
    graph.add_node(NodeType.PREFERENCE, "prefers local inference")
    graph.add_node(NodeType.BELIEF, "open models are viable")
    html = render_html(graph, zones=["active"])
    # All node type values should appear in the embedded JSON
    assert "ENTITY" in html
    assert "CONCEPT" in html


def test_render_html_includes_edges(graph):
    from dory.visualize import render_html

    n1 = graph.add_node(NodeType.ENTITY, "project A")
    n2 = graph.add_node(NodeType.CONCEPT, "technology B")
    graph.add_edge(n1.id, n2.id, EdgeType.USES, weight=0.8)
    html = render_html(graph, zones=["active"])
    # Edge source and target IDs should be in the embedded data
    assert n1.id in html
    assert n2.id in html
