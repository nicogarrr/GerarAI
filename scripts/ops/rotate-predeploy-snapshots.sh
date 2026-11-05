#!/usr/bin/env bash
# Rotacion de los snapshots predeploy-*.json del volumen duckdb de prod.
#
# Contexto (medido 5-nov-2026): cada deploy deja 3 snapshots de estado
# (predeploy-<sha>-critical-state.json, -esef-valuations.json,
# -complete-state.json, ~40 MB en total) en cavaai-prod-duckdb y NUNCA
# rotan (~400 MB en 2 dias; el volumen tambien guarda la cache de
# modelos, que NO se toca). El escritor es el runbook FULLPRE del piloto
# (fuera del repo); este script es la retencion: conserva los KEEP mas
# recientes y borra el resto. KEEP=30 por defecto: unos 10 deploys de
# historial (3 JSON por deploy).
#
# LO EJECUTA UN OPERADOR, nunca un agente ni un cron sin OK de Nico
# (los predeploy-*.json son backups):
#   ./scripts/ops/rotate-predeploy-snapshots.sh --confirm-rotate
set -euo pipefail

KEEP="${KEEP:-30}"

case "${1:-}" in
  --confirm-rotate) ;;
  *) echo "Uso: $0 --confirm-rotate"; echo "Borra snapshots predeploy antiguos del volumen duckdb (conserva los ${KEEP} mas recientes)."; exit 1;;
esac

# KEEP se valida ANTES de tocar docker: sin validacion, un KEEP inyectado
# expandiria dentro del sh -c que corre como root en el contenedor.
case "${KEEP}" in
  ''|*[!0-9]*) echo "KEEP debe ser un entero positivo (valor actual: '${KEEP}')"; exit 2;;
esac
if [ "${KEEP}" -lt 1 ]; then
  echo "KEEP debe ser al menos 1 (valor actual: ${KEEP})"; exit 2
fi

DUCKDB_VOLUME="${DUCKDB_VOLUME:-cavaai-prod-duckdb}"

# Dentro del volumen via alpine: nada de rutas de host (/var/lib/docker es
# root-only). Solo se listan/borran predeploy-*.json del nivel raiz de
# /data. KEEP viaja como argumento posicional ($1), nunca interpolado en
# el script que corre como root.
docker run --rm -v "${DUCKDB_VOLUME}":/data alpine sh -c '
  set -eu
  KEEP="$1"
  cd /data
  TOTAL=$(ls -1 predeploy-*.json 2>/dev/null | wc -l)
  echo "[rotate] snapshots predeploy presentes: ${TOTAL}; se conservan los ${KEEP} mas recientes"
  ls -1t predeploy-*.json 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r F; do
    echo "[rotate] borrando ${F}"
    rm -f "${F}"
  done
  QUEDAN=$(ls -1 predeploy-*.json 2>/dev/null | wc -l)
  echo "[rotate] quedan: ${QUEDAN}"
' -- "${KEEP}"
