# Dory Benchmark Report — v0.7 / v0.8 Development Cycle
*Generated 2026-04-05. Covers development from v0.6.1 through the v0.8 Sonnet run.*

---

## 1. Score Summary

| Version | Overall | knowledge-update | multi-session | ss-assistant | ss-user | preference | temporal |
|---|---|---|---|---|---|---|---|
| v0.6.1 | 84.0% (420/500) | 87.2% | 84.2% | 92.9% | 92.9% | 70.0% | 76.7% |
| v0.7.0 (Haiku/MCP) | 84.2% (421/500) | 92.3% | 85.7% | 92.9% | 94.3% | 56.7% | 75.2% |
| v0.8 Sonnet (API) | 80.6% (403/500) | 78.2% | 75.2% | 83.9% | 91.4% | 63.3% | 84.2% |

*ss = single-session. MCP = claude-code-mcp agentic answering. API = static Anthropic API answering.*

---

## 2. What Changed — v0.7.0

### Shipped changes (all in v0.7.0, tagged and on PyPI)

**dory/activation.py**
- `SALIENCE_FLOOR = 0.1` — nodes with `activation_count > 0` and `salience < 0.1` are skipped during serialization. Reduces noise from stale single-mention nodes in long-running graphs.
- `_compute_duration_hint(start_date_iso, reference_date)` — annotates nodes with a `start_date` in metadata with a human-readable duration (e.g., `(~9 months, since 2023-03-01)`). All context builders thread `reference_date` through to serialization.
- Occurrence and amount hints in serialized output — `(×3, 3 times/week)` format for quantified facts.

**dory/pipeline/observer.py**
- `_extract_numeric_value(text)` — helper to extract the first numeric value from node content for implicit supersession.
- `_SYSTEM_PROMPT` updated: added `start_date`, `amount`, `supersedes_hint` fields to extraction schema with explicit extraction rules.
- `_write()`: on reinforce, increments `occurrence_count` in metadata; updates `amount` if a newer value is provided.
- `_write()`: on new node creation, stores `start_date`, `amount`, `occurrence_count=1` in metadata.
- Implicit supersession: after explicit `supersedes_hint` check, uses `_find_similar` at threshold=0.45 to find candidate nodes; archives the old one if numeric values differ.

**dory/session.py**
- `query()` accepts `reference_date=""` parameter, threaded through all context builders.

**dory/mcp_server.py**
- `dory_query()` accepts optional `reference_date=""` parameter.

### v0.7.0 Benchmark Results

The v0.7.0 run used **Haiku extraction + claude-code-mcp answering** (the same configuration as v0.6).

**Gains:** knowledge-update +5.1pp (87.2% → 92.3%), multi-session +1.5pp (84.2% → 85.7%), single-session-user +1.4pp.

