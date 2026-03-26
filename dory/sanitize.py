from __future__ import annotations

"""
Adversarial memory injection defense.

Sanitizes content before it enters the memory graph. Two threat models:

1. Prompt injection — user or extracted content contains instructions designed
   to override the LLM's behavior when the memory is injected into a future prompt.
   Detected via pattern matching; flagged content is still stored but tagged so
   the caller can decide whether to reject or quarantine it.

2. Flooding — extremely long content that would dominate any context window.
   Truncated to safe limits.

Usage:
    from dory.sanitize import sanitize_node_content, sanitize_observation

    clean, flagged, reason = sanitize_node_content(raw_content)
    if flagged:
        # log or reject
"""

import re
from typing import NamedTuple


# Maximum content length for a single memory node (characters).
# ~1000 chars ≈ 250 tokens — a node that long is almost certainly not a clean
# fact extraction anyway.
MAX_NODE_CONTENT_LEN = 1000

# Maximum length for raw observation turns stored in the episodic log.
# Longer than node content since full message turns can be verbose.
MAX_OBSERVATION_LEN = 8000


class SanitizeResult(NamedTuple):
    content: str   # sanitized (possibly truncated) content
    flagged: bool  # True if injection pattern detected or length exceeded
    reason: str    # comma-separated list of reasons, empty string if clean


# ---------------------------------------------------------------------------
# Injection patterns
# Each tuple is (compiled_regex, label).
# Patterns are ordered from most dangerous/specific to least.
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Classic instruction overrides
    (re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE), "instruction_override"),
    (re.compile(r"(?:disregard|forget|override)\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|context|memory|rules?)", re.IGNORECASE), "context_override"),
    # Persona hijacking
    (re.compile(r"\byou\s+are\s+now\s+(?:a\s+|an\s+)?\w", re.IGNORECASE), "persona_override"),
    (re.compile(r"act\s+as\s+(?:a\s+|an\s+)?(?:different|new|another|evil|unrestricted)\b", re.IGNORECASE), "persona_override"),
    # Chat template tokens used to inject fake system/user turns
    (re.compile(r"<\|(?:system|user|assistant|im_start|im_end)\|>", re.IGNORECASE), "chat_template_token"),
    (re.compile(r"\[(?:INST|SYS|SYSTEM)\]", re.IGNORECASE), "llama_template_token"),
    (re.compile(r"###\s*(?:system|instruction|human|assistant)\s*[\n:]", re.IGNORECASE), "alpaca_template"),
    (re.compile(r"<(?:system|instruction)>\s*\S", re.IGNORECASE), "xml_system_tag"),
    # Memory-specific injection attempts
    (re.compile(r"(?:always|never)\s+(?:say|respond|answer|tell)", re.IGNORECASE), "behavioral_override"),
    (re.compile(r"your\s+(?:real|true|actual|secret)\s+(?:instructions?|purpose|goal|task)\s+(?:is|are)\b", re.IGNORECASE), "identity_override"),
]


def sanitize_node_content(content: str) -> SanitizeResult:
    """
    Sanitize a memory node's content before writing to the graph.

    Returns (content, flagged, reason).
    - content  : truncated if over limit, otherwise unchanged
    - flagged  : True if any issue found (injection pattern or truncation)
    - reason   : comma-separated labels, e.g. "truncated,injection:instruction_override"

    The caller decides what to do with flagged content. Dory's default is to
    still store it (so it's auditable) but tag it with "flagged" so retrieval
    can downweight or exclude it.
    """
    if not content:
        return SanitizeResult("", False, "")

    reasons: list[str] = []

    if len(content) > MAX_NODE_CONTENT_LEN:
        content = content[:MAX_NODE_CONTENT_LEN] + "…"
        reasons.append("truncated")

    for pattern, label in _INJECTION_PATTERNS:
        if pattern.search(content):
            reasons.append(f"injection:{label}")

    flagged = bool(reasons)
    return SanitizeResult(content, flagged, ",".join(reasons))


def sanitize_observation(content: str) -> SanitizeResult:
    """
    Lighter sanitization for raw observation turns (episodic log).
    Allows longer content than node content; same injection detection.
    """
    if not content:
        return SanitizeResult("", False, "")

    reasons: list[str] = []

    if len(content) > MAX_OBSERVATION_LEN:
        content = content[:MAX_OBSERVATION_LEN] + "…"
        reasons.append("truncated")

    for pattern, label in _INJECTION_PATTERNS:
        if pattern.search(content):
            reasons.append(f"injection:{label}")

    flagged = bool(reasons)
    return SanitizeResult(content, flagged, ",".join(reasons))
