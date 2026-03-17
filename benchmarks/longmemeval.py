#!/usr/bin/env python3
"""
LongMemEval benchmark runner for Dory.

Evaluates Dory's memory retrieval on the LongMemEval dataset (ICLR 2025).
https://arxiv.org/abs/2410.10813

Usage:
    # Download dataset first (oracle split is 15MB, fast to run):
    #   huggingface-cli download xiaowu0162/longmemeval-cleaned --repo-type dataset --local-dir data/longmemeval

    python benchmarks/longmemeval.py \
        --data data/longmemeval/longmemeval_oracle.json \
        --output benchmarks/predictions_oracle.jsonl \
        --extract-model qwen3:8b \
        --answer-model qwen3:14b \
        --backend ollama

    # After generating predictions, evaluate with the official LongMemEval script:
    #   cd LongMemEval/src/evaluation
    #   python evaluate_qa.py gpt-4o ../../../benchmarks/predictions_oracle.jsonl \\
    #       ../../../data/longmemeval/longmemeval_oracle.json
    #   python print_qa_metrics.py predictions_oracle.jsonl.log

Notes:
    - Each question gets a fresh isolated graph (no cross-contamination between questions)
    - The oracle split tests reading + retrieval on filtered context (~15k tokens each)
    - The S split (~115k tokens) better demonstrates spreading activation's value
    - Evaluation judge requires GPT-4o or Claude (see --judge-backend)
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# LLM answer generation
# ---------------------------------------------------------------------------

_ANSWER_PROMPT_DEFAULT = """\
You are answering a question about a person based on their conversation history.
Use only the provided memory context — do not make up information.
If the context doesn't contain enough information to answer confidently, say so briefly.
Give a concise, direct answer.

Memory context:
{context}

Question: {question}

Answer:"""

_ANSWER_PROMPT_TEMPORAL = """\
You are answering a question about the timing or order of events from a person's conversation history.

SESSION memories below have date prefixes like [YYYY-MM-DD]. Use these dates to determine
order and duration. Show your date comparison explicitly before giving your final answer.

Memory context:
{context}

Question: {question}

Answer (compare dates explicitly, then give a direct answer):"""

_ANSWER_PROMPT_MULTI_SESSION = """\
You are answering a question that may require finding information across multiple conversations.

Search ALL memories below — including every SESSION entry. For counting or listing questions,
find every relevant instance before answering. Do not stop at the first match.

Memory context:
{context}

Question: {question}

Answer (check all sessions, then give a direct answer):"""

_ANSWER_PROMPT_KNOWLEDGE_UPDATE = """\
You are answering a question about a person's current situation based on their conversation history.

If you see a [KNOWLEDGE UPDATE] in the memories, use the UPDATED value, not the original.
Always prefer the most recent information.

Memory context:
{context}

Question: {question}

Answer:"""

_ANSWER_PROMPT_SESSION = """\
You are answering a question about what happened or was said in a specific conversation.

The answer is likely in a SESSION memory. Look for the specific detail asked about:
exact names, numbers, items, colors, recommendations, or things the assistant said.

Memory context:
{context}

Question: {question}

