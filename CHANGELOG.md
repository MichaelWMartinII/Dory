# Changelog

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
