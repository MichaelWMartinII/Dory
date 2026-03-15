#!/usr/bin/env python3
"""
Seed the Engram graph with known facts about /Users/michael/Repo.
Run once to bootstrap the graph. Safe to re-run — duplicate edges are reinforced.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dory.graph import Graph
from dory.schema import NodeType, EdgeType

g = Graph()


def _n(node_type: NodeType, content: str, tags: list[str] | None = None):
    """Find existing node by exact content match, or create a new one."""
    for node in g.all_nodes(zone=None):
        if node.type == node_type and node.content == content:
            return node
    return _n(node_type, content, tags=tags or [])


print("Seeding Engram graph...")

# ── People ────────────────────────────────────────────────────────────────────

michael = _n(NodeType.ENTITY, "Michael Martin", tags=["person", "owner"])
print(f"  {michael.id}  Michael Martin")

# ── Projects ──────────────────────────────────────────────────────────────────

agent = _n(NodeType.ENTITY, "Agent", tags=["project", "ai", "local-llm", "python"])
clanker = _n(NodeType.ENTITY, "Clanker", tags=["project", "ai", "local-llm", "python", "rag"])
allergy = _n(NodeType.ENTITY, "AllergyFind", tags=["project", "saas", "fastapi", "python", "business"])
ferrobot = _n(NodeType.ENTITY, "FerroBot", tags=["project", "simulation", "physics", "python"])
engram = _n(NodeType.ENTITY, "Engram", tags=["project", "memory", "graph", "python"])
portfolio = _n(NodeType.ENTITY, "portfolio", tags=["project", "nextjs", "typescript", "react"])
socials = _n(NodeType.ENTITY, "Socials", tags=["project", "ai", "claude", "python", "cli"])
weathermap = _n(NodeType.ENTITY, "WeatherMap", tags=["project", "pwa", "javascript", "leaflet"])

print(f"  {agent.id}  Agent")
print(f"  {clanker.id}  Clanker")
print(f"  {allergy.id}  AllergyFind")
print(f"  {ferrobot.id}  FerroBot")
print(f"  {engram.id}  Engram")
print(f"  {portfolio.id}  portfolio")
print(f"  {socials.id}  Socials")
print(f"  {weathermap.id}  WeatherMap")

# ── Technologies ──────────────────────────────────────────────────────────────

fastapi = _n(NodeType.CONCEPT, "FastAPI", tags=["framework", "python", "web"])
postgres = _n(NodeType.CONCEPT, "PostgreSQL", tags=["database", "sql"])
supabase = _n(NodeType.CONCEPT, "Supabase", tags=["database", "postgres", "hosted"])
nextjs = _n(NodeType.CONCEPT, "Next.js", tags=["framework", "react", "typescript"])
llamacpp = _n(NodeType.CONCEPT, "llama.cpp", tags=["local-llm", "inference", "c++"])
chromadb = _n(NodeType.CONCEPT, "ChromaDB", tags=["vector-db", "rag", "embeddings"])
sqlite = _n(NodeType.CONCEPT, "SQLite", tags=["database", "local"])
mlx = _n(NodeType.CONCEPT, "MLX", tags=["apple-silicon", "inference", "framework"])
anthropic_api = _n(NodeType.CONCEPT, "Anthropic API", tags=["api", "claude", "cloud"])
local_llm = _n(NodeType.CONCEPT, "local-first AI", tags=["architecture", "privacy", "no-cloud"])
qwen = _n(NodeType.CONCEPT, "Qwen models", tags=["llm", "alibaba", "open-source"])
spreading_activation = _n(NodeType.CONCEPT, "spreading activation", tags=["memory", "graph", "retrieval", "collins-loftus"])

print(f"  {fastapi.id}  FastAPI")
print(f"  {local_llm.id}  local-first AI")

# ── Preferences ───────────────────────────────────────────────────────────────

pref_local = _n(NodeType.PREFERENCE, "Prefers local-first, no cloud AI where possible", tags=["architecture"])
pref_license = _n(NodeType.PREFERENCE, "Prefers Apache 2.0 licensed models", tags=["licensing"])
pref_privacy = _n(NodeType.PREFERENCE, "Values privacy — data stays on device", tags=["privacy"])
pref_mlx = _n(NodeType.PREFERENCE, "Use MLX over llama.cpp on Apple Silicon (20-30% faster)", tags=["performance", "apple-silicon"])
pref_qwen = _n(NodeType.PREFERENCE, "Uses Qwen3-14B-Q4_K_M as primary local model", tags=["llm", "local"])

print(f"  {pref_local.id}  Preference: local-first")
print(f"  {pref_license.id}  Preference: Apache 2.0")

# ── Beliefs / Architecture decisions ─────────────────────────────────────────

belief_flatfile = _n(NodeType.BELIEF, "Flat file memory has no topology, no emergence — Engram solves this", tags=["memory", "architecture"])
belief_gap = _n(NodeType.BELIEF, "Open/closed LLM gap is now ~2% — open models viable for most tasks", tags=["llm", "open-source"])
belief_chinese = _n(NodeType.BELIEF, "Chinese labs (Qwen, DeepSeek, MiniMax, Kimi) now dominate open-source frontier", tags=["llm", "open-source"])
belief_meta = _n(NodeType.BELIEF, "Meta may go closed-source with Avocado — Llama 4 may be last open Llama", tags=["llm", "meta", "open-source"])
belief_moe = _n(NodeType.BELIEF, "MoE architecture: total params ≠ inference cost, only active params matter", tags=["llm", "architecture", "moe"])

print(f"  {belief_gap.id}  Belief: open/closed gap")

# ── Key facts / Events ────────────────────────────────────────────────────────

giovanni = _n(NodeType.ENTITY, "Giovanni Ristorante Nashville", tags=["customer", "allergyfind", "restaurant"])
murfreesboro = _n(NodeType.ENTITY, "Murfreesboro, TN", tags=["location"])
elwin = _n(NodeType.ENTITY, "Elwin Ransom", tags=["agent", "ai-companion", "name"])
deepseek_v4 = _n(NodeType.EVENT, "DeepSeek V4 expected March 2026 — worth waiting for as fine-tune base", tags=["llm", "deepseek", "upcoming"])
fine_tune_plan = _n(NodeType.CONCEPT, "Fine-tune coding model on Lambda Labs, run quantized locally", tags=["plan", "lambda-labs", "fine-tuning"])
best_local_coding = _n(NodeType.CONCEPT, "Qwen3-Coder-Next (80B/3B active) best local coding agent on 64GB Apple Silicon", tags=["local-llm", "coding", "recommendation"])
best_local_reasoning = _n(NodeType.CONCEPT, "QwQ-32B best local reasoning model — rivals DeepSeek R1 at 1/20th size", tags=["local-llm", "reasoning", "recommendation"])

print(f"  {giovanni.id}  Giovanni Ristorante (AllergyFind customer)")
print(f"  {elwin.id}  Elwin Ransom (Agent name)")

# ── Edges ─────────────────────────────────────────────────────────────────────

print("\nBuilding edges...")

# Michael's projects
g.add_edge(michael.id, agent.id, EdgeType.WORKS_ON)
g.add_edge(michael.id, clanker.id, EdgeType.WORKS_ON)
g.add_edge(michael.id, allergy.id, EdgeType.WORKS_ON)
g.add_edge(michael.id, ferrobot.id, EdgeType.WORKS_ON)
g.add_edge(michael.id, engram.id, EdgeType.WORKS_ON)
g.add_edge(michael.id, portfolio.id, EdgeType.WORKS_ON)
g.add_edge(michael.id, socials.id, EdgeType.WORKS_ON)
g.add_edge(michael.id, weathermap.id, EdgeType.WORKS_ON)
g.add_edge(michael.id, murfreesboro.id, EdgeType.RELATED_TO)

# Preferences
g.add_edge(michael.id, pref_local.id, EdgeType.PREFERS)
g.add_edge(michael.id, pref_license.id, EdgeType.PREFERS)
g.add_edge(michael.id, pref_privacy.id, EdgeType.PREFERS)
g.add_edge(michael.id, pref_mlx.id, EdgeType.PREFERS)
g.add_edge(michael.id, pref_qwen.id, EdgeType.PREFERS)

# Agent internals
g.add_edge(agent.id, llamacpp.id, EdgeType.USES)
g.add_edge(agent.id, sqlite.id, EdgeType.USES)
g.add_edge(agent.id, qwen.id, EdgeType.USES)
g.add_edge(agent.id, local_llm.id, EdgeType.INSTANCE_OF)
g.add_edge(agent.id, elwin.id, EdgeType.RELATED_TO)

# Clanker internals
g.add_edge(clanker.id, llamacpp.id, EdgeType.USES)
g.add_edge(clanker.id, chromadb.id, EdgeType.USES)
g.add_edge(clanker.id, fastapi.id, EdgeType.USES)
g.add_edge(clanker.id, local_llm.id, EdgeType.INSTANCE_OF)

# AllergyFind internals
g.add_edge(allergy.id, fastapi.id, EdgeType.USES)
g.add_edge(allergy.id, postgres.id, EdgeType.USES)
g.add_edge(allergy.id, supabase.id, EdgeType.USES)
g.add_edge(allergy.id, giovanni.id, EdgeType.RELATED_TO)

# Portfolio
g.add_edge(portfolio.id, nextjs.id, EdgeType.USES)

# Socials uses Anthropic
g.add_edge(socials.id, anthropic_api.id, EdgeType.USES)

# Engram architecture
g.add_edge(engram.id, spreading_activation.id, EdgeType.USES)
g.add_edge(engram.id, belief_flatfile.id, EdgeType.CAUSED)
g.add_edge(engram.id, sqlite.id, EdgeType.RELATED_TO)

# LLM landscape
g.add_edge(fine_tune_plan.id, qwen.id, EdgeType.RELATED_TO)
g.add_edge(fine_tune_plan.id, deepseek_v4.id, EdgeType.RELATED_TO)
g.add_edge(best_local_coding.id, local_llm.id, EdgeType.INSTANCE_OF)
g.add_edge(best_local_reasoning.id, local_llm.id, EdgeType.INSTANCE_OF)
g.add_edge(pref_mlx.id, mlx.id, EdgeType.RELATED_TO)

# Beliefs — LLM landscape
g.add_edge(belief_gap.id, local_llm.id, EdgeType.RELATED_TO)
g.add_edge(belief_gap.id, qwen.id, EdgeType.RELATED_TO)
g.add_edge(belief_chinese.id, qwen.id, EdgeType.RELATED_TO)
g.add_edge(belief_chinese.id, belief_gap.id, EdgeType.RELATED_TO)
g.add_edge(belief_meta.id, belief_gap.id, EdgeType.RELATED_TO)
g.add_edge(belief_meta.id, local_llm.id, EdgeType.RELATED_TO)
g.add_edge(belief_moe.id, qwen.id, EdgeType.RELATED_TO)
g.add_edge(belief_moe.id, belief_chinese.id, EdgeType.RELATED_TO)

# Consolidate
from dory import consolidation
result = consolidation.run(g)

g.save()

stats = g.stats()
print(f"\nGraph seeded:")
print(f"  Nodes: {stats['nodes']}")
print(f"  Edges: {stats['edges']}")
print(f"  Core:  {stats['core_nodes']}")
print(f"\nGraph saved to: {g.path}")
