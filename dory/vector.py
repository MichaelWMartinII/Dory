from __future__ import annotations

"""
Vector index for Engram — sqlite-vec + Ollama local embeddings.

Falls back gracefully if Ollama isn't running or sqlite-vec isn't available.
Embedding model: nomic-embed-text (137M, 768-dim, runs fully offline after pull).
"""

import sqlite3
from pathlib import Path
from typing import Any

_SQLITE_VEC_OK = False
try:
    import sqlite_vec
    _SQLITE_VEC_OK = True
except ImportError:
    pass

_OLLAMA_OK = False
try:
    import ollama
    _OLLAMA_OK = True
except ImportError:
    pass

EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768
_VEC_TABLE = "node_embeddings"


def _connect(path: Path) -> sqlite3.Connection | None:
    """Return a vec-enabled connection, or None if sqlite-vec unavailable."""
    if not _SQLITE_VEC_OK:
        return None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (sqlite3.OperationalError, AttributeError):
        conn.close()
        return None
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {_VEC_TABLE} USING vec0(
            node_id TEXT PRIMARY KEY,
            embedding float[{EMBED_DIM}]
        )
        """
    )
    conn.commit()
    return conn


def embed(text: str) -> list[float] | None:
    """Generate an embedding via Ollama. Returns None if unavailable."""
    if not _OLLAMA_OK:
        return None
    try:
        resp = ollama.embeddings(model=EMBED_MODEL, prompt=text)
        return resp["embedding"]
    except Exception:
        return None


def index_node(node_id: str, content: str, path: Path) -> bool:
    """Embed a node and store in the vector index. Returns True on success."""
    conn = _connect(path)
    if conn is None:
        return False
    vec = embed(content)
    if vec is None:
        conn.close()
        return False
    conn.execute(
        f"INSERT OR REPLACE INTO {_VEC_TABLE} (node_id, embedding) VALUES (?, ?)",
        (node_id, sqlite_vec.serialize_float32(vec)),
    )
    conn.commit()
    conn.close()
    return True


def knn_search(query: str, path: Path, k: int = 10) -> list[str]:
    """KNN search over node embeddings. Returns node IDs ranked by similarity."""
    conn = _connect(path)
    if conn is None:
        return []
    vec = embed(query)
    if vec is None:
        conn.close()
        return []
    rows = conn.execute(
        f"""
        SELECT node_id, distance
        FROM {_VEC_TABLE}
        WHERE embedding MATCH ?
        ORDER BY distance
        LIMIT ?
        """,
        (sqlite_vec.serialize_float32(vec), k),
    ).fetchall()
    conn.close()
    return [r["node_id"] for r in rows]


def available() -> bool:
    """True if both sqlite-vec and Ollama are functional."""
    return _SQLITE_VEC_OK and _OLLAMA_OK
