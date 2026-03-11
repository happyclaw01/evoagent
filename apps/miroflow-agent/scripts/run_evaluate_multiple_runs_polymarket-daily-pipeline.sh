#!/bin/bash
set -o pipefail

# Polymarket Daily evaluation (pipeline-based, MCP tools enabled)
#
# Required env:
# - OPENAI_API_KEY (or set API_KEY and we'll map it to OPENAI_API_KEY)
#
# Optional env (similar to README style):
# - LLM_MODEL, BASE_URL, LLM_PROVIDER, AGENT_SET
# - MAX_CONTEXT_LENGTH, TEMPERATURE, MAX_TASKS
# - ORDERBOOK_TOP_N, PRICE_HISTORY_TAIL_N, MAX_EXTRA_CHARS

BENCHMARK_NAME="polymarket-daily"

LLM_MODEL=${LLM_MODEL:-"gpt-5-2025-08-07"}
BASE_URL=${BASE_URL:-"https://api.openai.com/v1"}
LLM_PROVIDER=${LLM_PROVIDER:-"openai"}
AGENT_SET=${AGENT_SET:-"single_agent_keep5"}

MAX_CONTEXT_LENGTH=${MAX_CONTEXT_LENGTH:-32768}
TEMPERATURE=${TEMPERATURE:-1.0}
MAX_TASKS=${MAX_TASKS:-null}

ORDERBOOK_TOP_N=${ORDERBOOK_TOP_N:-20}
PRICE_HISTORY_TAIL_N=${PRICE_HISTORY_TAIL_N:-120}
MAX_EXTRA_CHARS=${MAX_EXTRA_CHARS:-6000}

# Key mapping for README-style API_KEY
API_KEY=${API_KEY:-""}
if [ -n "$API_KEY" ] && [ -z "$OPENAI_API_KEY" ]; then
  export OPENAI_API_KEY="$API_KEY"
fi

if [ -z "$OPENAI_API_KEY" ]; then
  echo "ERROR: missing OPENAI_API_KEY. Set OPENAI_API_KEY (or API_KEY)."
  exit 1
fi

export PYTHONUNBUFFERED=1

RESULTS_DIR="../../logs/${BENCHMARK_NAME}/$(date +%m%d)/${LLM_PROVIDER}_${LLM_MODEL}_${AGENT_SET}"
mkdir -p "$RESULTS_DIR"

echo "Starting ${NUM_RUNS} runs..."
echo "Results dir: $RESULTS_DIR"

echo "Starting 1 run..."

echo "=========================================="
echo "Launching run 1/1"
echo "=========================================="

RUN_ID="run_1"
RUN_OUT_BASE="${RESULTS_DIR}/${RUN_ID}"
mkdir -p "$RUN_OUT_BASE"

CMD=(uv run python scripts/evaluate_polymarket_daily.py \
  --benchmark "$BENCHMARK_NAME" \
  --agent "$AGENT_SET" \
  --llm gpt-5 \
  --llm-provider "$LLM_PROVIDER" \
  --model-name "$LLM_MODEL" \
  --base-url "$BASE_URL" \
  --temperature "$TEMPERATURE" \
  --max-context-length "$MAX_CONTEXT_LENGTH" \
  --orderbook-top-n "$ORDERBOOK_TOP_N" \
  --price-history-tail-n "$PRICE_HISTORY_TAIL_N" \
  --max-extra-chars "$MAX_EXTRA_CHARS" \
  --out-dir "$RUN_OUT_BASE")

if [ "$MAX_TASKS" != "null" ] && [ -n "$MAX_TASKS" ]; then
  CMD+=(--max-tasks "$MAX_TASKS")
fi

echo "[run=1] $(date -Iseconds) starting..."
"${CMD[@]}" 2>&1 | tee "${RESULTS_DIR}/${RUN_ID}_output.log"
UV_EXIT_CODE=${PIPESTATUS[0]}

if [ $UV_EXIT_CODE -eq 0 ]; then
  echo "Run 1 completed successfully"
else
  echo "Run 1 failed! (exit_code=$UV_EXIT_CODE)"
fi

echo "Done. Check: $RESULTS_DIR"

