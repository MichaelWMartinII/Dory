# Dory v0.5 Session Changes
**Date:** 2026-03-26 | **Author:** Claude Sonnet 4.6

Three independent improvements made in this session. All changes are tested (175/175 passing).
No version bump yet — these are staged for v0.5.

---

## 1. Fix: `--bare` Flag Removed from `claude -p`

**File:** `benchmarks/longmemeval.py`
**Functions:** `_answer_claude_code()`, `_answer_claude_code_mcp()`

### What changed
Removed `--bare` from all `claude -p` subprocess calls. Prompt is now passed via
`input=` (stdin) instead of as a positional argument.

### Why
`--bare` forces `ANTHROPIC_API_KEY` auth, bypassing subscription OAuth. The v0.4.0
full 500-question run cost ~$35 because of this. Without `--bare`, `claude -p` reads
the prompt from stdin and routes through subscription capacity — $0 for benchmark runs.

Root cause of original issue: without `--bare`, the positional argument is NOT treated
as the prompt — it's interpreted as a file path, causing errors. Switching to `input=`
fixes both the auth issue and the argument parsing issue.

### How to revert
If `--bare` behavior is needed again, add `"--bare"` back to the subprocess args list
and change `input=question` back to appending `question` as the last positional arg.

### Tested by
3-question live smoke test — all 3 hypotheses non-empty, 0 errors, exit 0.

---

## 2. Temporal Date-Anchoring

**File:** `benchmarks/longmemeval.py`
**Functions:** `_answer_claude_code_mcp()`, `_MCP_TYPE_HINTS`

### What changed

**System prompt structure:**
```
Before: "...{type_hint} Today's date is {question_date}. Give a short, direct answer."
After:  "REFERENCE DATE: {question_date}\n\n...{type_hint} Give a short, direct answer."
```

The date is now on its own line at the TOP of the system prompt, labeled `REFERENCE DATE`,
instead of buried at the end of a long sentence.

**Temporal type hint:**
```
Before: "This question is about timing or ordering of events. Use date prefixes in
         memories to calculate exact differences."

After:  "This question is about timing, ordering, or counting events. Use date prefixes
         in memories to calculate exact differences. Count days INCLUSIVELY — both start
         and end dates count (e.g. Nov 18 to Nov 24 = 7 days: 18,19,20,21,22,23,24).
         Always use the REFERENCE DATE shown above for any relative calculations
         ("X months ago", "last week", etc.) — do not infer or guess today's date."
```

### Why
The v0.4.0 failure analysis identified two major temporal failure patterns:
- **Off-by-one counting (~12/37 failures):** LongMemEval counts both endpoints inclusively
  (Nov 18 to Nov 24 = 7, not 6). The model was computing exclusive differences.
- **Relative date resolution (~10/37 failures):** "How many months ago did I...?" — model
  recalculated from inferred "now" instead of anchoring to `question_date`.

Both are addressed directly. Estimated impact: +2-4pts on temporal category.

### How to revert
Revert `_MCP_TYPE_HINTS["temporal-reasoning"]` and the `system_prompt` construction
in `_answer_claude_code_mcp()` to their previous string values.

### Note
This only affects the `claude-code-mcp` backend. Other backends use `_get_prompt()`
which already prepends `"Today's date: {question_date}"` to the context string.

---

## 3. Karpathy Fix: Salience Calibration + Memory Framing

**Files:** `dory/pipeline/observer.py`, `benchmarks/longmemeval.py`, `dory/mcp_server.py`

### Problem
Andrej Karpathy's complaint (2026-03-26): single low-signal interactions persist with
the same weight as deeply-confirmed preferences. Models "try too hard" with whatever
is injected into context — a training artifact, not a retrieval bug.

Two-part fix:

---

### Part A: Confidence-Seeded Activation Count

**File:** `dory/pipeline/observer.py`, `Observer._write()`

**What changed:** After creating a new node, its `activation_count` is seeded from
the extraction confidence instead of defaulting to 0:

```python
node.activation_count = 3   # confidence >= 0.95 (strong explicit statement)
node.activation_count = 2   # confidence >= 0.85 (clear statement)
node.activation_count = 1   # confidence >= 0.70 (just above floor, weak signal)
```

Also writes `node.metadata["signal_strength"]` = `"strong"` / `"moderate"` / `"weak"`.

**Why it matters:** Salience is computed as:
```
0.3 × connectivity + 0.4 × log(activation_count) + 0.3 × recency
```

With `activation_count=0`, the reinforcement term is always 0 for all new nodes —
a one-off mention has the same salience as a repeatedly-confirmed preference.
Seeding from confidence means:
- A single vague mention (confidence=0.72) starts with `activation_count=1` → decays
  quickly if never reinforced again
- An explicit strong statement (confidence=0.95) starts with `activation_count=3` →
  survives decay longer and needs less reinforcement

**How to revert:** Remove the 12-line block after `content_to_id[content] = node_id`
in `Observer._write()` (the block that checks `if node is not None` and sets
`node.activation_count` and `node.metadata["signal_strength"]`).

---

### Part B: Memory Framing as Hints

**Files:** `benchmarks/longmemeval.py`, `dory/mcp_server.py`

**What changed:**

