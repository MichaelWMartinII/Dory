#!/bin/bash
source .venv/bin/activate
nohup python benchmarks/longmemeval.py --data benchmarks/data/longmemeval/longmemeval_oracle.json --output benchmarks/predictions_sonnet.jsonl --extract-model claude-sonnet-4-6 --answer-model claude-sonnet-4-6 --backend anthropic --api-key $ANTHROPIC_API_KEY --resume > benchmarks/run_sonnet.log 2>&1 &
echo "Started PID $!"
tail -f benchmarks/run_sonnet.log
