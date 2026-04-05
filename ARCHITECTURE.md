# Dory Architecture

`Dory` is a local-first memory system for AI agents. It stores semantic memory,
episodic traces, and retrieval metadata in a single SQLite database, then uses
graph traversal plus query-specific routing to build context for an LLM.

The current implementation is not the original "Engram" prototype described in
older docs. This file describes the architecture that exists in the codebase
today.

## Design Goals

Dory is built around a few constraints:

1. Persistent memory should work without a server.
2. Retrieval should preserve relationships, not just chunks.
3. Context injection should stay small and cacheable.
4. Old memory should fade without losing provenance.
5. The system should support both manual writes and automatic extraction from
   conversation turns.

## System Overview

At a high level, Dory has five layers:

1. Storage: SQLite tables for nodes, edges, observations, compressed
   observations, and FTS5 indexes.
2. Graph model: in-memory `Graph` object for nodes, edges, salience, and
   mutation.
3. Retrieval: seed finding, spreading activation, and query routing across
   semantic and episodic memory.
4. Pipeline: `Observer`, `Prefixer`, `Decayer`, `Reflector`, and `Summarizer`.
5. Interfaces: Python API, CLI, framework adapters, visualization, and MCP.

## Storage Layer

The backing store is a single SQLite database, defaulting to
`~/.dory/engram.db`.

Defined in `dory/store.py`, the schema includes:

- `nodes`: canonical memory records
- `edges`: graph relationships between memories
- `nodes_fts`: FTS5 index over node content and tags
- `observations`: raw conversation turns
- `compressed_obs`: compressed observation blocks for older history

Important storage properties:

- SQLite runs in WAL mode so readers do not block writers.
- Connections are cached per thread because `Observer` can extract in parallel.
- FTS5 is always available; vector search is optional.
- The graph is loaded into memory and persisted back to SQLite on save.

## Data Model

### Node Types

Current node types are defined in `dory/schema.py`:

- `ENTITY`
- `CONCEPT`
- `EVENT`
- `PREFERENCE`
- `BELIEF`
- `SESSION`
- `PROCEDURE`
- `SESSION_SUMMARY`

Each node stores:

- `id`
- `type`
- `content`
- `created_at`
- `last_activated`
- `activation_count`
- `salience`
- `is_core`
- `tags`
- `zone`
- `superseded_at`
- `metadata`
- `distinct_sessions`

### Edge Types

Current edge types are:

- Explicit semantic edges:
  `WORKS_ON`, `BACKGROUND_IN`, `INTERESTED_IN`, `CAUSED`, `CONTRADICTS`,
  `PART_OF`, `INSTANCE_OF`, `TRIGGERED`, `PREFERS`, `USES`, `RELATED_TO`
- Provenance edge:
  `SUPERSEDES`
- Implicit associative edge:
  `CO_OCCURS`
- Episodic edges:
  `TEMPORALLY_AFTER`, `TEMPORALLY_BEFORE`, `MENTIONS`, `SUPPORTS_FACT`

Each edge stores:

- `id`
- `source_id`
- `target_id`
- `type`
- `weight`
- `created_at`
- `last_activated`
- `activation_count`
- `decay_rate`

### Visibility Zones

Nodes move between three retrieval zones:

- `active`: visible to normal retrieval
- `archived`: hidden from default retrieval but kept for historical access
- `expired`: hidden except for provenance and inspection

Nothing is deleted as part of normal forgetting. Zone changes are reversible.

## Graph Layer

`dory/graph.py` implements the in-memory graph.

Responsibilities:

- load nodes and edges from SQLite
- add and retrieve nodes and edges
- enforce typed edge reinforcement for repeated links
- recompute node salience
- expose graph stats

Salience is recomputed from:

- connectivity: normalized degree in the graph
- reinforcement: log-scaled `activation_count`
- diversity: `distinct_sessions` dampens one-session overfitting
- recency: exponential decay from `last_activated`

This means memory importance is partly emergent from use, not only from write
time labels.

## Retrieval Architecture

### Seed Finding

`dory/activation.py` finds initial seed nodes in three stages:

1. FTS5 BM25 search over node content and tags
2. Optional vector KNN search if `sqlite-vec` and embeddings are available
3. Substring fallback if neither returns useful results

FTS queries are intentionally broadened with OR-style term expansion for recall.

