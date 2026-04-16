from __future__ import annotations

import re

from .graph import Graph
from .schema import NodeType, EdgeType, new_id
from . import activation as act
from . import consolidation
from . import store
from .sanitize import sanitize_node_content

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


def _parse_session_date(content: str) -> str:
    """Extract YYYY-MM-DD from SESSION content like '[2023-04-10] Session: ...'"""
    m = re.match(r"\[(\d{4}-\d{2}-\d{2})\]", content.strip())
    return m.group(1) if m else "9999-99-99"  # unknown dates sort last






def _serialize_structured(
    activated: dict[str, float],
    graph: Graph,
    max_nodes: int = 50,
    reference_date: str = "",
) -> str:
    """
    Unified context serializer for the v2.0 retrieval path.

    Groups nodes by structural role so the LLM can reason about the graph directly
    without the retrieval layer needing to preprocess based on query type:

      - Current Values    — nodes that supersede something; authoritative facts
      - Knowledge Updates — explicit supersession chains (old → new)
      - Preferences       — PREFERENCE nodes (all, salience-ranked)
      - Procedures        — PROCEDURE nodes
      - Working           — WORKING nodes (ephemeral, in-session facts)
      - Events            — EVENT nodes, chronological
      - Sessions          — SESSION nodes, chronological
      - Session Summaries — SESSION_SUMMARY nodes with embedded counts
      - Context           — ENTITY, CONCEPT, BELIEF; spreading-activation ranked

    Supersession annotations ([SUPERSEDED], [CURRENT VALUE]), duration hints,
    occurrence counts, and salient_counts are all rendered inline so the answerer
    can identify current vs. historical values and answer counting questions from
    the structured data, not prose reconstruction.
    """
    if not activated:
        return "(no relevant memories found)"

    # Pre-compute supersession markers
    superseding_ids: set[str] = set()   # nodes that supersede something (current values)
    superseded_ids: set[str] = set()    # nodes that have been superseded (historical)
    supersession_pairs: list[tuple] = []  # (current_node, old_node) for inline rendering
    refinement_pairs: list[tuple] = []   # (specific_node, base_node) for REFINES rendering
    for edge in graph.all_edges():
        if edge.type == EdgeType.SUPERSEDES:
            superseding_ids.add(edge.source_id)
            superseded_ids.add(edge.target_id)
            src = graph.get_node(edge.source_id)
            tgt = graph.get_node(edge.target_id)
            if src and tgt:
                supersession_pairs.append((src, tgt, edge))
        elif edge.type == EdgeType.REFINES:
            src = graph.get_node(edge.source_id)
            tgt = graph.get_node(edge.target_id)
            if src and tgt:
                refinement_pairs.append((src, tgt))

    floor = act.SALIENCE_FLOOR

    def _node_line(node, level: float = 0.0, prefix: str = "") -> str:
        core_marker = " [CORE]" if node.is_core else ""
        current_marker = " [CURRENT VALUE]" if node.id in superseding_ids else ""
        historical_marker = " [SUPERSEDED]" if node.id in superseded_ids else ""

        date_hint = ""
        if node.type.value == "EVENT" and node.created_at:
            d = act._fmt_date(node.created_at)
            if d:
                date_hint = f" ({d})"

        duration_hint = ""
        if reference_date and node.metadata:
            start_date = node.metadata.get("start_date", "")
            if start_date:
                dur = act._compute_duration_hint(start_date, reference_date)
                if dur:
                    duration_hint = f" ({dur})"

        occurrence_hint = ""
        if node.metadata:
            count = node.metadata.get("occurrence_count", 0)
            amount = node.metadata.get("amount", "")
            if count > 1 and amount:
                occurrence_hint = f" (×{count}, {amount})"
            elif count > 1:
                occurrence_hint = f" (×{count})"
            elif amount:
                occurrence_hint = f" [{amount}]"

        type_label = f"[{node.type.value}{core_marker}{current_marker}{historical_marker}]"
        return f"{prefix}- {type_label}{date_hint}{duration_hint}{occurrence_hint} {node.content}"

    # Bucket nodes into sections
    current_vals: list = []
    preferences: list = []
    procedures: list = []
    working: list = []
    events: list = []
    sessions: list = []
    summaries: list = []
    context_nodes: list = []

    seen_ids: set[str] = set()

    # Always include SESSION, SESSION_SUMMARY, PREFERENCE, and PROCEDURE nodes
    # regardless of activation — these are structurally high-value and should
    # always be available to the answerer without depending on seed quality.
    always_prefs: list = []
    always_procs: list = []
    for node in graph.all_nodes():
        if node.zone != "active":
            continue
        if node.type.value == "SESSION":
            sessions.append(node)
            seen_ids.add(node.id)
        elif node.type.value == "SESSION_SUMMARY":
            summaries.append(node)
            seen_ids.add(node.id)
        elif node.type == NodeType.PREFERENCE:
            always_prefs.append(node)
            seen_ids.add(node.id)
        elif node.type == NodeType.PROCEDURE:
            always_procs.append(node)
            seen_ids.add(node.id)

    # Cap to avoid flooding context — sort by salience descending
    always_prefs.sort(key=lambda n: -n.salience)
    always_procs.sort(key=lambda n: -n.salience)
    always_prefs = always_prefs[:15]
    always_procs = always_procs[:15]
    preferences = [(n, 1.0) for n in always_prefs]
    procedures = [(n, 1.0) for n in always_procs]

    # Bucket activated nodes
    ranked = sorted(
        activated.items(),
        key=lambda kv: (kv[1], graph.get_node(kv[0]).salience if graph.get_node(kv[0]) else 0),
        reverse=True,
    )[:max_nodes]

    for node_id, level in ranked:
        node = graph.get_node(node_id)
        if not node or node.zone != "active" or node_id in seen_ids:
            continue
        if node.activation_count > 0 and node.salience < floor:
            continue
        seen_ids.add(node_id)

        if node.type == NodeType.PREFERENCE:
            pass  # already included via always_prefs
        elif node.type == NodeType.PROCEDURE:
            pass  # already included via always_procs
        elif node.type.value == "WORKING":
            working.append((node, level))
        elif node.type.value == "EVENT":
            events.append((node, level))
        elif node.id in superseding_ids:
            current_vals.append((node, level))
        else:
            context_nodes.append((node, level))

    # Sort sections
    sessions.sort(key=lambda n: _parse_session_date(n.content))
    summaries.sort(key=lambda n: _parse_session_date(n.content), reverse=True)
    events.sort(key=lambda x: (
        x[0].metadata.get("event_date") or x[0].metadata.get("start_date") or x[0].created_at or ""
    ))
    preferences.sort(key=lambda x: -x[1])
    current_vals.sort(key=lambda x: -x[1])
    context_nodes.sort(key=lambda x: -x[1])

    sections = []

    if current_vals:
        lines = ["## Current Values"]
        for node, level in current_vals:
            lines.append(_node_line(node, level))
        sections.append("\n".join(lines))

    # Inline supersession chains: only pairs where both sides are relevant
    relevant_updates = [
        (cur, old, edge) for cur, old, edge in supersession_pairs
        if cur.id in seen_ids or old.id in seen_ids
    ]
    if relevant_updates:
        lines = ["## Knowledge Updates"]
        for cur, old, edge in relevant_updates:
            date = act._fmt_date(old.superseded_at or edge.created_at)
            date_str = f" (updated {date})" if date else ""
            lines.append(f"  [KNOWLEDGE UPDATE{date_str}] Previously: {old.content} → Now: {cur.content}")
        sections.append("\n".join(lines))

    # REFINES chains
    relevant_refinements = [
        (specific, base) for specific, base in refinement_pairs
        if specific.id in seen_ids or base.id in seen_ids
    ]
    if relevant_refinements:
        lines = ["## Elaborations"]
        for specific, base in relevant_refinements:
            lines.append(f"  [ELABORATION] {base.content} → more specifically: {specific.content}")
        sections.append("\n".join(lines))

    if preferences:
        lines = ["## Preferences"]
        for node, level in preferences:
            lines.append(_node_line(node, level))
        sections.append("\n".join(lines))

    if working:
        lines = ["## In Progress (current session)"]
        for node, level in working:
            lines.append(_node_line(node, level))
        sections.append("\n".join(lines))

    if procedures:
        lines = ["## Procedures"]
        for node, level in procedures:
            lines.append(_node_line(node, level))
        sections.append("\n".join(lines))

    if events:
        lines = ["## Events (chronological)"]
        for node, level in events:
            lines.append(_node_line(node, level))
        sections.append("\n".join(lines))

    if summaries:
        lines = ["## Session Summaries (most recent first)"]
        for node in summaries:
            date = node.metadata.get("session_date") or _parse_session_date(node.content)
            text = re.sub(r"^\[\d{4}-\d{2}-\d{2}\]\s+Summary:\s*", "", node.content).strip()
            lines.append(f"\n[{date}]")
            lines.append(f"  {text}")
            counts = node.metadata.get("salient_counts") or {}
            if counts:
                low_conf = set(node.metadata.get("low_confidence_counts") or [])
                parts = []
                for k, v in counts.items():
                    if k in low_conf:
                        parts.append(f"{k}: {v} ⚠")
                    else:
                        parts.append(f"{k}: {v}")
                lines.append(f"  Counts: {', '.join(parts)}")
        sections.append("\n".join(lines))

    if sessions:
        lines = ["## Sessions (chronological)"]
        for node in sessions:
            lines.append(f"- {node.content}")
        sections.append("\n".join(lines))

    if context_nodes:
        lines = ["## Context"]
        for node, level in context_nodes:
            lines.append(_node_line(node, level))
        sections.append("\n".join(lines))

    return "\n\n".join(sections) if sections else "(no relevant memories found)"


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


