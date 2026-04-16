"""
Dory REST Server — HTTP API for browser extensions and non-MCP clients.

Runs on localhost:7341 by default. Wraps the same session.query/observe
functions used by the MCP server.

Start with: dory serve [--port 7341] [--db ~/.dory/engram.db]
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from importlib.metadata import version as _pkg_version

try:
    from fastapi import FastAPI, Query, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
except ImportError as e:
    raise ImportError(
        "REST server requires fastapi and uvicorn: pip install dory-memory[serve]"
    ) from e

from .graph import Graph
from .schema import NodeType
from .store import DEFAULT_GRAPH_PATH
from . import session

try:
    _version = _pkg_version("dory-memory")
except Exception:
    _version = "0.0.0"


def _db_path() -> Path:
    env = os.environ.get("DORY_DB_PATH")
    return Path(env) if env else DEFAULT_GRAPH_PATH


def _graph() -> Graph:
    return Graph(path=_db_path())


def create_app() -> FastAPI:
    app = FastAPI(title="Dory Memory API", version=_version)

    # Allow browser extension requests from any chrome-extension:// origin
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    class ObserveRequest(BaseModel):
        content: str
        node_type: str = "CONCEPT"

    class IngestRequest(BaseModel):
        user_turn: str
        assistant_turn: str = ""
        session_id: str = ""

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get("/health")
    def health():
        db = _db_path()
        return {"ok": True, "version": _version, "db": str(db)}

    @app.get("/query")
    def query(
        topic: str = Query(..., description="Natural language query topic"),
        reference_date: str = Query("", description="ISO date for duration hints"),
    ):
        graph = _graph()
        context = session.query(topic, graph, reference_date=reference_date)
        graph.save()
        node_count = len([n for n in graph.all_nodes() if n.zone == "active"])
        return {"context": context, "node_count": node_count}

    @app.post("/observe")
    def observe(req: ObserveRequest):
        try:
            ntype = NodeType(req.node_type.upper())
        except ValueError:
            valid = [t.value for t in NodeType]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid node_type '{req.node_type}'. Valid: {valid}",
            )
        graph = _graph()
        node_id = session.observe(req.content, ntype, graph)
        graph.save()
        return {"id": node_id, "node_type": ntype.value, "content": req.content}

    @app.post("/ingest")
    def ingest(req: IngestRequest):
        """
        Run Observer extraction on a conversation turn pair.
        Useful for browser extension auto-extraction after each AI response.
        """
        from .pipeline.observer import Observer

        graph = _graph()
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="ANTHROPIC_API_KEY not set — extraction unavailable",
            )

        obs = Observer(
            graph=graph,
            api_key=api_key,
            session_id=req.session_id or None,
            threshold=2,  # extract after both turns are buffered
        )
        if req.user_turn:
            obs.add_turn("user", req.user_turn)
        if req.assistant_turn:
            obs.add_turn("assistant", req.assistant_turn)

        result = obs.flush()
        graph.save()
        return {"nodes_extracted": result.get("nodes_written", 0)}

    @app.get("/stats")
    def stats():
        graph = _graph()
        s = graph.stats()
        core = sorted(
            [n for n in graph.all_nodes() if n.is_core],
            key=lambda n: -n.salience,
        )[:10]
        return {
            "nodes": s["nodes"],
            "edges": s["edges"],
            "core_nodes": s["core_nodes"],
            "top_core": [
                {"id": n.id, "type": n.type.value, "content": n.content, "salience": round(n.salience, 3)}
                for n in core
            ],
        }

    @app.get("/nodes")
    def nodes(
        type: Optional[str] = Query(None, description="Filter by node type (e.g. PREFERENCE)"),
        limit: int = Query(50, description="Max nodes to return"),
    ):
        graph = _graph()
        all_nodes = [n for n in graph.all_nodes() if n.zone == "active"]
        if type:
            all_nodes = [n for n in all_nodes if n.type.value == type.upper()]
        all_nodes.sort(key=lambda n: -n.salience)
        return {
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type.value,
                    "content": n.content,
                    "salience": round(n.salience, 3),
                    "is_core": n.is_core,
                    "created_at": n.created_at,
                }
                for n in all_nodes[:limit]
            ],
            "total": len(all_nodes),
        }

    return app
