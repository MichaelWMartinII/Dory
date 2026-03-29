# Dory

Persistent memory for AI agents. Graph-based, spreading activation retrieval, principled forgetting. Single SQLite file. No server required.

```bash
pip install dory-memory
```

```python
from dory import DoryMemory

mem = DoryMemory()
mem.observe("User prefers local-first AI")
mem.observe("User switched from llama.cpp to MLX — 25% faster")

print(mem.query("what does the user prefer for inference?"))
# → MLX (updated preference, supersedes llama.cpp)
```

**LongMemEval (500q, oracle split):** 79.6% on the current v0.5 Claude Code MCP run; 80.6% on the v0.4 MCP run.

---

## The problem

Every session, your agent starts from zero. Systems that claim to "remember" typically do keyword search through a flat list of notes. That's not memory — it's ctrl+F.

The deeper problem: naive context injection makes things *worse*. Research ([Chroma, 2025](https://research.trychroma.com/context-rot)) shows all major frontier models degrade starting at 500–750 tokens of context. Dumping everything into a prompt creates noise that degrades performance on the things that actually matter.

## What Dory does

**Four memory types**

| Type | What it stores | Status |
|---|---|---|
| Episodic | Past events, sessions, experiences | ✓ |
| Semantic | Facts, preferences, entities, relationships | ✓ |
| Procedural | Skills, workflows, repeatable processes | ✓ |
| Working | In-context window (managed by your LLM) | — |

**Spreading activation retrieval** — not vector similarity search. Relevant memories pull in connected memories through the graph. "AllergyFind" activates "Giovanni's" activates "FastAPI" activates "menu endpoint" because those things co-occurred. That's how human associative memory works.

**Cacheable prefix output** — Dory splits output into a *stable prefix* (unchanged until memory changes, enabling prompt cache hits) and a *dynamic suffix* (query-specific). Result: cache hits on every turn. Substantially cheaper to run agents with memory than without.

**Principled forgetting** — three decay zones: active, archived, expired. Scores based on recency + frequency + relevance. Archived memories are queryable for historical context ("what was true in January?"). Nothing is ever deleted — only decayed.

**Bi-temporal conflict resolution** — when a fact changes, the old version is archived with a `SUPERSEDES` edge and a timestamp. Full provenance for every update.

**Zero-server stack** — single SQLite file. FTS5 for keyword search, adjacency tables for the graph. No Postgres, no Neo4j, no Redis. Works offline.

---

## Quick start

```python
from dory import DoryMemory

mem = DoryMemory()

# Add memories manually
mem.observe("Alice is migrating payments from Stripe to a custom processor", node_type="EVENT")
mem.observe("Alice prefers async Python over synchronous frameworks", node_type="PREFERENCE")
mem.observe("The migration deadline is end of Q2", node_type="EVENT")

# Query — returns context to inject into your LLM prompt
context = mem.query("payment migration deadline")
print(context)

# End of session: consolidate, decay, promote core memories
mem.flush()

# See your graph in the browser
mem.visualize()
# Or explicitly opt into the remote D3 interactive view
mem.visualize(allow_remote_js=True)
```

Or from the command line:

```bash
dory visualize                    # local-only fallback view, no remote JS
dory visualize --remote-assets    # full interactive D3 view
dory show               # print stats + core memories
dory query "topic"      # spreading activation from the terminal
```

**With auto-extraction** (Dory extracts memories from conversation turns automatically):

```python
mem = DoryMemory(extract_model="qwen3:8b")                  # local via Ollama (5 GB)
mem = DoryMemory(extract_model="qwen3:14b")                 # local via Ollama (9 GB, better quality)
mem = DoryMemory(                                           # Claude
    extract_model="claude-haiku-4-5-20251001",
    extract_backend="anthropic",
    extract_api_key="sk-ant-...",
)
mem = DoryMemory(                                           # GPT / Grok / any compat
    extract_model="gpt-4o-mini",
    extract_backend="openai",
    extract_api_key="sk-...",
)

# Log turns — extraction happens automatically every N turns
mem.add_turn("user", "I'm working on AllergyFind today, need to add a menu endpoint")
mem.add_turn("assistant", "What authentication approach are you using?")

# Build API-ready messages with prompt caching
result = mem.build_context("menu endpoint authentication")
messages = result.as_anthropic_messages(user_query)   # Anthropic SDK w/ cache_control
messages = result.as_openai_messages(user_query)      # OpenAI / compat
```

### MCP server (Claude Code / Claude Desktop)

```bash
pip install 'dory-memory[mcp]'

# Find the installed binary path (needed if installed in a venv)
which dory-mcp

# Register globally across all Claude Code projects
claude mcp add --scope user dory -- /full/path/to/dory-mcp --db ~/.dory/engram.db
```

The `--db` path defaults to `~/.dory/engram.db` if omitted. You can also set `DORY_DB_PATH` as an environment variable.

Verify the server connected:
```bash
claude mcp list   # should show dory ✓ Connected
```

Five tools are exposed: `dory_query`, `dory_observe`, `dory_consolidate`, `dory_visualize`, `dory_stats`.

**Claude Desktop** — add to `claude_desktop_config.json`:
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

---

## Visualization

**[Live graph visualization →](https://michaelwmartinii.github.io/Dory/demo.html)**

![Dory memory graph demo](https://raw.githubusercontent.com/MichaelWMartinII/Dory/main/docs/demo.gif)

The hosted demo uses the fully interactive D3 view.

Locally, generated visualizations now default to a local-only fallback page that
shows the full node and edge data without loading remote JavaScript. If you want
the old interactive graph locally, opt in with `allow_remote_js=True` or
`dory visualize --remote-assets`.

---

### Framework adapters

**LangChain** — drop-in `BaseMemory` replacement:

```python
from dory.adapters.langchain import DoryMemoryAdapter
from langchain.chains import ConversationChain
from langchain_anthropic import ChatAnthropic

memory = DoryMemoryAdapter(
    extract_model="claude-haiku-4-5-20251001",
    extract_backend="anthropic",
    extract_api_key="sk-ant-...",
)
chain = ConversationChain(llm=ChatAnthropic(model="claude-sonnet-4-6"), memory=memory)
```

**LangGraph** — graph nodes with the `(state) -> state` signature:

```python
from dory.adapters.langgraph import DoryMemoryNode, MemoryState
from langgraph.graph import StateGraph, START, END

mem = DoryMemoryNode(extract_model="claude-haiku-4-5-20251001", extract_backend="anthropic")

builder = StateGraph(MemoryState)
builder.add_node("load_memory", mem.load_context)
builder.add_node("record_turn", mem.record_turn)
builder.add_edge(START, "load_memory")
builder.add_edge("load_memory", "record_turn")
builder.add_edge("record_turn", END)
graph = builder.compile()
```

**Multi-agent** — shared memory pool with thread-safe writes and agent attribution:

```python
from dory.adapters.multi_agent import SharedMemoryPool

pool = SharedMemoryPool(db_path="shared.db")
pool.observe("User prefers dark mode", agent_id="agent-1")
pool.add_turn("user", "Let's ship it", agent_id="agent-2", session_id="s1")
results = pool.query("UI preferences")
```

### Async API

All `DoryMemory` methods have async counterparts — safe to await from FastAPI, LangGraph, and any async framework:

```python
context = await mem.aquery("current topic")
result  = await mem.abuild_context("current topic")
await mem.aadd_turn("user", "message")
node_id = await mem.aobserve("User prefers JWT", node_type="PREFERENCE")
stats   = await mem.aflush()
```

### Export / import

```python
from dory.export.jsonld import JSONLDExporter

exporter = JSONLDExporter(graph)
exporter.export("memory.jsonld.json")
JSONLDExporter.import_into(graph, "memory.jsonld.json")
```

### Security notes

Security and hardening guidance lives in:

- `SECURITY.md`
- `docs/HARDENING_2026-03-29.md`
- `docs/REPO_CLEANUP_2026-03-29.md`

---

## How it works

### Knowledge graph

Every piece of information is a typed node: `ENTITY`, `CONCEPT`, `EVENT`, `PREFERENCE`, `BELIEF`, `PROCEDURE`, `SESSION` (episodic narrative), `SESSION_SUMMARY` (structured episodic). Edges between them are typed and weighted: `USES`, `WORKS_ON`, `PREFERS`, `SUPERSEDES`, `CO_OCCURS`, `SUPPORTS_FACT`, `TEMPORALLY_AFTER`, etc.

Salience is computed from connectivity, activation frequency, and recency. High-salience nodes become **core memories** — they anchor the stable context prefix.

### Observer

Every N conversation turns, the Observer calls an LLM to extract structured memories. Extractions carry confidence scores — anything below threshold is logged but not written to the graph.

Backends: Ollama (default), Anthropic (Claude), or any OpenAI-compatible endpoint.

### Prefixer

Builds context in two parts:

```
[stable prefix]         ← core memories + key relationships
                          same bytes across turns → prompt cache hits

[dynamic suffix]        ← spreading activation for this specific query
                          + recent episodic observations
```

### Decayer

```
score = recency_weight  × exp(-λ × days_since_activation)
      + frequency_weight × log(1 + activation_count)
      + relevance_weight × salience
```

Nodes below the active floor → archived. Below the archive floor → expired. Core memories are shielded with a configurable multiplier.

### Reflector

Near-duplicate detection (Jaccard ≥ 0.82): merges duplicates, keeping the higher-salience node and rewiring edges. Supersession detection (Jaccard in [0.45, 0.82), shared subject): archives the older node, adds `SUPERSEDES` provenance edge. Old observations compressed into summaries.

---

## Architecture

```
dory/
├── graph.py          ← nodes, edges, salience computation
├── schema.py         ← NodeType, EdgeType, zone constants
├── activation.py     ← spreading activation engine
├── consolidation.py  ← edge decay, strengthen, prune, promote/demote core
├── session.py        ← session-level helpers: query, observe, write_turn, end_session
├── memory.py         ← DoryMemory — high-level API (sync + async)
├── visualize.py      ← D3.js interactive graph visualization
├── mcp_server.py     ← MCP tools (dory_query, dory_observe, dory_consolidate, …)
├── store.py          ← SQLite backend (nodes, edges, FTS5, observations)
│
├── pipeline/
│   ├── observer.py   ← LLM extraction of memories from conversation turns
│   ├── summarizer.py ← episodic layer: SESSION nodes from conversation turns
│   ├── prefixer.py   ← stable prefix + dynamic suffix builder
│   ├── decayer.py    ← node decay scoring + zone management
│   └── reflector.py  ← dedup, supersession, observation compression
│
├── adapters/
│   ├── langchain.py   ← DoryMemoryAdapter (BaseMemory drop-in)
│   ├── langgraph.py   ← DoryMemoryNode (StateGraph integration)
│   └── multi_agent.py ← SharedMemoryPool (thread-safe multi-agent)
│
└── export/
    └── jsonld.py      ← JSON-LD round-trip export/import
```

---

## Local LLM setup

```bash
ollama pull qwen3:14b          # extraction
ollama pull nomic-embed-text   # embeddings (768-dim, offline after pull)
```

OpenAI-compatible endpoint (llama.cpp server, vLLM, etc.):
```python
obs = Observer(graph, backend="openai", base_url="http://localhost:8000", model="qwen3")
```

Vector search activates automatically once `nomic-embed-text` is available. Falls back to FTS5 BM25 if no embedding model is running.

---

## Decay zones

| Zone | Behavior | How to query |
|---|---|---|
| `active` | Retrieved in all normal queries | `graph.all_nodes()` (default) |
| `archived` | Invisible to normal queries | `graph.all_nodes(zone="archived")` |
| `expired` | Completely invisible | `graph.all_nodes(zone=None)` |

Memory is never deleted — only decayed. Archived and expired nodes retain full provenance and can be restored if reactivated. The one exception: exact structural duplicates detected by the Reflector are hard-merged (lower-salience copy removed, edges rewired to the winner).

---

## Comparison

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

## Graph topology — what flat search can't do

Run [`examples/demo_topology.py`](examples/demo_topology.py) to see six live graph traversals:

```
Q1 · Supersession — "What was the inference backend before MLX replaced it?"

  ┌ BEFORE  [PREFERENCE]  Prefers llama.cpp — cross-platform, well-supported
  │         zone=archived  archived=2026-03-01
  ├─SUPERSEDES──▶
  └ AFTER   [PREFERENCE]  Prefers MLX over llama.cpp on Apple Silicon (20-30% faster)

  ✗ Flat search: returns both nodes with equal score. No directionality. No timestamp.

──────────────────────────────────────────────────────────────────────
Q4 · Semantic Path — "How does local-first philosophy connect to the 80.6% result?"

  ● [CONCEPT]    Local-first AI — data stays on device, no cloud
    └─[CO_OCCURS]──▶
  ● [PREFERENCE] Prefers local-first — no data leaves device unless necessary
    └─[PREFERS]──▶
  ● [ENTITY]     Developer — solo, Apple Silicon
    └─[WORKS_ON]──▶
  ● [ENTITY]     Dory — agent memory library
    └─[CO_OCCURS]──▶
  ● [EVENT]      [2026-03-28] v0.5 temporal spot check — 90.0% temporal-reasoning

  ✗ Flat search: returns both endpoints as separate results. No connecting path.
```

| Query | Traversal | What it answers |
|---|---|---|
| Q1 Supersession | `SUPERSEDES` edges | What changed and when |
| Q2 Chronicle | `TEMPORALLY_AFTER` chain | Full session history in order |
| Q3 Dependencies | `USES` traversal (depth 2) | What a project actually needs |
| Q4 Semantic Path | BFS across typed edges | How two concepts connect |
| Q5 Provenance | `SUPPORTS_FACT` traversal | What proves a specific fact |
| Q6 Belief Grounding | `SUPPORTS_FACT` + `BELIEF` | Which beliefs have evidence |

---

## Benchmark results

[LongMemEval](https://arxiv.org/abs/2410.10813) (ICLR 2025), oracle split, 500 questions.

| Version | Extract | Answer | n | Score |
|---|---|---|---|---|
| v0.1 | Haiku | Haiku | 500 | 54.4% |
| v0.1 | Sonnet | Sonnet | 500 | 66.8% |
| v0.3 | Sonnet | Sonnet (direct API) | 500 | 79.8% |
| v0.4 | Haiku | Claude Code (MCP) | 500 | 80.6% |
| **v0.5** | **Haiku** | **Claude Code (MCP)** | **500** | **79.6%** |

v0.5 is statistically flat versus v0.4 overall, but the category movement is
the real story:

- temporal reasoning improved after explicit reference-date anchoring
- knowledge-update regressed due to date-override failures and reflector changes

Full writeups:

- [`benchmarks/REPORT_claudecode_mcp_v04.md`](benchmarks/REPORT_claudecode_mcp_v04.md)
- [`benchmarks/README.md`](benchmarks/README.md)

Published scores for reference: Mem0 68.4%, Zep 71.2%, Mastra 94.87%¹.

¹ Mastra uses GPT-4o-mini on TypeScript. Architecturally different stacks — not directly comparable.

**Note:** LongMemEval oracle split uses pre-filtered context (~15K tokens per question). Performance with live, unfiltered conversations will differ.

---

## Current priorities

The next engineering priorities are:

- fix reference-date override failures in duration calculations
- restore targeted knowledge-update synthesis without reintroducing noisy preference synthesis
- improve multi-session counting
- keep the docs and benchmark surface aligned with the shipped code

---

## Research basis

- [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560) — two-tier memory architecture
- [Zep: A Temporal Knowledge Graph Architecture](https://arxiv.org/abs/2501.13956) — bi-temporal provenance
- [MAGMA: Multi-Graph based Agentic Memory](https://arxiv.org/abs/2601.03236) — multi-graph retrieval
- [Mastra Observational Memory](https://mastra.ai/research/observational-memory) — cacheable prefix architecture
- [LongMemEval](https://arxiv.org/abs/2410.10813) (ICLR 2025) — evaluation benchmark
- Collins & Loftus (1975) — spreading activation in semantic memory
- Hebb (1949) — neurons that fire together wire together
- [Hopfield (1982)](https://www.pnas.org/doi/10.1073/pnas.79.8.2554) — associative memory energy landscape (Nobel Prize in Physics, 2024)

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

*Named after Dory from Finding Nemo, because your AI agent right now is Dory. This fixes it.*