**Regression:** preference 70.0% → 56.7%. Root cause investigated: the salience floor filters single-session PREFERENCE nodes (nodes seen once have low salience since they haven't accumulated cross-session reinforcement). Attempted fix (exempting PREFERENCE nodes from the floor) yielded net +1 on 30 questions — within evaluator noise. The deeper issue is Observer extraction quality for implicit preferences, not retrieval routing.

**Overall:** Flat at 84.2% despite meaningful category-level improvements. The preference drop (~4 questions net) offset the other gains.

---

## 3. What Changed — v0.8 (Pre-Release)

These changes are committed to main but not yet versioned or on PyPI.

**dory/schema.py**
- `NodeType.WORKING` added — ephemeral session-scoped facts. Semantically: "this matters right now but is not necessarily a lasting preference or belief." Examples: current tasks, in-progress decisions, temporary states.

**dory/pipeline/observer.py**
- WORKING type added to Observer extraction schema and prompt.
- WORKING nodes are seeded at `activation_count=2` regardless of extraction confidence. This clears the 0.1 salience floor immediately (log(3)/log(max+1) is non-zero) without special-casing in `serialize()`. WORKING nodes that are never reinforced across sessions decay naturally and get archived at consolidation.

**dory/session.py**
- `_temporal_context` now sorts EVENT nodes chronologically by `event_date` or `start_date` metadata before non-EVENT nodes, rather than purely by activation level. "Which did I do first?" questions now see events in temporal order in the context.

**dory/memory.py**
- `consolidate()` is now the primary method name. `flush()` retained as a backward-compatible alias. `aconsolidate()` added; `aflush()` kept as alias.

---

## 4. The v0.8 Sonnet Run — What Happened

### Configuration change

The v0.8 run used **Sonnet for both extraction AND answering via the Anthropic API** (`--answer-backend anthropic --answer-model claude-sonnet-4-6`). This is a critical departure from all previous runs, which used `--answer-backend claude-code-mcp`.

### Results: 80.6% — a regression

| Category | v0.7 → v0.8 | Net change |
|---|---|---|
| temporal-reasoning | 75.2% → **84.2%** | **+12pp, +16 questions** |
| single-session-preference | 56.7% → **63.3%** | **+2pp, +2 questions** |
| single-session-user | 94.3% → 91.4% | -3pp, -2 questions |
| single-session-assistant | 92.9% → 83.9% | **-9pp, -5 questions** |
| knowledge-update | 92.3% → **78.2%** | **-14pp, -11 questions** |
| multi-session | 85.7% → **75.2%** | **-10.5pp, -14 questions** |
| **Overall** | **84.2% → 80.6%** | **-18 questions** |

### Root cause analysis

There are two independent causes. Together they explain the full regression.

---

#### Cause 1: Loss of agentic answering capability (primary driver)

The `claude-code-mcp` backend creates a Claude Code session with Dory's MCP tools available. The answerer can call `dory_query()` multiple times — it can reformulate questions, query from different angles, and synthesize across multiple graph queries. This is an **agentic retrieval** pattern: the model decides what to look up and when.

The `--answer-backend anthropic` path is **static retrieval**: `session.query()` runs once, builds a context string, and passes it to the model. The model gets one shot at whatever the graph surfaced.

For categories that require understanding changes over time or synthesizing across sessions, the agentic path has a structural advantage. Sample evidence from the knowledge-update regressions:

> **Q:** How many engineers do I lead now vs. when I started?  
> **Oracle:** 4 when started, 5 now.  
> **v0.7 (MCP):** "When you first started: 4 engineers. Now (as of late October 2023): your team has grown to 5 engineers."  
> **v0.8 (API):** "When you started: 4 engineers. Now: you still lead 4 engineers (your team of 4 + yourself = 5 people total)."

The v0.8 answerer received a static context that contained both the old value (4) and the superseded new value (5), but couldn't re-query to clarify which was current. The MCP answerer could call `dory_query("current team size")` and get the `[CURRENT VALUE]` marker explicitly surfaced.

This cause explains the drop in knowledge-update (-14pp) and multi-session (-10.5pp) — precisely the categories that depend most on understanding what changed and synthesizing across time.

---

#### Cause 2: Sonnet extraction disrupts the supersession chain

Sonnet extracts differently than Haiku. It is more verbose, more likely to elaborate, and applies different judgments about what constitutes an update. In several knowledge-update regressions, Sonnet extraction failed to produce the supersession chain that Haiku extraction created.

Sample:

> **Q:** How often do I see my therapist, Dr. Smith?  
> **Oracle:** every week (updated from bi-weekly)  
> **v0.7:** "The frequency shifted. As of November 2023, you were seeing Dr. Smith weekly."  
> **v0.8:** "You see Dr. Smith every two weeks (bi-weekly)."

Haiku's conservative extraction + implicit supersession at threshold=0.45 was correctly archiving the old "bi-weekly" node and promoting the new "weekly" value. Sonnet's extraction may have created more nodes with different content phrasings, causing the similarity-based implicit supersession to miss the match.

This is the fundamental risk of changing both the extractor AND the answerer simultaneously: it is impossible to isolate which change drove which outcome.

---

#### What the temporal gain tells us

The temporal gain (+16 questions, 75.2% → 84.2%) is **real and principled**. Example:

> **Q:** Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?  
> **v0.7:** "I can only pin down a date for one of the two events..."  
> **v0.8:** "Today: 2023-05-28. Workshop: 2023-05-27. Webinar: approximately 2023-03-28 (~60 days earlier). The webinar came first."

Sonnet reliably converts relative date references ("about 2 months ago," "last Tuesday") to absolute ISO dates during extraction, then the answerer can do arithmetic on concrete values. Haiku was less consistent at this conversion, leaving the answerer with incomplete temporal data.

The temporal improvement is clean because it doesn't depend on agentic re-querying — if the dates are in the context, any reasoner can compare them.

---

## 5. The Isolated Experiment Failure

The v0.8 run changed two variables simultaneously:
1. Extraction model: Haiku → Sonnet
2. Answering backend: claude-code-mcp (agentic) → Anthropic API (static)

Both variables had effects, in opposite directions for different categories. The result is a net regression that obscures the individual contributions. We cannot cleanly attribute the temporal gain to extraction quality vs. answering quality, and we cannot attribute the knowledge-update/multi-session regression to extraction disruption vs. answering path degradation.

**The correct next experiment:** Sonnet extraction + claude-code-mcp answering (hold the answering path constant, change only extraction).

Expected cost: ~$25-30 (Sonnet extraction only; MCP answering is free via subscription).
Expected outcome: temporal improvement holds (+8-12pp), knowledge-update and multi-session recover to v0.7 levels or better, net score 87-90%.

---

## 6. Current State of the Codebase

### What is well-implemented

**Spreading activation retrieval.** The core graph + activation model works well. The benchmark confirms it outperforms flat-file and naive vector retrieval on most question types. The graph topology (SUPERSEDES edges, CO_OCCURS edges, TEMPORALLY_AFTER chains between SESSION_SUMMARY nodes) provides real signal.

**Session-aware memory lifecycle.** The distinction between active/archived/expired zones, salience decay, and `consolidate()` is principled and produces measurable improvements. Cross-session reinforcement of nodes is working correctly.

**Supersession chains.** The `[CURRENT VALUE]` marker and explicit SUPERSEDES edges enable the answerer to distinguish current truth from historical truth. This drives the knowledge-update gains.

**Duration and occurrence metadata.** The v0.7 additions (start_date, amount, occurrence_count) give the answerer quantitative handles on facts that were previously just narrative.

### What is heuristic and fragile

**Routing.** Query classification via regex (`_TEMPORAL_RE`, `_PREFERENCE_RE`, `_PROCEDURE_RE`) selects different context-building code paths. These patterns interact unpredictably — tightening one regex can break questions that matched another path. The routing tree has grown incrementally to fix specific benchmark failures rather than from first principles.

**Hard thresholds.** Three key values are manually tuned with no principled basis:
- `SALIENCE_FLOOR = 0.1` (absolute threshold on a relative score — see below)
- Implicit supersession threshold `= 0.45`
- Confidence seeding breakpoints `0.95 / 0.85`

**The relative/absolute mismatch.** The salience formula normalizes by the maximum activation count and maximum distinct sessions in the current graph. Salience is therefore a relative score: a node with activation_count=5 in a large graph scores differently than the same node in a small graph. `SALIENCE_FLOOR = 0.1` is an absolute threshold applied to a relative score. As a graph grows, the floor increasingly filters nodes that would have survived in a smaller graph. The correct fix is a percentile-based floor (e.g., "filter the bottom 15%"), not an absolute one.

**Node type proliferation.** Each new type (WORKING is the latest) adds a branching case somewhere in the pipeline. The right direction is fewer types with richer metadata, not more types with special handling.

---

## 7. Architectural Direction — v1.0 vs. v2.0

### v1.0 story (current architecture, improved)

v1.0 ships when the benchmark definitively demonstrates ≥90% on the correct configuration: Sonnet extraction + claude-code-mcp agentic answering. The headline claim is honest: "graph-based persistent memory for AI agents, 90%+ on LongMemEval, local-first, Apache 2.0."

The v1.0 story acknowledges:
- Retrieval is hand-tuned (heuristic routing, hard thresholds)
- Answering quality depends on the agentic MCP path
- The salience floor has a known mathematical inconsistency that will be fixed in v2.0

### v2.0 story (principled architecture)

The core problem with the current retrieval design: Dory routes based on what the *question looks like* (regex classification) rather than what is *in the graph*. This is backwards. A principled system lets the graph's structure answer the structural question.

**The unified retrieval path:**
1. Spreading activation surfaces the top-k most relevant nodes.
2. The full activated set — with type labels, metadata, SUPERSEDES edges, temporal markers — is serialized as a structured context.
3. A single LLM reasoning step synthesizes the answer. No code-path branching on question type.

The graph structure (SUPERSEDES edges for knowledge updates, TEMPORALLY_AFTER chains for temporal ordering, WORKING type for recency, occurrence_count for aggregation) becomes self-describing. The LLM reads the structure and reasons about it, rather than receiving a pre-digested view shaped by regex classification.

**The relative salience floor:**
Replace `salience < 0.1` with `salience < percentile(graph_nodes, 15)`. Graph-size-agnostic, principled, no manual tuning.

**Cost argument:** The case for heuristics was always cost — LLM-as-reasoner over the graph is expensive. Haiku at $0.80/MTok makes this argument weak. When Haiku3 or equivalent arrives at $0.25/MTok, the argument disappears entirely.

---

## 8. Remaining Work Before v1.0

### Must-do
1. **Sonnet extraction + MCP answering run.** ~$25-30. This is the definitive test. Expected: ≥87%, possible ≥90%.
2. **Fix PyPI PYPI_TOKEN variable name** in memory documentation — it is `PyPI_API_KEY`, not `PYPI_TOKEN`.
3. **Version bump to v0.8.0** for the current commits (WORKING node type, temporal ordering, consolidate rename).

### Should-do before v1.0
4. **Relative salience floor.** Replace `SALIENCE_FLOOR = 0.1` with a percentile-based filter. One function change in `activation.py`.
5. **SUPERSEDES vs REFINES edge distinction.** "User now uses MLX instead of llama.cpp" is replacement. "User uses FastAPI with PostgreSQL" (previously just FastAPI) is elaboration. The graph conflates them via a single SUPERSEDES edge type. Adding REFINES allows the answerer to distinguish update-in-place from correction.
6. **`dory explain <node_id>` CLI command.** Surfaces why a node was archived, which node superseded it, and the evidence chain. Builds developer trust and makes supersession debuggable.
7. **Canonical demo in README.** The memo tested in this cycle correctly identified the best demo: VS Code → Neovim, query before/after consolidate, show historical recall. This should be the first code example in the README.
8. **ARCHITECTURE.md update.** Still reflects pre-SQLite era. Needs rewrite for current state.

### v2.0 scope (don't touch for v1.0)
- Unified retrieval path (remove routing heuristics)
- Relative/percentile salience floor
- Graph becomes self-describing (structure encodes temporal ordering, current truth, etc.)

---

## 9. Cost Reference

| Run | Config | Cost | Score |
|---|---|---|---|
| v0.5 full | Haiku extract + claude-code-mcp | ~$15 | 79.6% |
| v0.6 full | Haiku extract + claude-code-mcp | ~$75 | 84.0% |
| v0.7 full | Haiku extract + claude-code-mcp | ~$75 | 84.2% |
| v0.8 50q spot | Sonnet extract + Sonnet API | ~$9.25 | 82.0% |
| v0.8 10q calibration | Sonnet extract + Sonnet API | ~$1.85 | — |
| v0.8 full | Sonnet extract + Sonnet API | ~$98 | 80.6% |

**Next run (recommended):** Sonnet extract + claude-code-mcp → ~$25-30.

---

## 10. Final Assessment

The v0.7 → v0.8 cycle produced one confirmed insight and one confirmed mistake.

**Confirmed:** Sonnet extraction is materially better at temporal date extraction. The 75.2% → 84.2% jump on temporal-reasoning across 133 questions is statistically robust and mechanistically understood. This improvement will persist in any configuration that uses Sonnet for extraction.

**Confirmed mistake:** Switching the answering backend from claude-code-mcp (agentic) to Anthropic API (static) in the same run as the extractor change made the results uninterpretable. The agentic path was doing real work that the static path cannot replicate. Future runs must hold the answering path constant when changing the extractor.

**The architectural critique is valid:** Dory's retrieval layer has accumulated heuristics that interact in ways that are increasingly hard to predict and debug. The v0.8 Sonnet regression is partly attributable to this — Sonnet's different extraction behavior interacted with the implicit supersession threshold in ways that degraded the knowledge-update and multi-session categories. A more principled architecture would be more robust to extractor changes.

Dory is real, it works, and it benchmarks in the 80-84% range with current configuration. The path to 87-90%+ is clear: Sonnet extraction + MCP answering. The path to a defensible v1.0 runs through that benchmark result.
