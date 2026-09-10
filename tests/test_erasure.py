"""Tests for erasure.py — hard deletion with provable receipts."""
import sqlite3

import pytest

from dory import erasure, store
from dory.graph import Graph
from dory.schema import NodeType, EdgeType, ZONE_ARCHIVED, ZONE_EXPIRED, now_iso, new_id


# --- helpers ---

def _observe(db_path, content, session_id="s1", role="user", obs_id=None):
    oid = obs_id or new_id()
    store.write_observation(
        obs_id=oid, content=content, path=db_path,
        session_id=session_id, role=role, created_at=now_iso(),
    )
    return oid


@pytest.fixture
def seeded(graph, db_path):
    """A graph with nodes, edges, raw observations, and a compressed summary."""
    n1 = graph.add_node(NodeType.EVENT, "Trip to Chicago in June", tags=["travel"])
    n2 = graph.add_node(NodeType.CONCEPT, "FastAPI backend framework", tags=["tech"])
    n3 = graph.add_node(NodeType.PREFERENCE, "Prefers deep dish from Chicago")
    graph.add_edge(n1.id, n3.id, EdgeType.RELATED_TO, weight=0.7)
    graph.add_edge(n2.id, n3.id, EdgeType.RELATED_TO, weight=0.5)

    o1 = _observe(db_path, "We went to Chicago last June and it rained")
    o2 = _observe(db_path, "FastAPI is the backend of choice")
    n1.metadata["source_obs_ids"] = [o1]
    graph.save()

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO compressed_obs (id, session_id, content, created_at, source_ids) "
        "VALUES (?,?,?,?,?)",
        ("c1", "s1", "Summary: the Chicago trip went well", now_iso(), f'["{o1}"]'),
    )
    conn.commit()
    conn.close()

    return graph, n1, n2, n3, o1, o2


# --- hashing ---

def test_normalize_collapses_whitespace():
    assert erasure.normalize("  a   b\n c ") == "a b c"


def test_normalize_preserves_case():
    assert erasure.normalize("Chicago") == "Chicago"
    assert erasure.content_hash("Chicago") != erasure.content_hash("chicago")


def test_content_hash_stable_across_formatting():
    assert erasure.content_hash("hello  world") == erasure.content_hash("hello world")


# --- planning ---

def test_plan_touches_nothing(seeded, db_path):
    graph, n1, _, _, _, _ = seeded
    before = len(graph.all_nodes(zone=None))
    p = erasure.plan(graph, "chicago")
    assert not p.is_empty()
    assert len(graph.all_nodes(zone=None)) == before
    assert store.get_observations(db_path, limit=100)


def test_plan_matches_nodes_and_edges(seeded):
    graph, n1, n2, n3, _, _ = seeded
    p = erasure.plan(graph, "chicago")
    assert set(p.node_ids) == {n1.id, n3.id}
    assert n2.id not in p.node_ids
    # Both edges are incident to n3, so both go.
    assert len(p.edge_ids) == 2


def test_plan_finds_raw_observations(seeded):
    graph, _, _, _, o1, o2 = seeded
    p = erasure.plan(graph, "chicago")
    assert o1 in p.observation_ids
    assert o2 not in p.observation_ids


def test_plan_finds_compressed_obs(seeded):
    graph, _, _, _, _, _ = seeded
    p = erasure.plan(graph, "chicago")
    assert "c1" in p.compressed_ids


def test_plan_reaches_archived_and_expired_nodes(graph):
    a = graph.add_node(NodeType.EVENT, "archived chicago memory")
    e = graph.add_node(NodeType.EVENT, "expired chicago memory")
    a.zone = ZONE_ARCHIVED
    e.zone = ZONE_EXPIRED
    graph.save()

    p = erasure.plan(graph, "chicago")
    assert set(p.node_ids) == {a.id, e.id}


def test_plan_empty_query_matches_nothing(graph):
    graph.add_node(NodeType.CONCEPT, "something")
    graph.save()
    p = erasure.plan(graph, "")
    assert p.is_empty()


