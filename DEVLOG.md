# Dory — Developer Log
*A technical narrative of how we got here, where we are, and what comes next.*

---

## The Problem That Started This

Every agent framework has the same dirty secret: the agent forgets everything the moment the conversation ends. You can build the most sophisticated RAG pipeline in the world, wire up a dozen tools, prompt-engineer your way to impressive single-session demos — and then the next day, the agent has no idea who you are or what you talked about. You start over. Every. Single. Time.

There are libraries that claim to solve this. Most of them reduce memory to one of two things: a flat list of strings you dump into the context window, or a vector database you run similarity search against. Both of these approaches share the same failure mode: they treat memory as *retrieval* when what you actually need is *reasoning over a graph of related facts with principled forgetting*.

The insight that started Dory: **memory has topology**. "I use FastAPI" and "I'm building AllergyFind" and "AllergyFind is for restaurant allergen management" are not three separate embeddings floating in vector space. They are nodes in a graph, connected, and querying one should surface the others. Flat file memory has no topology, no emergence. A vector store gives you neighbors by semantic distance, which is a rough proxy at best.

The second insight: **forgetting is as important as remembering**. Agents that never forget accumulate stale facts. "I might switch to Postgres" stored six months ago, never reinforced, should decay out of active retrieval. But it shouldn't vanish — it should be archivable, queryable in historical context ("what was true then?"), and surfaceable only if the user asks about it. This is how human memory works. Total recall is not intelligence; selective recall with principled decay is.

The third insight, which came later and hurt more: **injecting memory can actively make things worse**. Chroma's context-rot research (2025) tested all 18 major frontier models and found degradation starting at 500-750 tokens of injected context, becoming substantial past 2500 tokens. Dumping 5,000 tokens of memory into a prompt doesn't help the agent remember — it creates noise that actively degrades reasoning on the facts that matter. Memory must be *selective* and *compact*, not comprehensive.

Dory was an attempt to build the right thing: a spreading-activation knowledge graph with typed edges, principled decay, and compact retrieval. The project had a prior life as `Engram`. It became `dory-memory` on March 10, 2026, when the first version hit PyPI.

---

## v0.1 — The First Release (March 10, 2026)

The v0.1 architecture was conceptually complete even if the numbers weren't there yet:

- **Nodes** with types: ENTITY, CONCEPT, EVENT, PREFERENCE, BELIEF, PROCEDURE, SESSION, SESSION_SUMMARY
- **Edges** with semantics: CO_OCCURS, SUPERSEDES, SUPPORTS_FACT, TEMPORALLY_AFTER
- **Spreading activation retrieval** — start from seed nodes matching the query, propagate relevance through edges with decay, return the activated subgraph
- **Observer pipeline** — LLM-based extraction from raw text into typed nodes
- **Reflector** — cross-session behavioral pattern synthesis
- **Decayer** — salience decay over time and sessions
- **SQLite backend** — FTS5 for keyword search, adjacency tables for the graph, `sqlite-vec` extension for optional vector search
- **MCP server** — five tools: `dory_query`, `dory_observe`, `dory_consolidate`, `dory_stats`, `dory_visualize`
- Adapters for LangChain, LangGraph, and multi-agent frameworks

The first benchmark result against LongMemEval (ICLR 2025) was **66.8%**. That felt bad. The theoretical architecture was sound, the implementation was clean, but 66.8% meant one in three questions was being answered wrong. Real agents would be confidently hallucinating.

The breakdown told the story. Temporal-reasoning questions — "which event came first?" "how long ago did I change jobs?" — were scoring around 46%. The graph was storing the events, but the context wasn't surfacing them in a form that let the answerer do date arithmetic. SESSION nodes existed but weren't being used efficiently. Aggregation questions — "how many plants have I added to my collection?" — were scoring poorly because counting requires enumerating all event mentions across sessions, and the spreading activation was stopping at the most recently active nodes rather than pulling in the full history.

The bones were good. The retrieval was wrong.

---

## v0.2 — The Architecture That Actually Worked (March 19, 2026)

The v0.2 development cycle was the most intellectually dense single session of the project. The benchmark failures were almost all traceable to one root cause: the retrieval context was structurally incomplete for the question types that mattered most.

The changes:

