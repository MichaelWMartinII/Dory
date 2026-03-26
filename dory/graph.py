from __future__ import annotations

import math
import threading
from datetime import datetime, timezone
from pathlib import Path

from .schema import Node, Edge, NodeType, EdgeType, now_iso, new_id, ZONE_ACTIVE
from . import store


def _recency_score(last_activated: str, half_life_days: float = 14.0) -> float:
    """1.0 if just activated, decays toward 0 with a 14-day half-life."""
    try:
        last = datetime.fromisoformat(last_activated)
        now = datetime.now(timezone.utc)
        delta_days = (now - last).total_seconds() / 86400
        return math.exp(-delta_days * math.log(2) / half_life_days)
    except Exception:
        return 0.0


class Graph:
    def __init__(self, path: Path = store.DEFAULT_GRAPH_PATH):
        self.path = path
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}
        self._dirty: bool = False
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        data = store.load(self.path)
        self._nodes = {n["id"]: Node.from_dict(n) for n in data.get("nodes", [])}
        self._edges = {e["id"]: Edge.from_dict(e) for e in data.get("edges", [])}
        self._dirty = False

    def save(self) -> None:
        with self._lock:
            if self._dirty:
                self._recompute_salience()
                self._dirty = False
            store.save(
                {
                    "nodes": [n.to_dict() for n in self._nodes.values()],
                    "edges": [e.to_dict() for e in self._edges.values()],
                },
                self.path,
            )

    # --- Nodes ---

    def add_node(
        self,
        type: NodeType,
        content: str,
        tags: list[str] | None = None,
    ) -> Node:
        with self._lock:
            now = now_iso()
            node = Node(
                id=new_id(),
                type=type,
                content=content,
                created_at=now,
                last_activated=now,
                tags=tags or [],
            )
            self._nodes[node.id] = node
            self._dirty = True
            return node

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def find_nodes(self, query: str, zone: str | None = ZONE_ACTIVE) -> list[Node]:
        """Substring search across content and tags, filtered by zone."""
        if self._dirty:
            self._recompute_salience()
            self._dirty = False
        terms = query.lower().split()
        results = []
        for node in self._nodes.values():
            if zone and node.zone != zone:
                continue
            text = (node.content + " " + " ".join(node.tags)).lower()
            if all(t in text for t in terms):
                results.append(node)
        return sorted(results, key=lambda n: n.salience, reverse=True)

    def all_nodes(self, zone: str | None = ZONE_ACTIVE) -> list[Node]:
        """Return nodes filtered by zone. Pass zone=None for all zones."""
        if zone is None:
            return list(self._nodes.values())
        return [n for n in self._nodes.values() if n.zone == zone]

    # --- Edges ---

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        type: EdgeType,
        weight: float = 0.8,
        decay_rate: float = 0.02,
    ) -> Edge:
        with self._lock:
            # Reinforce if this typed edge already exists between these nodes
            for edge in self._edges.values():
                if (
                    edge.source_id == source_id
                    and edge.target_id == target_id
                    and edge.type == type
                ):
                    edge.weight = min(1.0, edge.weight + 0.1)
                    edge.activation_count += 1
                    edge.last_activated = now_iso()
                    self._dirty = True
                    return edge

            now = now_iso()
            edge = Edge(
                id=new_id(),
                source_id=source_id,
                target_id=target_id,
                type=type,
                weight=weight,
                created_at=now,
                last_activated=now,
                decay_rate=decay_rate,
            )
            self._edges[edge.id] = edge
            self._dirty = True
            return edge

    def edges_for_node(self, node_id: str) -> list[Edge]:
        return [
            e for e in self._edges.values()
            if e.source_id == node_id or e.target_id == node_id
        ]

    def all_edges(self) -> list[Edge]:
        return list(self._edges.values())

    # --- Salience ---

    def _recompute_salience(
        self,
        alpha: float = 0.3,
        beta: float = 0.4,
        gamma: float = 0.3,
    ) -> None:
        # Called from save() which already holds _lock — no re-acquire needed (RLock is reentrant).
        if not self._nodes:
            return

        # Use all nodes (including archived) for degree computation
        degrees: dict[str, int] = {nid: 0 for nid in self._nodes}
        for edge in self._edges.values():
            if edge.source_id in degrees:
                degrees[edge.source_id] += 1
            if edge.target_id in degrees:
                degrees[edge.target_id] += 1

        max_degree = max(degrees.values()) or 1
        max_activations = max((n.activation_count for n in self._nodes.values()), default=1) or 1

        for node in self._nodes.values():
            connectivity = degrees[node.id] / max_degree
            reinforcement = math.log(node.activation_count + 1) / math.log(max_activations + 1)
            recency = _recency_score(node.last_activated)
            node.salience = alpha * connectivity + beta * reinforcement + gamma * recency

    def stats(self) -> dict:
        all_n = list(self._nodes.values())
        return {
            "nodes": len(all_n),
            "edges": len(self._edges),
            "core_nodes": sum(1 for n in all_n if n.is_core),
            "active":   sum(1 for n in all_n if n.zone == "active"),
            "archived": sum(1 for n in all_n if n.zone == "archived"),
            "expired":  sum(1 for n in all_n if n.zone == "expired"),
        }
