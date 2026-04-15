# Dory Memory

Use `Dory` as shared persistent memory across Codex and Claude Code sessions.

## Shared database

Default to the same database path Claude Code uses:

```bash
export DORY_DB_PATH="${DORY_DB_PATH:-$HOME/.dory/engram.db}"
```

If the current repo defines a different explicit path for team use, prefer that.

## Workflow

At the start of meaningful work:

```bash
python /path/to/Dory/dory_cli.py query --json "current project status"
```

When you learn a durable fact, decision, preference, or ongoing workstream:

```bash
python /path/to/Dory/dory_cli.py observe --json CONCEPT "..."
```

At the end of a session or major task:

```bash
python /path/to/Dory/dory_cli.py consolidate --json
```

## What to store

Store:

- project goals and active workstreams
- architectural decisions
- user preferences that matter across sessions
- benchmark status and open issues

Do not store:

- transient scratchpad thoughts
- one-off filler
- secrets unless the operator explicitly wants them in the memory graph

## Expected behavior

- Query memory at the start of a task or topic switch.
- Observe durable facts as they emerge.
- Favor concise, durable observations over long transcripts.
- Consolidate after meaningful work completes.
