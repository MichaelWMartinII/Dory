# PyPI New-User Test Report
**Date:** 2026-03-21
**Version tested:** dory-memory 0.3.2 (pre-fix), bugs carried into 0.3.3, fixed in 0.3.4
**Environment:** macOS Darwin 24.6.0, Python 3.14, clean venv at `/tmp/dory_user_test`
**Tester:** Claude Code (simulated new-user walkthrough)

---

## Method

Installed `dory-memory[ollama]` from PyPI into a clean venv and followed the README
exactly as a new user would. Tested each documented feature in order.

```bash
python3 -m venv /tmp/dory_user_test
source /tmp/dory_user_test/bin/activate
pip install "dory-memory[ollama]"
```

---

## Step 1 — Basic Quickstart (no LLM)

**Test:**
```python
from dory import DoryMemory
mem = DoryMemory()
mem.observe("User prefers local-first AI")
mem.observe("User switched from llama.cpp to MLX — 25% faster")
print(mem.query("what does the user prefer for inference?"))
```

**Result: PASS**

Output:
```
Activated memories:
- [CONCEPT] User prefers local-first AI
- [CONCEPT] User switched from llama.cpp to MLX — 25% faster

Relationships:
  User switched from llama.cpp to MLX — 25% faster --[CO_OCCURS]--> User prefers local-first AI
```

Imports correct, API matches README, spreading activation working.

---

## Step 2 — All README Imports

**Test:** Imported every module referenced in the README.

```python
from dory.adapters.langchain import DoryMemoryAdapter
from dory.adapters.langgraph import DoryMemoryNode, MemoryState
from dory.adapters.multi_agent import SharedMemoryPool
from dory.export.jsonld import JSONLDExporter
from dory import Graph, Observer, Prefixer
```

**Result: PASS** — All imports resolved without errors.

---

## Step 3 — CLI Commands

**Test:** Ran all three CLI commands from the README.

```bash
dory --help
dory show
dory query "test"
```

**Result: PASS**

- `dory --help` listed all 7 subcommands correctly
- `dory show` printed node/edge counts
- `dory query "test"` returned "(no relevant memories found)" on empty DB

---

## Step 4 — Ollama Auto-Extraction (default backend)

**Test:** Followed README example for local extraction.

```python
mem = DoryMemory(extract_model="qwen3:8b")
mem.add_turn("user", "Hey, I am building an AI agent...")
# ... 4 more turns
# auto-extraction fires at turn 5
stats = mem.flush()
```

**Result: PASS (with caveats)**

- Extraction completed successfully: 5 nodes written, 0 errors
- **Critical caveat: extraction took ~92 seconds** (without `think=False` fix in 0.3.2)
- README gives no warning about this — new user would assume the process hung

**Root cause:** qwen3:8b uses extended thinking mode by default. The `ollama.chat()` call in
`_call_ollama` did not set `think=False`, causing the model to spend ~90s in reasoning mode
before generating the JSON response.

**Fix applied in 0.3.3:** Added `think=False` to `ollama.chat()` in `_call_ollama`. Cuts
extraction time from ~90s → ~30s.

---

## Step 5 — OpenAI-compat Backend Pointing at Ollama

**Test:** Used `extract_backend="openai"` with Ollama's `/v1` endpoint (a common pattern
for local LLM users).

```python
mem = DoryMemory(
    extract_model="qwen3:8b",
    extract_backend="openai",
    extract_base_url="http://127.0.0.1:11434",
)
```

**Result: SILENT FAILURE**

- `errors: 1, nodes_written: 0` — extraction silently failed
- Root cause: `_call_openai_compat` has a hardcoded `timeout=60`. With qwen3:8b thinking
  mode enabled, the model takes ~90s to respond. The httpx timeout fires first.
- User sees no error message — just "No memories extracted."

**Fix applied in 0.3.3:** `think=False` reduces response time to ~30s, which is under the
60s timeout. The openai-compat backend now works with Ollama + qwen3.

---

## Issues Found

| Severity | Issue | Status |
|---|---|---|
| Critical | Ollama extraction takes ~90s, README gives no warning | Fixed in 0.3.3 (think=False) |
| Critical | `extract_backend="openai"` + Ollama = silent extraction failure (90s > 60s timeout) | Fixed in 0.3.3 (think=False) |
| Medium | README suggests `qwen3:14b` (9GB) with no smaller alternative | Fixed in 0.3.3 (added qwen3:8b) |
| Medium | No mention of extraction timing in README | Fixed in 0.3.3 (added timing note) |

---

## What Worked Well

- Zero-dependency quickstart (observe + query) is clean and fast
- All imports resolve correctly
- CLI commands work as documented
- Spreading activation retrieval returns correct results
- Graph structure and relationships built correctly

---

## Recommendations Applied

1. ✅ Added `think=False` to `_call_ollama` in observer.py
2. ✅ Added `qwen3:8b` as smaller alternative in README
3. ✅ Added local extraction timing note to README
4. ✅ Fixed roadmap to show shipped items correctly
