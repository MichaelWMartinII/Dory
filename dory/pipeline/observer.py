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
from .. import store, session as _session
from ..sanitize import sanitize_node_content

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a precise memory extraction system for an AI agent.
Given a conversation, extract only durable, meaningful facts worth remembering long-term.

Return ONLY valid JSON matching this schema exactly:
{
  "nodes": [
    {
      "type": "ENTITY | CONCEPT | EVENT | PREFERENCE | BELIEF | PROCEDURE",
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
- EVENT: something that happened or was decided. If a session date is provided at the top
  and the event includes relative timing ("yesterday", "last week", "a month ago", "2 weeks
  ago"), calculate and include the approximate absolute date in the content.
  Example: "User bought smoker (approx. 2023-03-10, purchased about a week before session 2023-03-17)"
  Example: "User attended baking class (approx. 2022-03-20, mentioned as yesterday in session 2022-03-21)"
- PREFERENCE: a stated or clearly implied preference or working style. Capture these signals:
  positive ("I like/love/enjoy/prefer"), negative ("I hate/dislike/avoid", "this sucked"),
  commitment ("I'll stick with", "I always use", "I never"), and repeated behavior
  (choosing the same thing multiple times). Do not require explicit "I prefer" language.
  IMPORTANT — also extract PREFERENCE for:
  * Personal lifestyle choices and routines (bedtime habits, dietary choices, exercise patterns)
    even when described procedurally. "User winds down with meditation before 9:30 PM and
    avoids phone use in the evening" is a PREFERENCE, not just a PROCEDURE.
  * Viewing/listening/reading habits: genre, platform, format. "User watches Netflix stand-up
    specials" and "User listens to history podcasts (Hardcore History, Lore)" are PREFERENCES.
  * Dietary and recipe choices: "User makes coffee creamer with almond milk, vanilla, honey"
    reveals a PREFERENCE for natural/homemade creamers — extract that, not just the recipe steps.
  * Avoidances and constraints with conditions: "no phone after 9:30 PM", "avoids crowded venues",
    "prefers under 45-minute workouts". Capture the constraint, not just the general topic.
  When a PROCEDURE also reveals a clear personal preference, extract BOTH nodes.
- BELIEF: an assertion about the world the speaker holds to be true
- PROCEDURE: a repeatable step-by-step process, workflow, skill, or algorithm the user applies
- confidence: 0.9+ for explicitly stated facts, 0.7-0.89 for strongly implied, below 0.7 for uncertain
- Only extract facts that would still be useful in a future unrelated session
- Skip pleasantries, filler, and transient task details
- Keep content concise but specific — aim for one clear sentence per node
- Do NOT generalize away specificity. Preserve: genre names, platform names, brand names,
  time constraints, frequency constraints, and qualifying conditions.
  WRONG: "User likes comedy" — RIGHT: "User prefers Netflix stand-up comedy specials with strong storytelling"
  WRONG: "User enjoys podcasts" — RIGHT: "User prefers history podcasts (Hardcore History, Lore, The Dollop) during commute"
  WRONG: "User has bedtime habits" — RIGHT: "User avoids phone use after 9:30 PM as part of wind-down routine"
- Return {"nodes": [], "edges": []} if nothing meaningful to extract"""

_USER_TEMPLATE = """Extract memories from this conversation:

{turns}"""

_USER_TEMPLATE_WITH_DATE = """Session date: {session_date}

Extract memories from this conversation:

{turns}"""


# ---------------------------------------------------------------------------
# Implicit preference inference prompt
# ---------------------------------------------------------------------------

_IMPLICIT_PREF_SYSTEM = """You are inferring IMPLICIT preferences — things someone values or prefers that were NEVER explicitly stated.

Given a list of facts (events, entities, concepts) extracted from a conversation, identify preferences implied by patterns or choices described, even if the person never said "I prefer" or "I like."

Examples of valid inferences:
- Multiple cooking events → "Prefers home cooking over eating out"
- Repeated 5am workout mentions → "Prefers early morning exercise"
- Jazz chosen in two different contexts → "Prefers jazz music"
- Evening meditation described as routine → "Prefers evening wind-down with meditation"

Return ONLY valid JSON:
{
  "inferred_preferences": [
    {
      "content": "concise preference statement (e.g. 'Prefers X over Y' or 'Values X')",
      "confidence": 0.75,
      "basis": "one sentence: what behavior implies this"
    }
  ]
}

Rules:
- Only infer from CLEAR behavioral patterns, NOT single mentions
- Confidence 0.9+ only when the implication is near-certain
- 0.7–0.89 for strong but not certain implications
- Do NOT re-infer preferences that were already explicitly extracted
- Return {"inferred_preferences": []} if nothing clear to infer"""


# ---------------------------------------------------------------------------
# LLM backends
# ---------------------------------------------------------------------------

def _user_message(turns_text: str, session_date: str = "") -> str:
    if session_date:
        return _USER_TEMPLATE_WITH_DATE.format(session_date=session_date, turns=turns_text)
    return _USER_TEMPLATE.format(turns=turns_text)


def _call_ollama(turns_text: str, model: str, session_date: str = "") -> dict | None:
    try:
        import ollama
        resp = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _user_message(turns_text, session_date)},
            ],
            format="json",
            think=False,
            options={"temperature": 0.1},
        )
        return json.loads(resp["message"]["content"])
    except Exception as e:
        return {"_error": str(e)}


def _call_openai_compat(turns_text: str, model: str, base_url: str, api_key: str = "local", session_date: str = "") -> dict | None:
    try:
        import httpx
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _user_message(turns_text, session_date)},
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
        # Strip <think>...</think> blocks (Qwen3 and similar reasoning models)
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return _extract_json(content) or {"_error": "JSON parse failed"}
    except Exception as e:
        return {"_error": str(e)}


def _call_anthropic(turns_text: str, model: str, api_key: str, session_date: str = "") -> dict | None:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": _user_message(turns_text, session_date)}
            ],
        )
        raw = resp.content[0].text
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return _extract_json(raw) or {"_error": "JSON parse failed"}
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
        infer_implicit: bool = False,
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
        self.infer_implicit = infer_implicit

        self._buffer: list[dict] = []
        self._stats = {"turns_logged": 0, "extractions_run": 0, "nodes_written": 0, "nodes_skipped": 0, "implicit_inferred": 0, "errors": 0}

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

    def flush(self, session_date: str = "") -> dict:
        """
        Force extraction of any remaining buffered turns.
        Call at end of session.
        Returns extraction stats.
        """
        if self._buffer:
            self._extract(session_date=session_date)
        self.graph.save()
        return dict(self._stats)

    def stats(self) -> dict:
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _extract(self, session_date: str = "") -> None:
        if not self._buffer:
            return

        turns_text = "\n".join(
            f"{t['role'].upper()}: {t['content']}" for t in self._buffer
        )
        self._buffer = []
        self._stats["extractions_run"] += 1

        raw = self._call_llm(turns_text, session_date=session_date)
        if not raw or "_error" in raw:
            self._stats["errors"] += 1
            return

        self._write(raw)

        # Optional second pass: infer implicit preferences from extracted events/concepts
        if self.infer_implicit and raw.get("nodes"):
            implicit = self._infer_implicit_preferences(raw["nodes"])
            if implicit:
                self._write({"nodes": implicit, "edges": []})
                self._stats["implicit_inferred"] += len(implicit)

    def _call_llm(self, turns_text: str, session_date: str = "") -> dict | None:
        if self.backend == "ollama":
            return _call_ollama(turns_text, self.model, session_date=session_date)
        elif self.backend == "openai":
            return _call_openai_compat(turns_text, self.model, self.base_url, self.api_key, session_date=session_date)
        elif self.backend == "anthropic":
            return _call_anthropic(turns_text, self.model, self.api_key, session_date=session_date)
        return None

    def _write(self, extracted: dict) -> None:
        """Write extracted nodes and edges into the graph."""
        nodes_data = extracted.get("nodes", [])
        edges_data = extracted.get("edges", [])

        # Build a content→node_id map for edge linking
        content_to_id: dict[str, str] = {n.content: n.id for n in self.graph.all_nodes()}

        for nd in nodes_data:
            confidence = float(nd.get("confidence", 0.0))
            raw_content = (nd.get("content") or "").strip()
            if not raw_content:
                continue

            # Sanitize before confidence check so truncation/flags are always applied
            content, flagged, flag_reason = sanitize_node_content(raw_content)

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
            if flagged:
                tags.append("flagged")
                if flag_reason:
                    tags.append(f"flag_reason:{flag_reason[:64]}")

            # Avoid duplicating very similar content (simple dedup)
            existing = self._find_similar(content)
            if existing:
                # Reinforce by updating last_activated
                existing.activation_count += 1
                existing.last_activated = now_iso()
                content_to_id[content] = existing.id
                self._stats["nodes_written"] += 1
                continue

            node_id = _session.observe(content, node_type, self.graph, tags=tags)
            content_to_id[content] = node_id
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

    def _infer_implicit_preferences(self, extracted_nodes: list[dict]) -> list[dict]:
        """
        Second-pass inference: given nodes extracted from this batch, ask the LLM
        to identify any preferences implied by behaviors/choices that weren't
        explicitly stated as preferences.

        Only runs if infer_implicit=True. Returns node dicts ready for _write().
        """
        # Only reason over events/concepts/entities with sufficient confidence
        source_nodes = [
            n for n in extracted_nodes
            if n.get("type", "").upper() in ("EVENT", "CONCEPT", "ENTITY")
            and float(n.get("confidence", 0)) >= 0.7
        ]
        if len(source_nodes) < 2:
            return []

        facts = "\n".join(f"- [{n['type'].upper()}] {n['content']}" for n in source_nodes)

        raw: dict | None = None
        try:
            if self.backend == "ollama":
                import ollama
                resp = ollama.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": _IMPLICIT_PREF_SYSTEM},
                        {"role": "user", "content": f"Facts:\n{facts}"},
                    ],
                    format="json",
                    think=False,
                    options={"temperature": 0.1},
                )
                raw = json.loads(resp["message"]["content"])
            elif self.backend == "anthropic":
                import anthropic
                client = anthropic.Anthropic(api_key=self.api_key)
                resp = client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    system=_IMPLICIT_PREF_SYSTEM,
                    messages=[{"role": "user", "content": f"Facts:\n{facts}"}],
                )
                raw = json.loads(resp.content[0].text)
            elif self.backend == "openai":
                import httpx
                r = httpx.post(
                    f"{self.base_url.rstrip('/')}/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": _IMPLICIT_PREF_SYSTEM},
                            {"role": "user", "content": f"Facts:\n{facts}"},
                        ],
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                    },
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=60,
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                raw = json.loads(content)
        except Exception:
            return []

        if not raw:
            return []

        inferred = raw.get("inferred_preferences", [])
        return [
            {
                "type": "PREFERENCE",
                "content": p.get("content", "").strip(),
                "tags": ["inferred"],
                "confidence": float(p.get("confidence", 0.7)),
            }
            for p in inferred
            if p.get("content", "").strip() and float(p.get("confidence", 0)) >= 0.7
        ]

    def _find_similar(self, content: str, threshold: float = 0.85):
        """
        Fuzzy dedup: return an existing node if its content is very similar
        to the new content.

        Uses FTS to get a small candidate set first (fast path), then computes
        Jaccard similarity only on those candidates. Falls back to an in-memory
        scan when FTS returns no results — covers nodes added in the current
        extraction batch that haven't been flushed to SQLite yet.
        """
        from .. import store
        from ..activation import _fts_query

        a = set(content.lower().split())
        if not a:
            return None

        fts_q = _fts_query(content, n=8)
        candidate_ids = store.search_fts(fts_q, self.db_path, limit=20) if fts_q else []

        # Fast path: check FTS candidates
        for node_id in candidate_ids:
            node = self.graph.get_node(node_id)
            if not node:
                continue
            b = set(node.content.lower().split())
            if not b:
                continue
            if len(a & b) / len(a | b) >= threshold:
                return node

        # Fallback: in-memory scan for nodes not yet flushed to SQLite
        # (e.g. nodes written in the current extraction batch)
        indexed = set(candidate_ids)
        for node in self.graph.all_nodes():
            if node.id in indexed:
                continue  # already checked above
            b = set(node.content.lower().split())
            if not b:
                continue
            if len(a & b) / len(a | b) >= threshold:
                return node

        return None
