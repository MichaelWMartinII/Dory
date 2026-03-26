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
You are answering a question about a person based on their prior conversation history.
Treat the memory context below as your actual prior conversations with this person.
Use only what is directly supported by the context. Do not make up information.
Only say there is not enough information if the relevant fact is genuinely absent.
Give a short, direct answer. Do not explain your reasoning unless asked.

Memory context:
{context}

Question: {question}

Answer:"""

_ANSWER_PROMPT_TEMPORAL = """\
You are answering a question about the timing or order of events from a person's conversation history.
Treat the memory context below as your actual prior conversations with this person.

Rules:
- SESSION memories have date prefixes like [YYYY-MM-DD] — use these for ordering.
- Use "Today's date" shown in the context to resolve relative expressions like "X days ago",
  "last Saturday", "the past month", "recently", etc. Calculate exact dates when needed.
- For any date calculation, show your arithmetic on one line before your answer:
  "Today: YYYY-MM-DD. Event: YYYY-MM-DD. Difference: N days."
- Only state a chronological order if both events have explicit dates, can be calculated from
  today's date, or the ordering is explicitly stated in the context.
- If ordering cannot be determined even with today's date, say so directly and briefly.
- Give a short, direct answer after showing your arithmetic.

Memory context:
{context}

Question: {question}

Answer:"""

_ANSWER_PROMPT_MULTI_SESSION = """\
You are answering a question that may require finding information across multiple conversations.
Treat the memory context below as your actual prior conversations with this person.

Search ALL memories — including every SESSION entry. For counting or listing questions,
find every relevant instance before answering. Do not stop at the first match.
Give a short, direct answer.

Memory context:
{context}

Question: {question}

Answer:"""

_ANSWER_PROMPT_KNOWLEDGE_UPDATE = """\
You are answering a question about a person's current situation based on their conversation history.
Treat the memory context below as your actual prior conversations with this person.

If you see a [KNOWLEDGE UPDATE] in the memories, use the UPDATED value, not the original.
Always prefer the most recent information. Give a short, direct answer.

Memory context:
{context}

Question: {question}

Answer:"""

_ANSWER_PROMPT_SESSION = """\
You are answering a question about what happened or was said in a specific conversation.
Treat the memory context below as your actual prior conversations with this person.

The answer is likely in a SESSION memory. Look for the specific detail asked about:
exact names, numbers, items, colors, recommendations, or things the assistant said.
Only say there is not enough information if the fact is genuinely absent from the context.
Give a short, direct answer.

Memory context:
{context}

Question: {question}

Answer:"""

_ANSWER_PROMPT_PREFERENCE = """\
You are answering a question about what this person would prefer or how they would like to be helped.
Treat the memory context below as your actual prior conversations with this person.

Instructions:
- Search the context for any relevant preferences, interests, past experiences, or personality details
  that apply to this question — even if the exact topic was never explicitly discussed before.
- If the context contains a "Key events" section, prioritize those specific memories — they capture
  memorable moments and specific details (named things, achievements, encounters) that should be
  directly referenced and built upon in your answer.
- Apply what you know about this person to give a tailored, personalized answer.
- Do NOT say "this was never discussed" or "I don't have memory" unless the context has absolutely
  nothing relevant. If you have partial context, use it.
- Give a direct, helpful response as if you know this person well.

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
    "single-session-preference": _ANSWER_PROMPT_PREFERENCE,
}


def _get_prompt(question: str, context: str, question_type: str, question_date: str = "") -> str:
    template = _ANSWER_PROMPTS.get(question_type, _ANSWER_PROMPT_DEFAULT)
    if question_date:
        context = f"Today's date: {question_date}\n\n{context}"
    return template.format(context=context, question=question)


def _answer_ollama(question: str, context: str, model: str, question_type: str = "", question_date: str = "") -> str:
    import ollama
    resp = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": _get_prompt(question, context, question_type, question_date)}],
        options={"temperature": 0.0},
    )
    return resp["message"]["content"].strip()


def _answer_anthropic(question: str, context: str, model: str, api_key: str, question_type: str = "", question_date: str = "") -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=512,
        messages=[{"role": "user", "content": _get_prompt(question, context, question_type, question_date)}],
    )
    return resp.content[0].text.strip()


def _answer_openai(question: str, context: str, model: str, base_url: str, api_key: str, question_type: str = "", question_date: str = "") -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": _get_prompt(question, context, question_type, question_date)}],
        temperature=0.0,
        max_tokens=512,
    )
    return resp.choices[0].message.content.strip()


def _answer_claude_code(question: str, context: str, question_type: str = "", question_date: str = "") -> str:
    """
    Use `claude -p --bare` with Dory context injected as full prompt.
    Approach A: same context as other backends, but answered by the Claude Code CLI.
    """
    import subprocess
    full_prompt = _get_prompt(question, context, question_type, question_date)
    result = subprocess.run(
        ["claude", "-p", "--output-format", "text", "--bare", full_prompt],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude -p failed (exit {result.returncode}): {result.stderr[:500]}"
        )
    return result.stdout.strip()