In `_answer_claude_code_mcp()` system prompt:
```
Before: "...Call dory_query with relevant search terms to retrieve memories, then
         answer the question based on what you find..."

After:  "...Call dory_query with relevant search terms to retrieve relevant memories.
         Treat retrieved memories as contextual hints — reference them when genuinely
         relevant to the question, but use your judgment. Do not force memories into
         the answer if they don't naturally apply..."
```

In `dory/mcp_server.py`, `dory_query` docstring:
```
Added: "Retrieved memories are contextual hints ranked by relevance and recency.
        Use your judgment about which memories apply to the current question —
        not every retrieved memory needs to be referenced in your response."
```

**Why:** The training artifact Karpathy describes — models treating all injected context
as authoritative — can't be fully fixed from the retrieval side. But the framing of the
tool docstring and system prompt shapes how the model interprets retrieved content.
"Contextual hints" vs "memories based on what you find" changes the epistemic stance:
the model is more likely to evaluate relevance rather than reflexively citing everything.

**How to revert:** Revert the system_prompt string in `_answer_claude_code_mcp()` and
the docstring in `dory/mcp_server.py` to their previous values.

---

## 4. Observer Async Extraction

**File:** `dory/pipeline/observer.py`

### What changed
Observer now submits LLM extraction calls to a `ThreadPoolExecutor(max_workers=2)` so
`add_turn()` returns immediately instead of blocking on the LLM call.

**New fields on Observer:**
- `self._executor`: `ThreadPoolExecutor(max_workers=2, thread_name_prefix="dory_obs")`
- `self._write_lock`: `threading.Lock()` — serializes graph writes
- `self._pending`: `list[Future]` — tracks in-flight extractions
- `self._pending_lock`: `threading.Lock()` — protects `_pending` list

**New public methods:**
- `Observer.close()` — shuts down the thread pool. Safe to call multiple times.
- `Observer.__del__()` — calls `close()` on garbage collection.

**Changed behavior:**
- `add_turn()`: when buffer hits threshold, snapshots the buffer, clears it immediately,
  and submits `_run_extract(buffer_snapshot)` to the thread pool. Returns without waiting.
- `flush()`: submits remaining buffer (if any) to thread pool, then calls
  `future.result(timeout=300)` on all pending futures before `graph.save()`.
  **This is the synchronization point** — always call `flush()` at end of session.
- `_extract()` replaced by `_run_extract(buffer_snapshot, session_date="")`:
  takes an explicit buffer snapshot, runs LLM call, acquires `_write_lock`, writes to graph.

**Thread safety design:**
- LLM calls (`_call_llm`) run in parallel across workers — the expensive part.
- Graph writes (`_write`) are serialized via `_write_lock` — cheap and fast.
- `graph.add_node()` / `graph.add_edge()` have their own `RLock` — safe from multiple threads,
  but `_write_lock` prevents two `_write()` calls from racing on `content_to_id` mapping.
- SQLite store: per-thread connections, WAL mode — reads don't block writers.

### Why
LLM extraction dominates session processing time. With synchronous extraction,
every N turns blocked the session for the duration of an LLM call (~5-15s).
With async extraction, that latency is hidden behind subsequent session processing.
Expected impact: cuts effective per-question time from ~61s toward ~30s.

### Important usage note
`flush()` **must** be called at end of session. This is unchanged from before —
the difference is `flush()` now also waits for in-flight thread pool futures.
Code that already called `flush()` requires no changes.

### Test changes
`tests/test_observer.py`: added `obs.flush()` inside `with patch(...)` blocks for
all tests that trigger extraction via `add_turn()` and then assert on graph state.
This is required because extraction is now async — `add_turn()` returns before the
LLM mock is called, so the patch context must remain active when `flush()` drains
the thread pool.

### How to revert
This is the most invasive change. To revert:
1. Remove `import concurrent.futures` and `import threading` from top of observer.py
2. Remove `_executor`, `_write_lock`, `_pending`, `_pending_lock` from `__init__`
3. Remove `close()` and `__del__` methods
4. Replace `_run_extract()` with the original `_extract()`:
   ```python
   def _extract(self, session_date: str = "") -> None:
       if not self._buffer:
           return
       turns_text = "\n".join(f"{t['role'].upper()}: {t['content']}" for t in self._buffer)
       self._buffer = []
       self._stats["extractions_run"] += 1
       raw = self._call_llm(turns_text, session_date=session_date)
       if not raw or "_error" in raw:
           self._stats["errors"] += 1
           return
       self._write(raw)
       if self.infer_implicit and raw.get("nodes"):
           implicit = self._infer_implicit_preferences(raw["nodes"])
           if implicit:
               self._write({"nodes": implicit, "edges": []})
               self._stats["implicit_inferred"] += len(implicit)
   ```
5. Restore `add_turn()` to call `self._extract()` directly
6. Restore `flush()` to call `self._extract(session_date=session_date)` then `self.graph.save()`
7. Revert test changes: remove `obs.flush()` calls added inside `with patch(...)` blocks

---

## Test Results

```
175 passed in 0.72s  (full suite, excluding live integration tests)
```

Benchmark smoke test (3 questions, claude-code-mcp backend):
- 0 errors
- All hypotheses non-empty
- Total time: 43s (vs ~52s before —bare fix; async benefit will show at scale)
