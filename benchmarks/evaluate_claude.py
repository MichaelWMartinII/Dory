#!/usr/bin/env python3
"""
LongMemEval evaluator using Claude as judge (drop-in for evaluate_qa.py).
Same prompts as the official script — no GPT-4o required.

Usage:
    python benchmarks/evaluate_claude.py predictions.jsonl data/longmemeval/longmemeval_oracle.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from collections import defaultdict
import anthropic

JUDGE_MODEL = "claude-haiku-4-5-20251001"

TEMPLATES = {
    "default": (
        "I will give you a question, a correct answer, and a response from a model. "
        "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
        "If the response is equivalent to the correct answer or contains all the intermediate steps "
        "to get the correct answer, you should also answer yes. If the response only contains a subset "
        "of the information required by the answer, answer no. "
        "\n\nQuestion: {q}\n\nCorrect Answer: {a}\n\nModel Response: {h}"
        "\n\nIs the model response correct? Answer yes or no only."
    ),
    "temporal-reasoning": (
        "I will give you a question, a correct answer, and a response from a model. "
        "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
        "If the response is equivalent to the correct answer or contains all the intermediate steps "
        "to get the correct answer, you should also answer yes. If the response only contains a subset "
        "of the information required by the answer, answer no. "
        "In addition, do not penalize off-by-one errors for the number of days. If the question asks "
        "for the number of days/weeks/months, etc., and the model makes off-by-one errors "
        "(e.g., predicting 19 days when the answer is 18), the model's response is still correct. "
        "\n\nQuestion: {q}\n\nCorrect Answer: {a}\n\nModel Response: {h}"
        "\n\nIs the model response correct? Answer yes or no only."
    ),
    "knowledge-update": (
        "I will give you a question, a correct answer, and a response from a model. "
        "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
        "If the response contains some previous information along with an updated answer, the response "
        "should be considered as correct as long as the updated answer is the required answer."
        "\n\nQuestion: {q}\n\nCorrect Answer: {a}\n\nModel Response: {h}"
        "\n\nIs the model response correct? Answer yes or no only."
    ),
    "single-session-preference": (
        "I will give you a question, a rubric for desired personalized response, and a response from a model. "
        "Please answer yes if the response satisfies the desired response. Otherwise, answer no. "
        "The model does not need to reflect all the points in the rubric. The response is correct as long as "
        "it recalls and utilizes the user's personal information correctly."
        "\n\nQuestion: {q}\n\nRubric: {a}\n\nModel Response: {h}"
        "\n\nIs the model response correct? Answer yes or no only."
    ),
    "_abstention": (
        "I will give you an unanswerable question, an explanation, and a response from a model. "
        "Please answer yes if the model correctly identifies the question as unanswerable. "
        "The model could say that the information is incomplete, or some other information is given "
        "but the asked information is not."
        "\n\nQuestion: {q}\n\nExplanation: {a}\n\nModel Response: {h}"
        "\n\nDoes the model correctly identify the question as unanswerable? Answer yes or no only."
    ),
}


def judge(client: anthropic.Anthropic, q: str, a: str, h: str, qtype: str, is_abstention: bool) -> bool:
    if is_abstention:
        tmpl = TEMPLATES["_abstention"]
    else:
        tmpl = TEMPLATES.get(qtype, TEMPLATES["default"])
    prompt = tmpl.format(q=q, a=a, h=h)
    resp = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=10,
        messages=[{"role": "user", "content": prompt}],
    )
    return "yes" in resp.content[0].text.strip().lower()


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python evaluate_claude.py predictions.jsonl reference.json")
        sys.exit(1)

    hyp_path = Path(sys.argv[1])
    ref_path = Path(sys.argv[2])

    hypotheses = [json.loads(l) for l in hyp_path.read_text().splitlines() if l.strip()]
    references = json.loads(ref_path.read_text())
    if isinstance(references, dict):
        references = references.get("data", [])

    qid2ref = {r["question_id"]: r for r in references}

    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY") or ""
    client = anthropic.Anthropic(api_key=api_key)

    by_type: dict[str, list[int]] = defaultdict(list)
    results = []

    for entry in hypotheses:
        qid = entry["question_id"]
        ref = qid2ref.get(qid)
        if not ref:
            print(f"  WARN: {qid} not in reference — skipping")
            continue

        qtype = ref["question_type"]
        q = ref["question"]
        a = ref["answer"]
        h = entry["hypothesis"]
        is_abs = "_abs" in qid

        correct = judge(client, q, a, h, qtype, is_abs)
        by_type[qtype].append(1 if correct else 0)
        results.append({**entry, "correct": correct, "answer": a})
        mark = "✓" if correct else "✗"
        print(f"  {mark} [{qtype}] {qid}")
        print(f"      Q: {q[:80]}")
        print(f"      A: {a}")
        print(f"      H: {h[:120]}")

    print()
    total = sum(sum(v) for v in by_type.values())
    count = sum(len(v) for v in by_type.values())
    print(f"Overall: {total}/{count} = {total/count:.1%}")
    for qtype, scores in sorted(by_type.items()):
        print(f"  {qtype}: {sum(scores)}/{len(scores)} = {sum(scores)/len(scores):.1%}")

    out_path = hyp_path.with_suffix(".eval.jsonl")
    out_path.write_text("\n".join(json.dumps(r) for r in results))
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
