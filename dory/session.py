from __future__ import annotations

import re
from typing import Literal

from .graph import Graph
from .schema import NodeType, EdgeType, new_id, ZONE_ARCHIVED
from . import activation as act
from . import consolidation
from . import store
from .sanitize import sanitize_node_content

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


# Procedural questions asking how to do something — surface PROCEDURE nodes first.
_PROCEDURE_RE = re.compile(
    r"\b("
    r"how (?:do|to|can|should|did) (?:I|we|you)\b|"
    r"what(?:'s| is) the (?:process|steps?|procedure|workflow|way) (?:to|for)\b|"
    r"walk (?:me )?through\b|"
    r"step[- ]by[- ]step\b|"
    r"what are the steps\b|"
    r"instructions? (?:for|to)\b|"
    r"how (?:does|do) .{0,30} work\b"
    r")\b",
    re.IGNORECASE,
)


# Preference questions asking for personalized recommendations or suggestions.
# Needs to match generic phrasing ("any advice", "can you suggest") used in benchmarks.
_PREFERENCE_RE = re.compile(
    r"\b("
    r"would I (?:like|enjoy|prefer)|"
    r"suggest(?:ions?)? for (?:my|me)|"
    r"based on (?:my|what I)|"
    r"recommend(?:ation)?s? for (?:my|me)|"
    r"what should I get|"
    r"what kind of .{0,20} (?:do|would) I|"
    r"any (?:\w+ )?(?:suggestions?|recommendations?|advice|tips?|ideas?)\b|"
    r"(?:can you |could you )(?:suggest|recommend)\b|"
    r"what should I\b|"
    r"what would you (?:recommend|suggest)|"
    r"(?:what do|do) you think\b|"
    # Third-person preference questions (LongMemEval asks about "the user" or by name)
    r"what .{0,40}(?:would|might|could) (?:they|he|she|\w+) (?:like|enjoy|prefer)\b|"
    r"which .{0,30}(?:would|might) .{0,20}(?:prefer|enjoy|like|choose|pick)\b|"
    r"(?:most likely|probably) (?:to )?(?:like|enjoy|prefer|want|choose)\b|"
    r"what .{0,20}(?:does|do) .{0,20}(?:like|enjoy|prefer|tend to)\b|"
    r"(?:suit(?:s|ed)?|good match for|fit(?:s|ting)? .{0,10}taste)"
    r")\b",
    re.IGNORECASE,
)


def _route_query(topic: str) -> Literal["graph", "episodic", "hybrid", "procedure"]:
    """
    Classify a query into one of four retrieval modes. Deterministic — no LLM call.

    procedure: how-to questions — surface PROCEDURE nodes first
    hybrid:    questions about change or evolution across time (need both layers)
    episodic:  counts, ordering, specific events, relative time (need session log)
    graph:     preferences, stable facts, beliefs, relationships (default)
    """
    if _PROCEDURE_RE.search(topic):
        return "procedure"
    if _HYBRID_RE.search(topic):
        return "hybrid"
    if _PREFERENCE_RE.search(topic):
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


def _aggregate_counts(summaries: list) -> dict:
    """
    Sum salient_counts across all SESSION_SUMMARY nodes.
    Returns a dict of {key: total} for any key appearing in at least one summary.
    """
    totals: dict = {}
    for node in summaries:
        for k, v in (node.metadata.get("salient_counts") or {}).items():
            if isinstance(v, (int, float)):
                totals[k] = totals.get(k, 0) + v
    return totals


def _format_summary_block(summaries: list, include_totals: bool = False) -> str:
    """
    Render SESSION_SUMMARY nodes as a concise episodic block for context injection.
    Includes date, narrative, and salient_counts so the model can answer counting
    questions directly from structured data rather than re-deriving from prose.

    If include_totals=True, prepend an aggregated totals line across all sessions.
    """
    if not summaries:
        return ""

    lines = []

    # Aggregate totals across sessions when requested (for counting questions)
    if include_totals:
        totals = _aggregate_counts(summaries)
        if totals:
            totals_str = ", ".join(f"{k}: {v}" for k, v in sorted(totals.items()))
            lines.append(f"AGGREGATED TOTALS (sum across ALL sessions): {totals_str}")
            lines.append("↑ Use these totals directly for 'how many' questions. "
                         "Do NOT recount from session text unless a total seems wrong.")
            lines.append("")

    lines.append("Episodic summaries (most recent first):")
    for node in summaries:
        date = node.metadata.get("session_date") or _parse_session_date(node.content)
        # Strip the "[date] Summary: " prefix — we'll re-render it cleanly
        text = re.sub(r"^\[\d{4}-\d{2}-\d{2}\]\s+Summary:\s*", "", node.content).strip()
        lines.append(f"\n[{date}]")
        lines.append(f"  {text}")
        counts = node.metadata.get("salient_counts") or {}
        if counts:
            low_conf = set(node.metadata.get("low_confidence_counts") or [])
            parts = []
            for k, v in counts.items():
                if k in low_conf:
                    parts.append(f"{k}: {v} ⚠ low confidence — verify against session text")
                else:
                    parts.append(f"{k}: {v}")
            lines.append(f"  Counts: {', '.join(parts)}")
    return "\n".join(lines)


