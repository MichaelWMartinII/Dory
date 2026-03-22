#!/usr/bin/env python3
"""
Preference extraction audit for Dory.

For each failing single-session-preference question:
1. Run haystack sessions through Observer (Haiku extraction)
2. Print what PREFERENCE nodes were stored
3. Show whether _PREFERENCE_RE matches the question
4. Show what _preference_context returns
5. Compare to the expected answer

Usage:
    python benchmarks/preference_audit.py --api-key "$ANTHROPIC_API_KEY" --limit 5
    python benchmarks/preference_audit.py --api-key "$ANTHROPIC_API_KEY" --qids 75832dbd 0edc2aef
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

# Auto-load .env from repo root if present
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            import os as _os; _os.environ.setdefault(_k.strip(), _v.strip())

from dory.graph import Graph
from dory.pipeline.observer import Observer
from dory import session as _session
from dory.schema import NodeType


ORACLE_PATH = Path(__file__).parent / "data/longmemeval/longmemeval_oracle.json"
EVAL_PATH   = Path(__file__).parent / "predictions_sonnet_full.jsonl.eval-results-claude-haiku-4-5-20251001"


def load_failures() -> list[dict]:
    with open(ORACLE_PATH) as f:
        oracle = {q["question_id"]: q for q in json.load(f)}
    with open(EVAL_PATH) as f:
        evals = {json.loads(l)["question_id"]: json.loads(l) for l in f}
    return [
        oracle[qid]
        for qid, e in evals.items()
        if qid in oracle
        and oracle[qid]["question_type"] == "single-session-preference"
        and not e["autoeval_label"]["label"]
    ]


def _parse_date(raw: str) -> str:
    try:
        return datetime.strptime(raw.split(" (")[0].strip(), "%Y/%m/%d").strftime("%Y-%m-%d")
    except Exception:
        return raw


def audit_question(item: dict, api_key: str, extract_model: str) -> None:
    qid      = item["question_id"]
    question = item["question"]
    expected = item["answer"]
    sessions = item.get("haystack_sessions", [])
    dates    = item.get("haystack_dates", [])

    print(f"\n{'='*72}")
    print(f"QID      : {qid}")
    print(f"QUESTION : {question}")
    print(f"EXPECTED : {expected[:200]}{'...' if len(expected) > 200 else ''}")

    route      = _session._route_query(question)
    pref_match = _session._PREFERENCE_RE.search(question)
    print(f"\nROUTE    : {route}  |  _PREFERENCE_RE: {repr(pref_match.group(0)) if pref_match else 'NO MATCH ❌'}")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "audit.db"
        graph   = Graph(db_path)

        obs = Observer(
            graph,
            db_path=db_path,
            model=extract_model,
            backend="anthropic",
            api_key=api_key,
            threshold=999,        # manual flush per session
            confidence_floor=0.6, # lower so borderline cases are visible
        )

        for i, sess_turns in enumerate(sessions):
            sess_date = _parse_date(dates[i]) if i < len(dates) else ""
            for turn in sess_turns:
                obs.add_turn(turn["role"], turn["content"])
            obs.flush(session_date=sess_date)

        # Surface any extraction errors
        from dory.pipeline import observer as _obs_mod
        _orig_call = obs._call_llm
        def _debug_call(turns_text, session_date=""):
            r = _orig_call(turns_text, session_date=session_date)
            if r and "_error" in r:
                print(f"  [EXTRACTION ERROR]: {r['_error'][:300]}")
            return r

        print(f"\nEXTRACTION : {obs.stats()}")

        # Node type breakdown
        type_counts: dict[str, int] = {}
        for n in graph.all_nodes():
            type_counts[n.type.value] = type_counts.get(n.type.value, 0) + 1
        print(f"NODE TYPES : {type_counts}")

        # PREFERENCE nodes
        pref_nodes = sorted(
            [n for n in graph.all_nodes() if n.type == NodeType.PREFERENCE],
            key=lambda x: -x.salience,
        )
        print(f"\nPREFERENCE NODES ({len(pref_nodes)}):")
        if pref_nodes:
            for n in pref_nodes:
                print(f"  [{n.salience:.2f}] {n.content}")
        else:
            print("  (none stored ❌)")

        # Built context
        context = _session.query(question, graph)
        print(f"\nCONTEXT ({len(context)} chars):")
        print(context[:1200] + ("..." if len(context) > 1200 else ""))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default="")
    parser.add_argument("--extract-model", default="claude-haiku-4-5-20251001")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--qids", nargs="*", help="Specific question IDs to audit")
    args = parser.parse_args()

    import os
    api_key = args.api_key if args.api_key and args.api_key != "from_env" else os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: no API key — set ANTHROPIC_API_KEY or pass --api-key", file=sys.stderr)
        sys.exit(1)

    failures = load_failures()
    print(f"Total preference failures in full Sonnet run: {len(failures)}")

    targets = [f for f in failures if f["question_id"] in args.qids] if args.qids else failures[:args.limit]
    print(f"Auditing {len(targets)} questions...\n")

    for item in targets:
        audit_question(item, api_key=api_key, extract_model=args.extract_model)

    print(f"\n{'='*72}\nAudit complete.")


if __name__ == "__main__":
    main()
