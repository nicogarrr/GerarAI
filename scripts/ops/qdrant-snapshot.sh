#!/usr/bin/env bash
# Snapshot programado de Qdrant por coleccion (API loopback del compose).
#
# Motivo (medido 18-nov-2026): Qdrant tenia datos verificados en el drill del
# 26-sep y el repo sabe restaurarlos (backup_qdrant.py, API de snapshots), pero
# NO habia ningun backup programado: el unico flujo que los tomaba era el
# legacy scripts/backup.sh, hoy bloqueado. Perder el volumen obliga a
# re-embedir todo (coste de LLM/CPU y horas). Coste 0 EUR.
#
# Esta version se extrae del flujo legacy (misma llamada por coleccion via
# API) y anade retencion y verificacion minima: cada .snapshot descargado debe
# existir y no estar vacio; un fallo en cualquier coleccion termina con error
# y NO rota copias anteriores.
#
# No toca datos de Qdrant: crear y descargar snapshots es lectura. Solo
# escribe en OUT_DIR y borra alli los snapshots que sobran por retencion.
#
# Variables:
#   QDRANT_API_URL  API solo-loopback del compose (defecto http://127.0.0.1:6333)
#   OUT_DIR         destino (defecto ~/backups/qdrant)
#   KEEP            snapshots por coleccion a conservar (defecto 7: uno diario, una semana)
#
# Uso: ./scripts/ops/qdrant-snapshot.sh
# Cron sugerido (host): 20 4 * * * /ruta/qdrant-snapshot.sh || avisar
# La frescura la vigila check-backup-freshness.sh (pilar qdrant).
set -euo pipefail

API="${QDRANT_API_URL:-http://127.0.0.1:6333}"
OUT_DIR="${OUT_DIR:-$HOME/backups/qdrant}"
KEEP="${KEEP:-7}"
case "${KEEP}" in ''|*[!0-9]*) echo "KEEP debe ser un numero (p. ej. 7)"; exit 2;; esac
if [ "${KEEP}" -lt 1 ]; then echo "KEEP debe ser al menos 1"; exit 2; fi
command -v curl >/dev/null || { echo "[qdrant-snapshot] falta curl"; exit 2; }
command -v python3 >/dev/null || { echo "[qdrant-snapshot] falta python3"; exit 2; }

mkdir -p "${OUT_DIR}"
TS="$(date -u +%Y%m%dT%H%M%S)"

COLLECTIONS_JSON="$(curl -fsS "${API}/collections")" || { echo "[qdrant-snapshot] ERROR: API no disponible en ${API} (copias anteriores intactas)"; exit 1; }
mapfile -t COLLECTIONS < <(printf '%s' "${COLLECTIONS_JSON}" | python3 -c 'import json,sys; [print(c["name"]) for c in json.load(sys.stdin)["result"]["collections"]]')
if [ "${#COLLECTIONS[@]}" -eq 0 ]; then
  echo "[qdrant-snapshot] ERROR: la API no devolvio ninguna coleccion (copias anteriores intactas)"
  exit 1
fi

fail=0
for COLL in "${COLLECTIONS[@]}"; do
  OUT="${OUT_DIR}/${COLL}-${TS}.snapshot"
  SNAP_NAME="$(curl -fsS -X POST "${API}/collections/${COLL}/snapshots" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["name"])')" || {
    echo "[qdrant-snapshot] ERROR creando snapshot de ${COLL}"; fail=1; continue; }
  if ! curl -fsS "${API}/collections/${COLL}/snapshots/${SNAP_NAME}" -o "${OUT}.part"; then
    echo "[qdrant-snapshot] ERROR descargando snapshot de ${COLL}"; rm -f "${OUT}.part"; fail=1; continue
  fi
  if [ ! -s "${OUT}.part" ]; then
    echo "[qdrant-snapshot] ERROR: snapshot de ${COLL} vacio"; rm -f "${OUT}.part"; fail=1; continue
  fi
  mv "${OUT}.part" "${OUT}"
  echo "[qdrant-snapshot] OK ${COLL}: $(wc -c < "${OUT}") bytes"
  # El snapshot se crea en el disco del SERVIDOR Qdrant: si no se borra, el
  # cron diario llena el volumen (hallazgo de FAV, 18-nov-2026). Solo se borra
  # despues de descargarlo y verificarlo; si la descarga fallo, queda en el
  # servidor para diagnostico (y la retencion de mas abajo lo acota).
  if ! curl -fsS -X DELETE "${API}/collections/${COLL}/snapshots/${SNAP_NAME}"; then
    echo "[qdrant-snapshot] ERROR: no se pudo borrar el snapshot del servidor (${COLL}/${SNAP_NAME}); la copia local esta a salvo pero el disco del servidor crece"
    fail=1
  fi
done

# Retencion TAMBIEN en el servidor: los restos de borrados fallidos no pueden
# acumularse sin limite. Se conservan los KEEP mas recientes por coleccion
# (los nombres llevan timestamp ISO: el orden alfabetico es el cronologico).
for COLL in "${COLLECTIONS[@]}"; do
  LIST_JSON="$(curl -fsS "${API}/collections/${COLL}/snapshots")" || {
    echo "[qdrant-snapshot] ERROR listando snapshots del servidor de ${COLL}"; fail=1; continue; }
  mapfile -t SERVER_SNAPS < <(printf '%s' "${LIST_JSON}" | python3 -c 'import json,sys; [print(s["name"]) for s in sorted(json.load(sys.stdin)["result"], key=lambda s: s["name"])]')
  EXTRAS=$(( ${#SERVER_SNAPS[@]} - KEEP ))
  if [ "${EXTRAS}" -gt 0 ]; then
    for OLD in "${SERVER_SNAPS[@]:0:${EXTRAS}}"; do
      if curl -fsS -X DELETE "${API}/collections/${COLL}/snapshots/${OLD}"; then
        echo "[qdrant-snapshot] servidor: borrado snapshot antiguo ${COLL}/${OLD}"
      else
        echo "[qdrant-snapshot] ERROR borrando snapshot antiguo ${COLL}/${OLD}"
        fail=1
      fi
    done
  fi
done

# Rotar solo si TODO salio bien: un fallo nunca purga copias buenas.
if [ "${fail}" -eq 0 ]; then
  for COLL in "${COLLECTIONS[@]}"; do
    ls -1t "${OUT_DIR}/${COLL}"-*.snapshot 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r OLD; do
      rm -f -- "${OLD}"
    done
  done
  echo "[qdrant-snapshot] OK: ${#COLLECTIONS[@]} colecciones, retencion ${KEEP} por coleccion"
else
  echo "[qdrant-snapshot] ERROR: hubo fallos; copias anteriores conservadas"
fi
exit "${fail}"
