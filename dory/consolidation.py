from __future__ import annotations

from datetime import datetime, timezone

from .graph import Graph
from .schema import now_iso


def _days_since(iso_timestamp: str) -> float:
    try:
        last = datetime.fromisoformat(iso_timestamp)
        return (datetime.now(timezone.utc) - last).total_seconds() / 86400
    except Exception:
        return 0.0


def strengthen(traversed_edge_ids: list[str], graph: Graph, delta: float = 0.05) -> None:
    """Reinforce edges that were traversed during a session."""
    now = now_iso()
    for edge in graph.all_edges():
        if edge.id in traversed_edge_ids:
            edge.weight = min(1.0, edge.weight + delta)
            edge.activation_count += 1
            edge.last_activated = now


def decay(graph: Graph) -> None:
    """Decay all edge weights proportional to time since last activation."""
    for edge in graph.all_edges():
        days = _days_since(edge.last_activated)
        edge.weight = max(0.0, edge.weight - edge.decay_rate * days)


def prune(graph: Graph, min_weight: float = 0.05) -> int:
    """Remove edges that have decayed below the minimum weight."""
    to_remove = [eid for eid, e in graph._edges.items() if e.weight < min_weight]
    for eid in to_remove:
        del graph._edges[eid]
    return len(to_remove)


def promote_core(graph: Graph, threshold: float = 0.65) -> list[str]:
    """Flag high-salience nodes as core memories."""
    promoted = []
    for node in graph.all_nodes():
        if not node.is_core and node.salience >= threshold:
            node.is_core = True
            promoted.append(node.id)
    return promoted


def demote_core(graph: Graph, threshold: float = 0.25) -> list[str]:
    """Remove core flag from nodes whose salience has fallen."""
    demoted = []
    for node in graph.all_nodes():
        if node.is_core and node.salience < threshold:
            node.is_core = False
            demoted.append(node.id)
    return demoted


def run(graph: Graph) -> dict:
    """Full consolidation pass: decay → prune → promote/demote → recompute salience."""
    decay(graph)
    pruned = prune(graph)
    promoted = promote_core(graph)
    demoted = demote_core(graph)
    graph._recompute_salience()
    graph.save()
    return {
        "pruned_edges": pruned,
        "promoted_core": len(promoted),
        "demoted_core": len(demoted),
    }
