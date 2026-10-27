#!/usr/bin/env bash
# Guarded launcher for the direct 50-choice Finance router MLX LoRA training.
#
# Usage:
#   bash model_training/finance_candidate_router/train_direct_qwen25.sh smoke
#   bash model_training/finance_candidate_router/train_direct_qwen25.sh full
#
# Must be run from a normal macOS Terminal with a Metal device. The Codex/headless
# sandbox has no GPU and cannot run MLX forward/backward passes.
#
# The script refuses to reuse a non-empty adapter directory so that every run
# produces a fresh, reproducible checkpoint set.

set -euo pipefail

MODE="${1:-}"
if [[ "${MODE}" != "smoke" && "${MODE}" != "full" && "${MODE}" != "full_long" ]]; then
  echo "usage: $0 {smoke|full|full_long}" >&2
  exit 2
fi

# Resolve repo root from this script's location (…/model_training/finance_candidate_router/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Resolve Python and the model from the environment; no workstation paths are baked in.
#   ROUTER_PYTHON     - python interpreter (defaults to the python3 on PATH)
#   ROUTER_BASE_MODEL - local MLX model directory (required)
#   ROUTER_DATA_DIR   - dataset directory (defaults to the in-repo direct dataset)
PYTHON="${ROUTER_PYTHON:-$(command -v python3 || true)}"
MODEL="${ROUTER_BASE_MODEL:-}"
DATA_DIR="${ROUTER_DATA_DIR:-enterprise_root/tenants/company/training_data/finance_router_direct_candidate_v1}"

if [[ -z "${PYTHON}" ]]; then
  echo "error: no python3 found on PATH; set ROUTER_PYTHON to the interpreter." >&2
  exit 2
fi
if [[ -z "${MODEL}" ]]; then
  echo "error: set ROUTER_BASE_MODEL to the local MLX model directory." >&2
  exit 2
fi

if [[ "${MODE}" == "smoke" ]]; then
  ADAPTER_PATH="adapters/finance_direct_router_qwen25_1p5b_smoke_v1"
  ITERS=20
  GRAD_ACCUM=4
  STEPS_PER_REPORT=5
  STEPS_PER_EVAL=10
  SAVE_EVERY=10
  EARLY_STOP_PATIENCE=3
elif [[ "${MODE}" == "full" ]]; then
  ADAPTER_PATH="adapters/finance_direct_router_qwen25_1p5b_v1"
  # 414 training examples are not divisible by gradient-accumulation 8; MLX-LM
  # only applies an optimizer update on multiples of the accumulation count, so
  # 416 iters guarantees the final accumulated gradient group is applied.
  ITERS=416
  GRAD_ACCUM=8
  STEPS_PER_REPORT=26
  STEPS_PER_EVAL=104
  SAVE_EVERY=104
  EARLY_STOP_PATIENCE=2
else
  # Extended run: ~3 passes over the 414 training examples (1248 = 3 x 416),
  # kept a multiple of gradient-accumulation 8. The full run's best checkpoint
  # was its last iteration (validation loss still falling), so this searches for
  # where validation loss actually plateaus. Early stopping halts once it stops
  # improving, and checkpoint selection keeps the lowest-validation-loss weights,
  # so a longer ceiling cannot degrade the deployed adapter.
  ADAPTER_PATH="adapters/finance_direct_router_qwen25_1p5b_long_v1"
  ITERS=1248
  GRAD_ACCUM=8
  STEPS_PER_REPORT=52
  STEPS_PER_EVAL=104
  SAVE_EVERY=104
  EARLY_STOP_PATIENCE=2
fi

# Refuse to reuse a non-empty adapter directory.
if [[ -d "${ADAPTER_PATH}" ]] && [[ -n "$(ls -A "${ADAPTER_PATH}" 2>/dev/null)" ]]; then
  echo "error: adapter directory '${ADAPTER_PATH}' already exists and is not empty." >&2
  echo "       Move or rename it, or pick a new adapter path, before training." >&2
  exit 1
fi

mkdir -p artifacts
LOG="artifacts/$(basename "${ADAPTER_PATH}").log"

echo "mode=${MODE} adapter=${ADAPTER_PATH} iters=${ITERS} grad_accum=${GRAD_ACCUM}"
echo "log=${LOG}"

caffeinate -i "${PYTHON}" -u \
  -m model_training.finance_candidate_router.train_mlx train \
  --routing-mode direct \
  --model "${MODEL}" \
  --data-dir "${DATA_DIR}" \
  --adapter-path "${ADAPTER_PATH}" \
  --iters "${ITERS}" \
  --learning-rate 2e-5 \
  --num-layers 8 \
  --rank 16 \
  --scale 2.0 \
  --dropout 0.05 \
  --gradient-accumulation "${GRAD_ACCUM}" \
  --steps-per-report "${STEPS_PER_REPORT}" \
  --steps-per-eval "${STEPS_PER_EVAL}" \
  --save-every "${SAVE_EVERY}" \
  --early-stopping-patience "${EARLY_STOP_PATIENCE}" \
  --min-delta 1e-4 \
  --max-length 4096 \
  2>&1 | tee "${LOG}"
