"""
Dory quickstart — run this after `pip install dory-memory`.

No external dependencies required. Uses manual observations (no LLM extraction).
After running, your graph opens in the browser.

To add auto-extraction from conversation turns, swap in:
    mem = DoryMemory(extract_model="claude-haiku-4-5-20251001",
                     extract_backend="anthropic", extract_api_key="sk-ant-...")
"""

from dory import DoryMemory

# Create memory (defaults to ./engram.db)
mem = DoryMemory()

# Add some memories manually
mem.observe("Alice is a backend engineer focused on payments infrastructure", node_type="ENTITY")
mem.observe("The team is migrating from Stripe to a custom payment processor", node_type="EVENT")
mem.observe("Alice prefers async Python over synchronous frameworks", node_type="PREFERENCE")
mem.observe("FastAPI is the web framework for the payments service", node_type="CONCEPT")
mem.observe("The migration deadline is end of Q2", node_type="EVENT")
mem.observe("Alice is concerned about webhook reliability during the cutover", node_type="BELIEF")

# Query — see what context Dory would inject for a given topic
print("--- Context for 'payment migration' ---")
print(mem.query("payment migration"))

# Run consolidation (decay, dedup, core promotion)
stats = mem.flush()
print(f"\n--- Flush stats ---")
print(f"Core memories promoted: {stats.get('promoted_core', 0)}")

# Open the graph in your browser
print("\nOpening graph visualization...")
mem.visualize()
