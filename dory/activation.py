from __future__ import annotations

from .graph import Graph
from .schema import now_iso


def find_seeds(query: str, graph: Graph) -> list[str]:
    """
    Return node IDs ranked by relevance to the query.

    Priority order:
      1. FTS5 BM25 search (best recall, handles partial terms)
      2. Vector KNN search (semantic similarity, if Ollama running)
      3. Substring fallback (always works, no dependencies)

    Results are deduplicated and merged, with FTS hits ranked first.
    """
    from . import store, vector

    seen: dict[str, int] = {}  # node_id → score (lower = better rank)

    # 1. FTS BM25
    fts_ids = store.search_fts(query, graph.path)
    for rank, nid in enumerate(fts_ids):
        if nid in graph._nodes:
            seen[nid] = rank

    # 2. Vector KNN (if available)
    if vector.available():
        vec_ids = vector.knn_search(query, graph.path)
        for rank, nid in enumerate(vec_ids):
            if nid in graph._nodes and nid not in seen:
                seen[nid] = len(fts_ids) + rank

    # 3. Substring fallback for anything not caught above
    if not seen:
        terms = query.lower().split()
        for node in graph.all_nodes():
            text = (node.content + " " + " ".join(node.tags)).lower()
            hits = sum(1 for t in terms if t in text)
            if hits:
                seen[node.id] = -hits  # negative so higher hits = lower score

    return sorted(seen, key=lambda nid: seen[nid])


def spread(
    seed_ids: list[str],
    graph: Graph,
    depth: int = 3,
    depth_decay: float = 0.5,
    threshold: float = 0.05,
) -> dict[str, float]:
    """
    Spread activation from seed nodes outward through the graph.
    Returns {node_id: activation_level} for all nodes above threshold.
    Activation received = source_activation × edge_weight × depth_decay per hop.
    """
    activation: dict[str, float] = {sid: 1.0 for sid in seed_ids}
    frontier: dict[str, float] = dict(activation)

    traversed_edges: set[str] = set()

    for _ in range(depth):
        next_frontier: dict[str, float] = {}
        for node_id, level in frontier.items():
            for edge in graph.edges_for_node(node_id):
                neighbor_id = (
                    edge.target_id if edge.source_id == node_id else edge.source_id
                )
                received = level * edge.weight * depth_decay
                if received >= threshold:
                    traversed_edges.add(edge.id)
                    current = activation.get(neighbor_id, 0.0)
                    new_val = min(1.0, current + received)
                    if new_val > current:
                        activation[neighbor_id] = new_val
                        next_frontier[neighbor_id] = new_val
        frontier = next_frontier
        if not frontier:
            break

    # Record activation on touched nodes and traversed edges
    now = now_iso()
    for node_id, level in activation.items():
        if level >= threshold:
            node = graph.get_node(node_id)
            if node:
                node.activation_count += 1
                node.last_activated = now

    for edge in graph.all_edges():
        if edge.id in traversed_edges:
            edge.activation_count += 1
            edge.last_activated = now

    return {nid: v for nid, v in activation.items() if v >= threshold}


def serialize(activated: dict[str, float], graph: Graph, max_nodes: int = 20) -> str:
    """Convert activated subgraph to a natural language context block."""
    if not activated:
        return "(no relevant memories found)"

    ranked = sorted(
        activated.items(),
        key=lambda kv: (
            kv[1],
            graph.get_node(kv[0]).salience if graph.get_node(kv[0]) else 0,
        ),
        reverse=True,
    )[:max_nodes]

    lines = []
    for node_id, level in ranked:
        node = graph.get_node(node_id)
        if not node:
            continue
        core_marker = " [CORE]" if node.is_core else ""
        lines.append(f"- [{node.type.value}{core_marker}] {node.content}")

    # Include edges between activated nodes
    activated_ids = set(activated)
    edge_lines = []
    seen: set[tuple] = set()
    for edge in graph.all_edges():
        if edge.source_id in activated_ids and edge.target_id in activated_ids:
            key = (edge.source_id, edge.target_id, edge.type.value)
            if key not in seen:
                src = graph.get_node(edge.source_id)
                tgt = graph.get_node(edge.target_id)
                if src and tgt:
                    edge_lines.append(
                        f"  {src.content} --[{edge.type.value}]--> {tgt.content}"
                    )
                    seen.add(key)

    result = "Activated memories:\n" + "\n".join(lines)
    if edge_lines:
        result += "\n\nRelationships:\n" + "\n".join(edge_lines[:15])
    return result