**SESSION_SUMMARY nodes with `salient_counts` metadata.** After each session, the Summarizer creates a compressed narrative node that records what happened *and* counts: how many plants were added, how many books were read, how many miles were run. Previously, "how many plants have I acquired" required activating every individual plant-addition EVENT node. Now it could read the salient count directly from the session summary. The first cross-validate step checked these counts against individual EVENT nodes and flagged low-confidence aggregations.

**`SUPPORTS_FACT` and `MENTIONS` edges.** Bidirectional provenance from SESSION_SUMMARY nodes back to the semantic nodes they ground. Spreading activation can now traverse from a semantic fact to its supporting sessions, or from a session to all the facts it establishes. This is graph topology doing real work.

**`TEMPORALLY_AFTER` / `TEMPORALLY_BEFORE` edges between SESSION_SUMMARY nodes.** A chronological chain. This sounds obvious in retrospect. Before v0.2, sessions were stored in the graph but there was no explicit temporal ordering edge connecting them. The chain meant the context could now tell a temporal story in sequence rather than as an unordered set.

**`_route_query()`.** Deterministic regex-based query classification that selects different retrieval strategies:
- `graph` mode — pure spreading activation, for semantic and entity questions
- `episodic` mode — SESSION_SUMMARY chain injection, for temporal and aggregation questions  
- `hybrid` mode — both, for complex queries spanning multiple sessions

**The aggregation-before-temporal priority bug.** This one took a while to find. In `_aggregation_context()`, SESSION memories were initially placed *before* the semantic block. The model would anchor on the first count it saw — two plants mentioned in a session summary — and report "two" even when there were three EVENT nodes in the graph. The fix was mechanical: move SESSION memories after the semantic block. The model now sees the complete enumeration of events first, then the session summary as corroborating context. A four-line change that recovered several points.

**The `question_date` injection.** Temporal questions in LongMemEval include a "today's date" field that represents when the question is being asked. Previously, this wasn't being threaded into the answer prompt. A question like "how long ago did I change jobs?" was being answered relative to whenever the last session happened, not relative to today. The fix: prepend `REFERENCE DATE: {question_date}` at the top of the context. Every temporal anchor in the graph can now be computed against a fixed reference point.

The v0.2 result: **79.8% (399/500)**. Thirteen percentage points in one session. Temporal-reasoning jumped 29.3pp (46.6% → 75.9%). Multi-session improved 9.8pp. Knowledge-update improved 9pp. No regressions.

More importantly, it now beat Mem0 (68.4%) and Zep (71.2%) on the same benchmark.

---

## The Preference Problem

The one stubborn category was `single-session-preference`. These questions ask for personalized advice or recommendations: "Do you have any tips for my marathon training?" "What would you suggest for a date night restaurant?" The correct answer requires recalling stored preferences and applying them.

Early scores on preference hovered around 33-47%. The first assumption was routing — preference questions were probably hitting `graph` mode instead of `hybrid`, missing the SESSION context that contained the raw preference statements. That was partially true. The `_PREFERENCE_RE` routing fix (v0.3.5) added pattern matching for "any advice on", "can you suggest", "any tips", "what should I" — questions that use generic phrasing rather than the word "preference". The fix helped somewhat.

But an audit of known-failing preference questions revealed a second problem, deeper and harder to fix: Observer extraction quality. The model was failing to recognize implicit preferences at extraction time. "I've always found jazz uncomfortable to study to" is a preference, but Observer was often typing it as a CONCEPT ("user has feelings about jazz") or simply missing it. The verbose, specific phrase needed to reach the graph as a PREFERENCE node, verbatim, with enough specificity to be useful.

v0.3.7 rewrote the Observer `_SYSTEM_PROMPT` for preference extraction specifically:
- Explicit enumeration of categories that are preferences (lifestyle routines, viewing habits, dietary constraints, genre specificity, brand names)
- Anti-generalization rules: "User prefers Netflix stand-up comedy specials with strong storytelling" vs. the lossy "User likes comedy"
- WRONG/RIGHT examples
- Dual-extraction rule: when a procedure reveals a preference, extract both

The targeted 30-question preference spot check went from 33% to 46.7%. Progress, but still failing almost half.

