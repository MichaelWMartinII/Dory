from __future__ import annotations

from .graph import Graph
from .schema import NodeType, EdgeType, new_id
from . import activation as act
from . import consolidation
from . import store


def query(topic: str, graph: Graph) -> str:
    """
    Query the graph for context relevant to a topic.
    Returns a context block suitable for injecting into a prompt.
    """
    seeds = act.find_seeds(topic, graph)
    if not seeds:
        return f"(no memories found for: {topic!r})"
    activated = act.spread(seeds[:5], graph)
    graph._recompute_salience()
    return act.serialize(activated, graph)


def observe(
    content: str,
    node_type: NodeType,
    graph: Graph,
    tags: list[str] | None = None,
) -> str:
    """Add a new observation node. Returns the new node ID."""
    node = graph.add_node(type=node_type, content=content, tags=tags or [])
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
