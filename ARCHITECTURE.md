# Architecture — Dory

> Originally written under the project name "Engram". Published as `dory-memory`.

*An engram is the physical substrate of a memory in the brain — the actual trace left behind by experience. This project is the engineered equivalent for AI companions.*

---

## The Problem

Every AI memory system currently in use stores memories as flat files — bullet points, text chunks, key-value pairs. These are retrieval systems, not memory systems. They answer "what did we store?" not "what is relevant, what connects, what has become important over time?"

Flat files fail in three specific ways:
1. **No topology** — every fact has equal weight, nothing can become important through use
2. **No maintenance** — updating one fact means rewriting everything; contradictions coexist silently
3. **No emergence** — a "core memory" can't develop; importance must be pre-labeled at write time

The context window scaling bet (just make it bigger) doesn't fix this. It raises the ceiling on when the problem becomes painful. The architecture problem remains.

---

## The Core Insight

The brain doesn't have a better hard drive. It has a better retrieval architecture.

**Neurons that fire together wire together** (Hebb, 1949). When two memories are active simultaneously, the connection between them strengthens. Importance emerges from connectivity — a memory becomes "core" not because it was labeled important, but because over time everything connects through it.

This is what Engram builds: a memory graph where salience is computed, not assigned, and retrieval is spreading activation, not lookup.

---

## Architecture

### Node Types

```
ENTITY     — a person, place, or thing
CONCEPT    — an abstract idea or domain
EVENT      — something that happened at a point in time
PREFERENCE — a stated or observed inclination
BELIEF     — an assertion about the world, held with some confidence
SESSION    — a conversation instance (anchor for co-occurrence edges)
```

Each node carries:
- `id` — uuid
- `type` — from above
- `content` — natural language description
- `created_at` — timestamp
- `last_activated` — timestamp
- `activation_count` — how many times spread has touched this node
- `salience` — computed: f(connections, activation_count, recency)

### Edge Types

Two classes of edges:

**Explicit** — semantically labeled, created intentionally
```
WORKS_ON, BACKGROUND_IN, INTERESTED_IN, CAUSED, CONTRADICTS,
PART_OF, INSTANCE_OF, TRIGGERED, PREFERS
```

**Implicit** — co-occurrence based, formed automatically
```
CO_OCCURS — X and Y appeared in the same session context
           weight builds with each co-occurrence
           decays if the two stop appearing together
```

Each edge carries:
- `source_id`, `target_id`
- `type` — from above
- `weight` — 0.0 to 1.0, association strength
- `created_at`
- `last_activated`
- `activation_count`
- `decay_rate` — how fast weight drops without reinforcement

### Salience (computed, not assigned)

```
salience(node) =
    α × (degree / max_degree)          # connectivity
  + β × log(activation_count + 1)     # reinforcement
  + γ × recency_score(last_activated) # recency
```

Where α + β + γ = 1.0, tunable per use case.

A node becomes "core" when its salience crosses a threshold — emergent from use, not pre-labeled.

---

## Retrieval: Spreading Activation

Standard graph traversal won't work. We use spreading activation — the mechanism proposed by Collins & Loftus (1975) for semantic memory, adapted here for AI companion context.

```
1. Seed nodes — derive from current session content
   (NLP extraction or explicit tagging)

2. Spread — each seed node broadcasts activation to neighbors
   activation_received = source_activation × edge_weight × depth_decay

3. Accumulate — nodes can receive activation from multiple paths,
   values sum (with ceiling)

4. Threshold — return all nodes above activation threshold,
   sorted descending

5. Serialize — activated subgraph → natural language summary
   for context injection
```

Depth decay prevents the entire graph from lighting up. Default: 0.5 per hop.

---

## Consolidation (Forgetting as a Feature)

Runs periodically (e.g., end of session, or on a schedule):

1. **Strengthen** — edges traversed frequently get weight += reinforcement_delta
2. **Decay** — all edges lose weight × decay_rate since last activation
3. **Prune** — edges below minimum weight threshold are removed
4. **Promote** — nodes crossing salience threshold are flagged as core
5. **Demote** — core nodes whose salience drops below threshold lose the flag

This is the biological solution to the frame problem: strategic forgetting.
The system doesn't maintain every memory against every new fact —
it lets low-salience connections fade and high-salience ones strengthen.

---

## Module Plan

```
Engram/
├── planning.md          ← this file
├── engram/
│   ├── __init__.py
│   ├── graph.py         ← core graph: nodes, edges, CRUD
│   ├── activation.py    ← spreading activation engine
│   ├── consolidation.py ← decay, strengthen, prune, promote
│   ├── session.py       ← session interface: load context, integrate observations
│   ├── schema.py        ← node/edge types, validation
│   └── store.py         ← JSON persistence layer
└── tests/
    ├── test_graph.py
    ├── test_activation.py
    └── test_consolidation.py
```

---

## Implementation Phases

**Phase 1 — Core graph**
- Node and edge CRUD
- JSON persistence
- Basic salience computation

**Phase 2 — Activation engine**
- Spreading activation from seed nodes
- Depth decay
- Threshold filtering and sorting

**Phase 3 — Consolidation**
- Edge decay over time
- Strengthening on activation
- Core memory promotion/demotion

**Phase 4 — Session interface**
- Session start: extract seeds from context, run activation, serialize output
- Session end: parse new observations, form implicit co-occurrence edges, run consolidation

**Phase 5 — Implicit edge formation**
- Co-occurrence detection across a session
- Automatic edge creation and weight updates
- This is the hardest phase — requires reasoning about what "same context" means

---

## Open Questions

1. **Seed extraction** — how do we derive seed nodes from raw conversation text? Keyword extraction, NER, or an LLM call to identify relevant entities?

2. **Implicit edge granularity** — do SESSION nodes connect everything mentioned in a session to each other? That may over-connect. What's the right granularity for co-occurrence?

3. **Serialization format** — when injecting activated subgraph into context, do we output structured data, natural language, or a hybrid? Model comprehension depends heavily on this.

4. **Cold start** — new companion with empty graph. How do we bootstrap? Explicit onboarding, or let the graph build naturally from first sessions?

5. **Multi-companion** — one graph per companion instance, or a shared substrate with companion-scoped edges?

6. **Contradiction handling** — when a new observation conflicts with an existing belief node, do we: add a CONTRADICTS edge, update the existing node, create a new node and let salience arbitrate?

7. **Salience weights (α, β, γ)** — what are the right defaults? Probably use-case dependent. Needs empirical tuning.

---

## Why This Is Different

| Capability | Flat file | Vector DB + RAG | Engram |
|---|---|---|---|
| Update single fact | Rewrite file | Reindex chunk | Update one node |
| Relationship traversal | No | No | Yes |
| Importance emerges from use | No | No | Yes |
| Contradiction detection | No | No | Yes (CONTRADICTS edge) |
| Strategic forgetting | No | No | Yes (consolidation) |
| Contextual retrieval | Keyword | Semantic similarity | Spreading activation |
| Provenance tracking | No | Partial | Yes (edge metadata) |
| Core memory | Manual label | Manual label | Computed salience |

---

*Named for the engram — the hypothetical physical trace a memory leaves in neural tissue. First proposed by Richard Semon (1904). Still not fully understood. That feels right.*