def _temporal_context(graph: Graph, activated: dict[str, float], summaries: list | None = None, reference_date: str = "") -> str:
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

    non_session = {
        nid: lvl for nid, lvl in activated.items()
        if graph.get_node(nid) and graph.get_node(nid).type.value not in ("SESSION", "SESSION_SUMMARY")
    }

    if non_session:
        lines.append("\nAdditional context:")
        # Sort EVENT nodes by event_date metadata for chronological ordering;
        # non-EVENT nodes follow sorted by activation level.
        def _temporal_sort_key(item: tuple[str, float]) -> tuple[int, str, float]:
            nid, lvl = item
            node = graph.get_node(nid)
            if node and node.type.value == "EVENT":
                date = node.metadata.get("event_date") or node.metadata.get("start_date") or ""
                return (0, date, -lvl)
            return (1, "", -lvl)
        ordered = dict(sorted(non_session.items(), key=_temporal_sort_key))
        lines.append(act.serialize(ordered, graph, max_nodes=20, reference_date=reference_date))

    return "\n".join(lines)


def _aggregation_context(topic: str, graph: Graph, activated: dict[str, float], summaries: list | None = None, reference_date: str = "") -> str:
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

    semantic_block = act.serialize(non_session, graph, max_nodes=80, reference_date=reference_date)

    parts = []

    summary_block = _format_summary_block(summaries or [], include_totals=True)
    if summary_block:
        parts.append(summary_block)
        parts.append(
            "Note: The AGGREGATED TOTALS above sum counts across ALL sessions — use them "
            "as the authoritative answer for 'how many total' questions. If a thing appears "
            "in multiple sessions, SUM those counts; do not use just the most recent session."
        )

    parts.append(semantic_block)

    if session_lines:
        session_lines_sorted = sorted(session_lines)
        parts.append("SESSION memories (complete episode log):\n" + "\n".join(session_lines_sorted))

    return "\n\n".join(p for p in parts if p)


def _hybrid_context(topic: str, graph: Graph, activated: dict[str, float], summaries: list | None = None, reference_date: str = "") -> str:
    """
    For evolution/change questions: semantic graph block followed by episodic
    summaries and session log, with explicit trust hierarchy.
    """
    semantic = act.serialize(activated, graph, max_nodes=30, reference_date=reference_date)
    episodic = _aggregation_context(topic, graph, activated, summaries, reference_date=reference_date)

    return (
        semantic
        + "\n\n"
        + episodic
        + "\n\n"
        + "Trust hierarchy: for counts, specific events, and dates trust the episodic "
        + "summaries and SESSION memories. For preferences, beliefs, and stable facts "
        + "trust the semantic graph."
    )


def _procedure_context(topic: str, graph: Graph, activated: dict[str, float], reference_date: str = "") -> str:
    """
    For how-to / procedural questions: surface PROCEDURE nodes first, then
    spreading activation semantic context, then any relevant session history.

    PROCEDURE nodes are shown regardless of activation level — a stored workflow
    is relevant to any matching how-to query even if it wasn't recently activated.
    """
    # All active PROCEDURE nodes, highest salience first
    proc_nodes = sorted(
        [n for n in graph.all_nodes() if n.type == NodeType.PROCEDURE],
        key=lambda n: -n.salience,
    )

    # FTS expansion on the topic to find relevant procedures specifically
    terms = _key_terms(topic, n=8)
    fts_ids: set[str] = set()
    if terms:
        or_query = " OR ".join(terms.split())
        fts_ids = set(store.search_fts(or_query, graph.path, limit=50))

    # Topically relevant procedures (FTS match) sorted first
    relevant_procs = [n for n in proc_nodes if n.id in fts_ids]
    other_procs = [n for n in proc_nodes if n.id not in fts_ids]
    ordered_procs = relevant_procs + other_procs

    # Semantic context from spreading activation (exclude PROCEDURE nodes already shown)
    proc_ids = {n.id for n in ordered_procs}
    expanded: dict[str, float] = {
        nid: lvl for nid, lvl in activated.items()
        if nid not in proc_ids
        and graph.get_node(nid)
        and graph.get_node(nid).type.value not in ("SESSION", "SESSION_SUMMARY")
    }

    parts = []

    if ordered_procs:
        proc_lines = ["Stored procedures and workflows:"]
        for node in ordered_procs:
            core_marker = " [CORE]" if node.is_core else ""
            proc_lines.append(f"- [PROCEDURE{core_marker}] {node.content}")
        parts.append("\n".join(proc_lines))

    if expanded:
        parts.append(act.serialize(expanded, graph, max_nodes=20, reference_date=reference_date))

    return "\n\n".join(p for p in parts if p) or "(no relevant memories found)"


