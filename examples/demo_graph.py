"""
Generate a realistic demo memory graph and render it to docs/demo.html.

Usage:
    python examples/demo_graph.py

Opens the visualization in your browser and writes docs/demo.html.
"""

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parent.parent))

from dory.graph import Graph
from dory.schema import NodeType, EdgeType, ZONE_ARCHIVED, now_iso
from dory.session import _route_query
from dory import activation as act
from dory import visualize

_tmp = Path(tempfile.mktemp(suffix=".db"))
g = Graph(_tmp)

# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
user       = g.add_node(NodeType.ENTITY, "Michael — solo developer, Murfreesboro TN", tags=["user"])
allergyapp = g.add_node(NodeType.ENTITY, "AllergyFind — B2B allergen platform for restaurants", tags=["project"])
agent_proj = g.add_node(NodeType.ENTITY, "Agent — local AI companion 'Elwin Ransom'", tags=["project"])
dory_proj  = g.add_node(NodeType.ENTITY, "Dory — agent memory library (this project)", tags=["project"])
giovanni   = g.add_node(NodeType.ENTITY, "Giovanni Ristorante Nashville — live customer", tags=["customer"])
qwen       = g.add_node(NodeType.ENTITY, "Qwen3-14B-Q4_K_M — primary local model", tags=["tool"])
fastapi    = g.add_node(NodeType.ENTITY, "FastAPI — web framework", tags=["tool"])
supabase   = g.add_node(NodeType.ENTITY, "Supabase / PostgreSQL — AllergyFind backend", tags=["tool"])
mlx        = g.add_node(NodeType.ENTITY, "MLX — Apple Silicon inference framework (20-30% faster than llama.cpp)", tags=["tool"])

# Archived — superseded by MLX switch (the real transition that happened March 2026)
llamacpp   = g.add_node(NodeType.ENTITY, "llama.cpp — inference backend (replaced by MLX)", tags=["tool"])
llamacpp.zone = ZONE_ARCHIVED
llamacpp.superseded_at = "2026-03-01T00:00:00+00:00"

# ---------------------------------------------------------------------------
# Concepts
# ---------------------------------------------------------------------------
local_first = g.add_node(NodeType.CONCEPT, "Local-first AI — data stays on device, no cloud", tags=["philosophy"])
mem_graph   = g.add_node(NodeType.CONCEPT, "Knowledge graph with spreading activation retrieval", tags=["architecture"])
episodic    = g.add_node(NodeType.CONCEPT, "Episodic memory — SESSION + SESSION_SUMMARY nodes", tags=["architecture"])
decay       = g.add_node(NodeType.CONCEPT, "Principled forgetting — three decay zones", tags=["architecture"])
benchmarks  = g.add_node(NodeType.CONCEPT, "LongMemEval benchmark — 500 questions (ICLR 2025)", tags=["research"])

# ---------------------------------------------------------------------------
# Procedures
# ---------------------------------------------------------------------------
deploy_proc = g.add_node(NodeType.PROCEDURE,
    "Deploy AllergyFind: 1) run pytest 2) push to main 3) Supabase migration 4) Render deploy",
    tags=["workflow", "allergyapp"])
debug_proc  = g.add_node(NodeType.PROCEDURE,
    "Debug local model: 1) check ollama serve 2) test with curl 3) inspect logits 4) reduce context",
    tags=["workflow", "llm"])

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
ev1 = g.add_node(NodeType.EVENT, "[2026-03-01] Switched inference backend from llama.cpp to MLX — 25% faster on M-series", tags=["decision"])
ev2 = g.add_node(NodeType.EVENT, "[2026-03-10] Shipped Dory v0.1 to PyPI — initial release", tags=["milestone"])
ev3 = g.add_node(NodeType.EVENT, "[2026-03-17] LongMemEval baseline — v0.1 Sonnet 66.8%, temporal-reasoning only 46.6%", tags=["benchmark"])
ev4 = g.add_node(NodeType.EVENT, "[2026-03-19] Episodic layer shipped — SESSION_SUMMARY nodes, retrieval fusion, ablation +20pp", tags=["milestone"])
ev5 = g.add_node(NodeType.EVENT, "[2026-03-20] v0.3 full run — 79.8% Sonnet (+13pp). Beats Mem0 and Zep. Tagged v0.3.0.", tags=["milestone", "benchmark"])
ev6 = g.add_node(NodeType.EVENT, "[2026-02-15] Giovanni Ristorante went live on AllergyFind — first revenue", tags=["milestone"])

