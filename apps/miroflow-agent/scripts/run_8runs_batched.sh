#!/bin/bash

# 8 runs 分4批执行，每批2个并行，避免卡死
# 使用完整152题数据集

LLM_MODEL=${LLM_MODEL:-"openai/gpt-5-2025-08-07"}
BASE_URL=${BASE_URL:-"https://openrouter.ai/api/v1"}
LLM_PROVIDER=${LLM_PROVIDER:-"openai"}
AGENT_SET=${AGENT_SET:-"single_agent_keep5"}
MAX_CONTEXT_LENGTH=${MAX_CONTEXT_LENGTH:-65536}
MAX_CONCURRENT=${MAX_CONCURRENT:-5}
TEMPERATURE=${TEMPERATURE:-1.0}
API_KEY=${API_KEY:-"${OPENAI_API_KEY}"}

RESULTS_DIR="../../logs/futurex/$(date +%m%d)/${LLM_PROVIDER}_${LLM_MODEL}_${AGENT_SET}"
mkdir -p "$RESULTS_DIR"

echo "Results dir: $RESULTS_DIR"
echo "Running 8 runs in 4 batches (2 per batch)"
echo ""

run_one() {
    local i=$1
    echo "[Run $i] Starting..."
    uv run python benchmarks/common_benchmark.py \
        benchmark=futurex \
        benchmark.data.metadata_file="standardized_data_250924_250930.jsonl" \
        llm=gpt-5 \
        llm.provider=$LLM_PROVIDER \
        llm.model_name=$LLM_MODEL \
        llm.base_url=$BASE_URL \
        llm.async_client=true \
        llm.temperature=$TEMPERATURE \
        llm.max_context_length=$MAX_CONTEXT_LENGTH \
        llm.api_key=$API_KEY \
        benchmark.execution.max_tasks=null \
        benchmark.execution.max_concurrent=$MAX_CONCURRENT \
        benchmark.execution.pass_at_k=1 \
        benchmark.data.data_dir=../../data/futurex \
        agent=$AGENT_SET \
        hydra.run.dir=${RESULTS_DIR}/run_$i \
        2>&1 | tee "$RESULTS_DIR/run_${i}_output.log"
    echo "[Run $i] Done. Exit code: $?"
}

# Batch 1: run 1-2
echo "========== Batch 1/4 (run 1-2) =========="
run_one 1 &
sleep 5
run_one 2 &
wait
echo "Batch 1 done."
echo ""

# Batch 2: run 3-4
echo "========== Batch 2/4 (run 3-4) =========="
run_one 3 &
sleep 5
run_one 4 &
wait
echo "Batch 2 done."
echo ""

# Batch 3: run 5-6
echo "========== Batch 3/4 (run 5-6) =========="
run_one 5 &
sleep 5
run_one 6 &
wait
echo "Batch 3 done."
echo ""

# Batch 4: run 7-8
echo "========== Batch 4/4 (run 7-8) =========="
run_one 7 &
sleep 5
run_one 8 &
wait
echo "Batch 4 done."
echo ""

echo "=========================================="
echo "All 8 runs completed!"
echo "=========================================="

# 聚合结果
echo "Extracting predictions and formatting for FutureX submission..."
uv run python benchmarks/evaluators/extract_futurex_results.py "$RESULTS_DIR"

if [ $? -eq 0 ]; then
    echo "Submission file generated: $RESULTS_DIR/futurex_submission.jsonl"
else
    echo "Failed to generate submission file."
fi

echo "Results in: $RESULTS_DIR"
