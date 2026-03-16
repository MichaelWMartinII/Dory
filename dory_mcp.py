#!/usr/bin/env python3
"""
Dory MCP Server entry point.

Exposes Dory memory tools (query, observe, consolidate, stats) to any
MCP-compatible AI client such as Claude Desktop or Claude Code.

Usage:
  python dory_mcp.py [--db /path/to/engram.db]

  # Or set the database path via environment variable:
  DORY_DB_PATH=/path/to/engram.db python dory_mcp.py

Configure in Claude Desktop
(~/Library/Application Support/Claude/claude_desktop_config.json):

  {
    "mcpServers": {
      "dory": {
        "command": "dory-mcp",
        "args": ["--db", "/path/to/your/engram.db"]
      }
    }
  }

Configure in Claude Code:

  claude mcp add dory -- dory-mcp --db /path/to/your/engram.db

After pip install dory-memory[mcp], the `dory-mcp` script is available on PATH.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dory MCP server — graph memory for AI agents"
    )
    parser.add_argument(
        "--db",
        help="Path to Dory database file. Overrides DORY_DB_PATH env var.",
        default=None,
    )
    args = parser.parse_args()

    if args.db:
        os.environ["DORY_DB_PATH"] = args.db

    from dory.mcp_server import mcp
    mcp.run()


if __name__ == "__main__":
    main()