def test_plan_by_node_id(seeded):
    graph, n1, _, _, _, _ = seeded
    p = erasure.plan(graph, "", node_ids=[n1.id])
    assert p.node_ids == [n1.id]
    assert p.mode == "node_ids"


def test_cascade_pulls_in_derived_nodes(graph, db_path):
    o1 = _observe(db_path, "the secret phrase is bluebird")
    match = graph.add_node(NodeType.EVENT, "bluebird was mentioned")
    match.metadata["source_obs_ids"] = [o1]
    derived = graph.add_node(NodeType.CONCEPT, "a bird-related topic came up")
    derived.metadata["source_obs_ids"] = [o1]
    graph.save()

    without = erasure.plan(graph, "bluebird", cascade_derived=False)
    assert derived.id not in without.node_ids

    with_cascade = erasure.plan(graph, "bluebird", cascade_derived=True)
    assert derived.id in with_cascade.node_ids


# --- execution ---

def test_forget_removes_nodes_and_edges(seeded, db_path):
    graph, n1, n2, n3, _, _ = seeded
    erasure.forget(graph, "chicago")

    fresh = Graph(path=db_path)
    remaining = {n.id for n in fresh.all_nodes(zone=None)}
    assert n1.id not in remaining
    assert n3.id not in remaining
    assert n2.id in remaining
    assert fresh.all_edges() == []


def test_forget_removes_raw_observations(seeded, db_path):
    graph, _, _, _, o1, o2 = seeded
    erasure.forget(graph, "chicago")

    remaining = {o["id"] for o in store.get_observations(db_path, limit=100)}
    assert o1 not in remaining
    assert o2 in remaining


def test_forget_removes_compressed_obs(seeded, db_path):
    graph, _, _, _, _, _ = seeded
    erasure.forget(graph, "chicago")

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT id FROM compressed_obs").fetchall()
    conn.close()
    assert rows == []


def test_forget_clears_fts_index(seeded, db_path):
    graph, _, _, _, _, _ = seeded
    assert store.search_fts("chicago", db_path)
    erasure.forget(graph, "chicago")
    assert store.search_fts("chicago", db_path) == []


def test_forget_leaves_unrelated_content_alone(seeded, db_path):
    graph, _, n2, _, _, o2 = seeded
    erasure.forget(graph, "chicago")

    fresh = Graph(path=db_path)
    assert fresh.get_node(n2.id) is not None
    remaining = {o["id"] for o in store.get_observations(db_path, limit=100)}
    assert o2 in remaining


def test_forget_on_no_match_is_a_noop(seeded, db_path):
    graph, _, _, _, _, _ = seeded
    before = len(graph.all_nodes(zone=None))
    receipt = erasure.forget(graph, "nonexistentterm")
    assert receipt["counts"]["nodes"] == 0
    assert len(Graph(path=db_path).all_nodes(zone=None)) == before


# --- receipts ---

def test_receipt_records_counts(seeded):
    graph, _, _, _, _, _ = seeded
    receipt = erasure.forget(graph, "chicago")
    c = receipt["counts"]
    assert c["nodes"] == 2
    assert c["edges"] == 2
    assert c["observations"] == 1
    assert c["compressed_obs"] == 1


def test_receipt_stores_hashes_not_content(seeded, db_path):
    graph, n1, _, _, _, _ = seeded
    original = n1.content
    receipt = erasure.forget(graph, "chicago")

    assert erasure.content_hash(original) in receipt["content_hashes"]
    blob = " ".join(str(v) for v in receipt.values())
    assert "Chicago" not in blob

    raw = sqlite3.connect(str(db_path)).execute(
        "SELECT query, node_ids, content_hashes, counts FROM erasure_receipts"
    ).fetchall()
    assert "Chicago" not in str(raw)


def test_first_receipt_links_to_genesis(seeded):
    graph, _, _, _, _, _ = seeded
    receipt = erasure.forget(graph, "chicago")
    assert receipt["seq"] == 1
    assert receipt["prev_hash"] == erasure.GENESIS_HASH


