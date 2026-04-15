"""
Dory MCP Server — exposes Dory memory tools to any MCP-compatible AI client.

This module contains the server definition. Use dory_mcp.py as the entry point,
or run via the installed `dory-mcp` script.
"""

from __future__ import annotations

import os
from pathlib import Path

from importlib.metadata import version as _pkg_version
from mcp.server.fastmcp import FastMCP

from .graph import Graph
from .schema import NodeType
from .store import DEFAULT_GRAPH_PATH
from . import session
from .visualize import open_visualization


def _db_path() -> Path:
    env = os.environ.get("DORY_DB_PATH")
    return Path(env) if env else DEFAULT_GRAPH_PATH


def _graph() -> Graph:
    """Load a fresh Graph instance from the configured database path."""
    return Graph(path=_db_path())


try:
    _version = _pkg_version("dory-memory")
except Exception:
    _version = "0.0.0"

mcp = FastMCP(
    "Dory Memory",
    instructions=(
        "Dory is a persistent memory graph for AI agents. "
        "Use dory_query at the start of a session to load relevant context. "
        "Use dory_observe during a session to store new facts, preferences, or decisions. "
        "Use dory_consolidate at the end of a session to decay old memories and resolve conflicts."
    ),
)


@mcp.tool()
def dory_query(topic: str, reference_date: str = "") -> str:
    """
    Query the Dory memory graph using spreading activation.

    Returns relevant memories and relationships for the given topic.
    Call this at the start of a session or when switching to a new topic.

    Retrieved memories are contextual hints ranked by relevance and recency.
    Use your judgment about which memories apply to the current question —
    not every retrieved memory needs to be referenced in your response.

    Args:
        topic: Natural language description of what you want to recall.
        reference_date: Optional ISO date (YYYY-MM-DD) to use as "today" for
            duration calculations (e.g. "how long have I worked at X"). Pass the
            question date here when answering temporal questions.
    """
    graph = _graph()
    result = session.query(topic, graph, reference_date=reference_date)
    graph.save()
    return result


@mcp.tool()
def dory_observe(content: str, node_type: str = "CONCEPT") -> str:
    """
    Store a new memory in the Dory graph.

    Use this when you learn something worth remembering across sessions:
    user preferences, project decisions, key facts, or important context.

    Args:
        content: The memory to store, as a natural language statement.
        node_type: Memory category — one of ENTITY, CONCEPT, EVENT, PREFERENCE, BELIEF.
                   Defaults to CONCEPT.
    """
    try:
        ntype = NodeType(node_type.upper())
    except ValueError:
        valid = [t.value for t in NodeType]
        return f"Invalid node_type '{node_type}'. Valid values: {valid}"

    graph = _graph()
    node_id = session.observe(content, ntype, graph)
    graph.save()
    return f"Stored [{ntype.value}]: {content}  (id: {node_id})"


@mcp.tool()
def dory_consolidate() -> str:
    """
    Run end-of-session consolidation on the memory graph.

    Applies decay to old memories, merges near-duplicates, resolves conflicting
    facts, and promotes or demotes core memories based on activation history.
    Call this at the end of a working session.
    """
    graph = _graph()
    result = session.end_session(graph)
    graph.save()
    lines = [
        "Consolidation complete:",
        f"  Archived nodes:    {result['archived_nodes']}",
        f"  Expired nodes:     {result['expired_nodes']}",
        f"  Duplicates merged: {result['duplicates_merged']}",
        f"  Supersessions:     {result['supersessions']}",
        f"  Promoted core:     {result['promoted_core']}",
        f"  Demoted core:      {result['demoted_core']}",
        f"  Pruned edges:      {result['pruned_edges']}",
        f"  Restored nodes:    {result['restored_nodes']}",
    ]
    return "\n".join(lines)


@mcp.tool()
def dory_visualize(include_archived: bool = False) -> str:
    """
    Generate a knowledge graph visualization and open it in a browser.

    Creates a self-contained HTML file showing all memory nodes, their types,
    salience scores, edges, and relationships. Loads D3.js from d3js.org for
    the interactive force-directed graph.

    Args:
        include_archived: If True, also show archived (decayed) nodes in addition
                          to active ones. Defaults to False.
    """
    from .schema import ZONE_ARCHIVED
    zones = ["active", ZONE_ARCHIVED] if include_archived else ["active"]
    graph = _graph()
    output_path = open_visualization(graph, zones=zones, open_browser=True, allow_remote_js=True)
    node_count = len([n for n in graph.all_nodes(zone=None) if n.zone in zones])
    return f"Opened visualization with {node_count} nodes → {output_path}"


@mcp.tool()
def dory_stats() -> str:
    """
    Return current memory graph statistics and core memories.

    Shows node/edge counts and lists the highest-salience core memories —
    the facts Dory considers most important to always keep in context.
    """
    graph = _graph()
    stats = graph.stats()
    lines = [
        f"Nodes: {stats['nodes']}   Edges: {stats['edges']}   Core: {stats['core_nodes']}",
    ]
    core_nodes = sorted(
        [n for n in graph.all_nodes() if n.is_core],
        key=lambda n: n.salience,
        reverse=True,
    )
    if core_nodes:
        lines.append("\nCore memories:")
        for n in core_nodes[:10]:
            lines.append(f"  [{n.type.value}] {n.content}  (salience={n.salience:.2f})")
    return "\n".join(lines)
