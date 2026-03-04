# Agent Memory System — Architecture & Vision

*Research-grounded design for a Python-native, local-first agent memory library.*
*Drafted March 3, 2026 — based on deep survey of the current landscape.*

---

## Why This Exists

The agent memory space is fragmented and underbuilt. Every major framework has solved session amnesia at a basic level, but the hard problems remain completely unsolved in production:

- Agents accumulate stale, contradictory memories indefinitely — no principled forgetting
- Multi-agent write conflicts resolved by last-writer-wins universally
- No memory format standard — every system is a silo
- No Python-native equivalent of Mastra's Observational Memory (the best architecture found)
- Local/offline stack is fragmented — no integrated solution
- Procedural memory (skill accumulation) is embryonic
- False memory from bad LLM extraction — no defense

The market validation: mem0 has 30k+ GitHub stars and $0 in solved temporal reasoning. Zep/Graphiti solves temporal memory but requires Neo4j and enterprise pricing. Mastra has the best benchmark architecture but is TypeScript-only. Nobody has shipped all four memory types with principled forgetting in a drop-in Python library.

Engram's existing graph + spreading activation model is a natural foundation.

---

## The Four Memory Types

Drawn from cognitive science (Tulving's taxonomy). Every real memory system needs all four.

| Type | What it stores | Current state in field |
|---|---|---|
| **Working** | Active context window | Every agent has this — not a storage problem |
| **Episodic** | Past events, sessions, experiences | Most underbuilt. "Episodic Memory is the Missing Piece" (arXiv 2502.06975) |
| **Semantic** | Facts, preferences, world knowledge | Most systems do this reasonably via RAG |
| **Procedural** | Skills, strategies, how-to patterns | Embryonic — MemOS attempts it, nothing ships it well |

LLMs have strong semantic memory baked into weights, zero episodic memory at inference time, and fixed procedural memory that can't be written to at runtime. Every memory system is compensating for these gaps.

---

## Full System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     AGENT / LLM CALL                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  MEMORY INTERFACE LAYER                     │
│          (drop-in, framework-agnostic Python API)           │
│                                                             │
│   mem.write(turn)   mem.read(query)   mem.context()         │
└────────────┬──────────────────┬───────────────┬────────────┘
             │                  │               │
             ▼                  ▼               ▼
        [WRITER]           [READER]       [CONTEXT BUILDER]
             │                  │               │
             ▼                  ▼               ▼
┌────────────────────────────────────────────────────────────┐
│                     PROCESSING LAYER                       │
│                                                            │
│  ┌─────────────┐    ┌──────────────┐   ┌───────────────┐  │
│  │  OBSERVER   │    │  RETRIEVER   │   │    PREFIXER   │  │
│  │             │    │              │   │               │  │
│  │ compresses  │    │ hybrid:      │   │ builds stable │  │
│  │ turns into  │    │ vector +     │   │ cacheable     │  │
│  │ timestamped │    │ graph +      │   │ context       │  │
│  │ observations│    │ BM25         │   │ prefix        │  │
│  └──────┬──────┘    └──────┬───────┘   └───────┬───────┘  │
│         │                  │                   │           │
│         ▼                  │                   │           │
│  ┌─────────────┐           │                   │           │
│  │  REFLECTOR  │           │                   │           │
│  │             │           │                   │           │
│  │ merges obs. │           │                   │           │
│  │ resolves    │           │                   │           │
│  │ conflicts   │           │                   │           │
│  └──────┬──────┘           │                   │           │
│         │                  │                   │           │
│         ▼                  │                   │           │
│  ┌─────────────┐           │                   │           │
│  │   DECAYER   │           │                   │           │
│  │             │           │                   │           │
│  │ recency     │           │                   │           │
│  │ frequency   │           │                   │           │
│  │ relevance   │           │                   │           │
│  └──────┬──────┘           │                   │           │
└─────────┼──────────────────┼───────────────────┼───────────┘
          │                  │                   │
          ▼                  ▼                   │
┌─────────────────────────────────────┐          │
│            STORAGE LAYER            │◄─────────┘
│                                     │
│  ┌──────────────┐  ┌─────────────┐  │
│  │  EPISODIC    │  │  SEMANTIC   │  │
│  │  sqlite      │  │  graph      │  │
│  │  (obs log)   │  │  sqlite     │  │
│  │              │  │  (entities, │  │
│  │  what        │  │  relations, │  │
│  │  happened    │  │  facts)     │  │
│  └──────────────┘  └─────────────┘  │
│                                     │
│  ┌──────────────┐  ┌─────────────┐  │
│  │  VECTOR      │  │ PROCEDURAL  │  │
│  │  sqlite-vec  │  │  sqlite     │  │
│  │  (embeddings │  │  (skills,   │  │
│  │   for        │  │  patterns,  │  │
│  │   retrieval) │  │  strategies)│  │
│  └──────────────┘  └─────────────┘  │
└─────────────────────────────────────┘
```

---

## Write Path

```
Agent turn (user + assistant messages)
        │
        ▼
Observer runs every N turns (configurable threshold)
        │
        ├─→ extract entities  → Semantic graph nodes
        ├─→ extract events    → Episodic log (timestamped)
        ├─→ extract patterns  → Procedural store
        └─→ embed all         → Vector index (sqlite-vec)
        │
        ▼
Reflector runs periodically (async / background)
        │
        ├─→ merge duplicate/related observations
        ├─→ resolve conflicts (newer fact supersedes older, with provenance)
        ├─→ update semantic graph edges
        └─→ flag low-confidence extractions (false memory risk)
        │
        ▼
Decayer scores everything on write
        │
        ├─→ recency score    (exponential decay by time)
        ├─→ frequency score  (access count boost)
        └─→ relevance score  (updated when retrieved)
```

---

## Read Path

```
Query / agent turn
        │
        ▼
Retriever (hybrid, runs in parallel)
        │
        ├─→ vector search     (semantic similarity via sqlite-vec)
        ├─→ graph traversal   (entity relationships, 2-hop max)
        └─→ BM25 keyword      (exact term match)
        │
        ▼
Score fusion (weighted)
        default: vector 0.5 / graph 0.3 / BM25 0.2
        configurable per use case
        │
        ▼
Decay filter
        exclude items below score threshold
        │
        ▼
Prefixer assembles output in two parts:
        │
        ├─→ STABLE PREFIX (cacheable):
        │       long-term facts + entity graph summary
        │       same across turns until Reflector runs
        │       → provider prompt cache hits here
        │
        └─→ DYNAMIC SUFFIX (per-query):
                recent observations relevant to this turn
                small, changes per query
        │
        ▼
Injected into agent context
```

---

## The Caching Insight (Why This Beats RAG)

The core architectural innovation — first implemented by Mastra, no Python equivalent exists.

```
RAG approach (standard today):
  Turn 1: [system prompt] + [retrieved chunks A, B, C]   ← cache MISS
  Turn 2: [system prompt] + [retrieved chunks A, D, E]   ← cache MISS
  Turn 3: [system prompt] + [retrieved chunks B, C, F]   ← cache MISS
  → Pay full input token price every single turn
  → Context rot: retrieved chunks act as distractors

Observational prefix approach:
  Turn 1: [system prompt + stable prefix v1] + [dynamic]  ← cache MISS
  Turn 2: [system prompt + stable prefix v1] + [dynamic]  ← cache HIT ✓
  Turn 3: [system prompt + stable prefix v1] + [dynamic]  ← cache HIT ✓
  ...
  Reflector runs → stable prefix becomes v2
  Turn N:   [system prompt + stable prefix v2] + [dynamic] ← cache MISS
  Turn N+1: [system prompt + stable prefix v2] + [dynamic] ← cache HIT ✓

Result: 4–10x token cost reduction
  - compression effect: fewer tokens in context
  - caching effect: cheaper cost per token on cache hits
  Both effects stack. Tool-heavy agents see 5–40x compression.
```

Mastra benchmark results on LongMemEval (the standard benchmark):
- GPT-5-mini + Mastra: 94.87% (highest recorded)
- GPT-4o + Mastra: 84.23%
- GPT-4o + RAG baseline: 80.05%

---

## Decay Model

The completely unsolved problem in production. Every current system either never deletes or deletes arbitrarily.

```python
memory_score = (
    recency_weight   * exp(-λ * days_since_access)
  + frequency_weight * log(1 + access_count)
  + relevance_weight * last_retrieval_score
)
```

Three decay zones — never permanently lose a memory:

```
memory_score ≥ active_threshold    → ACTIVE    (retrieved normally)
memory_score ≥ archive_threshold   → ARCHIVED  (retrieved only on explicit request)
memory_score < archive_threshold   → EXPIRED   (invisible but logged; can be restored)
```

Tunable parameters per use case:
- `λ` — decay rate (how fast recency score drops)
- `recency_weight`, `frequency_weight`, `relevance_weight` — salience model
- `active_threshold`, `archive_threshold` — zone boundaries

The biological principle: human memory decays by recency, frequency of use, and emotional salience. Strategic forgetting is not data loss — it's noise reduction.

---

## Conflict Resolution

Zep's core insight, implemented without requiring Neo4j.

```
New fact arrives: "user lives in Nashville"
Existing fact:    "user lives in Memphis" (written 90 days ago)

Resolution:
  1. Do NOT overwrite — append new fact with timestamp
  2. Tag old fact as SUPERSEDED (not deleted)
  3. Update semantic graph:
       [user] -[lives_in]-> [Nashville]
       with provenance: { replaced: "Memphis", date: ..., confidence: ... }
  4. Bi-temporal record preserved:
       "as of [today], Nashville; prior to [date], Memphis"

Query: "where does user live?"          → Nashville ✓
Query: "where did user live last year?" → Memphis   ✓
```

This is implemented in sqlite with adjacency tables and a provenance column. No graph database server required.

---

## Context Rot Warning

Research finding that changes the retrieval design requirements.

Chroma Research tested 18 frontier models (Claude Opus 4, GPT-4.1, Gemini 2.5, Qwen3-235B, others) and found **every single model** degrades as context grows:
- Degradation begins at 500–750 tokens
- Substantial degradation beyond 2,500 tokens
- "Lost in the middle" effect: strong attention at start and end, poor attention to middle tokens

**Implication**: a memory system with poor retrieval precision can actively *hurt* agent performance compared to no memory at all. This makes the Prefixer's job critical — the stable prefix must be genuinely relevant, not just comprehensive. Less is more.

---

## Storage Stack (All Local, No Server)

| Layer | Library | Notes |
|---|---|---|
| Vector search | `sqlite-vec` | SQLite extension, K-NN, SIMD-accelerated, zero deployment overhead |
| Graph / relational | `sqlite` (adjacency tables) | Entities, edges, provenance, episodic log — all in one file |
| Embeddings | `Ollama` (nomic-embed-text) | Local, offline, 768-dim. MLX on Apple Silicon for speed |
| Full-text search | SQLite FTS5 | BM25 built in, no extra dependency |

Everything is a single SQLite file. Portable, inspectable, zero-infra.

Optional cloud path: swap Ollama embeddings for OpenAI/Voyage; keep everything else identical.

---

## Integration Layer

```
┌──────────────────────────────────────────────────┐
│                INTEGRATION LAYER                  │
│                                                   │
│  ┌──────────┐ ┌──────────┐ ┌────────────────┐   │
│  │LangChain │ │LangGraph │ │  Raw (any LLM) │   │
│  │ adapter  │ │ adapter  │ │  API call      │   │
│  └──────────┘ └──────────┘ └────────────────┘   │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │          MCP Server (optional)              │ │
│  │   exposes memory as MCP tools               │ │
│  │   works with Claude Code, Claude Desktop    │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │        Portable Export / Import             │ │
│  │   JSON-LD format                            │ │
│  │   import from / export to Zep, mem0, Letta  │ │
│  └─────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

The MCP server is strategically important: it makes this system usable with Claude Code and Claude Desktop out of the box, without any framework adoption.

---

## What Engram Already Provides

```
Engram today:
  ✓ Graph storage (JSON → migrate to sqlite)
  ✓ Node types: ENTITY, CONCEPT, EVENT, PREFERENCE, BELIEF, SESSION
  ✓ Spreading activation retrieval
  ✓ Salience computation (connectivity + recency + activation count)
  ✓ Consolidation (decay, strengthen, prune, promote)
  ✓ Co-occurrence edge formation
  ✓ Session-scoped observe + query CLI

What gets added:
  + sqlite-vec vector index alongside graph
  + Observer pipeline (LLM-based extraction into all four memory types)
  + Reflector (background merge + conflict resolution)
  + Cacheable prefix builder (the Mastra insight, in Python)
  + Decay zones (active / archived / expired)
  + Bi-temporal conflict resolution (provenance preservation)
  + LangChain / LangGraph adapters
  + MCP server
  + Portable import/export format
```

The graph model and spreading activation are keepers. The storage layer migrates from JSON to sqlite. Everything else is additive.

---

## Module Plan

```
engram/
├── AGENT_MEMORY_ARCHITECTURE.md   ← this file
├── planning.md                    ← original Engram design doc
├── engram_cli.py                  ← existing CLI (preserved)
│
└── engram/
    ├── __init__.py
    │
    ├── core/
    │   ├── graph.py           ← nodes, edges, CRUD (sqlite)
    │   ├── schema.py          ← node/edge types, validation
    │   ├── salience.py        ← salience computation
    │   └── activation.py      ← spreading activation engine
    │
    ├── memory/
    │   ├── episodic.py        ← observation log (timestamped events)
    │   ├── semantic.py        ← entity/fact graph
    │   ├── procedural.py      ← skill/pattern store
    │   └── vector.py          ← sqlite-vec embedding index
    │
    ├── pipeline/
    │   ├── observer.py        ← compress turns → observations
    │   ├── reflector.py       ← merge, conflict resolution (async)
    │   ├── decayer.py         ← decay scoring, zone management
    │   └── prefixer.py        ← build stable + dynamic context prefix
    │
    ├── retrieval/
    │   ├── hybrid.py          ← vector + graph + BM25 fusion
    │   └── temporal.py        ← bi-temporal query support
    │
    ├── interface/
    │   ├── memory.py          ← public API: write(), read(), context()
    │   ├── langchain.py       ← LangChain adapter
    │   ├── langgraph.py       ← LangGraph adapter
    │   └── mcp_server.py      ← MCP tool server
    │
    ├── storage/
    │   ├── sqlite_store.py    ← unified sqlite backend
    │   └── export.py          ← portable JSON-LD import/export
    │
    └── tests/
        ├── test_observer.py
        ├── test_reflector.py
        ├── test_decay.py
        ├── test_retrieval.py
        └── test_prefixer.py
```

---

## Build Phases

**Phase 1 — Storage foundation**
- Migrate graph from JSON to sqlite
- Add sqlite-vec for embeddings
- Add FTS5 for keyword search
- Port existing node/edge model

**Phase 2 — Observer pipeline**
- LLM-based extraction: entities → semantic graph, events → episodic log
- Configurable extraction prompt (unlike mem0's fixed prompt)
- Confidence scoring to flag potential false memories

**Phase 3 — Hybrid retrieval + Prefixer**
- Vector + graph + BM25 fusion
- Score weighting configurable
- Stable prefix builder with cache-friendly output
- This is the core differentiator

**Phase 4 — Decay + Reflector**
- Decay scoring on all memory items
- Active / archived / expired zones
- Conflict resolution with bi-temporal provenance
- Reflector as async background process

**Phase 5 — Integration layer**
- LangChain / LangGraph adapters
- MCP server
- Import/export format

**Phase 6 — Procedural memory**
- Skill/pattern extraction from successful interactions
- Strategy templates that accumulate over time
- The frontier — nobody has shipped this well

---

## Open Decisions

1. **Name** — keep Engram, or new name for the expanded library? Engram is a good name and already exists.

2. **Scope of Phase 1** — build the full library, or ship just the Observer + cacheable prefix first? The prefix builder alone is a publishable contribution with no Python equivalent.

3. **Embedding model** — local-only default (nomic-embed-text via Ollama) or support cloud embeddings (OpenAI, Voyage) from day one?

4. **False memory defense** — confidence scoring at extraction time is table stakes. How aggressive? Flag-only vs. require confirmation for low-confidence writes?

5. **Multi-agent support** — single-agent first, add shared memory blocks in a later phase? Multi-agent consistency (CRDTs, optimistic concurrency) is a full project on its own.

6. **Spreading activation vs. pure vector** — Engram's spreading activation is a genuine differentiator from every other system. Keep it as the primary retrieval mechanism, with vector/BM25 as supporting signals?

---

## Key Papers for Reference

| Paper | arXiv | Key contribution |
|---|---|---|
| MemGPT | 2310.08560 | OS-inspired two-tier memory, foundational |
| Zep/Graphiti | 2501.13956 | Bi-temporal knowledge graph, best temporal reasoning |
| MAGMA | 2601.03236 | Four-graph architecture, 95% token reduction |
| MemOS | 2505.22101 | Memory as OS resource (MemCube abstraction) |
| LongMemEval | 2410.10813 | The standard benchmark |
| Episodic Memory | 2502.06975 | Episodic memory as the missing piece |
| A-MEM | 2502.12110 | Zettelkasten-inspired agentic memory |
| Memory Survey | 2512.13564 | Best survey paper, three-dimensional framework |

---

## Competitive Landscape Summary

| System | Strength | Critical Gap |
|---|---|---|
| mem0 | Easiest integration, 30k stars | No temporal reasoning, 20s write latency self-hosted |
| Zep/Graphiti | Best temporal reasoning | Requires Neo4j, enterprise pricing |
| Letta | Most coherent architecture | Full runtime commitment, not a library |
| Mastra | Best benchmarks, caching insight | TypeScript only |
| ReMe | Local-first, Apache 2.0 | New, under-documented |
| **This system** | All of the above in Python, local-first | TBD |

---

*The name engram — the hypothetical physical trace a memory leaves in neural tissue, first proposed by Richard Semon (1904) — still applies. This is the engineered equivalent, with all four memory types, principled forgetting, and no cloud required.*
