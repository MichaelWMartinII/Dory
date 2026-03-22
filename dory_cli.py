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
    print(session.query(" ".join(args.topic), graph))
    graph.save()


def cmd_observe(args, graph: Graph) -> None:
    try:
        node_type = NodeType(args.type.upper())
    except ValueError:
        print(f"Unknown node type: {args.type}. Valid: {[t.value for t in NodeType]}")
        sys.exit(1)
    tags = args.tags.split(",") if args.tags else []
    node_id = session.observe(" ".join(args.content), node_type, graph, tags=tags)
    graph.save()
    print(f"Added node {node_id}: {' '.join(args.content)}")


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
    print(f"Nodes:      {stats['nodes']}")
    print(f"Edges:      {stats['edges']}")
    print(f"Core nodes: {stats['core_nodes']}")
    print()
    core_nodes = [n for n in graph.all_nodes() if n.is_core]
    if core_nodes:
        print("Core memories:")
        for n in sorted(core_nodes, key=lambda n: n.salience, reverse=True):
            print(f"  [{n.type.value}] {n.content}  (salience={n.salience:.2f})")


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
        help="Path to graph JSON file (default: ~/.claude memory dir)",
        default=None,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # query
    p_query = sub.add_parser("query", help="Spread activation and return context")
    p_query.add_argument("topic", nargs="+", help="Topic or query terms")

    # observe
    p_obs = sub.add_parser("observe", help="Add a new observation node")
    p_obs.add_argument("type", help="Node type: ENTITY, CONCEPT, EVENT, PREFERENCE, BELIEF")
    p_obs.add_argument("content", nargs="+", help="Natural language description")
    p_obs.add_argument("--tags", help="Comma-separated tags", default=None)

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
    sub.add_parser("show", help="Show graph stats and core memories")

    # visualize
    p_viz = sub.add_parser("visualize", help="Open an interactive graph visualization in the browser")
    p_viz.add_argument("--output", type=lambda p: Path(p), default=None, help="Save HTML to this path instead of a temp file")
    p_viz.add_argument("--archived", action="store_true", help="Include archived nodes")
    p_viz.add_argument("--expired",  action="store_true", help="Include expired nodes")
    p_viz.add_argument("--no-open",  action="store_true", help="Save the file but don't open the browser")

    # consolidate
    sub.add_parser("consolidate", help="Run end-of-session consolidation")

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
    graph_path = Path(args.graph) if args.graph else DEFAULT_GRAPH_PATH
    graph = Graph(path=graph_path)

    dispatch = {
        "query": cmd_query,
        "observe": cmd_observe,
        "link": cmd_link,
        "list": cmd_list,
        "show": cmd_show,
        "visualize": cmd_visualize,
        "consolidate": cmd_consolidate,
        "review-session": cmd_review_session,
    }
    dispatch[args.command](args, graph)


if __name__ == "__main__":
    main()
