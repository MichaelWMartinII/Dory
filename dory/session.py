from __future__ import annotations

import re
from typing import Literal

from .graph import Graph
from .schema import NodeType, EdgeType, new_id
from . import activation as act
from . import consolidation
from . import store

_EPISODIC_EDGE_TYPES = frozenset({"SUPPORTS_FACT", "MENTIONS"})

_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "have", "has",
    "had", "do", "does", "did", "will", "would", "should", "may", "might",
    "can", "could", "to", "of", "in", "on", "at", "for", "with", "by", "from",
    "as", "and", "or", "but", "not", "this", "that", "it", "its", "also",
    "more", "than", "just", "very", "all", "any", "one", "two", "get",
    "use", "uses", "used", "using", "new", "add", "adds", "added",
})

# Temporal questions ask about order, duration, or relative time between events.
_TEMPORAL_RE = re.compile(
    r"\b(before|after|earlier|earliest|later|latest|prior to|"
    r"how long|how many (?:days?|weeks?|months?|years?)|"
    r"which (?:one )?(?:came|was|happened) (?:first|last|before|after|earlier|later)|"
    r"in what order|chronolog|timeline|when did|more recent|duration|"
    # Relative time: "2 weeks ago", "a month ago", "3 days ago", "two months ago"
    r"(?:\d+|a|an|two|three|four|five|six|several|few|couple\s+of)\s+"
    r"(?:days?|weeks?|months?|years?)\s+ago|"
    # "last Saturday/week/month/two months", "this week/month", "yesterday"
    r"last\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|year|night|"
    r"(?:few|several|two|three|four|five|six|\d+)\s+(?:days?|weeks?|months?|years?))|"
    r"yesterday|today|tonight|"
    r"this\s+(?:week|month|year|morning|evening|afternoon)|"
    r"past\s+(?:few|several|couple\s+of|two|three|four|five|six|\d+)?\s*(?:days?|weeks?|months?|years?)|"
    r"previous\s+(?:week|month|year)|"
    # "which/who X first/last", "what is the order of"
    r"which\b.+\b(?:first|last)\b|"
    r"who\b.+\b(?:first|last)\b|"
    r"the order of|order of the|most recently|"
    # Holiday/calendar anchors
    r"valentine|thanksgiving|christmas|new year)\b",
    re.IGNORECASE,
)

# Aggregation questions ask for counts or exhaustive lists.
_AGGREGATION_RE = re.compile(
    r"\b(how many(?!\s+(?:days?|weeks?|months?|years?))|"
    r"how (?:often|frequently)|list (?:all|every|each)|"
    r"all (?:the )?times?|every time|each time|"
    r"total (?:number|count|times?)|number of times|"
    r"times (?:did|have|has)|occasions?|instances?)\b",
    re.IGNORECASE,
)

# Hybrid questions ask about change or evolution across time — need both layers.
_HYBRID_RE = re.compile(
    r"\b(how has\b|"
    r"has .{1,40} changed|"
    r"changed over|"
    r"over time|"
    r"evolution of|"
    r"progress on|"
    r"then (?:vs?\.?|versus) now|"
    r"compare.{0,20} sessions?|"
    r"across sessions?|"
    r"throughout .{0,20} (?:sessions?|time|weeks?|months?))\b",
    re.IGNORECASE,
)


def _route_query(topic: str) -> Literal["graph", "episodic", "hybrid"]:
    """
    Classify a query into one of three retrieval modes. Deterministic — no LLM call.

    hybrid:   questions about change or evolution across time (need both layers)
    episodic: counts, ordering, specific events, relative time (need session log)
    graph:    preferences, stable facts, beliefs, relationships (default)
    """
    if _HYBRID_RE.search(topic):
        return "hybrid"
    if _AGGREGATION_RE.search(topic) or _TEMPORAL_RE.search(topic):
        return "episodic"
    return "graph"


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


def _get_linked_summaries(
    activated: dict[str, float],
    graph: Graph,
    limit: int = 3,
) -> list:
    """
    Walk SUPPORTS_FACT and MENTIONS edges from activated nodes to find
    SESSION_SUMMARY nodes. Returns up to `limit` summaries, sorted
    most-recent-first, scored by (activation_level × edge_weight).
    """
    scores: dict[str, float] = {}
    for node_id, level in activated.items():
        for edge in graph.edges_for_node(node_id):
            if edge.type.value not in _EPISODIC_EDGE_TYPES:
                continue
            other_id = edge.target_id if edge.source_id == node_id else edge.source_id
            other = graph.get_node(other_id)
            if other and other.type == NodeType.SESSION_SUMMARY:
                scores[other_id] = max(scores.get(other_id, 0.0), level * edge.weight)

    top = sorted(scores.items(), key=lambda x: -x[1])[:limit]
    nodes = [graph.get_node(sid) for sid, _ in top if graph.get_node(sid)]
    nodes.sort(key=lambda n: _parse_session_date(n.content), reverse=True)
    return nodes


