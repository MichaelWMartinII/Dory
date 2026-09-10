from __future__ import annotations

"""
Erasure — deletion you can prove after the fact.

Decay is not deletion. The Decayer moves nodes active → archived → expired,
which makes them invisible to retrieval, but every byte stays in the database.
That is the right default for a memory system and the wrong answer entirely
when someone asks you to forget something.

This module does the other thing. `forget()` physically removes matching
content from every surface that holds it:

  1. nodes          — the semantic memory itself
  2. edges          — every edge incident to an erased node
  3. nodes_fts      — the search index (rebuilt from nodes on save)
  4. observations   — the raw conversation turns the nodes were derived from
  5. compressed_obs — summaries derived from those turns

Surface 4 is the one that matters and the one that is easy to miss. Erasing a
node while leaving the raw turn that produced it means the text is still on
disk in plaintext, and any honest audit will find it.

Proving it
----------
Erasure that cannot be demonstrated later is just a claim. Every operation
writes a receipt recording SHA-256 hashes of the content it destroyed — never
the content itself. Two independent properties follow:

  * verify_chain()   — receipts are hash-chained, so removing or editing a past
                       receipt breaks every receipt after it and is detectable.
  * verify_erasure() — re-hash everything currently stored and confirm nothing
                       matches a hash in any receipt. This proves the erased
                       content is *still* absent, not merely that it was once
                       deleted.

Receipts do not record the search query by default. The query is very often the
exact thing being erased — a name, an address, a passphrase — and writing it into
a permanent append-only log would defeat the erasure it documents. Only a hash of
it is kept. Pass retain_query=True when the term is not itself sensitive.

Hash caveat: hashes are unsalted so a third party can verify them independently.
That makes short or highly-guessable content brute-forceable from a receipt. Do
not treat the receipt log itself as confidential-safe for low-entropy secrets.

Usage:
    from dory.erasure import plan, forget, verify

    p = plan(graph, "chicago")      # preview — touches nothing
    print(p.summary())

    receipt = forget(graph, "chicago")
    print(receipt["counts"])

    print(verify(graph.path))       # {"chain_valid": True, "erasure_holds": True, ...}
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import store
from .graph import Graph
from .schema import new_id, now_iso

# First link in the hash chain. Any chain whose first receipt does not point
# here has had its head removed.
GENESIS_HASH = "0" * 64


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def normalize(text: str) -> str:
    """
    Canonical form for hashing.

    Whitespace is collapsed so that reformatting alone does not defeat a match.
    Case is preserved: re-adding content with different capitalization is a new
    observation, not a failed erasure, and conflating the two would make
    verify_erasure() report false failures.
    """
    return " ".join((text or "").split())


def content_hash(text: str) -> str:
    """SHA-256 of the normalized content, hex-encoded."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_receipt_hash(payload: dict) -> str:
    """Hash of a receipt's canonical payload. Deterministic across processes."""
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


@dataclass
class ErasurePlan:
    """What forget() would remove. Produced by plan(); touches nothing."""

    query: str
    mode: str = "query"
    node_ids: list[str] = field(default_factory=list)
    node_contents: list[str] = field(default_factory=list)
    edge_ids: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    observation_contents: list[str] = field(default_factory=list)
    compressed_ids: list[str] = field(default_factory=list)
    compressed_contents: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.node_ids or self.observation_ids or self.compressed_ids)

    def counts(self) -> dict:
        return {
            "nodes": len(self.node_ids),
            "edges": len(self.edge_ids),
            "observations": len(self.observation_ids),
            "compressed_obs": len(self.compressed_ids),
        }

    def all_contents(self) -> list[str]:
        return self.node_contents + self.observation_contents + self.compressed_contents

    def summary(self) -> str:
        c = self.counts()
        lines = [
            f"Erasure plan for {self.query!r} (mode={self.mode})",
            f"  nodes:          {c['nodes']}",
            f"  edges:          {c['edges']}",
            f"  observations:   {c['observations']}",
            f"  compressed_obs: {c['compressed_obs']}",
        ]
        if self.node_contents:
            lines.append("\n  Nodes to erase:")
            for content in self.node_contents[:10]:
                snippet = normalize(content)[:100]
                lines.append(f"    - {snippet}")
            if len(self.node_contents) > 10:
                lines.append(f"    ... and {len(self.node_contents) - 10} more")
        if self.observation_contents:
            lines.append("\n  Raw observations to erase:")
            for content in self.observation_contents[:5]:
                snippet = normalize(content)[:100]
                lines.append(f"    - {snippet}")
            if len(self.observation_contents) > 5:
                lines.append(f"    ... and {len(self.observation_contents) - 5} more")
        return "\n".join(lines)


def _match_nodes(graph: Graph, terms: list[str]) -> list:
    """
    Substring-AND match across content and tags, over every zone.

    graph.find_nodes() defaults to the active zone. Erasure must reach archived
    and expired nodes too — those are exactly the ones a user assumes are gone.
    """
    hits = []
    for node in graph.all_nodes(zone=None):
        text = (node.content + " " + " ".join(node.tags)).lower()
        if all(t in text for t in terms):
            hits.append(node)
    return hits