### Spreading Activation

After seed selection, activation spreads through neighboring edges up to a fixed
depth with depth decay:

`received = source_activation * edge_weight * depth_decay`

During spread:

- only `active` nodes participate
- activation accumulates across paths
- touched nodes and traversed edges get their activation metadata updated

Nodes with `salience < SALIENCE_FLOOR` (default 0.1) are skipped in
serialization after their first save cycle. This prevents low-signal memories
from polluting context.

The serialized result is a compact natural-language block containing:

- top activated nodes
- `[CORE]` markers for high-salience memories
- `[CURRENT VALUE]` markers for nodes that supersede older values
- duration hints for nodes with a known `start_date` metadata field:
  `(~9 months, since 2023-03-01)` — computed from `reference_date`
- occurrence and amount hints for tracked quantities:
  `(×3, 3 days/week)` or `[$400,000]`
- relationship lines between activated nodes

`serialize()` accepts an optional `reference_date` (ISO date string) so
duration hints are anchored to the question date rather than wall clock time.

### Query Routing

Dory does not use one retrieval mode for every question.

`dory/session.py` routes a query into one of four modes using deterministic
regex heuristics:

- `graph`: stable facts, preferences, relationships
- `episodic`: chronology, counting, relative-time, and event questions
- `hybrid`: changes over time, preferences, cross-session evolution
- `procedure`: workflow and how-to questions

This is a major part of the current architecture. The retrieval path depends on
the question type.

### Episodic Retrieval

For temporal and aggregation queries, Dory uses episodic memory instead of only
semantic nodes.

Key mechanisms:

- `SESSION` nodes preserve chronological session context
- `SESSION_SUMMARY` nodes provide compressed episodic summaries
- `MENTIONS` and `SUPPORTS_FACT` edges connect summaries to semantic nodes
- `salient_counts` in summary metadata let the model answer counting questions
  from structured totals instead of recounting prose

The retrieval formatter can aggregate counts across summaries before injecting
them into the prompt.

## Write Path

### Manual Observation

Manual writes go through `session.observe()` or `DoryMemory.observe()`.

This path:

1. sanitizes node content
2. creates the node
3. saves immediately so FTS stays current
4. opportunistically links related nodes

Manual writes are the simplest and most deterministic way to add memory.

### Automatic Extraction with Observer

`dory/pipeline/observer.py` is the extraction engine.

It buffers conversation turns, logs raw observations, and periodically calls an
LLM to extract durable nodes and edges.

Current properties:

- supports `ollama`, `anthropic`, and OpenAI-compatible backends
- extraction is asynchronous via `ThreadPoolExecutor`
- writes are serialized with a lock even when extraction calls run concurrently
- low-confidence memories are filtered before graph insertion
- extraction can attach `supersedes_hint` to support later knowledge updates
- node `activation_count` is seeded from extraction confidence

The extraction schema includes optional structured fields beyond content and
type:

- `start_date` (YYYY-MM-DD): when a fact began, for "how long have I..." queries
- `amount`: quantifiable value with unit (e.g. `"3 times/week"`, `"$400,000"`)
- `occurrence_count`: incremented on each reinforcement of an existing node

On each write, Observer checks for implicit supersession: if a similar node
exists at similarity ≥ 0.45 and the numeric value in the new fact differs from
the old one, the old node is archived and linked with a `SUPERSEDES` edge. This
supplements the explicit `supersedes_hint` path in the Reflector.

Observer is responsible for semantic memory creation, not full transcript
preservation.

## Prompt Construction

`dory/pipeline/prefixer.py` builds context blocks with a split architecture:

- stable prefix: core memories plus top non-core high-salience facts
- dynamic suffix: per-query retrieval and recent observations

Why this exists:

- full RAG-style reinjection changes every prompt and kills cache reuse
- a stable prefix enables prompt caching in Anthropic and repeated-prefix reuse
  in OpenAI-compatible APIs

The prefix is cached and invalidated only when graph state changes
meaningfully.

## Consolidation Pipeline

`DoryMemory.flush()` ends a session by combining extraction and consolidation.

The consolidation pipeline currently runs through `dory/consolidation.py` and
the pipeline modules it invokes.

### 1. Edge Decay and Pruning

`consolidation.decay()` and `consolidation.prune()`:

