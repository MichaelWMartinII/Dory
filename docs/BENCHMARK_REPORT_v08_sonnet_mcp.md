# Dory Benchmark Report — v0.8 Sonnet+MCP
**Date:** 2026-04-07  
**Run:** `predictions_v08_sonnet_mcp_full.jsonl`  
**Config:** Sonnet extraction (`claude-sonnet-4-6`) + claude-code-mcp answering  
**Judge:** Haiku (`claude-haiku-4-5-20251001`)  
**Dataset:** LongMemEval Oracle (500 questions)

---

## Overall Result

| Metric | Score |
|--------|-------|
| **Overall** | **84.2% (421/500)** |

Ties v0.7.0's best-ever score. Correct hypothesis: Sonnet extraction + agentic (claude-code-mcp) answering = same ceiling as Haiku extraction + agentic answering, with material category-level trade-offs.

---

## Category Breakdown

| Category | v0.5 | v0.6 | v0.7 (best) | v0.8-API (regression) | **v0.8-MCP (this run)** | Δ vs v0.7 |
|---|---|---|---|---|---|---|
| **Overall** | 79.6% | 84.0% | 84.2% | 80.6% | **84.2%** | — |
| knowledge-update | — | — | 92.3% | 78.2% | **87.2%** | -5.1pp |
| multi-session | — | — | 85.7% | 75.2% | **83.5%** | -2.2pp |
| single-session-assistant | — | — | 92.9% | — | **80.4%** | -12.5pp |
| single-session-user | — | — | 94.3% | — | **94.3%** | — |
| temporal-reasoning | — | — | 75.2% | 84.2% | **82.7%** | +7.5pp |
| preference | — | — | 56.7% | — | **70.0%** | +13.3pp |
| abstention | — | — | 66.7% | 70.0% | **73.3%** | +6.6pp |

---

## What Changed

### Configuration
- **Extractor:** `claude-haiku-4-5-20251001` → `claude-sonnet-4-6`
- **Answering backend:** `claude-code-mcp` (same as v0.7) — agentic, multi-query capable
- **Code:** v0.8 branch (WORKING node, temporal chronological ordering, `flush()` → `consolidate()`)

### Key difference from the v0.8-API regression run
The previous v0.8 run (80.6%) changed **both** extractor AND answering backend simultaneously. That run used the Anthropic API for answering — static one-shot context, no ability to re-query. This run restores the agentic answering backend, confirming the regression was caused by the answer backend switch, not the Sonnet extractor.

---

## Analysis

### Gains

**Temporal-reasoning: +7.5pp (75.2% → 82.7%)**  
Most meaningful improvement. Sonnet reliably extracts explicit dates from conversations and anchors them to `event_date` metadata. Haiku was inconsistent here — it would extract an event but omit or blur the date. With better-dated nodes, the temporal context builder can sort chronologically and Claude can do accurate arithmetic.

**Preference: +13.3pp (56.7% → 70.0%)**  
Second-largest gain. Sonnet is better at recognizing implicit preferences ("I've always found X annoying", "I tend to prefer Y") and storing them as PREFERENCE nodes vs. just burying them in SESSION summaries. The preference routing code (`_PREFERENCE_RE`, `_preference_context()`) was already in place — Sonnet just feeds it better raw material.

**Abstention: +6.6pp (66.7% → 73.3%)**  
Abstention questions require the model to correctly say "I don't have that information." Sonnet extraction appears to produce cleaner, more bounded graphs — when information genuinely isn't there, the context reflects its absence more clearly instead of hallucinating partial matches.

### Regressions

**Single-session-assistant: -12.5pp (92.9% → 80.4%)**  
Most alarming regression. These questions ask about things Claude (the assistant) said in a prior session — advice given, recommendations made. Haiku may extract these as direct quotes or paraphrases with high fidelity. Sonnet may be over-abstracting or interpreting rather than faithfully preserving the assistant utterances. Worth a targeted extraction audit on known failures here.

**Knowledge-update: -5.1pp (92.3% → 87.2%)**  
Knowledge-update questions require the model to supersede an earlier fact with a later one ("I used to X, now I Y"). Sonnet extraction may be disrupting SUPERSEDES chains — possibly by rephrasing nodes in ways that prevent the implicit supersession detector from linking them, or by generating more nodes that create noise around the updated fact.

