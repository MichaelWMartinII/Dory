"""
Anthropic-backed evaluator for LongMemEval predictions.
Drop-in replacement for evaluate_qa.py when no OpenAI key is available.

Usage:
    python3 benchmarks/evaluate_anthropic.py \
        benchmarks/predictions_pref_v37.jsonl \
        benchmarks/spot_preference.json \
        --model claude-haiku-4-5-20251001 \
        --api-key "$ANTHROPIC_API_KEY"
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import anthropic
import numpy as np


def get_anscheck_prompt(task: str, question: str, answer: str, response: str, abstention: bool = False) -> str:
    if not abstention:
        if task in ("single-session-user", "single-session-assistant", "multi-session"):
            t = ("I will give you a question, a correct answer, and a response from a model. "
                 "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
                 "If the response is equivalent to the correct answer or contains all the intermediate steps "
                 "to get the correct answer, you should also answer yes. If the response only contains a subset "
                 "of the information required by the answer, answer no. "
                 "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}"
                 "\n\nIs the model response correct? Answer yes or no only.")
        elif task == "temporal-reasoning":
            t = ("I will give you a question, a correct answer, and a response from a model. "
                 "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
                 "If the response is equivalent to the correct answer or contains all the intermediate steps "
                 "to get the correct answer, you should also answer yes. If the response only contains a subset "
                 "of the information required by the answer, answer no. In addition, do not penalize off-by-one "
                 "errors for the number of days. "
                 "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}"
                 "\n\nIs the model response correct? Answer yes or no only.")
        elif task == "knowledge-update":
            t = ("I will give you a question, a correct answer, and a response from a model. "
                 "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
                 "If the response contains some previous information along with an updated answer, the response "
                 "should be considered as correct as long as the updated answer is the required answer."
                 "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}"
                 "\n\nIs the model response correct? Answer yes or no only.")
        elif task == "single-session-preference":
            t = ("I will give you a question, a rubric for desired personalized response, and a response from a model. "
                 "Please answer yes if the response satisfies the desired response. Otherwise, answer no. "
                 "The model does not need to reflect all the points in the rubric. The response is correct as long "
                 "as it recalls and utilizes the user's personal information correctly."
                 "\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}"
                 "\n\nIs the model response correct? Answer yes or no only.")
        else:
            raise NotImplementedError(f"Unknown task type: {task}")
    else:
        t = ("I will give you an unanswerable question, an explanation, and a response from a model. "
             "Please answer yes if the model correctly identifies the question as unanswerable. "
             "The model could say that the information is incomplete, or some other information is given "
             "but the asked information is not."
             "\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}"
             "\n\nDoes the model correctly identify the question as unanswerable? Answer yes or no only.")
    return t.format(question, answer, response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("hyp_file")
    parser.add_argument("ref_file")
    parser.add_argument("--model", default="claude-haiku-4-5-20251001")
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()

    api_key = args.api_key or os.getenv("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=api_key)

    with open(args.hyp_file) as f:
        hypotheses = [json.loads(line) for line in f]
    with open(args.ref_file) as f:
        references = json.load(f)

    qid2qdata = {e["question_id"]: e for e in references}
    qid2qtype = {e["question_id"]: e["question_type"] for e in references}
    qtypes = set(qid2qtype.values())
    qtype2acc: dict[str, list[int]] = {t: [] for t in qtypes}

    result_file = args.hyp_file + f".eval-results-{args.model}"
    logs = []

    with open(result_file, "w") as out_f:
        for i, entry in enumerate(hypotheses, 1):
            qid = entry["question_id"]
            if qid not in qid2qtype:
                print(f"Warning: skipping {qid} — not in reference data")
                continue

            qtype = qid2qtype[qid]
            q = qid2qdata[qid]["question"]
            ans = qid2qdata[qid]["answer"]
            hyp = entry["hypothesis"]
            abstention = "_abs" in qid

            prompt = get_anscheck_prompt(qtype, q, ans, hyp, abstention)
            resp = client.messages.create(
                model=args.model,
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}],
            )
            eval_response = resp.content[0].text.strip()
            label = "yes" in eval_response.lower()

            entry["autoeval_label"] = {"model": args.model, "label": label}
            logs.append(entry)
            qtype2acc[qtype].append(1 if label else 0)
            print(f"[{i}/{len(hypotheses)}] {qid} → {'✓' if label else '✗'}  ({qtype})", flush=True)
            print(json.dumps(entry), file=out_f)

    overall = round(float(np.mean([1 if x["autoeval_label"]["label"] else 0 for x in logs])), 4)
    print(f"\nAccuracy: {overall}")
    for k, v in qtype2acc.items():
        print(f"\t{k}: {round(float(np.mean(v)), 4)} ({len(v)})")
    print(f"Saved to {result_file}")


if __name__ == "__main__":
    main()
