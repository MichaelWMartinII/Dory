# Dory

**Agent memory that actually sticks.**

Named after the fish with no short-term memory — because that's your AI agent right now.

Dory is a Python-native, local-first memory library for AI agents. Drop it into any LLM pipeline and your agent stops forgetting between sessions.

```python
pip install dory-ai
```

---

## The problem

Every time you start a new session, your agent starts from zero. Even systems that claim to "remember" you are doing keyword search through a flat list of notes. That's not memory — that's ctrl+F.

The deeper problem: naive memory injection makes things *worse*. Dumping everything into context creates noise that degrades model performance. Research ([Chroma, 2025](https://research.trychroma.com/context-rot)) shows all major frontier models degrade starting at 500–750 tokens of context.

## What Dory does differently

**Four memory types, all in one place**

| Type | What it stores | Status |
|---|---|---|
| Episodic | Past events, sessions, experiences | ✓ |
| Semantic | Facts, preferences, entities, relationships | ✓ |
| Procedural | Skills and patterns (coming soon) | roadmap |
| Working | In-context window (managed by your LLM) | — |

**Spreading activation retrieval** — not vector similarity search. Relevant memories pull in connected memories through the graph. "AllergyFind" activates "Giovanni's" activates "FastAPI" activates "menu endpoint" because those things co-occurred. That's how human memory works.

**Cacheable prefix output** — instead of regenerating your full memory context every turn (which blows prompt caching), Dory splits output into a *stable prefix* (same until memory actually changes) and a *dynamic suffix* (query-specific). Result: cache hits every turn. 4–10x cheaper to run agents with memory than without.

**Principled forgetting** — three decay zones: active, archived, expired. Scores based on recency + frequency + relevance. Nothing is ever deleted — archived memories are queryable for historical context. No other production memory library ships this.

**Bi-temporal conflict resolution** — when a fact changes, the old version is archived with a `SUPERSEDES` edge and a timestamp. You can query "what was true in January" and get the right answer.

**Zero-server stack** — everything runs in a single SQLite file. `sqlite-vec` for vectors, FTS5 for keyword search, adjacency tables for the graph. No Postgres, no Neo4j, no Redis. Works offline.

---

## Quick start

```python
from dory import Graph, Observer, Prefixer

graph = Graph()  # reads/writes to ./dory.db

# --- During a session: log turns ---
obs = Observer(graph, backend="ollama", model="qwen3:14b")
obs.add_turn("user", "I'm working on AllergyFind today, need to add a menu endpoint")
obs.add_turn("assistant", "What authentication approach are you using?")

# --- Before each LLM call: inject context ---
p = Prefixer(graph)
result = p.build("menu endpoint authentication")

# Plain injection
system_prompt = result.full

# Anthropic API with cache_control (stable prefix cached automatically)
messages = result.as_anthropic_messages(user_query)

# OpenAI-compatible (Ollama, llama.cpp, Clanker, etc.)
messages = result.as_openai_messages(user_query, system="You are a helpful assistant.")

# --- End of session: extract memories + consolidate ---
obs.flush()
```

---

## How it works

### Memory graph

Every piece of information is a node. Nodes have types: `ENTITY`, `CONCEPT`, `EVENT`, `PREFERENCE`, `BELIEF`. Edges between them are typed and weighted: `USES`, `WORKS_ON`, `PREFERS`, `SUPERSEDES`, `CO_OCCURS`, etc.

Salience is computed, not assigned:
```
salience = α × connectivity + β × activation_frequency + γ × recency
```

High-salience nodes become **core memories** — they anchor the stable context prefix.

### Observer

Every N conversation turns (configurable), the Observer calls a local LLM to extract structured memories from the raw conversation. Extractions have confidence scores — anything below the threshold is logged but not written to the graph, guarding against false memory.

Backends: Ollama (default) or any OpenAI-compatible endpoint (llama.cpp, Clanker, vLLM, etc.).

### Prefixer

Builds context in two parts:

```
[stable prefix]         ← core memories + key relationships
                          same bytes across turns → prompt cache hits

[dynamic suffix]        ← spreading activation for this specific query
                          + recent episodic observations
                          changes per query but small
```

### Decayer

Runs periodically to score every node:
```
score = recency_weight  × exp(-λ × days_since_activation)
      + frequency_weight × log(1 + activation_count)
      + relevance_weight × salience
```

Nodes below the active floor → archived. Below the archive floor → expired. Core memories are shielded with a configurable multiplier.

### Reflector

Finds near-duplicate nodes (Jaccard similarity), merges them keeping the higher-salience one. Detects supersession (same subject, newer fact), archives the old node, and adds a `SUPERSEDES` provenance edge. Old observations are compressed into summaries.

---

## Architecture

```
dory/
├── core/
│   graph.py          ← nodes, edges, spreading activation, salience
│   schema.py         ← NodeType, EdgeType, zone constants
│   activation.py     ← spreading activation engine
│   consolidation.py  ← edge decay, strengthen, prune, promote/demote core
│
├── pipeline/
│   observer.py       ← LLM extraction of memories from conversation turns
│   prefixer.py       ← stable prefix + dynamic suffix builder
│   decayer.py        ← node decay scoring + zone management
│   reflector.py      ← dedup, supersession, observation compression
│
└── store.py          ← SQLite backend (nodes, edges, FTS5, observations)
```

---

## Local LLM setup

Dory defaults to Ollama for LLM-based extraction (Observer) and embedding (vector search).

```bash
# Pull the default models
ollama pull qwen3:14b          # extraction
ollama pull nomic-embed-text   # embeddings (768-dim, offline after pull)
```

OpenAI-compatible endpoint (Clanker, llama.cpp server, vLLM):
```python
obs = Observer(
    graph,
    backend="openai",
    base_url="http://localhost:8000",
    model="qwen3",
)
```

Vector search activates automatically once `nomic-embed-text` is available. Falls back to FTS5 BM25 + substring search if no embedding model is running.

---

## Decay zones

| Zone | Behavior | How to query |
|---|---|---|
| `active` | Retrieved in all normal queries | `graph.all_nodes()` (default) |
| `archived` | Invisible to normal queries | `graph.all_nodes(zone="archived")` |
| `expired` | Completely invisible | `graph.all_nodes(zone=None)` |

Nothing is ever deleted. Archived nodes retain full provenance and can be restored if reactivated.

---

## What's different from other memory libraries

| | mem0 | Zep | Letta | Mastra | **Dory** |
|---|---|---|---|---|---|
| Principled forgetting | ✗ | ✗ | ✗ | ✗ | ✓ |
| Spreading activation retrieval | ✗ | ✗ | ✗ | ✗ | ✓ |
| Cacheable prefix output | ✗ | ✗ | ✗ | ✓ (TS only) | ✓ |
| Bi-temporal conflict resolution | ✗ | ✓ | ✗ | ✗ | ✓ |
| Zero-server local stack | partial | ✗ | partial | ✗ | ✓ |
| Drop-in Python library | ✓ | partial | ✗ | ✗ | ✓ |
| Apache 2.0 | ✓ | ✓ | ✓ | ✓ | ✓ |

---

## Roadmap

- [ ] MCP server — expose Dory memory as MCP tools for Claude Code / Claude Desktop
- [ ] LangChain adapter
- [ ] LangGraph adapter
- [ ] Procedural memory (skill accumulation)
- [ ] Multi-agent shared memory with conflict-free writes
- [ ] Portable import/export format (JSON-LD)

---

## Research basis

Dory draws from:
- [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560) — two-tier memory architecture
- [Zep: A Temporal Knowledge Graph Architecture](https://arxiv.org/abs/2501.13956) — bi-temporal provenance
- [MAGMA: Multi-Graph based Agentic Memory](https://arxiv.org/abs/2601.03236) — multi-graph retrieval
- [Mastra Observational Memory](https://mastra.ai/research/observational-memory) — cacheable prefix architecture (Python port)
- [LongMemEval](https://arxiv.org/abs/2410.10813) — the benchmark we care about
- Collins & Loftus (1975) — spreading activation in semantic memory
- Hebb (1949) — neurons that fire together wire together

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

*Named after Dory from Finding Nemo, because your AI agent right now is Dory. This fixes it.*
