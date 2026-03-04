from __future__ import annotations

"""
Decayer — principled memory decay with three visibility zones.

Every node gets a decay score based on:
  - Recency:   how recently it was activated (exponential decay)
  - Frequency: how often it has been activated (logarithmic boost)
  - Relevance: score from last retrieval (rolling average)

Based on the score, nodes move between three zones:
  active   → retrieved normally in all queries
  archived → invisible to normal queries; accessible on explicit request
  expired  → completely invisible; kept for provenance only

Core memories (is_core=True) are shielded from archival/expiry unless
their salience drops dramatically — they decay slower.

Nothing is ever deleted. Zone changes are reversible.

Usage:
    from dory.pipeline.decayer import Decayer, DecayConfig

    cfg = DecayConfig()                  # defaults
    d = Decayer(graph, config=cfg)
    stats = d.run()
    print(stats)  # {"scored": 53, "archived": 2, "expired": 0, "restored": 1}
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..graph import Graph
from ..schema import Node, ZONE_ACTIVE, ZONE_ARCHIVED, ZONE_EXPIRED, now_iso


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class DecayConfig:
    # Decay rate λ: higher = faster decay. Default half-life ≈ 14 days
    lambda_recency: float = 0.05

    # Salience component weights (must sum to 1.0)
    recency_weight: float = 0.4
    frequency_weight: float = 0.35
    relevance_weight: float = 0.25

    # Zone thresholds
    active_floor: float = 0.15    # below this → archived
    archive_floor: float = 0.04   # below this → expired

    # Core memory protection: multiply active_floor by this factor for core nodes
    # i.e. core nodes need a much lower score before they get archived
    core_shield: float = 0.3

    # Restored: if an archived/expired node gets activated, move it back to active
    restore_on_activation: bool = True

    # Minimum activations before decay can archive a node (prevents new nodes
    # from being immediately archived due to low frequency score)
    min_activations_before_archive: int = 2


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _days_since(iso_ts: str) -> float:
    try:
        last = datetime.fromisoformat(iso_ts)
        return (datetime.now(timezone.utc) - last).total_seconds() / 86400
    except Exception:
        return 999.0


def score_node(node: Node, cfg: DecayConfig, max_activations: int = 1) -> float:
    """
    Compute decay score in [0.0, 1.0].
    Higher = more alive. Lower = candidate for archival/expiry.
    """
    days = _days_since(node.last_activated)
    recency = math.exp(-cfg.lambda_recency * days)

    freq = math.log(node.activation_count + 1) / math.log(max(max_activations, 2) + 1)

    # relevance: use salience as a proxy until retrieval scoring is wired in
    relevance = node.salience

    return (
        cfg.recency_weight   * recency
      + cfg.frequency_weight * freq
      + cfg.relevance_weight * relevance
    )


# ---------------------------------------------------------------------------
# Decayer
# ---------------------------------------------------------------------------

class Decayer:
    def __init__(self, graph: Graph, config: DecayConfig | None = None):
        self.graph = graph
        self.cfg = config or DecayConfig()

    def run(self) -> dict:
        """
        Score all nodes and move them between zones as needed.
        Returns stats dict.
        """
        all_nodes = list(self.graph._nodes.values())
        if not all_nodes:
            return {"scored": 0, "archived": 0, "expired": 0, "restored": 0}

        max_act = max((n.activation_count for n in all_nodes), default=1) or 1

        stats = {"scored": 0, "archived": 0, "expired": 0, "restored": 0}

        for node in all_nodes:
            decay_score = score_node(node, self.cfg, max_act)
            stats["scored"] += 1

            # Restore: if node was recently activated and is archived/expired
            if self.cfg.restore_on_activation and node.zone != ZONE_ACTIVE:
                days = _days_since(node.last_activated)
                if days < 1.0:  # activated within the last day
                    node.zone = ZONE_ACTIVE
                    stats["restored"] += 1
                    continue

            # Skip freshly created nodes
            if node.activation_count < self.cfg.min_activations_before_archive:
                continue

            # Determine effective floor for this node
            if node.is_core:
                effective_active_floor = self.cfg.active_floor * self.cfg.core_shield
                effective_archive_floor = self.cfg.archive_floor * self.cfg.core_shield
            else:
                effective_active_floor = self.cfg.active_floor
                effective_archive_floor = self.cfg.archive_floor

            current_zone = node.zone

            if decay_score < effective_archive_floor:
                if current_zone != ZONE_EXPIRED:
                    node.zone = ZONE_EXPIRED
                    node.is_core = False  # can't be core if expired
                    stats["expired"] += 1
            elif decay_score < effective_active_floor:
                if current_zone == ZONE_ACTIVE:
                    node.zone = ZONE_ARCHIVED
                    stats["archived"] += 1
                elif current_zone == ZONE_EXPIRED:
                    # Score improved (e.g. after restore), bump back to archived
                    node.zone = ZONE_ARCHIVED
                    stats["restored"] += 1
            else:
                if current_zone != ZONE_ACTIVE:
                    node.zone = ZONE_ACTIVE
                    stats["restored"] += 1

        self.graph._recompute_salience()
        self.graph.save()
        return stats

    def scores(self) -> list[dict]:
        """Return decay scores for all nodes — useful for inspection/debugging."""
        all_nodes = list(self.graph._nodes.values())
        if not all_nodes:
            return []
        max_act = max((n.activation_count for n in all_nodes), default=1) or 1
        result = []
        for n in sorted(all_nodes, key=lambda x: score_node(x, self.cfg, max_act), reverse=True):
            result.append({
                "id": n.id,
                "zone": n.zone,
                "is_core": n.is_core,
                "score": round(score_node(n, self.cfg, max_act), 4),
                "days_since_activation": round(_days_since(n.last_activated), 1),
                "activation_count": n.activation_count,
                "content": n.content[:60],
            })
        return result
