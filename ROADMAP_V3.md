# Dory v0.3 Roadmap — Addressing All Review Concerns

Generated 2026-03-19. Based on reviews from GPT (OpenAI), Claude (Anthropic), and Grok (xAI)
covering both the v0.1 repo and the v0.2 episodic layer.

---

## What the Reviews Got Right

| Concern | Reviewer | Verdict |
|---|---|---|
| No full 500q v0.2 run — spot check isn't proof | All three | **Correct. Fix first.** |
| Benchmark shaping risk — some fixes may be LongMemEval-specific | GPT | **Partially correct. Ablation needed.** |
| salient_counts extraction fragile ("a few plants" ≠ count) | Claude | **Correct. Specific fix available.** |
| Preference stuck at 33% — behavioral preferences not captured | All three | **Correct. Biggest opportunity.** |
| SessionSummary trust problem — wrong counts become authoritative | GPT | **Correct. Cross-validation needed.** |
| Graph topology advantage unproven | GPT, Grok | **Correct. LongMemEval tests recall, not topology.** |
| Attribution ambiguity — all v0.2 fixes bundled | GPT | **Correct. Ablation table needed.** |
| Mastra comparison unfair (different model, language, stack) | Claude | **Correct. Reframe, don't delete.** |
| README roadmap shows shipped features as planned | Claude | **Correct. Easy fix.** |
| v0.2 not on main — verifiability gap | Grok | **Correct. Merge after validation.** |
| Zero community adoption signals | All three | **Real. Addressable.** |

## What the Reviews Got Wrong

| Concern | Verdict |
|---|---|
| "Mostly fixing routing bugs, not real architecture" | Wrong. SESSION_SUMMARY + staged fusion is genuine. But ablation will prove it. |
| "0 stars means no external validation" | This is a 2-week-old public repo. Unfair baseline. |
| "Real conversations are messier" | True but not actionable yet. Benchmark first. |
| Regressions attributed to evaluator noise | Debatable. Two of three looked like genuine judge errors in raw output. |

---

## Phases

### Phase 0 — Validation Gate *(Blocker)*
**Goal:** Confirm v0.2 doesn't regress before merging anything.
**Cost:** ~$0.30 (Haiku/Haiku, 10 questions)
**Files:** `benchmarks/longmemeval.py`

- Run `spot_micro.json` cleanly (v0.2-episodic branch, `source .env` first)
- Evaluate with `evaluate_qa_claude.py`
- Compare against v0.1 Haiku baseline using `compare_runs.py`
- **Gate:** v0.2 ≥ v0.1 Haiku on same 10 questions → proceed. Otherwise, debug regressions first.

---

### Phase 1 — Ablation Study *(Scientific Credibility)*
**Goal:** Isolate which v0.2 components are actually contributing to the gain.
**Cost:** ~$0.30 (two additional 10q Haiku runs)
**Files:** `benchmarks/longmemeval.py` (temporary flags)

Three controlled runs on `spot_micro.json`:
- **Run A** — SESSION_SUMMARY disabled (`summarize_session()` call removed)
  → Isolates: does salient_counts/staged fusion help, or just the SESSION node?
- **Run B** — Both SESSION + SESSION_SUMMARY disabled, routing kept
  → Isolates: how much is routing matrix alone worth?

Compare all three with `compare_runs.py`. Document in `benchmarks/ABLATION.md`.

This directly addresses the "attribution ambiguity" criticism with real data, not speculation.

---

### Phase 2 — Technical Fixes (Priority Order)

#### 2a — Behavioral Preference Synthesis in Reflector *(Highest ROI)*
**Goal:** Capture latent preferences inferred from behavior, not just stated preferences.
**Estimated lift:** +3-5pp on preference category (33% → ~38%)
**Cost:** $0 (no LLM calls — pure graph aggregation)
**File:** `dory/pipeline/reflector.py`

**The gap:** Observer extracts PREFERENCE when user *says* "I prefer X". But LongMemEval preference
questions require inferring preferences from *behavior* across sessions: user mentions quinoa 4 times
across 3 sessions → "User regularly incorporates quinoa in meal prep." Observer never sees this
pattern; it only processes one session at a time.

**The fix:** New `_synthesize_behavioral_preferences()` method in `Reflector.run()`:
1. Group all PREFERENCE + CONCEPT nodes by shared subject keyword (using existing `_word_set()`)
2. When 3+ nodes about the same topic exist across different sessions → synthesize a new
   high-confidence PREFERENCE node: "User consistently engages with X (observed 3+ sessions)"
3. Link with SUPERSEDES edges from the synthetic node to the source nodes
4. Set `is_core=True` on the synthetic node
5. No LLM call required — pure Jaccard-based aggregation

