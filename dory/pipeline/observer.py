from __future__ import annotations

"""
Observer — the extraction engine for Engram's memory pipeline.

Every N conversation turns, Observer calls a local LLM to extract durable
facts from the conversation and writes them into the graph as nodes and edges.
Raw turns are always logged to the episodic observations table first.

Confidence scoring guards against false memory: extractions below the
confidence floor are logged but not written to the graph.

Usage:
    from dory.pipeline import Observer

    obs = Observer(graph, db_path)
    obs.add_turn("user", "I'm working on AllergyFind today")
    obs.add_turn("assistant", "What do you need help with?")
    obs.flush()  # force extraction at end of session
"""

import json
import re
from typing import Any

from ..graph import Graph
from ..schema import NodeType, EdgeType, new_id, now_iso
from .. import store

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a precise memory extraction system for an AI agent.
Given a conversation, extract only durable, meaningful facts worth remembering long-term.

Return ONLY valid JSON matching this schema exactly:
{
  "nodes": [
    {
      "type": "ENTITY | CONCEPT | EVENT | PREFERENCE | BELIEF",
      "content": "concise natural language description",
      "tags": ["tag1", "tag2"],
      "confidence": 0.0
    }
  ],
  "edges": [
    {
      "source_content": "exact content of source node",
      "target_content": "exact content of target node",
      "type": "WORKS_ON | INTERESTED_IN | PREFERS | USES | PART_OF | CAUSED | RELATED_TO | INSTANCE_OF",
      "weight": 0.8
    }
  ]
}

Rules:
- ENTITY: a person, place, project, tool, or organization
- CONCEPT: an idea, domain, technology, or pattern
- EVENT: something that happened or was decided
- PREFERENCE: a stated or clearly implied preference or working style
- BELIEF: an assertion about the world the speaker holds to be true
- confidence: 0.9+ for explicitly stated facts, 0.7-0.89 for strongly implied, below 0.7 for uncertain
- Only extract facts that would still be useful in a future unrelated session
- Skip pleasantries, filler, and transient task details
- Keep content concise but specific — aim for one clear sentence per node
- Return {"nodes": [], "edges": []} if nothing meaningful to extract"""

_USER_TEMPLATE = """Extract memories from this conversation:

{turns}"""


# ---------------------------------------------------------------------------
# LLM backends
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
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _USER_TEMPLATE.format(turns=turns_text)},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        r = httpx.post(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        return {"_error": str(e)}


def _extract_json(raw: str) -> dict | None:
    """Try to pull a JSON object out of a raw text response."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


# ---------------------------------------------------------------------------
# Observer
# ---------------------------------------------------------------------------

