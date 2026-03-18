#!/usr/bin/env python3
"""
Compare two benchmark prediction runs question-by-question.

Usage:
    python benchmarks/compare_runs.py \
        benchmarks/predictions_spot_v4.jsonl.eval-results-claude-haiku-4-5-20251001 \
        benchmarks/predictions_spot_v4_v2.jsonl.eval-results-claude-haiku-4-5-20251001 \
        --questions benchmarks/spot_v4.json \
        --labels v0.1 v0.2
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict


def load_results(path: Path) -> dict[str, bool]:
    results = {}
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            results[r["question_id"]] = r["autoeval_label"]["label"]
    return results


def load_questions(path: Path) -> dict[str, dict]:
    with open(path) as f:
        data = json.load(f)
    return {q["question_id"]: q for q in data}


def summarize(labels: dict[str, bool], question_types: dict[str, str]) -> dict:
    by_type: dict[str, list[bool]] = defaultdict(list)
    for qid, label in labels.items():
        qt = question_types.get(qid, "unknown")
        by_type[qt].append(label)
    return by_type


def main():
    parser = argparse.ArgumentParser(description="Compare two benchmark runs")
    parser.add_argument("baseline", type=Path, help="Baseline eval-results file (v0.1)")
    parser.add_argument("new", type=Path, help="New eval-results file (v0.2)")
    parser.add_argument("--questions", type=Path, required=True, help="Questions JSON")
    parser.add_argument("--labels", nargs=2, default=["baseline", "new"],
                        metavar=("LABEL_A", "LABEL_B"))
    args = parser.parse_args()

    label_a, label_b = args.labels
    a = load_results(args.baseline)
    b = load_results(args.new)
    questions = load_questions(args.questions)
    question_types = {qid: q["question_type"] for qid, q in questions.items()}

    shared = sorted(set(a) & set(b))
    if not shared:
        print("No shared question IDs found.", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # Overall
    # ------------------------------------------------------------------ #
    a_correct = sum(a[qid] for qid in shared)
    b_correct = sum(b[qid] for qid in shared)
    n = len(shared)

    print(f"\n{'='*60}")
    print(f"  {label_a}: {a_correct}/{n} = {a_correct/n*100:.1f}%")
    print(f"  {label_b}: {b_correct}/{n} = {b_correct/n*100:.1f}%")
    delta = (b_correct - a_correct) / n * 100
    sign = "+" if delta >= 0 else ""
    print(f"  delta:  {sign}{delta:.1f}pp  ({b_correct - a_correct:+d} questions)")
    print(f"{'='*60}\n")

    # ------------------------------------------------------------------ #
    # By question type
    # ------------------------------------------------------------------ #
    a_by_type = summarize({qid: a[qid] for qid in shared}, question_types)
    b_by_type = summarize({qid: b[qid] for qid in shared}, question_types)
    all_types = sorted(set(a_by_type) | set(b_by_type))

    print(f"{'Question Type':<35} {label_a:>8}  {label_b:>8}  {'Delta':>7}")
    print("-" * 62)
    for qt in all_types:
        a_labels = a_by_type.get(qt, [])
        b_labels = b_by_type.get(qt, [])
        if not a_labels and not b_labels:
            continue
        a_pct = sum(a_labels) / len(a_labels) * 100 if a_labels else 0
        b_pct = sum(b_labels) / len(b_labels) * 100 if b_labels else 0
        d = b_pct - a_pct
        sign = "+" if d >= 0 else ""
        print(f"  {qt:<33} {a_pct:>6.0f}%   {b_pct:>6.0f}%   {sign}{d:.0f}pp")
    print()

    # ------------------------------------------------------------------ #
    # Individual changes
    # ------------------------------------------------------------------ #
    fixed = [qid for qid in shared if not a[qid] and b[qid]]
    broken = [qid for qid in shared if a[qid] and not b[qid]]
    both_pass = [qid for qid in shared if a[qid] and b[qid]]
    both_fail = [qid for qid in shared if not a[qid] and not b[qid]]

    print(f"  Fixed ({len(fixed)}):    {label_a} FAIL → {label_b} PASS")
    for qid in fixed:
        qt = question_types.get(qid, "?")
        q = questions.get(qid, {}).get("question", "")[:60]
        print(f"    [{qt}] {qid}: {q}")

    print(f"\n  Broken ({len(broken)}):   {label_a} PASS → {label_b} FAIL")
    for qid in broken:
        qt = question_types.get(qid, "?")
        q = questions.get(qid, {}).get("question", "")[:60]
        ans = questions.get(qid, {}).get("answer", "")
        hyp_b = b.get(qid)
        print(f"    [{qt}] {qid}: {q}")
        print(f"      correct: {ans}")

    print(f"\n  Both pass: {len(both_pass)}  |  Both fail: {len(both_fail)}")
    print()


if __name__ == "__main__":
    main()
