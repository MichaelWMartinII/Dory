#!/bin/bash
# Run LongMemEval benchmark against Dory.
#
# Usage:
#   ./run_benchmark.sh                                       # full 500q, Haiku
#   ./run_benchmark.sh --extract-model claude-sonnet-4-6    # Sonnet extraction
#   ./run_benchmark.sh --limit 50                           # spot check
#   ./run_benchmark.sh --resume                             # continue interrupted run
#
# Reads ANTHROPIC_API_KEY from .env if not already set.

set -euo pipefail

if [ -f .env ]; then
  source .env
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "Error: ANTHROPIC_API_KEY not set (add it to .env or export it)"
  exit 1
fi

OUTPUT="benchmarks/predictions_$(date +%Y%m%d_%H%M%S).jsonl"

python3 benchmarks/longmemeval.py \
  --data benchmarks/data/longmemeval/longmemeval_oracle.json \
  --output "$OUTPUT" \
  --backend anthropic \
  --extract-model claude-haiku-4-5-20251001 \
  --answer-model claude-haiku-4-5-20251001 \
  --api-key "$ANTHROPIC_API_KEY" \
  --verbose \
  "$@"

echo ""
echo "Predictions written to: $OUTPUT"
echo ""
echo "Evaluate with:"
echo "  source .env && ANTHROPIC_API_KEY=\$ANTHROPIC_API_KEY python3 benchmarks/evaluate_qa_claude.py \\"
echo "    $OUTPUT benchmarks/data/longmemeval/longmemeval_oracle.json"
