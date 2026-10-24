#!/usr/bin/env bash
# Audita un entorno Python resuelto con pip, NO uv.lock ni la imagen real:
# instala requirements.txt en un venv py3.12 limpio, aplica el mismo override de
# Pillow que Dockerfile.prod (`pip install --no-deps pillow==X`; fastembed declara
# pillow<13 y pip no lo resuelve solo) y ejecuta pip-audit --local sobre ese venv.
#
# Limites (leer antes de interpretar "exit 0"):
#  - Solo avisos que conoce la base de pip-audit hoy. 0 != "sin advisories".
#  - torch y torchvision (+cpu, indice de PyTorch) no estan en PyPI: pip-audit los
#    SALTA ("could not be audited"). No auditados.
#  - pip resuelve rangos en el momento de ejecutar (y segun arquitectura/SO): no es
#    el entorno exacto de la imagen (apt, no-root, ARM64) ni lo que resuelve uv.lock.
#  - No lleva exclusiones por defecto: pasa "$@" tal cual a pip-audit (p. ej. --ignore-vuln).
#
# Requiere uv y Python 3.12 (pillow 13 exige >=3.11). La instalacion tarda varios minutos.
# AUDIT_VENV=/ruta permite reanudar (venv propio, marcado, NO se borra); sin ella se
# crea un venv temporal que se borra al salir (ruta temporal con trap: no probada de
# punta a punta, solo la ruta AUDIT_VENV).
# Uso: data-engine/scripts/audit_deps.sh [args de pip-audit]
# Devuelve el exit code de pip-audit (0 = sin hallazgos conocidos).
set -euo pipefail
cd "$(dirname "$0")/.."

# Override Pillow: cada Dockerfile debe llevar exactamente UN pin pillow== y ambos
# deben coincidir; ausente en uno, ambiguo o discordante -> exit 2.
pin_of() {
  local v n
  v="$(grep -oE 'pillow==[0-9][0-9.]*' "$1" | sort -u || true)"
  n="$(printf '%s' "$v" | grep -c . || true)"
  if [ "$n" -ne 1 ]; then
    echo "ERROR: $1 debe tener exactamente un pin pillow== (hay $n: $v)" >&2; exit 2
  fi
  printf '%s' "$v"
}
PIN_A="$(pin_of Dockerfile)"; PIN_B="$(pin_of Dockerfile.prod)"
if [ "$PIN_A" != "$PIN_B" ]; then
  echo "ERROR: pines discordantes: Dockerfile=$PIN_A Dockerfile.prod=$PIN_B" >&2; exit 2
fi
OVR="$PIN_A"

MARK=".audit_deps_venv"
if [ -n "${AUDIT_VENV:-}" ]; then
  V="$AUDIT_VENV"; mkdir -p "$V"
  if [ -e "$V/env" ] && [ ! -e "$V/$MARK" ]; then
    echo "ERROR: $V/env existe y no lleva la marca de este script; no se reutiliza" >&2; exit 2
  fi
else
  V="$(mktemp -d)"; trap 'rm -rf "$V"' EXIT
fi
[ -x "$V/env/bin/python" ] || uv venv --python 3.12 -q "$V/env"
: > "$V/$MARK"
PY="$V/env/bin/python"
PYV="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
if [ "$PYV" != "3.12" ]; then
  echo "ERROR: el venv usa Python $PYV, se exige 3.12" >&2; exit 2
fi
uv pip install --python "$PY" -q pip pip-audit
"$PY" -m pip install -q -r requirements.txt
"$PY" -m pip install -q --no-deps "$OVR"
GOT="$("$PY" -c 'import importlib.metadata as m;print("pillow=="+m.version("pillow"))')"
if [ "$GOT" != "$OVR" ]; then
  echo "ERROR: pillow instalado $GOT != override $OVR; no se audita" >&2; exit 2
fi
echo "entorno auditado: py$PYV, requirements.txt + $OVR (env $V/env)" >&2
"$PY" -m pip_audit --local "$@"