def test_receipts_chain_together(seeded, db_path):
    graph, _, _, _, _, _ = seeded
    first = erasure.forget(graph, "chicago")
    second = erasure.forget(graph, "fastapi")

    assert second["seq"] == 2
    assert second["prev_hash"] == first["receipt_hash"]
    assert len(store.get_receipts(db_path)) == 2


# --- verification ---

def test_verify_passes_after_clean_erasure(seeded, db_path):
    graph, _, _, _, _, _ = seeded
    erasure.forget(graph, "chicago")

    result = erasure.verify(db_path)
    assert result["chain_valid"]
    assert result["erasure_holds"]
    assert result["resurrected"] == []


def test_verify_empty_chain_is_valid(db_path):
    Graph(path=db_path)
    result = erasure.verify(db_path)
    assert result["chain_valid"]
    assert result["erasure_holds"]
    assert result["receipts"] == 0


def test_verify_detects_edited_receipt(seeded, db_path):
    graph, _, _, _, _, _ = seeded
    erasure.forget(graph, "chicago")

    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE erasure_receipts SET query='something else'")
    conn.commit()
    conn.close()

    result = erasure.verify(db_path)
    assert not result["chain_valid"]
    assert any("modified after it was written" in p for p in result["chain_problems"])


def test_verify_detects_removed_receipt(seeded, db_path):
    graph, _, _, _, _, _ = seeded
    erasure.forget(graph, "chicago")
    erasure.forget(graph, "fastapi")

    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM erasure_receipts WHERE seq=1")
    conn.commit()
    conn.close()

    result = erasure.verify(db_path)
    assert not result["chain_valid"]


def test_verify_detects_resurrected_content(seeded, db_path):
    graph, n1, _, _, _, _ = seeded
    original = n1.content
    erasure.forget(graph, "chicago")

    fresh = Graph(path=db_path)
    fresh.add_node(NodeType.EVENT, original)
    fresh.save()

    result = erasure.verify(db_path)
    assert result["chain_valid"]
    assert not result["erasure_holds"]
    assert result["resurrected"][0]["hash"] == erasure.content_hash(original)


def test_verify_detects_resurrection_via_raw_observation(seeded, db_path):
    graph, _, _, _, o1, _ = seeded
    original = store.get_observations_by_ids([o1], db_path)[0]["content"]
    erasure.forget(graph, "chicago")

    _observe(db_path, original)
    result = erasure.verify(db_path)
    assert not result["erasure_holds"]


# --- secure delete / vacuum ---

def test_secure_delete_pragma_is_on(db_path):
    conn = store._connect(db_path)
    assert conn.execute("PRAGMA secure_delete").fetchone()[0] == 1


def _raw_bytes_on_disk(db_path):
    """Every byte of the database and its sidecar files, concatenated."""
    blob = b""
    for suffix in ("", "-wal", "-shm"):
        f = db_path.parent / (db_path.name + suffix)
        if f.exists():
            blob += f.read_bytes()
    return blob


def test_erased_bytes_are_gone_from_disk(graph, db_path):
    """
    The whole point: after erasure the plaintext must not be recoverable from
    the file. secure_delete zeroes freed pages, the checkpoint clears the WAL,
    and VACUUM rebuilds the file without the freed space.
    """
    secret = "xylophonemarmalade9317"
    graph.add_node(NodeType.EVENT, f"the passphrase is {secret}")
    _observe(db_path, f"user said the passphrase is {secret}")
    graph.save()

    assert secret.encode() in _raw_bytes_on_disk(db_path), "setup failed to write the secret"

    erasure.forget(graph, secret, vacuum=True)

    assert secret.encode() not in _raw_bytes_on_disk(db_path)


def test_without_vacuum_bytes_may_survive(graph, db_path):
    """
    Documents why vacuum defaults to on: skipping it is faster but leaves the
    erased content addressable in the file. Asserted loosely because whether a
    freed page is reused is up to SQLite.
    """
    secret = "quinceflugelhorn5521"
    graph.add_node(NodeType.EVENT, f"the passphrase is {secret}")
    graph.save()

    receipt = erasure.forget(graph, secret, vacuum=False)
    assert receipt["vacuumed"] is False
    # The row is gone from the logical database regardless.
    assert Graph(path=db_path).find_nodes(secret) == []


