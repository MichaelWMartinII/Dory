#!/usr/bin/env bash
set -euo pipefail

DORY_KEY=$(grep ANTHROPIC_API_KEY .env | cut -d= -f2 | tr -d '[:space:]')

python3 benchmarks/longmemeval.py \
  --data benchmarks/data/longmemeval/longmemeval_oracle.json \
  --output benchmarks/predictions_v07_full.jsonl \
  --backend anthropic \
  --api-key "$DORY_KEY" \
  --extract-model claude-haiku-4-5-20251001 \
  --answer-backend claude-code-mcp \
  --verbose \
  "$@"
