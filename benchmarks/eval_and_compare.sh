#!/usr/bin/env bash
# Evaluate spot_v4_v2 predictions and compare against v0.1 baseline.
# Usage: bash benchmarks/eval_and_compare.sh

set -e
cd "$(dirname "$0")/.."
set -a && source .env && set +a

VENV_PYTHON=".venv/bin/python"
EVAL_SCRIPT="benchmarks/evaluate_qa_claude.py"
COMPARE_SCRIPT="benchmarks/compare_runs.py"

PREDS_V2="benchmarks/predictions_spot_v4_v2.jsonl"
EVAL_V2="${PREDS_V2}.eval-results-claude-haiku-4-5-20251001"
EVAL_V1="benchmarks/predictions_spot_v4.jsonl.eval-results-claude-haiku-4-5-20251001"
QUESTIONS="benchmarks/spot_v4.json"

echo "=== Evaluating v0.2 predictions ==="
$VENV_PYTHON $EVAL_SCRIPT \
  "$PREDS_V2" \
  "$QUESTIONS" \
  --model claude-haiku-4-5-20251001 \
  --api-key "$ANTHROPIC_API_KEY"

echo ""
echo "=== v0.1 vs v0.2 comparison ==="
$VENV_PYTHON $COMPARE_SCRIPT \
  "$EVAL_V1" \
  "$EVAL_V2" \
  --questions "$QUESTIONS" \
  --labels v0.1 v0.2
