from __future__ import annotations

import re

from .graph import Graph
from .schema import NodeType, EdgeType, new_id
from . import activation as act
from . import consolidation
from . import store

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


def _temporal_context(graph: Graph, activated: dict[str, float]) -> str:
    """
    For temporal questions: SESSION nodes in chronological order, then
    spread-activated semantic nodes for subject context.
    """
    session_nodes = sorted(
        [n for n in graph.all_nodes() if n.type.value == "SESSION"],
        key=lambda n: _parse_session_date(n.content),
    )

    lines = ["SESSION memories (chronological):"]
    for node in session_nodes:
        lines.append(f"- {node.content}")

    non_session = sorted(
        [
            (nid, lvl) for nid, lvl in activated.items()
            if graph.get_node(nid) and graph.get_node(nid).type.value != "SESSION"
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


def _aggregation_context(topic: str, graph: Graph, activated: dict[str, float]) -> str:
    """
    For counting/listing questions: expand to all FTS matches so every
    relevant instance is included, not just the top activated nodes.
    SESSION nodes are always included at full weight — they're the most
    complete record of what happened in each session.
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
            expanded[node.id] = 0.3  # above SESSION floor so they appear

    # Always keep all SESSION nodes — required for complete counts across sessions.
    # Separate them out so they aren't squeezed by max_nodes on semantic content.
    session_lines = []
    non_session: dict[str, float] = {}
    for node_id, level in expanded.items():
        node = graph.get_node(node_id)
        if node and node.type.value == "SESSION":
            session_lines.append(f"- {node.content}")
        else:
            non_session[node_id] = level

    semantic_block = act.serialize(non_session, graph, max_nodes=80)

    if session_lines:
        session_lines_sorted = sorted(session_lines)  # rough chronological by date prefix
        return semantic_block + "\n\nSESSION memories (complete episode log):\n" + "\n".join(session_lines_sorted)
    return semantic_block


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

    # Aggregation wins when "how many [non-time-unit]" is present, even if temporal
    # language like "last month" also appears. Temporal is for ordering/duration, not counting.
    if _AGGREGATION_RE.search(topic):
        return _aggregation_context(topic, graph, activated)

    if _TEMPORAL_RE.search(topic):
        return _temporal_context(graph, activated)

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
