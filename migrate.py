#!/usr/bin/env python3
"""
Migrate graph.json → engram.db

Run once:
  python migrate.py

Reads the existing graph.json and writes all nodes and edges into the
new SQLite store. The original graph.json is left untouched as a backup.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

JSON_PATH = Path(__file__).parent / "graph.json"
DB_PATH = Path(__file__).parent / "engram.db"


def main() -> None:
    if not JSON_PATH.exists():
        print(f"No graph.json found at {JSON_PATH} — nothing to migrate.")
        return

    with open(JSON_PATH) as f:
        data = json.load(f)

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    if not nodes and not edges:
        print("graph.json is empty — nothing to migrate.")
        return

    from dory import store

    if DB_PATH.exists():
        print(f"engram.db already exists at {DB_PATH}")
        resp = input("Overwrite? [y/N] ").strip().lower()
        if resp != "y":
            print("Aborted.")
            return
        DB_PATH.unlink()

    store.save(data, DB_PATH)

    # Verify
    loaded = store.load(DB_PATH)
    print(f"Migration complete:")
    print(f"  Nodes:  {len(loaded['nodes'])} (source: {len(nodes)})")
    print(f"  Edges:  {len(loaded['edges'])} (source: {len(edges)})")
    print(f"  DB:     {DB_PATH}")
    print(f"  Backup: {JSON_PATH} (untouched)")


if __name__ == "__main__":
    main()