def query(topic: str, graph: Graph, reference_date: str = "") -> str:
    """
    Query the graph for context relevant to a topic.
    Returns a structured context block suitable for injecting into a prompt.

    Unified retrieval path (v2.0): spreading activation → top-k nodes →
    structured serialization. No routing or query-type branching. The graph
    structure itself (node types, SUPERSEDES edges, chronological ordering,
    salient_counts in SESSION_SUMMARY) makes the context self-describing so
    the answerer can reason about it without preprocessing.

    reference_date: ISO date string (YYYY-MM-DD) used to compute duration hints
    (e.g. "~9 months, since 2023-03-01") for nodes with a start_date in metadata.
    """
    seeds = act.find_seeds(topic, graph)
    activated: dict[str, float] = {}
    if seeds:
        activated = act.spread(seeds[:8], graph)
    graph._recompute_salience()

    return _serialize_structured(activated, graph, max_nodes=50, reference_date=reference_date)


def observe(
    content: str,
    node_type: NodeType,
    graph: Graph,
    tags: list[str] | None = None,
    auto_link: bool = True,
) -> str:
    """Add a new observation node, auto-linking to related nodes. Returns the new node ID."""
    clean, flagged, reason = sanitize_node_content(content)
    all_tags = list(tags or [])
    if flagged:
        all_tags.append("flagged")
        if reason:
            all_tags.append(f"flag_reason:{reason[:64]}")
    node = graph.add_node(type=node_type, content=clean, tags=all_tags)
    if auto_link:
        _auto_link(node.id, clean, graph)
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
