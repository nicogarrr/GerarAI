#!/usr/bin/env bash
# Crossover RAGAS en un venv aislado, en un solo comando (desde data-engine/):
#
#     bash scripts/ragas_crossover.sh            # stub determinista, sin red ni Qdrant
#     bash scripts/ragas_crossover.sh --real     # recuperador real (exige Qdrant y el venv del servicio)
#
# Ver evals/rag/requirements-ragas.txt para el porque de cada pin.
set -euo pipefail
cd "$(dirname "$0")/.."
VENV="${RAGAS_VENV:-.venv-ragas}"
REQ="evals/rag/requirements-ragas.txt"
PY="${RAGAS_PYTHON:-python3.12}"

if [ ! -x "$VENV/bin/python" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv -q -p 3.12 "$VENV"
  else
    "$PY" -m venv "$VENV"
  fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install -q -p "$VENV/bin/python" -r "$REQ"
else
  "$VENV/bin/python" -m pip install -q -r "$REQ"
fi

# ragas manda telemetria por defecto; el runner bloquea la red (solo loopback).
export RAGAS_DO_NOT_TRACK=true

MODE="--dry-run"
if [ "${1:-}" = "--real" ]; then MODE=""; fi
exec "$VENV/bin/python" scripts/run_rag_evals.py $MODE --ragas-crossover