# ---------------------------------------------------------------------------
# Preferences — including the supersession story
# ---------------------------------------------------------------------------
# Archived: old inference preference (superseded when MLX proved faster)
pr_old = g.add_node(NodeType.PREFERENCE,
    "Prefers llama.cpp for local inference — cross-platform, well-supported",
    tags=["tooling", "inference"])
pr_old.zone = ZONE_ARCHIVED
pr_old.superseded_at = "2026-03-01T00:00:00+00:00"

# Current: MLX replaced it after benchmarking
pr2 = g.add_node(NodeType.PREFERENCE, "Prefers MLX over llama.cpp on Apple Silicon (20-30% faster)", tags=["tooling", "inference"])
pr3 = g.add_node(NodeType.PREFERENCE, "Prefers local-first — no data leaves device unless necessary", tags=["philosophy"])
pr4 = g.add_node(NodeType.PREFERENCE, "Prefers Apache 2.0 license for all models and libraries", tags=["license"])
pr5 = g.add_node(NodeType.PREFERENCE, "Prefers minimal dependencies — Dory core has zero required deps", tags=["engineering"])

# ---------------------------------------------------------------------------
# Beliefs
# ---------------------------------------------------------------------------
bl1 = g.add_node(NodeType.BELIEF, "Graph memory beats flat vector search on multi-hop retrieval", tags=["technical"])
bl2 = g.add_node(NodeType.BELIEF, "Principled forgetting is a competitive moat — nobody else ships it", tags=["product"])

# ---------------------------------------------------------------------------
# SESSION nodes
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# SESSION_SUMMARY nodes (v0.2 — structured episodic with salient_counts)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Salience + core
# ---------------------------------------------------------------------------
for node, count in [
    (user, 22), (dory_proj, 20), (allergyapp, 16), (local_first, 14),
    (mem_graph, 15), (episodic, 14), (ev5, 12), (benchmarks, 13),
    (ss3, 11), (bl2, 9), (pr3, 10), (mlx, 8),
]:
    node.activation_count = count

for node in [user, dory_proj, allergyapp, local_first, mem_graph, episodic, ev5, ss3]:
    node.is_core = True

g._recompute_salience()

# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------
g.add_edge(user.id, allergyapp.id,  EdgeType.WORKS_ON,  weight=0.9)
g.add_edge(user.id, agent_proj.id,  EdgeType.WORKS_ON,  weight=0.8)
g.add_edge(user.id, dory_proj.id,   EdgeType.WORKS_ON,  weight=0.95)
g.add_edge(user.id, pr2.id,         EdgeType.PREFERS,   weight=0.9)
g.add_edge(user.id, pr3.id,         EdgeType.PREFERS,   weight=0.95)
g.add_edge(user.id, pr4.id,         EdgeType.PREFERS,   weight=0.85)
g.add_edge(user.id, pr5.id,         EdgeType.PREFERS,   weight=0.8)
g.add_edge(pr3.id,  local_first.id, EdgeType.CO_OCCURS, weight=0.9)

# Supersession: old llama.cpp preference → new MLX preference
g.add_edge(pr2.id,     pr_old.id,   EdgeType.SUPERSEDES, weight=0.95)
g.add_edge(mlx.id,     llamacpp.id, EdgeType.SUPERSEDES, weight=0.9)
g.add_edge(ev1.id,     mlx.id,      EdgeType.CO_OCCURS,  weight=0.85)
g.add_edge(ev1.id,     llamacpp.id, EdgeType.CO_OCCURS,  weight=0.7)

# Projects → tools
g.add_edge(allergyapp.id, giovanni.id,   EdgeType.USES, weight=0.9)
g.add_edge(allergyapp.id, fastapi.id,    EdgeType.USES, weight=0.8)
g.add_edge(allergyapp.id, supabase.id,   EdgeType.USES, weight=0.8)
g.add_edge(allergyapp.id, deploy_proc.id, EdgeType.USES, weight=0.7)
g.add_edge(agent_proj.id, qwen.id,       EdgeType.USES, weight=0.9)
g.add_edge(agent_proj.id, mlx.id,        EdgeType.USES, weight=0.85)
g.add_edge(agent_proj.id, debug_proc.id, EdgeType.USES, weight=0.7)