_MCP_TYPE_HINTS = {
    "temporal-reasoning": (
        "This question is about timing or ordering of events. "
        "Use date prefixes in memories to calculate exact differences."
    ),
    "multi-session": (
        "This question may require info from multiple conversations. "
        "Search broadly and count every relevant instance."
    ),
    "knowledge-update": (
        "Use the most recent information — prefer updated values over originals."
    ),
    "single-session-user": (
        "The answer is likely in a specific session memory. Look for exact names, numbers, or items."
    ),
    "single-session-assistant": (
        "The answer is something the assistant said. Look in session memories for specific details."
    ),
    "single-session-preference": (
        "Answer based on stored preferences, interests, and past experiences. "
        "Be personalized and reference specific memories."
    ),
}


def _answer_claude_code_mcp(
    question: str,
    db_path: "Path",
    question_type: str = "",
    question_date: str = "",
) -> str:
    """
    Use `claude -p --strict-mcp-config` so Claude Code queries Dory autonomously.
    Approach B: the authentic test — Claude uses dory_query to retrieve its own memories.
    """
    import json
    import subprocess
    import tempfile

    dory_mcp_script = str(Path(__file__).parent.parent / "dory_mcp.py")
    mcp_config = {
        "mcpServers": {
            "dory": {
                "command": sys.executable,
                "args": [dory_mcp_script, "--db", str(db_path)],
            }
        }
    }

    type_hint = _MCP_TYPE_HINTS.get(question_type, "")
    date_hint = f" Today's date is {question_date}." if question_date else ""

    system_prompt = (
        "You have access to a Dory memory graph containing someone's conversation history. "
        "Call dory_query with relevant search terms to retrieve memories, then answer "
        f"the question based on what you find. {type_hint}{date_hint} "
        "Give a short, direct answer."
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(mcp_config, f)
        mcp_config_path = f.name

    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--output-format", "text",
                "--bare",
                "--dangerously-skip-permissions",
                "--strict-mcp-config",
                "--mcp-config", mcp_config_path,
                "--system-prompt", system_prompt,
                question,
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"claude -p failed (exit {result.returncode}): {result.stderr[:500]}"
            )
        return result.stdout.strip()
    finally:
        Path(mcp_config_path).unlink(missing_ok=True)


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
    no_session_summary: bool = False,
    no_session_node: bool = False,
    answer_backend: str | None = None,
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

    # Parse question_date → human-readable "Monday, May 20, 2023" for today-anchor
    question_date_str = ""
    raw_qdate = item.get("question_date", "")
    if raw_qdate:
        try:
            from datetime import datetime as _dt
            question_date_str = _dt.strptime(
                raw_qdate.split(" (")[0].strip(), "%Y/%m/%d"
            ).strftime("%A, %B %d, %Y")
        except Exception:
            pass

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

            # Process sessions one at a time so extracted nodes can be
            # backdated to the actual session date. Processing all turns
            # at once stamps every node with today's date, breaking
            # temporal ordering questions.
            for idx, session_data in enumerate(sessions):
                session_turns: list[dict] = []
                if isinstance(session_data, list):
                    session_turns = [
                        t for t in session_data
                        if isinstance(t, dict) and t.get("content")
                    ]
                elif isinstance(session_data, dict) and session_data.get("content"):
                    session_turns = [session_data]

                if not session_turns:
                    continue

                # Parse "2023/04/10 (Mon) 17:50" → "2023-04-10"
                raw_date = haystack_dates[idx] if idx < len(haystack_dates) else None
                session_date: str | None = None
                if raw_date:
                    try:
                        from datetime import datetime, timezone
                        session_date = datetime.strptime(
                            raw_date.split(" (")[0].strip(), "%Y/%m/%d"
                        ).strftime("%Y-%m-%d")
                    except Exception:
                        pass

                # Snapshot node IDs before this session
                nodes_before = set(g._nodes.keys())

                for turn in session_turns:
                    role = turn.get("role", "user")
                    content = turn.get("content", "")
                    if content:
                        obs.add_turn(role, content)

                obs.flush(session_date=session_date or "")

                # Backdate newly extracted nodes to the actual session date
                # so temporal ordering questions get correct relative dates.
                if session_date:
                    from datetime import datetime, timezone
                    session_ts = datetime.strptime(
                        session_date, "%Y-%m-%d"
                    ).replace(tzinfo=timezone.utc).isoformat()
                    for node_id, node in g._nodes.items():
                        if node_id not in nodes_before:
                            node.created_at = session_ts
                            node.last_activated = session_ts

                # Episodic summary for this session (SESSION node — full narrative)
                # + SESSION_SUMMARY node — structured counts + provenance edges
                summ = Summarizer(
                    g,
                    model=extract_model,
                    backend=backend,
                    base_url=base_url,
                    api_key=api_key,
                )
                if not no_session_node:
                    summ.summarize(session_turns, session_date=session_date)
                if not no_session_summary and not no_session_node:
                    summ.summarize_session(session_turns, session_date=session_date)

            # Synthesize behavioral preferences from repeated patterns across sessions
            from dory.pipeline.reflector import Reflector
            Reflector(g, db_path=db_path).run()

            context = session.query(question, g)
            g.save()

            if verbose:
                session_nodes = sum(1 for n in g.all_nodes() if n.type.value == "SESSION")
                summary_nodes = sum(1 for n in g.all_nodes() if n.type.value == "SESSION_SUMMARY")
                print(f"    [{question_id}] {len(g.all_nodes())} nodes ({session_nodes} sessions, {summary_nodes} summaries)")

            # MCP mode: answer while DB still exists (temp dir about to be cleaned up)
            ans_be = answer_backend or backend
            if ans_be == "claude-code-mcp":
                try:
                    mcp_answer = _answer_claude_code_mcp(
                        question, db_path, question_type, question_date_str
                    )
                except Exception as e:
                    err = str(e).lower()
                    if "credit" in err or "billing" in err or "insufficient" in err or "balance" in err:
                        raise
                    mcp_answer = f"ERROR: {e}"
                return {
                    "question_id": question_id,
                    "hypothesis": mcp_answer,
                    "_context_length": len(context),
                }
    else:
        # Baseline: raw conversation as context (no extraction, one API call)
        context = "Conversation history:\n" + "\n".join(
            f"{t.get('role','?').upper()}: {t.get('content','')}"
            for t in all_turns
        )
        if verbose:
            print(f"    [{question_id}] raw context ({len(context)} chars)")

    ans_be = answer_backend or backend

    # Generate answer — re-raise credit/auth errors so the caller can abort
    try:
        if ans_be == "claude-code":
            answer = _answer_claude_code(question, context, question_type, question_date_str)
        elif ans_be == "ollama":
            answer = _answer_ollama(question, context, answer_model, question_type, question_date_str)
        elif ans_be == "anthropic":
            answer = _answer_anthropic(question, context, answer_model, api_key, question_type, question_date_str)
        else:
            answer = _answer_openai(question, context, answer_model, base_url, api_key, question_type, question_date_str)
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
                        help="LLM backend for extraction (default: ollama)")
    parser.add_argument("--answer-backend", default=None,
                        choices=["ollama", "anthropic", "openai", "claude-code", "claude-code-mcp"],
                        help=(
                            "Override backend for answer generation only. "
                            "claude-code: inject Dory context, answer via `claude -p`. "
                            "claude-code-mcp: Claude Code calls dory_query autonomously. "
                            "Defaults to --backend if not set."
                        ))
    parser.add_argument("--base-url", default="http://localhost:11434",
                        help="Base URL for OpenAI-compat backend")
    parser.add_argument("--api-key", default="local",
                        help="API key for Anthropic or OpenAI backends")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only run N questions (for testing)")
    parser.add_argument("--offset", type=int, default=0,
                        help="Start at this index in the dataset (default: 0)")
    parser.add_argument("--stratify", type=str, default=None,
                        help=(
                            "Stratified sample by question type. "
                            "Format: type:n,type:n,... "
                            "e.g. temporal-reasoning:20,single-session-preference:15,"
                            "multi-session:7,knowledge-update:8"
                        ))
    parser.add_argument("--resume", action="store_true",
                        help="Skip questions already in output file")
    parser.add_argument("--verbose", action="store_true",
                        help="Print per-item progress")
    parser.add_argument("--no-session-summary", action="store_true",
                        help="Ablation: disable SESSION_SUMMARY nodes (keep SESSION nodes)")
    parser.add_argument("--no-session-node", action="store_true",
                        help="Ablation: disable both SESSION and SESSION_SUMMARY nodes")
    args = parser.parse_args()

    # Load dataset
    print(f"Loading dataset from {args.data}...")
    items = load_dataset(args.data)
    if args.offset:
        items = items[args.offset :]
    if args.limit:
        items = items[: args.limit]

    # Stratified sampling
    if args.stratify:
        import random
        by_type: dict[str, list] = {}
        for item in items:
            t = item.get("question_type", "unknown")
            by_type.setdefault(t, []).append(item)
        sampled = []
        for spec in args.stratify.split(","):
            qtype, n = spec.strip().rsplit(":", 1)
            pool = by_type.get(qtype.strip(), [])
            sampled.extend(random.sample(pool, min(int(n), len(pool))))
        random.shuffle(sampled)
        items = sampled
        print(f"  Stratified sample: {len(items)} questions")
        for qtype, pool in by_type.items():
            n = sum(1 for i in items if i.get("question_type") == qtype)
            if n:
                print(f"    {qtype}: {n}")
    else:
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

            time.sleep(2)  # avoid Sonnet rate limits between questions
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
                    no_session_summary=args.no_session_summary,
                    no_session_node=args.no_session_node,
                    answer_backend=args.answer_backend,
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
