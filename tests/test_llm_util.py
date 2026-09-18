"""Tests for pipeline/llm_util.py — tolerant JSON parsing of local-model output."""
import logging
import sys
from unittest.mock import MagicMock, patch

from dory.pipeline.llm_util import parse_llm_json
from dory.pipeline.observer import Observer


def test_parses_bare_json():
    assert parse_llm_json('{"nodes": []}') == {"nodes": []}


def test_parses_fenced_json():
    # Gemma 4 via Ollama wraps its output like this even in JSON mode
    raw = '```json\n{"nodes": [{"content": "x"}]}\n```'
    assert parse_llm_json(raw) == {"nodes": [{"content": "x"}]}


def test_ignores_braces_inside_think_block():
    raw = '<think>maybe {"nodes": ["wrong"]}</think>\n{"nodes": ["right"]}'
    assert parse_llm_json(raw) == {"nodes": ["right"]}


def test_returns_none_without_an_object():
    assert parse_llm_json("I couldn't find anything to extract.") is None
    assert parse_llm_json("[1, 2, 3]") is None
    assert parse_llm_json("") is None
    assert parse_llm_json(None) is None


def test_observer_ollama_backend_accepts_fenced_output(db_path, graph):
    fenced = (
        '```json\n{"nodes": [{"type": "ENTITY", "content": "Lila is a three year old lab mix",'
        ' "confidence": 0.9, "tags": []}], "edges": []}\n```'
    )
    fake_ollama = MagicMock()
    fake_ollama.chat.return_value = {"message": {"content": fenced}}
    with patch.dict(sys.modules, {"ollama": fake_ollama}):
        obs = Observer(graph, db_path=db_path, threshold=10)
        obs.add_turn("user", "My dog Lila is a three year old lab mix.")
        stats = obs.flush()

    assert stats["errors"] == 0
    assert fake_ollama.chat.call_args.kwargs["think"] is False
    assert any("Lila" in n.content for n in graph.all_nodes())


def test_observer_logs_extraction_errors(db_path, graph, caplog):
    with patch("dory.pipeline.observer._call_ollama", return_value={"_error": "timed out"}):
        obs = Observer(graph, db_path=db_path, threshold=10)
        obs.add_turn("user", "My dog Lila is a three year old lab mix.")
        with caplog.at_level(logging.WARNING, logger="dory.pipeline.observer"):
            stats = obs.flush()

    assert stats["errors"] == 1
    assert "timed out" in caplog.text
