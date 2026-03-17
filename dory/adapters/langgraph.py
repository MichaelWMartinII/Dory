"""
LangGraph memory adapter for Dory.

Provides DoryMemoryNode — a class whose methods are designed to be used
as nodes in a LangGraph StateGraph. Handles memory retrieval, turn logging,
and end-of-session consolidation as discrete graph nodes.

Usage:
    from dory.adapters.langgraph import DoryMemoryNode, MemoryState
    from langgraph.graph import StateGraph, START, END

    mem = DoryMemoryNode(
        db_path="myapp.db",
        extract_model="claude-haiku-4-5-20251001",
        extract_backend="anthropic",
        extract_api_key="sk-ant-...",
    )

    builder = StateGraph(MemoryState)
    builder.add_node("load_memory", mem.load_context)
    builder.add_node("record_turn", mem.record_turn)
    builder.add_edge(START, "load_memory")
    builder.add_edge("load_memory", "record_turn")
    builder.add_edge("record_turn", END)
    graph = builder.compile()

    # In your agent loop:
    state = graph.invoke({"query": "What are we building?", "messages": []})
    # state["context"] is now populated with relevant memory
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from ..memory import DoryMemory


class MemoryState(TypedDict, total=False):
    """
    Typed state dict for LangGraph graphs that use DoryMemoryNode.

    Add these fields to your own StateGraph state to enable memory.
    """
    query: str                  # the current user query
    context: str                # memory context retrieved by load_context
    messages: list[dict]        # conversation messages [{"role": ..., "content": ...}]
    memory_stats: dict          # populated by consolidate()


class DoryMemoryNode:
    """
    LangGraph node class for Dory memory operations.

    Each public method has the signature ``(state: dict) -> dict``
    so it can be passed directly to ``StateGraph.add_node()``.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        extract_model: str | None = None,
        extract_backend: str = "ollama",
        extract_base_url: str = "http://localhost:11434",
        extract_api_key: str = "local",
    ) -> None:
        self._dory = DoryMemory(
            db_path=db_path,
            extract_model=extract_model,
            extract_backend=extract_backend,
            extract_base_url=extract_base_url,
            extract_api_key=extract_api_key,
        )

    # ------------------------------------------------------------------
    # Node functions (state → state)
    # ------------------------------------------------------------------

    def load_context(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Retrieve memory context relevant to the current query.
        Populates state["context"] with the result.
        Add this as the first node in your graph.
        """
        query = state.get("query", "")
        result = self._dory.build_context(query)
        return {**state, "context": result.full}

    def record_turn(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Log the most recent message to the episodic store.
        Reads from state["messages"] — expects the last entry to be the
        turn to record. No-op if messages is empty or no extract_model set.
        """
        messages = state.get("messages", [])
        if messages:
            last = messages[-1]
            role = last.get("role", "user")
            content = last.get("content", "")
            if content:
                self._dory.add_turn(role, str(content))
        return state

    def record_exchange(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Log the last user+assistant exchange (last two messages).
        Use instead of record_turn when your graph appends both turns at once.
        """
        messages = state.get("messages", [])
        for msg in messages[-2:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                self._dory.add_turn(role, str(content))
        return state

    def consolidate(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        End-of-session consolidation: flush pending turns, run decay/dedup.
        Populates state["memory_stats"] with consolidation results.
        Add this as a terminal node or call at session end.
        """
        stats = self._dory.flush()
        return {**state, "memory_stats": stats}

    # ------------------------------------------------------------------
    # Async node functions
    # Same signatures as sync versions — use these when your LangGraph
    # graph is compiled with async support (graph.ainvoke / astream).
    # ------------------------------------------------------------------

    async def aload_context(self, state: dict[str, Any]) -> dict[str, Any]:
        """Async version of load_context()."""
        query = state.get("query", "")
        result = await self._dory.abuild_context(query)
        return {**state, "context": result.full}

    async def arecord_turn(self, state: dict[str, Any]) -> dict[str, Any]:
        """Async version of record_turn()."""
        messages = state.get("messages", [])
        if messages:
            last = messages[-1]
            role = last.get("role", "user")
            content = last.get("content", "")
            if content:
                await self._dory.aadd_turn(role, str(content))
        return state

    async def arecord_exchange(self, state: dict[str, Any]) -> dict[str, Any]:
        """Async version of record_exchange()."""
        messages = state.get("messages", [])
        for msg in messages[-2:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                await self._dory.aadd_turn(role, str(content))
        return state

    async def aconsolidate(self, state: dict[str, Any]) -> dict[str, Any]:
        """Async version of consolidate()."""
        stats = await self._dory.aflush()
        return {**state, "memory_stats": stats}

    # ------------------------------------------------------------------
    # Direct access
    # ------------------------------------------------------------------

    @property
    def dory(self) -> DoryMemory:
        return self._dory

    def observe(self, content: str, node_type: str = "CONCEPT") -> str:
        """Manually add a memory node. Returns the new node ID."""
        return self._dory.observe(content, node_type=node_type)
