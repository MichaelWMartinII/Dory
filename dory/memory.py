from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .graph import Graph
from .schema import NodeType
from .pipeline.prefixer import Prefixer, PrefixResult
from .pipeline.observer import Observer
from . import session as _session, consolidation


class DoryMemory:
    """
    High-level memory interface for any AI application.

    Drop this into any LLM pipeline to give your agent persistent, structured
    memory across sessions. Works with any model — local or cloud.

    Quick start (manual observations only):
        mem = DoryMemory()
        context = mem.query("what are we working on")
        mem.observe("User is building a B2B allergen platform")
        mem.flush()

    With auto-extraction — choose your backend:

        # Local (Ollama)
        mem = DoryMemory(extract_model="qwen3:14b")

        # Anthropic (Claude)
        mem = DoryMemory(
            extract_model="claude-haiku-4-5-20251001",
            extract_backend="anthropic",
            extract_api_key="sk-ant-...",
        )

        # OpenAI (GPT / Grok / any compat endpoint)
        mem = DoryMemory(
            extract_model="gpt-4o-mini",
            extract_backend="openai",
            extract_api_key="sk-...",
        )

    Inject into API calls:
        result = mem.build_context("current topic")
        messages = result.as_anthropic_messages(user_query)   # Anthropic SDK
        messages = result.as_openai_messages(user_query)       # OpenAI / compat

    Parameters
    ----------
    db_path : str | Path | None
        Path to the SQLite memory file. Defaults to ./engram.db.
    extract_model : str | None
        Model name for auto-extraction from conversation turns.
        None disables auto-extraction (manual observe() only).
    extract_backend : str
        "ollama" (default), "anthropic", or "openai".
    extract_base_url : str
        Base URL for OpenAI-compatible endpoints (Ollama, llama.cpp, vLLM, etc.).
    extract_api_key : str
        API key for Anthropic or OpenAI backends.
    session_id : str | None
        ID for this session. Auto-generated if not provided.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        extract_model: str | None = None,
        extract_backend: str = "ollama",
        extract_base_url: str = "http://localhost:11434",
        extract_api_key: str = "local",
        session_id: str | None = None,
        infer_implicit: bool = False,
    ):
        from .store import DEFAULT_GRAPH_PATH
        path = Path(db_path) if db_path else DEFAULT_GRAPH_PATH
        self._graph = Graph(path=path)
        self._prefixer = Prefixer(self._graph, db_path=path)
        self._observer: Observer | None = None
        self._executor = ThreadPoolExecutor()
        if extract_model:
            self._observer = Observer(
                self._graph,
                db_path=path,
                model=extract_model,
                backend=extract_backend,
                base_url=extract_base_url,
                api_key=extract_api_key,
                session_id=session_id,
                infer_implicit=infer_implicit,
            )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def query(self, topic: str) -> str:
        """
        Query for context relevant to a topic.
        Returns a formatted string ready to inject into a system prompt.
        """
        return _session.query(topic, self._graph)

    def build_context(self, query: str = "") -> PrefixResult:
        """
        Build a stable prefix + dynamic suffix for this query.

        The prefix is identical across turns until memory changes —
        enabling prompt cache hits on every turn.

        Returns a PrefixResult with:
            .full                              — plain string injection
            .as_anthropic_messages(query)      — Anthropic SDK with cache_control
            .as_openai_messages(query)         — OpenAI / any compat endpoint
        """
        return self._prefixer.build(query)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def add_turn(self, role: str, content: str) -> None:
        """
        Log a conversation turn.

        If auto-extraction is enabled, memories are extracted from the
        conversation periodically as the buffer fills, then written to the graph.
        If no extract_model was provided, this is a no-op.
        """
        if self._observer:
            self._observer.add_turn(role, content)

    def observe(
        self,
        content: str,
        node_type: str = "CONCEPT",
        tags: list[str] | None = None,
    ) -> str:
        """
        Manually add a memory to the graph. Auto-links to related nodes.
        Returns the new node ID.

        node_type: "ENTITY" | "CONCEPT" | "EVENT" | "PREFERENCE" | "BELIEF"
        """
        try:
            ntype = NodeType(node_type.upper())
        except ValueError:
            ntype = NodeType.CONCEPT
        node_id = _session.observe(content, ntype, self._graph, tags=tags)
        self._graph.save()  # keep FTS index current so subsequent observes can link to this node
        return node_id

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def flush(self) -> dict:
        """
        End the session.

        Flushes any buffered turns, extracts remaining memories, then runs
        full consolidation: edge decay, node zone management, deduplication,
        supersession detection, and core promotion.

        Returns a combined stats dict.
        """
        extraction_stats: dict = {}
        if self._observer:
            extraction_stats = self._observer.flush()
        consolidation_stats = consolidation.run(self._graph)
        self._prefixer.invalidate()
        return {**extraction_stats, **consolidation_stats}

    # ------------------------------------------------------------------
    # Async API
    # All async methods delegate to their sync counterparts via run_in_executor,
    # so they are safe to await from FastAPI, LangGraph, and other async frameworks
    # without blocking the event loop.
    # ------------------------------------------------------------------

    async def aquery(self, topic: str) -> str:
        """Async version of query()."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.query, topic)

    async def abuild_context(self, query: str = "") -> PrefixResult:
        """Async version of build_context()."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.build_context, query)

    async def aadd_turn(self, role: str, content: str) -> None:
        """Async version of add_turn(). Safe to await when Observer makes LLM calls."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self.add_turn, role, content)

    async def aobserve(
        self,
        content: str,
        node_type: str = "CONCEPT",
        tags: list[str] | None = None,
    ) -> str:
        """Async version of observe()."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, lambda: self.observe(content, node_type, tags)
        )

    async def aflush(self) -> dict:
        """Async version of flush(). Awaitable — LLM extraction runs in thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.flush)

    # ------------------------------------------------------------------
    # Power-user access
    # ------------------------------------------------------------------

    def visualize(self, output_path: "Path | None" = None, open_browser: bool = True) -> "Path":
        """
        Open an interactive D3.js visualization of the current memory graph.

        Parameters
        ----------
        output_path : Path | None
            Where to save the HTML file. Defaults to a temp file.
        open_browser : bool
            Open the file in the default browser immediately (default True).

        Returns the path to the generated HTML file.
        """
        from .visualize import open_visualization
        return open_visualization(self._graph, output_path=output_path, open_browser=open_browser)

    def close(self) -> None:
        """Release resources held by this DoryMemory instance."""
        self._executor.shutdown(wait=False)

    def __enter__(self) -> "DoryMemory":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    @property
    def graph(self) -> Graph:
        """Direct access to the underlying Graph for advanced operations."""
        return self._graph