Answer:"""

_ANSWER_PROMPTS = {
    "temporal-reasoning": _ANSWER_PROMPT_TEMPORAL,
    "multi-session": _ANSWER_PROMPT_MULTI_SESSION,
    "knowledge-update": _ANSWER_PROMPT_KNOWLEDGE_UPDATE,
    "single-session-user": _ANSWER_PROMPT_SESSION,
    "single-session-assistant": _ANSWER_PROMPT_SESSION,
    "single-session-preference": _ANSWER_PROMPT_SESSION,
}


def _get_prompt(question: str, context: str, question_type: str) -> str:
    template = _ANSWER_PROMPTS.get(question_type, _ANSWER_PROMPT_DEFAULT)
    return template.format(context=context, question=question)


def _answer_ollama(question: str, context: str, model: str, question_type: str = "") -> str:
    import ollama
    resp = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": _get_prompt(question, context, question_type)}],
        options={"temperature": 0.0},
    )
    return resp["message"]["content"].strip()


def _answer_anthropic(question: str, context: str, model: str, api_key: str, question_type: str = "") -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=512,
        messages=[{"role": "user", "content": _get_prompt(question, context, question_type)}],
    )
    return resp.content[0].text.strip()


def _answer_openai(question: str, context: str, model: str, base_url: str, api_key: str, question_type: str = "") -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": _get_prompt(question, context, question_type)}],
        temperature=0.0,
        max_tokens=512,
    )
    return resp.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

def load_dataset(path: Path) -> list[dict]:
    """Load LongMemEval JSON dataset."""
    with open(path) as f:
        data = json.load(f)
    # Handle both list format and dict-with-data format
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    raise ValueError(f"Unexpected dataset format in {path}")


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def run_item(
    item: dict,
    extract_model: str,
    answer_model: str,
    backend: str,
    base_url: str,
    api_key: str,
    verbose: bool = False,
    use_dory: bool = True,
) -> dict:
    """
    Process one LongMemEval item.

    Two modes:
    - use_dory=True  (default): feed sessions through Dory Observer, query with
                                spreading activation, answer from retrieved context.
    - use_dory=False (--no-dory): flatten all sessions into raw context and answer
                                  directly. Useful as a baseline / cheaper run.
    """
    from dory.graph import Graph
    from dory.pipeline.observer import Observer
    from dory.pipeline.summarizer import Summarizer
    from dory import session

    question_id = item.get("question_id") or item.get("id", "unknown")
    question = item.get("question", "")
    question_type = item.get("question_type", "")
    sessions = item.get("haystack_sessions") or item.get("history", [])
    haystack_dates = item.get("haystack_dates") or []

    # Flatten sessions into turns
    all_turns: list[dict] = []
    for session_data in sessions:
        if isinstance(session_data, list):
            all_turns.extend(session_data)
        elif isinstance(session_data, dict):
            all_turns.append(session_data)

    if use_dory:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "bench.db"
            g = Graph(path=db_path)

            obs = Observer(
                g,
                db_path=db_path,
                model=extract_model,
                backend=backend,
                base_url=base_url,
                api_key=api_key,
                threshold=6,
                confidence_floor=0.65,
            )

            for turn in all_turns:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if content:
                    obs.add_turn(role, content)

            obs.flush()

            # Episodic layer: summarize each session individually so
            # single-session questions ("what did you do in session X?") are answerable
            for idx, session_data in enumerate(sessions):
                session_turns: list[dict] = []
                if isinstance(session_data, list):
                    session_turns = [
                        t for t in session_data
                        if isinstance(t, dict) and t.get("content")
                    ]
                elif isinstance(session_data, dict) and session_data.get("content"):
                    session_turns = [session_data]

                if session_turns:
                    # Parse "2023/04/10 (Mon) 17:50" → "2023-04-10"
                    raw_date = haystack_dates[idx] if idx < len(haystack_dates) else None
                    session_date: str | None = None
                    if raw_date:
                        try:
                            from datetime import datetime
                            session_date = datetime.strptime(
                                raw_date.split(" (")[0].strip(), "%Y/%m/%d"
                            ).strftime("%Y-%m-%d")
                        except Exception:
                            pass

                    summ = Summarizer(
                        g,
                        model=extract_model,
                        backend=backend,
                        base_url=base_url,
                        api_key=api_key,
                    )
                    summ.summarize(session_turns, session_date=session_date)

            context = session.query(question, g)
            g.save()

            if verbose:
                session_nodes = sum(1 for n in g.all_nodes() if n.type.value == "SESSION")
                print(f"    [{question_id}] {len(g.all_nodes())} nodes ({session_nodes} sessions)")
    else:
        # Baseline: raw conversation as context (no extraction, one API call)
        context = "Conversation history:\n" + "\n".join(
            f"{t.get('role','?').upper()}: {t.get('content','')}"
            for t in all_turns
        )
        if verbose:
            print(f"    [{question_id}] raw context ({len(context)} chars)")

    # Generate answer — re-raise credit/auth errors so the caller can abort
    try:
        if backend == "ollama":
            answer = _answer_ollama(question, context, answer_model, question_type)
        elif backend == "anthropic":
            answer = _answer_anthropic(question, context, answer_model, api_key, question_type)
        else:
            answer = _answer_openai(question, context, answer_model, base_url, api_key, question_type)
    except Exception as e:
        err = str(e).lower()
        if "credit" in err or "billing" in err or "insufficient" in err or "balance" in err:
            raise  # propagate so main loop aborts cleanly
        answer = f"ERROR: {e}"

    return {
        "question_id": question_id,
        "hypothesis": answer,
        "_context_length": len(context),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Dory against LongMemEval benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--data", required=True, type=Path,
                        help="Path to LongMemEval JSON file (oracle, s, or m split)")
    parser.add_argument("--output", required=True, type=Path,
                        help="Output JSONL file for predictions")
    parser.add_argument("--extract-model", default="qwen3:8b",
                        help="Model for Observer memory extraction (default: qwen3:8b)")
    parser.add_argument("--answer-model", default="qwen3:14b",
                        help="Model for answer generation (default: qwen3:14b)")
    parser.add_argument("--backend", default="ollama",
                        choices=["ollama", "anthropic", "openai"],
                        help="LLM backend (default: ollama)")
    parser.add_argument("--base-url", default="http://localhost:11434",
                        help="Base URL for OpenAI-compat backend")
    parser.add_argument("--api-key", default="local",
                        help="API key for Anthropic or OpenAI backends")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only run first N questions (for testing)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip questions already in output file")
    parser.add_argument("--verbose", action="store_true",
                        help="Print per-item progress")
    args = parser.parse_args()

    # Load dataset
    print(f"Loading dataset from {args.data}...")
    items = load_dataset(args.data)
    if args.limit:
        items = items[: args.limit]
    print(f"  {len(items)} questions")

    # Handle resume
    done_ids: set[str] = set()
    if args.resume and args.output.exists():
        with open(args.output) as f:
            for line in f:
                try:
                    done_ids.add(json.loads(line)["question_id"])
                except Exception:
                    pass
        print(f"  Resuming — {len(done_ids)} already completed")

    # Run benchmark
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.resume else "w"

    correct = 0
    total = 0
    errors = 0
    start = time.time()

    with open(args.output, mode) as out:
        for i, item in enumerate(items):
            qid = item.get("question_id") or item.get("id", f"q{i}")
            if qid in done_ids:
                continue

            t0 = time.time()
            try:
                result = run_item(
                    item,
                    extract_model=args.extract_model,
                    answer_model=args.answer_model,
                    backend=args.backend,
                    base_url=args.base_url,
                    api_key=args.api_key,
                    verbose=args.verbose,
                )
            except Exception as e:
                err = str(e).lower()
                if "credit" in err or "billing" in err or "insufficient" in err or "balance" in err:
                    print(f"\n\nOut of credits — stopping at {total} questions.")
                    print("Add credits at console.anthropic.com/settings/billing")
                    print(f"Resume with: --resume (already wrote {total} predictions)")
                    break
                result = {"question_id": qid, "hypothesis": f"ERROR: {e}"}
                errors += 1

            elapsed = time.time() - t0
            total += 1

            # Write prediction (clean version without debug fields)
            prediction = {
                "question_id": result["question_id"],
                "hypothesis": result["hypothesis"],
            }
            out.write(json.dumps(prediction) + "\n")
            out.flush()

            if args.verbose:
                print(f"  [{total}/{len(items)}] {qid} ({elapsed:.1f}s)")
            else:
                # Simple progress bar
                pct = total / len(items) * 100
                eta = (time.time() - start) / total * (len(items) - total)
                print(f"\r  Progress: {total}/{len(items)} ({pct:.0f}%) | "
                      f"ETA: {eta:.0f}s | Errors: {errors}   ", end="", flush=True)

    print(f"\n\nDone. {total} predictions written to {args.output}")
    print(f"Errors: {errors}")
    print(f"Total time: {time.time() - start:.0f}s")
    print(f"\nNext step — run the official evaluator:")
    print(f"  cd LongMemEval/src/evaluation")
    print(f"  python evaluate_qa.py gpt-4o {args.output.resolve()} {args.data.resolve()}")
    print(f"  python print_qa_metrics.py {args.output.resolve()}.log")


if __name__ == "__main__":
    main()
