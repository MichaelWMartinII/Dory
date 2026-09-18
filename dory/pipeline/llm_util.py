"""
Shared helpers for the pipeline's LLM calls.

Local models don't always honor JSON mode. Reasoning models prepend
<think> blocks, and some (Gemma 4 via Ollama) wrap the object in a
```json fence even when the request asks for bare JSON. A strict
json.loads() rejects both, and the extraction is silently lost.
"""

from __future__ import annotations

import json
import re

# Local models on consumer hardware are slow; 60s dropped real extractions.
LLM_TIMEOUT = 180

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_llm_json(raw: str | None) -> dict | None:
    """Return the JSON object in raw model output, or None if there isn't one."""
    text = _THINK_RE.sub("", raw or "").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = _OBJECT_RE.search(text)
        if not match:
            return None
        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None