**Why this is genuinely valuable beyond the benchmark:** Real agents accumulate many low-confidence
preference signals. Synthesizing them is useful for any personalization use case.

#### 2b — salient_counts Normalization in Summarizer *(High ROI)*
**Goal:** Fix extraction fragility — natural language item lists don't produce reliable counts.
**Estimated lift:** +2-4pp on multi-session counting questions
**Cost:** $0 (prompt change, no extra calls)
**File:** `dory/pipeline/summarizer.py`

**The gap:** "I bought tomatoes, peppers, and three basil plants" — the current prompt extracts
`{"basil_plants": 3}` but misses tomatoes and peppers as countable items.

**Two changes:**
1. `_SUMMARY_SYSTEM_PROMPT` — Add: "When items appear in an enumeration or list, count each
   distinct named item as 1 even without an explicit number. 'tomatoes, peppers, and basil' = 3
   items (tomatoes: 1, peppers: 1, basil: 3 if stated). Budget: max 15 salient_count entries."
2. `_SUMMARY_USER_TEMPLATE` — Add explicit enumeration example showing expected output format.

#### 2c — SessionSummary Count Cross-Validation *(Data Integrity)*
**Goal:** Flag unverified salient_counts so the model doesn't anchor on wrong totals.
**Estimated lift:** +1-2pp (prevents anchoring on bad counts)
**Cost:** $0 (graph traversal, no LLM)
**Files:** `dory/pipeline/summarizer.py`, `dory/session.py`

**The gap:** When salient_counts is wrong (missed tomatoes, only counted cucumbers), the current
context says "trust the Counts fields" and the model anchors on the incomplete count.

**Two changes:**
1. In `Summarizer.summarize_session()`: after creating a SESSION_SUMMARY, walk all EVENT nodes
   linked via SUPPORTS_FACT edges and count how many mention the same entity as each salient_count
   key. If the graph EVENT count differs from salient_count by more than 1, add
   `"count_confidence": "low"` to `node.metadata`.
2. In `session.py` `_format_summary_block()`: render low-confidence counts with explicit warning:
   `"Counts: plants: 3 ⚠ low confidence — verify against session text below"`

#### 2d — Temporal Answer Prompt — Show Arithmetic Work
**Goal:** Reduce date math errors in temporal-reasoning questions.
**Estimated lift:** +2-3pp on temporal category
**Cost:** $0 (prompt change)
**File:** `benchmarks/longmemeval.py`

**The gap:** Model has correct dates but fails arithmetic (predicted 17 days ago, correct was 12).
The `_ANSWER_PROMPT_TEMPORAL` says "resolve relative expressions" but doesn't force step-by-step
calculation.

**Change to `_ANSWER_PROMPT_TEMPORAL`:**
Add: "For any date calculation, show your work explicitly in one line before your answer:
'Today: YYYY-MM-DD. Event: YYYY-MM-DD. Difference: N days.' Then give your final answer."

Note: This is primarily benchmark-specific. Real-world value depends on whether users ask
date-arithmetic questions.

#### 2e — Preference Questions Routed to Hybrid *(Moderate ROI)*
**Goal:** Ensure preference questions get both semantic PREFERENCE nodes AND episodic context.
**Estimated lift:** +2-3pp on preference category
**Cost:** $0 (routing change, no extra calls)
**File:** `dory/session.py`
**Risk:** May add noise — test on spot_micro before committing.

**The gap:** `_route_query()` sends preference questions to "graph" (spreading activation only).
But LongMemEval preference questions like "suggest recipes for my meal prep" need episodic context
(what has the user actually cooked before?) not just stated PREFERENCE nodes.

**Change:** Add `_PREFERENCE_RE` pattern matching:
```python
_PREFERENCE_RE = re.compile(
    r"\b(would I (?:like|enjoy|prefer)|suggest(?:ions)? for me|"
    r"based on (?:my|what I)|recommend for|what should I get|"
    r"what kind of .{0,20} (?:do|would) I|"
    r"any suggestions? for (?:my|me))\b",
    re.IGNORECASE,
)
```
When matched AND not already hybrid, route to `"hybrid"` to include episodic context.
**Gate:** Only apply if spot_micro test shows no regression on non-preference questions.

---

### Phase 3 — Validate All Fixes
**Cost:** ~$1.14 (stratified 40q Haiku/Haiku)
**Files:** run `benchmarks/longmemeval.py` on a fresh `spot_v5.json` (new stratified sample)

After implementing all Phase 2 fixes, run a new stratified 40-question sample (not spot_v4 — that's
been used for tuning and may be overfit). Use `compare_runs.py` against the v0.2 baseline.

**Target:** preference ≥ 38%, temporal ≥ 70%, multi-session ≥ 70%, overall ≥ 65%.

