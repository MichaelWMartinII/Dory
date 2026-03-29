"""
demo_topology.py — Graph Topology Proof

Six queries that only a knowledge graph can answer correctly.
Flat vector search returns documents; Dory traverses typed relationships.

Usage:
    python examples/demo_topology.py
"""

from __future__ import annotations

import sys
import tempfile
import os
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dory.graph import Graph
from dory.schema import EdgeType, NodeType, ZONE_ACTIVE, ZONE_ARCHIVED, now_iso

# ── Build demo graph ──────────────────────────────────────────────────────────

fd, tmp = tempfile.mkstemp(suffix=".db")
os.close(fd)
Path(tmp).unlink(missing_ok=True)
g = Graph(Path(tmp))

# Entities
user       = g.add_node(NodeType.ENTITY, "Michael — solo developer, Murfreesboro TN", tags=["user"])
allergyapp = g.add_node(NodeType.ENTITY, "AllergyFind — B2B allergen platform for restaurants", tags=["project"])
agent_proj = g.add_node(NodeType.ENTITY, "Agent — local AI companion 'Elwin Ransom'", tags=["project"])
dory_proj  = g.add_node(NodeType.ENTITY, "Dory — agent memory library (this project)", tags=["project"])
giovanni   = g.add_node(NodeType.ENTITY, "Unnamed restaurant client — live production customer", tags=["customer"])
qwen       = g.add_node(NodeType.ENTITY, "Qwen3-14B-Q4_K_M — primary local model", tags=["tool"])
fastapi    = g.add_node(NodeType.ENTITY, "FastAPI — web framework", tags=["tool"])
supabase   = g.add_node(NodeType.ENTITY, "Supabase / PostgreSQL — AllergyFind backend", tags=["tool"])
mlx        = g.add_node(NodeType.ENTITY, "MLX — Apple Silicon inference framework (20-30% faster than llama.cpp)", tags=["tool"])

llamacpp   = g.add_node(NodeType.ENTITY, "llama.cpp — inference backend (replaced by MLX)", tags=["tool"])
llamacpp.zone = ZONE_ARCHIVED
llamacpp.superseded_at = "2026-03-01T00:00:00+00:00"

# Concepts
local_first = g.add_node(NodeType.CONCEPT, "Local-first AI — data stays on device, no cloud", tags=["philosophy"])
mem_graph   = g.add_node(NodeType.CONCEPT, "Knowledge graph with spreading activation retrieval", tags=["architecture"])
episodic    = g.add_node(NodeType.CONCEPT, "Episodic memory — SESSION + SESSION_SUMMARY nodes", tags=["architecture"])
decay       = g.add_node(NodeType.CONCEPT, "Principled forgetting — three decay zones", tags=["architecture"])
benchmarks  = g.add_node(NodeType.CONCEPT, "LongMemEval benchmark — 500 questions (ICLR 2025)", tags=["research"])

# Procedures
deploy_proc = g.add_node(NodeType.PROCEDURE,
    "Deploy AllergyFind: 1) run pytest 2) push to main 3) Supabase migration 4) Render deploy",
    tags=["workflow", "allergyapp"])
debug_proc  = g.add_node(NodeType.PROCEDURE,
    "Debug local model: 1) check ollama serve 2) test with curl 3) inspect logits 4) reduce context",
    tags=["workflow", "llm"])

# Events
ev1 = g.add_node(NodeType.EVENT, "[2026-03-01] Switched inference backend from llama.cpp to MLX — 25% faster on M-series", tags=["decision"])
ev2 = g.add_node(NodeType.EVENT, "[2026-03-10] Shipped Dory v0.1 to PyPI — initial release", tags=["milestone"])
ev3 = g.add_node(NodeType.EVENT, "[2026-03-17] LongMemEval baseline — v0.1 Sonnet 66.8%, temporal-reasoning only 46.6%", tags=["benchmark"])
ev4 = g.add_node(NodeType.EVENT, "[2026-03-19] Episodic layer shipped — SESSION_SUMMARY nodes, retrieval fusion, ablation +20pp", tags=["milestone"])
ev5 = g.add_node(NodeType.EVENT, "[2026-03-20] v0.3 full run — 79.8% Sonnet (+13pp). Beats Mem0 and Zep. Tagged v0.3.0.", tags=["milestone", "benchmark"])
ev6 = g.add_node(NodeType.EVENT, "[2026-02-15] First restaurant client went live on AllergyFind — first revenue", tags=["milestone"])