A deeper extraction audit uncovered a completely separate bug: Observer's `max_tokens` was set to 1024. Long conversations — anything over ~15,000 characters — produced truncated JSON responses that failed silently. Zero nodes written, no error, no log. Every long-session preference question was working with an extraction that had simply stopped partway through the conversation and produced nothing. Bumping to 4096 recovered several questions that had been dead for the entire project.

---

## v0.4 — The Night of Twenty-Three Fixes (March 22, 2026)

v0.4 was built in a single session and landed 23 changes across the codebase. Not all of them were about the benchmark:

- **Reflector exception swallowing** — the behavioral synthesis code was catching all exceptions silently. Failures were invisible.
- **Multi-agent query filter** — the multi-agent adapter was returning all nodes instead of filtering by the requesting agent's scope.
- **Async executor leak** — `ThreadPoolExecutor` instances were being created per-observation and never cleaned up. In long sessions with many observations, this leaked threads until the process became sluggish.
- **Graph RLock thread safety** — concurrent reads and writes were possible without proper locking. Added `threading.RLock` to the Graph class.
- **Observer `_find_similar` FTS+fallback** — similarity search for the implicit supersession detector was occasionally failing silently when FTS5 returned no results. Added a fallback path.
- **Adversarial injection defense** (`sanitize.py`) — raw observation strings containing patterns like `<system>`, `[INST]`, or obvious role-play injection attempts are sanitized before writing to the graph, preventing stored memories from being replayed as injected instructions in future contexts.
- **SQLite WAL mode and connection caching** — write-ahead logging for better concurrent access; connection pooling for repeated queries.
- **PROCEDURE node routing** — procedural questions ("how do I set up my development environment?") now route to a dedicated context builder that surfaces PROCEDURE nodes with higher priority than CONCEPT nodes.
- **Implicit preference inference** — an `infer_implicit` flag on the Observer that attempts to extract preferences from behavioral description even when no explicit preference statement is made.

Some of these paid off in the benchmark. Most of them were just correctness fixes that should have been there from the start. 175 tests passing throughout.

---

## v0.5 — Making Extraction Async (March 28, 2026)

The performance problem with Observer was straightforward: LLM extraction calls were sequential. A session with 20 exchanges made 20 sequential API calls, each waiting for the previous to complete. For any agent that processes conversations in real time, this was a latency problem.

v0.5 made Observer extraction async with a `ThreadPoolExecutor`:

```python
# Before: 20 sequential LLM calls
for chunk in chunks:
    nodes = await self._extract(chunk)
    await self._write(nodes)

# After: parallel LLM calls, serialized graph writes
futures = [executor.submit(self._extract_sync, chunk) for chunk in chunks]
results = [f.result() for f in futures]
# _write_lock ensures no concurrent writes to graph
for nodes in results:
    await self._write(nodes)
```

The key insight: extraction is embarrassingly parallel (each chunk is independent) but graph writes must be serialized (concurrent writes corrupt the adjacency tables). `ThreadPoolExecutor` for extraction + `asyncio.Lock` for writes. `flush()` became the sync point — it blocks until all pending extractions complete and all writes are committed.

Two other v0.5 additions that mattered for the benchmark:

**Temporal date-anchoring.** The REFERENCE DATE was being injected into the answer prompt but not into the MCP server's system prompt — so when claude-code-mcp called `dory_query()`, it was answering without a temporal reference point. Fixed by adding `REFERENCE DATE: {question_date}` to the top of the MCP system prompt. The temporal score improved immediately.

**Confidence-seeded activation counts.** Observer's confidence score on each extracted node now seeds the `activation_count` at creation: high confidence (0.95+) starts at 3, moderate (0.85+) at 2, weak at 1. Combined with the salience formula that uses log(activation_count), this means high-confidence nodes start with enough salience to clear later filtering thresholds, while uncertain extractions are treated as tentative until reinforced.

**Distinct sessions in salience.** The salience formula was updated to weight cross-session persistence: `salience = log(activation_count) * (0.5 + 0.5 * log(distinct_sessions))`. A node seen in five sessions with moderate activation outscores a node seen obsessively in one session. This rewards the kind of facts that genuinely matter — the persistent background of who someone is — over the conversational noise of a single long session.