def _format_summary_block(summaries: list) -> str:
    """
    Render SESSION_SUMMARY nodes as a concise episodic block for context injection.
    Includes date, narrative, and salient_counts so the model can answer counting
    questions directly from structured data rather than re-deriving from prose.
    """
    if not summaries:
        return ""
    lines = ["Episodic summaries (most recent first):"]
    for node in summaries:
        date = node.metadata.get("session_date") or _parse_session_date(node.content)
        # Strip the "[date] Summary: " prefix — we'll re-render it cleanly
        text = re.sub(r"^\[\d{4}-\d{2}-\d{2}\]\s+Summary:\s*", "", node.content).strip()
        lines.append(f"\n[{date}]")
        lines.append(f"  {text}")
        counts = node.metadata.get("salient_counts") or {}
        if counts:
            count_str = ", ".join(f"{k}: {v}" for k, v in counts.items())
            lines.append(f"  Counts: {count_str}")
    return "\n".join(lines)


def _temporal_context(graph: Graph, activated: dict[str, float], summaries: list | None = None) -> str:
    """
    For temporal questions: episodic summaries (if any) then SESSION nodes in
    chronological order, then spread-activated semantic nodes for subject context.
    """
    lines = []

    summary_block = _format_summary_block(summaries or [])
    if summary_block:
        lines.append(summary_block)
        lines.append("")

    session_nodes = sorted(
        [n for n in graph.all_nodes() if n.type.value == "SESSION"],
        key=lambda n: _parse_session_date(n.content),
    )

    lines.append("SESSION memories (chronological):")
    for node in session_nodes:
        lines.append(f"- {node.content}")

    non_session = sorted(
        [
            (nid, lvl) for nid, lvl in activated.items()
            if graph.get_node(nid) and graph.get_node(nid).type.value not in ("SESSION", "SESSION_SUMMARY")
        ],
        key=lambda x: -x[1],
    )[:20]

    if non_session:
        lines.append("\nAdditional context:")
        for nid, _ in non_session:
            node = graph.get_node(nid)
            if node:
                core_marker = " [CORE]" if node.is_core else ""
                lines.append(f"- [{node.type.value}{core_marker}] {node.content}")

    return "\n".join(lines)


def _aggregation_context(topic: str, graph: Graph, activated: dict[str, float], summaries: list | None = None) -> str:
    """
    For counting/listing questions: episodic summaries (structured counts first),
    then full FTS expansion so every relevant instance is captured.

    Trust hierarchy: salient_counts in summaries are authoritative for counts.
    SESSION nodes provide full narrative backup.
    """
    terms = _key_terms(topic, n=6)
    if terms:
        or_query = " OR ".join(terms.split())
        fts_ids = set(store.search_fts(or_query, graph.path, limit=200))
    else:
        fts_ids = set()

    expanded: dict[str, float] = dict(activated)
    for node in graph.all_nodes():
        if node.id in fts_ids and node.id not in expanded:
            expanded[node.id] = 0.3

    session_lines = []
    non_session: dict[str, float] = {}
    for node_id, level in expanded.items():
        node = graph.get_node(node_id)
        if node and node.type.value == "SESSION":
            session_lines.append(f"- {node.content}")
        elif node and node.type.value != "SESSION_SUMMARY":
            non_session[node_id] = level

    semantic_block = act.serialize(non_session, graph, max_nodes=80)

    parts = []

    summary_block = _format_summary_block(summaries or [])
    if summary_block:
        parts.append(summary_block)
        parts.append(
            "Note: For counting questions, trust the 'Counts' fields above over the "
            "narrative memories below — they were extracted at session end."
        )

    parts.append(semantic_block)

    if session_lines:
        session_lines_sorted = sorted(session_lines)
        parts.append("SESSION memories (complete episode log):\n" + "\n".join(session_lines_sorted))

    return "\n\n".join(p for p in parts if p)


def _hybrid_context(topic: str, graph: Graph, activated: dict[str, float], summaries: list | None = None) -> str:
    """
    For evolution/change questions: semantic graph block followed by episodic
    summaries and session log, with explicit trust hierarchy.
    """
    semantic = act.serialize(activated, graph, max_nodes=30)
    episodic = _aggregation_context(topic, graph, activated, summaries)

    return (
        semantic
        + "\n\n"
        + episodic
        + "\n\n"
        + "Trust hierarchy: for counts, specific events, and dates trust the episodic "
        + "summaries and SESSION memories. For preferences, beliefs, and stable facts "
        + "trust the semantic graph."
    )


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

    Three retrieval modes, selected automatically:
    - temporal:     chronological SESSION timeline for date/order questions
    - aggregation:  full-graph FTS scan for counting/listing questions
    - default:      spreading activation (all other questions)

    All modes ensure SESSION nodes are present for episodic recall.
    """
    seeds = act.find_seeds(topic, graph)
    activated: dict[str, float] = {}
    if seeds:
        activated = act.spread(seeds[:8], graph)
    graph._recompute_salience()

    # Ensure all SESSION nodes are present (at minimum activation level)
    for node in graph.all_nodes():
        if node.type.value == "SESSION" and node.id not in activated:
            activated[node.id] = 0.1

    route = _route_query(topic)

    # For episodic and hybrid routes, pull SESSION_SUMMARY nodes linked to
    # the activated semantic nodes — staged retrieval.
    summaries: list = []
    if route in ("episodic", "hybrid"):
        summaries = _get_linked_summaries(activated, graph, limit=3)

    if route == "hybrid":
        return _hybrid_context(topic, graph, activated, summaries)

    if route == "episodic":
        # Aggregation wins over temporal when both signals are present —
        # counting questions need exhaustive recall, not just ordering.
        if _AGGREGATION_RE.search(topic):
            return _aggregation_context(topic, graph, activated, summaries)
        return _temporal_context(graph, activated, summaries)

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