# Preferences (includes superseded old preference)
pr_old = g.add_node(NodeType.PREFERENCE,
    "Prefers llama.cpp for local inference — cross-platform, well-supported",
    tags=["tooling", "inference"])
pr_old.zone = ZONE_ARCHIVED
pr_old.superseded_at = "2026-03-01T00:00:00+00:00"

pr2 = g.add_node(NodeType.PREFERENCE, "Prefers MLX over llama.cpp on Apple Silicon (20-30% faster)", tags=["tooling", "inference"])
pr3 = g.add_node(NodeType.PREFERENCE, "Prefers local-first — no data leaves device unless necessary", tags=["philosophy"])
pr4 = g.add_node(NodeType.PREFERENCE, "Prefers Apache 2.0 license for all models and libraries", tags=["license"])
pr5 = g.add_node(NodeType.PREFERENCE, "Prefers minimal dependencies — Dory core has zero required deps", tags=["engineering"])

# Beliefs
bl1 = g.add_node(NodeType.BELIEF, "Graph memory beats flat vector search on multi-hop retrieval", tags=["technical"])
bl2 = g.add_node(NodeType.BELIEF, "Principled forgetting is a competitive moat — nobody else ships it", tags=["product"])

# SESSION nodes
s1 = g.add_node(NodeType.SESSION,
    "[2026-03-17] Session: Ran LongMemEval baseline. Temporal-reasoning at 46.6% — worst category. "
    "Identified SESSION_SUMMARY layer as the key missing piece.",
    tags=["session"])
s2 = g.add_node(NodeType.SESSION,
    "[2026-03-19] Session: Shipped episodic layer. Ablation: SESSION_SUMMARY = +20pp. "
    "Spot check 67.5% Haiku — matches v0.1 Sonnet at 1/10th cost.",
    tags=["session"])
s3 = g.add_node(NodeType.SESSION,
    "[2026-03-20] Session: Full v0.3 Sonnet run complete. 79.8% (+13pp). "
    "Tagged v0.3.0. Published GitHub Release. Every category improved.",
    tags=["session"])

# SESSION_SUMMARY nodes
ss1 = g.add_node(NodeType.SESSION_SUMMARY,
    "[2026-03-17] Summary: LongMemEval baseline run. Identified temporal-reasoning (46.6%) "
    "and multi-session as weakest. Planned episodic SESSION_SUMMARY layer as primary fix.",
    tags=["session_summary"])
ss1.metadata["session_date"] = "2026-03-17"
ss1.metadata["salient_counts"] = {"benchmark_runs": 1, "questions_evaluated": 500, "categories_analyzed": 6}

ss2 = g.add_node(NodeType.SESSION_SUMMARY,
    "[2026-03-19] Summary: Shipped v0.2 episodic layer. SESSION_SUMMARY nodes, retrieval fusion, "
    "3-mode routing. Ablation confirmed +20pp from summaries. Spot check 67.5% Haiku.",
    tags=["session_summary"])
ss2.metadata["session_date"] = "2026-03-19"
ss2.metadata["salient_counts"] = {"features_shipped": 4, "benchmark_questions": 40, "ablation_runs": 3}

ss3 = g.add_node(NodeType.SESSION_SUMMARY,
    "[2026-03-20] Summary: Full v0.3 Sonnet run — 79.8% overall, +13pp over v0.1. "
    "Temporal: 46.6% → 75.9% (+29.3pp). Every category improved. Tagged v0.3.0.",
    tags=["session_summary"])
