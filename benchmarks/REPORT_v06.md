# Dory v0.6 — Full LongMemEval Report
**Date:** 2026-03-30 | **Dory version:** v0.6 (unreleased) | **Dataset:** LongMemEval oracle split, 500 questions

---

## Headline Result

**84.0% overall (420/500) — new best, +4.4pp over v0.5 (79.6%) and +3.4pp over v0.4 (80.6%).**

Every category improved. This is the first run where extraction was fully operational — prior runs had a silent `ANTHROPIC_API_KEY` misconfiguration that left the memory graph empty and produced ~40% naive retrieval. v0.6 is the first valid apples-to-apples comparison for the full pipeline.

The biggest winners: knowledge-update (+9.0pp), single-session-preference (+10.0pp), multi-session (+5.3pp). The supersedes chain and REFERENCE DATE hardening changes drove the knowledge-update recovery. Preference improvement likely traces to better extraction quality (Haiku actually running) rather than a targeted change.

---

## Version Comparison Table

| Version | Extract | Answer | n | Score | Notes |
|---|---|---|---|---|---|
| v0.3 | Sonnet | Sonnet (direct API) | 500 | 79.8% | Full context injection |
| v0.4 | Haiku | Claude Code (MCP) | 500 | 80.6% | Staged MCP retrieval |
| v0.5 | Haiku* | Claude Code (MCP) | 500 | 79.6% | *extraction broken — empty API key |
| **v0.6** | **Haiku** | **Claude Code (MCP)** | **500** | **84.0%** | First clean full-pipeline run |

*v0.5's Haiku extraction silently failed on every question (empty API key passed to `anthropic.Anthropic()`). The DB was empty; Claude returned "I don't have any memories" for ~75% of questions. The 79.6% score reflects retrieval from session summaries only — not a meaningful extraction baseline.

---

## Per-Category Breakdown

| Category | v0.3 | v0.4 | v0.5 | **v0.6** | Δ v5→v6 | n |
|---|---|---|---|---|---|---|
| knowledge-update | 84.6% | 89.7% | 78.2% | **87.2%** | **+9.0** | 78 |
| multi-session | 80.5% | 79.7% | 78.9% | **84.2%** | **+5.3** | 133 |
| single-session-assistant | 87.5% | 83.9% | 89.3% | **92.9%** | **+3.6** | 56 |
| single-session-preference | 46.7% | 63.3% | 60.0% | **70.0%** | **+10.0** | 30 |
| single-session-user | 88.6% | 92.9% | 91.4% | **92.9%** | **+1.5** | 70 |
| temporal-reasoning | 75.9% | 72.2% | 75.2% | **76.7%** | **+1.5** | 133 |
| **TOTAL** | **79.8%** | **80.6%** | **79.6%** | **84.0%** | **+4.4** | **500** |

---

## What Drove Each Win

### Knowledge-update: 78.2% → 87.2% (+9.0pp)

v0.5 had 17 failures; v0.6 has 10. The recovery maps directly to two v0.6 changes:

**`supersedes_hint` in Observer extraction.** The Observer now detects update language ("I switched to X", "now it's Y instead of Z") during extraction and writes a SUPERSEDES edge from the new node to the archived old one. In v0.5, both the old and new values competed in activation; the old value frequently won because it had higher activation_count (seen earlier, reinforced more). v0.6 archives the old node and surfaces the new one as `[CURRENT VALUE]` in the serialized context. The mortgage pre-approval failure from v0.5 ($350k retrieved instead of $400k) is fixed.

**Hardened REFERENCE DATE prompt.** The v0.5 bug where duration calculations ("how long have I had X?") used the model's internal clock (March 2026) instead of the injected question_date is substantially mitigated. The v0.6 prompt explicitly says:
```
- Durations ('how long have I had X'): (REFERENCE DATE) minus (start date from memory)
```

Remaining 10 failures include: off-by-one values (38 vs 37 coins, 7 PM vs 6 PM gym time), a relocation case where two locations appear in memory (suburbs vs Chicago), and 3 cases where the supersedes chain didn't form because the update language was too implicit for the extractor to flag.

### multi-session: 78.9% → 84.2% (+5.3pp)

21 failures remain, almost all counting/aggregation:

- "How many items of clothing do I need to pick up?" → Got 2, answer is 3
- "How many plants did I acquire in the last month?" → Got 2, answer is 3
- "How many hours have I spent playing games in total?" → Got wrong total
- "How many projects have I led?" → Got 3, answer is 2

The SESSION_SUMMARY aggregation improvements (summing `salient_counts` across sessions) helped but didn't eliminate counting errors. The model still miscounts when instances are spread across many low-salience nodes that don't all surface in a single query. The `AGGREGATED TOTALS` prefix in the context block is being used for some questions but missed for others.

### single-session-preference: 60.0% → 70.0% (+10.0pp)

This improvement is likely driven by working extraction rather than a targeted preference fix. When the graph is empty, preference questions fail completely. With properly extracted PREFERENCE nodes, the model can apply stored preferences to new scenarios.

9 failures remain. Breakdown by inspection:
- **~5 evaluator mismatch** — answer is substantively correct but doesn't match the rubric's expected form ("The user would prefer responses that...")
- **~3 retrieval miss** — `dory_query` didn't surface the relevant preference node ("I don't have any memories of your watch history")
- **~1 genuine gap** — preference never established in the conversation

