# Dory Hardening Notes

Date: 2026-03-29

This document records the security and reliability hardening changes applied in
this session, why they were made, what tradeoffs they introduce, and exactly
how to revert them.

## Scope

The goal of this pass was targeted hardening with minimal behavior change:

1. Stop stale `Graph` saves from deleting rows written by other processes.
2. Stop obvious prompt-injection text from raw observations being reinjected
   into future prompts.
3. Remove one insecure temp-file pattern from a tracked example.

These are not broad architectural rewrites. They are bounded changes intended
to reduce the most immediate integrity and trust-boundary risks.

## 1. Persistence Hardening

### What changed

Files:

- `dory/graph.py`
- `dory/store.py`
- `dory/consolidation.py`
- `dory/pipeline/reflector.py`

Behavior before:

- `Graph.save()` wrote the full in-memory snapshot.
- `store.save()` deleted every node and edge not present in that snapshot.
- A stale `Graph` instance could erase rows written by another process.

Behavior now:

- `Graph` tracks explicit tombstones in `_deleted_node_ids` and
  `_deleted_edge_ids`.
- `store.save()` only deletes rows listed in those tombstones.
- Upserts remain unchanged.
- The FTS index is rebuilt from the current database contents rather than from
  the caller snapshot.
- Call sites that truly remove graph elements now use `graph.remove_node()` and
  `graph.remove_edge()`.

### Why

The previous model was unsafe for any multi-writer or stale-reader scenario,
including:

- MCP server use
- multi-agent shared memory
- async extraction and background writes
- multiple `Graph` instances pointed at the same DB

### Tradeoffs

- Slightly more implementation complexity.
- Deletion is now explicit rather than implicit.
- The FTS rebuild now reads from the DB, which is safer under concurrent saves.

### How to revert

If you want the previous full-snapshot behavior back:

1. In `dory/store.py`, restore the `DELETE ... WHERE id NOT IN (...)` logic in
   `save()`.
2. In `dory/graph.py`, remove `_deleted_node_ids`, `_deleted_edge_ids`,
   `remove_node()`, and `remove_edge()`.
3. In `dory/graph.py`, stop passing `deleted_node_ids` and `deleted_edge_ids`
   into `store.save()`.
4. In `dory/consolidation.py` and `dory/pipeline/reflector.py`, revert the
   removal call sites to direct `del graph._edges[...]` / `del graph._nodes[...]`.

Reverting this will restore the simpler implementation but reintroduce stale
writer data-loss risk.

## 2. Raw Observation Sanitization

### What changed

Files:

- `dory/store.py`

Behavior before:

- `Observer.add_turn()` logged raw conversation text exactly as received.
- Prefixer and adapter history paths could later re-inject that text into model
  prompts.
- `sanitize_observation()` existed but was not enforced at write time.

Behavior now:

- `store.write_observation()` always runs `sanitize_observation()`.
- Truncation still preserves the truncated content.
- If injection-style patterns are detected, the stored observation is replaced
  with a redacted marker:

  `[FLAGGED_OBSERVATION ...]`

### Why

This reduces the chance that obviously malicious or adversarial text gets
stored in the episodic log and then reintroduced verbatim into future prompts.

### Tradeoffs

- Some raw conversational fidelity is lost for flagged observations.
- A malicious message that trips the detector is no longer available verbatim in
  the observation log.
- This is intentionally conservative only for injection-pattern hits, not for
  normal text.

### How to revert

If you want to preserve raw observations exactly as entered:

1. In `dory/store.py`, remove the `sanitize_observation()` call from
   `write_observation()`.
2. Restore the original `content` write path so the DB stores raw text without
   redaction.

Reverting this will restore full raw-history fidelity but reintroduce the risk
of replaying prompt-injection text through observation-based context paths.

## 3. Example Temp-File Fix

### What changed

File:

- `examples/demo_topology.py`

Behavior before:

- Used `tempfile.mktemp()`.

Behavior now:

- Uses `tempfile.mkstemp()`, closes the file descriptor, and reuses the path.

### Why

`mktemp()` is an insecure temp-file pattern and should not appear in tracked
examples for a repo that claims to be security-conscious.

### Tradeoffs

- None for normal use.

### How to revert

If you want the old shorter example back:

1. In `examples/demo_topology.py`, replace the `mkstemp()` block with the prior
   single `tempfile.mktemp()` line.

This is not recommended.

## Tests Added / Updated

File:

- `tests/test_store.py`

Added checks for:

- preserving unrelated rows across independent saves
- explicit deletion behavior
- prompt-injection redaction in observations

## Notes

This hardening pass did not change:

- retrieval heuristics
- prompt templates
- benchmark logic
- visualization network dependencies

Those are separate decisions and can be handled independently.
