"""
live_chat.py — Dory live memory demo

Jolene (played by Claude) has a conversation with Elwin in Session 1.
Dory extracts memories. Session 2 starts fresh — only Dory's memory
carries the context forward.

Usage:
    python examples/live_chat.py
"""

from __future__ import annotations

import json
import re
import sys
import textwrap
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "Agent"))

from dory import DoryMemory

# ── Server config — try Elwin first, fall back to Clanker ────────────────────

ELWIN   = ("http://127.0.0.1:59086", "ER-ransom-llm-2f8a9c")
CLANKER = ("http://127.0.0.1:8001",  "")

# Force a specific server (set to None to auto-detect)
FORCE_SERVER: tuple | None = CLANKER

DB_PATH = Path(__file__).parent.parent / "demo_live.db"


def _pick_server() -> tuple[str, str, str]:
    """Return (base_url, api_key, name). Tries Elwin first."""
    candidates = [(*FORCE_SERVER, "Clanker")] if FORCE_SERVER else [(*ELWIN, "Elwin"), (*CLANKER, "Clanker")]
    for url, key, name in candidates:
        try:
            req = urllib.request.Request(f"{url}/v1/models",
                                         headers={"Authorization": f"Bearer {key}"} if key else {})
            with urllib.request.urlopen(req, timeout=3) as r:
                data = json.loads(r.read())
                model = (data.get("models") or data.get("data") or [{}])[0].get("name", "unknown")
                return url, key, f"{name} ({model})"
        except Exception:
            continue
    print("ERROR: No LLM server found. Start Elwin or Clanker first.")
    sys.exit(1)


BASE_URL, API_KEY, SERVER_NAME = _pick_server()

# ── LLM call (stdlib only — matches Elwin's own client) ──────────────────────

def _call(messages: list[dict], system: str) -> str:
    body = {
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": False,
        "temperature": 0.7,
        "max_tokens": 400,
    }
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(
        f"{BASE_URL}/v1/chat/completions", data=data, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        obj = json.loads(resp.read())
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


def _print_speaker(speaker: str, text: str, color: str) -> None:
    label = f"{color}{BOLD}{speaker:<10}{RESET}"
    wrapped = textwrap.fill(text, width=68, subsequent_indent=" " * 11)
    # Replace first indent with label
    lines = wrapped.split("\n")
    lines[0] = f"  {label} {lines[0]}"
    for i in range(1, len(lines)):
        lines[i] = "  " + " " * 11 + lines[i]
    print("\n".join(lines) + "\n")


def _hr(char="─", n=68, color=""):
    print(f"{color}{char * n}{RESET}")


# ── Jolene's script ───────────────────────────────────────────────────────────
# Designed to plant facts across every memory category.
# The Clara detail (hikes alone → went with Clara) tests knowledge update.

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
    "You are Elwin, a warm and curious AI companion. You're having a casual conversation. "
    "Respond naturally, show genuine interest, and ask follow-up questions."
)
SYSTEM_S2 = (
    "You are Elwin. Answer each question using only the memory context provided below. "
    "Be specific and direct. If the context doesn't contain the answer, say so."
)

# ── Session 1 ─────────────────────────────────────────────────────────────────

def session_1() -> DoryMemory:
    print()
    _hr("═", color=CYAN)
    print(f"  {CYAN}{BOLD}DORY LIVE DEMO  ·  Session 1 of 2{RESET}")
    print(f"  Server: {SERVER_NAME}")
    print(f"  Jolene talks to Elwin. Dory extracts memories.")
    _hr("═", color=CYAN)
    print()

    mem = DoryMemory(
        db_path=DB_PATH,
        extract_model="Qwen3-14B-Q4_K_M.gguf",
        extract_backend="openai",
        extract_base_url=BASE_URL,
        extract_api_key=API_KEY,
    )

    history: list[dict] = []

    for line in JOLENE_SCRIPT:
        _print_speaker("Jolene", line, BLUE)
        time.sleep(0.3)

        history.append({"role": "user", "content": line})
        mem.add_turn("user", line)

        reply = _call(history, SYSTEM_S1)
        _print_speaker("Elwin", reply, GREEN)

        history.append({"role": "assistant", "content": reply})
        mem.add_turn("assistant", reply)
        time.sleep(0.3)

    # Flush
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
        print(f"  {YELLOW}No memories extracted — conversation may have been too short.{RESET}")

    print()
    return mem


# ── Session 2 ─────────────────────────────────────────────────────────────────

def session_2(mem: DoryMemory) -> None:
    print()
    _hr("═", color=CYAN)
    print(f"  {CYAN}{BOLD}DORY LIVE DEMO  ·  Session 2 of 2{RESET}")
    print(f"  Fresh context. No conversation history. Only Dory knows.")
    _hr("═", color=CYAN)
    print()

    for question in SESSION_2_QUESTIONS:
        _print_speaker("Question", question, YELLOW)
        time.sleep(0.2)

        context = mem.query(question)

        # Show retrieved context
        _hr("·", 68, DIM)
        print(f"  {DIM}Dory retrieved:{RESET}")
        for ln in context.splitlines()[:10]:
            print(f"  {DIM}{ln}{RESET}")
        _hr("·", 68, DIM)
        print()

        system_with_mem = f"{SYSTEM_S2}\n\nMemory:\n{context}"
        answer = _call([{"role": "user", "content": question}], system_with_mem)
        _print_speaker("Elwin", answer, GREEN)
        time.sleep(0.2)

    _hr("═", color=CYAN)
    print(f"  {CYAN}{BOLD}Done.{RESET}  DB: {DB_PATH}")
    _hr("═", color=CYAN)
    print()
    try:
        mem.visualize()
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if DB_PATH.exists():
        DB_PATH.unlink()

    mem = session_1()
    try:
        input(f"\n  {BOLD}Press Enter to start Session 2…{RESET}\n")
    except EOFError:
        print(f"\n  Starting Session 2…\n")
    session_2(mem)