ss3.metadata["session_date"] = "2026-03-20"
ss3.metadata["salient_counts"] = {"benchmark_questions": 500, "categories_improved": 6, "pp_gain": 13}

# Salience
for node, count in [
    (user, 22), (dory_proj, 20), (allergyapp, 16), (local_first, 14),
    (mem_graph, 15), (episodic, 14), (ev5, 12), (benchmarks, 13),
    (ss3, 11), (bl2, 9), (pr3, 10), (mlx, 8),
]:
    node.activation_count = count

for node in [user, dory_proj, allergyapp, local_first, mem_graph, episodic, ev5, ss3]:
    node.is_core = True

g._recompute_salience()

# Edges
g.add_edge(user.id, allergyapp.id,   EdgeType.WORKS_ON,  weight=0.9)
g.add_edge(user.id, agent_proj.id,   EdgeType.WORKS_ON,  weight=0.8)
g.add_edge(user.id, dory_proj.id,    EdgeType.WORKS_ON,  weight=0.95)
g.add_edge(user.id, pr2.id,          EdgeType.PREFERS,   weight=0.9)
g.add_edge(user.id, pr3.id,          EdgeType.PREFERS,   weight=0.95)
g.add_edge(user.id, pr4.id,          EdgeType.PREFERS,   weight=0.85)
g.add_edge(user.id, pr5.id,          EdgeType.PREFERS,   weight=0.8)
g.add_edge(pr3.id,  local_first.id,  EdgeType.CO_OCCURS, weight=0.9)
g.add_edge(pr2.id,  pr_old.id,       EdgeType.SUPERSEDES, weight=0.95)
g.add_edge(mlx.id,  llamacpp.id,     EdgeType.SUPERSEDES, weight=0.9)
g.add_edge(ev1.id,  mlx.id,          EdgeType.CO_OCCURS,  weight=0.85)
g.add_edge(ev1.id,  llamacpp.id,     EdgeType.CO_OCCURS,  weight=0.7)
g.add_edge(allergyapp.id, giovanni.id,    EdgeType.USES, weight=0.9)
g.add_edge(allergyapp.id, fastapi.id,     EdgeType.USES, weight=0.8)
g.add_edge(allergyapp.id, supabase.id,    EdgeType.USES, weight=0.8)
g.add_edge(allergyapp.id, deploy_proc.id, EdgeType.USES, weight=0.7)
g.add_edge(agent_proj.id, qwen.id,        EdgeType.USES, weight=0.9)
g.add_edge(agent_proj.id, mlx.id,         EdgeType.USES, weight=0.85)
g.add_edge(agent_proj.id, debug_proc.id,  EdgeType.USES, weight=0.7)
g.add_edge(dory_proj.id,  mem_graph.id,   EdgeType.USES,          weight=0.95)
g.add_edge(dory_proj.id,  episodic.id,    EdgeType.USES,          weight=0.9)
g.add_edge(dory_proj.id,  decay.id,       EdgeType.USES,          weight=0.85)
g.add_edge(dory_proj.id,  benchmarks.id,  EdgeType.CO_OCCURS,     weight=0.8)
g.add_edge(mem_graph.id,  bl1.id,         EdgeType.SUPPORTS_FACT, weight=0.85)
g.add_edge(decay.id,      bl2.id,         EdgeType.SUPPORTS_FACT, weight=0.8)
g.add_edge(ev2.id,        dory_proj.id,   EdgeType.CO_OCCURS,     weight=0.8)
g.add_edge(ev3.id,        benchmarks.id,  EdgeType.SUPPORTS_FACT, weight=0.9)
g.add_edge(ev4.id,        episodic.id,    EdgeType.SUPPORTS_FACT, weight=0.9)
g.add_edge(ev5.id,        benchmarks.id,  EdgeType.SUPPORTS_FACT, weight=0.95)
g.add_edge(ev5.id,        dory_proj.id,   EdgeType.CO_OCCURS,     weight=0.9)
g.add_edge(ev6.id,        allergyapp.id,  EdgeType.CO_OCCURS,     weight=0.9)
g.add_edge(ss2.id,  ss1.id,  EdgeType.TEMPORALLY_AFTER, weight=0.9)
g.add_edge(ss3.id,  ss2.id,  EdgeType.TEMPORALLY_AFTER, weight=0.9)
g.add_edge(ss1.id,  benchmarks.id, EdgeType.SUPPORTS_FACT, weight=0.85)
g.add_edge(ss1.id,  ev3.id,        EdgeType.SUPPORTS_FACT, weight=0.8)
g.add_edge(ss2.id,  episodic.id,   EdgeType.SUPPORTS_FACT, weight=0.9)
g.add_edge(ss2.id,  ev4.id,        EdgeType.SUPPORTS_FACT, weight=0.85)
g.add_edge(ss3.id,  ev5.id,        EdgeType.SUPPORTS_FACT, weight=0.95)
g.add_edge(ss3.id,  dory_proj.id,  EdgeType.MENTIONS,      weight=0.8)
g.add_edge(ss3.id,  benchmarks.id, EdgeType.MENTIONS,      weight=0.8)
g.add_edge(s1.id,   ss1.id,        EdgeType.SUPPORTS_FACT, weight=0.7)
g.add_edge(s2.id,   ss2.id,        EdgeType.SUPPORTS_FACT, weight=0.7)
g.add_edge(s3.id,   ss3.id,        EdgeType.SUPPORTS_FACT, weight=0.7)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _lbl(node, width=60) -> str:
    c = node.content
    return (c[:width] + "…") if len(c) > width else c


