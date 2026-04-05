from __future__ import annotations

from datetime import datetime, timezone

from .graph import Graph
from .schema import now_iso, EdgeType, ZONE_ACTIVE


def _fmt_date(iso: str | None) -> str:
    """Return 'YYYY-MM-DD' from an ISO timestamp, or '' on failure."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "have", "has",
    "had", "do", "does", "did", "will", "would", "should", "may", "might",
    "can", "could", "to", "of", "in", "on", "at", "for", "with", "by", "from",
    "as", "and", "or", "but", "not", "this", "that", "it", "its", "also",
    "more", "than", "just", "very", "all", "any", "one", "two", "get",
    "use", "uses", "used", "using", "new", "add", "i", "my", "me", "you",
    "your", "we", "our", "what", "which", "who", "when", "where", "how",
    "first", "last", "did", "after", "before", "about",
})


def _fts_query(text: str, n: int = 10) -> str:
    """
    Extract meaningful terms from text for FTS5, joined with OR.
    OR mode gives much better recall than FTS5's default AND.
    Includes numeric tokens (years, day numbers) for date matching.
    """
    import re
    # Alpha tokens (words)
    alpha = re.findall(r"[a-zA-Z]\w*", text)
    # Numeric tokens: extract raw digit sequences (1-4 digits) — captures years, day
    # numbers, and ordinals like "15th" (extracts "15"). Longer numbers are ignored.
    numeric = [m for m in re.findall(r"\d+", text) if 1 <= len(m) <= 4]

    seen: set[str] = set()
    terms = []

    for w in alpha:
        lo = w.lower()
        if len(lo) >= 3 and lo not in _STOPWORDS and lo not in seen:
            seen.add(lo)
            terms.append(lo)
            if len(terms) >= n:
                break

    for num in numeric:
        if num not in seen:
            seen.add(num)
            terms.append(num)

    return " OR ".join(terms) if terms else text


def find_seeds(query: str, graph: Graph) -> list[str]:
    """
    Return node IDs ranked by relevance to the query.

    Priority order:
      1. FTS5 BM25 search (best recall, handles partial terms)
      2. Vector KNN search (semantic similarity, if Ollama running)
      3. Substring fallback (always works, no dependencies)

    Results are deduplicated and merged, with FTS hits ranked first.
    """
    from . import store, vector

    seen: dict[str, int] = {}  # node_id → score (lower = better rank)

    # 1. FTS BM25 — use OR over key terms for recall (avoids AND-mode over-constraining)
    fts_ids = store.search_fts(_fts_query(query), graph.path)
    for rank, nid in enumerate(fts_ids):
        node = graph._nodes.get(nid)
        if node and node.zone == ZONE_ACTIVE:
            seen[nid] = rank

    # 2. Vector KNN (if available)
    if vector.available():
        vec_ids = vector.knn_search(query, graph.path)
        for rank, nid in enumerate(vec_ids):
            node = graph._nodes.get(nid)
            if node and node.zone == ZONE_ACTIVE and nid not in seen:
                seen[nid] = len(fts_ids) + rank

    # 3. Substring fallback for anything not caught above
    if not seen:
        terms = query.lower().split()
        for node in graph.all_nodes():
            text = (node.content + " " + " ".join(node.tags)).lower()
            hits = sum(1 for t in terms if t in text)
            if hits:
                seen[node.id] = -hits  # negative so higher hits = lower score

    return sorted(seen, key=lambda nid: seen[nid])


def spread(
    seed_ids: list[str],
    graph: Graph,
    depth: int = 3,
    depth_decay: float = 0.5,
    threshold: float = 0.05,
) -> dict[str, float]:
    """
    Spread activation from seed nodes outward through the graph.
    Returns {node_id: activation_level} for all nodes above threshold.
    Activation received = source_activation × edge_weight × depth_decay per hop.
    """
    activation: dict[str, float] = {sid: 1.0 for sid in seed_ids}
    frontier: dict[str, float] = dict(activation)

    traversed_edges: set[str] = set()

    for _ in range(depth):
        next_frontier: dict[str, float] = {}
        for node_id, level in frontier.items():
            for edge in graph.edges_for_node(node_id):
                neighbor_id = (
                    edge.target_id if edge.source_id == node_id else edge.source_id
                )
                neighbor = graph.get_node(neighbor_id)
                if not neighbor or neighbor.zone != ZONE_ACTIVE:
                    continue
                received = level * edge.weight * depth_decay
                if received >= threshold:
                    traversed_edges.add(edge.id)
                    current = activation.get(neighbor_id, 0.0)
                    new_val = min(1.0, current + received)
                    if new_val > current:
                        activation[neighbor_id] = new_val
                        next_frontier[neighbor_id] = new_val
        frontier = next_frontier
        if not frontier:
            break

    # Record activation on touched nodes and traversed edges
    now = now_iso()
    for node_id, level in activation.items():
        if level >= threshold:
            node = graph.get_node(node_id)
            if node:
                node.activation_count += 1
                node.last_activated = now

    for edge in graph.all_edges():
        if edge.id in traversed_edges:
            edge.activation_count += 1
            edge.last_activated = now

    return {nid: v for nid, v in activation.items() if v >= threshold}


SALIENCE_FLOOR: float = 0.1  # nodes below this are skipped during serialization


def _compute_duration_hint(start_date_iso: str, reference_date: str) -> str:
    """
    Given a start_date (YYYY-MM-DD) and reference_date (YYYY-MM-DD or
    human-readable like 'Monday, May 20, 2023'), return a string like
    '~9 months, since 2023-03-01' or '' on any failure.
    """
    if not start_date_iso or not reference_date:
        return ""
    try:
        from datetime import datetime as _dt
        ref = None
        for fmt in ("%Y-%m-%d", "%A, %B %d, %Y", "%B %d, %Y"):
            try:
                ref = _dt.strptime(reference_date.strip(), fmt)
                break
            except ValueError:
                continue
        if ref is None:
            return ""
        start = _dt.fromisoformat(start_date_iso[:10])
        delta = ref - start
        if delta.days < 0:
            return ""
        months = delta.days / 30.44
        if months < 1:
            d = delta.days
            return f"~{d} day{'s' if d != 1 else ''}, since {start_date_iso[:10]}"
        elif months < 24:
            m = round(months)
            return f"~{m} month{'s' if m != 1 else ''}, since {start_date_iso[:10]}"
        else:
            y = round(months / 12, 1)
            return f"~{y} years, since {start_date_iso[:10]}"
    except Exception:
        return ""


def serialize(
    activated: dict[str, float],
    graph: Graph,
    max_nodes: int = 20,
    reference_date: str = "",
) -> str:
    """Convert activated subgraph to a natural language context block."""
    if not activated:
        return "(no relevant memories found)"

    ranked = sorted(
        activated.items(),
        key=lambda kv: (
            kv[1],
            graph.get_node(kv[0]).salience if graph.get_node(kv[0]) else 0,
        ),
        reverse=True,
    )[:max_nodes]

    # Pre-compute which nodes have outgoing SUPERSEDES edges (they are canonical current values)
    superseding_ids: set[str] = set()
    for edge in graph.all_edges():
        if edge.type == EdgeType.SUPERSEDES:
            superseding_ids.add(edge.source_id)

    lines = []
    for node_id, level in ranked:
        node = graph.get_node(node_id)
        if not node or node.zone != ZONE_ACTIVE:
            continue
        # Skip low-salience nodes to reduce noise (only after first save cycle)
        if node.activation_count > 0 and node.salience < SALIENCE_FLOOR:
            continue
        core_marker = " [CORE]" if node.is_core else ""
        current_marker = " [CURRENT VALUE]" if node_id in superseding_ids else ""
        # SESSION nodes already embed the date in their content as "[YYYY-MM-DD] Session: ..."
        # so we don't add a redundant (and potentially wrong) date hint for them.
        # EVENT nodes still get the hint from created_at.
        date_hint = ""
        if node.type.value == "EVENT" and node.created_at:
            d = _fmt_date(node.created_at)
            if d:
                date_hint = f" ({d})"
        # Duration hint for entities with a known start_date
        duration_hint = ""
        if reference_date and node.metadata:
            start_date = node.metadata.get("start_date", "")
            if start_date:
                dur = _compute_duration_hint(start_date, reference_date)
                if dur:
                    duration_hint = f" ({dur})"
        # Occurrence count and amount hint (precomputed during extraction)
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
        lines.append(f"- [{node.type.value}{core_marker}{current_marker}]{date_hint}{duration_hint}{occurrence_hint} {node.content}")

    # Include edges between activated nodes
    activated_ids = set(activated)
    edge_lines = []
    seen: set[tuple] = set()
    for edge in graph.all_edges():
        if edge.source_id in activated_ids and edge.target_id in activated_ids:
            key = (edge.source_id, edge.target_id, edge.type.value)
            if key not in seen:
                src = graph.get_node(edge.source_id)
                tgt = graph.get_node(edge.target_id)
                if src and tgt:
                    if edge.type == EdgeType.SUPERSEDES:
                        date = _fmt_date(src.superseded_at or edge.created_at)
                        date_str = f" (updated {date})" if date else ""
                        edge_lines.append(
                            f"  [KNOWLEDGE UPDATE{date_str}] Previously: {src.content} → Now: {tgt.content}"
                        )
                    else:
                        edge_lines.append(
                            f"  {src.content} --[{edge.type.value}]--> {tgt.content}"
                        )
                    seen.add(key)

    result = "Activated memories:\n" + "\n".join(lines)
    if edge_lines:
        result += "\n\nRelationships:\n" + "\n".join(edge_lines[:15])
    return result