**Multi-session: -2.2pp (85.7% → 83.5%)**  
Small but consistent. Likely same root cause as knowledge-update: cross-session supersession chains are noisier with Sonnet extraction. Also possible that Sonnet produces longer, more detailed nodes that crowd the context window and reduce signal density.

---

## Key Findings

### 1. Agentic answering is non-negotiable
The v0.8-API run proved it: switching from claude-code-mcp to a static API call dropped overall score 3.6pp. The multi-query capability of claude-code-mcp — where Claude can call `dory_query()` multiple times, reformulate, and synthesize — is load-bearing for knowledge-update and multi-session categories. This is not a cost optimization; it is a qualitatively different answering mechanism.

### 2. Sonnet extraction trades recall for precision
Haiku extracts fast and slightly fuzzily. Sonnet extracts more carefully and accurately, which helps temporal and preference (where accuracy matters) but hurts knowledge-update and single-session-assistant (where verbatim fidelity and chain integrity matter). The optimal extractor may be task-type dependent.

### 3. The ceiling appears to be around 84–85% with current architecture
Three runs at this ceiling: v0.6 (84.0%), v0.7 (84.2%), v0.8-MCP (84.2%). Different extractors, same result. The bottleneck is probably not extraction quality — it's retrieval architecture. The current system uses regex routing (`_TEMPORAL_RE`, `_PREFERENCE_RE`), hard thresholds (salience floor, supersession score), and separate code paths per query type. Each heuristic was added to fix a specific failure and they interact unpredictably.

### 4. Preference is solvable but not yet solved
70% is a real improvement from 56.7%, but still the weakest non-abstention category. Two remaining gaps: (a) extraction quality — implicit preferences still missed by both models, (b) salience floor — single-session PREFERENCE nodes (activation_count=1) get filtered before retrieval. WORKING node type (seeds at activation_count=2) would address (b).

---

## Version History

| Version | Score | Extract | Answer | Notes |
|---|---|---|---|---|
| v0.5 | 79.6% | Haiku | claude-code-mcp | Baseline agentic run |
| v0.6 | 84.0% | Haiku | claude-code-mcp | +4.4pp, preference routing, SUPERSEDES |
| v0.7 | **84.2%** | Haiku | claude-code-mcp | WORKING node, temporal ordering |
| v0.8-API | 80.6% | Sonnet | Anthropic API | Regression — static answering |
| **v0.8-MCP** | **84.2%** | Sonnet | claude-code-mcp | Confirms agentic answering is load-bearing |

---

## What to Try Next (when resuming)

**High-priority experiments:**
1. **Unified retrieval path** — remove regex routing, use spreading activation → top-k → single LLM reasoning step. Graph metadata (node types, SUPERSEDES edges, dates) becomes the signal. Mastra achieves 94.87% with this approach. This is the most likely path to breaking 85%.
2. **WORKING node type** — seeds at activation_count=2, clears salience floor for single-session facts. Would fix preference abstention and reduce noise in knowledge-update. Already on the v0.8 branch as a code change, not yet benchmarked.
3. **Single-session-assistant failure audit** — spot-check 10 known failures to determine if Sonnet is over-abstracting assistant utterances. If confirmed, consider Haiku extraction for that question type only, or add verbatim-preservation instructions to the Observer prompt.
4. **Relative salience floor** — replace absolute floor (0.1) with percentile-based (bottom 20% pruned). Less brittle than a magic number.

**Do not do:**
- Another full 500q Sonnet+API run — that experiment is done and the answer is known.
- Changing extractor and answer backend in the same run — always one variable at a time.

---

## Cost Reference

| Component | Model | Approx. cost |
|---|---|---|
| Extraction (500q) | Sonnet | ~$15–20 |
| Answering (500q) | claude-code-mcp (subscription) | ~$10–15 equiv. |
| Evaluation (500q) | Haiku | ~$2–3 |
| **Total** | | **~$25–38** |

*Multiple resume cycles due to claude-code-mcp session limits added overhead. Future runs: budget for 3–4 resume cycles or investigate rate limit mitigation.*