v0.5 benchmark: **79.6% (398/500)**. A slight regression from the 79.8% of v0.3. Within evaluator noise, but it stings.

---

## v0.6 — Behavioral Synthesis, Then Disabling It (April 2026)

v0.6 shipped with a feature that was subsequently turned off.

The Reflector's `_synthesize_behavioral_preferences()` function was designed to automatically infer PREFERENCE nodes from repeated behavioral patterns across sessions, without requiring Observer to explicitly extract them. The logic: if "go for a run", "track miles", and "morning workout" appear across 3+ nodes in 2+ different dates, synthesize a PREFERENCE: "User prioritizes morning exercise routines." No LLM call required — just keyword cluster analysis.

It sounded elegant. In practice, it generated PREFERENCE nodes that were keyword-noise: too generic, lacking specificity, occasionally wrong. "User prioritizes morning exercise" generated from three mentions of running was technically defensible but useless for answering "what kind of exercise do you think I'd enjoy trying?" The generated nodes cluttered retrieval and occasionally pushed more specific, useful nodes out of the activated context.

After a targeted ablation, behavioral synthesis was disabled: `_synthesize_behavioral_preferences()` now returns 0 and is effectively a no-op. The principle — inferring preferences from behavioral patterns without LLM calls — is still right. The execution was wrong. Future work.

v0.6 also shipped the complete preference routing stack: `_preference_context()` as a dedicated code path that surfaces all PREFERENCE nodes first (regardless of activation level), then FTS-expanded semantic nodes, then full SESSION history. When a preference question is detected, PREFERENCE nodes are front and center in the context. This mattered.

v0.6 benchmark: **84.0% (420/500)**. Plus four full percentage points from v0.5. The preference routing was working. Knowledge-update and multi-session were both strong.

---

## v0.7 — The Salience Floor and the Preference Regression (April 5, 2026)

v0.7 added several things that felt right:

**Salience floor.** `SALIENCE_FLOOR = 0.1` in `activation.py`. Nodes with `activation_count > 0` and `salience < 0.1` are skipped during serialization. The reasoning: a node extracted once from a single session, never reinforced, in a large graph with many high-salience nodes, contributes noise rather than signal. Filter it. The floor is conceptually sound. The implementation has a problem that took a while to see clearly.

**Duration hints.** Nodes with a `start_date` in metadata now serialize with a human-readable duration: `(~9 months, since 2023-03-01)`. A node like "User has been vegetarian since March 2023" becomes richer without requiring the answerer to do date math from scratch. Duration hints are annotated on every context serialization that threads a `reference_date`.

**Occurrence and amount hints.** `(×3, 3 times/week)` annotations for quantified facts. "User goes to therapy (×12, weekly)" gives the answerer both the frequency and the total count, enabling more precise answers to aggregation questions.

**Implicit supersession.** If Observer extracts a new node with numeric content that conflicts with an existing similar node, the old one is archived automatically. "Pre-approval is now $400k" following "$350k approved" shouldn't require explicit `supersedes_hint` from the extraction — the numeric value difference at similarity threshold 0.45 is enough signal to archive the old node and mark the new one as current.

**The start_date field in Observer schema.** Observer was already extracting event dates when explicitly stated. Now it also extracts `start_date` for facts that imply a duration without a specific date: "I've been at this job since March" → `start_date: "2023-03-01"` (resolved against session date).

v0.7 benchmark: **84.2% (421/500)**. A single question better than v0.6.

And then the preference score: **56.7%** (17/30). Down from 70.0% in v0.6. Thirteen percentage points of regression in the weakest category.

The investigation: the salience floor was the culprit. Single-session PREFERENCE nodes — extracted once from one conversation, never reinforced across sessions — have `activation_count=1` and `distinct_sessions=1`. Their salience score: `log(1) * (0.5 + 0.5 * log(1)) = 0 * 0.5 = 0`. Zero salience, below the floor, filtered out entirely.

This is the absolute threshold applied to a relative score problem in its clearest form. The PREFERENCE node was extracted correctly. The routing to `_preference_context()` was correct. But the node never made it out of serialization because its salience was zero — not because it was noise, but because it had never been mentioned in any other session. A single-session preference is still a preference.

