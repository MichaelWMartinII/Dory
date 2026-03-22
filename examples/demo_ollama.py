"""
demo_ollama.py — Dory two-session memory demo using Ollama (fully local, no API key)

Jolene talks to an AI in Session 1. Dory extracts memories.
Session 2 starts fresh — only Dory remembers. The model answers questions
it has no direct access to using only retrieved memory context.

Prerequisites:
    1. Install Ollama:      https://ollama.com
    2. Pull a model:        ollama pull qwen3:14b
    3. Start Ollama:        ollama serve
    4. Install deps:        pip install "dory-memory[ollama]"

Usage:
    python examples/demo_ollama.py
    python examples/demo_ollama.py --model qwen3:8b
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dory import DoryMemory

OLLAMA_BASE = "http://127.0.0.1:11434"
DB_PATH = Path(__file__).parent.parent / "demo_ollama.db"

# ── Model detection ───────────────────────────────────────────────────────────

PREFERRED = ["qwen3", "qwen2.5", "llama3", "mistral", "gemma"]


def _list_models() -> list[str]:
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=5) as r:
            data = json.loads(r.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _pick_model(override: str | None) -> str:
    if override:
        return override

    models = _list_models()
    if not models:
        print(
            "ERROR: Cannot reach Ollama at http://127.0.0.1:11434\n"
            "       Run: ollama serve"
        )
        sys.exit(1)

    for pref in PREFERRED:
        for m in models:
            if pref in m.lower():
                return m

    return models[0]


# ── LLM chat call ─────────────────────────────────────────────────────────────

def _call(messages: list[dict], system: str, model: str) -> str:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": False,
        "temperature": 0.7,
        "max_tokens": 400,
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            obj = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"\nERROR {e.code}: {e.read().decode()}")
        sys.exit(1)
    text = obj["choices"][0]["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


# ── Display helpers ───────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
BLUE   = "\033[94m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
DIM    = "\033[2m"


def _speaker(name: str, text: str, color: str) -> None:
    label = f"{color}{BOLD}{name:<10}{RESET}"
    wrapped = textwrap.fill(text, width=68, subsequent_indent=" " * 11)
    lines = wrapped.split("\n")
    lines[0] = f"  {label} {lines[0]}"
    for i in range(1, len(lines)):
        lines[i] = "  " + " " * 11 + lines[i]
    print("\n".join(lines) + "\n")


def _hr(char="─", n=68, color=""):
    print(f"{color}{char * n}{RESET}")


# ── Jolene's script ───────────────────────────────────────────────────────────
# Plants facts across every memory category.
# The Clara correction (hikes alone → went with Clara) tests knowledge update.

JOLENE_SCRIPT = [
    "Hey! I'm Jolene. I'm a fiction author based in Asheville, North Carolina. "
    "Really glad to have someone to talk to today.",

    "I'm working on my second novel right now — it's called The Marrow Season. "
    "Literary fiction, set in the Appalachian mountains. My first book was called "
    "Dusk at Meridian, published back in 2023. It did alright.",

    "I just got back from a four-day hike on the Art Loeb Trail. Finished it yesterday, "
    "actually. My legs are absolutely wrecked. I usually hike alone — I like the quiet.",

    "I sent the first three chapters of The Marrow Season to my agent about two weeks ago. "
    "Still waiting to hear back. That waiting period is the worst part of writing.",

    "When I'm not writing I'm usually in the kitchen. I cook low and slow, very Southern-influenced. "
    "Cast iron is non-negotiable for me. I also make craft cocktails — my go-to right now is a "
    "mezcal negroni with a smoked salt rim. I cannot stand gin though. Bad experience at a wedding "
    "years ago, never recovered.",

    "My writing routine is pretty strict. Black coffee, ninety minutes of writing before I touch my "
    "phone or email. Best work happens before nine in the morning or it doesn't happen at all. "
    "That's just how my brain works.",

    "Oh, I should mention — I said I hike alone but actually I did the Art Loeb Trail with my "
    "friend Clara. She talked me into it. It was better having company, honestly.",
]

SESSION_2_QUESTIONS = [
    "What is Jolene currently working on, and what was her first book?",
    "What did Jolene do this past week?",
    "What's her favorite cocktail, and is there anything she absolutely won't drink?",
    "Does Jolene hike alone or with someone?",
    "When did she send chapters to her agent?",
    "Describe her morning writing routine.",
]

SYSTEM_S1 = (
    "You are a warm and curious AI companion. You're having a casual conversation. "
    "Respond naturally, show genuine interest, and ask follow-up questions."
)
SYSTEM_S2 = (
    "You are an AI assistant. Answer each question using only the memory context provided. "
    "Be specific and direct. If the context doesn't contain the answer, say so.\n\n"
    "Memory:\n{context}"
)


# ── Session 1 ─────────────────────────────────────────────────────────────────

def session_1(model: str) -> DoryMemory:
    print()
    _hr("═", color=CYAN)
    print(f"  {CYAN}{BOLD}DORY + OLLAMA DEMO  ·  Session 1 of 2{RESET}")
    print(f"  Model:  {model}")
    print(f"  Server: {OLLAMA_BASE}")
    print(f"  Jolene talks. Dory extracts memories.")
    _hr("═", color=CYAN)
    print()

    mem = DoryMemory(
        db_path=DB_PATH,
        extract_model=model,
        extract_backend="ollama",
    )

    history: list[dict] = []

    for line in JOLENE_SCRIPT:
        _speaker("Jolene", line, BLUE)
        time.sleep(0.2)

        history.append({"role": "user", "content": line})
        mem.add_turn("user", line)

        reply = _call(history, SYSTEM_S1, model)
        _speaker("AI", reply, GREEN)

        history.append({"role": "assistant", "content": reply})
        mem.add_turn("assistant", reply)
        time.sleep(0.2)

    print()
    _hr(color=DIM)
    print(f"  {YELLOW}Extracting memories…{RESET}")
    _hr(color=DIM)
    print()

    mem.flush()

    nodes = mem.graph.all_nodes()
    if nodes:
        print(f"  {BOLD}{len(nodes)} memories stored:{RESET}\n")
        for node in sorted(nodes, key=lambda n: n.salience, reverse=True):
            tag = f" [{node.tags[0]}]" if node.tags else ""
            print(f"  {GREEN}+{RESET}  {DIM}[{node.type.value}{tag}]{RESET}  {node.content[:62]}")
    else:
        print(f"  {YELLOW}No memories extracted.{RESET}")

    print()
    return mem


# ── Session 2 ─────────────────────────────────────────────────────────────────

def session_2(mem: DoryMemory, model: str) -> None:
    print()
    _hr("═", color=CYAN)
    print(f"  {CYAN}{BOLD}DORY + OLLAMA DEMO  ·  Session 2 of 2{RESET}")
    print(f"  Fresh context. No conversation history. Only Dory knows.")
    _hr("═", color=CYAN)
    print()

    for question in SESSION_2_QUESTIONS:
        _speaker("Question", question, YELLOW)
        time.sleep(0.2)

        context = mem.query(question)

        _hr("·", 68, DIM)
        print(f"  {DIM}Dory retrieved:{RESET}")
        for ln in context.splitlines()[:10]:
            print(f"  {DIM}{ln}{RESET}")
        _hr("·", 68, DIM)
        print()

        answer = _call(
            [{"role": "user", "content": question}],
            SYSTEM_S2.format(context=context),
            model,
        )
        _speaker("AI", answer, GREEN)
        time.sleep(0.2)

    _hr("═", color=CYAN)
    print(f"  {CYAN}{BOLD}Done.{RESET}  DB saved to: {DB_PATH}")
    _hr("═", color=CYAN)
    print()
    try:
        mem.visualize()
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Dory two-session memory demo using Ollama")
    parser.add_argument("--model", default=None, help="Ollama model name (auto-detected if omitted)")
    args = parser.parse_args()

    model = _pick_model(args.model)

    if DB_PATH.exists():
        DB_PATH.unlink()

    mem = session_1(model)
    try:
        input(f"\n  {BOLD}Press Enter to start Session 2…{RESET}\n")
    except EOFError:
        print("\n  Starting Session 2…\n")
    session_2(mem, model)


if __name__ == "__main__":
    main()