def _section(title: str, query: str) -> None:
    bar = "─" * 68
    print(f"\n{bar}")
    print(f"  {title}")
    print(f"  Query: \"{query}\"")
    print(bar)


def _flat_note(text: str) -> None:
    print(f"\n  ✗ Flat search can't do this:")
    for line in text.strip().splitlines():
        print(f"    {line}")


def _shortest_path(start_id: str, end_id: str) -> list[tuple[str, str | None]] | None:
    """
    BFS shortest path between two nodes (undirected).
    Returns list of (node_id, edge_type_used_to_arrive) pairs, or None if unreachable.
    """
    if start_id == end_id:
        return [(start_id, None)]

    adj: dict[str, list[tuple[str, str]]] = {}
    for edge in g.all_edges():
        adj.setdefault(edge.source_id, []).append((edge.target_id, edge.type.value))
        adj.setdefault(edge.target_id, []).append((edge.source_id, edge.type.value))

    # BFS
    queue: deque[list[tuple[str, str | None]]] = deque([[(start_id, None)]])
    visited = {start_id}

    while queue:
        path = queue.popleft()
        current_id = path[-1][0]
        for neighbor_id, etype in adj.get(current_id, []):
            if neighbor_id not in visited:
                new_path = path + [(neighbor_id, etype)]
                if neighbor_id == end_id:
                    return new_path
                visited.add(neighbor_id)
                queue.append(new_path)
    return None


# ── Query 1: Supersession — belief/preference/tool changes ────────────────────

_section("Q1 · Supersession Audit", "What changed, what replaced it, and when?")

supersedes = [e for e in g.all_edges() if e.type == EdgeType.SUPERSEDES]
print()
for edge in supersedes:
    new_node = g.get_node(edge.source_id)
    old_node = g.get_node(edge.target_id)
    if not new_node or not old_node:
        continue
    archived_date = old_node.superseded_at[:10] if old_node.superseded_at else "unknown"
    print(f"  ┌ BEFORE  [{old_node.type.value}]  {_lbl(old_node)}")
    print(f"  │         zone={old_node.zone}  archived={archived_date}")
    print(f"  ├─SUPERSEDES──▶")
    print(f"  └ AFTER   [{new_node.type.value}]  {_lbl(new_node)}")
    print()