If targets met, proceed to full run. Full 500q run with Haiku/Haiku (~$14) is the minimum to
establish a credible v0.3 number. Sonnet/Sonnet (~$53) is needed to compare against the 66.8%
v0.1 Sonnet baseline — requires a credit top-up.

---

### Phase 4 — Merge, Release, Reposition
**Cost:** $0
**Time:** 2-3 hours

#### 4a — Merge v0.2-episodic to main
After Phase 0 confirms no regression. Tag `v0.2.0` on GitHub.

#### 4b — README Rewrite
- **Benchmark table:** Add footnote: "Mastra uses GPT-4o-mini on TypeScript. Dory uses
  claude-sonnet-4-6 on Python. Architecturally different stacks — not directly comparable."
  Add a Dory Haiku row to show cost/performance tradeoff.
- **Positioning:** Change framing to "best Python-native local-first agent memory library"
- **Roadmap:** Update `[x]` for all shipped items. Add real `[ ]` items for v0.3 work.
- **Add disclaimer:** "LongMemEval oracle split uses pre-filtered context. Production performance
  with live noisy conversations will differ."

#### 4c — PyPI Release
- Bump `pyproject.toml` to `0.2.0`
- Add `CHANGELOG.md`
- `python -m build && twine upload dist/*`

#### 4d — Ablation Documentation
- Write `benchmarks/ABLATION.md` with Phase 1 results
- Add link from README

---

### Phase 5 — Graph Topology Proof *(Differentiation)*
**Cost:** $0 (no benchmark runs needed)
**Goal:** Demonstrate what Dory does that Mastra/Zep/Mem0 cannot.

The review criticism "graph topology advantage unproven" is correct — LongMemEval rewards flat
episodic recall. The graph's unique value (provenance, semantic traversal, evolution queries,
contradiction detection) is invisible in LongMemEval scores.

Design 5-10 "topology-specific" demo queries:
- `"What was the first time I mentioned project X?"` — requires temporal chain traversal
- `"Which of my interests connect to each other?"` — requires semantic hop traversal
- `"What did I believe about Y before I changed my mind?"` — requires SUPERSEDES edge traversal
- `"How has my relationship with topic Z evolved?"` — requires TEMPORALLY_AFTER chain

Add these to a `demo_topology.py` script and a **Topology Advantage** section in the README.
This is the clearest way to show the architectural differentiation that the benchmark cannot measure.

---

### Phase 6 — Production Hardening *(Optional, Post-Adoption)*
**Deferred until there's usage evidence. Don't over-engineer before validation.**

- Opt-in episodic layer: `DoryMemory(use_episodic=True)` to control cost overhead
- Benchmark on S-split (longer sessions, harder)
- Stress test SQLite under multi-agent concurrent writes
- Extraction quality tests on real (non-oracle) conversation samples
- False memory / adversarial input handling

---

## Budget Summary

| Phase | Runs | Questions | Backend | Est. Cost |
|---|---|---|---|---|
| Phase 0: validation | 1 | 10 | Haiku/Haiku | ~$0.28 |
| Phase 1: ablation (2 runs) | 2 | 10 each | Haiku/Haiku | ~$0.30 |
| Phase 3: validation | 1 | 40 | Haiku/Haiku | ~$1.14 |
| Phase 3: full run (Haiku) | 1 | 500 | Haiku/Haiku | ~$14 |
| Phase 3: full run (Sonnet) | 1 | 500 | Sonnet/Sonnet | ~$53 |

**With ~$8-9 remaining:** Can complete Phase 0, 1, and 3 validation. Need top-up ($20+) for
full Sonnet run to get a comparable number to v0.1's 66.8%.

---

## Fix vs. Value Classification

| Fix | Benchmark value | General product value | Benchmark-specific? |
|---|---|---|---|
| Behavioral preference synthesis | High | High | No — general pattern |
| salient_counts normalization | High | High | No — extraction quality |
| Count cross-validation | Medium | High | No — data integrity |
| Temporal answer arithmetic | Medium | Low | Yes — prompt for benchmark |
| Preference → hybrid routing | Medium | Low | Mostly yes |
| Ablation study | Critical (credibility) | None | Yes |
| README fixes | None | High | No |
| PyPI release | None | High | No |
| Topology demo | None | High | No |

---

## Dependency Graph

```
Phase 0 (validation)
  └── Phase 1 (ablation) — needs clean baseline
        └── Phase 2 fixes (guided by ablation findings)
              └── Phase 3 (validate all fixes)
                    └── Phase 4a (merge to main)
                          ├── Phase 4b (README)
                          └── Phase 4c (PyPI)

Phase 5 (topology demo) — independent, can start any time
Phase 6 (production hardening) — deferred until adoption signals
```