# Dory → architecture
g.add_edge(dory_proj.id, mem_graph.id,  EdgeType.USES,         weight=0.95)
g.add_edge(dory_proj.id, episodic.id,   EdgeType.USES,         weight=0.9)
g.add_edge(dory_proj.id, decay.id,      EdgeType.USES,         weight=0.85)
g.add_edge(dory_proj.id, benchmarks.id, EdgeType.CO_OCCURS,    weight=0.8)
g.add_edge(mem_graph.id, bl1.id,        EdgeType.SUPPORTS_FACT, weight=0.85)
g.add_edge(decay.id,     bl2.id,        EdgeType.SUPPORTS_FACT, weight=0.8)

# Events → concepts
g.add_edge(ev2.id, dory_proj.id,  EdgeType.CO_OCCURS,    weight=0.8)
g.add_edge(ev3.id, benchmarks.id, EdgeType.SUPPORTS_FACT, weight=0.9)
g.add_edge(ev4.id, episodic.id,   EdgeType.SUPPORTS_FACT, weight=0.9)
g.add_edge(ev5.id, benchmarks.id, EdgeType.SUPPORTS_FACT, weight=0.95)
g.add_edge(ev5.id, dory_proj.id,  EdgeType.CO_OCCURS,    weight=0.9)
g.add_edge(ev6.id, allergyapp.id, EdgeType.CO_OCCURS,    weight=0.9)

# SESSION_SUMMARY temporal chain
g.add_edge(ss2.id, ss1.id, EdgeType.TEMPORALLY_AFTER, weight=0.9)
g.add_edge(ss3.id, ss2.id, EdgeType.TEMPORALLY_AFTER, weight=0.9)

# SESSION_SUMMARY → semantic nodes (staged retrieval)
g.add_edge(ss1.id, benchmarks.id, EdgeType.SUPPORTS_FACT, weight=0.85)
g.add_edge(ss1.id, ev3.id,        EdgeType.SUPPORTS_FACT, weight=0.8)
g.add_edge(ss2.id, episodic.id,   EdgeType.SUPPORTS_FACT, weight=0.9)
g.add_edge(ss2.id, ev4.id,        EdgeType.SUPPORTS_FACT, weight=0.85)
g.add_edge(ss3.id, ev5.id,        EdgeType.SUPPORTS_FACT, weight=0.95)
g.add_edge(ss3.id, dory_proj.id,  EdgeType.MENTIONS,      weight=0.8)
g.add_edge(ss3.id, benchmarks.id, EdgeType.MENTIONS,      weight=0.8)

# SESSION → SESSION_SUMMARY
g.add_edge(s1.id, ss1.id, EdgeType.SUPPORTS_FACT, weight=0.7)
g.add_edge(s2.id, ss2.id, EdgeType.SUPPORTS_FACT, weight=0.7)
g.add_edge(s3.id, ss3.id, EdgeType.SUPPORTS_FACT, weight=0.7)

# ---------------------------------------------------------------------------
# Pre-compute demo queries (spreading activation on real graph)
# ---------------------------------------------------------------------------
def compute_query(topic: str) -> dict:
    seeds = act.find_seeds(topic, g)
    activated = {}
    if seeds:
        activated = act.spread(seeds[:8], g)
    route = _route_query(topic)
    # Normalize to [0, 1]
    if activated:
        max_level = max(activated.values())
        if max_level > 0:
            activated = {k: round(v / max_level, 3) for k, v in activated.items()}
    return {"text": topic, "route": route, "activated": activated}


demo_queries = [
    compute_query("what does Michael prefer for local AI and inference?"),
    compute_query("when did v0.3 ship and what was the benchmark score?"),
    compute_query("how many benchmark runs have been done?"),
    compute_query("has the inference backend ever changed?"),
]

# ---------------------------------------------------------------------------
# Render — include archived zone so superseded nodes are visible
# ---------------------------------------------------------------------------
from dory.schema import ZONE_ACTIVE, ZONE_ARCHIVED

out = Path(__file__).parent.parent / "docs" / "demo.html"
out.parent.mkdir(parents=True, exist_ok=True)

path = visualize.open_visualization(
    g,
    output_path=out,
    zones=[ZONE_ACTIVE, ZONE_ARCHIVED],
    open_browser=True,
    demo_queries=demo_queries,
)
print(f"Demo written to: {path}")