_flat_note("""\
Keyword search for "inference" returns both nodes with equal score.
No directionality. No timestamp. No way to know which came first
or that one explicitly replaced the other.""")


# ── Query 2: Temporal Chronicle — walk session history ───────────────────────

_section("Q2 · Temporal Chronicle", "Walk the full history of benchmark work, session by session")

# Find the earliest SESSION_SUMMARY (no TEMPORALLY_AFTER edge pointing to it)
ta_targets = {e.target_id for e in g.all_edges() if e.type == EdgeType.TEMPORALLY_AFTER}
ta_sources = {e.source_id for e in g.all_edges() if e.type == EdgeType.TEMPORALLY_AFTER}

# The chain is: ss1 ← ss2 ← ss3 (ss3 is most recent, points back to ss2, etc.)
# Start from the oldest: the one that appears as a target but not as a source
oldest_ss_id = (ta_targets - ta_sources)
all_ss = {n.id for n in g.all_nodes(zone=None) if n.type == NodeType.SESSION_SUMMARY}
oldest_id = (oldest_ss_id & all_ss)
if not oldest_id:
    oldest_id = all_ss  # fallback

# Build chain forward from oldest
chain = []
current_id = next(iter(oldest_id))
visited_chain: set[str] = set()
while current_id and current_id not in visited_chain:
    chain.append(current_id)
    visited_chain.add(current_id)
    # Find what points TEMPORALLY_AFTER to this node (i.e., the next summary after this)
    nxt = next(
        (e.source_id for e in g.all_edges()
         if e.type == EdgeType.TEMPORALLY_AFTER and e.target_id == current_id),
        None
    )
    current_id = nxt

print()
for i, nid in enumerate(chain):
    node = g.get_node(nid)
    if not node:
        continue
    date = node.metadata.get("session_date", "")
    counts = node.metadata.get("salient_counts", {})
    connector = "  │\n  ▼ TEMPORALLY_AFTER\n  │\n" if i < len(chain) - 1 else ""
    print(f"  ● {_lbl(node, 60)}")
    if counts:
        count_str = "  ".join(f"{k}: {v}" for k, v in counts.items())
        print(f"    counts: {count_str}")
    if connector:
        print(connector, end="")
print()

_flat_note("""\
Keyword search returns all session nodes jumbled by similarity score.
No ordering. No structured counts at each step.
No way to reconstruct "what happened first → what changed → what resulted".""")


# ── Query 3: Dependency Tree — recursive USES traversal ──────────────────────

_section("Q3 · Dependency Tree", "What does AllergyFind depend on, down to its procedures?")

def _walk_uses(node_id: str, depth: int, visited: set, indent: int = 0) -> None:
    if depth == 0 or node_id in visited:
        return
    visited.add(node_id)
    node = g.get_node(node_id)
    if not node:
        return
    prefix = "    " + "  " * indent
    bullet = "└─" if indent > 0 else "●"
    print(f"{prefix}{bullet} [{node.type.value}] {_lbl(node, 55)}")
    for edge in g.all_edges():
        if edge.source_id == node_id and edge.type == EdgeType.USES:
            _walk_uses(edge.target_id, depth - 1, visited, indent + 1)

print()
_walk_uses(allergyapp.id, depth=3, visited=set())
print()

_flat_note("""\
"AllergyFind dependencies" matches every node that mentions AllergyFind.
No hierarchy. No depth. No distinction between direct and transitive deps.""")


# ── Query 4: Semantic Path — shortest path between two concepts ───────────────

_section(
    "Q4 · Semantic Path",
    "How is Michael's local-first philosophy connected to the 79.8% benchmark result?"
)

path = _shortest_path(local_first.id, ev5.id)
print()
if path:
    for i, (nid, etype) in enumerate(path):
        node = g.get_node(nid)
        if not node:
            continue
        if etype:
            print(f"    │")
            print(f"    └─[{etype}]──▶")
            print(f"    │")
        print(f"  ● [{node.type.value}] {_lbl(node, 58)}")
else:
    print("  (no path found)")
print()