Estimated true accuracy: ~75–80%, consistent with prior estimates.

### single-session-assistant: 89.3% → 92.9% (+3.6pp)

4 failures, all close calls:

- "27th parameter from a 100-prompt-parameter list" → Memory captured a summary of the session, not the raw list. The specific 27th item was lost during summarization.
- "Doc Martin" → Got the correct answer, evaluator rejected it (hypothesis adds context the judge penalized).
- Two others: retrieval miss and evaluator mismatch.

This category is effectively at ceiling for the current architecture. The remaining failures require either verbatim recall from long lists (which the summarizer intentionally compresses) or edge cases in the judge.

### temporal-reasoning: 75.2% → 76.7% (+1.5pp)

31 failures. The temporal improvement is modest — the REFERENCE DATE hardening helped duration calculations but didn't address the two remaining failure modes:

**Day-count arithmetic errors.** The model finds the correct dates but miscounts the interval. "How many days passed between March 15 and March 19?" answers 3 instead of 4 (or 4 instead of 5 inclusive). The inclusive counting rule helps for clean examples but the model is inconsistent on harder cases.

**Counting across sessions.** "Which airline did I fly the most in March and April?" requires enumerating all flight mentions across sessions and tallying. The model retrieves some but not all instances.

**Relative ordering with no explicit dates.** "Which happened first, the road trip or the lens arriving?" requires either explicit timestamps or relative language in the session summaries. When both events happened in the same session-date bucket, ordering is ambiguous.

---

## Failure Taxonomy

Total failures: 80/500 (16.0%)

| Category | Failures | Miss Rate |
|---|---|---|
| temporal-reasoning | 31/133 | 23.3% |
| multi-session | 21/133 | 15.8% |
| single-session-preference | 9/30 | 30.0% |
| knowledge-update | 10/78 | 12.8% |
| single-session-user | 5/70 | 7.1% |
| single-session-assistant | 4/56 | 7.1% |

Temporal + multi-session = **65% of failures** (52/80), same proportion as v0.5.

Estimated failure type breakdown:

| Type | Est. Count | Notes |
|---|---|---|
| **Counting / aggregation miss** | ~20 | Multi-session totals wrong |
| **Temporal arithmetic** | ~15 | Day math, duration anchor |
| **Retrieval miss** | ~15 | Memory exists but not surfaced |
| **Evaluator mismatch** | ~15 | Correct answer, judge rejected |
| **Supersession miss** | ~8 | Implicit update not detected |
| **Genuine gap** | ~7 | Information absent from graph |

---

## Run Notes

Clean single-pass run, no interruptions, no errors. 500/500 completed overnight (~7.5 hours, ~98s/question). The per-question time breaks down as: Observer extraction ~40s (multiple Haiku calls per session), Summarizer ~20s, `claude -p` subprocess ~35s.

**Actual cost: ~$45** (started at $72.85, finished with ~$28 remaining). Prior $25 estimate was based on runs with broken extraction. Corrected rule of thumb: **$0.09/q Haiku extraction + $0.06/q answer = ~$0.15/q, ~$75 for 500q**.

---

## v0.7 Targets (by impact)

**1. Multi-session counting (~20 failures)**
The aggregation path works but is brittle — the model misses instances when they're in low-salience nodes or across many sessions. A dedicated counting pass: after `dory_query`, force 2–3 additional queries with count-specific terms and sum explicitly before answering.

**2. Temporal day-count consistency (~15 failures)**
The inclusive counting rule is in the type hint but applied inconsistently. Add an explicit worked example in the system prompt: "Jan 10 to Jan 17 = 7 days exclusive, 8 days inclusive. Always state which convention you're using." The few-shot anchor reduces variance on ambiguous cases.

**3. Retrieval miss for preference/single-session (~15 failures)**
Some preference and single-session nodes aren't surfacing because `dory_query` is called with the question itself rather than extracted keywords. Prompt Claude to break compound questions into 2–3 focused keyword queries before retrieving.

**4. Hard salience floor (deferred from v0.6)**
Drop nodes below salience threshold in `activation.serialize()` before injection. Low-signal nodes currently compete with high-signal ones in the context window. A floor of `salience < 0.1` could reduce noise without meaningful recall loss.

**5. Observer: implicit supersession detection**
3–5 knowledge-update failures trace to updates where the user didn't explicitly say "switched" or "changed" — e.g., a new value is mentioned alongside the old one without explicit update language. The extractor should infer supersession from value-type conflicts (new number replacing old number for same entity).

---

## Conclusion

Dory v0.6 scores 84.0% on LongMemEval — a genuine +4.4pp improvement over v0.5 and new best across all versions. The supersedes chain and REFERENCE DATE hardening delivered their predicted gains on knowledge-update. The preference improvement was an extraction quality bonus. Temporal and multi-session counting remain the two dominant failure modes, accounting for 65% of remaining errors. Both are tractable with targeted prompting changes in v0.7.

The path to 87–88% is through fixing multi-session counting and temporal day-math consistency. The 90% barrier requires addressing the ~15 evaluator mismatches, which may not be solvable through Dory changes alone.
