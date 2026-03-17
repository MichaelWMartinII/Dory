from __future__ import annotations

"""
Summarizer — episodic memory layer for Dory.

Unlike the Observer, which extracts durable semantic facts and deliberately
filters out transient session details, the Summarizer captures *everything*
that happened in a session as a queryable SESSION node.

This is how Dory answers "what did you do in session X?" or "what did
the assistant recommend last Tuesday?" — questions the Observer misses
by design.

SESSION nodes:
  - Decay normally (old sessions fade unless reactivated)
  - Link to semantic nodes via CO_OCCURS (spread activation finds them)
  - Include a date prefix when the session date is known
  - Are excluded from the stable prefix (too episodic) but appear in suffix

Usage:
    from dory.pipeline import Summarizer

    summarizer = Summarizer(graph, model="claude-haiku-4-5-20251001", backend="anthropic")
    node_id = summarizer.summarize(turns, session_date="2026-03-16")
"""

import json
import re

from ..graph import Graph
from ..schema import NodeType, EdgeType, new_id, now_iso


# ---------------------------------------------------------------------------
# Summarization prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an episodic memory system for an AI agent.

Your job is to capture a session as a detailed, queryable memory. Do NOT filter
for long-term relevance — preserve everything specific that could answer a future
question like "what did the assistant say about X?" or "what happened on date Y?".

Write a detailed summary that explicitly includes:
- SPECIFIC names of people, places, products, brands, and organizations
- SPECIFIC numbers, quantities, measurements, prices, scores, and dates
- EXACT items in any list, schedule, table, or set (do not summarize as "several items")
- What the assistant specifically said, recommended, created, or provided
- What the user did, decided, experienced, or asked for
- Outcomes, results, and concrete next steps

Return ONLY valid JSON:
{
  "summary": "detailed paragraph preserving all specific facts from the session",
  "topics": ["topic1", "topic2"],
  "session_date": "YYYY-MM-DD if clearly stated in the conversation, else null"
}"""

_USER_TEMPLATE = """Capture this conversation as a detailed episodic memory. Preserve every specific name, number, item, and recommendation — do not compress or omit specifics:

{turns}"""


# ---------------------------------------------------------------------------
# LLM backends (shared pattern with Observer)
# ---------------------------------------------------------------------------

def _call_ollama(turns_text: str, model: str) -> dict | None:
    try:
        import ollama
        resp = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _USER_TEMPLATE.format(turns=turns_text)},
            ],
            format="json",
            options={"temperature": 0.1},
        )
        return json.loads(resp["message"]["content"])
    except Exception as e:
        return {"_error": str(e)}


def _call_openai_compat(turns_text: str, model: str, base_url: str, api_key: str = "local") -> dict | None:
    try:
        import httpx
        r = httpx.post(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _USER_TEMPLATE.format(turns=turns_text)},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        return {"_error": str(e)}


def _call_anthropic(turns_text: str, model: str, api_key: str) -> dict | None:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _USER_TEMPLATE.format(turns=turns_text)}],
        )
        raw = resp.content[0].text
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return {"_error": "JSON parse failed"}
    except Exception as e:
        return {"_error": str(e)}


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------

class Summarizer:
    """
    Creates SESSION nodes from conversation turns.

    Parameters
    ----------
    graph : Graph
        The Dory graph to write SESSION nodes into.
    model : str
        Model name for summarization.
    backend : str
        "ollama", "openai", or "anthropic".
    base_url : str
        Base URL for OpenAI-compat backends.
    api_key : str
        API key for Anthropic or OpenAI backends.
    session_id : str | None
        ID for this session. Auto-generated if None.
    """

    def __init__(
        self,
        graph: Graph,
        model: str = "qwen3:14b",
        backend: str = "ollama",
        base_url: str = "http://localhost:8000",
        api_key: str = "local",
        session_id: str | None = None,
    ):
        self.graph = graph
        self.model = model
        self.backend = backend
        self.base_url = base_url
        self.api_key = api_key
        self.session_id = session_id or new_id()

    def summarize(
        self,
        turns: list[dict],
        session_date: str | None = None,
    ) -> str | None:
        """
        Summarize turns and write a SESSION node to the graph.

        Parameters
        ----------
        turns : list[dict]
            [{"role": "user"|"assistant", "content": "..."}]
        session_date : str | None
            Optional ISO date override (e.g. "2026-03-16"). The LLM will
            also try to infer a date from the conversation itself.

        Returns
        -------
        str | None
            Node ID of the created SESSION node, or None on failure.
        """
        if not turns:
            return None

        turns_text = "\n".join(
            f"{t['role'].upper()}: {t['content']}" for t in turns
        )

        result = self._call_llm(turns_text)
        if not result or "_error" in result:
            return None

        summary = (result.get("summary") or "").strip()
        if not summary:
            return None

        topics = [str(t) for t in (result.get("topics") or [])[:6]]
        date = session_date or result.get("session_date") or None

        # Build content — date prefix makes temporal queries work
        date_prefix = f"[{date}] " if date else ""
        content = f"{date_prefix}Session: {summary}"

        node = self.graph.add_node(
            NodeType.SESSION,
            content,
            tags=["episodic", "session"] + topics,
        )
        # Use the actual session date for created_at so serialize() shows the right date.
        # Fall back to now() if no date is available.
        if date:
            try:
                from datetime import datetime, timezone
                node.created_at = datetime.strptime(date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                ).isoformat()
            except Exception:
                node.created_at = now_iso()
        else:
            node.created_at = now_iso()
        node.last_activated = now_iso()

        # Link to semantic nodes via CO_OCCURS so spreading activation reaches them
        self._link_to_semantic(node.id, summary + " " + " ".join(topics))
        self.graph.save()
        return node.id

    def _call_llm(self, turns_text: str) -> dict | None:
        if self.backend == "ollama":
            return _call_ollama(turns_text, self.model)
        elif self.backend == "openai":
            return _call_openai_compat(turns_text, self.model, self.base_url, self.api_key)
        elif self.backend == "anthropic":
            return _call_anthropic(turns_text, self.model, self.api_key)
        return None

    def _link_to_semantic(self, session_node_id: str, text: str, max_links: int = 6) -> None:
        """CO_OCCURS edges from SESSION node to related semantic nodes found via FTS."""
        from .. import activation as act

        seeds = act.find_seeds(text, self.graph)
        linked = 0
        for seed_id in seeds:
            if seed_id == session_node_id:
                continue
            node = self.graph.get_node(seed_id)
            if node and node.type != NodeType.SESSION:
                self.graph.add_edge(session_node_id, seed_id, EdgeType.CO_OCCURS, weight=0.6)
                linked += 1
                if linked >= max_links:
                    break