def plan(
    graph: Graph,
    query: str,
    node_ids: list[str] | None = None,
    cascade_derived: bool = False,
) -> ErasurePlan:
    """
    Compute what would be erased, without erasing anything.

    query
        Substring-AND search terms. All terms must be present.
    node_ids
        Erase these exact node ids instead of searching. Sets mode="node_ids".
    cascade_derived
        Also erase nodes whose recorded provenance points at an erased
        observation, even when the node's own text does not match the query.
        Off by default: those nodes are abstractions that may legitimately no
        longer contain the erased content, and removing them silently deletes
        more than the user asked for.
    """
    terms = [t for t in (query or "").lower().split() if t]
    mode = "node_ids" if node_ids else "query"
    p = ErasurePlan(query=query, mode=mode)

    # --- nodes ---
    if node_ids:
        matched = [n for n in (graph.get_node(nid) for nid in node_ids) if n is not None]
    else:
        if not terms:
            return p  # refuse to match everything on an empty query
        matched = _match_nodes(graph, terms)

    for node in matched:
        p.node_ids.append(node.id)
        p.node_contents.append(node.content)

    # --- edges incident to erased nodes ---
    erased_nodes = set(p.node_ids)
    p.edge_ids = [
        e.id for e in graph.all_edges()
        if e.source_id in erased_nodes or e.target_id in erased_nodes
    ]

    # --- observations ---
    obs_by_id: dict[str, dict] = {}

    # Provenance: turns the matched nodes were extracted from.
    provenance_ids: list[str] = []
    for node in matched:
        provenance_ids.extend(node.metadata.get("source_obs_ids") or [])
    for row in store.get_observations_by_ids(sorted(set(provenance_ids)), graph.path):
        obs_by_id[row["id"]] = row

    # Direct content match: turns that mention the query regardless of whether
    # any node was ever extracted from them.
    if terms:
        for row in store.search_observations(terms, graph.path):
            obs_by_id[row["id"]] = row

    for row in obs_by_id.values():
        p.observation_ids.append(row["id"])
        p.observation_contents.append(row["content"] or "")

    # --- compressed observations ---
    comp_by_id: dict[str, dict] = {}
    if terms:
        for row in store.search_compressed_obs(terms, graph.path):
            comp_by_id[row["id"]] = row
    for row in store.compressed_obs_referencing(p.observation_ids, graph.path):
        comp_by_id[row["id"]] = row

    for row in comp_by_id.values():
        p.compressed_ids.append(row["id"])
        p.compressed_contents.append(row["content"] or "")

    # --- optional cascade to derived nodes ---
    if cascade_derived and p.observation_ids:
        erased_obs = set(p.observation_ids)
        for node in graph.all_nodes(zone=None):
            if node.id in erased_nodes:
                continue
            sources = set(node.metadata.get("source_obs_ids") or [])
            if sources & erased_obs:
                p.node_ids.append(node.id)
                p.node_contents.append(node.content)
                erased_nodes.add(node.id)
        # Recompute incident edges now that the node set has grown.
        p.edge_ids = [
            e.id for e in graph.all_edges()
            if e.source_id in erased_nodes or e.target_id in erased_nodes
        ]

    return p


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def execute(
    graph: Graph,
    p: ErasurePlan,
    vacuum: bool = True,
    retain_query: bool = False,
) -> dict:
    """
    Carry out an ErasurePlan and append a receipt. Returns the receipt.

    Content is hashed *before* deletion — afterwards it is unrecoverable, which
    is the point.

    retain_query
        Store the search terms in the receipt as plaintext. Off by default: the
        query is very often the exact thing being erased (a name, an address, a
        passphrase), and writing it into a permanent append-only log would
        defeat the erasure it is supposed to document. When off, the receipt
        keeps only a hash of the query, which is enough to correlate receipts
        without retaining the term.
    """
    hashes = sorted({content_hash(c) for c in p.all_contents() if normalize(c)})

    # Hash first, then destroy.
    edges_before = len(graph.all_edges())
    nodes_removed = sum(
        1 for node_id in p.node_ids
        if graph.remove_node(node_id, remove_incident_edges=True)
    )
    edges_removed = edges_before - len(graph.all_edges())
    if nodes_removed:
        # Applies the tombstones as real DELETEs against nodes and edges.
        graph.save()

    obs_removed = store.delete_observations(p.observation_ids, graph.path)
    comp_removed = store.delete_compressed_obs(p.compressed_ids, graph.path)

    # save() clears nodes_fts with DELETE, which leaves the erased terms sitting
    # in FTS5's shadow segment blobs. Drop and rebuild so the search index does
    # not outlive the data it indexed.
    if nodes_removed:
        store.purge_fts_index(graph.path)

    # Report what was actually removed, not what was planned.
    counts = {
        "nodes": nodes_removed,
        "edges": edges_removed,
        "observations": obs_removed,
        "compressed_obs": comp_removed,
    }

    receipt = _build_receipt(
        path=graph.path,
        query=p.query,
        mode=p.mode,
        node_ids=sorted(p.node_ids),
        content_hashes=hashes,
        counts=counts,
        vacuumed=vacuum,
        retain_query=retain_query,
    )
    # The receipt is written before the vacuum so its own pages are laid down in
    # the rebuilt file rather than appended to a WAL that the vacuum already
    # checkpointed past.
    store.append_receipt(receipt, graph.path)

    if vacuum:
        store.purge_free_pages(graph.path)

    return receipt


