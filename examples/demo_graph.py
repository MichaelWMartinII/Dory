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
from dory.schema import NodeType, EdgeType
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

# ---------------------------------------------------------------------------
# Concepts
# ---------------------------------------------------------------------------
local_first = g.add_node(NodeType.CONCEPT, "Local-first AI — data stays on device, no cloud", tags=["philosophy"])
mem_graph   = g.add_node(NodeType.CONCEPT, "Knowledge graph with spreading activation retrieval", tags=["architecture"])
episodic    = g.add_node(NodeType.CONCEPT, "Episodic memory — SESSION + SESSION_SUMMARY nodes", tags=["architecture"])
decay       = g.add_node(NodeType.CONCEPT, "Principled forgetting — three decay zones", tags=["architecture"])
benchmarks  = g.add_node(NodeType.CONCEPT, "LongMemEval benchmark — 500 questions (ICLR 2025)", tags=["research"])

# ---------------------------------------------------------------------------
# Procedures  (v0.1 feature)
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
ev1 = g.add_node(NodeType.EVENT, "[2026-03-10] Shipped Dory v0.1 to PyPI — initial release", tags=["milestone"])
ev2 = g.add_node(NodeType.EVENT, "[2026-03-17] LongMemEval baseline — v0.1 Sonnet 66.8%, temporal-reasoning only 46.6%", tags=["benchmark"])
ev3 = g.add_node(NodeType.EVENT, "[2026-03-19] Episodic layer shipped — SESSION_SUMMARY nodes, retrieval fusion", tags=["milestone"])
ev4 = g.add_node(NodeType.EVENT, "[2026-03-20] v0.3 full run — 79.8% Sonnet (+13pp). Beats Mem0 and Zep.", tags=["milestone", "benchmark"])
ev5 = g.add_node(NodeType.EVENT, "[2026-02-15] Giovanni Ristorante went live on AllergyFind — first revenue", tags=["milestone"])

# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------
pr1 = g.add_node(NodeType.PREFERENCE, "Prefers Apache 2.0 license for all models and libraries", tags=["license"])
pr2 = g.add_node(NodeType.PREFERENCE, "Prefers MLX over llama.cpp on Apple Silicon (20-30% faster)", tags=["tooling"])
pr3 = g.add_node(NodeType.PREFERENCE, "Prefers local-first — no data leaves device unless necessary", tags=["philosophy"])

# ---------------------------------------------------------------------------
# Beliefs
# ---------------------------------------------------------------------------
bl1 = g.add_node(NodeType.BELIEF, "Graph memory beats flat vector search on multi-hop retrieval", tags=["technical"])
bl2 = g.add_node(NodeType.BELIEF, "Principled forgetting is a competitive moat — nobody else ships it", tags=["product"])

