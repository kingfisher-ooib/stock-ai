#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -x .venv/bin/python ]]; then
  echo "Missing .venv; run .uv-bootstrap/bin/uv sync --extra dev" >&2
  exit 1
fi
MODEL="$(.venv/bin/python -c 'from stock_ai.config import Settings; print(Settings().mlx_model)')"
if [[ -z "$MODEL" ]]; then
  echo "MLX_MODEL is empty" >&2
  exit 1
fi
echo "MLX model: $MODEL"
echo "Approximate first download: 17.2 GB for the default Qwen 4-bit checkpoint (other models vary)."
echo "Cache: ${HF_HOME:-$HOME/.cache/huggingface}"
echo "Binding: 127.0.0.1:8080 only"
exec .venv/bin/mlx_lm.server --model "$MODEL" --host 127.0.0.1 --port 8080