The attempted fix: exempting PREFERENCE nodes from the salience floor. The result: net +1 question (17 → 18) across 30 preference questions, with 7 gains and 6 regressions. Within evaluator noise. The regressions appeared to be preference-routing-caused wrong answers surfacing previously-filtered generic nodes. The floor exemption wasn't the solution.

The correct solution — WORKING node type seeded at `activation_count=2` — was identified but not yet validated.

The honest summary: knowledge-update jumped to 92.3% (+5.1pp), multi-session reached 85.7% (+1.5pp), single-session-user hit 94.3% (+1.4pp). Four questions of net improvement were erased by the four-question preference regression. v0.7 shipped at essentially the same overall score as v0.6.

---

## v0.8 — The Code Changes and the Experiment Mistake

v0.8 code landed on main as one commit. Three changes:

**WORKING node type.** A new node type for ephemeral session-scoped facts: current tasks, in-progress decisions, temporary states. "I'm trying to decide between Postgres and SQLite for this project" is a WORKING fact — it matters now, it may resolve by next session, and it shouldn't accumulate salience like a persistent preference. WORKING nodes are seeded at `activation_count=2` at creation regardless of extraction confidence. This clears the `SALIENCE_FLOOR = 0.1` immediately — `log(3) * (0.5 + 0.5 * log(1)) = 0.549 * 0.5 = 0.274`. Single-session facts survive filtering as long as they're typed WORKING. After consolidation with no reinforcement, they decay naturally and archive themselves. This also addresses the preference problem for new single-session preferences: if Observer types them as WORKING, they survive.

**Temporal context chronological ordering.** `_temporal_context()` now sorts EVENT nodes by `event_date` or `start_date` metadata, not by activation level. Previously, the most recently activated events appeared first in the context — which often meant the most-recently-queried events, not the most-recently-dated ones. "Which happened first?" questions were seeing events in arbitrary relevance order. Now they see them in calendar order. Mechanical change, meaningful impact on temporal questions.

**`flush()` → `consolidate()` rename.** The primary method is now `consolidate()`. `flush()` retained as a backward-compatible alias. `consolidate` is the right word — it describes the intent (decay, dedup, conflict resolution, archive management) better than `flush` (which implies buffer clearing). `aconsolidate()` added; `aflush()` kept.

Then the benchmark run.

The decision: run Sonnet for *both* extraction and answering. The hypothesis was that Sonnet's stronger reasoning would improve across the board — better extraction *and* better answers. The implementation used `--answer-backend anthropic` with `--answer-model claude-sonnet-4-6`, which uses the Anthropic API directly to answer rather than going through claude-code-mcp.

This was a mistake, but it wasn't obvious until the results came in.

**v0.8 Sonnet (API) benchmark: 80.6% (403/500).** A 3.6pp regression.

The category breakdown was illuminating:

| Category | v0.7 | v0.8-API | Δ |
|---|---|---|---|
| temporal-reasoning | 75.2% | 84.2% | **+9pp** |
| preference | 56.7% | 63.3% | +6.6pp |
| single-session-user | 94.3% | 91.4% | -2.9pp |
| single-session-assistant | 92.9% | 83.9% | **-9pp** |
| knowledge-update | 92.3% | 78.2% | **-14pp** |
| multi-session | 85.7% | 75.2% | **-10.5pp** |

Temporal went up 9 points. Knowledge-update fell 14. The net: eighteen fewer correct answers than v0.7.

The temporal gain was mechanistically clear: Sonnet reliably converts relative date references to absolute ISO dates during extraction. "About two months ago" becomes `2023-03-28`. Haiku was less consistent at this. With precise dates in the graph, any answerer can do arithmetic. The temporal gain was real and would persist in any configuration using Sonnet for extraction.

The knowledge-update and multi-session regression required more thought.

The answer was in the answering path, not the extraction. `claude-code-mcp` is an *agentic* answering backend. Claude Code runs with Dory's MCP tools available. The answerer can call `dory_query()` multiple times — it can reformulate, query from different angles, synthesize across separate graph queries. It decides what to look up. When it sees "4 engineers when I started, 5 now" in the context, it can call `dory_query("current team size this year")` to confirm the update, then call `dory_query("team size when they started")` to verify the starting point. Two targeted queries, each returning compact, relevant context.

