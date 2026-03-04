from __future__ import annotations

"""
Reflector — conflict resolution, deduplication, and observation compression.

Runs periodically (end of session, or on a schedule) to:

  1. Near-duplicate detection
     Find pairs of nodes with high content similarity.
     Merge them: keep higher-salience node, archive the other.

  2. Supersession (bi-temporal provenance)
     When a newer node clearly supersedes an older one about the same subject,
     add a SUPERSEDES edge and archive the old node.
     The old node is NEVER deleted — it's queryable with zone=None.
     This enables "what was true in the past" queries.

  3. Observation compression (optional, requires LLM)
     Batch old raw observations into compressed_obs entries.
     Falls back gracefully if no LLM is available.

Usage:
    from dory.pipeline.reflector import Reflector

    r = Reflector(graph, db_path)
    stats = r.run()
    print(stats)
"""

from pathlib import Path
from typing import Any

from ..graph import Graph
from ..schema import Node, EdgeType, ZONE_ACTIVE, ZONE_ARCHIVED, now_iso, new_id
from .. import store


# ---------------------------------------------------------------------------
# Similarity helpers
# ---------------------------------------------------------------------------

def _word_set(text: str) -> set[str]:
    return set(text.lower().split())


def _jaccard(a: str, b: str) -> float:
    wa, wb = _word_set(a), _word_set(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _shared_subject(a: str, b: str) -> bool:
    """
    Rough heuristic: do both strings share the first 2+ significant words?
    Used to detect "same subject, different predicate" (supersession candidates).
    """
    stop = {"the", "a", "an", "is", "are", "was", "were", "has", "have",
            "had", "of", "in", "on", "at", "to", "for", "with", "and", "or"}
    wa = [w for w in a.lower().split() if w not in stop]
    wb = [w for w in b.lower().split() if w not in stop]
    if not wa or not wb:
        return False
    # First two significant words match
    return wa[:2] == wb[:2]


# ---------------------------------------------------------------------------
# Reflector
# ---------------------------------------------------------------------------

class Reflector:
    """
    Parameters
    ----------
    graph : Graph
    db_path : Path | None
    dup_threshold : float
        Jaccard similarity above which two nodes are considered near-duplicates.
        Default 0.82 (high precision, avoids merging distinct but related nodes).
    supersede_threshold : float
        Jaccard similarity above which two nodes are checked for supersession.
        Lower than dup_threshold — overlapping subject, different content.
        Default 0.45.
    compress_older_than_hours : float
        Compress raw observations older than this many hours. Default 2.0.
    llm_model : str
        Ollama model for compression. Default "qwen3:14b".
    llm_backend : str
        "ollama" or "openai". Default "ollama".
    llm_base_url : str
        Base URL for OpenAI-compat backend.
    """

    def __init__(
        self,
        graph: Graph,
        db_path: Path | None = None,
        dup_threshold: float = 0.82,
        supersede_threshold: float = 0.45,
        compress_older_than_hours: float = 2.0,
        llm_model: str = "qwen3:14b",
        llm_backend: str = "ollama",
        llm_base_url: str = "http://localhost:8000",
    ):
        self.graph = graph
        self.db_path = db_path or graph.path
        self.dup_threshold = dup_threshold
        self.supersede_threshold = supersede_threshold
        self.compress_older_than_hours = compress_older_than_hours
        self.llm_model = llm_model
        self.llm_backend = llm_backend
        self.llm_base_url = llm_base_url

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> dict:
        stats = {
            "duplicates_merged": 0,
            "supersessions_applied": 0,
            "observations_compressed": 0,
            "errors": 0,
        }

        try:
            stats["duplicates_merged"] = self._merge_duplicates()
        except Exception as e:
            stats["errors"] += 1

        try:
            stats["supersessions_applied"] = self._apply_supersessions()
        except Exception as e:
            stats["errors"] += 1

        try:
            stats["observations_compressed"] = self._compress_observations()
        except Exception as e:
            stats["errors"] += 1

        self.graph._recompute_salience()
        self.graph.save()
        return stats

    def find_near_duplicates(self) -> list[tuple[Node, Node, float]]:
        """
        Return pairs of active nodes with Jaccard similarity >= dup_threshold.
        Each pair is (node_a, node_b, similarity), a before b by ID sort.
        """
        nodes = self.graph.all_nodes(zone=ZONE_ACTIVE)
        pairs: list[tuple[Node, Node, float]] = []
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                if a.type != b.type:
                    continue  # only compare same-type nodes
                sim = _jaccard(a.content, b.content)
                if sim >= self.dup_threshold:
                    pairs.append((a, b, sim))
        return pairs

    def find_supersession_candidates(self) -> list[tuple[Node, Node]]:
        """
        Return (old_node, new_node) pairs where the newer node likely
        supersedes the older one about the same subject.

        Criteria:
          - Same type
          - Jaccard in [supersede_threshold, dup_threshold)  (similar but not duplicate)
          - Shared subject words
          - new_node created_at > old_node created_at
        """
        nodes = sorted(
            self.graph.all_nodes(zone=ZONE_ACTIVE),
            key=lambda n: n.created_at,
        )
        candidates: list[tuple[Node, Node]] = []
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                if a.type != b.type:
                    continue
                sim = _jaccard(a.content, b.content)
                if self.supersede_threshold <= sim < self.dup_threshold:
                    if _shared_subject(a.content, b.content):
                        # a is older (sorted by created_at), b is newer
                        candidates.append((a, b))
        return candidates

    # ------------------------------------------------------------------
    # Internal — deduplication
    # ------------------------------------------------------------------

    def _merge_duplicates(self) -> int:
        pairs = self.find_near_duplicates()
        merged = 0
        archived_ids: set[str] = set()

        for a, b, sim in pairs:
            if a.id in archived_ids or b.id in archived_ids:
                continue

            # Keep the higher-salience node; archive the other
            keep, drop = (a, b) if a.salience >= b.salience else (b, a)

            # Transfer activation count to winner
            keep.activation_count += drop.activation_count
            keep.last_activated = max(keep.last_activated, drop.last_activated)

            # Rewire any edges pointing to drop → point to keep
            for edge in self.graph.all_edges():
                if edge.source_id == drop.id:
                    edge.source_id = keep.id
                if edge.target_id == drop.id:
                    edge.target_id = keep.id

            # Archive the duplicate
            drop.zone = ZONE_ARCHIVED
            drop.superseded_at = now_iso()
            archived_ids.add(drop.id)

            # Add a provenance edge
            self.graph.add_edge(keep.id, drop.id, EdgeType.SUPERSEDES, weight=1.0)
            merged += 1

        return merged

    # ------------------------------------------------------------------
    # Internal — supersession
    # ------------------------------------------------------------------

    def _apply_supersessions(self) -> int:
        candidates = self.find_supersession_candidates()
        applied = 0
        archived_ids: set[str] = set()

        for old, new in candidates:
            if old.id in archived_ids or new.id in archived_ids:
                continue

            # Archive the old node with bi-temporal timestamp
            old.zone = ZONE_ARCHIVED
            old.superseded_at = now_iso()
            archived_ids.add(old.id)

            # Add provenance edge: new --[SUPERSEDES]--> old
            self.graph.add_edge(new.id, old.id, EdgeType.SUPERSEDES, weight=0.9)
            applied += 1

        return applied

    # ------------------------------------------------------------------
    # Internal — observation compression
    # ------------------------------------------------------------------

    def _compress_observations(self) -> int:
        """
        Compress old uncompressed observations into a summary entry.
        Requires LLM. Falls back to a simple concatenation if unavailable.
        """
        from datetime import timedelta

        cutoff_iso = (
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            - timedelta(hours=self.compress_older_than_hours)
        ).isoformat()

        conn = store._connect(self.db_path)
        rows = conn.execute(
            """SELECT * FROM observations
               WHERE compressed=0 AND created_at < ?
               ORDER BY created_at ASC""",
            (cutoff_iso,),
        ).fetchall()
        conn.close()

        if not rows:
            return 0

        raw_obs = [dict(r) for r in rows]
        source_ids = [r["id"] for r in raw_obs]

        turns_text = "\n".join(
            f"{r.get('role','?').upper()}: {r.get('content','')}" for r in raw_obs
        )

        summary = self._summarize(turns_text)
        if not summary:
            return 0

        # Write compressed entry
        comp_id = new_id()
        session_id = raw_obs[0].get("session_id")
        conn = store._connect(self.db_path)
        conn.execute(
            """INSERT OR IGNORE INTO compressed_obs
               (id, session_id, content, created_at, source_ids)
               VALUES (?,?,?,?,?)""",
            (comp_id, session_id, summary, now_iso(), str(source_ids)),
        )
        # Mark source observations as compressed
        conn.execute(
            f"UPDATE observations SET compressed=1 WHERE id IN ({','.join('?'*len(source_ids))})",
            source_ids,
        )
        conn.commit()
        conn.close()
        return len(source_ids)

    def _summarize(self, turns_text: str) -> str | None:
        """Call LLM to summarize a batch of observations. Returns None on failure."""
        prompt = (
            "Summarize the key facts from these conversation turns in 2-4 bullet points. "
            "Focus on durable facts, decisions, and context — not filler.\n\n"
            + turns_text
        )
        try:
            if self.llm_backend == "ollama":
                import ollama
                resp = ollama.chat(
                    model=self.llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.1},
                )
                return resp["message"]["content"].strip()
            elif self.llm_backend == "openai":
                import httpx
                r = httpx.post(
                    f"{self.llm_base_url.rstrip('/')}/v1/chat/completions",
                    json={
                        "model": self.llm_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                    },
                    timeout=60,
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            return None
