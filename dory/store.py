from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

# Per-thread connection cache — SQLite connections are not thread-safe to share
# across threads without check_same_thread=False, but creating a new connection
# per call has measurable overhead for high-frequency use.
# Each thread gets its own connection per db path, kept open for the thread's lifetime.
_thread_local = threading.local()

DEFAULT_GRAPH_PATH = Path.home() / ".dory" / "engram.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_activated TEXT NOT NULL,
    activation_count INTEGER DEFAULT 0,
    salience REAL DEFAULT 0.0,
    is_core INTEGER DEFAULT 0,
    tags TEXT DEFAULT '[]',
    zone TEXT DEFAULT 'active',
    superseded_at TEXT,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    type TEXT NOT NULL,
    weight REAL NOT NULL,
    created_at TEXT NOT NULL,
    last_activated TEXT NOT NULL,
    activation_count INTEGER DEFAULT 0,
    decay_rate REAL DEFAULT 0.02
);

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    id UNINDEXED,
    content,
    tags
);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    role TEXT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    compressed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS compressed_obs (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    referenced_at TEXT,
    source_ids TEXT DEFAULT '[]'
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply schema migrations for columns added after the initial release."""
    for col, defn in [
        ("zone", "TEXT DEFAULT 'active'"),
        ("superseded_at", "TEXT"),
        ("metadata", "TEXT DEFAULT '{}'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE nodes ADD COLUMN {col} {defn}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists


def _connect(path: Path) -> sqlite3.Connection:
    """
    Return a SQLite connection for this thread and db path.

    Connections are cached per-thread per-path — creating a new connection on
    every call has overhead that accumulates for high-frequency workloads.
    WAL mode is enabled so readers don't block writers.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    cache: dict[str, sqlite3.Connection] = getattr(_thread_local, "connections", None)
    if cache is None:
        _thread_local.connections = {}
        cache = _thread_local.connections

    key = str(path.resolve())
    if key not in cache:
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        _migrate(conn)
        cache[key] = conn

    return cache[key]


def close_connection(path: Path) -> None:
    """Explicitly close and remove the cached connection for this thread/path."""
    cache: dict | None = getattr(_thread_local, "connections", None)
    if cache is None:
        return
    key = str(path.resolve())
    conn = cache.pop(key, None)
    if conn:
        try:
            conn.close()
        except Exception:
            pass


def load(path: Path = DEFAULT_GRAPH_PATH) -> dict:
    conn = _connect(path)
    nodes = [dict(r) for r in conn.execute("SELECT * FROM nodes").fetchall()]
    edges = [dict(r) for r in conn.execute("SELECT * FROM edges").fetchall()]
    for n in nodes:
        n["tags"] = json.loads(n.get("tags") or "[]")
        n["is_core"] = bool(n["is_core"])
        n["metadata"] = json.loads(n.get("metadata") or "{}")
    return {"nodes": nodes, "edges": edges}


def save(data: dict, path: Path = DEFAULT_GRAPH_PATH) -> None:
    conn = _connect(path)

    # Remove nodes and edges that are no longer in the in-memory graph
    node_ids = [n["id"] for n in data.get("nodes", [])]
    edge_ids = [e["id"] for e in data.get("edges", [])]
    if node_ids:
        conn.execute(
            f"DELETE FROM nodes WHERE id NOT IN ({','.join('?'*len(node_ids))})", node_ids
        )
    else:
        conn.execute("DELETE FROM nodes")
    if edge_ids:
        conn.execute(
            f"DELETE FROM edges WHERE id NOT IN ({','.join('?'*len(edge_ids))})", edge_ids
        )
    else:
        conn.execute("DELETE FROM edges")

    for n in data.get("nodes", []):
        tags = n["tags"] if isinstance(n.get("tags"), list) else json.loads(n.get("tags") or "[]")
        metadata = n.get("metadata") or {}
        conn.execute(
            """
            INSERT INTO nodes
                (id, type, content, created_at, last_activated,
                 activation_count, salience, is_core, tags, zone, superseded_at, metadata)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type,
                content=excluded.content,
                last_activated=excluded.last_activated,
                activation_count=excluded.activation_count,
                salience=excluded.salience,
                is_core=excluded.is_core,
                tags=excluded.tags,
                zone=excluded.zone,
                superseded_at=excluded.superseded_at,
                metadata=excluded.metadata
            """,
            (
                n["id"], n["type"], n["content"],
                n["created_at"], n["last_activated"],
                n["activation_count"], n["salience"],
                int(n["is_core"]),
                json.dumps(tags),
                n.get("zone", "active"),
                n.get("superseded_at"),
                json.dumps(metadata),
            ),
        )

    for e in data.get("edges", []):
        conn.execute(
            """
            INSERT INTO edges
                (id, source_id, target_id, type, weight,
                 created_at, last_activated, activation_count, decay_rate)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                weight=excluded.weight,
                last_activated=excluded.last_activated,
                activation_count=excluded.activation_count
            """,
            (
                e["id"], e["source_id"], e["target_id"],
                e["type"], e["weight"],
                e["created_at"], e["last_activated"],
                e["activation_count"], e["decay_rate"],
            ),
        )

    # Rebuild FTS index
    conn.execute("DELETE FROM nodes_fts")
    for n in data.get("nodes", []):
        raw_tags = n.get("tags") or []
        tags_list = raw_tags if isinstance(raw_tags, list) else json.loads(raw_tags)
        conn.execute(
            "INSERT INTO nodes_fts (id, content, tags) VALUES (?,?,?)",
            (n["id"], n["content"], " ".join(tags_list)),
        )

    conn.commit()


def search_fts(query: str, path: Path = DEFAULT_GRAPH_PATH, limit: int = 20) -> list[str]:
    """BM25 full-text search. Returns node IDs ranked by relevance."""
    import re
    # Strip FTS5 operators/special chars that cause OperationalError
    safe_query = re.sub(r'["\(\)\*\:\^]', " ", query).strip()
    if not safe_query:
        return []
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT id FROM nodes_fts WHERE nodes_fts MATCH ? ORDER BY rank LIMIT ?",
            (safe_query, limit),
        ).fetchall()
        return [r["id"] for r in rows]
    except sqlite3.OperationalError:
        # Last-resort fallback: strip to plain words only
        plain = " OR ".join(re.findall(r"[a-zA-Z]\w{2,}", safe_query)[:8])
        if not plain:
            return []
        try:
            rows = conn.execute(
                "SELECT id FROM nodes_fts WHERE nodes_fts MATCH ? ORDER BY rank LIMIT ?",
                (plain, limit),
            ).fetchall()
            return [r["id"] for r in rows]
        except sqlite3.OperationalError:
            return []
    except Exception:
        return []


def write_observation(
    obs_id: str,
    content: str,
    path: Path = DEFAULT_GRAPH_PATH,
    session_id: str | None = None,
    role: str | None = None,
    created_at: str | None = None,
) -> None:
    """Append a raw turn to the episodic observation log."""
    from .schema import now_iso
    conn = _connect(path)
    conn.execute(
        "INSERT OR IGNORE INTO observations (id, session_id, role, content, created_at) VALUES (?,?,?,?,?)",
        (obs_id, session_id, role, content, created_at or now_iso()),
    )
    conn.commit()


def get_observations(
    path: Path = DEFAULT_GRAPH_PATH,
    session_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Retrieve raw observations, optionally filtered by session."""
    conn = _connect(path)
    if session_id:
        rows = conn.execute(
            "SELECT * FROM observations WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM observations ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