- decay edge weights based on time since last activation
- remove very weak edges

### 2. Core Promotion and Demotion

`consolidation.promote_core()` and `consolidation.demote_core()`:

- promote high-salience nodes to core memory
- demote stale core nodes

### 3. Node Zone Management

`dory/pipeline/decayer.py` scores each node using:

- recency
- frequency
- relevance proxy from salience

Then moves nodes between `active`, `archived`, and `expired`.

Core memories get partial protection through lower archival thresholds.

### 4. Reflection

`dory/pipeline/reflector.py` performs maintenance that changes the meaning of
the graph, not just its weights:

- near-duplicate merge
- supersession detection for updated facts
- optional compression of older observations
- behavioral preference synthesis

Supersession is the key provenance mechanism. Older facts are archived and linked
with `SUPERSEDES` instead of being overwritten.

### 5. Session Summarization

If a summarizer is attached, the session can also be compressed into a
`SESSION_SUMMARY` node with:

- narrative summary
- topics
- `salient_counts`
- session date

This layer improves temporal reasoning, session recall, and cross-session
counting.

## Interfaces

### Python API

`DoryMemory` in `dory/memory.py` is the main high-level API.

It exposes:

- `observe()`
- `add_turn()`
- `query()`
- `build_context()`
- `flush()`
- async variants of all major methods
- direct graph access for power users

### CLI

`dory_cli.py` exposes:

- `query`
- `observe`
- `link`
- `list`
- `show`
- `visualize`
- `consolidate`
- `review-session`

`review-session` is specialized for Claude Code transcripts and runs them back
through `Observer`.

`visualize` now defaults to a local-only HTML fallback view. Remote D3.js is an
explicit opt-in for the fully interactive graph.

### MCP Server

`dory/mcp_server.py` exposes five tools:

- `dory_query(topic, reference_date="")` — optional ISO date anchors duration hints
- `dory_observe`
- `dory_consolidate`
- `dory_visualize`
- `dory_stats`

This is the bridge for Claude Code and other MCP-compatible clients.

### Adapters

The `adapters/` package provides integrations for:

- LangChain
- LangGraph
- multi-agent shared memory

## Operational Model

A typical session looks like this:

1. Query memory at session start or topic switch.
2. Inject prefix and suffix into the model prompt.
3. Log new conversation turns as they happen.
4. Extract durable memories asynchronously in the background.
5. Flush at the end of the session.
6. Decay stale memory, resolve conflicts, and optionally summarize the session.

## Tradeoffs

This architecture makes a few deliberate tradeoffs:

- SQLite over a service stack:
  simpler deployment, lower ops cost, weaker horizontal scaling
- Graph retrieval over pure vector search:
  better relationship handling, more hand-tuned heuristics
- Query routing over one universal retriever:
  more control, more maintenance burden
- Provenance through supersession and zones over deletion:
  better historical reasoning, more graph complexity
- Cacheable prefix over full dynamic context:
  cheaper and more stable prompts, but requires careful invalidation

## Module Map

Current package layout:

```text
dory/
├── activation.py        # seed finding, spreading activation, serialization
├── consolidation.py     # top-level consolidation orchestration
├── graph.py             # in-memory graph model and salience
├── memory.py            # high-level public API
├── mcp_server.py        # MCP tool server
├── sanitize.py          # content cleanup for writes
├── schema.py            # node/edge types and dataclasses
├── session.py           # retrieval routing and write helpers
├── store.py             # SQLite schema and persistence
├── visualize.py         # HTML graph visualization
├── adapters/            # LangChain, LangGraph, multi-agent
├── export/              # JSON-LD export/import
└── pipeline/
    ├── observer.py      # LLM extraction from turns
    ├── prefixer.py      # stable prefix + dynamic suffix builder
    ├── decayer.py       # node visibility-zone management
    ├── reflector.py     # deduplication and supersession
    └── summarizer.py    # episodic session summaries
```

## What This Document Intentionally Does Not Claim

This is a code-aligned architecture doc, not a research claim.

It does not assume:

- that every retrieval path is optimal
- that vector search is always enabled
- that behavioral synthesis is always desirable
- that the benchmark pipeline and the runtime library are the same thing

Those are active tuning areas. This document describes the moving parts that
exist today so future changes can be reasoned about against the real system.
