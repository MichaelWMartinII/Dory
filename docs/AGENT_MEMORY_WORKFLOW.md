# Agent Memory Workflow

This repo can use `Dory` as a real working memory layer for tools like Codex
and Claude Code instead of treating it as benchmark-only infrastructure.

## Goal

Keep durable project state outside the model:

- current priorities
- key decisions
- benchmark status
- open risks
- session summaries

That lets a new session recover context with a query instead of relying on the
base model to remember prior conversations.

## Recommended local setup

Use a repo-local database for this project:

```bash
cd /path/to/Dory
export DORY_DB_PATH="$PWD/.dory/engram.db"
```

The repo now ignores `.dory/`, so the local memory file and reviewed-session
state do not clutter git.

## Basic loop

At session start:

```bash
export DORY_DB_PATH="$PWD/.dory/engram.db"
python dory_cli.py query "current Dory project status"
```

When a durable fact or decision appears:

```bash
python dory_cli.py observe CONCEPT "Dory repo-quality hardening and cleanup pass was pushed to origin/main on 2026-03-29"
python dory_cli.py observe EVENT "Current workstream is v0.6 benchmark-quality improvements"
python dory_cli.py observe BELIEF "LongMemEval full runs should be reserved for release-candidate checks due to cost"
```

At the end of a work session:

```bash
python dory_cli.py consolidate
```

## Claude Code session ingestion

`dory_cli.py review-session` can extract durable memories from Claude Code
session transcripts.

Manual review of the latest local session for this repo:

```bash
export DORY_DB_PATH="$PWD/.dory/engram.db"
python dory_cli.py review-session
```

Manual review of a specific transcript:

```bash
python dory_cli.py review-session --file /path/to/session.jsonl
```

This is the cleanest current path for making Claude Code sessions durable
without manually re-entering every project decision.

## MCP usage

If Claude Code is configured with the Dory MCP server, the agent should:

1. Call `dory_query` at the start of a session or topic switch.
2. Call `dory_observe` for durable facts, preferences, and project decisions.
3. Call `dory_consolidate` near the end of a work session.

That turns `Dory` into shared task memory instead of passive storage.

## Current project seed state

The local repo memory should capture at least:

- `Dory` is intended as persistent agent memory for tools like Codex and Claude Code.
- Repo hardening and documentation cleanup were committed and pushed on 2026-03-29.
- Remaining uncommitted work is benchmark-focused (`longmemeval.py`, activation,
  observer, summarizer, session, and working benchmark reports).
- Cheapest benchmark workflow is to iterate on spot checks before full 500-question runs.

## Revert

To stop using repo-local agent memory:

1. Unset `DORY_DB_PATH`.
2. Delete `.dory/` locally.
3. Remove any shell alias or editor/task configuration that exports `DORY_DB_PATH`.

No tracked source files depend on the presence of `.dory/`.
