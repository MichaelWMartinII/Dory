#!/usr/bin/env python3
"""
Engram CLI — session-based graph memory for Claude Code.

Usage:
  python engram_cli.py query "AllergyFind database"
  python engram_cli.py observe CONCEPT "Michael prefers Apache 2.0 licenses"
  python engram_cli.py link <src_id> <tgt_id> USES
  python engram_cli.py list [--type CONCEPT]
  python engram_cli.py show
  python engram_cli.py consolidate
"""

import argparse
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


def cmd_consolidate(args, graph: Graph) -> None:
    result = session.end_session(graph)
    print(f"Consolidation complete:")
    print(f"  Pruned edges:   {result['pruned_edges']}")
    print(f"  Promoted core:  {result['promoted_core']}")
    print(f"  Demoted core:   {result['demoted_core']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Engram — graph memory CLI for Claude Code sessions"
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

    # consolidate
    sub.add_parser("consolidate", help="Run end-of-session consolidation")

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
        "consolidate": cmd_consolidate,
    }
    dispatch[args.command](args, graph)


if __name__ == "__main__":
    main()