The `--answer-backend anthropic` path is *static*. `session.query()` runs once, builds one context string, and hands it to the model. The model gets one shot. If the context contains both the old value and the updated value for a fact — which it often does, because superseded nodes surface in the graph alongside their replacements — the model has to determine which is current from the context alone. Sometimes it gets it wrong. With the agentic path, it can explicitly query for the current value and verify.

Example from the actual failures:

> **Q:** "How many engineers do I lead now vs. when I started?"  
> **v0.7 (MCP):** "When you first started: 4 engineers. As of late October 2023: your team has grown to 5 engineers."  
> **v0.8 (API):** "When you started: 4 engineers. Now: you still lead 4 engineers (your team of 4 + yourself = 5 total)."

The v0.8 answerer saw the context, got confused by the arithmetic surrounding the update, and reported the old value. The v0.7 answerer queried `dory_query("current team size")` explicitly and got the `[CURRENT VALUE]` marker front-and-center in its response.

The second cause: Sonnet's extraction disrupted supersession chains. The implicit supersession detector uses similarity threshold 0.45 to find candidate nodes whose numeric values conflict with a new observation. Sonnet's more verbose, more interpretive extraction style produces nodes with different surface forms than Haiku's more conservative extraction — "Therapy frequency increased to weekly visits" vs. "sees therapist weekly". When the content phrase changes significantly, the similarity score drops below 0.45 and the supersession doesn't trigger. The old "bi-weekly" node survives. The answerer sees both.

The lesson: changing both the extractor and the answering backend in the same run makes results uninterpretable. The two effects cannot be isolated. This should have been obvious in advance and wasn't.

---

## v0.8 MCP — The Correct Experiment (April 7, 2026)

The correct run: Sonnet extraction + claude-code-mcp answering. Hold the agentic path constant, change only the extractor. Cost: ~$25-30 in API credits plus the claude-code-mcp subscription.

**v0.8 Sonnet+MCP benchmark: 84.2% (421/500).**

| Category | v0.7 | v0.8-MCP | Δ |
|---|---|---|---|
| temporal-reasoning | 75.2% | 82.7% | **+7.5pp** |
| preference | 56.7% | 70.0% | **+13.3pp** |
| abstention | 66.7% | 73.3% | +6.6pp |
| single-session-user | 94.3% | 94.3% | — |
| knowledge-update | 92.3% | 87.2% | -5.1pp |
| multi-session | 85.7% | 83.5% | -2.2pp |
| single-session-assistant | 92.9% | 80.4% | **-12.5pp** |

The temporal and preference gains held. The agentic answering recovered most of the knowledge-update and multi-session regression. The single-session-assistant regression is new and unexplained — these questions ask about what Claude *said* in prior sessions, and Sonnet's extraction may be abstracting assistant utterances rather than preserving them verbatim. This deserves investigation.

Net: 421/500. Same as v0.7.

---

## The Ceiling

Three runs have now landed at 84-85%:

- v0.6: 84.0%
- v0.7: 84.2%
- v0.8-MCP: 84.2%

Different extractors. Same score. This is a ceiling, not a coincidence.

The bottleneck is the retrieval architecture, not the extraction quality. Specifically: the system routes based on what the *question looks like* rather than what is *in the graph*. `_TEMPORAL_RE` catches questions that contain temporal language and routes them to `_temporal_context()`. `_PREFERENCE_RE` catches questions that contain recommendation language and routes them to `_preference_context()`. Each routing branch was added to fix a specific category of benchmark failures, and they interact in ways that are increasingly hard to predict.

There are now three separate context builders (`_temporal_context`, `_preference_context`, `_hybrid_context`), an explicit routing function that classifies queries, and multiple node types with special handling in serialization. The system has accumulated heuristics incrementally, each justified by a benchmark failure it fixed. The heuristics are individually defensible. Together they form a decision tree that no longer has clean semantics.

The principled path forward is the opposite of routing: a single retrieval path that lets the graph's structure answer structural questions.

1. **Spreading activation surfaces top-k nodes.** The full activated set — with type labels, metadata, SUPERSEDES edges, temporal markers, occurrence counts, duration hints — is serialized as a structured, richly-annotated context.
2. **One LLM reasoning step synthesizes the answer.** No code-path branching. The model reads the graph structure and reasons about it.

