#!/bin/bash
#SBATCH --job-name=results_review
#SBATCH --partition=normal
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=/mnt/data/users/adjd119/logs/review_job_logs/%x_%j.log
#SBATCH --error=/mnt/data/users/adjd119/logs/review_job_logs/%x_%j.log  


set -euox pipefail

module purge
module add miniforge3/25.3.0-3/none-none/a-j26s7cx 

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate vllm_env


mkdir -p logs results/plotting_notebooks/monitor
mkdir -p logs results/plotting_notebooks/agent
mkdir -p logs results/plotting_notebooks/protocol

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

papermill plotting_notebooks/agent_performance_v2_fixed.ipynb \
    results/plotting_notebooks/agent/agent_performance_v2_${TIMESTAMP}.ipynb \
    --log-output

papermill plotting_notebooks/monitor_performance_fixed.ipynb \
    results/plotting_notebooks/monitor/monitor_performance_v2_${TIMESTAMP}.ipynb \
    --log-output

papermill plotting_notebooks_protocols/protocol_analysis.ipynb \
  results/plotting_notebooks/protocol/protocol_analysis_${TIMESTAMP}.ipynb \
  --log-output