class Observer:
    """
    Buffers conversation turns and periodically extracts memories via LLM.

    Parameters
    ----------
    graph : Graph
        The Engram graph to write extracted nodes/edges into.
    db_path : Path
        Path to the engram.db SQLite file (for observation logging).
    model : str
        Ollama model name or OpenAI-compat model name.
    backend : str
        "ollama" or "openai" (OpenAI-compatible endpoint).
    base_url : str
        Base URL for OpenAI-compat backend (e.g. "http://localhost:8000").
    api_key : str
        API key for OpenAI-compat backend (default "local" for Clanker/llama.cpp).
    threshold : int
        Number of turns to buffer before auto-extracting. Default 5.
    confidence_floor : float
        Minimum confidence to write a node to the graph. Default 0.7.
    session_id : str | None
        ID for this session, used to group observations. Auto-generated if None.
    """

    def __init__(
        self,
        graph: Graph,
        db_path=None,
        model: str = "qwen3:14b",
        backend: str = "ollama",
        base_url: str = "http://localhost:8000",
        api_key: str = "local",
        threshold: int = 5,
        confidence_floor: float = 0.7,
        session_id: str | None = None,
    ):
        self.graph = graph
        self.db_path = db_path or graph.path
        self.model = model
        self.backend = backend
        self.base_url = base_url
        self.api_key = api_key
        self.threshold = threshold
        self.confidence_floor = confidence_floor
        self.session_id = session_id or new_id()

        self._buffer: list[dict] = []
        self._stats = {"turns_logged": 0, "extractions_run": 0, "nodes_written": 0, "nodes_skipped": 0, "errors": 0}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_turn(self, role: str, content: str) -> None:
        """
        Add a conversation turn. Logs it immediately to the episodic store
        and triggers extraction when the buffer hits the threshold.
        """
        obs_id = new_id()
        store.write_observation(
            obs_id=obs_id,
            content=content,
            path=self.db_path,
            session_id=self.session_id,
            role=role,
            created_at=now_iso(),
        )
        self._buffer.append({"role": role, "content": content})
        self._stats["turns_logged"] += 1

        if len(self._buffer) >= self.threshold:
            self._extract()

    def flush(self) -> dict:
        """
        Force extraction of any remaining buffered turns.
        Call at end of session.
        Returns extraction stats.
        """
        if self._buffer:
            self._extract()
        self.graph.save()
        return dict(self._stats)

    def stats(self) -> dict:
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _extract(self) -> None:
        if not self._buffer:
            return

        turns_text = "\n".join(
            f"{t['role'].upper()}: {t['content']}" for t in self._buffer
        )
        self._buffer = []
        self._stats["extractions_run"] += 1

        raw = self._call_llm(turns_text)
        if not raw or "_error" in raw:
            self._stats["errors"] += 1
            return

        self._write(raw)

    def _call_llm(self, turns_text: str) -> dict | None:
        if self.backend == "ollama":
            return _call_ollama(turns_text, self.model)
        elif self.backend == "openai":
            return _call_openai_compat(turns_text, self.model, self.base_url, self.api_key)
        return None

    def _write(self, extracted: dict) -> None:
        """Write extracted nodes and edges into the graph."""
        nodes_data = extracted.get("nodes", [])
        edges_data = extracted.get("edges", [])

        # Build a content→node_id map for edge linking
        content_to_id: dict[str, str] = {n.content: n.id for n in self.graph.all_nodes()}

        for nd in nodes_data:
            confidence = float(nd.get("confidence", 0.0))
            content = (nd.get("content") or "").strip()
            if not content:
                continue

            if confidence < self.confidence_floor:
                self._stats["nodes_skipped"] += 1
                # Still log it as a low-confidence observation so it's auditable
                store.write_observation(
                    obs_id=new_id(),
                    content=f"[LOW_CONFIDENCE={confidence:.2f}] {content}",
                    path=self.db_path,
                    session_id=self.session_id,
                    role="observer",
                )
                continue

            try:
                node_type = NodeType(nd.get("type", "CONCEPT").upper())
            except ValueError:
                node_type = NodeType.CONCEPT

            tags = [t for t in (nd.get("tags") or []) if isinstance(t, str)]

            # Avoid duplicating very similar content (simple dedup)
            existing = self._find_similar(content)
            if existing:
                # Reinforce by updating last_activated
                existing.activation_count += 1
                existing.last_activated = now_iso()
                content_to_id[content] = existing.id
                self._stats["nodes_written"] += 1
                continue

            node = self.graph.add_node(type=node_type, content=content, tags=tags)
            content_to_id[content] = node.id
            self._stats["nodes_written"] += 1

        # Write edges
        for ed in edges_data:
            src_content = (ed.get("source_content") or "").strip()
            tgt_content = (ed.get("target_content") or "").strip()
            src_id = content_to_id.get(src_content)
            tgt_id = content_to_id.get(tgt_content)
            if not src_id or not tgt_id:
                continue

            try:
                edge_type = EdgeType(ed.get("type", "RELATED_TO").upper())
            except ValueError:
                edge_type = EdgeType.RELATED_TO

            weight = float(ed.get("weight", 0.8))
            self.graph.add_edge(src_id, tgt_id, edge_type, weight=weight)

    def _find_similar(self, content: str, threshold: float = 0.85):
        """
        Fuzzy dedup: return an existing node if its content is very similar
        to the new content. Uses character-level overlap (no ML needed).
        """
        content_lower = content.lower()
        for node in self.graph.all_nodes():
            existing_lower = node.content.lower()
            # Jaccard similarity on word sets
            a = set(content_lower.split())
            b = set(existing_lower.split())
            if not a or not b:
                continue
            jaccard = len(a & b) / len(a | b)
            if jaccard >= threshold:
                return node
        return None
