# Using Dory with Codex and other agent tools

`dory-mcp` is a standard MCP stdio server. Any tool that supports MCP can use it — Codex, Claude Code, Cursor, Windsurf, Continue, and others all share the same integration path.

## Install

```bash
pip install 'dory-memory[mcp]'
which dory-mcp   # note the full path — you'll need it in config
```

## Shared database

Point every tool at the same database file so they share one memory graph:

```bash
export DORY_DB_PATH="$HOME/.dory/engram.db"
```

Or pass `--db ~/.dory/engram.db` in each tool's MCP server args. The default is `~/.dory/engram.db` if neither is set.

## Codex

Add to `~/.codex/config.yaml`:

```yaml
mcpServers:
  dory:
    command: /full/path/to/dory-mcp
    args:
      - --db
      - ~/.dory/engram.db
```

## Claude Code

```bash
claude mcp add --scope user dory -- /full/path/to/dory-mcp --db ~/.dory/engram.db
claude mcp list   # should show dory ✓ Connected
```

## Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "dory": {
      "command": "/full/path/to/dory-mcp",
      "args": ["--db", "/Users/you/.dory/engram.db"]
    }
  }
}
```

## Cursor / Windsurf / Continue / any MCP client

Add to the tool's MCP server config (usually a JSON file):

```json
{
  "mcpServers": {
    "dory": {
      "command": "/full/path/to/dory-mcp",
      "args": ["--db", "/Users/you/.dory/engram.db"]
    }
  }
}
```

## Tools exposed

| Tool | What it does |
|---|---|
| `dory_query` | Spreading activation retrieval — call at session start or topic switch |
| `dory_observe` | Store a durable fact, preference, or decision |
| `dory_consolidate` | Decay, dedup, promote core memories — call at session end |
| `dory_stats` | Node/edge counts and core memory list |
| `dory_visualize` | Open the D3 graph in a browser |

## Recommended agent contract

Regardless of which tool you use:

1. **Session start** — call `dory_query` with the current topic to load relevant context.
2. **During work** — call `dory_observe` when a durable fact, decision, or preference appears.
3. **Session end** — call `dory_consolidate` to decay old memories and resolve conflicts.

That contract is more important than the client-specific configuration.

## What to store

Store:
- project goals and active workstreams
- architectural decisions and tradeoffs
- user preferences that matter across sessions
- benchmark status and open issues

Do not store:
- transient scratchpad thoughts
- one-off filler
- secrets or credentials