def _receipt_payload(r: dict) -> dict:
    """The exact fields covered by receipt_hash, in canonical form."""
    return {
        "seq": r["seq"],
        "created_at": r["created_at"],
        "query": r["query"],
        "query_hash": r["query_hash"],
        "mode": r["mode"],
        "node_ids": r["node_ids"],
        "content_hashes": r["content_hashes"],
        "counts": dict(sorted(r["counts"].items())),
        "vacuumed": bool(r["vacuumed"]),
        "prev_hash": r["prev_hash"],
    }


def _build_receipt(
    path: Path,
    query: str,
    mode: str,
    node_ids: list[str],
    content_hashes: list[str],
    counts: dict,
    vacuumed: bool,
    retain_query: bool = False,
) -> dict:
    previous = store.last_receipt(path)
    seq = (previous["seq"] + 1) if previous else 1
    prev_hash = previous["receipt_hash"] if previous else GENESIS_HASH

    receipt = {
        "seq": seq,
        "created_at": now_iso(),
        "query": query if retain_query else "",
        "query_hash": content_hash(query) if query else "",
        "mode": mode,
        "node_ids": node_ids,
        "content_hashes": content_hashes,
        "counts": dict(sorted(counts.items())),
        "vacuumed": bool(vacuumed),
        "prev_hash": prev_hash,
    }
    receipt["id"] = new_id()
    receipt["receipt_hash"] = compute_receipt_hash(_receipt_payload(receipt))
    return receipt


def forget(
    graph: Graph,
    query: str,
    node_ids: list[str] | None = None,
    cascade_derived: bool = False,
    vacuum: bool = True,
    retain_query: bool = False,
) -> dict:
    """Plan and execute in one call. Returns the receipt."""
    p = plan(graph, query, node_ids=node_ids, cascade_derived=cascade_derived)
    return execute(graph, p, vacuum=vacuum, retain_query=retain_query)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_chain(path: Path) -> dict:
    """
    Walk the receipt chain and confirm it has not been tampered with.

    Recomputes each receipt's hash from its own fields and checks that it links
    to its predecessor. Catches edited receipts, deleted receipts, and reordering.
    """
    receipts = store.get_receipts(path)
    problems: list[str] = []
    expected_prev = GENESIS_HASH
    expected_seq = 1

    for r in receipts:
        if r["seq"] != expected_seq:
            problems.append(
                f"receipt {r['id']}: seq {r['seq']}, expected {expected_seq} "
                f"(a receipt was removed or reordered)"
            )
        if r["prev_hash"] != expected_prev:
            problems.append(
                f"receipt {r['id']} (seq {r['seq']}): prev_hash does not match the "
                f"preceding receipt — the chain is broken here"
            )
        recomputed = compute_receipt_hash(_receipt_payload(r))
        if recomputed != r["receipt_hash"]:
            problems.append(
                f"receipt {r['id']} (seq {r['seq']}): contents do not match its "
                f"recorded hash — this receipt was modified after it was written"
            )
        expected_prev = r["receipt_hash"]
        expected_seq = r["seq"] + 1

    return {
        "receipts": len(receipts),
        "valid": not problems,
        "problems": problems,
    }


def verify_erasure(path: Path) -> dict:
    """
    Confirm every hash recorded in every receipt is absent from live storage.

    This is the property that actually matters to an auditor: not "we ran a
    delete once" but "the content is not here now".
    """
    receipts = store.get_receipts(path)
    erased: dict[str, str] = {}
    for r in receipts:
        for h in r["content_hashes"]:
            erased.setdefault(h, r["id"])

    resurrected: list[dict] = []
    if erased:
        for content in store.all_content_for_audit(path):
            h = content_hash(content)
            if h in erased:
                resurrected.append({
                    "hash": h,
                    "receipt_id": erased[h],
                    "snippet": normalize(content)[:120],
                })

    return {
        "hashes_tracked": len(erased),
        "holds": not resurrected,
        "resurrected": resurrected,
    }


def verify(path: Path) -> dict:
    """Run both checks. A fully clean result is chain_valid and erasure_holds."""
    chain = verify_chain(path)
    erasure = verify_erasure(path)
    return {
        "chain_valid": chain["valid"],
        "chain_problems": chain["problems"],
        "receipts": chain["receipts"],
        "erasure_holds": erasure["holds"],
        "hashes_tracked": erasure["hashes_tracked"],
        "resurrected": erasure["resurrected"],
    }
