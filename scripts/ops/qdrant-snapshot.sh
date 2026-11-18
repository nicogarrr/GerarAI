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
# API) y anade retencion y verificacion.
#
# REGLA DE BORRADO (v2, tras auditoria): NADA se borra del servidor sin una
# copia local VERIFICADA de ESE MISMO snapshot, y si algo no valida, no se
# borra. En concreto:
#   - el snapshot del dia solo se borra del servidor tras descargarlo y
#     verificarlo (no vacio, tar listable, sha256 local registrado);
#   - el barrido de retencion solo borra un snapshot antiguo del servidor si
#     existe copia local con el nombre de servidor registrado y sha256 que
#     verifica HOY; y se salta entera cualquier coleccion cuya descarga de
#     hoy fallo;
#   - todo nombre remoto (creado o listado) debe pasar una validacion
#     estricta antes de interpolarse en una URL: sin eso, ni descarga ni
#     borrado;
#   - un listado ilegible o malformado es ERROR visible y no borra nada.
#
# Verificacion local: no vacio + listable con tar (los snapshots de Qdrant
# son archivos tar) + sidecar .sha256 para detectar corrupcion posterior.
# El servidor no ofrece hash: la integridad la acredita el listado tar y la
# huella local, no el servidor (declarado).
#
# No toca datos de Qdrant: crear y descargar snapshots es lectura. Solo
# escribe en OUT_DIR y borra snapshots en el servidor bajo la regla de arriba.
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
for tool in curl python3 tar sha256sum; do
  command -v "${tool}" >/dev/null || { echo "[qdrant-snapshot] falta ${tool} (sin verificacion no hay backup valido)"; exit 2; }
done

mkdir -p "${OUT_DIR}"
TS="$(date -u +%Y%m%dT%H%M%S)"

# Los nombres remotos se interpolan en rutas URL: solo se acepta el formato
# documentado de Qdrant (sin espacios, barras ni caracteres de control).
nombre_valido() {
  [[ "$1" =~ ^[A-Za-z0-9._-]+\.snapshot$ ]]
}

# Copia local verificada de un snapshot concreto del servidor:
# fichero no vacio, sidecar .servername que lo vincula a ESE snapshot y
# sidecar .sha256 cuya huella verifica HOY contra el contenido local.
tiene_copia_local_verificada() {  # $1=coleccion $2=nombre en el servidor
  local f base
  for f in "${OUT_DIR}/$1"-*.snapshot; do
    [ -e "${f}" ] || continue
    [ -s "${f}" ] || continue
    base="$(basename "${f}")"
    [ -f "${f}.servername" ] || continue
    [ "$(cat "${f}.servername")" = "$2" ] || continue
    [ -f "${f}.sha256" ] || continue
    (cd "${OUT_DIR}" && sha256sum -c "${base}.sha256" >/dev/null 2>&1) || continue
    return 0
  done
  return 1
}

