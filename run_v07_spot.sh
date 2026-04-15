#!/usr/bin/env bash
set -euo pipefail

DORY_KEY=$(grep ANTHROPIC_API_KEY .env | cut -d= -f2 | tr -d '[:space:]')

python3 benchmarks/longmemeval.py \
  --data benchmarks/data/longmemeval/longmemeval_oracle.json \
  --output benchmarks/predictions_v07_stratified50.jsonl \
  --backend anthropic \
  --api-key "$DORY_KEY" \
  --extract-model claude-haiku-4-5-20251001 \
  --answer-backend claude-code-mcp \
  --stratify "temporal-reasoning:10,multi-session:10,knowledge-update:10,single-session-user:10,single-session-assistant:5,single-session-preference:5" \
  --verbose \
  "$@"
