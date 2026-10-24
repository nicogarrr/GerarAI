#!/usr/bin/env bash
# Audita el entorno Python EFECTIVO de la imagen, no solo requirements.txt:
# instala requirements.txt en un venv limpio, aplica el mismo override de Pillow
# que Dockerfile.prod (`pip install --no-deps pillow==X`; fastembed declara
# pillow<13 y pip no lo resuelve solo) y ejecuta pip-audit sobre ese entorno.
# Requiere uv y Python 3.12 (pillow 13 exige >=3.11). La instalacion tarda varios minutos.
# Uso: data-engine/scripts/audit_deps.sh [--ignore-vuln ID ...]
# Devuelve el exit code de pip-audit (0 = sin hallazgos).
set -euo pipefail
cd "$(dirname "$0")/.."
OVR="$(grep -oE 'pillow==[0-9][0-9.]*' Dockerfile.prod | head -1)"
[ -n "$OVR" ] || { echo "no se encontro override pillow== en Dockerfile.prod" >&2; exit 2; }
V="$(mktemp -d)"; trap 'rm -rf "$V"' EXIT
uv venv --python 3.12 -q "$V/env"
uv pip install --python "$V/env/bin/python" -q pip pip-audit
"$V/env/bin/python" -m pip install -q -r requirements.txt
"$V/env/bin/python" -m pip install -q --no-deps "$OVR"
echo "entorno auditado: requirements.txt + $OVR" >&2
"$V/env/bin/python" -m pip_audit --local "$@"
