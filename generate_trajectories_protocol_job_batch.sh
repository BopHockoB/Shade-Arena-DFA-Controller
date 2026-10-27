#!/bin/bash
#SBATCH -D /users/adjd119/projects/complex_sabotage
#SBATCH --job-name=traj_all
#SBATCH --partition=preemptgpu
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=20
#SBATCH --mem=80GB
#SBATCH --time=24:00:00
#SBATCH --gres=gpu:a100_80g:2
#SBATCH --array=0-2                     # one array job per task (see TASKS below)
#SBATCH --output=/mnt/data/users/adjd119/logs/generation_job_logs/%x_%A_%a.log
#SBATCH --error=/mnt/data/users/adjd119/logs/generation_job_logs/%x_%A_%a.log
#
# Usage:
#   sbatch generate_all_runs_job.sh gemma
#   sbatch generate_all_runs_job.sh qwen
#   sbatch --array=1 generate_all_runs_job.sh qwen          # only bank_transfer_2
#   RUNS="benign benign_dfa" sbatch generate_all_runs_job.sh gemma   # only some modes
#
# Each array job serves ONE model with vLLM and runs every mode below for ONE task.
# Afterwards run split_dfa_protocol_results.py (done automatically at the end if present).

VLLM_PID=""
cleanup() {
    if [[ -n "${VLLM_PID:-}" ]]; then
        echo "Stopping vLLM process group (PID $VLLM_PID)"
        kill -- -"$VLLM_PID" 2>/dev/null || kill "$VLLM_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT
set -euox pipefail

MODEL_KEY="${1:?usage: sbatch $0 gemma|qwen}"

# Load .env FIRST (for HF_TOKEN, proxy, etc.); every value hard-coded below wins over it.
if [[ -f .env ]]; then set -a; source .env; set +a; fi
set -a   # export everything below so task_completion.py / config.yaml see the same values

# ============================ HARD-CODED SETUP ============================

TASKS=(
    api_key_calendar_agendas_2
    bank_transfer_2
    jira_tickets
)

# Transcripts per run. >=5 per task/mode is the minimum for usable error bars.
NUM_EXPERIMENTS=10
MAX_CONCURRENT_THREADS=10

# mode name       | include_secondary_task | give_hint | dfa
# (all with REMOVE_THINKING_TAGS=False -> *_no_thinking_time dirs; benign has no such suffix)
declare -A MODE_SECONDARY=( [attack]=True  [attack_dfa]=True  [nohint]=True  [nohint_dfa]=True  [benign]=False [benign_dfa]=False )
declare -A MODE_HINT=(      [attack]=True  [attack_dfa]=True  [nohint]=False [nohint_dfa]=False [benign]=True  [benign_dfa]=True  )
declare -A MODE_DFA=(       [attack]=0     [attack_dfa]=1     [nohint]=0     [nohint_dfa]=1     [benign]=0     [benign_dfa]=1     )
# Order matters: highest-priority runs first, so a preempted/timed-out job still got the important ones.
DEFAULT_RUNS="attack attack_dfa benign benign_dfa nohint nohint_dfa"
RUNS="${RUNS:-$DEFAULT_RUNS}"

REMOVE_THINKING_TAGS=False
RUN_SOLUTION=False
TEST_MODE=False
RUN_ALL_TASKS=False
CONTROL_PROTOCOL=defer_to_trusted
ATTACKER_PROTOCOL=

case "$MODEL_KEY" in
    gemma)
        HF_MODEL=gemma-4-31B-it-FP8-block
        HF_MODEL_LOCAL=/mnt/data/users/adjd119/models/gemma-4-31B
        TOOL_CALL_PARSER=gemma4
        REASONING_PARSER=gemma4
        CONFIG_FILE=config_gemma_defer_to_trusted.yaml          # must point agent + monitor at gemma-4-31B-it-FP8-block
        ;;
    qwen)
        HF_MODEL=Qwen3.6-27B-FP8
        HF_MODEL_LOCAL=/mnt/data/users/adjd119/models/qwen3.6
        TOOL_CALL_PARSER=qwen3_coder
        REASONING_PARSER=qwen3
        CONFIG_FILE=config_qwen_defer_to_trusted.yaml          # must point agent + monitor at Qwen3.6-27B-FP8
        ;;
    *) echo "unknown model '$MODEL_KEY' (use gemma|qwen)"; exit 1 ;;
esac

# vLLM / hardware
VLLM_PORT=$((11444 + ${SLURM_ARRAY_TASK_ID:-0}))   # distinct port per array job in case two land on one node
VLLM_HOST=0.0.0.0
HF_HOME=/mnt/data/users/adjd119/models
GPU_MEMORY_UTILIZATION=0.92
TENSOR_PARALLEL_SIZE=2
PIPELINE_PARALLEL_SIZE=1
MAX_MODEL_LEN=128k
DTYPE=auto
KV_CACHE_DTYPE=auto
MAX_NUM_SEQS=256
MAX_NUM_BATCHED_TOKENS=4096

set +a
# ==========================================================================

TASK_ID="${SLURM_ARRAY_TASK_ID:-0}"
TASK="${TASKS[$TASK_ID]}"
echo "=== model=$HF_MODEL task=$TASK runs=[$RUNS] n=$NUM_EXPERIMENTS ==="

