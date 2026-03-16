from __future__ import annotations

"""
Prefixer — builds cacheable context blocks for LLM injection.

The core insight (from Mastra's Observational Memory research):
  RAG changes the injected context every turn → cache MISS every turn → full price every turn.
  A stable prefix that only changes when memory actually changes → cache HITs → 4-10x cheaper.

Output is split into two parts:
  prefix  — stable, built from core memories + key relationships
             identical across turns until graph state changes
             → mark this for prompt caching (Anthropic cache_control, OpenAI auto-cache)

  suffix  — per-query, built from spreading activation + recent observations
             small, changes per query
             → inject fresh each turn

Usage:
    from dory.pipeline.prefixer import Prefixer

    p = Prefixer(graph, db_path)
    result = p.build("what are we working on today?")

    # Plain injection
    system_prompt = result.full

    # Anthropic API with cache_control
    messages = result.as_anthropic_messages(user_query="...")

    # OpenAI API (cache is automatic for matching prefixes)
    messages = result.as_openai_messages(user_query="...")
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..graph import Graph
from ..schema import Node, EdgeType
from .. import store
from .. import activation as act


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Token budget (rough: 1 token ≈ 4 chars)
# ---------------------------------------------------------------------------

def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _trim_to_budget(lines: list[str], budget_tokens: int) -> list[str]:
    """Return as many lines as fit within the token budget."""
    out, used = [], 0
    for line in lines:
        cost = _approx_tokens(line)
        if used + cost > budget_tokens:
            break
        out.append(line)
        used += cost
    return out


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class PrefixResult:
    prefix: str   # stable — mark for caching
    suffix: str   # per-query — inject fresh each turn

    @property
    def full(self) -> str:
        """Concatenated context block for simple injection."""
        parts = [p for p in [self.prefix, self.suffix] if p.strip()]
        return "\n\n".join(parts)

    def as_anthropic_messages(self, user_query: str) -> list[dict]:
        """
        Format for the Anthropic API with cache_control on the stable prefix.
        Drop this into the `messages` parameter of client.messages.create().

        Example:
            result = prefixer.build(query)
            response = client.messages.create(
                model="claude-sonnet-4-6",
                messages=result.as_anthropic_messages(user_query),
                ...
            )
        """
        content: list[dict] = []
        if self.prefix.strip():
            content.append({
                "type": "text",
                "text": self.prefix,
                "cache_control": {"type": "ephemeral"},
            })
        dynamic = "\n\n".join(p for p in [self.suffix, user_query] if p.strip())
        if dynamic:
            content.append({"type": "text", "text": dynamic})
        return [{"role": "user", "content": content}]

    def as_openai_messages(self, user_query: str, system: str | None = None) -> list[dict]:
        """
        Format for OpenAI-compatible APIs (Clanker, llama.cpp server, etc.).
        OpenAI caches automatically when the system + prefix prefix matches.
        """
        messages = []
        sys_parts = [p for p in [system, self.prefix] if p and p.strip()]
        if sys_parts:
            messages.append({"role": "system", "content": "\n\n".join(sys_parts)})
        user_parts = [p for p in [self.suffix, user_query] if p and p.strip()]
        if user_parts:
            messages.append({"role": "user", "content": "\n\n".join(user_parts)})
        return messages


# ---------------------------------------------------------------------------
# Prefixer
# ---------------------------------------------------------------------------

class Prefixer:
    """
    Builds stable + dynamic context blocks from the Engram graph.

    Parameters
    ----------
    graph : Graph
        The Engram graph to read from.
    db_path : Path | None
        Path to engram.db. Defaults to graph.path.
    max_prefix_tokens : int
        Approximate token budget for the stable prefix. Default 800.
    max_suffix_tokens : int
        Approximate token budget for the dynamic suffix. Default 400.
    max_recent_obs : int
        How many recent raw observations to include in suffix. Default 6.
    spread_depth : int
        Spreading activation depth for suffix retrieval. Default 3.
    top_non_core : int
        How many high-salience non-core nodes to include in prefix. Default 8.
    """

    def __init__(
        self,
        graph: Graph,
        db_path: Path | None = None,
        max_prefix_tokens: int = 800,
        max_suffix_tokens: int = 400,
        max_recent_obs: int = 6,
        spread_depth: int = 3,
        top_non_core: int = 8,
    ):
        self.graph = graph
        self.db_path = db_path or graph.path
        self.max_prefix_tokens = max_prefix_tokens
        self.max_suffix_tokens = max_suffix_tokens
        self.max_recent_obs = max_recent_obs
        self.spread_depth = spread_depth
        self.top_non_core = top_non_core

        # Cache: only rebuild prefix when graph state changes
        self._prefix_cache: str = ""
        self._prefix_hash: str = ""

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def build(self, query: str = "") -> PrefixResult:
        """
        Build context for the current query.
        Prefix is cached and reused if the graph hasn't changed.
        """
        prefix = self._get_prefix()
        suffix = self._build_suffix(query) if query else ""
        return PrefixResult(prefix=prefix, suffix=suffix)

    def invalidate(self) -> None:
        """Force prefix rebuild on next call. Call after Reflector runs."""
        self._prefix_hash = ""
        self._prefix_cache = ""

    # ------------------------------------------------------------------
    # Stable prefix
    # ------------------------------------------------------------------

    def _graph_hash(self) -> str:
        """Hash of core node IDs + salience scores. Changes when graph changes meaningfully."""
        core = sorted(
            (n.id, round(n.salience, 2))
            for n in self.graph.all_nodes()
            if n.is_core
        )
        raw = str(core).encode()
        return hashlib.md5(raw).hexdigest()[:12]

    def _get_prefix(self) -> str:
        current_hash = self._graph_hash()
        if current_hash == self._prefix_hash and self._prefix_cache:
            return self._prefix_cache  # cache hit

        self._prefix_cache = self._build_prefix()
        self._prefix_hash = current_hash
        return self._prefix_cache

    def _build_prefix(self) -> str:
        all_nodes = self.graph.all_nodes()
        if not all_nodes:
            return ""

        core = sorted(
            [n for n in all_nodes if n.is_core],
            key=lambda n: n.salience,
            reverse=True,
        )
        non_core = sorted(
            [n for n in all_nodes if not n.is_core],
            key=lambda n: n.salience,
            reverse=True,
        )[: self.top_non_core]

        lines: list[str] = ["## Memory — stable context"]

        # Core memories by type
        by_type: dict[str, list[Node]] = {}
        for n in core:
            by_type.setdefault(n.type.value, []).append(n)

        type_labels = {
            "ENTITY": "Entities", "CONCEPT": "Concepts",
            "PREFERENCE": "Preferences", "BELIEF": "Beliefs",
            "EVENT": "Events", "SESSION": "Past sessions",
        }
        for t in ("ENTITY", "CONCEPT", "PREFERENCE", "BELIEF", "EVENT", "SESSION"):
            nodes = by_type.get(t, [])
            if not nodes:
                continue
            lines.append(f"\n### {type_labels[t]}")
            for n in nodes:
                date_hint = ""
                if t in ("EVENT", "SESSION") and n.created_at:
                    d = _fmt_date(n.created_at)
                    if d:
                        date_hint = f" ({d})"
                lines.append(f"- {n.content}{date_hint}")

        # High-salience non-core
        if non_core:
            lines.append("\n### Supporting context")
            for n in non_core:
                date_hint = ""
                if n.type.value in ("EVENT", "SESSION") and n.created_at:
                    d = _fmt_date(n.created_at)
                    if d:
                        date_hint = f" ({d})"
                lines.append(f"- [{n.type.value}]{date_hint} {n.content}")

        # Key relationships involving core nodes
        core_ids = {n.id for n in core}
        rel_lines: list[str] = []
        seen: set[tuple] = set()
        for edge in self.graph.all_edges():
            if edge.source_id in core_ids or edge.target_id in core_ids:
                src = self.graph.get_node(edge.source_id)
                tgt = self.graph.get_node(edge.target_id)
                if src and tgt:
                    key = (edge.source_id, edge.target_id)
                    if key not in seen:
                        if edge.type == EdgeType.SUPERSEDES:
                            date = _fmt_date(src.superseded_at or edge.created_at)
                            date_str = f" (updated {date})" if date else ""
                            rel_lines.append(
                                f"- [KNOWLEDGE UPDATE{date_str}] Previously: {src.content} → Now: {tgt.content}"
                            )
                        else:
                            rel_lines.append(
                                f"- {src.content} → [{edge.type.value}] → {tgt.content}"
                            )
                        seen.add(key)

        if rel_lines:
            lines.append("\n### Relationships")
            lines.extend(rel_lines)

        trimmed = _trim_to_budget(lines, self.max_prefix_tokens)
        return "\n".join(trimmed)

    # ------------------------------------------------------------------
    # Dynamic suffix
    # ------------------------------------------------------------------

    def _build_suffix(self, query: str) -> str:
        lines: list[str] = ["## Memory — relevant to this query"]

        # Spreading activation
        seeds = act.find_seeds(query, self.graph)
        if seeds:
            activated = act.spread(seeds[:5], self.graph, depth=self.spread_depth)
            # Exclude core nodes (already in prefix) unless very highly activated
            core_ids = {n.id for n in self.graph.all_nodes() if n.is_core}
            relevant = {
                nid: score for nid, score in activated.items()
                if nid not in core_ids or score > 0.8
            }
            if relevant:
                ranked = sorted(relevant.items(), key=lambda kv: kv[1], reverse=True)[:8]
                lines.append("\n### Activated")
                for nid, score in ranked:
                    node = self.graph.get_node(nid)
                    if node:
                        date_hint = ""
                        if node.type.value in ("EVENT", "SESSION") and node.created_at:
                            d = _fmt_date(node.created_at)
                            if d:
                                date_hint = f" ({d})"
                        lines.append(f"- [{node.type.value}]{date_hint} {node.content}")

                # Relationships between activated nodes
                activated_ids = set(activated)
                rel_lines: list[str] = []
                seen: set[tuple] = set()
                for edge in self.graph.all_edges():
                    if edge.source_id in activated_ids and edge.target_id in activated_ids:
                        key = (edge.source_id, edge.target_id)
                        if key not in seen:
                            src = self.graph.get_node(edge.source_id)
                            tgt = self.graph.get_node(edge.target_id)
                            if src and tgt:
                                if edge.type == EdgeType.SUPERSEDES:
                                    date = _fmt_date(src.superseded_at or edge.created_at)
                                    date_str = f" (updated {date})" if date else ""
                                    rel_lines.append(
                                        f"- [KNOWLEDGE UPDATE{date_str}] Previously: {src.content} → Now: {tgt.content}"
                                    )
                                else:
                                    rel_lines.append(
                                        f"- {src.content} → [{edge.type.value}] → {tgt.content}"
                                    )
                                seen.add(key)
                if rel_lines:
                    lines.append("\n### Relationships")
                    lines.extend(rel_lines[:6])

        # Recent episodic observations
        recent = store.get_observations(self.db_path, limit=self.max_recent_obs)
        if recent:
            lines.append("\n### Recent observations")
            for obs in reversed(recent):  # chronological order
                role = (obs.get("role") or "?").upper()
                content = (obs.get("content") or "").strip()
                if content.startswith("[LOW_CONFIDENCE"):
                    continue
                lines.append(f"- {role}: {content[:120]}")

        trimmed = _trim_to_budget(lines, self.max_suffix_tokens)
        result = "\n".join(trimmed)

        # If nothing relevant was found beyond the header, return empty
        if result.strip() == "## Memory — relevant to this query":
            return ""
        return result
