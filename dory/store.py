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

DEFAULT_GRAPH_PATH = Path.home() / ".dory" / "dory.db"

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
    metadata TEXT DEFAULT '{}',
    distinct_sessions INTEGER DEFAULT 0
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

-- Append-only, hash-chained log of erasure operations.
-- Each receipt records WHAT was erased (as SHA-256 content hashes, never the
-- content itself) so erasure can be proven after the fact without retaining
-- the erased data. prev_hash links each receipt to its predecessor: editing or
-- removing any receipt breaks the chain and is detectable by verify_chain().
CREATE TABLE IF NOT EXISTS erasure_receipts (
    id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    query TEXT NOT NULL,
    query_hash TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL,
    node_ids TEXT DEFAULT '[]',
    content_hashes TEXT DEFAULT '[]',
    counts TEXT DEFAULT '{}',
    vacuumed INTEGER DEFAULT 0,
    prev_hash TEXT,
    receipt_hash TEXT NOT NULL
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply schema migrations for columns added after the initial release."""
    for col, defn in [
        ("zone", "TEXT DEFAULT 'active'"),
        ("superseded_at", "TEXT"),
        ("metadata", "TEXT DEFAULT '{}'"),
        ("distinct_sessions", "INTEGER DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE nodes ADD COLUMN {col} {defn}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    for col, defn in [("query_hash", "TEXT NOT NULL DEFAULT ''")]:
        try:
            conn.execute(f"ALTER TABLE erasure_receipts ADD COLUMN {col} {defn}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists, or table not created yet


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
        # Overwrite freed pages with zeros on delete. Without this SQLite merely
        # unlinks a row and the bytes stay recoverable in the file's free list —
        # which would make "erased" a claim we could not honestly make.
        conn.execute("PRAGMA secure_delete=ON")
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

    # Apply only explicit deletions tracked by the caller.
    # This avoids wiping rows written by another process or a stale Graph instance.
    deleted_node_ids = list(data.get("deleted_node_ids", []))
    deleted_edge_ids = list(data.get("deleted_edge_ids", []))
    if deleted_edge_ids:
        conn.execute(
            f"DELETE FROM edges WHERE id IN ({','.join('?'*len(deleted_edge_ids))})",
            deleted_edge_ids,
        )
    if deleted_node_ids:
        conn.execute(
            f"DELETE FROM nodes WHERE id IN ({','.join('?'*len(deleted_node_ids))})",
            deleted_node_ids,
        )

    for n in data.get("nodes", []):
        tags = n["tags"] if isinstance(n.get("tags"), list) else json.loads(n.get("tags") or "[]")
        metadata = n.get("metadata") or {}
        conn.execute(
            """
            INSERT INTO nodes
                (id, type, content, created_at, last_activated,
                 activation_count, salience, is_core, tags, zone, superseded_at, metadata,
                 distinct_sessions)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                metadata=excluded.metadata,
                distinct_sessions=excluded.distinct_sessions
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
                n.get("distinct_sessions", 0),
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

    # Rebuild FTS index from the full DB state, not just the caller's snapshot.
    # This keeps FTS correct even when multiple Graph instances save concurrently.
    conn.execute("DELETE FROM nodes_fts")
    rows = conn.execute("SELECT id, content, tags FROM nodes").fetchall()
    for row in rows:
        raw_tags = row["tags"] or "[]"
        tags_list = raw_tags if isinstance(raw_tags, list) else json.loads(raw_tags)
        conn.execute(
            "INSERT INTO nodes_fts (id, content, tags) VALUES (?,?,?)",
            (row["id"], row["content"], " ".join(tags_list)),
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
    from .sanitize import sanitize_observation

    sanitized = sanitize_observation(content)
    stored_content = sanitized.content
    if sanitized.flagged and "injection:" in sanitized.reason:
        stored_content = f"[FLAGGED_OBSERVATION {sanitized.reason}]"

    conn = _connect(path)
    conn.execute(
        "INSERT OR IGNORE INTO observations (id, session_id, role, content, created_at) VALUES (?,?,?,?,?)",
        (obs_id, session_id, role, stored_content, created_at or now_iso()),
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


# ---------------------------------------------------------------------------
# Erasure primitives
#
# These are the only functions that physically remove rows outside of
# store.save()'s tombstone path. They are deliberately dumb: erasure.py owns
# the policy (what to erase), store.py owns the mechanics (making it gone).
# ---------------------------------------------------------------------------


def get_observations_by_ids(
    obs_ids: list[str],
    path: Path = DEFAULT_GRAPH_PATH,
) -> list[dict]:
    """Fetch specific observations by id. Used to hash content before erasing it."""
    if not obs_ids:
        return []
    conn = _connect(path)
    rows = conn.execute(
        f"SELECT * FROM observations WHERE id IN ({','.join('?'*len(obs_ids))})",
        obs_ids,
    ).fetchall()
    return [dict(r) for r in rows]


def search_observations(
    terms: list[str],
    path: Path = DEFAULT_GRAPH_PATH,
) -> list[dict]:
    """
    Substring-AND search over raw observation content.

    Deliberately not FTS: erasure must catch partial words and punctuation that
    a tokenizer would drop. Missing a row here means failing to erase it.
    """
    if not terms:
        return []
    conn = _connect(path)
    rows = conn.execute("SELECT * FROM observations").fetchall()
    lowered = [t.lower() for t in terms]
    return [
        dict(r) for r in rows
        if all(t in (r["content"] or "").lower() for t in lowered)
    ]


def search_compressed_obs(
    terms: list[str],
    path: Path = DEFAULT_GRAPH_PATH,
) -> list[dict]:
    """Substring-AND search over compressed observation summaries."""
    if not terms:
        return []
    conn = _connect(path)
    rows = conn.execute("SELECT * FROM compressed_obs").fetchall()
    lowered = [t.lower() for t in terms]
    return [
        dict(r) for r in rows
        if all(t in (r["content"] or "").lower() for t in lowered)
    ]


def compressed_obs_referencing(
    obs_ids: list[str],
    path: Path = DEFAULT_GRAPH_PATH,
) -> list[dict]:
    """
    Find compressed_obs rows whose source_ids include any of these observation ids.

    A compressed summary is derived content: if we erase its sources but leave
    the summary, the erased text can still be present in paraphrase.
    """
    if not obs_ids:
        return []
    wanted = set(obs_ids)
    conn = _connect(path)
    rows = conn.execute("SELECT * FROM compressed_obs").fetchall()
    hits = []
    for r in rows:
        try:
            sources = json.loads(r["source_ids"] or "[]")
        except (json.JSONDecodeError, TypeError):
            sources = []
        if wanted & set(sources):
            hits.append(dict(r))
    return hits


def delete_observations(
    obs_ids: list[str],
    path: Path = DEFAULT_GRAPH_PATH,
) -> int:
    """Physically delete raw observations. Returns rows removed."""
    if not obs_ids:
        return 0
    conn = _connect(path)
    cur = conn.execute(
        f"DELETE FROM observations WHERE id IN ({','.join('?'*len(obs_ids))})",
        obs_ids,
    )
    conn.commit()
    return cur.rowcount


def delete_compressed_obs(
    obs_ids: list[str],
    path: Path = DEFAULT_GRAPH_PATH,
) -> int:
    """Physically delete compressed observation summaries. Returns rows removed."""
    if not obs_ids:
        return 0
    conn = _connect(path)
    cur = conn.execute(
        f"DELETE FROM compressed_obs WHERE id IN ({','.join('?'*len(obs_ids))})",
        obs_ids,
    )
    conn.commit()
    return cur.rowcount


def purge_fts_index(path: Path = DEFAULT_GRAPH_PATH) -> None:
    """
    Drop and rebuild the FTS index from scratch.

    store.save() clears nodes_fts with DELETE and reinserts, which is correct
    logically but leaves the deleted terms sitting in FTS5's shadow segment
    blobs (nodes_fts_data) until a merge happens to overwrite them. Erased
    content is therefore still recoverable from the index. Dropping the virtual
    table discards those segments outright.
    """
    conn = _connect(path)
    conn.execute("DROP TABLE IF EXISTS nodes_fts")
    conn.execute(
        "CREATE VIRTUAL TABLE nodes_fts USING fts5(id UNINDEXED, content, tags)"
    )
    rows = conn.execute("SELECT id, content, tags FROM nodes").fetchall()
    for row in rows:
        raw_tags = row["tags"] or "[]"
        tags_list = raw_tags if isinstance(raw_tags, list) else json.loads(raw_tags)
        conn.execute(
            "INSERT INTO nodes_fts (id, content, tags) VALUES (?,?,?)",
            (row["id"], row["content"], " ".join(tags_list)),
        )
    conn.commit()


def purge_free_pages(path: Path = DEFAULT_GRAPH_PATH) -> None:
    """
    Checkpoint the WAL and VACUUM so erased bytes leave the file.

    secure_delete zeroes freed pages in the main database, but in WAL mode the
    pre-delete image can still sit in the -wal file until a checkpoint, and the
    file never shrinks without a VACUUM. Both are required before erasure can
    honestly be called complete.
    """
    conn = _connect(path)
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    # VACUUM cannot run inside a transaction; isolation_level=None for this call.
    prior = conn.isolation_level
    try:
        conn.isolation_level = None
        conn.execute("VACUUM")
    finally:
        conn.isolation_level = prior
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.commit()


# ---------------------------------------------------------------------------
# Erasure receipts (append-only hash chain)
# ---------------------------------------------------------------------------


def append_receipt(receipt: dict, path: Path = DEFAULT_GRAPH_PATH) -> None:
    """Append one receipt. Callers must have computed seq/prev_hash/receipt_hash."""
    conn = _connect(path)
    conn.execute(
        """
        INSERT INTO erasure_receipts
            (id, seq, created_at, query, query_hash, mode, node_ids, content_hashes,
             counts, vacuumed, prev_hash, receipt_hash)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            receipt["id"], receipt["seq"], receipt["created_at"],
            receipt["query"], receipt["query_hash"], receipt["mode"],
            json.dumps(receipt["node_ids"]),
            json.dumps(receipt["content_hashes"]),
            json.dumps(receipt["counts"]),
            int(receipt["vacuumed"]),
            receipt["prev_hash"],
            receipt["receipt_hash"],
        ),
    )
    conn.commit()


def get_receipts(path: Path = DEFAULT_GRAPH_PATH, limit: int | None = None) -> list[dict]:
    """Return receipts in chain order (oldest first)."""
    conn = _connect(path)
    sql = "SELECT * FROM erasure_receipts ORDER BY seq ASC"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["node_ids"] = json.loads(d.get("node_ids") or "[]")
        d["content_hashes"] = json.loads(d.get("content_hashes") or "[]")
        d["counts"] = json.loads(d.get("counts") or "{}")
        d["vacuumed"] = bool(d.get("vacuumed"))
        d.setdefault("query_hash", "")
        out.append(d)
    return out


def last_receipt(path: Path = DEFAULT_GRAPH_PATH) -> dict | None:
    """Return the most recent receipt in the chain, or None if the chain is empty."""
    conn = _connect(path)
    row = conn.execute(
        "SELECT * FROM erasure_receipts ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["node_ids"] = json.loads(d.get("node_ids") or "[]")
    d["content_hashes"] = json.loads(d.get("content_hashes") or "[]")
    d["counts"] = json.loads(d.get("counts") or "{}")
    d["vacuumed"] = bool(d.get("vacuumed"))
    d.setdefault("query_hash", "")
    return d


def all_content_for_audit(path: Path = DEFAULT_GRAPH_PATH) -> list[str]:
    """
    Every piece of stored content that erasure is responsible for.

    verify_erasure() hashes each of these and checks none matches a hash
    recorded in a receipt. If one does, the erasure did not hold.
    """
    conn = _connect(path)
    out: list[str] = []
    for table, col in (
        ("nodes", "content"),
        ("observations", "content"),
        ("compressed_obs", "content"),
    ):
        for row in conn.execute(f"SELECT {col} FROM {table}").fetchall():
            if row[0]:
                out.append(row[0])
    return out
