from __future__ import annotations

import re

from .graph import Graph
from .schema import NodeType, EdgeType, new_id
from . import activation as act
from . import consolidation
from . import store

_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "have", "has",
    "had", "do", "does", "did", "will", "would", "should", "may", "might",
    "can", "could", "to", "of", "in", "on", "at", "for", "with", "by", "from",
    "as", "and", "or", "but", "not", "this", "that", "it", "its", "also",
    "more", "than", "just", "very", "all", "any", "one", "two", "get",
    "use", "uses", "used", "using", "new", "add", "adds", "added",
})


def _key_terms(content: str, n: int = 12) -> str:
    """Extract up to n meaningful terms from content for FTS querying."""
    words = re.findall(r"[a-zA-Z]\w*", content)
    seen: set[str] = set()
    result = []
    for w in words:
        lo = w.lower()
        if len(lo) >= 3 and lo not in _STOPWORDS and lo not in seen:
            seen.add(lo)
            result.append(lo)
            if len(result) >= n:
                break
    return " ".join(result)


def _auto_link(new_node_id: str, content: str, graph: Graph, max_links: int = 5, weight: float = 0.5) -> int:
    """
    Find existing nodes related to content via FTS and create CO_OCCURS edges.
    Returns the number of edges created.
    """
    terms = _key_terms(content)
    if not terms:
        return 0
    # FTS5 defaults to AND; use OR so any matching term finds a candidate
    or_query = " OR ".join(terms.split())
    candidates = store.search_fts(or_query, graph.path, limit=max_links + 2)
    linked = 0
    for candidate_id in candidates:
        if candidate_id == new_node_id:
            continue
        if candidate_id not in graph._nodes:
            continue
        graph.add_edge(new_node_id, candidate_id, EdgeType.CO_OCCURS, weight=weight)
        linked += 1
        if linked >= max_links:
            break
    return linked


def query(topic: str, graph: Graph) -> str:
    """
    Query the graph for context relevant to a topic.
    Returns a context block suitable for injecting into a prompt.

    All SESSION nodes are always included — they hold episodic detail that
    may not score highly via spreading activation but is needed for session-
    level recall and temporal reasoning.
    """
    seeds = act.find_seeds(topic, graph)
    activated: dict[str, float] = {}
    if seeds:
        activated = act.spread(seeds[:8], graph)
    graph._recompute_salience()

    # Ensure all SESSION nodes are present (at minimum activation level)
    for node in graph.all_nodes():
        if node.type.value == "SESSION" and node.id not in activated:
            activated[node.id] = 0.1  # low but non-zero so they appear

    return act.serialize(activated, graph, max_nodes=50)


def observe(
    content: str,
    node_type: NodeType,
    graph: Graph,
    tags: list[str] | None = None,
    auto_link: bool = True,
) -> str:
    """Add a new observation node, auto-linking to related nodes. Returns the new node ID."""
    node = graph.add_node(type=node_type, content=content, tags=tags or [])
    if auto_link:
        _auto_link(node.id, content, graph)
    return node.id


def link(
    source_id: str,
    target_id: str,
    edge_type: EdgeType,
    graph: Graph,
    weight: float = 0.8,
) -> None:
    """Create a typed edge between two nodes."""
    graph.add_edge(source_id, target_id, edge_type, weight=weight)


def write_turn(
    content: str,
    graph: Graph,
    role: str = "user",
    session_id: str | None = None,
) -> str:
    """
    Log a raw conversation turn to the episodic observation store.
    Returns the observation ID.
    """
    obs_id = new_id()
    store.write_observation(
        obs_id=obs_id,
        content=content,
        path=graph.path,
        session_id=session_id,
        role=role,
    )
    return obs_id


def end_session(graph: Graph) -> dict:
    """Run consolidation at the end of a session."""
    return consolidation.run(graph)
