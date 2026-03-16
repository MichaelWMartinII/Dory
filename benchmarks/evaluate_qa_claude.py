#!/usr/bin/env python3
"""
LongMemEval evaluator using Claude instead of GPT-4o.

Drop-in replacement for LongMemEval/src/evaluation/evaluate_qa.py that uses
the Anthropic API so you don't need an OpenAI key.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...

    python benchmarks/evaluate_qa_claude.py \
        benchmarks/predictions_oracle.jsonl \
        benchmarks/data/longmemeval/longmemeval_oracle.json \
        --model claude-haiku-4-5-20251001

    python benchmarks/LongMemEval/src/evaluation/print_qa_metrics.py \
        benchmarks/predictions_oracle.jsonl.eval-results-claude-haiku
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def get_anscheck_prompt(task: str, question: str, answer: str, response: str, abstention: bool = False) -> str:
    """Same prompts as the official LongMemEval evaluator."""
    if not abstention:
        if task in ["single-session-user", "single-session-assistant", "multi-session"]:
            template = (
                "I will give you a question, a correct answer, and a response from a model. "
                "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
                "If the response is equivalent to the correct answer or contains all the intermediate "
                "steps to get the correct answer, you should also answer yes. If the response only "
                "contains a subset of the information required by the answer, answer no. "
                "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}"
                "\n\nIs the model response correct? Answer yes or no only."
            )
        elif task == "temporal-reasoning":
            template = (
                "I will give you a question, a correct answer, and a response from a model. "
                "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
                "If the response is equivalent to the correct answer or contains all the intermediate "
                "steps to get the correct answer, you should also answer yes. If the response only "
                "contains a subset of the information required by the answer, answer no. "
                "In addition, do not penalize off-by-one errors for the number of days. "
                "If the question asks for the number of days/weeks/months, etc., and the model makes "
                "off-by-one errors (e.g., predicting 19 days when the answer is 18), the model's "
                "response is still correct. "
                "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}"
                "\n\nIs the model response correct? Answer yes or no only."
            )
        elif task == "knowledge-update":
            template = (
                "I will give you a question, a correct answer, and a response from a model. "
                "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
                "If the response contains some previous information along with an updated answer, "
                "the response should be considered as correct as long as the updated answer is the "
                "required answer."
                "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}"
                "\n\nIs the model response correct? Answer yes or no only."
            )
        elif task == "single-session-preference":
            template = (
                "I will give you a question, a rubric for desired personalized response, and a "
                "response from a model. Please answer yes if the response satisfies the desired "
                "response. Otherwise, answer no. The model does not need to reflect all the points "
                "in the rubric. The response is correct as long as it recalls and utilizes the "
                "user's personal information correctly."
                "\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}"
                "\n\nIs the model response correct? Answer yes or no only."
            )
        else:
            # Fallback for unknown types
            template = (
                "I will give you a question, a correct answer, and a response from a model. "
                "Please answer yes if the response contains the correct answer. Otherwise, answer no."
                "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}"
                "\n\nIs the model response correct? Answer yes or no only."
            )
    else:
        template = (
            "I will give you an unanswerable question, an explanation, and a response from a model. "
            "Please answer yes if the model correctly identifies the question as unanswerable. "
            "The model could say that the information is incomplete, or some other information is "
            "given but the asked information is not."
            "\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}"
            "\n\nDoes the model correctly identify the question as unanswerable? Answer yes or no only."
        )
    return template.format(question, answer, response)


def evaluate_with_claude(
    hyp_file: Path,
    ref_file: Path,
    model: str,
    api_key: str,
    verbose: bool = True,
    resume: bool = False,
) -> None:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    # Load predictions
    try:
        hypotheses = [json.loads(line) for line in hyp_file.read_text().splitlines() if line.strip()]
    except json.JSONDecodeError:
        hypotheses = json.loads(hyp_file.read_text())

    # Load references
    references = json.loads(ref_file.read_text())
    qid2data = {e["question_id"]: e for e in references}
    qid2type = {e["question_id"]: e["question_type"] for e in references}

    qtypes = set(qid2type.values())
    qtype2results: dict[str, list[int]] = {t: [] for t in qtypes}

    result_file = Path(str(hyp_file) + f".eval-results-{model.split('/')[-1]}")

    # Resume: load already-evaluated QIDs
    done_ids: set[str] = set()
    existing_logs: list[dict] = []
    if resume and result_file.exists():
        for line in result_file.read_text().splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                # Only count entries that were actually evaluated (not defaulted False on error)
                label_obj = entry.get("autoeval_label", {})
                if isinstance(label_obj, dict) and "label" in label_obj and not label_obj.get("_error"):
                    done_ids.add(entry["question_id"])
                    existing_logs.append(entry)
                    qtype = qid2type.get(entry["question_id"])
                    if qtype:
                        qtype2results.setdefault(qtype, []).append(1 if label_obj["label"] else 0)
            except Exception:
                pass
        print(f"  Resuming — {len(done_ids)} already evaluated")

    logs = list(existing_logs)
    correct = sum(1 for e in logs if e.get("autoeval_label", {}).get("label") is True)

    file_mode = "a" if resume and result_file.exists() else "w"
    with open(result_file, file_mode) as out_f:
        remaining = [e for e in hypotheses if e["question_id"] not in done_ids]
        total_to_eval = len(remaining)

        for i, entry in enumerate(remaining):
            qid = entry["question_id"]
            if qid not in qid2type:
                print(f"Warning: skipping {qid} (not in reference data)")
                continue

            qtype = qid2type[qid]
            question = qid2data[qid]["question"]
            answer = qid2data[qid]["answer"]
            hypothesis = entry["hypothesis"]
            abstention = "_abs" in qid

            prompt = get_anscheck_prompt(qtype, question, answer, hypothesis, abstention)

            label = False
            # Retry on rate limits; abort on auth/credit errors
            for attempt in range(5):
                try:
                    resp = client.messages.create(
                        model=model,
                        max_tokens=10,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    eval_text = resp.content[0].text.strip().lower()
                    label = "yes" in eval_text
                    break
                except anthropic.RateLimitError:
                    wait = 2 ** attempt
                    print(f"\n  Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                except anthropic.AuthenticationError as e:
                    print(f"\n  Authentication error: {e}")
                    print("  Check your API key and credit balance at console.anthropic.com")
                    sys.exit(1)
                except anthropic.PermissionDeniedError as e:
                    print(f"\n  Permission denied (likely out of credits): {e}")
                    print("  Add credits at console.anthropic.com/settings/billing")
                    sys.exit(1)
                except Exception as e:
                    err_str = str(e).lower()
                    if "credit" in err_str or "billing" in err_str or "insufficient" in err_str:
                        print(f"\n  Billing error: {e}")
                        print("  Add credits at console.anthropic.com/settings/billing")
                        sys.exit(1)
                    print(f"\n  Error on {qid}: {e}")
                    label = False
                    break

            entry["autoeval_label"] = {"model": model, "label": label}
            logs.append(entry)
            qtype2results.setdefault(qtype, []).append(1 if label else 0)
            if label:
                correct += 1

            out_f.write(json.dumps(entry) + "\n")
            out_f.flush()

            evaluated_total = len(done_ids) + i + 1
            pct = evaluated_total / len(hypotheses) * 100
            acc_so_far = correct / evaluated_total * 100
            print(f"\r  [{evaluated_total}/{len(hypotheses)}] {pct:.0f}% | Accuracy so far: {acc_so_far:.1f}%   ", end="", flush=True)

            if verbose and (i + 1) % 25 == 0:
                print(f"\n  --- {evaluated_total} done | Running accuracy: {acc_so_far:.1f}% ---")

    overall = correct / len(logs) if logs else 0
    print(f"\n\nFinal accuracy: {overall:.4f} ({correct}/{len(logs)})")
    print("\nBy question type:")
    for qtype, results in sorted(qtype2results.items()):
        if results:
            acc = sum(results) / len(results)
            print(f"  {qtype:<35} {acc:.4f}  (n={len(results)})")
    print(f"\nResults saved to: {result_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate LongMemEval predictions with Claude")
    parser.add_argument("hyp_file", type=Path, help="JSONL predictions file")
    parser.add_argument("ref_file", type=Path, help="LongMemEval reference JSON file")
    parser.add_argument("--model", default="claude-haiku-4-5-20251001",
                        help="Claude model for evaluation (default: claude-haiku-4-5-20251001)")
    parser.add_argument("--api-key", default=os.environ.get("ANTHROPIC_API_KEY"),
                        help="Anthropic API key (default: $ANTHROPIC_API_KEY)")
    parser.add_argument("--quiet", action="store_true", help="Less verbose output")
    parser.add_argument("--resume", action="store_true",
                        help="Skip questions already in output file (reuses valid results)")
    args = parser.parse_args()

    if not args.api_key:
        print("Error: ANTHROPIC_API_KEY not set. Use --api-key or export ANTHROPIC_API_KEY=...")
        sys.exit(1)

    evaluate_with_claude(
        hyp_file=args.hyp_file,
        ref_file=args.ref_file,
        model=args.model,
        api_key=args.api_key,
        verbose=not args.quiet,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
