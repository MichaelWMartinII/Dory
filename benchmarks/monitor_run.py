#!/usr/bin/env python3
"""
Monitor a running benchmark. Evaluates snapshots at 50-question milestones.
Kills the run if trajectory indicates a regression vs v0.8 baseline.

Usage: python3 benchmarks/monitor_run.py <predictions_file>
"""
import json, os, sys, subprocess, signal
from pathlib import Path

ROOT = Path(__file__).parent.parent
ORACLE = ROOT / "benchmarks/data/longmemeval/longmemeval_oracle.json"
EVAL_SCRIPT = ROOT / "benchmarks/evaluate_qa_claude.py"
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

V08 = {
    "knowledge-update":           0.872,
    "multi-session":              0.835,
    "single-session-assistant":   0.804,
    "single-session-user":        0.943,
    "temporal-reasoning":         0.827,
    "single-session-preference":  0.700,
}

# Kill threshold: this many pp below v0.8 overall, with >= MIN_Q evaluated
KILL_THRESHOLD_PP = 10.0
MIN_Q_TO_KILL = 100

def load_oracle():
    with open(ORACLE) as f:
        return {q["question_id"]: q for q in json.load(f)}

def count_preds(pred_file):
    try:
        return sum(1 for l in open(pred_file) if l.strip())
    except:
        return 0

def evaluate_snapshot(pred_file, snapshot_file, api_key):
    import shutil
    shutil.copy(pred_file, snapshot_file)
    result = subprocess.run(
        [sys.executable, str(EVAL_SCRIPT), str(snapshot_file), str(ORACLE),
         "--api-key", api_key],
        capture_output=True, text=True, timeout=600
    )
    eval_file = str(snapshot_file) + ".eval-results-claude-haiku-4-5-20251001"
    return eval_file if os.path.exists(eval_file) else None

def parse_eval(eval_file, oracle):
    evals = {}
    with open(eval_file) as f:
        for l in f:
            if l.strip():
                r = json.loads(l)
                evals[r["question_id"]] = r.get("autoeval_label", {}).get("label", False)

    by_type = {}
    for qid, correct in evals.items():
        qt = oracle.get(qid, {}).get("question_type", "unknown")
        by_type.setdefault(qt, [0, 0])
        by_type[qt][1] += 1
        if correct:
            by_type[qt][0] += 1

    total = sum(v[1] for v in by_type.values())
    correct = sum(v[0] for v in by_type.values())
    overall = correct / total if total else 0
    return overall, by_type, total

def kill_run(pred_file):
    stem = Path(pred_file).stem
    result = subprocess.run(
        ["pkill", "-f", stem], capture_output=True
    )
    print(f"  !! KILLED benchmark process (pkill -f {stem})")

def report(milestone, overall, by_type, v08=V08):
    bar = "█" * int(overall * 40)
    print(f"\n{'='*60}")
    print(f"MILESTONE: {milestone}q evaluated | Overall: {overall*100:.1f}% [{bar}]")
    print(f"vs v0.8 baseline 84.2% | Delta: {(overall-0.842)*100:+.1f}pp")
    print()
    for qt, (c, t) in sorted(by_type.items()):
        base = v08.get(qt)
        delta = f" ({c/t - base:+.1%})" if base and t >= 5 else " (n<5)"
        flag = " ⚠️" if base and t >= 5 and (c/t - base) < -0.12 else ""
        print(f"  {qt:<32} {c}/{t} = {c/t*100:.0f}%{delta}{flag}")
    print(f"{'='*60}\n")

def main():
    if len(sys.argv) < 2:
        print("Usage: monitor_run.py <predictions_file>")
        sys.exit(1)

    pred_file = Path(sys.argv[1])
    oracle = load_oracle()
    api_key = API_KEY or open(ROOT / ".env").read().split("ANTHROPIC_API_KEY=")[1].split()[0]

    evaluated_milestones = set()
    print(f"Monitoring: {pred_file.name}")
    print(f"Kill threshold: {KILL_THRESHOLD_PP}pp below v0.8 with >= {MIN_Q_TO_KILL}q evaluated")

    import time
    while True:
        n = count_preds(pred_file)
        milestone = (n // 50) * 50

        if milestone >= 50 and milestone not in evaluated_milestones and n >= milestone:
            evaluated_milestones.add(milestone)
            print(f"\n[{milestone}q] Evaluating snapshot...")
            snap = pred_file.parent / f"snap_{milestone}.jsonl"
            eval_file = evaluate_snapshot(pred_file, snap, api_key)

            if eval_file:
                overall, by_type, total = parse_eval(eval_file, oracle)
                report(milestone, overall, by_type)

                if total >= MIN_Q_TO_KILL:
                    delta = overall - 0.842
                    if delta < -(KILL_THRESHOLD_PP / 100):
                        print(f"\n❌ REGRESSION DETECTED: {overall*100:.1f}% is >{KILL_THRESHOLD_PP}pp below v0.8")
                        print(f"   Killing benchmark run to save credits.")
                        kill_run(pred_file)
                        sys.exit(1)
                    else:
                        print(f"✓ On track — continuing run")

            if milestone >= 500:
                print("\n✓ Run complete — all 500q evaluated")
                break

        time.sleep(120)  # check every 2 min

if __name__ == "__main__":
    main()
