#!/usr/bin/env python3
"""
Dory CLI — session-based graph memory for AI agents.

Usage:
  python dory_cli.py query "AllergyFind database"
  python dory_cli.py observe CONCEPT "Michael prefers Apache 2.0 licenses"
  python dory_cli.py link <src_id> <tgt_id> USES
  python dory_cli.py list [--type CONCEPT]
  python dory_cli.py show
  python dory_cli.py consolidate
  python dory_cli.py review-session --from-hook    # called from Claude Code Stop hook
  python dory_cli.py review-session --file /path/to/session.jsonl
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dory.graph import Graph
from dory.schema import NodeType, EdgeType
from dory import session


def cmd_query(args, graph: Graph) -> None:
    result = session.query(" ".join(args.topic), graph)
    if args.json:
        print(json.dumps({
            "ok": True,
            "command": "query",
            "db_path": str(graph.path),
            "topic": " ".join(args.topic),
            "result": result,
        }))
    else:
        print(result)
    graph.save()


def cmd_observe(args, graph: Graph) -> None:
    try:
        node_type = NodeType(args.type.upper())
    except ValueError:
        valid = [t.value for t in NodeType]
        if args.json:
            print(json.dumps({
                "ok": False,
                "command": "observe",
                "error": f"Unknown node type: {args.type}",
                "valid_types": valid,
            }))
        else:
            print(f"Unknown node type: {args.type}. Valid: {valid}")
        sys.exit(1)
    tags = args.tags.split(",") if args.tags else []
    content = " ".join(args.content)
    node_id = session.observe(content, node_type, graph, tags=tags)
    graph.save()
    if args.json:
        print(json.dumps({
            "ok": True,
            "command": "observe",
            "db_path": str(graph.path),
            "node_id": node_id,
            "node_type": node_type.value,
            "content": content,
            "tags": tags,
        }))
    else:
        print(f"Added node {node_id}: {content}")


def cmd_link(args, graph: Graph) -> None:
    src = graph.get_node(args.src)
    tgt = graph.get_node(args.tgt)
    if not src:
        print(f"Source node not found: {args.src}")
        sys.exit(1)
    if not tgt:
        print(f"Target node not found: {args.tgt}")
        sys.exit(1)
    try:
        edge_type = EdgeType(args.edge_type.upper())
    except ValueError:
        print(f"Unknown edge type: {args.edge_type}. Valid: {[t.value for t in EdgeType]}")
        sys.exit(1)
    weight = float(args.weight) if args.weight else 0.8
    session.link(args.src, args.tgt, edge_type, graph, weight=weight)
    print(f"Linked: {src.content} --[{edge_type.value}]--> {tgt.content}")


def cmd_list(args, graph: Graph) -> None:
    nodes = graph.all_nodes()
    if args.type:
        try:
            filter_type = NodeType(args.type.upper())
            nodes = [n for n in nodes if n.type == filter_type]
        except ValueError:
            print(f"Unknown node type: {args.type}")
            sys.exit(1)
    nodes = sorted(nodes, key=lambda n: n.salience, reverse=True)
    if not nodes:
        print("(no nodes)")
        return
    for n in nodes:
        core = " *" if n.is_core else ""
        tags = f" [{', '.join(n.tags)}]" if n.tags else ""
        print(f"  {n.id}  [{n.type.value}{core}]  {n.content}{tags}  (salience={n.salience:.2f})")


def cmd_show(args, graph: Graph) -> None:
    stats = graph.stats()
    core_nodes = [n for n in graph.all_nodes() if n.is_core]
    sorted_core = sorted(core_nodes, key=lambda n: n.salience, reverse=True)
    if args.json:
        print(json.dumps({
            "ok": True,
            "command": "show",
            "db_path": str(graph.path),
            "stats": stats,
            "core_memories": [
                {
                    "id": n.id,
                    "type": n.type.value,
                    "content": n.content,
                    "salience": round(n.salience, 4),
                }
                for n in sorted_core
            ],
        }))
        return

    print(f"Nodes:      {stats['nodes']}")
    print(f"Edges:      {stats['edges']}")
    print(f"Core nodes: {stats['core_nodes']}")
    print()
    if sorted_core:
        print("Core memories:")
        for n in sorted_core:
            print(f"  [{n.type.value}] {n.content}  (salience={n.salience:.2f})")


def cmd_explain(args, graph: Graph) -> None:
    """
    Show the full provenance chain for a node — what it replaced, what replaced it,
    and why it was archived. Accepts a node ID or a content substring for fuzzy lookup.
    """
    from dory.schema import EdgeType, ZONE_ACTIVE, ZONE_ARCHIVED

    query = args.node_id

    # Try exact ID first, then substring match on content
    node = graph.get_node(query)
    if node is None:
        q = query.lower()
        candidates = [n for n in graph.all_nodes(zone=None) if q in n.content.lower()]
        if not candidates:
            print(f"No node found matching: {query!r}")
            return
        if len(candidates) > 1:
            print(f"Multiple matches — please be more specific or use a node ID:\n")
            for c in candidates[:10]:
                print(f"  [{c.id}] [{c.type.value}] [{c.zone}] {c.content[:80]}")
            return
        node = candidates[0]

    # Header
    zone_label = f" [{node.zone.upper()}]" if node.zone != ZONE_ACTIVE else ""
    print(f"\n[{node.type.value}]{zone_label}  id={node.id}")
    print(f"  {node.content}")
    print()

    # Core stats
    print(f"  salience:         {node.salience:.4f}")
    print(f"  activation_count: {node.activation_count}")
    print(f"  distinct_sessions:{node.distinct_sessions}")
    print(f"  created_at:       {node.created_at[:10] if node.created_at else 'unknown'}")
    if node.last_activated:
        print(f"  last_activated:   {node.last_activated[:10]}")
    if node.is_core:
        print(f"  is_core:          yes")

    # Metadata fields of interest
    meta = node.metadata or {}
    if meta.get("signal_strength"):
        print(f"  signal_strength:  {meta['signal_strength']}")
    if meta.get("occurrence_count", 0) > 1:
        print(f"  occurrence_count: {meta['occurrence_count']}")
    if meta.get("start_date"):
        print(f"  start_date:       {meta['start_date']}")
    if meta.get("amount"):
        print(f"  amount:           {meta['amount']}")

    # Archival reason
    if node.zone == ZONE_ARCHIVED and node.superseded_at:
        print(f"\n  Archived: {node.superseded_at[:10]}")

    # Build edge map for this node
    outgoing = []  # edges where this node is source
    incoming = []  # edges where this node is target
    for edge in graph.all_edges():
        if edge.source_id == node.id:
            outgoing.append(edge)
        elif edge.target_id == node.id:
            incoming.append(edge)

    # What this node superseded (outgoing SUPERSEDES)
    superseded_targets = [e for e in outgoing if e.type == EdgeType.SUPERSEDES]
    if superseded_targets:
        print(f"\n  Replaced (SUPERSEDES):")
        for e in superseded_targets:
            old = graph.get_node(e.target_id)
            if old:
                print(f"    [{old.id}] [{old.zone}] {old.content[:100]}")

    # What superseded this node (incoming SUPERSEDES)
    superseded_by = [e for e in incoming if e.type == EdgeType.SUPERSEDES]
    if superseded_by:
        print(f"\n  Superseded by:")
        for e in superseded_by:
            new = graph.get_node(e.source_id)
            if new:
                print(f"    [{new.id}] [{new.zone}] {new.content[:100]}")

    # REFINES edges
    refines_out = [e for e in outgoing if e.type == EdgeType.REFINES]
    refines_in  = [e for e in incoming if e.type == EdgeType.REFINES]
    if refines_out:
        print(f"\n  Refines (adds specificity to):")
        for e in refines_out:
            base = graph.get_node(e.target_id)
            if base:
                print(f"    [{base.id}] {base.content[:100]}")
    if refines_in:
        print(f"\n  Refined by (more specific versions):")
        for e in refines_in:
            specific = graph.get_node(e.source_id)
            if specific:
                print(f"    [{specific.id}] {specific.content[:100]}")

    # Current authoritative value (follow supersession chain forward)
    current = node
    chain_depth = 0
    while True:
        next_edges = [e for e in graph.all_edges()
                      if e.target_id == current.id and e.type == EdgeType.SUPERSEDES]
        if not next_edges:
            break
        current = graph.get_node(next_edges[0].source_id)
        if not current:
            break
        chain_depth += 1
        if chain_depth > 10:
            break

    if current.id != node.id:
        print(f"\n  Current authoritative value:")
        print(f"    [{current.id}] [{current.zone}] {current.content}")

    print()


def cmd_visualize(args, graph: Graph) -> None:
    from dory.visualize import open_visualization
    from dory.schema import ZONE_ARCHIVED, ZONE_EXPIRED
    zones = ["active"]
    if args.archived:
        zones.append(ZONE_ARCHIVED)
    if args.expired:
        zones.append(ZONE_EXPIRED)
    output_path = open_visualization(
        graph,
        output_path=args.output,
        zones=zones,
        open_browser=not args.no_open,
        allow_remote_js=args.remote_assets,
    )
    print(f"Visualization saved to: {output_path}")


def _find_latest_claude_session(project_dir: Path | None = None) -> Path | None:
    """Find the most recently modified Claude Code session JSONL for the given project dir."""
    cwd = project_dir or Path.cwd()
    # Claude Code maps project paths to slugs by replacing / with -
    slug = str(cwd).replace("/", "-").lstrip("-")
    sessions_dir = Path.home() / ".claude" / "projects" / slug
    if not sessions_dir.exists():
        return None
    jsonl_files = sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return jsonl_files[0] if jsonl_files else None


def _parse_claude_session(transcript_path: Path) -> tuple[list[dict], str]:
    """
    Parse a Claude Code session JSONL into (turns, session_date).
    Extracts only text-type content blocks; skips thinking/tool_use/tool_result.
    """
    turns = []
    session_date = ""
    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") not in ("user", "assistant"):
                continue

            if not session_date and obj.get("timestamp"):
                session_date = obj["timestamp"][:10]  # YYYY-MM-DD

            content = obj.get("message", {}).get("content", "")
            if isinstance(content, str):
                text = content.strip()
            elif isinstance(content, list):
                text = " ".join(
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ).strip()
            else:
                continue

            if text:
                turns.append({"role": obj["type"], "content": text})

    return turns, session_date


def _reviewed_sessions_file() -> Path:
    reviewed_dir = Path.home() / ".dory"
    reviewed_dir.mkdir(parents=True, exist_ok=True)
    return reviewed_dir / "reviewed_sessions.txt"


def _is_reviewed(session_id: str) -> bool:
    f = _reviewed_sessions_file()
    if not f.exists():
        return False
    return session_id in f.read_text().splitlines()


def _mark_reviewed(session_id: str) -> None:
    f = _reviewed_sessions_file()
    with open(f, "a") as fh:
        fh.write(session_id + "\n")


def cmd_review_session(args, graph: Graph) -> None:
    """
    Parse a Claude Code session transcript and run it through Observer
    to extract durable memories into the graph.

    Called from a Claude Code Stop hook (--from-hook reads transcript_path
    from the hook JSON payload on stdin), or directly with --file.
    """
    from dory.pipeline import Observer

    # --- Resolve transcript path ---
    if args.from_hook:
        raw = sys.stdin.read().strip()
        try:
            hook_data = json.loads(raw)
            transcript_path = Path(hook_data["transcript_path"])
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[dory review-session] Could not parse hook stdin: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.file:
        transcript_path = Path(args.file)
    else:
        transcript_path = _find_latest_claude_session()
        if not transcript_path:
            print("[dory review-session] No Claude Code session found for current directory.", file=sys.stderr)
            sys.exit(1)

    if not transcript_path.exists():
        print(f"[dory review-session] Transcript not found: {transcript_path}", file=sys.stderr)
        sys.exit(1)

    session_id = transcript_path.stem  # UUID filename without .jsonl

    if not args.force and _is_reviewed(session_id):
        print(f"[dory review-session] Already reviewed: {session_id}")
        return

    # --- Parse turns ---
    turns, session_date = _parse_claude_session(transcript_path)
    if not turns:
        print(f"[dory review-session] No text turns found in {transcript_path.name}")
        return

    print(f"[dory review-session] {len(turns)} turns | session {session_id[:8]}… | date {session_date or 'unknown'}")

    # --- Config from args or env ---
    backend  = args.backend  or os.getenv("DORY_BACKEND",  "anthropic")
    model    = args.model    or os.getenv("DORY_MODEL",    "claude-haiku-4-5-20251001")
    api_key  = args.api_key  or os.getenv("ANTHROPIC_API_KEY", "")
    base_url = args.base_url or os.getenv("DORY_BASE_URL", "http://localhost:8000")

    obs = Observer(
        graph=graph,
        model=model,
        backend=backend,
        api_key=api_key,
        base_url=base_url,
        threshold=args.threshold,
    )

    for turn in turns:
        obs.add_turn(turn["role"], turn["content"])

    stats = obs.flush(session_date=session_date)
    _mark_reviewed(session_id)

    print(f"[dory review-session] Done:")
    print(f"  turns logged:    {stats['turns_logged']}")
    print(f"  extractions run: {stats['extractions_run']}")
    print(f"  nodes written:   {stats['nodes_written']}")
    print(f"  nodes skipped:   {stats['nodes_skipped']}")
    print(f"  errors:          {stats['errors']}")


def cmd_consolidate(args, graph: Graph) -> None:
    result = session.end_session(graph)
    if args.json:
        print(json.dumps({
            "ok": True,
            "command": "consolidate",
            "db_path": str(graph.path),
            "result": result,
        }))
        return

    print(f"Consolidation complete:")
    print(f"  Pruned edges:      {result['pruned_edges']}")
    print(f"  Promoted core:     {result['promoted_core']}")
    print(f"  Demoted core:      {result['demoted_core']}")
    print(f"  Archived nodes:    {result['archived_nodes']}")
    print(f"  Expired nodes:     {result['expired_nodes']}")
    print(f"  Restored nodes:    {result['restored_nodes']}")
    print(f"  Duplicates merged: {result['duplicates_merged']}")
    print(f"  Supersessions:     {result['supersessions']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dory — graph memory CLI for AI agent sessions"
    )
    parser.add_argument(
        "--graph",
        help="Path to SQLite graph file (default: $DORY_DB_PATH or ~/.dory/engram.db)",
        default=None,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # query
    p_query = sub.add_parser("query", help="Spread activation and return context")
    p_query.add_argument("topic", nargs="+", help="Topic or query terms")
    p_query.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    # observe
    p_obs = sub.add_parser("observe", help="Add a new observation node")
    p_obs.add_argument("type", help="Node type: ENTITY, CONCEPT, EVENT, PREFERENCE, BELIEF")
    p_obs.add_argument("content", nargs="+", help="Natural language description")
    p_obs.add_argument("--tags", help="Comma-separated tags", default=None)
    p_obs.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    # link
    p_link = sub.add_parser("link", help="Create a typed edge between two nodes")
    p_link.add_argument("src", help="Source node ID")
    p_link.add_argument("tgt", help="Target node ID")
    p_link.add_argument("edge_type", help="Edge type: USES, PART_OF, PREFERS, etc.")
    p_link.add_argument("--weight", help="Edge weight 0.0-1.0 (default 0.8)", default=None)

    # list
    p_list = sub.add_parser("list", help="List all nodes")
    p_list.add_argument("--type", help="Filter by node type", default=None)

    # show
    p_show = sub.add_parser("show", help="Show graph stats and core memories")
    p_show.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    # explain
    p_explain = sub.add_parser("explain", help="Show provenance chain for a node — what it replaced and what replaced it")
    p_explain.add_argument("node_id", help="Node ID or content substring to look up")

    # visualize
    p_viz = sub.add_parser("visualize", help="Open an interactive graph visualization in the browser")
    p_viz.add_argument("--output", type=lambda p: Path(p), default=None, help="Save HTML to this path instead of a temp file")
    p_viz.add_argument("--archived", action="store_true", help="Include archived nodes")
    p_viz.add_argument("--expired",  action="store_true", help="Include expired nodes")
    p_viz.add_argument("--no-open",  action="store_true", help="Save the file but don't open the browser")
    p_viz.add_argument("--remote-assets", action="store_true", help="Allow remote D3.js for the fully interactive graph view")

    # consolidate
    p_cons = sub.add_parser("consolidate", help="Run end-of-session consolidation")
    p_cons.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    # review-session
    p_review = sub.add_parser(
        "review-session",
        help="Extract memories from a Claude Code session transcript",
    )
    src = p_review.add_mutually_exclusive_group()
    src.add_argument(
        "--from-hook", action="store_true",
        help="Read transcript_path from Claude Code Stop hook JSON on stdin",
    )
    src.add_argument(
        "--file", default=None, metavar="PATH",
        help="Path to a Claude Code session .jsonl file",
    )
    p_review.add_argument(
        "--backend", default=None,
        help="LLM backend: anthropic|ollama|openai (default: $DORY_BACKEND or anthropic)",
    )
    p_review.add_argument(
        "--model", default=None,
        help="Extraction model (default: $DORY_MODEL or claude-haiku-4-5-20251001)",
    )
    p_review.add_argument(
        "--api-key", default=None, dest="api_key",
        help="API key (default: $ANTHROPIC_API_KEY)",
    )
    p_review.add_argument(
        "--base-url", default=None, dest="base_url",
        help="Base URL for openai-compat backend (default: $DORY_BASE_URL)",
    )
    p_review.add_argument(
        "--threshold", type=int, default=10,
        help="Observer turn threshold for auto-extraction (default: 10)",
    )
    p_review.add_argument(
        "--force", action="store_true",
        help="Re-process even if this session was already reviewed",
    )

    args = parser.parse_args()

    from dory.store import DEFAULT_GRAPH_PATH
    env_graph = os.getenv("DORY_DB_PATH")
    graph_path = Path(args.graph) if args.graph else Path(env_graph) if env_graph else DEFAULT_GRAPH_PATH
    graph = Graph(path=graph_path)

    dispatch = {
        "query": cmd_query,
        "observe": cmd_observe,
        "link": cmd_link,
        "list": cmd_list,
        "show": cmd_show,
        "explain": cmd_explain,
        "visualize": cmd_visualize,
        "consolidate": cmd_consolidate,
        "review-session": cmd_review_session,
    }
    dispatch[args.command](args, graph)


if __name__ == "__main__":
    main()