# ---------------------------------------------------------------------------
# SESSION nodes (raw episodic log)
# ---------------------------------------------------------------------------
s1 = g.add_node(NodeType.SESSION,
    "[2026-03-17] Session: Ran LongMemEval baseline. Temporal-reasoning at 46.6% — worst category. "
    "Identified SESSION_SUMMARY layer as key missing piece.",
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
# SESSION_SUMMARY nodes (v0.2 feature — structured episodic with salient_counts)
# ---------------------------------------------------------------------------
ss1 = g.add_node(NodeType.SESSION_SUMMARY,
    "[2026-03-17] Summary: Ran 500-question LongMemEval baseline with Sonnet. "
    "Identified temporal-reasoning (46.6%) and multi-session as weakest categories. "
    "Planned episodic SESSION_SUMMARY layer as primary fix.",
    tags=["session_summary"])
ss1.metadata["session_date"] = "2026-03-17"
ss1.metadata["salient_counts"] = {"benchmark_runs": 1, "questions_evaluated": 500, "categories_analyzed": 6}

ss2 = g.add_node(NodeType.SESSION_SUMMARY,
    "[2026-03-19] Summary: Shipped v0.2 episodic layer. SESSION_SUMMARY nodes with salient_counts. "
    "Retrieval fusion with 3-mode routing. Ablation confirmed +20pp from summaries. "
    "Spot check on 40 questions: 67.5% Haiku.",
    tags=["session_summary"])
ss2.metadata["session_date"] = "2026-03-19"
ss2.metadata["salient_counts"] = {"features_shipped": 4, "benchmark_questions": 40, "ablation_runs": 3}

ss3 = g.add_node(NodeType.SESSION_SUMMARY,
    "[2026-03-20] Summary: Full v0.3 Sonnet/Sonnet run on 500 questions. "
    "79.8% overall, +13pp over v0.1. Temporal-reasoning: 46.6% → 75.9% (+29.3pp). "
    "Tagged v0.3.0, published GitHub Release, updated README.",
    tags=["session_summary"])
ss3.metadata["session_date"] = "2026-03-20"
ss3.metadata["salient_counts"] = {"benchmark_questions": 500, "categories_improved": 6, "pp_gain": 13}

# ---------------------------------------------------------------------------
# Salience / core
# ---------------------------------------------------------------------------
for node, count in [
    (user, 22), (dory_proj, 20), (allergyapp, 16), (local_first, 14),
    (mem_graph, 15), (episodic, 14), (ev4, 12), (benchmarks, 13),
    (ss3, 11), (bl2, 9), (pr3, 10),
]:
    node.activation_count = count

for node in [user, dory_proj, allergyapp, local_first, mem_graph, episodic, ev4, ss3]:
    node.is_core = True

g._recompute_salience()

# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------
# User → projects
g.add_edge(user.id, allergyapp.id, EdgeType.WORKS_ON,  weight=0.9)
g.add_edge(user.id, agent_proj.id, EdgeType.WORKS_ON,  weight=0.8)
g.add_edge(user.id, dory_proj.id,  EdgeType.WORKS_ON,  weight=0.95)
g.add_edge(user.id, pr1.id,        EdgeType.PREFERS,   weight=0.9)
g.add_edge(user.id, pr2.id,        EdgeType.PREFERS,   weight=0.85)
g.add_edge(user.id, pr3.id,        EdgeType.PREFERS,   weight=0.95)
g.add_edge(pr3.id,  local_first.id, EdgeType.CO_OCCURS, weight=0.9)

# Project → tools
g.add_edge(allergyapp.id, giovanni.id,   EdgeType.USES, weight=0.9)
g.add_edge(allergyapp.id, fastapi.id,    EdgeType.USES, weight=0.8)
g.add_edge(allergyapp.id, supabase.id,   EdgeType.USES, weight=0.8)
g.add_edge(allergyapp.id, deploy_proc.id, EdgeType.USES, weight=0.7)
g.add_edge(agent_proj.id, qwen.id,       EdgeType.USES, weight=0.9)
g.add_edge(agent_proj.id, debug_proc.id, EdgeType.USES, weight=0.7)

# Dory → architecture concepts
g.add_edge(dory_proj.id, mem_graph.id,  EdgeType.USES,       weight=0.95)
g.add_edge(dory_proj.id, episodic.id,   EdgeType.USES,       weight=0.9)
g.add_edge(dory_proj.id, decay.id,      EdgeType.USES,       weight=0.85)
g.add_edge(dory_proj.id, benchmarks.id, EdgeType.CO_OCCURS,  weight=0.8)
g.add_edge(mem_graph.id, bl1.id,        EdgeType.SUPPORTS_FACT, weight=0.85)
g.add_edge(decay.id,     bl2.id,        EdgeType.SUPPORTS_FACT, weight=0.8)

# Events → concepts
g.add_edge(ev1.id, dory_proj.id,  EdgeType.CO_OCCURS,   weight=0.8)
g.add_edge(ev2.id, benchmarks.id, EdgeType.SUPPORTS_FACT, weight=0.9)
g.add_edge(ev3.id, episodic.id,   EdgeType.SUPPORTS_FACT, weight=0.9)
g.add_edge(ev4.id, benchmarks.id, EdgeType.SUPPORTS_FACT, weight=0.95)
g.add_edge(ev4.id, dory_proj.id,  EdgeType.CO_OCCURS,   weight=0.9)
g.add_edge(ev5.id, allergyapp.id, EdgeType.CO_OCCURS,   weight=0.9)

# SESSION_SUMMARY → TEMPORALLY_AFTER chain (v0.2 episodic spine)
g.add_edge(ss2.id, ss1.id, EdgeType.TEMPORALLY_AFTER, weight=0.9)
g.add_edge(ss3.id, ss2.id, EdgeType.TEMPORALLY_AFTER, weight=0.9)

# SESSION_SUMMARY → semantic nodes via SUPPORTS_FACT / MENTIONS (v0.2 staged retrieval)
g.add_edge(ss1.id, benchmarks.id, EdgeType.SUPPORTS_FACT, weight=0.85)
g.add_edge(ss1.id, ev2.id,        EdgeType.SUPPORTS_FACT, weight=0.8)
g.add_edge(ss2.id, episodic.id,   EdgeType.SUPPORTS_FACT, weight=0.9)
g.add_edge(ss2.id, ev3.id,        EdgeType.SUPPORTS_FACT, weight=0.85)
g.add_edge(ss3.id, ev4.id,        EdgeType.SUPPORTS_FACT, weight=0.95)
g.add_edge(ss3.id, dory_proj.id,  EdgeType.MENTIONS,      weight=0.8)
g.add_edge(ss3.id, benchmarks.id, EdgeType.MENTIONS,      weight=0.8)

# SESSION → SESSION_SUMMARY (raw → compressed)
g.add_edge(s1.id, ss1.id, EdgeType.SUPPORTS_FACT, weight=0.7)
g.add_edge(s2.id, ss2.id, EdgeType.SUPPORTS_FACT, weight=0.7)
g.add_edge(s3.id, ss3.id, EdgeType.SUPPORTS_FACT, weight=0.7)

# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
out = Path(__file__).parent.parent / "docs" / "demo.html"
out.parent.mkdir(parents=True, exist_ok=True)

path = visualize.open_visualization(g, output_path=out, open_browser=True)
print(f"Demo written to: {path}")
