"""
Multi-agent shared memory for Dory.

SharedMemoryPool wraps a single Dory graph with thread-safe reads and writes,
enabling multiple agents to share a common memory store. Agent attribution is
tracked via tags so per-agent and cross-agent queries both work.

SQLite handles read concurrency natively in WAL mode. Writes are serialized
via a threading.RLock to prevent partial-write conflicts.

Usage:
    from dory.adapters.multi_agent import SharedMemoryPool

    pool = SharedMemoryPool("shared.db")

    # Agent 1 learns something
    node_id = pool.observe("AllergyFind uses PostgreSQL", agent_id="planner")

    # Agent 2 retrieves the whole pool
    context = pool.query("database stack", agent_id="coder")

    # Any agent can link nodes
    pool.link(node_id_a, node_id_b, "RELATED_TO", agent_id="planner")

    # End of run: consolidate everything
    stats = pool.consolidate()
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ..graph import Graph
from ..schema import NodeType, EdgeType
from .. import session as _session
from .. import consolidation as _consolidation


class SharedMemoryPool:
    """
    Thread-safe Dory graph shared across multiple agents.

    All writes are serialized via an RLock. Reads (query) do not lock
    so they can run concurrently with each other.

    Agent attribution is stored as a tag ``agent:<agent_id>`` on each node,
    allowing both per-agent filtering and global cross-agent queries.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._graph = Graph(path=self._path)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Write operations (serialized)
    # ------------------------------------------------------------------

    def observe(
        self,
        content: str,
        node_type: str = "CONCEPT",
        tags: list[str] | None = None,
        agent_id: str | None = None,
    ) -> str:
        """
        Write a memory node, attributed to agent_id if provided.
        Returns the new node ID.
        """
        all_tags = list(tags or [])
        if agent_id:
            all_tags.append(f"agent:{agent_id}")

        with self._lock:
            node_id = _session.observe(
                content=content,
                node_type=NodeType(node_type),
                graph=self._graph,
                tags=all_tags,
            )
            self._graph.save()

        return node_id

    def link(
        self,
        source_id: str,
        target_id: str,
        edge_type: str = "RELATED_TO",
        agent_id: str | None = None,
    ) -> None:
        """Create a typed edge between two nodes."""
        with self._lock:
            _session.link(
                source_id=source_id,
                target_id=target_id,
                edge_type=EdgeType(edge_type),
                graph=self._graph,
            )
            self._graph.save()

    def add_turn(
        self,
        role: str,
        content: str,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """Log a raw conversation turn to the episodic store."""
        sid = session_id or agent_id
        with self._lock:
            obs_id = _session.write_turn(
                content=content,
                graph=self._graph,
                role=role,
                session_id=sid,
            )
        return obs_id

    # ------------------------------------------------------------------
    # Read operations (no lock needed — SQLite handles read concurrency)
    # ------------------------------------------------------------------

    def query(
        self,
        topic: str,
        agent_id: str | None = None,
    ) -> str:
        """
        Query the shared memory pool.

        If agent_id is provided, results are filtered to nodes tagged with
        that agent OR nodes with no agent tag (shared pool entries).
        Otherwise returns the full cross-agent context.
        """
        if not agent_id:
            return _session.query(topic, self._graph)

        # Build the set of allowed node IDs: this agent's nodes + untagged shared nodes.
        # Node attribution is stored as tags — filtering must happen at the graph level,
        # not on rendered string output (tags are not included in the serialized context).
        allowed: set[str] = {
            n.id for n in self._graph.all_nodes()
            if not any(t.startswith("agent:") for t in n.tags)
            or f"agent:{agent_id}" in n.tags
        }

        from .. import activation as _act
        seeds = [nid for nid in _act.find_seeds(topic, self._graph) if nid in allowed]
        if not seeds:
            return "(no relevant memories found)"
        activated = {
            nid: lvl
            for nid, lvl in _act.spread(seeds[:8], self._graph).items()
            if nid in allowed
        }
        return _act.serialize(activated, self._graph) if activated else "(no relevant memories found)"

    def get_agent_nodes(self, agent_id: str) -> list[Any]:
        """Return all active nodes written by a specific agent."""
        tag = f"agent:{agent_id}"
        return [n for n in self._graph.all_nodes() if tag in n.tags]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def consolidate(self) -> dict:
        """Run decay, dedup, and conflict resolution across the shared graph."""
        with self._lock:
            stats = _consolidation.run(self._graph)
            self._graph.save()
        return stats

    @property
    def graph(self) -> Graph:
        """Direct access to the underlying graph (use with care in multi-agent context)."""
        return self._graph