def _dedup_similar(nodes: list, threshold: float = 0.65) -> list:
    """
    Remove near-duplicate nodes by Jaccard word-overlap.
    The first (highest-ranked) node in each cluster is kept.
    """
    kept = []
    for n in nodes:
        wa = set(n.content.lower().split())
        duplicate = any(
            len(wa & set(k.content.lower().split())) / max(len(wa | set(k.content.lower().split())), 1) >= threshold
            for k in kept
        )
        if not duplicate:
            kept.append(n)
    return kept


def _preference_context(topic: str, graph: Graph, activated: dict[str, float], reference_date: str = "") -> str:
    """
    For preference/recommendation questions: surface explicit PREFERENCE nodes first,
    then KEY EVENTS (specific memorable episodes), then SESSION_SUMMARY grounding,
    then FTS-expanded semantic nodes, then SESSION narratives, then synthesized patterns.

    Ordering rationale:
      - FTS-sort preferences so query-relevant ones appear first, not just highest salience
      - Deduplicate near-identical preferences to reduce noise and surfacing diverse facts
      - Elevate EVENT nodes to their own section — episodic specifics are often the key fact
      - Cap ENTITY nodes at 5 to prevent restaurant/product lists drowning key events
    """
    # FTS expansion on the topic — needed for both preference ranking and entity capping
    terms = _key_terms(topic, n=8)
    fts_ids: set[str] = set()
    if terms:
        or_query = " OR ".join(terms.split())
        fts_ids = set(store.search_fts(or_query, graph.path, limit=100))

    # Split into explicitly extracted preferences vs synthesized behavioral patterns
    real_prefs = []
    synth_prefs = []
    for n in graph.all_nodes():
        if n.type == NodeType.PREFERENCE and n.zone != ZONE_ARCHIVED:
            if "synthesized" in (n.tags or []):
                synth_prefs.append(n)
            else:
                real_prefs.append(n)

    # FTS-first sort: preferences matching the query bubble to the top
    real_prefs.sort(key=lambda n: (n.id not in fts_ids, -n.salience))
    # Deduplicate near-identical preferences — reduces 7 yogurt clones to 2-3 distinct ones
    real_prefs = _dedup_similar(real_prefs, threshold=0.65)

    # Only surface synthesized patterns if they overlap with the query topic
    topic_words = {w.lower() for w in topic.split() if len(w) >= 4}
    relevant_synth = [
        n for n in synth_prefs
        if any(kw in n.content.lower() for kw in topic_words)
    ][:5]

    # Separate EVENT nodes from other activated nodes — events are high signal for preference Qs
    # (e.g. "user met Brandon Flowers after a concert" is the key fact for a Denver trip question)
    event_nodes: list[tuple] = []
    event_ids: set[str] = set()
    expanded: dict[str, float] = {}
    entity_count = 0
    proc_count = 0

    for nid, lvl in activated.items():
        node = graph.get_node(nid)
        if not node or node.zone == ZONE_ARCHIVED:
            continue
        if node.type.value in ("SESSION", "SESSION_SUMMARY") or node.type == NodeType.PREFERENCE:
            continue
        if node.type == NodeType.EVENT:
            event_nodes.append((node, lvl))
            event_ids.add(nid)
        elif node.type == NodeType.ENTITY:
            # Cap ENTITY nodes at 5 — long restaurant/product lists drown key events
            if entity_count < 5 or nid in fts_ids:
                expanded[nid] = lvl
                entity_count += 1
        elif node.type == NodeType.PROCEDURE:
            # Cap PROCEDURE nodes at 3 — full recipes bias the answer model away from preferences
            if proc_count < 3:
                expanded[nid] = lvl
                proc_count += 1
        else:
            expanded[nid] = lvl

    # Also pull FTS-matched EVENT nodes not yet in activated
    for nid in fts_ids:
        node = graph.get_node(nid)
        if not node or node.zone == ZONE_ARCHIVED:
            continue
        if node.type == NodeType.EVENT and nid not in event_ids:
            event_nodes.append((node, 0.3))
            event_ids.add(nid)
        elif node.type not in (NodeType.PREFERENCE, NodeType.EVENT) and \
                node.type.value not in ("SESSION", "SESSION_SUMMARY") and \
                nid not in expanded:
            if node.type == NodeType.PROCEDURE and proc_count >= 3:
                continue  # respect procedure cap for FTS-matched nodes too
            expanded[nid] = 0.3

    # Sort events: FTS-matched first (most query-relevant), then by activation level
    event_nodes.sort(key=lambda x: (x[0].id not in fts_ids, -x[1]))
    event_nodes = event_nodes[:8]

    parts = []

    # 1. Explicit preferences — FTS-ranked, deduplicated, highest signal
    if real_prefs:
        pref_lines = ["Stored preferences:"]
        for node in real_prefs:
            core_marker = " [CORE]" if node.is_core else ""
            pref_lines.append(f"- [PREFERENCE{core_marker}] {node.content}")
        parts.append("\n".join(pref_lines))

    # 2. Key events — specific memorable episodes, often the decisive detail
    if event_nodes:
        event_lines = ["Key events:"]
        for node, _ in event_nodes:
            date_prefix = f"({node.created_at[:10]}) " if node.created_at else ""
            event_lines.append(f"- [EVENT] {date_prefix}{node.content}")
        parts.append("\n".join(event_lines))

    # 3. SESSION_SUMMARY nodes — episodic grounding for experience-based questions
    summaries = _get_linked_summaries(activated, graph, limit=3)
    summary_block = _format_summary_block(summaries)
    if summary_block:
        parts.append(summary_block)

    # 4. FTS-expanded semantic context (entity-capped, events already shown above)
    if expanded:
        parts.append(act.serialize(expanded, graph, max_nodes=20, reference_date=reference_date))

    # 5. Full session narratives
    session_nodes = sorted(
        [n for n in graph.all_nodes() if n.type.value == "SESSION"],
        key=lambda n: _parse_session_date(n.content),
    )
    if session_nodes:
        sess_lines = ["Session history (context on user experiences):"]
        for node in session_nodes:
            sess_lines.append(f"- {node.content}")
        parts.append("\n".join(sess_lines))

    # 6. Synthesized behavioral patterns — only if topically relevant, lowest priority
    if relevant_synth:
        synth_lines = ["Behavioral patterns (inferred from repeated engagement):"]
        for node in relevant_synth:
            synth_lines.append(f"- {node.content}")
        parts.append("\n".join(synth_lines))

    return "\n\n".join(p for p in parts if p) or "(no relevant memories found)"


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
    Returns a context block suitable for injecting into a prompt.

    Three retrieval modes, selected automatically:
    - temporal:     chronological SESSION timeline for date/order questions
    - aggregation:  full-graph FTS scan for counting/listing questions
    - default:      spreading activation (all other questions)

    All modes ensure SESSION nodes are present for episodic recall.

    reference_date: ISO date string (YYYY-MM-DD) used to compute duration hints
    (e.g. "~9 months, since 2023-03-01") for nodes with a start_date in metadata.
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

    if route == "procedure":
        return _procedure_context(topic, graph, activated, reference_date=reference_date)

    # For episodic and hybrid routes, pull SESSION_SUMMARY nodes linked to
    # the activated semantic nodes — staged retrieval.
    summaries: list = []
    if route in ("episodic", "hybrid"):
        summaries = _get_linked_summaries(activated, graph, limit=3)

    if route == "hybrid":
        if _PREFERENCE_RE.search(topic):
            return _preference_context(topic, graph, activated, reference_date=reference_date)
        return _hybrid_context(topic, graph, activated, summaries, reference_date=reference_date)

    if route == "episodic":
        # Aggregation wins over temporal when both signals are present —
        # counting questions need exhaustive recall, not just ordering.
        if _AGGREGATION_RE.search(topic):
            return _aggregation_context(topic, graph, activated, summaries, reference_date=reference_date)
        return _temporal_context(graph, activated, summaries, reference_date=reference_date)

    return act.serialize(activated, graph, max_nodes=50, reference_date=reference_date)


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