The graph already encodes the answers to the routing questions:
- Is this a temporal question? The EVENT nodes have `event_date` metadata and the SESSION chain has `TEMPORALLY_AFTER` edges.
- Is this about what's currently true? SUPERSEDES edges and `[CURRENT VALUE]` markers show which node is authoritative.
- Is this an aggregation? `occurrence_count` and `salient_counts` in SESSION_SUMMARY nodes give the numbers.

The LLM doesn't need the routing layer to answer these questions — it needs the graph to *be interpretable*. The routing layer exists to compensate for a context that isn't self-describing. Make the context self-describing, remove the routing.

Mastra Observational Memory achieves 94.87% on LongMemEval with this approach. The difference isn't a smarter model or more expensive extraction — it's a context structure that doesn't require preprocessing.

---

## Where Things Stand

**Code state:** v0.8 branch. Three changes committed to main, not yet versioned:
- WORKING node type (seeded at activation_count=2, clears salience floor, self-archives after consolidation)
- Temporal chronological ordering in `_temporal_context()`
- `flush()` → `consolidate()` rename (backward-compatible)

**PyPI state:** v0.7.0 is the current release.

**Benchmark state:** 84.2% is the honest current performance. The v0.8-MCP run represents the best configuration: Sonnet extraction, agentic MCP answering. This is what gets shipped as v0.8.0.

**The single-session-assistant regression** (-12.5pp vs v0.7) is unexplained and needs investigation before making claims about improvement over v0.7. Hypothesis: Sonnet extracts assistant utterances by abstracting/summarizing rather than quoting, losing the specificity needed to answer "what advice did you give me about X?" This is a targeted extraction audit, not a full benchmark run.

---

## What I Want to Try

These are ordered by impact-to-cost ratio, not by ambition.

### Near-term (cheap, targeted)

**1. Version v0.8.0 and push to PyPI.**
The code is stable, the benchmark validates it, and it's been sitting unreleased. The only thing missing is a version bump and `twine upload`. Do this first — it closes the loop on a month of work.

**2. Single-session-assistant extraction audit.**
Pull the 11 questions where v0.8-MCP failed but v0.7 succeeded. Run extraction on those 11 conversations with both Haiku and Sonnet. Compare the extracted nodes side by side. Determine: is Sonnet abstracting assistant utterances? If yes, add verbatim-preservation instruction to the Observer prompt specifically for assistant turns. Targeted fix, no full run needed to validate.

**3. Relative salience floor.**
Replace `SALIENCE_FLOOR = 0.1` with `salience < percentile(active_nodes, 15)`. One function change in `activation.py`. The current floor is an absolute threshold on a relative score — as graphs grow, it increasingly filters nodes that would have cleared the floor in smaller graphs. Percentile-based floor is graph-size-agnostic. Validate with a 40-question spot check, not a full run.

**4. WORKING node validation spot check.**
Run 20 preference questions that failed in v0.7 and failed in v0.8-MCP. Check whether Observer is now typing those single-session preferences as WORKING (clearing the floor) or still as PREFERENCE (still getting filtered). If WORKING is working, the preference score should improve. If not, the Observer prompt needs tuning. 20 questions, not 500.

### Medium-term (significant but bounded)

**5. SUPERSEDES vs REFINES edge distinction.**
"User now uses MLX instead of llama.cpp" is replacement — the old value is wrong. "User uses FastAPI with PostgreSQL" (previously just FastAPI) is elaboration — the old value is still true, it's now more specific. The graph conflates these via a single SUPERSEDES edge type. Adding REFINES allows the answerer to distinguish "this supersedes that" from "this elaborates on that". Relevant for knowledge-update and multi-session questions where the distinction matters.

**6. `dory explain <node_id>` CLI command.**
When a supersession fires and a node gets archived, there's currently no way to inspect the provenance chain without querying the database directly. `dory explain` would surface: what was this node, why was it archived, what superseded it, what evidence triggered the supersession, and what the current authoritative value is. This isn't a benchmark feature — it's a trust feature. Developers need to be able to verify that the graph is doing what they think it's doing.

### Architecture (the real work)