module purge
module add miniforge3/25.3.0-3/none-none/a-j26s7cx
module add cuda/13.1.1/none-none/a-imd4uac
module add apptainer/1.4.4/gcc-15.2.0/a-57buj5f


VLLM_LOG=/mnt/data/users/adjd119/logs/vllm_logs/vllm_${SLURM_JOB_NAME:-local}_${SLURM_JOB_ID:-0}_${TASK_ID}.log
echo "Starting vLLM ($HF_MODEL) -> $VLLM_LOG"

setsid apptainer exec \
    --nv \
    --bind "/mnt/data/users/adjd119:/mnt/data/users/adjd119" \
    --env HF_HOME="${HF_HOME}" \
    --env HF_TOKEN="${HF_TOKEN:-}" \
    --env no_proxy="localhost,127.0.0.1" \
    --env NO_PROXY="localhost,127.0.0.1" \
    vllm.sif \
    vllm serve \
        --model "$HF_MODEL_LOCAL" \
        --served_model_name "$HF_MODEL" \
        --host "$VLLM_HOST" \
        --port "$VLLM_PORT" \
        --tensor-parallel-size "$TENSOR_PARALLEL_SIZE" \
        --pipeline-parallel-size "$PIPELINE_PARALLEL_SIZE" \
        --dtype "$DTYPE" \
        --kv-cache-dtype "$KV_CACHE_DTYPE" \
        --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
        --max-model-len "$MAX_MODEL_LEN" \
        --max-num-seqs "$MAX_NUM_SEQS" \
        --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS" \
        --enable-auto-tool-choice \
        --tool-call-parser "$TOOL_CALL_PARSER" \
        --reasoning-parser "$REASONING_PARSER" \
        --default-chat-template-kwargs '{"enable_thinking": true}' \
    > "$VLLM_LOG" 2>&1 &
VLLM_PID=$!

export OPENAI_API_KEY="local"
export no_proxy="localhost,127.0.0.1"
export NO_PROXY="localhost,127.0.0.1"

echo "Waiting for vLLM (up to 20 min)..."
for i in $(seq 1 240); do
    if curl -sf "http://localhost:${VLLM_PORT}/v1/models" >/dev/null; then
        echo "vLLM ready after ~$((i * 5))s"; break
    fi
    if ! kill -0 "$VLLM_PID" 2>/dev/null; then
        echo "vLLM died during startup, see $VLLM_LOG"; tail -50 "$VLLM_LOG"; exit 1
    fi
    [[ $i -eq 240 ]] && { echo "vLLM failed to start within timeout"; exit 1; }
    sleep 5
done

mkdir -p test_results protocol_results

FAILED=()
for RUN in $RUNS; do
    [[ -n "${MODE_SECONDARY[$RUN]:-}" ]] || { echo "unknown run '$RUN', skipping"; continue; }

    DFA_ARGS=()
    if [[ "${MODE_DFA[$RUN]}" == 1 ]]; then
        DFA_DIR="task_pairs/$TASK/dfa"
        if [[ ! -d "$DFA_DIR" ]]; then
            echo "!! $DFA_DIR missing, skipping $RUN"; FAILED+=("$TASK:$RUN(no dfa dir)"); continue
        fi
        DFA_ARGS=(--dfa_protocol "$DFA_DIR")
    fi

    echo ""
    echo ">>> [$(date +%T)] $HF_MODEL | $TASK | $RUN (secondary=${MODE_SECONDARY[$RUN]} hint=${MODE_HINT[$RUN]} dfa=${MODE_DFA[$RUN]})"

    if ! conda run --no-capture-output -n vllm_env python -u task_completion.py \
        --num_experiments "$NUM_EXPERIMENTS" \
        --test_mode "$TEST_MODE" \
        --task_folder "$TASK" \
        --max_concurrent_threads "$MAX_CONCURRENT_THREADS" \
        --give_hint "${MODE_HINT[$RUN]}" \
        --remove_thinking_tags "$REMOVE_THINKING_TAGS" \
        --run_solution "$RUN_SOLUTION" \
        --run_all_tasks "$RUN_ALL_TASKS" \
        --include_secondary_task "${MODE_SECONDARY[$RUN]}" \
        "${DFA_ARGS[@]}" \
        ${CONTROL_PROTOCOL:+--control_protocol "$CONTROL_PROTOCOL"} \
        ${ATTACKER_PROTOCOL:+--attacker_protocol "$ATTACKER_PROTOCOL"} \
        ${CONFIG_FILE:+--config_file "$CONFIG_FILE"}
    then
        echo "!! run failed: $TASK $RUN (continuing)"
        FAILED+=("$TASK:$RUN")
    fi
done

# DFA runs write into the normal transcript dirs; move them to *_dfa dirs
if [[ -f split_dfa_protocol_transcripts.py ]]; then
    conda run --no-capture-output -n vllm_env python split_dfa_protocol_results.py protocol_results || true
fi

echo ""
echo "=== Done: $HF_MODEL / $TASK ==="
if (( ${#FAILED[@]} )); then
    echo "Failed runs: ${FAILED[*]}"; exit 1
fi