def test_no_vacuum_still_erases(seeded, db_path):
    graph, n1, _, _, _, _ = seeded
    receipt = erasure.forget(graph, "chicago", vacuum=False)
    assert receipt["vacuumed"] is False
    assert Graph(path=db_path).get_node(n1.id) is None


# --- leak regressions ---

def test_query_is_not_stored_in_receipt_by_default(graph, db_path):
    """
    The search term is usually the thing being erased. Writing it verbatim into
    a permanent append-only log would defeat the erasure it documents.
    """
    secret = "hunter2passphrase"
    graph.add_node(NodeType.EVENT, f"the passphrase is {secret}")
    graph.save()

    receipt = erasure.forget(graph, secret)
    assert receipt["query"] == ""
    assert receipt["query_hash"] == erasure.content_hash(secret)

    raw = sqlite3.connect(str(db_path)).execute(
        "SELECT * FROM erasure_receipts"
    ).fetchall()
    assert secret not in str(raw)


def test_retain_query_opt_in(graph, db_path):
    graph.add_node(NodeType.EVENT, "a trip to chicago")
    graph.save()
    receipt = erasure.forget(graph, "chicago", retain_query=True)
    assert receipt["query"] == "chicago"
    assert erasure.verify(db_path)["chain_valid"]


def test_erased_terms_leave_fts_shadow_tables(graph, db_path):
    """
    store.save() clears nodes_fts with DELETE, which leaves the terms in FTS5's
    shadow segment blobs. Erasure has to drop the index, not just empty it.
    """
    secret = "zzqqxxtermmarker"
    graph.add_node(NodeType.EVENT, f"contains {secret} inside")
    graph.save()

    conn = sqlite3.connect(str(db_path))
    fts_blob = str(conn.execute("SELECT * FROM nodes_fts_data").fetchall())
    conn.close()
    assert secret in fts_blob, "setup failed to index the secret"

    erasure.forget(graph, secret)

    conn = sqlite3.connect(str(db_path))
    fts_blob = str(conn.execute("SELECT * FROM nodes_fts_data").fetchall())
    conn.close()
    assert secret not in fts_blob


def test_fts_still_searchable_after_purge(seeded, db_path):
    """Rebuilding the index must not break search for surviving nodes."""
    graph, _, n2, _, _, _ = seeded
    erasure.forget(graph, "chicago")
    assert n2.id in store.search_fts("fastapi", db_path)


# --- end-to-end: extraction → provenance → erasure ---

def test_erasure_reaches_raw_turn_via_observer_provenance(graph, db_path):
    """
    The full path this feature exists for: a turn is logged, a node is extracted
    from it, and erasing the node also destroys the turn it came from — even
    though the turn's wording differs from the node's.
    """
    from unittest.mock import patch
    from dory.pipeline.observer import Observer

    with patch("dory.pipeline.observer._call_ollama") as mock_llm:
        mock_llm.return_value = {
            "nodes": [{
                "type": "EVENT",
                "content": "Michael visited Bratislava",
                "confidence": 0.95,
                "tags": [],
            }],
            "edges": [],
        }
        obs = Observer(graph, db_path=db_path, threshold=2, backend="ollama")
        obs.add_turn("user", "last spring I spent a week in Bratislava with my wife")
        obs.add_turn("assistant", "that sounds like a good trip")
        obs.flush()

    raw = store.get_observations(db_path, limit=100)
    assert any("Bratislava" in r["content"] for r in raw)

    erasure.forget(graph, "Bratislava")

    remaining = store.get_observations(db_path, limit=100)
    assert not any("Bratislava" in (r["content"] or "") for r in remaining), (
        "the raw turn survived erasure of the node extracted from it"
    )
    assert Graph(path=db_path).find_nodes("Bratislava") == []
    assert erasure.verify(db_path)["erasure_holds"]