**7. Unified retrieval path.**
Remove `_route_query()`, `_temporal_context()`, `_preference_context()`, `_hybrid_context()`, `_aggregation_context()`, `_procedure_context()`. Replace with a single path:

```python
async def query(self, text: str, reference_date: str = "") -> str:
    seeds = await self._find_seeds(text)
    activated = self.activation.spread(seeds, max_nodes=50)
    context = self.serialize_structured(activated, reference_date=reference_date)
    return context  # let the LLM reason about it
```

`serialize_structured()` produces a self-describing context: events in chronological order, SUPERSEDES chains annotated with `[SUPERSEDED]` / `[CURRENT VALUE]` markers, PREFERENCE nodes grouped and labeled, SESSION_SUMMARY nodes with their counts. The context is interpretable without preprocessing. The LLM reasons directly about the structure.

This is the path to breaking 85%. It's also a significant refactor — maybe 400 lines of code deleted, 150 written. The routing tree and all its heuristics become dead code.

Expected cost: a full 500q run after implementing, ~$30. Expected result: 87-90%. Possible 90%+. That's the v1.0 benchmark claim.

---

## Lessons That Apply Everywhere

**Change one variable at a time.** The v0.8 regression was caused by changing both extractor and answering backend simultaneously. The results were uninterpretable for weeks. This applies to every experiment, every ablation, every "what if I just also change X while I'm in there."

**Agentic retrieval is qualitatively different from static retrieval.** Claude Code calling `dory_query()` multiple times, reformulating, and synthesizing across queries is not a cost optimization — it's a different capability class. Static one-shot context injection cannot replicate multi-query synthesis. When you're measuring memory system performance, you're also measuring the answering path.

**The context-rot problem is real and applies to memory.** Injecting too much memory creates noise that degrades performance on the things that matter. The spreading activation approach — surface the relevant subgraph, not the whole graph — is the right instinct. The self-describing context (unified retrieval, v2.0 direction) takes this further: compact, structured, no redundancy.

**Absolute thresholds on relative scores are wrong.** `SALIENCE_FLOOR = 0.1` is the clearest example but not the only one. The supersession threshold (0.45), the confidence seeds (0.95/0.85) — all of these are magic numbers calibrated on a specific graph size and session history. They will drift as graphs grow. Percentile-based thresholds are the right form.

**Trust the graph topology.** Every time the benchmark improved meaningfully, it was because the graph structure started doing more work: TEMPORALLY_AFTER edges for chronological ordering, SUPPORTS_FACT edges for provenance traversal, SUPERSEDES edges for current-truth identification. The routing heuristics are a workaround for a context that doesn't surface its own structure well enough. Fix the context, remove the heuristics.

---

## Current Standing in the Landscape

The agent memory landscape has gotten crowded in 2026. Mem0 (50k GitHub stars), Zep/Graphiti (bi-temporal knowledge graph, 24k stars), Letta (the MemGPT lineage), Mastra (TypeScript-only, best benchmarks, 94.87%). The open-source space has gone from nothing to several well-funded competitors in eighteen months.

Dory occupies a specific niche: **Python-native, local-first, principled forgetting, graph-based, Apache 2.0**. Mastra is TypeScript-only and cloud-friendly. Zep/Graphiti requires Neo4j. Mem0 has a 20-second self-hosted write latency problem. Letta requires full adoption of their runtime.

Dory works with any LLM, runs on a single SQLite file, and can be adopted incrementally into an existing agent codebase in five lines:

```python
from dory import DoryMemory
mem = DoryMemory()
mem.observe(user_message)
context = mem.query(question)
# inject context into your existing prompt
```

The benchmark result (84.2%) is honest and reproducible. It's not the best number in the space, but it's a real number on a public benchmark with published methodology. When the unified retrieval path lands and the correct v1.0 run produces 87-90%, that becomes a competitive claim.

For now: v0.8.0 is ready to ship. The architecture has a clear path forward. And the benchmarks are going to have to wait until the credits recover.

---

*Last updated: 2026-04-07*  
*Current version: v0.7.0 (PyPI) / v0.8.0 (main, unreleased)*  
*Benchmark: 84.2% LongMemEval Oracle, 500 questions, Haiku judge*
