# Benchmarks

This directory contains three different kinds of material:

1. Canonical benchmark tooling
2. Working benchmark reports and spot-check datasets
3. Historical prediction artifacts from prior runs

## Canonical entry points

These are the current benchmark entry points:

- `benchmarks/longmemeval.py`
- `benchmarks/evaluate_qa_claude.py`
- `benchmarks/compare_runs.py`

`benchmarks/eval_and_compare.sh` was removed on 2026-03-29 because it referenced
missing `v0.2` files and was no longer runnable as checked in.

## Historical material

Items under `benchmarks/archive/` are preserved for comparison and audit trails.
They are not part of the active package or runtime surface.

The checked-in `predictions_*.jsonl` and `*.eval-results-*` files in this
directory are experiment outputs. They are useful internally, but they are not
required to use `dory-memory`.
