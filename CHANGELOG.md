# Changelog

## [0.9.0] — 2026-04-15

### Added
- **REFINES edge type** — `EdgeType.REFINES` is now distinct from `SUPERSEDES`. A REFINES
  edge means the new node elaborates an existing node without replacing it (e.g. "uses FastAPI
  with PostgreSQL" REFINES "uses FastAPI" — both remain active). The `_is_elaboration()`
  heuristic in Observer distinguishes numeric-conflict supersession from non-numeric elaboration.
  Rendered in context under `## Elaborations` as `[ELABORATION] base → more specifically: specific`.
- **`dory explain` CLI command** — surface the full provenance chain for any node: what it
  supersedes, what supersedes it, REFINES relationships, archival metadata, and activation
  history. Accepts a node ID or a substring match. `dory explain <node_id_or_text>`

### Changed
- **Unified retrieval path** — `_route_query()` and all five query-type-specific context
  builders (`_temporal_context`, `_aggregation_context`, `_hybrid_context`,
  `_procedure_context`, `_preference_context`) are removed. `query()` now calls a single
  `_serialize_structured()` function that groups nodes by structural role (Current Values,
  Knowledge Updates, Elaborations, Preferences, Procedures, Working, Events, Session
  Summaries, Sessions, Context). The graph structure is self-describing — no routing
  heuristics needed.
- **Dead code removed** — all regex routing patterns (`_TEMPORAL_RE`, `_AGGREGATION_RE`,
  `_HYBRID_RE`, `_PROCEDURE_RE`, `_PREFERENCE_RE`) and associated helper functions
  (`_get_linked_summaries`, `_aggregate_counts`, `_format_summary_block`, `_dedup_similar`)
  removed from `session.py`. ~440 lines of dead code eliminated.

### Benchmark
- Architecture change only — no new 500q run. Last measured score: **84.2%** (v0.8-MCP).
  Unified retrieval is the architectural prerequisite for breaking the 84-85% ceiling.

## [0.8.1] — 2026-04-08

### Added
- **WORKING node type** — ephemeral session-scoped facts (current tasks, in-progress
  decisions, temporary states). Seeded at `activation_count=2` at creation, clearing
  `SALIENCE_FLOOR` immediately. Self-archives after consolidation if not reinforced.
  Addresses the single-session preference filtering problem for newly-extracted facts.
- **MCP visualization now loads D3.js** — `dory_visualize` MCP tool now passes
  `allow_remote_js=True`, enabling the full interactive force-directed graph in the
  browser instead of the static fallback view. (Was broken in 0.8.0.)

### Changed
- **Temporal context is chronologically ordered** — `_temporal_context()` now sorts
  EVENT nodes by `event_date` / `start_date` metadata rather than activation level.
  "Which happened first?" questions now see events in calendar order.
- **`flush()` renamed to `consolidate()`** — the primary method is now `consolidate()`;
  `flush()` is retained as a backward-compatible alias. `aconsolidate()` added;
  `aflush()` kept. The new name better describes the intent: decay, dedup, conflict
  resolution, archive management.

### Benchmark
- LongMemEval 500q (Sonnet extraction + claude-code-mcp answering): **84.2%** (421/500)
  — ties v0.7.0 best. Category gains: temporal-reasoning +7.5pp (82.7%), preference
  +13.3pp (70.0%), abstention +6.6pp (73.3%). Category regressions: single-session-assistant
  -12.5pp (80.4%, under investigation), knowledge-update -5.1pp (87.2%).

## [0.7.0] — 2026-04-05

### Added
- **Duration hints** — `serialize()` now accepts a `reference_date` parameter and
  annotates nodes with a `start_date` in metadata (e.g. `(~9 months, since 2023-03-01)`).
  All context builders (`_temporal_context`, `_hybrid_context`, `_aggregation_context`,
  `_preference_context`, `_procedure_context`) thread `reference_date` through to
  serialization.
- **Occurrence and amount hints** — Observer extracts `occurrence_count` and `amount`
  metadata fields. Repeated reinforcement increments the count; `serialize()` surfaces
  them as `(×3, $350,000)` inline annotations for aggregation and counting questions.
- **`start_date` extraction** — Observer prompt now extracts `start_date` for facts
  that imply a duration ("I've been at this job since March", "started medication last
  Monday"). Approximate ISO date is computed from session date when provided.
- **Implicit supersession** — Observer detects numeric-value conflicts without explicit
  update language (e.g. "pre-approval is $400k" following "$350k") using
  `_find_similar` at threshold 0.45 and `_extract_numeric_value`.
- **`supersedes_hint` and `amount` in Observer schema** — extraction prompt now asks
  for these fields explicitly, improving supersession chain accuracy.
- **Salience floor** — `serialize()` skips nodes with `activation_count > 0` and
  `salience < 0.1`, reducing noise from single-mention stale nodes in large graphs.

### Changed
- Visualization is now safe-by-default: generated HTML no longer loads remote
  D3.js unless explicitly requested. The default output is a local-only fallback
  view that still exposes node and edge data.
- `DoryMemory.visualize()` and `dory visualize` now support explicit opt-in to
  remote assets for the full interactive graph view.

### Benchmark
- LongMemEval 500q: **84.2%** (421/500) — flat vs v0.6 overall, with meaningful
  gains in knowledge-update (+5.1pp → 92.3%) and multi-session (+1.5pp → 85.7%).

### Repo cleanup
- Removed stale `benchmarks/eval_and_compare.sh`, which referenced missing benchmark files.
- Archived the local-only demo from `examples/live_chat.py` to `examples/archive/live_chat_legacy.py`.
- Moved historical user-experience reports from `tests/user_tests/` to `docs/archive/user-tests/`.
- Added `benchmarks/README.md` and `docs/REPO_CLEANUP_2026-03-29.md`.

## [0.3.8] — 2026-03-22

### Added
- `dory review-session` CLI command — reads a Claude Code session `.jsonl` transcript,
  strips tool calls / thinking blocks, pipes text turns through `Observer`, and writes
  extracted memories into the graph. Supports three source modes:
  - `--from-hook`: reads `transcript_path` from Claude Code Stop hook JSON on stdin
  - `--file PATH`: explicit transcript path
  - auto-detect: finds most recently modified `.jsonl` for the current project directory
- Processed sessions tracked in `~/.dory/reviewed_sessions.txt` to prevent double-extraction.
  Use `--force` to re-process.
- `benchmarks/evaluate_anthropic.py` (shipped in v0.3.7, added here for clarity) — Anthropic-backed
  LongMemEval evaluator, drop-in replacement when no OpenAI key is available.

### Changed
- Claude Code Stop hook now runs `review-session --from-hook` before `consolidate`, so every
  session is automatically extracted into the memory graph at session end.
  Config in `~/.claude/settings.json`.

## [0.3.7] — 2026-03-22

### Changed
- Observer `_SYSTEM_PROMPT` significantly expanded PREFERENCE guidance to fix two failure modes
  seen in LongMemEval `single-session-preference` questions:
  - **Classification misses**: lifestyle routines, viewing/listening habits, dietary choices, and
    avoidance constraints were being typed as CONCEPT or PROCEDURE instead of PREFERENCE. Now
    explicitly enumerated with examples (bedtime routines, Netflix stand-up specials, podcast genres,
    recipe ingredient choices as preference signals).
  - **Specificity loss**: nodes were being generalized (e.g. "User likes comedy" instead of
    "User prefers Netflix stand-up comedy specials with strong storytelling"). Added explicit
    anti-generalization rule: preserve genre names, platform names, brand names, time/frequency
    constraints, and qualifying conditions. Three WRONG/RIGHT examples added.
  - Also added PROCEDURE+PREFERENCE dual-extraction rule: when a procedure clearly reveals a
    personal preference, extract both node types.
- Targeted 30-question benchmark on `single-session-preference` subset: **18/30 = 60.0%**
  (Haiku extract + Haiku answer + Haiku judge). Note: this is a short-run indicative result;
  a full 500-question Sonnet run is incoming for a clean apples-to-apples comparison
  against the v0.3.0 baseline of 79.8%.

## [0.3.6] — 2026-03-22

### Fixed
- Routing: added `(?:what do|do) you think` to `_PREFERENCE_RE` so questions like
  "Do you think it might be my allergies?" and "What do you think about my training
  plan?" correctly route to preference context instead of plain graph mode.

## [0.3.5] — 2026-03-22

### Fixed
- Preference recall: `_PREFERENCE_RE` broadened to match actual recommendation question phrasing
  ("any advice on...", "can you suggest...", "any tips on...", "what should I..."). Previously,
  preference questions using generic language routed to plain graph mode and missed PREFERENCE
  nodes and SESSION narratives. Now routes to a dedicated `_preference_context()` function.
- Added `_preference_context()`: surfaces all PREFERENCE nodes first (regardless of activation
  level), then FTS-expanded semantic nodes, then full SESSION history. Ensures stored preferences
  are front-and-center when answering recommendation questions.
- Routing bug: `_PREFERENCE_RE` is now checked before `_TEMPORAL_RE` in `_route_query`. Previously,
  time words like "tonight" or "today" in preference questions ("any movie recommendations for
  tonight?") caused misrouting to episodic mode, producing empty context. Preference signal now
  takes priority over incidental temporal language.
- Observer (`_call_anthropic`): increased `max_tokens` from 1024 to 4096. Long conversations
  (>~15k chars) were producing truncated JSON responses that silently failed extraction — 0 nodes
  written, no error surfaced. Affected all Anthropic-backend users with lengthy sessions.

## [0.3.4] — 2026-03-21

### Fixed
- `DEFAULT_GRAPH_PATH` now resolves to `~/.dory/engram.db` instead of `site-packages/engram.db`. Previously, using `dory-mcp` or `DoryMemory()` without an explicit `db_path` would silently write the user's memory graph inside the Python package installation directory — ephemeral and wrong.
- MCP server now reports the correct `dory-memory` package version in the initialize handshake instead of the MCP library version.

### Changed
- README MCP setup section rewritten: shows `which dory-mcp` step (required for venv installs), canonical `--db ~/.dory/engram.db` form, `claude mcp list` verification step, `DORY_DB_PATH` env var, and Claude Desktop config.

## [0.3.3] — 2026-03-21

### Added
- `examples/demo_ollama.py` — fully local two-session memory demo using Ollama (no API key required). Auto-detects installed model, uses native Ollama backend.

### Fixed
- `think=False` added to `ollama.chat()` in `_call_ollama` — disables Qwen3 extended reasoning mode during extraction. Cuts extraction time ~3x (90s → 30s). Also fixes silent extraction failure when using `extract_backend="openai"` pointed at a local Ollama server (90s model response > 60s httpx timeout → 0 memories, no error message).

### Changed
- README: added `qwen3:8b` (5 GB) alongside `qwen3:14b` as a recommended extraction model
- README: added note that local Ollama extraction takes 15–60s per batch
- README: moved graph topology demo and Ollama demo to v0.3 shipped section; removed from v0.4 in-progress

## [0.3.2] — 2026-03-20

### Added
- `mem.visualize()` interactive graph with spreading activation query mode, edge type coloring, archived/superseded node rendering, and session summary chain
- `examples/demo_topology.py` — six live graph traversals demonstrating what spreading activation + typed edges can answer that flat/vector search cannot (supersession, chronicle, dependency, semantic path, provenance, belief grounding)
- Live demo hosted on GitHub Pages

### Changed
- README: result-first positioning, demo GIF, topology section

## [0.3.1] — 2026-03-20

### Changed
- PyPI description leads with benchmark result (+13pp, 79.8%)
- README opening rewritten: result first, 5-line temporal overwrite example
- Added DoryMemory.visualize() — one-liner to open graph in browser
- Added examples/quickstart.py — zero-dependency end-to-end example

## [0.3.0] — 2026-03-20

### Benchmark
- Full 500-question LongMemEval oracle run: **79.8%** (Sonnet/Sonnet), up from 66.8% in v0.1 (+13.0pp)
- Every category improved — no regressions
- temporal-reasoning: 46.6% → 75.9% (+29.3pp), largest absolute gain
- multi-session: 70.7% → 80.5% (+9.8pp)
- knowledge-update: 75.6% → 84.6% (+9.0pp)
- Beats Mem0 (68.4%) and Zep (71.2%) on full 500-question run

### Changed
- Version bump to 0.3.0

## [0.2.0] — 2026-03-19

### Added

**Episodic memory layer (SESSION_SUMMARY)**
- `SESSION_SUMMARY` node type with structured `salient_counts` metadata — enables reliable answers to counting questions without re-reading full session narratives
- `Summarizer.summarize_session()` — creates SESSION_SUMMARY nodes with compressed narrative, extracted counts, and provenance edges
- `SUPPORTS_FACT` and `MENTIONS` edge types — bidirectional provenance from SESSION_SUMMARY to the semantic nodes it grounds
- `TEMPORALLY_AFTER` / `TEMPORALLY_BEFORE` edge types — chronological chain linking SESSION_SUMMARY nodes across sessions

**Retrieval fusion**
- `_route_query()` — deterministic regex-based query routing (no LLM call): `graph` / `episodic` / `hybrid`
- `_get_linked_summaries()` — staged retrieval: spreading activation → SUPPORTS_FACT traversal → SESSION_SUMMARY injection
- `_format_summary_block()` — renders SESSION_SUMMARY nodes with date, narrative, and salient_counts including low-confidence warnings
- `_hybrid_context()` — semantic graph block + episodic summaries + trust hierarchy instruction
- `_PREFERENCE_RE` — routes personalized suggestion queries to hybrid mode for episodic context

**Behavioral preference synthesis**
- `Reflector._synthesize_behavioral_preferences()` — detects repeated behavioral patterns across sessions (keyword clusters appearing in 3+ nodes across 2+ dates) and synthesizes PREFERENCE nodes without LLM calls

**Count reliability**
- `Summarizer._cross_validate_counts()` — cross-validates salient_counts against EVENT nodes, flags uncertain counts with `count_confidence: low` metadata
- Low-confidence counts displayed with ⚠ warning in context injection

**Benchmark tooling**
- `benchmarks/compare_runs.py` — question-by-question comparison of two eval-results files
- `benchmarks/eval_and_compare.sh` — shell script: evaluate + compare in one command
- `benchmarks/ABLATION.md` — ablation study documenting component contributions
- `benchmarks/longmemeval.py` — ablation flags: `--no-session-summary`, `--no-session-node`

### Changed

- `Node` dataclass now has `metadata: dict` field (persisted as JSON in SQLite)
- `_ANSWER_PROMPT_TEMPORAL` updated to require explicit date arithmetic ("show your work")
- `_SUMMARY_SYSTEM_PROMPT` updated to count enumerated items even without explicit numbers
- Aggregation routing now takes priority over temporal routing within episodic mode

### Fixed

- SESSION memories now appear **after** semantic block in `_aggregation_context()` — prevents model anchoring on incomplete counts from session summaries
- `_TEMPORAL_RE` expanded to catch relative time patterns: "2 weeks ago", "last Saturday", "the past month"
- `question_date` now injected into answer prompts for accurate relative-time reasoning
- Observer `session_date` threading for correct EVENT node temporal ordering

## [0.1.0] — 2026-03-10

Initial release.
- Knowledge graph with spreading activation retrieval
- Observer pipeline (LLM-based memory extraction)
- Summarizer (SESSION nodes), Prefixer, Decayer, Reflector
- MCP server (5 tools)
- LangChain, LangGraph, and multi-agent adapters
- Async API throughout
- SQLite backend (FTS5 + optional sqlite-vec)
- JSON-LD export/import
# Unreleased

## Security / reliability hardening

- Switched persistence away from implicit full-snapshot deletion to explicit
  tombstone-based deletion, reducing the risk that a stale `Graph` instance
  wipes rows written by another process.
- Sanitized raw observations at write time and redact obvious prompt-injection
  content before it can be replayed through history/recent-observation paths.
- Replaced insecure `tempfile.mktemp()` usage in `examples/demo_topology.py`.
- Added `SECURITY.md` and `docs/HARDENING_2026-03-29.md`, including revert
  instructions for each hardening change.
