"""
LangChain memory adapter for Dory.

Implements LangChain's BaseMemory interface so Dory can be used as a
drop-in memory backend in any LangChain chain or agent.

Usage:
    from dory.adapters.langchain import DoryMemoryAdapter
    from langchain.chains import ConversationChain
    from langchain_anthropic import ChatAnthropic

    memory = DoryMemoryAdapter(
        db_path="myapp.db",
        extract_model="claude-haiku-4-5-20251001",
        extract_backend="anthropic",
        extract_api_key="sk-ant-...",
    )

    chain = ConversationChain(
        llm=ChatAnthropic(model="claude-sonnet-4-6"),
        memory=memory,
    )

    response = chain.invoke({"input": "What are we working on?"})
    # memory context is injected automatically via load_memory_variables()
    # turns are saved automatically via save_context()
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..memory import DoryMemory
from .. import store as _store


class DoryMemoryAdapter:
    """
    LangChain-compatible memory backend backed by Dory.

    Exposes two memory variables:
      - ``context``  — spreading-activation retrieval from the graph
      - ``history``  — last N raw turns from the episodic store

    Compatible with langchain BaseMemory duck-typing without requiring
    langchain as a hard dependency.
    """

    memory_variables: list[str] = ["context", "history"]

    def __init__(
        self,
        db_path: str | Path | None = None,
        extract_model: str | None = None,
        extract_backend: str = "ollama",
        extract_base_url: str = "http://localhost:11434",
        extract_api_key: str = "local",
        history_turns: int = 6,
        input_key: str = "input",
        output_key: str = "output",
    ) -> None:
        self._dory = DoryMemory(
            db_path=db_path,
            extract_model=extract_model,
            extract_backend=extract_backend,
            extract_base_url=extract_base_url,
            extract_api_key=extract_api_key,
        )
        self._history_turns = history_turns
        self._input_key = input_key
        self._output_key = output_key

    # ------------------------------------------------------------------
    # LangChain BaseMemory interface
    # ------------------------------------------------------------------

    def load_memory_variables(self, inputs: dict[str, Any]) -> dict[str, str]:
        """
        Called at the start of each chain run.
        Retrieves memory context relevant to the current input.
        """
        query = inputs.get(self._input_key, "")
        result = self._dory.build_context(query)
        return {
            "context": result.full,
            "history": self._recent_history(),
        }

    def save_context(
        self,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
    ) -> None:
        """Called at the end of each chain run. Logs both turns."""
        user_msg = str(inputs.get(self._input_key, ""))
        ai_msg = str(outputs.get(self._output_key, ""))
        if user_msg:
            self._dory.add_turn("user", user_msg)
        if ai_msg:
            self._dory.add_turn("assistant", ai_msg)

    def clear(self) -> None:
        """Flush memory and run consolidation."""
        self._dory.flush()

    # ------------------------------------------------------------------
    # Async interface
    # ------------------------------------------------------------------

    async def aload_memory_variables(
        self, inputs: dict[str, Any]
    ) -> dict[str, str]:
        """Async version of load_memory_variables() for use with async chains."""
        query = inputs.get(self._input_key, "")
        result = await self._dory.abuild_context(query)
        return {
            "context": result.full,
            "history": self._recent_history(),
        }

    async def asave_context(
        self,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
    ) -> None:
        """Async version of save_context()."""
        user_msg = str(inputs.get(self._input_key, ""))
        ai_msg = str(outputs.get(self._output_key, ""))
        if user_msg:
            await self._dory.aadd_turn("user", user_msg)
        if ai_msg:
            await self._dory.aadd_turn("assistant", ai_msg)

    async def aclear(self) -> None:
        """Async flush."""
        await self._dory.aflush()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _recent_history(self) -> str:
        obs = _store.get_observations(
            self._dory.graph.path,
            limit=self._history_turns,
        )
        if not obs:
            return ""
        return "\n".join(
            f"{o['role'].upper()}: {o['content']}" for o in reversed(obs)
        )

    # Expose underlying DoryMemory for power users
    @property
    def dory(self) -> DoryMemory:
        return self._dory
