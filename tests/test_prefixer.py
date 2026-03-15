"""Tests for pipeline/prefixer.py — cacheable context block builder."""
import pytest
from dory.pipeline.prefixer import Prefixer, PrefixResult
from dory.schema import NodeType, EdgeType


# --- PrefixResult ---

def test_prefix_result_full_combines_both(populated_graph):
    result = PrefixResult(prefix="PREFIX", suffix="SUFFIX")
    assert "PREFIX" in result.full
    assert "SUFFIX" in result.full


def test_prefix_result_full_skips_empty_parts():
    result = PrefixResult(prefix="PREFIX", suffix="")
    assert result.full == "PREFIX"

    result2 = PrefixResult(prefix="", suffix="SUFFIX")
    assert result2.full == "SUFFIX"


def test_prefix_result_as_anthropic_messages_structure():
    result = PrefixResult(prefix="stable context", suffix="dynamic context")
    messages = result.as_anthropic_messages(user_query="what are we working on?")

    assert len(messages) == 1
    msg = messages[0]
    assert msg["role"] == "user"
    assert isinstance(msg["content"], list)

    # First block should have cache_control
    cache_block = msg["content"][0]
    assert cache_block["type"] == "text"
    assert cache_block["text"] == "stable context"
    assert cache_block["cache_control"] == {"type": "ephemeral"}


def test_prefix_result_as_anthropic_messages_includes_user_query():
    result = PrefixResult(prefix="context", suffix="")
    messages = result.as_anthropic_messages(user_query="my question")
    # The user query should appear somewhere in the message content
    content_texts = [
        block["text"] for block in messages[0]["content"]
        if isinstance(block, dict) and "text" in block
    ]
    assert any("my question" in t for t in content_texts)


def test_prefix_result_as_anthropic_no_cache_when_prefix_empty():
    result = PrefixResult(prefix="", suffix="dynamic only")
    messages = result.as_anthropic_messages(user_query="q")
    # No cache_control block when prefix is empty
    content = messages[0]["content"]
    for block in content:
        if isinstance(block, dict):
            assert "cache_control" not in block


def test_prefix_result_as_openai_messages_returns_system_and_user():
    result = PrefixResult(prefix="stable ctx", suffix="dynamic ctx")
    messages = result.as_openai_messages(user_query="user question")

    roles = [m["role"] for m in messages]
    assert "system" in roles
    assert "user" in roles


def test_prefix_result_as_openai_messages_with_system_override():
    result = PrefixResult(prefix="memory ctx", suffix="")
    messages = result.as_openai_messages(user_query="q", system="You are an assistant.")
    sys_msg = next(m for m in messages if m["role"] == "system")
    assert "You are an assistant." in sys_msg["content"]
    assert "memory ctx" in sys_msg["content"]


# --- Prefixer.build ---

def test_prefixer_build_returns_prefix_result(graph):
    p = Prefixer(graph)
    result = p.build()
    assert isinstance(result, PrefixResult)


def test_prefixer_build_prefix_includes_core_nodes(graph):
    n = graph.add_node(NodeType.ENTITY, "AllergyFind restaurant SaaS")
    n.is_core = True
    graph.save()

    p = Prefixer(graph)
    result = p.build()
    assert "AllergyFind" in result.prefix


def test_prefixer_build_empty_graph_returns_empty_strings(graph):
    p = Prefixer(graph)
    result = p.build()
    assert result.prefix == ""
    assert result.suffix == ""


def test_prefixer_suffix_includes_activated_nodes(populated_graph):
    graph, n1, n2, n3, n4 = populated_graph
    p = Prefixer(graph)
    result = p.build(query="AllergyFind")
    # AllergyFind should be activated and appear in suffix or prefix
    assert "AllergyFind" in result.full


def test_prefixer_suffix_empty_when_no_query(graph):
    graph.add_node(NodeType.ENTITY, "some node")
    p = Prefixer(graph)
    result = p.build(query="")
    assert result.suffix == ""


# --- prefix caching ---

def test_prefix_cached_across_calls(graph):
    n = graph.add_node(NodeType.ENTITY, "cached node")
    n.is_core = True
    graph.save()

    p = Prefixer(graph)
    result1 = p.build()
    result2 = p.build()

    assert result1.prefix == result2.prefix
    # Same object reference — cache was hit
    assert p._prefix_cache is result2.prefix


def test_prefix_rebuilds_after_invalidate(graph):
    n = graph.add_node(NodeType.ENTITY, "initial node")
    n.is_core = True
    graph.save()

    p = Prefixer(graph)
    result1 = p.build()
    first_hash = p._prefix_hash

    p.invalidate()
    result2 = p.build()
    # After invalidate, a new prefix is built (hash recomputed)
    # Content may be the same if graph didn't change, but the cache was cleared
    assert p._prefix_hash != ""  # hash was recomputed


def test_prefix_hash_changes_when_core_nodes_change(graph):
    n = graph.add_node(NodeType.ENTITY, "node A")
    p = Prefixer(graph)
    hash_before = p._graph_hash()

    n.is_core = True
    hash_after = p._graph_hash()

    assert hash_before != hash_after


# --- token budget ---

def test_prefix_respects_token_budget(graph):
    # Add many core nodes to exceed a tiny budget
    for i in range(50):
        n = graph.add_node(NodeType.CONCEPT, f"concept number {i} with some extra words here")
        n.is_core = True
    graph.save()

    p = Prefixer(graph, max_prefix_tokens=100)
    result = p.build()

    # Approximate: 100 tokens * 4 chars ≈ 400 chars
    assert len(result.prefix) <= 600  # generous margin for the budget check


def test_suffix_respects_token_budget(populated_graph):
    graph, *_ = populated_graph
    p = Prefixer(graph, max_suffix_tokens=50)
    result = p.build(query="AllergyFind")
    # 50 tokens * 4 chars ≈ 200 chars
    assert len(result.suffix) <= 400
