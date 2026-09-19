"""Tests for summary truncation handling (appended to tests/test_summarizer.py)."""
import sys, types
import pytest
from dory.pipeline import summarizer as S


class _Resp:
    def __init__(self, text, stop_reason):
        self.content = [types.SimpleNamespace(text=text)]
        self.stop_reason = stop_reason


def _fake_anthropic(monkeypatch, text, stop_reason):
    """Stand in for the anthropic SDK so no network call is made."""
    class _Messages:
        def create(self, **kw):
            _Messages.seen = kw
            return _Resp(text, stop_reason)
    class _Client:
        def __init__(self, api_key=None): self.messages = _Messages()
    mod = types.ModuleType("anthropic"); mod.Anthropic = _Client
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return _Messages


def test_truncated_summary_reports_truncation_not_parse_failure(monkeypatch):
    # A real 15k-char session needed 1263 output tokens; the old 1024 cap cut
    # the JSON mid-key and the failure was reported as a parser problem.
    _fake_anthropic(monkeypatch, '{"summary": "it was going fine until', "max_tokens")
    out = S._call_anthropic("USER: hello", "claude-haiku-4-5-20251001", "k")
    assert "truncated" in out["_error"]
    assert "JSON parse failed" not in out["_error"]


def test_truncated_structured_summary_also_reports_truncation(monkeypatch):
    _fake_anthropic(monkeypatch, '{"summary": "cut off here', "max_tokens")
    out = S._call_anthropic_summary("USER: hello", "claude-haiku-4-5-20251001", "k")
    assert "truncated" in out["_error"]


def test_genuine_parse_failure_still_says_so(monkeypatch):
    # Not truncated — the model simply did not return JSON.
    _fake_anthropic(monkeypatch, "I'm afraid I can't do that.", "end_turn")
    out = S._call_anthropic("USER: hello", "claude-haiku-4-5-20251001", "k")
    assert out["_error"] == "JSON parse failed"


def test_summary_calls_request_the_raised_cap(monkeypatch):
    msgs = _fake_anthropic(monkeypatch, '{"summary": "ok"}', "end_turn")
    S._call_anthropic("USER: hello", "claude-haiku-4-5-20251001", "k")
    assert msgs.seen["max_tokens"] == S.SUMMARY_MAX_TOKENS == 4096
