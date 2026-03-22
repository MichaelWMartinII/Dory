#!/usr/bin/env python3
"""
Dory demo — run this to see the library in action.

    python demo.py

No Ollama, no sqlite-vec required. Core graph only.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dory import Graph, NodeType, EdgeType, activation, consolidation
from dory.pipeline import Prefixer, Decayer, DecayConfig

# ── helpers ──────────────────────────────────────────────────────────────────

W = 70

def banner(text):
    print(f"\n{'─' * W}")
    print(f"  {text}")
    print(f"{'─' * W}")

def show_nodes(graph, title="Graph nodes"):
    print(f"\n  {title}:")
    nodes = sorted(graph.all_nodes(zone=None), key=lambda n: n.salience, reverse=True)
    for n in nodes:
        core = " ★" if n.is_core else ""
        zone = f" [{n.zone}]" if n.zone != "active" else ""
        print(f"    [{n.type.value:<10}]{core} {n.content:<52} salience={n.salience:.2f}{zone}")


# ── demo ─────────────────────────────────────────────────────────────────────

def main():
    tmp = tempfile.mkdtemp()
    db = Path(tmp) / "demo.db"
    g = Graph(path=db)

    # ── 1. The problem ───────────────────────────────────────────────────────

    banner("THE PROBLEM")
    print("""
  Every AI memory system today stores memories as flat files —
  bullet points, key-value pairs, text chunks. These are retrieval
  systems, not memory systems. They answer "what did we store?"
  not "what is relevant, what connects, what has become important?"

  Flat files fail in three ways:
    1. No topology    — every fact has equal weight
    2. No maintenance — contradictions coexist silently
    3. No emergence   — importance must be pre-labeled at write time

  Dory fixes this with a memory graph where salience is computed,
  not assigned, and retrieval is spreading activation, not lookup.
""")

    # ── 2. Build a graph ─────────────────────────────────────────────────────

    banner("STEP 1 — Build a memory graph")
    print("\n  Adding nodes about a developer named Michael...\n")

    michael  = g.add_node(NodeType.ENTITY,     "Michael Martin, solo developer")
    dory     = g.add_node(NodeType.ENTITY,     "Dory — agent memory library")
    allergy  = g.add_node(NodeType.ENTITY,     "AllergyFind — B2B allergen platform")
    elwin    = g.add_node(NodeType.ENTITY,     "Elwin Ransom — local AI companion")
    local_ai = g.add_node(NodeType.PREFERENCE, "Michael prefers local-first AI")
    apache   = g.add_node(NodeType.PREFERENCE, "Michael prefers Apache 2.0 licenses")
    qwen     = g.add_node(NodeType.CONCEPT,    "Qwen3-14B — primary local model")
    fastapi  = g.add_node(NodeType.CONCEPT,    "FastAPI — Python web framework")
    sqlite   = g.add_node(NodeType.CONCEPT,    "SQLite — embedded database")
    revenue  = g.add_node(NodeType.EVENT,      "AllergyFind onboarded first paying customer")

    g.add_edge(michael.id,  dory.id,     EdgeType.WORKS_ON)
    g.add_edge(michael.id,  allergy.id,  EdgeType.WORKS_ON)
    g.add_edge(michael.id,  elwin.id,    EdgeType.WORKS_ON)
    g.add_edge(michael.id,  local_ai.id, EdgeType.PREFERS)
    g.add_edge(michael.id,  apache.id,   EdgeType.PREFERS)
    g.add_edge(elwin.id,    qwen.id,     EdgeType.USES)
    g.add_edge(allergy.id,  fastapi.id,  EdgeType.USES)
    g.add_edge(allergy.id,  sqlite.id,   EdgeType.USES)
    g.add_edge(dory.id,     sqlite.id,   EdgeType.USES)
    g.add_edge(revenue.id,  allergy.id,  EdgeType.CAUSED)

    g.save()
    show_nodes(g, "After initial load")

    print("""
  Notice salience is computed from graph structure — not pre-assigned.
  Michael has high salience because everything connects through him.
""")

    # ── 3. Spreading activation ──────────────────────────────────────────────

    banner("STEP 2 — Spreading activation retrieval")

    queries = [
        "AllergyFind customer revenue",
        "local AI model preferences",
        "database",
    ]

    for q in queries:
        print(f"\n  Query: {q!r}")
        seeds = activation.find_seeds(q, g)
        if seeds:
            activated = activation.spread(seeds[:3], g)
            ranked = sorted(activated.items(), key=lambda kv: kv[1], reverse=True)[:4]
            for nid, score in ranked:
                node = g.get_node(nid)
                if node:
                    print(f"    {score:.2f}  [{node.type.value:<10}] {node.content}")
        else:
            print("    (no seeds found)")

    print("""
  Spreading activation follows edges. Asking about "AllergyFind revenue"
  retrieves the paying-customer event AND its FastAPI/SQLite stack —
  not just documents that mention those words.