COLLECTIONS_JSON="$(curl -fsS "${API}/collections")" || { echo "[qdrant-snapshot] ERROR: API no disponible en ${API} (copias anteriores intactas)"; exit 1; }
# Validar TODO el listado ANTES de crear, descargar o borrar nada: la forma
# esperada y TODOS los nombres validos. Un parseo a medias (process
# substitution tragaba el exit del parser y seguia con la primera coleccion)
# presentaba un inventario parcial como sano (hallazgo del auditor, v3).
if ! COLLECTIONS_LIST="$(printf '%s' "${COLLECTIONS_JSON}" | python3 -c '
import json, re, sys
data = json.load(sys.stdin)
collections = data["result"]["collections"]
names = []
for c in collections:
    name = c["name"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise SystemExit("nombre de coleccion invalido: " + repr(name))
    names.append(name)
for n in names:
    print(n)
')"; then
  echo "[qdrant-snapshot] ERROR: listado de colecciones ilegible o con nombres invalidos (copias anteriores intactas, no se toca nada)"
  exit 1
fi
mapfile -t COLLECTIONS <<< "${COLLECTIONS_LIST}"
[ "${#COLLECTIONS[@]}" -gt 0 ] && [ -n "${COLLECTIONS[0]}" ] || COLLECTIONS=()
if [ "${#COLLECTIONS[@]}" -eq 0 ]; then
  echo "[qdrant-snapshot] ERROR: la API no devolvio ninguna coleccion (copias anteriores intactas)"
  exit 1
fi

fail=0
FAILED_COLLS=""
for COLL in "${COLLECTIONS[@]}"; do
  OUT="${OUT_DIR}/${COLL}-${TS}.snapshot"
  SNAP_NAME="$(curl -fsS -X POST "${API}/collections/${COLL}/snapshots" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["name"])')" || {
    echo "[qdrant-snapshot] ERROR creando snapshot de ${COLL}"; fail=1; FAILED_COLLS="${FAILED_COLLS} ${COLL}"; continue; }
  if ! nombre_valido "${SNAP_NAME}"; then
    # Nombre remoto fuera de formato: no se interpola en ninguna URL. Queda
    # en el servidor (el barrido tampoco lo tocara: no valida).
    echo "[qdrant-snapshot] ERROR: el servidor devolvio un nombre de snapshot invalido para ${COLL}; no se descarga ni se borra"
    fail=1; FAILED_COLLS="${FAILED_COLLS} ${COLL}"; continue
  fi
  if ! curl -fsS "${API}/collections/${COLL}/snapshots/${SNAP_NAME}" -o "${OUT}.part"; then
    echo "[qdrant-snapshot] ERROR descargando snapshot de ${COLL} (queda en el servidor para diagnostico)"; rm -f "${OUT}.part"; fail=1; FAILED_COLLS="${FAILED_COLLS} ${COLL}"; continue
  fi
  if [ ! -s "${OUT}.part" ]; then
    echo "[qdrant-snapshot] ERROR: snapshot de ${COLL} vacio (queda en el servidor)"; rm -f "${OUT}.part"; fail=1; FAILED_COLLS="${FAILED_COLLS} ${COLL}"; continue
  fi
  if ! tar -tf "${OUT}.part" >/dev/null 2>&1; then
    # No es un tar listable: no es restaurable, no vale como copia.
    echo "[qdrant-snapshot] ERROR: snapshot de ${COLL} no es un tar listable (queda en el servidor)"
    rm -f "${OUT}.part"; fail=1; FAILED_COLLS="${FAILED_COLLS} ${COLL}"; continue
  fi
  mv "${OUT}.part" "${OUT}"
  digest="$(sha256sum "${OUT}" | awk '{print $1}')"
  printf '%s  %s\n' "${digest}" "$(basename "${OUT}")" > "${OUT}.sha256"
  printf '%s' "${SNAP_NAME}" > "${OUT}.servername"
  echo "[qdrant-snapshot] OK ${COLL}: $(wc -c < "${OUT}") bytes, sha256 ${digest}"
  # El snapshot se crea en el disco del SERVIDOR Qdrant: si no se borra, el
  # cron diario llena el volumen (hallazgo de FAV, 18-nov-2026). Solo se borra
  # ahora: copia local de ESTE snapshot ya verificada arriba. Si la descarga
  # fallo, la coleccion esta en FAILED_COLLS y nada suyo se borra.
  if ! curl -fsS -X DELETE "${API}/collections/${COLL}/snapshots/${SNAP_NAME}"; then
    echo "[qdrant-snapshot] ERROR: no se pudo borrar el snapshot del servidor (${COLL}/${SNAP_NAME}); la copia local esta a salvo pero el disco del servidor crece"
    fail=1
  fi
done

# Retencion TAMBIEN en el servidor, bajo la regla de borrado: solo se borra
# un snapshot antiguo con copia local verificada de ESE snapshot, y nunca en
# una coleccion cuya descarga de hoy fallo.
for COLL in "${COLLECTIONS[@]}"; do
  case "${FAILED_COLLS}" in
    *" ${COLL}"*)
      echo "[qdrant-snapshot] servidor: retencion de ${COLL} pospuesta (la descarga de hoy fallo; no se borra nada suyo)"
      continue
      ;;
  esac
  LIST_JSON="$(curl -fsS "${API}/collections/${COLL}/snapshots")" || {
    echo "[qdrant-snapshot] ERROR listando snapshots del servidor de ${COLL} (no se borra nada)"; fail=1; continue; }
  # Validar el listado ANTES de formar la lista de borrado: JSON con la forma
  # esperada y TODOS los nombres con formato valido. Si algo no valida, la
  # coleccion entera queda sin borrar (un listado dudoso no autoriza deletes).
  if ! SERVER_LIST="$(printf '%s' "${LIST_JSON}" | python3 -c '
import json, re, sys
data = json.load(sys.stdin)
snaps = data["result"]
if not isinstance(snaps, list):
    raise SystemExit("forma inesperada")
names = []
for s in snaps:
    name = s["name"]
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.snapshot", name):
        raise SystemExit("nombre invalido: " + repr(name))
    names.append(name)
for n in sorted(names):
    print(n)
')"; then
    echo "[qdrant-snapshot] ERROR: listado de snapshots de ${COLL} ilegible o con nombres invalidos (no se borra nada)"
    fail=1
    continue
  fi
  mapfile -t SERVER_SNAPS <<< "${SERVER_LIST}"
  [ "${#SERVER_SNAPS[@]}" -gt 0 ] && [ -n "${SERVER_SNAPS[0]}" ] || SERVER_SNAPS=()
  EXTRAS=$(( ${#SERVER_SNAPS[@]} - KEEP ))
  if [ "${EXTRAS}" -gt 0 ]; then
    for OLD in "${SERVER_SNAPS[@]:0:${EXTRAS}}"; do
      if ! tiene_copia_local_verificada "${COLL}" "${OLD}"; then
        # Sin copia local verificada de ESTE snapshot: no se borra, visible.
        echo "[qdrant-snapshot] servidor: ${COLL}/${OLD} excede la retencion pero NO tiene copia local verificada; no se borra"
        fail=1
        continue
      fi
      if curl -fsS -X DELETE "${API}/collections/${COLL}/snapshots/${OLD}"; then
        echo "[qdrant-snapshot] servidor: borrado snapshot antiguo ${COLL}/${OLD} (copia local verificada)"
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
      rm -f -- "${OLD}" "${OLD}.sha256" "${OLD}.servername"
    done
  done
  echo "[qdrant-snapshot] OK: ${#COLLECTIONS[@]} colecciones, retencion ${KEEP} por coleccion"
else
  echo "[qdrant-snapshot] ERROR: hubo fallos; copias anteriores conservadas"
fi
exit "${fail}"
