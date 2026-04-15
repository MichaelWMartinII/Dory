# Codex Integration

This document describes the easiest path to use `Dory` with Codex while
sharing the same persistent memory graph used by Claude Code.

## Goal

Use one database for both tools:

- Claude Code via `dory-mcp`
- Codex via a local plugin or direct CLI calls

The recommended shared path is:

```bash
~/.dory/engram.db
```

That keeps memory durable across sessions and across tools.

## What was added

This repo now includes:

- a Codex plugin scaffold at `plugins/dory-memory/`
- a local plugin marketplace entry at `.agents/plugins/marketplace.json`
- machine-readable CLI output for:
  - `dory query --json`
  - `dory observe --json`
  - `dory show --json`
  - `dory consolidate --json`

These JSON modes make it possible for Codex-side tooling to call `Dory`
without scraping human-readable terminal output.

## Shared setup

Install the package:

```bash
pip install 'dory-memory[mcp]'
```

Use the same database path everywhere:

```bash
export DORY_DB_PATH="$HOME/.dory/engram.db"
```

Claude Code can keep using:

```bash
claude mcp add --scope user dory -- dory-mcp --db ~/.dory/engram.db
```

## Codex path

There are two viable Codex integration paths.

### 1. Plugin path

Point Codex at the local plugin marketplace in this repo and install the
`dory-memory` plugin.

The plugin is intentionally thin. It standardizes the workflow:

- query memory at session start
- observe durable facts during work
- consolidate at session end

### 2. Direct CLI path

Even without plugin installation, Codex can use the same shared memory by
calling the CLI directly:

```bash
export DORY_DB_PATH="$HOME/.dory/engram.db"
python /path/to/Dory/dory_cli.py query --json "current project status"
python /path/to/Dory/dory_cli.py observe --json CONCEPT "Current workstream is v0.8 benchmark iteration"
python /path/to/Dory/dory_cli.py consolidate --json
```

## Recommended agent contract

For Codex and other agent tools, the integration contract should be:

1. At session start or topic switch, query memory.
2. When a durable fact or decision appears, store it.
3. At session end, consolidate memory.

That contract is more important than the client-specific UI.

## Limitations

- This does not magically attach every Codex session to `Dory`; the client
  still needs to install the plugin or call the CLI.
- Claude Code remains the more mature MCP environment today.
- Codex integration is currently a local-plugin workflow, not a published
  marketplace integration.

## Revert

To remove the Codex integration scaffolding:

1. Delete `.agents/plugins/marketplace.json`.
2. Delete `plugins/dory-memory/`.
3. Stop using `--json` CLI modes if they are no longer needed.
