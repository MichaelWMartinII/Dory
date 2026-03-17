# Dory: Complete Technical Overview

**Agent memory that actually sticks.**

*A Python-native, local-first knowledge graph memory library for AI agents.*

---

## Table of Contents

1. [What Dory Is — For Everyone](#1-what-dory-is--for-everyone)
2. [The Problem Dory Solves](#2-the-problem-dory-solves)
3. [How It Works — Conceptual Overview](#3-how-it-works--conceptual-overview)
4. [Architecture Map](#4-architecture-map)
5. [Schema: Nodes, Edges, and Zones](#5-schema-nodes-edges-and-zones)
6. [Storage Layer: SQLite Backend](#6-storage-layer-sqlite-backend)
7. [The Knowledge Graph](#7-the-knowledge-graph)
8. [Spreading Activation Retrieval](#8-spreading-activation-retrieval)
9. [Session Management and Query Routing](#9-session-management-and-query-routing)
10. [The Observer: Extracting Memories from Conversation](#10-the-observer-extracting-memories-from-conversation)
11. [The Summarizer: Episodic Memory](#11-the-summarizer-episodic-memory)
12. [The Prefixer: Cacheable Context Output](#12-the-prefixer-cacheable-context-output)
13. [The Decayer: Principled Forgetting](#13-the-decayer-principled-forgetting)
14. [The Reflector: Deduplication and Conflict Resolution](#14-the-reflector-deduplication-and-conflict-resolution)
15. [Consolidation: End-of-Session Housekeeping](#15-consolidation-end-of-session-housekeeping)
16. [Framework Adapters](#16-framework-adapters)
17. [Multi-Agent Shared Memory](#17-multi-agent-shared-memory)
18. [JSON-LD Export and Import](#18-json-ld-export-and-import)
19. [Visualization](#19-visualization)
20. [MCP Server: Memory for Claude](#20-mcp-server-memory-for-claude)
21. [CLI Reference](#21-cli-reference)
22. [Complete Defaults and Thresholds](#22-complete-defaults-and-thresholds)
23. [Benchmark Results: LongMemEval](#23-benchmark-results-longmemeval)
24. [Design Decisions and Trade-offs](#24-design-decisions-and-trade-offs)
25. [Research Basis](#25-research-basis)

---

## 1. What Dory Is — For Everyone

### The simple version

Every time you start a conversation with an AI assistant, it starts from scratch. It doesn't remember that you told it last Tuesday what you're building. It doesn't remember that you prefer a certain coding style. It doesn't remember that you already solved that bug three weeks ago. Every session is a blank slate.

Dory fixes that. It gives AI agents a memory that persists across sessions, organized as a **knowledge graph** — a web of connected facts, where related ideas are linked together. When you ask about something, Dory doesn't just keyword-search a flat list of notes. It starts from the most relevant memories and *follows the connections*, pulling in related context the way a human mind naturally would.

### The technical version

Dory is a Python library that implements a persistent, typed knowledge graph backed by a single SQLite file. It provides:

- **Memory storage**: Five semantic node types (Entity, Concept, Event, Preference, Belief, Procedure) connected by typed, weighted edges
- **Spreading activation retrieval**: Graph traversal that follows connections to surface contextually relevant memories — not just exact keyword matches
- **Principled forgetting**: Three-zone decay system (active → archived → expired) with salience-based scoring, so memory doesn't grow unbounded
- **Bi-temporal conflict resolution**: When facts change, old versions are archived with a `SUPERSEDES` provenance edge — queryable for historical context
- **Cacheable prefix output**: Stable context blocks that hit prompt cache every turn, making memory injection 4–10x cheaper
- **Zero-server stack**: Everything in a single SQLite file. No Postgres, no Neo4j, no Redis, no network. Works offline.
- **Framework integrations**: LangChain, LangGraph, multi-agent pools, MCP server for Claude
- **Full async API**: Every method has an async counterpart for FastAPI, LangGraph, and event-loop-based applications

---

## 2. The Problem Dory Solves

### Problem 1: Agents forget everything

LLMs have no persistent state. Each session starts empty. Even products that claim "memory" are typically doing keyword search over a flat list of saved notes — what the Dory README calls "ctrl+F, not memory."

The result: agents can't build on prior sessions, can't track evolving projects, can't remember user preferences, can't notice that a question was already answered last week.

### Problem 2: Naive memory injection makes things worse

Dumping everything you know into the context window actively harms model performance. Research from Chroma (2025) showed that all major frontier models start degrading at 500–750 tokens of injected context. More isn't better — it's noise.

The correct solution is *selective, structured* injection: pull only what's relevant, organize it hierarchically (stable core facts first, query-specific detail second), and keep it under the degradation threshold.

### Problem 3: Memory injection kills prompt caching

Prompt caching (supported by Anthropic, OpenAI, and others) gives you up to 10x cost reduction when identical bytes appear at the start of your prompt. But if you rebuild your memory context from scratch every turn — personalizing it based on the current query — the prefix changes every turn and you get zero cache hits.

Dory's Prefixer solves this: it splits context into a **stable prefix** (core memories, same until the graph actually changes) and a **dynamic suffix** (query-specific retrieval, small and fresh). Cache hits every turn, meaningful context every turn.

---

## 3. How It Works — Conceptual Overview

### The lifecycle of a memory

1. **A conversation happens.** The Observer buffers conversation turns.
2. **Every 5 turns**, the Observer calls an LLM (local or cloud) to extract structured memories: "Michael is building AllergyFind, a B2B allergen platform." This becomes a `CONCEPT` node.
3. **Auto-linking**: the new node is linked to related existing nodes via FTS search and `CO_OCCURS` edges — "AllergyFind" gets connected to "FastAPI," "Giovanni's," "menu endpoint."
4. **Episodic capture**: The Summarizer simultaneously creates `SESSION` nodes — date-stamped summaries of what happened in each session, capturing specific details that might not survive semantic extraction.
5. **At session end**, `flush()` is called. The Decayer scores every node and moves low-scoring ones to archived or expired. The Reflector merges near-duplicates and creates `SUPERSEDES` edges for changed facts.
6. **Next session**: the Prefixer builds a stable prefix from high-salience core memories, and a query-specific suffix via spreading activation. This context is injected into the system prompt.

### The graph structure

Think of a city map where:
- **Nodes** are landmarks (people, projects, concepts, events, preferences)
- **Edges** are roads between them (uses, works-on, prefers, supersedes)
- **Salience** is how busy a landmark is — how often you visit, how recently, how well-connected
- **Core memories** are the landmarks that go on the tourist map — always included in context
- **Spreading activation** is how you navigate: start at your destination, and all nearby points-of-interest light up

---

## 4. Architecture Map

```
dory/
├── schema.py         Node types, edge types, zone constants, Node/Edge dataclasses
├── store.py          SQLite backend: nodes, edges, FTS5 index, episodic observations
├── graph.py          In-memory graph: add/get/find nodes, edges, salience computation
├── activation.py     Spreading activation engine + seed finding (FTS + vector + substring)
├── session.py        High-level session ops: query routing, observe, link, write_turn
├── consolidation.py  End-of-session pipeline: decay → prune → promote → demote → reflect
├── memory.py         DoryMemory — the drop-in public API (sync + async)
├── visualize.py      D3.js interactive graph visualization
├── mcp_server.py     MCP tool definitions (query, observe, consolidate, stats, visualize)
├── store.py          SQLite backend (nodes, edges, FTS5, observations)
│
├── pipeline/
│   ├── observer.py   LLM extraction: conversation turns → structured graph nodes
│   ├── summarizer.py Episodic capture: turns → SESSION nodes with date prefix
│   ├── prefixer.py   Builds stable prefix + dynamic suffix for prompt injection
│   ├── decayer.py    Zone management: active / archived / expired scoring
│   └── reflector.py  Dedup (Jaccard merge), supersession detection, obs compression
│
├── adapters/
│   ├── langchain.py  DoryMemoryAdapter — LangChain BaseMemory drop-in
│   ├── langgraph.py  DoryMemoryNode — LangGraph StateGraph nodes
│   └── multi_agent.py SharedMemoryPool — thread-safe multi-agent shared graph
│
└── export/
    └── jsonld.py     JSONLDExporter — W3C JSON-LD portable export/import
```

**Entry points:**
- `dory_cli.py` — CLI tool (`dory` command)
- `dory_mcp.py` — MCP server entry point (`dory-mcp` command)

---

## 5. Schema: Nodes, Edges, and Zones

### Node Types

Every piece of memory is a `Node` with a specific semantic type:

| Type | What it stores | Example |
|---|---|---|
| `ENTITY` | A person, place, project, tool, or organization | "AllergyFind", "Giovanni Ristorante Nashville", "FastAPI" |
| `CONCEPT` | An idea, domain, technology, or pattern | "JWT authentication", "spreading activation", "B2B SaaS" |
| `EVENT` | Something that happened or was decided | "Shipped menu endpoint on 2025-03-14", "Giovanni went live" |
| `PREFERENCE` | A stated or clearly implied working style | "Prefers local-first AI", "Prefers async FastAPI endpoints" |
| `BELIEF` | An assertion about the world | "Local LLMs are sufficient for most memory extraction tasks" |
| `SESSION` | A dated summary of a past session | "[2025-03-14] Session: Worked on Dory temporal query improvements..." |
| `PROCEDURE` | A repeatable workflow, skill, or algorithm | "LongMemEval benchmark run procedure: set ANTHROPIC_API_KEY, run benchmarks/longmemeval.py..." |

**Why typed nodes matter**: Type information governs retrieval, formatting, and decay. SESSION nodes are always injected for temporal queries. PROCEDURE nodes are always included in the prefix (they represent persistent skills). PREFERENCE and BELIEF nodes get higher core promotion scores.

### The Node Dataclass

```python
@dataclass
class Node:
    id: str                    # 8-character UUID prefix (unique, short, readable)
    type: NodeType             # One of the seven types above
    content: str               # Natural language description
    created_at: str            # ISO 8601 UTC timestamp
    last_activated: str        # ISO 8601 — updated whenever node is accessed
    activation_count: int      # Lifetime retrieval count (starts 0)
    salience: float            # 0.0–1.0, computed from connectivity + frequency + recency
    is_core: bool              # True = always included in stable prefix
    tags: list[str]            # Free-form labels (e.g., ["agent:elwin", "project:allergyFind"])
    zone: str                  # "active", "archived", or "expired"
    superseded_at: str | None  # ISO timestamp if this node was superseded by a newer fact
```

### Edge Types

Edges are the connections between nodes. They are typed and weighted.

**Semantic edges** (set by Observer extraction):
- `WORKS_ON` — entity is working on a project or concept
- `BACKGROUND_IN` — entity has expertise in a domain
- `INTERESTED_IN` — entity has expressed interest
- `CAUSED` — one event caused another
- `CONTRADICTS` — two beliefs or facts are in tension
- `PART_OF` — hierarchical membership
- `INSTANCE_OF` — classification
- `TRIGGERED` — event triggered another event or action
- `PREFERS` — entity prefers something
- `USES` — entity or project uses a tool or technology
- `RELATED_TO` — general semantic relationship

**Provenance edges** (set by Reflector):
- `SUPERSEDES` — newer fact supersedes an older one (bi-temporal provenance)

**Implicit edges** (set by auto-linking):
- `CO_OCCURS` — two nodes frequently appear in the same context

### The Edge Dataclass

```python
@dataclass
class Edge:
    id: str               # 8-character UUID prefix
    source_id: str        # Source node ID
    target_id: str        # Target node ID
    type: EdgeType        # One of the types above
    weight: float         # 0.0–1.0. New edges start at 0.8.
    created_at: str       # ISO timestamp
    last_activated: str   # Updated when traversed by spreading activation
    activation_count: int # Times this edge was traversed
    decay_rate: float     # Per-day weight decay. Default 0.02.
```

**Edge reinforcement**: When an edge is traversed during retrieval, its weight increases by +0.1 (capped at 1.0). This implements Hebbian learning — edges between frequently co-accessed concepts get stronger over time.

**Edge decay**: Edges that aren't used lose weight at 0.02 per day. An edge that hasn't been traversed in 50 days drops from 0.8 to essentially 0.0 and is pruned.

### Memory Zones

Every node lives in one of three zones:

| Zone | Behavior | Threshold | Query behavior |
|---|---|---|---|
| `active` | Normal, fully visible | score ≥ 0.15 | Retrieved in all queries |
| `archived` | Invisible to normal queries | 0.04 ≤ score < 0.15 | Accessible with `zone="archived"` |
| `expired` | Completely invisible | score < 0.04 | Accessible with `zone=None` |

**Critical design decision: nothing is ever deleted.** Archived and expired nodes are retained in the database with full provenance. This enables:
- Historical queries ("What did we decide about auth in January?")
- Supersession lookups ("What was the old approach?")
- Re-activation if a topic resurfaces

---

## 6. Storage Layer: SQLite Backend

All data lives in a single SQLite file. Default path: `engram.db` in the current directory.

### Database Tables

**`nodes`** — the node store:
```sql
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_activated TEXT NOT NULL,
    activation_count INTEGER DEFAULT 0,
    salience REAL DEFAULT 0.0,
    is_core INTEGER DEFAULT 0,       -- boolean
    tags TEXT DEFAULT '[]',          -- JSON array
    zone TEXT DEFAULT 'active',
    superseded_at TEXT               -- nullable
)
```

**`edges`** — the edge store:
```sql
CREATE TABLE edges (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    type TEXT NOT NULL,
    weight REAL NOT NULL,
    created_at TEXT NOT NULL,
    last_activated TEXT NOT NULL,
    activation_count INTEGER DEFAULT 0,
    decay_rate REAL DEFAULT 0.02
)
```

**`nodes_fts`** — FTS5 virtual table for full-text search:
```sql
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    id UNINDEXED,     -- not tokenized
    content,          -- natural language, tokenized for BM25
    tags              -- tag strings, tokenized
)
```
This enables `BM25` ranked keyword search across all node content and tags — the primary seed-finding mechanism before spreading activation runs.

**`observations`** — raw episodic turn log:
```sql
CREATE TABLE observations (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    role TEXT,            -- "user", "assistant", "observer"
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    compressed INTEGER DEFAULT 0
)
```

**`compressed_obs`** — summarized observation batches:
```sql
CREATE TABLE compressed_obs (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    content TEXT NOT NULL,      -- LLM summary of source observations
    created_at TEXT NOT NULL,
    referenced_at TEXT,         -- when this summary was created
    source_ids TEXT DEFAULT '[]' -- JSON array of source observation IDs
)
```

### Why SQLite

SQLite was chosen deliberately over specialized graph databases (Neo4j) or vector databases (Chroma, Pinecone):

1. **Zero dependencies at runtime**: No server process, no network, no configuration. `pip install dory-memory` is everything.
2. **FTS5 is fast enough**: BM25 ranking over hundreds of nodes is sub-millisecond on SQLite FTS5.
3. **sqlite-vec for vectors**: Optional vector search via the `sqlite-vec` extension — same file, no additional process.
4. **Portability**: The entire memory is one file. Copy it, back it up, version-control it.
5. **Transactions**: SQLite ACID semantics prevent graph corruption on crash.

### Key Storage Functions

**`load(path) → dict`**: Reads all nodes and edges into Python dicts. Parses JSON tags, converts `is_core` integer to bool.

**`save(data, path)`**: Upserts all nodes and edges (INSERT OR REPLACE), deletes nodes/edges not in current data, rebuilds FTS5 index.

**`search_fts(query, path, limit=20) → list[str]`**: BM25 search. Strips FTS5 operators from the query string to prevent injection. Falls back to plain word matching if the FTS query fails. Returns node IDs ranked by relevance.

---

## 7. The Knowledge Graph

### The `Graph` Class

The `Graph` class is the in-memory representation of the knowledge graph. It wraps the SQLite backend and provides the API that all other components use.

```python
graph = Graph(path="myapp.db")
```

On construction, it loads all nodes and edges into memory as Python dicts (`_nodes: dict[str, Node]`, `_edges: dict[str, Edge]`). A `_dirty` flag tracks whether unsaved changes exist.

### Adding Nodes

```python
node = graph.add_node(
    type=NodeType.CONCEPT,
    content="JWT for API authentication",
    tags=["auth", "api"]
)
```

Nodes get auto-generated 8-character IDs and current UTC timestamps. The graph is marked dirty.

### Adding Edges

```python
edge = graph.add_edge(
    source_id=node_a.id,
    target_id=node_b.id,
    type=EdgeType.USES,
    weight=0.8,
    decay_rate=0.02
)
```

**Reinforcement on re-creation**: If an edge of the same type already exists between two nodes, `add_edge` reinforces it instead of creating a duplicate — weight +0.1, activation_count +1, last_activated updated. This is the Hebbian mechanism: "edges that fire together wire together."

### Finding Nodes

```python
nodes = graph.find_nodes("AllergyFind")    # substring search, active zone only
nodes = graph.all_nodes(zone="archived")  # all archived nodes
nodes = graph.all_nodes(zone=None)        # all zones
```

`find_nodes` uses substring matching (all query terms must appear in content or tags). Results are sorted by salience descending. Zone filtering is applied before returning.

### Salience Computation

Salience is **computed**, not assigned. It runs every time the graph is saved.

```
salience = α × connectivity_score
         + β × reinforcement_score
         + γ × recency_score
```

Where:
- **α = 0.3** — connectivity: `node_degree / max_degree` across all nodes
- **β = 0.4** — reinforcement: `log(activation_count + 1) / log(max_activations + 1)`
- **γ = 0.3** — recency: `exp(-delta_days × ln(2) / 14)` (14-day half-life)

The result is normalized to [0.0, 1.0] and rounded to 4 decimal places.

**Why these weights?** Reinforcement has the highest weight because nodes that are repeatedly useful should be promoted. Connectivity is second because well-linked nodes are likely important. Recency is third to prevent old but well-linked nodes from dominating permanently.

### Core Memories

Nodes with `is_core=True` are **always injected into the stable prefix**, regardless of the current query. They represent the foundational facts about this agent's user that should always be available.

Core promotion threshold: salience ≥ 0.65
Core demotion threshold: salience < 0.25

A core node's demotion threshold has a buffer — once promoted, a node needs to fall significantly before being demoted, preventing oscillation.

---

## 8. Spreading Activation Retrieval

Spreading activation is the core retrieval mechanism. It implements a computational model of how human semantic memory works: activating one concept activates related concepts, which activate their neighbors, propagating relevance through the graph.

### Finding Seeds

Before spreading, we need seed nodes — the starting points most relevant to the query.

**Three-tier seed finding (in order of reliability):**

1. **FTS5 BM25 search**: Query the `nodes_fts` virtual table using the query string. Fast, handles partial terms, returns ranked node IDs. This is the primary mechanism and works on every install.

2. **Vector KNN** (if available): If Ollama is running with `nomic-embed-text`, embed the query and find nearest neighbor nodes by cosine similarity. This catches semantic matches that don't share keywords ("velocity" → "speed"). Falls back gracefully if Ollama isn't available.

3. **Substring fallback**: Direct string matching on node content. Always works, no dependencies. Lower precision but ensures we always return something.

Results from all three tiers are deduplicated and merged, with FTS hits ranked first.

### The Spread Algorithm

```python
def spread(
    seed_ids: list[str],
    graph: Graph,
    depth: int = 3,
    depth_decay: float = 0.5,
    threshold: float = 0.05
) -> dict[str, float]
```

**Algorithm:**
1. Initialize seed nodes at activation level `1.0`
2. For each depth hop (up to 3):
   - For each currently activated node:
     - Find all its edges (incoming and outgoing)
     - For each connected neighbor: `neighbor_level += source_level × edge_weight × depth_decay`
     - Cap activation at 1.0 per node
3. Record activation on every touched node and edge (increment `activation_count`, update `last_activated`)
4. Filter out nodes below `threshold` (0.05)
5. Return `{node_id: activation_level}` dict

**Depth decay** is why the algorithm terminates naturally — each hop multiplies the activation by 0.5, so after 3 hops the contribution is 0.5³ = 0.125 of the original. Distant nodes are only included if the path is strong (high edge weights).

**Why this beats vector search alone**: Vector similarity finds nodes that are semantically similar to the query. Spreading activation finds nodes that are *related* to the most similar nodes — it discovers context you wouldn't think to search for. "AllergyFind" in the query → finds Giovanni's (via `WORKS_ON`) → finds menu endpoint (via `RELATED_TO`) → finds JWT auth (via `USES`), even though the query never mentioned any of those.

### Serializing Activated Nodes

```python
def serialize(
    activated: dict[str, float],
    graph: Graph,
    max_nodes: int = 20
) -> str
```

After activation, the subgraph is converted to a human-readable context block:
- Nodes ranked by `(activation_level × 0.6) + (salience × 0.4)`
- Up to 20 nodes included
- Date hints added for EVENT and SESSION nodes
- Edges between activated nodes included (up to 15)
- `SUPERSEDES` edges get special formatting: `[KNOWLEDGE UPDATE (date)] Previously: X → Now: Y`
- Returns `"(no relevant memories found)"` if nothing above threshold

---

## 9. Session Management and Query Routing

The `session.py` module sits above the graph and activation layers, providing higher-level operations and intelligent query routing.

### Query Routing

The `query()` function detects what *kind* of question is being asked and routes to the most appropriate retrieval strategy:

```python
def query(topic: str, graph: Graph) -> str
```

**Mode 1: Temporal queries**

*Detected by regex:* `before|after|earlier|latest|prior to|how long|how many (days|weeks|months|years)|which came first|chronolog|timeline|when did|more recent|duration`

*Strategy:* Return SESSION nodes sorted chronologically (by date prefix extracted from content), plus top 20 spread-activated non-SESSION nodes. This answers questions like "What did we work on last week?" or "What happened after the Giovanni launch?"

**Why a separate mode?** Spreading activation ranks by salience, not time. A question about the sequence of events doesn't need the most salient memories — it needs them in order. Without this mode, temporal questions were Dory's weakest category on LongMemEval (32.3%).

**Mode 2: Aggregation queries**

*Detected by regex:* `how many (not time units)|how often|list all|every time|each time|total count|number of times|occasions|instances`

*Strategy:* Expand FTS search to 200 candidates at max_nodes=100. The goal is completeness — find every instance, not just the most relevant ones. Non-seed nodes get a baseline activation of 0.3.

**Why a separate mode?** Default spreading activation finds the most connected/salient match and stops at 20 nodes. That's wrong for "list all projects" — you need an exhaustive scan. The negative lookahead in the regex (`(?!\s+(?:days?|weeks?|months?|years?))`) prevents "how many days" from being misclassified as aggregation.

**Mode 3: Default (spreading activation)**

Everything else. Depth-3 spreading activation, max 50 nodes. Best for general context retrieval.

**All modes guarantee SESSION nodes**: Regardless of mode, SESSION nodes are always included at a minimum activation of 0.1 if nothing stronger was found.

### Core Session Operations

**`observe(content, node_type, graph, tags=None)`**: Creates a node and auto-links it to up to 5 related existing nodes via FTS. Auto-links use `CO_OCCURS` edges with weight 0.5.

**`link(source_id, target_id, edge_type, graph, weight=0.8)`**: Explicit edge creation between existing nodes.

**`write_turn(content, graph, role, session_id)`**: Logs a raw conversation turn to the episodic observations table. Returns the observation ID.

---

## 10. The Observer: Extracting Memories from Conversation

The Observer is Dory's LLM-powered extraction pipeline. It listens to conversation turns and periodically calls an LLM to extract structured memories.

### Configuration

```python
Observer(
    graph=graph,
    model="qwen3:14b",           # or "claude-haiku-4-5-20251001", "gpt-4o-mini"
    backend="ollama",            # "ollama", "anthropic", or "openai"
    base_url="http://localhost:11434",  # for Ollama/compat endpoints
    api_key="local",             # for Anthropic/OpenAI
    threshold=5,                 # trigger extraction every 5 turns
    confidence_floor=0.7,        # min confidence to write to graph
    session_id=None              # auto-generated if not provided
)
```

### Supported Backends

| Backend | Description | Dependency |
|---|---|---|
| `ollama` | Local models via Ollama REST API | `pip install ollama` |
| `anthropic` | Claude via Anthropic API | `pip install anthropic` |
| `openai` | Any OpenAI-compatible endpoint (GPT, Grok, llama.cpp, vLLM, Clanker) | `pip install httpx` |

### The Extraction Prompt

When the buffer fills (every 5 turns), the Observer sends the buffered conversation to the LLM with a structured extraction prompt. The LLM is instructed to return:

```json
{
  "nodes": [
    {
      "type": "ENTITY | CONCEPT | EVENT | PREFERENCE | BELIEF | PROCEDURE",
      "content": "Specific, complete description as a standalone statement",
      "tags": ["relevant", "tags"],
      "confidence": 0.85
    }
  ],
  "edges": [
    {
      "source_content": "exact content of source node",
      "target_content": "exact content of target node",
      "type": "USES",
      "weight": 0.8
    }
  ]
}
```

**Confidence thresholds (from prompt instructions):**
- `0.9+` — explicitly stated facts ("I'm building AllergyFind")
- `0.7–0.89` — strongly implied ("since we're using FastAPI" → uses FastAPI)
- `< 0.7` — uncertain ("maybe they use Redis?") — logged but not written

Anything below 0.7 is discarded, guarding against false memory injection.

### Fuzzy Deduplication Before Writing

Before any extracted node is written, the Observer checks for near-duplicates:

```python
def _find_similar(content: str, threshold: float = 0.85) -> Node | None
```

Jaccard similarity on word sets. If a node with ≥0.85 similarity already exists, the new extraction is merged into it (activation_count incremented, last_activated updated) rather than creating a duplicate. This threshold is intentionally high — 0.85 means ~85% word overlap.

### Auto-Linking Extracted Nodes

After writing a node, it's auto-linked to up to 5 related existing nodes via FTS search. This seeds the graph's connectivity, enabling spreading activation to traverse from newly extracted facts to pre-existing context.

---

## 11. The Summarizer: Episodic Memory

The Summarizer is the episodic memory layer. Where the Observer extracts *semantic* memories (generalizable facts), the Summarizer captures *episodic* memories (what happened in this specific session, when).

### Why a separate episodic layer?

Semantic extraction filters by long-term relevance. "Looked up the FastAPI docs for 5 minutes" won't survive Observer extraction — it's not a stable fact. But it might be the answer to "What did we do last Tuesday?" A separate episodic layer captures this.

SESSION nodes have a date-stamped prefix: `"[2025-03-14] Session: ..."`. This enables the temporal query router to sort them chronologically.

### Summarization

```python
summarizer.summarize(
    turns=[{"role": "user", "content": "..."}, ...],
    session_date="2025-03-14"   # optional override
)
```

The LLM is instructed to generate a **detailed** summary that preserves:
- Specific names, numbers, measurements
- Decisions made and why
- Items discussed (lists, recommendations)
- Questions asked and answers given

"Be specific. Don't be vague." The summary is longer and more specific than a typical summary, because losing detail here means permanently losing episodic context.

### Linking Sessions to Semantic Memory

After creating the SESSION node, the Summarizer creates `CO_OCCURS` edges (weight 0.6) to related semantic nodes via FTS. This means a temporal query ("What did we do last week?") can spread-activate into semantic memory, and a semantic query ("What did we decide about auth?") can spread-activate into SESSION nodes.

---

## 12. The Prefixer: Cacheable Context Output

The Prefixer implements Dory's most financially significant feature: context injection that is compatible with prompt caching.

### The Cache Problem

Standard memory injection:
1. Run vector search for this query → get relevant memories
2. Format them → inject into system prompt
3. Next query → different results → different prefix → **cache miss**

With 4,000-turn agents, this means paying full price for every single turn.

### The Prefix/Suffix Split

```
[STABLE PREFIX — never changes until graph changes]
  Core memories (highest salience, is_core=True)
  High-salience non-core nodes (top 8)
  Key relationships involving core nodes
  Same bytes → cache hit on every turn

[DYNAMIC SUFFIX — changes per query, intentionally small]
  Spreading activation results for this specific query
  Recent episodic observations (last 6)
  Different each turn, but small (≤400 tokens)
```

**Result**: The expensive part (stable prefix, up to 800 tokens) is cached. The cheap part (dynamic suffix, up to 400 tokens) is fresh. Total effective cost: ~1/8 of full injection.

### PrefixResult

Every call to `build_context()` returns a `PrefixResult`:

```python
@dataclass
class PrefixResult:
    prefix: str    # stable — same until graph changes
    suffix: str    # per-query — fresh each turn

    @property
    def full(self) -> str
        # Combined string for simple injection

    def as_anthropic_messages(user_query: str) -> list[dict]
        # Proper Anthropic format with cache_control blocks

    def as_openai_messages(user_query: str, system: str = None) -> list[dict]
        # OpenAI/compat format — OpenAI auto-caches matching system prefixes
```

**Anthropic format** injects `cache_control: {"type": "ephemeral"}` on the prefix text block — this explicitly marks it for caching.

**OpenAI format** puts the prefix in the system message — OpenAI's caching activates automatically when system messages match.

### Prefix Caching

The Prefixer tracks a hash of `(core_node_ids, salience_scores)`. If the hash hasn't changed since last build, it returns the cached prefix string directly without rebuilding. This means even the Python-side build cost is near-zero on cache hits.

`prefixer.invalidate()` forces a rebuild — called automatically after the Reflector runs (when node structure may have changed).

### Prefix Structure

```markdown
## Memory — stable context

### Entities
- AllergyFind (salience: 0.89) [core]
- Giovanni Ristorante Nashville (salience: 0.71) [core]

### Concepts
- FastAPI + PostgreSQL stack
- JWT authentication

### Preferences
- Prefers local-first AI; data stays on device

### Past sessions
- [2025-03-14] Session: Worked on menu endpoint...
```

### Token Budgeting

Prefix is trimmed to `max_prefix_tokens=800` (≈3200 characters). Suffix is trimmed to `max_suffix_tokens=400`. The Prefixer uses a `len(text) / 4` approximation for token counting — fast, accurate enough.

---

## 13. The Decayer: Principled Forgetting

Dory is designed so memory doesn't grow unbounded. The Decayer implements principled forgetting based on a multi-factor score.

### The Decay Score

```python
score = recency_weight  × exp(-λ × days_since_last_activation)
      + frequency_weight × log(activation_count + 1) / log(max_activations + 1)
      + relevance_weight × salience
```

With default weights:
- **recency_weight = 0.4**, λ = 0.05 (≈14-day half-life)
- **frequency_weight = 0.35**
- **relevance_weight = 0.25**

### Zone Transitions

| Condition | Transition |
|---|---|
| Activated within 1 day, zone ≠ active | archived/expired → **active** (restore) |
| activation_count < 2 | Skip (protect newly created nodes) |
| score < active_floor (0.15) | active → **archived** |
| score < archive_floor (0.04) | archived → **expired** |
| score improved | expired → **archived** (bump back) |

### Core Node Protection

Core nodes (`is_core=True`) have their thresholds multiplied by `core_shield=0.3`:
- Effective active floor for core: 0.15 × 0.3 = **0.045**
- Effective archive floor for core: 0.04 × 0.3 = **0.012**

This means a core memory needs to fall to almost zero before being archived. Important foundational facts resist decay even when not recently activated.

### What Forgetting Actually Means

"Archived" means invisible to normal queries. "Expired" means invisible to all queries. But the data is never deleted from SQLite. An archived memory can:
- Be queried directly: `graph.all_nodes(zone="archived")`
- Be restored automatically if reactivated (score improves, activated within 1 day)
- Serve as a target for `SUPERSEDES` edges ("what was true before")

---

## 14. The Reflector: Deduplication and Conflict Resolution

The Reflector runs at end-of-session and handles two problems: duplicate nodes and conflicting facts.

### Deduplication: Jaccard Merge

When multiple Observer extractions produce similar nodes ("User uses FastAPI" and "The project uses FastAPI"), the Reflector detects and merges them.

**Jaccard similarity** between two nodes' content:
```
J(A, B) = |words(A) ∩ words(B)| / |words(A) ∪ words(B)|
```

**Dedup threshold: 0.82** (very high — requires ~82% word overlap). Only true near-duplicates are merged, not merely related nodes.

**Merge behavior:**
- Keep the higher-salience node
- Transfer `activation_count` to the winner
- Update `last_activated` to the max of both
- Rewire all edges from the deleted node to the winner
- Remove any self-loops created by rewiring
- Hard-delete the duplicate (unlike archiving — truly gone, not just invisible)

### Supersession: Bi-Temporal Conflict Resolution

When a fact changes ("Michael is building AllergyFind v1" → "AllergyFind is now in v2 with multi-restaurant support"), the old fact shouldn't be deleted — it may be historically relevant. The Reflector detects this and creates a provenance chain.

**Supersession detection criteria:**
1. Same node type
2. Jaccard similarity ≥ 0.45 (related subject matter) AND < 0.82 (not a duplicate)
3. Shared subject words (first 2+ significant words overlap)
4. Old node created before new node (`created_at` ordering)

**Supersession action:**
- Archive the old node (`zone = "archived"`, `superseded_at = now()`)
- Create edge: `new_node --[SUPERSEDES]--> old_node` (weight 0.9)
- The old fact remains queryable forever via `zone=None`

**In context output** (serialize in activation.py):
```
[KNOWLEDGE UPDATE (2025-03-14)] Previously: AllergyFind v1 basic menu listing → Now: AllergyFind v2 with multi-restaurant support and live pricing
```

### Observation Compression

Raw conversation turns accumulate in the `observations` table. After 2 hours, the Reflector batches them and calls an LLM to produce compressed summaries, stored in `compressed_obs`. The originals are marked `compressed=1` but retained for full audit trail.

---

## 15. Consolidation: End-of-Session Housekeeping

`consolidation.run(graph)` is the end-of-session pipeline. It ties all the maintenance operations together.

### Full Pipeline

```
1. decay()          — reduce all edge weights by decay_rate × days_since_last_activation
2. prune()          — delete edges below min_weight (0.05)
3. promote_core()   — flag nodes with salience ≥ 0.65 as core
4. demote_core()    — unflag nodes with salience < 0.25
5. recompute_salience() — recalculate salience from current state
6. Decayer.run()    — zone management (active/archived/expired)
7. Reflector.run()  — dedup, supersession, observation compression
```

### Return Stats

```python
{
    "pruned_edges": 12,
    "promoted_core": 2,
    "demoted_core": 0,
    "archived_nodes": 5,
    "expired_nodes": 1,
    "restored_nodes": 0,
    "duplicates_merged": 3,
    "supersessions": 1
}
```

This is returned from `DoryMemory.flush()` and surfaced through the MCP `consolidate` tool.

---

## 16. Framework Adapters

### LangChain Adapter

`DoryMemoryAdapter` implements the LangChain `BaseMemory` duck-type interface — no hard dependency on LangChain required. Any LangChain chain or agent that accepts a memory object can use Dory as a drop-in backend.

```python
from dory.adapters.langchain import DoryMemoryAdapter

memory = DoryMemoryAdapter(
    db_path="myapp.db",
    extract_model="claude-haiku-4-5-20251001",
    extract_backend="anthropic",
    extract_api_key="sk-ant-...",
    history_turns=6,        # how many raw turns to include in "history"
    input_key="input",      # LangChain chain input key
    output_key="output",    # LangChain chain output key
)
```

**Interface methods:**

| Method | Called when | What it does |
|---|---|---|
| `load_memory_variables(inputs)` | Start of chain run | Returns `{"context": <spread activation>, "history": <last 6 turns>}` |
| `save_context(inputs, outputs)` | End of chain run | Calls `add_turn()` for user and assistant messages |
| `clear()` | Manual or on session end | Calls `flush()` — decay, dedup, consolidate |
| `aload_memory_variables()` | Async chain start | Async version |
| `asave_context()` | Async chain end | Async version |
| `aclear()` | Async session end | Async version |

`memory_variables = ["context", "history"]` — these keys are injected into the prompt template.

### LangGraph Adapter

`DoryMemoryNode` provides `(state: dict) → dict` functions suitable for use as nodes in a LangGraph `StateGraph`.

```python
from dory.adapters.langgraph import DoryMemoryNode, MemoryState
```

**`MemoryState`** TypedDict:
```python
class MemoryState(TypedDict, total=False):
    query: str          # current user query
    context: str        # populated by load_context
    messages: list[dict]  # [{role, content}, ...]
    memory_stats: dict  # populated by consolidate
```

**Node functions:**

| Method | Reads from state | Writes to state | Use case |
|---|---|---|---|
| `load_context(state)` | `state["query"]` | `state["context"]` | First node — retrieves memory |
| `record_turn(state)` | `state["messages"][-1]` | (unchanged) | After agent responds — log last turn |
| `record_exchange(state)` | `state["messages"][-2:]` | (unchanged) | When both turns appended at once |
| `consolidate(state)` | — | `state["memory_stats"]` | Terminal node — end-of-session cleanup |

All four have async counterparts: `aload_context`, `arecord_turn`, `arecord_exchange`, `aconsolidate`.

### Async API

Every `DoryMemory` method has an async counterpart. All are implemented via `asyncio.get_running_loop().run_in_executor(ThreadPoolExecutor(), ...)` — blocking SQLite and LLM calls are offloaded to a thread pool, keeping the event loop free.

```python
# Sync
context = mem.query("topic")
result  = mem.build_context("topic")
mem.add_turn("user", "message")
node_id = mem.observe("content", node_type="PREFERENCE")
stats   = mem.flush()

# Async (same semantics, safe to await)
context = await mem.aquery("topic")
result  = await mem.abuild_context("topic")
await mem.aadd_turn("user", "message")
node_id = await mem.aobserve("content", node_type="PREFERENCE")
stats   = await mem.aflush()
```

---

## 17. Multi-Agent Shared Memory

`SharedMemoryPool` provides a single knowledge graph shared across multiple agents, with thread-safe writes and per-agent attribution.

```python
from dory.adapters.multi_agent import SharedMemoryPool

pool = SharedMemoryPool(db_path="shared.db")
```

### Thread Safety

All write operations acquire a `threading.RLock` before executing. Read operations (query, get_agent_nodes) do not lock — SQLite's WAL (Write-Ahead Logging) mode handles concurrent reads safely.

### Agent Attribution

Every write operation accepts an optional `agent_id`. When provided, nodes are automatically tagged with `"agent:<agent_id>"` for attribution filtering.

```python
node_id = pool.observe(
    "User's preferred API style is REST over GraphQL",
    node_type="PREFERENCE",
    agent_id="agent-planning"
)
```

### Cross-Agent and Per-Agent Queries

```python
# Full cross-agent context
context = pool.query("API preferences")

# Per-agent context (filtered to agent's nodes + untagged shared nodes)
context = pool.query("API preferences", agent_id="agent-planning")

# All nodes written by a specific agent
nodes = pool.get_agent_nodes("agent-planning")
```

### Use Cases

- Planner/executor agent pairs sharing state about a task
- Multiple specialized agents (researcher, writer, reviewer) sharing a common knowledge base
- Session hand-off: one agent picks up where another left off
- Audit: query which agent wrote which memories

---

## 18. JSON-LD Export and Import

`JSONLDExporter` produces W3C JSON-LD documents for portability and semantic web interoperability.

### What is JSON-LD?

JSON-LD (JSON for Linked Data) is a W3C standard format for representing structured data. It adds a `@context` block that maps field names to standard vocabulary URIs (e.g., schema.org). This makes Dory graphs readable by any semantic web tooling, importable into triple stores, and portable across systems.

### Export

```python
from dory.export.jsonld import JSONLDExporter

exporter = JSONLDExporter(graph)

# Export active nodes only (default)
data = exporter.export()

# Export including archived nodes
data = exporter.export(include_archived=True)

# Export to file
exporter.export(output_path="memory.jsonld.json", include_archived=True)
```

The output is a valid JSON-LD document with:
- `@context`: Dory-to-schema.org mapping
- `@graph`: array of node and edge objects
- Nodes as `dory:MemoryNode` with `schema:name`, `schema:dateCreated`, etc.
- Edges as `dory:MemoryEdge` with subject/predicate/object RDF structure

### Import

```python
# Round-trip: import a previously exported graph
stats = JSONLDExporter.import_into(graph, "memory.jsonld.json")
# stats = {"nodes_imported": 42, "edges_imported": 117, "skipped": 3}
```

Import merges by ID — existing IDs are skipped, new ones are added. This enables partial merges and incremental sync.

---

## 19. Visualization

Dory includes a self-contained interactive graph visualization using D3.js.

```python
from dory.visualize import open_visualization

open_visualization(graph)                               # opens browser
open_visualization(graph, zones=["active", "archived"]) # include archived
open_visualization(graph, output_path="graph.html", open_browser=False)
```

Or via CLI:
```bash
dory visualize
dory visualize --archived --expired
dory visualize --output graph.html --no-open
```

### Visual Design

**Node colors by type:**

| Type | Color |
|---|---|
| ENTITY | Light blue (#4fc3f7) |
| CONCEPT | Light purple (#b39ddb) |
| EVENT | Light green (#81c784) |
| PREFERENCE | Orange (#ffb74d) |
| BELIEF | Light red (#ef9a9a) |
| SESSION | Gray (#90a4ae) |

**Zone opacity:**
- Active: 1.0 (full opacity)
- Archived: 0.4 (dimmed)
- Expired: 0.15 (very faint)

**Core memory indicator**: Core nodes (`is_core=True`) render with a visible ring.

### Interactivity

The D3.js visualization is fully interactive:
- Force-directed layout with drag
- Zoom and pan
- Click a node to inspect full details (content, type, salience, activation count, zone, tags)
- Search bar to filter nodes by content or tag
- Zone toggles (show/hide active, archived, expired)
- Type toggles (legend items are clickable)
- Edge labels on hover

The output is a **single self-contained HTML file** with all JavaScript inline — no server required, no external CDN calls.

---

## 20. MCP Server: Memory for Claude

Dory ships a Model Context Protocol (MCP) server that exposes the knowledge graph as tools available to Claude Code and Claude Desktop.

### Installation

```bash
pip install 'dory-memory[mcp]'

# Register globally (Claude Code)
claude mcp add --scope user dory -- dory-mcp

# With custom DB path
claude mcp add --scope user dory -- dory-mcp --db /path/to/engram.db
```

### Exposed Tools

| Tool | Purpose |
|---|---|
| `dory_query` | Spreading activation retrieval for a topic |
| `dory_observe` | Add a new memory node (with type) |
| `dory_consolidate` | End-of-session: decay, dedup, zone management |
| `dory_stats` | Graph statistics: node/edge counts, core memories |
| `dory_visualize` | Generate and open interactive graph visualization |

### Recommended Workflow (Claude Code / Claude Desktop)

1. **Session start**: Call `dory_query("<topic of conversation>")` to load relevant context
2. **During session**: Call `dory_observe("<fact>", "CONCEPT")` when important information is learned
3. **Session end**: `dory_consolidate()` runs automatically via the Stop hook (or call manually)

### Environment Variable

`DORY_DB_PATH` — set to override the default database path without using `--db`.

---

## 21. CLI Reference

```bash
# Query the graph
dory query "authentication approach"

# Add a memory manually
dory observe CONCEPT "User prefers JWT for stateless API auth"
dory observe PREFERENCE "Prefers local-first AI with data on device"
dory observe PROCEDURE "Deploy: push to main, Render auto-deploys within 3 minutes"

# Create an explicit edge between two nodes
dory link <source_node_id> <target_node_id> USES
dory link <source_node_id> <target_node_id> SUPERSEDES --weight 0.9

# List all nodes
dory list
dory list --type PREFERENCE
dory list --type SESSION

# Show graph stats and core memories
dory show

# Interactive visualization
dory visualize
dory visualize --archived
dory visualize --archived --expired
dory visualize --output graph.html --no-open

# End-of-session consolidation
dory consolidate
```

---

## 22. Complete Defaults and Thresholds

| Parameter | Default | Component | Notes |
|---|---|---|---|
| Edge initial weight | 0.8 | Graph | New edges start here |
| Edge reinforcement delta | +0.1 | Graph | Per reactivation, capped at 1.0 |
| Edge min weight (prune) | 0.05 | Consolidation | Below = deleted |
| Edge decay rate | 0.02/day | Graph | ~50 days to near zero |
| Salience α (connectivity) | 0.3 | Graph | Node degree weight |
| Salience β (reinforcement) | 0.4 | Graph | Activation frequency weight |
| Salience γ (recency) | 0.3 | Graph | Recency weight |
| Recency half-life | 14 days | Graph + Decayer | For both salience and decay score |
| Activation depth | 3 hops | Activation | Max spreading distance |
| Depth decay per hop | 0.5 | Activation | 3 hops = 0.125 of initial level |
| Activation threshold | 0.05 | Activation | Below = not included in results |
| Activation max nodes (default) | 20 | Session | Nodes returned by default query |
| Activation max nodes (temporal) | 20 | Session | Non-SESSION nodes in temporal mode |
| Activation max nodes (aggregation) | 100 | Session | Expanded for completeness |
| FTS search limit (default) | 20 | Store | Candidates per BM25 search |
| FTS search limit (aggregation) | 200 | Session | Expanded search |
| Baseline activation (aggregation) | 0.3 | Session | Non-FTS-seed nodes |
| Core promotion threshold | 0.65 | Consolidation | Salience to flag as core |
| Core demotion threshold | 0.25 | Consolidation | Salience to unflag as core |
| Decay λ | 0.05 | Decayer | Exponential decay rate |
| Recency weight | 0.4 | Decayer | In decay score formula |
| Frequency weight | 0.35 | Decayer | In decay score formula |
| Relevance weight | 0.25 | Decayer | In decay score formula |
| Active floor | 0.15 | Decayer | Below = archived |
| Archive floor | 0.04 | Decayer | Below = expired |
| Core shield multiplier | 0.3 | Decayer | Core threshold × 0.3 |
| Min activations before archive | 2 | Decayer | Protect newly created nodes |
| Restore activation window | 1 day | Decayer | If activated within, restore from archived |
| Dedup threshold (Reflector) | 0.82 | Reflector | Jaccard sim for merge |
| Supersession threshold | 0.45–0.82 | Reflector | Range for bi-temporal edges |
| Compress observations older than | 2 hours | Reflector | Batch for LLM summary |
| Observer buffer threshold | 5 turns | Observer | Trigger extraction |
| Observer confidence floor | 0.7 | Observer | Min to write to graph |
| Observer fuzzy dedup threshold | 0.85 | Observer | Node similarity before write |
| Co-occurrence auto-link max | 5 | Session | Links per new observe() |
| CO_OCCURS initial weight | 0.5 | Session | Auto-linked edges |
| SESSION → semantic CO_OCCURS weight | 0.6 | Summarizer | SESSION to related nodes |
| SUPERSEDES edge weight | 0.9 | Reflector | Provenance edge |
| Prefix max tokens | 800 | Prefixer | Stable context budget |
| Suffix max tokens | 400 | Prefixer | Query context budget |
| Prefix top non-core nodes | 8 | Prefixer | High-salience non-core nodes |
| Prefix max relationships | varies | Prefixer | Edges involving core nodes |
| Suffix max recent observations | 6 | Prefixer | Raw turns in suffix |
| Suffix spread depth | 3 | Prefixer | Same as activation default |

---

## 23. Benchmark Results: LongMemEval

LongMemEval (ICLR 2025) is the benchmark Dory targets. It tests 500 questions across five categories using multi-session conversation transcripts.

**Published scores of other systems:**
- Mem0: 68.4%
- Zep: 71.2%
- Mastra: 94.87% (GPT-5-mini, TypeScript only)

### Dory Results

**Current (Haiku for extraction, Haiku for answering):**

| Category | Score | Notes |
|---|---|---|
| Overall | **54.4%** | Up from 18.4% before episodic layer |
| Knowledge update | 65.4% | Bi-temporal supersession working |
| Multi-session | 60.2% | SESSION nodes working |
| Single-session user | 80.0% | Strong |
| Single-session assistant | 50.0% | Room for improvement |
| Single-session preference | 46.7% | Room for improvement |
| Temporal reasoning | 32.3% | Lowest; temporal routing added to address this |

**Spot checks with Sonnet for extraction (50–100 questions):**
- Temporal reasoning: **64.0%** (50-question sample)
- Multi-session: **76.0%** (25-question sample)

**Improvement trajectory:**
- Pre-episodic layer: 18.4%
- Post-episodic layer: 54.4%
- Post temporal routing (projected): 65–70%
- With Sonnet throughout (full 500-question run pending): estimated 75–80%

The gap vs. Mastra's 94.87% is largely explained by: (1) Mastra uses GPT-5-mini (far stronger model) for extraction and answering; (2) Mastra is TypeScript-native with full OpenAI integration; (3) Dory uses Haiku for budget reasons in the published run.

---

## 24. Design Decisions and Trade-offs

### Why a knowledge graph instead of a vector database?

Vector databases find nodes that are semantically similar to a query. Knowledge graphs find nodes that are *connected* to similar nodes. The key advantage: surfacing context you wouldn't think to search for.

A user asks about "authentication." Vector search finds all nodes about authentication. Spreading activation starts at authentication nodes and follows edges to FastAPI, then to AllergyFind, then to Giovanni's — because those things co-occurred in real conversations. The context injected is richer and more useful.

Trade-off: knowledge graphs are more expensive to maintain (extraction, linking, decay) than vector embeddings. Dory mitigates this by making vector search an optional enhancement on top of FTS5, not the primary mechanism.

### Why SQLite instead of a dedicated graph database?

See Section 6. Summary: zero-server, zero-configuration, fully portable, fast enough at the scale of agent memory (hundreds to low thousands of nodes), and single-file backup.

### Why local LLMs by default?

The default backend is Ollama (`qwen3:14b`). Reasons:
- Privacy: conversation contents don't leave the machine
- Cost: free at inference time once the model is pulled
- Latency: local inference with good hardware is faster than round-trip API calls
- Independence: no API keys, no rate limits, works offline

Cloud backends (Anthropic, OpenAI) are supported and often produce better extraction quality, but they're opt-in.

### Why spreading activation instead of just BM25 or vector search?

BM25 and vector search are *point queries* — they find the nodes most similar to the query. Spreading activation is a *neighborhood query* — it finds the subgraph most relevant to the query, including nodes that wouldn't match a direct search.

This more closely mirrors how human memory works (Collins & Loftus 1975 — semantic priming). The computational cost is low (BFS over a small in-memory graph), and the quality improvement is significant for contextual questions.

### Why never delete nodes?

Two reasons:

1. **Bi-temporal queries**: "What was the plan before we pivoted?" requires the old plan to still exist. If we delete on supersession, we lose historical context.

2. **Reactivation**: A topic that hasn't been discussed in months may resurface. Archived nodes can be restored automatically when they're activated again — the memory "comes back" rather than starting from scratch.

The cost is a growing SQLite file. In practice, knowledge graph nodes are tiny (a few hundred bytes each), and an agent that's been running for years would accumulate at most tens of thousands of nodes — still sub-megabyte.

### Why the prefix/suffix split?

Pure economic optimization. Prompt caching is the highest-leverage cost reduction available in LLM API pricing (Anthropic offers up to 90% discount on cached tokens). Rebuilding context from scratch every turn forfeits this entirely.

The design constraint: the stable part (prefix) must be byte-identical across turns. So it can only contain information that doesn't change per-query — core memories and high-salience context, not query-specific results.

The insight: most of the *important* memories (high-salience core facts) *are* stable. They're the same whether you're asking about authentication or deployment. Only the query-specific context needs to be fresh.

### Why 5-turn extraction threshold?

Extracting after every turn would produce noisy, redundant nodes and be expensive. Extracting after the full conversation would miss temporal context (what was discussed early vs. late in the session).

5 turns is a heuristic that balances these. It's configurable.

### Why Jaccard similarity instead of cosine similarity for deduplication?

Cosine similarity requires embeddings, which require a running model. Jaccard similarity on word sets requires nothing — it's a pure Python set operation. For short memory node content (typically 1–2 sentences), Jaccard is surprisingly accurate and fast.

---

## 25. Research Basis

Dory's design draws from published research across memory systems, graph theory, and cognitive psychology:

**[MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560)** (Packer et al., 2023)
Two-tier memory architecture: main context (working memory) + external storage (long-term memory). Dory's prefix/suffix split is an evolution of this pattern.

**[Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956)** (2025)
Bi-temporal provenance for knowledge graphs. Dory's `SUPERSEDES` edge pattern and `superseded_at` timestamp are directly inspired by this approach.

**[MAGMA: Multi-Graph based Agentic Memory Architecture](https://arxiv.org/abs/2601.03236)** (2026)
Multi-graph retrieval and memory specialization. Informed Dory's decision to separate episodic (SESSION) from semantic (CONCEPT/ENTITY/etc.) memory layers.

**[Mastra Observational Memory](https://mastra.ai/research/observational-memory)**
Cacheable prefix architecture. Dory's Prefixer is a Python port and extension of this approach, adding a dynamic suffix layer.

**[LongMemEval](https://arxiv.org/abs/2410.10813)** (ICLR 2025)
The benchmark Dory is evaluated against. 500 questions across five memory types: knowledge-update, multi-session, single-session user/assistant/preference, temporal-reasoning.

**Collins & Loftus (1975)** — Spreading Activation Theory of Semantic Processing
The foundational cognitive science paper establishing spreading activation as a model of human semantic memory. Dory's activation engine is a direct computational implementation.

**Hebb (1949)** — The Organization of Behavior
"Neurons that fire together wire together." Dory's edge reinforcement (+0.1 per traversal) implements the Hebbian learning principle in the graph.

---

*Dory is Apache 2.0 licensed. Source: [github.com/MichaelWMartinII/Dory](https://github.com/MichaelWMartinII/Dory)*

*Named after Dory from Finding Nemo, because your AI agent right now is Dory. This fixes it.*