""")

    # ── 4. Salience emerges from use ─────────────────────────────────────────

    banner("STEP 3 — Salience emerges from repeated use")
    print("\n  Simulating 10 sessions where AllergyFind is discussed...\n")

    for _ in range(10):
        seeds = activation.find_seeds("AllergyFind customer revenue FastAPI", g)
        if seeds:
            activation.spread(seeds[:3], g)

    g._recompute_salience()
    show_nodes(g, "After 10 AllergyFind sessions")

    print("""
  AllergyFind and its connected nodes have risen in salience.
  Nothing was manually labeled — importance emerged from use.
""")

    # ── 5. Core memory promotion ─────────────────────────────────────────────

    banner("STEP 4 — Core memory promotion")

    promoted = consolidation.promote_core(g, threshold=0.55)
    g.save()

    if promoted:
        print(f"\n  {len(promoted)} node(s) promoted to core memory (★):")
        for nid in promoted:
            node = g.get_node(nid)
            print(f"    ★  {node.content}  (salience={node.salience:.2f})")
    else:
        print("\n  No nodes crossed the promotion threshold yet.")

    print("""
  Core memories anchor the stable prefix — they're included in every
  context injection regardless of the current query.
""")

    # ── 6. Prefixer — cacheable context blocks ───────────────────────────────

    banner("STEP 5 — Prefixer: stable prefix + dynamic suffix")

    p = Prefixer(g)

    print("\n  ── Stable prefix (mark for prompt caching) ──────────────────")
    result = p.build(query="")
    prefix = result.prefix or "(no core memories yet — add more sessions)"
    for line in prefix.splitlines():
        print(f"  {line}")

    print("\n  ── Dynamic suffix for query: 'what database does AllergyFind use?' ──")
    result = p.build(query="what database does AllergyFind use")
    suffix = result.suffix or "(no activated nodes above threshold)"
    for line in suffix.splitlines():
        print(f"  {line}")

    print("""
  The stable prefix is identical across turns until the graph changes.
  Cache it with Anthropic's cache_control or OpenAI's prefix caching
  for 4–10x token cost reduction (per Mastra's research).

  result.as_anthropic_messages(user_query="...")  →  ready to pass to API
  result.as_openai_messages(user_query="...")     →  same for OpenAI-compat
""")

    # ── 7. Decay ──────────────────────────────────────────────────────────────

    banner("STEP 6 — Principled forgetting")

    from datetime import datetime, timezone, timedelta

    # Simulate apache and qwen not being activated for 6 months
    for node in [apache, qwen]:
        node.last_activated = (
            datetime.now(timezone.utc) - timedelta(days=180)
        ).isoformat()
        node.activation_count = 2

    cfg = DecayConfig(active_floor=0.30, min_activations_before_archive=2)
    d = Decayer(g, config=cfg)
    stats = d.run()

    print(f"\n  Decay run results:")
    print(f"    scored:   {stats['scored']}")
    print(f"    archived: {stats['archived']}")
    print(f"    expired:  {stats['expired']}")
    print(f"    restored: {stats['restored']}")

    show_nodes(g, "After decay (zone=None shows all)")

    print("""
  Low-salience nodes move to 'archived' (invisible to normal queries)
  or 'expired' (invisible entirely). Nothing is ever deleted.
  Zone changes are reversible — activation restores a node.
""")

    # ── 8. Summary ───────────────────────────────────────────────────────────

    banner("SUMMARY")

    stats = g.stats()
    print(f"""
  Graph state:
    Total nodes:  {stats['nodes']}
    Active:       {stats['active']}
    Archived:     {stats['archived']}
    Expired:      {stats['expired']}
    Core (★):     {stats['core_nodes']}
    Edges:        {stats['edges']}

  What Dory provides that flat files don't:
    ✓  Salience emerges from use, not pre-labeling
    ✓  Spreading activation follows relationships
    ✓  Core memories anchor stable cacheable prefixes
    ✓  Principled forgetting — archive, don't delete
    ✓  Conflict resolution via SUPERSEDES edges
    ✓  LLM extraction pipeline (Observer) — optional
    ✓  Zero required dependencies — works offline

  Install:
    pip install dory-memory                  # core only
    pip install dory-memory[ollama]          # + LLM extraction
    pip install dory-memory[full]            # + vector search

  GitHub: https://github.com/MichaelWMartinII/Dory
{'─' * W}
""")


if __name__ == "__main__":
    main()
