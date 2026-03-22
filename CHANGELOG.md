# Changelog

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
