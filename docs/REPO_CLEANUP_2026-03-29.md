# Repo Cleanup Notes

Date: 2026-03-29

This document records the stale-file cleanup performed in this session, why each
change was made, and how to revert it.

## Goals

The cleanup was intentionally conservative:

- do not touch active benchmark inputs or currently open working files
- archive old material rather than deleting it where history may still matter
- remove only files that were clearly stale or broken as checked in

## Changes

### 1. Removed stale benchmark helper

Removed:

- `benchmarks/eval_and_compare.sh`

Why:

- It referenced missing files like `benchmarks/predictions_spot_v4_v2.jsonl`
  and `benchmarks/spot_v4.json`.
- It was no longer runnable as checked in.

How to revert:

1. Restore `benchmarks/eval_and_compare.sh` from git history.
2. If you want it to be usable again, update it to point at files that still
   exist in `benchmarks/`.

### 2. Archived legacy live demo

Moved:

- `examples/live_chat.py` → `examples/archive/live_chat_legacy.py`

Why:

- It depended on local-only infrastructure, a sibling `Agent` checkout, and
  hardcoded server assumptions.
- It was not part of the documented example surface.

How to revert:

1. Move `examples/archive/live_chat_legacy.py` back to `examples/live_chat.py`.
2. If you want to expose it as a supported example again, remove the local-only
   assumptions and document the setup in `README.md`.

### 3. Archived historical user-test reports

Moved:

- `tests/user_tests/README.md` → `docs/archive/user-tests/README.md`
- `tests/user_tests/report_mcp_new_user_2026-03-21.md`
  → `docs/archive/user-tests/report_mcp_new_user_2026-03-21.md`
- `tests/user_tests/report_pypi_new_user_2026-03-21.md`
  → `docs/archive/user-tests/report_pypi_new_user_2026-03-21.md`

Why:

- These were not executable tests.
- They are historical validation reports for older `0.3.x` onboarding flows.
- Keeping them under `tests/` made the repo structure look less intentional.

How to revert:

1. Move the files from `docs/archive/user-tests/` back into `tests/user_tests/`.
2. If you want them to remain under `tests/`, make it explicit that they are
   reports, not automated tests.

### 4. Added benchmark directory guide

Added:

- `benchmarks/README.md`

Why:

- The benchmark directory contains canonical tooling, active reports, and many
  archival artifacts. The new README clarifies what is current versus archival.

How to revert:

1. Delete `benchmarks/README.md` if you do not want directory-level guidance.

## Not changed on purpose

These were left alone because they are active, currently open, or still plausibly
useful working materials:

- `benchmarks/predictions_v05_claudecode_mcp_full.jsonl`
- `benchmarks/predictions_v06_claudecode_mcp_full.jsonl`
- `benchmarks/REPORT_v05.md`
- `benchmarks/CHANGES_v05_session.md`

## Notes

This cleanup did not change package code or benchmark logic. It only adjusted
repo structure and stale-file placement.