_flat_note("""\
Returns "local-first" and the benchmark event as separate high-scoring docs.
No connecting path. No explanation of how one leads to the other.
Multi-hop semantic relationships are invisible to embedding distance.""")


# ── Query 5: Provenance Trail — what grounds a fact? ─────────────────────────

_section("Q5 · Provenance Trail", "What session evidence grounds the 79.8% benchmark claim?")

target = ev5
print(f"\n  Fact: \"{_lbl(target, 62)}\"\n")
print("  Grounded by:")

# Walk backwards: find nodes that SUPPORTS_FACT → ev5
direct_supporters = [
    g.get_node(e.source_id)
    for e in g.all_edges()
    if e.type == EdgeType.SUPPORTS_FACT and e.target_id == target.id
]
for src in direct_supporters:
    if src:
        print(f"    ● [{src.type.value}] {_lbl(src, 58)}")
        # And what grounds those?
        indirect = [
            g.get_node(e.source_id)
            for e in g.all_edges()
            if e.type in (EdgeType.SUPPORTS_FACT, EdgeType.MENTIONS) and e.target_id == src.id
        ]
        for isrc in indirect:
            if isrc:
                print(f"      └─ [{isrc.type.value}] {_lbl(isrc, 54)}")
print()

_flat_note("""\
Similarity search returns every node mentioning "79.8%" or "benchmark".
No distinction between the claim itself and its supporting evidence.
No way to ask "what proves this?" — only "what's similar to this?".""")


# ── Query 6: Belief Grounding — are beliefs backed by evidence? ───────────────

_section("Q6 · Belief Grounding", "Which beliefs have SESSION_SUMMARY evidence behind them?")

beliefs = [n for n in g.all_nodes(zone=None) if n.type == NodeType.BELIEF]
print()
for belief in beliefs:
    print(f"  BELIEF: \"{_lbl(belief, 62)}\"")
    # Find direct SUPPORTS_FACT sources
    supporters = [
        g.get_node(e.source_id)
        for e in g.all_edges()
        if e.type == EdgeType.SUPPORTS_FACT and e.target_id == belief.id
    ]
    if supporters:
        for s in supporters:
            if s:
                print(f"    └─ SUPPORTS_FACT ← [{s.type.value}] {_lbl(s, 50)}")
    else:
        print("    └─ ⚠ No direct evidence nodes linked")
    print()

_flat_note("""\
"Graph memory beats flat search" returns similar nodes about graphs and search.
No way to distinguish "this belief exists" from "this belief is proven."
Provenance requires directed typed edges — not cosine similarity.""")


# ── Summary ───────────────────────────────────────────────────────────────────

print("\n" + "═" * 68)
print("  Dory Graph Topology — Summary")
print("═" * 68)
rows = [
    ("Q1 Supersession", "SUPERSEDES edges",       "What changed and when"),
    ("Q2 Chronicle",    "TEMPORALLY_AFTER chain",  "Full session history in order"),
    ("Q3 Dependencies", "USES traversal (depth 2)","What a project actually needs"),
    ("Q4 Semantic Path","BFS across typed edges",  "How two concepts connect"),
    ("Q5 Provenance",   "SUPPORTS_FACT traversal", "What proves a specific fact"),
    ("Q6 Belief",       "SUPPORTS_FACT + BELIEF",  "Which beliefs have evidence"),
]
for query, traversal, answer in rows:
    print(f"  {query:<20} {traversal:<28} → {answer}")

print("\n  None of the above are answerable by cosine similarity alone.")
print("  They require directed, typed edges between persistent nodes.\n")

# ── Open visualization ────────────────────────────────────────────────────────

from dory import visualize

out = Path(__file__).parent.parent / "docs" / "demo.html"
out.parent.mkdir(parents=True, exist_ok=True)
path = visualize.open_visualization(
    g,
    output_path=out,
    zones=[ZONE_ACTIVE, ZONE_ARCHIVED],
    open_browser=True,
)
print(f"Graph written to: {path}\n")
