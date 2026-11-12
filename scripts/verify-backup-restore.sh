#!/usr/bin/env bash
# Drill de verificacion de backup/restore para la VM de produccion.
#
# NO toca contenedores ni volumenes de produccion: genera una copia del
# compose de prod con nombres/puertos propios (cavaai-verify-*), restaura
# ahi un backup real con el MISMO scripts/restore.sh y verifica Postgres,
# Qdrant, MinIO y DuckDB. Al terminar (bien o mal) baja el proyecto y borra
# sus volumenes.
#
# Prerequisitos en la VM: docker compose v2, curl, python3, y un backup
# generado por scripts/backup.sh. El .env de produccion se reutiliza (las
# credenciales internas son las mismas; los servicios van en una red propia).
#
# Uso: ./scripts/verify-backup-restore.sh backups/YYYYMMDD-HHMMSS
set -euo pipefail

# Retirado con MinIO de produccion. El cuerpo legacy se conserva solo como
# referencia del formato antiguo; NO es un backup/restore valido de Garage.
# Ni COMPOSE_CMD permite saltarse el bloqueo: podria apuntar a produccion.
echo "ERROR: flujo legacy MinIO retirado. No se ha tocado ningun dato. Usa el flujo de backup/restore Garage validado por operaciones; este script no lo sustituye." >&2
exit 1

BACKUP_PATH="${1:?Uso: ./scripts/verify-backup-restore.sh backups/YYYYMMDD-HHMMSS}"
case "${BACKUP_PATH}" in backups/*) ;; *) echo "El backup debe estar dentro de ./backups/"; exit 1;; esac
[ -f "${BACKUP_PATH}/postgres.dump" ] || { echo "No existe ${BACKUP_PATH}/postgres.dump"; exit 1; }

# El compose de prod exige variables de .env.production (POSTGRES_PASSWORD,
# MINIO_ROOT_*, RESEARCH_AUTH_SECRET, BACKEND_DOMAIN): sin --env-file,
# `docker compose config` falla antes de empezar. No es el nombre por
# defecto de compose, asi que hay que pasarlo explicitamente.
ENV_FILE="${ENV_FILE:-.env.production}"
[ -f "${ENV_FILE}" ] || { echo "No existe ${ENV_FILE} (hace falta para las credenciales del compose aislado)"; exit 1; }
[ -f "${BACKUP_PATH}/manifest.txt" ] || { echo "No existe ${BACKUP_PATH}/manifest.txt"; exit 1; }

# El compose generado va en la RAIZ del repo: las rutas relativas del compose
# de prod (build ./data-engine, mounts ./data-esef-snapshots, ./infra/...) se
# resuelven desde el directorio del primer -f. Dentro de backups/ quedarian
# rotas o apuntando a carpetas equivocadas.
VERIFY_COMPOSE=".verify-compose.yml"
export COMPOSE_CMD="docker compose -p cavaai-verify -f ${VERIFY_COMPOSE} --env-file ${ENV_FILE}"
export QDRANT_API_URL="http://127.0.0.1:16333"
export QDRANT_VOLUME="cavaai-verify-qdrant"
export MINIO_VOLUME="cavaai-verify-minio"
export DUCKDB_VOLUME="cavaai-verify-duckdb"
# Sin caddy (puerto 80 es de produccion) ni worker/scheduler: no hacen falta
# para verificar datos y su arranque tocaria colas reales.
export RESTORE_UP_SERVICES="postgres redis qdrant minio backend"

VERIFY_DATA_VOLUMES="cavaai-verify-postgres cavaai-verify-redis cavaai-verify-qdrant cavaai-verify-minio cavaai-verify-duckdb"

cleanup() {
  echo "[verify] limpieza: bajando el proyecto aislado y borrando sus volumenes…"
  ${COMPOSE_CMD} down -v --remove-orphans >/dev/null 2>&1 || true
  # Los volumenes con name: explicito son externos para compose: down -v NO
  # los borra. Sin esto, el drill siguiente hereda la base restaurada (WAL
  # recovery larga) y postgres no responde dentro de la espera del restore.
  docker volume rm ${VERIFY_DATA_VOLUMES} cavaai-verify-freshduck >/dev/null 2>&1 || true
  # La imagen del drill es un artefacto regenerable (mismo build en cada
  # corrida): sin este borrado cada verify deja ~4,4 GB de imagen mas las
  # capas <none> del build anterior.
  docker image rm cavaai-backend:verify >/dev/null 2>&1 || true
  rm -f "${VERIFY_COMPOSE}"
}
trap cleanup EXIT

# ---------------------------------------------------------------- 1/5 ----
echo "[verify] 1/5 arranque con volumen NUEVO (imagen Dockerfile.prod)…"
docker build -q -f data-engine/Dockerfile.prod -t cavaai-backend:verify data-engine >/dev/null
docker volume rm cavaai-verify-freshduck >/dev/null 2>&1 || true
docker volume create cavaai-verify-freshduck >/dev/null
# Un volumen named nuevo hereda propietario del /data de la imagen. Sin el
# chown del Dockerfile seria root-owned y este touch fallaria (USER cavaai).
docker run --rm -v cavaai-verify-freshduck:/data cavaai-backend:verify touch /data/.write-ok
echo "[verify] volumen nuevo escribible por el usuario de la app: OK"

# ---------------------------------------------------------------- 2/5 ----
echo "[verify] 2/5 proyecto compose aislado (nombres, puertos y volumenes propios)…"
# Arranque siempre desde volumenes vacios: los name: explicitos sobreviven
# a down -v y un drill anterior dejaria la base restaurada a medias.
# Un drill anterior interrumpido a la fuerza (kill -9 no ejecuta el trap)
# puede dejar contenedores cavaai-verify-* vivos: mientras existan RETIENEN
# sus volumenes y el rm de abajo falla en silencio, y este drill mediria
# sobre la base restaurada a medias de aquel. Primero se barren.
STALE_VERIFY=$(docker ps -aq --filter "name=cavaai-verify-" 2>/dev/null || true)
if [ -n "${STALE_VERIFY}" ]; then
  echo "[verify] restos de un drill anterior interrumpido: bajando contenedores aislados…"
  docker rm -f ${STALE_VERIFY} >/dev/null 2>&1 || true
fi
docker volume rm ${VERIFY_DATA_VOLUMES} >/dev/null 2>&1 || true
# Copia del compose de prod con identidad propia. sed deterministico, sin
# depender de la semantica de merge de overrides de compose.
sed -e 's/container_name: cavaai-/container_name: cavaai-verify-/' \
    -e 's/"127.0.0.1:6333:6333"/"127.0.0.1:16333:6333"/' \
    -e 's/name: cavaai-prod-/name: cavaai-verify-/' \
    -e 's/image: cavaai-backend:prod/image: cavaai-backend:verify/' \
    docker-compose.prod.yml > "${VERIFY_COMPOSE}"

# Validacion impresa ANTES de levantar nada: si el render no ensena la imagen
# aislada (cavaai-backend:verify), los volumenes cavaai-verify-* y los mounts
# esperados, no se toca Docker. Sin esto, un sed que no case pasa desapercibido
# y el drill acaba reconstruyendo la imagen o los volumenes de produccion.
${COMPOSE_CMD} config > /tmp/verify-compose-rendered.yml
grep -q 'cavaai-backend:verify' /tmp/verify-compose-rendered.yml || { echo "[verify] ERROR: el compose renderizado no usa imagen aislada"; exit 1; }
grep -q 'cavaai-verify-duckdb' /tmp/verify-compose-rendered.yml || { echo "[verify] ERROR: el compose renderizado no usa volumenes aislados"; exit 1; }
echo "[verify] compose renderizado validado (imagen y volumenes aislados):"
${COMPOSE_CMD} config | grep -E 'container_name|image:|name: cavaai-verify|127.0.0.1:16333|source: '

${COMPOSE_CMD} up -d postgres redis qdrant minio
echo "[verify] esperando a Qdrant en ${QDRANT_API_URL}…"
for _ in $(seq 1 30); do
  curl -fsS "${QDRANT_API_URL}/collections" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS "${QDRANT_API_URL}/collections" >/dev/null

# ---------------------------------------------------------------- 3/5 ----
echo "[verify] 3/5 integridad del backup (checksums del manifest) y restore REAL…"
# Cada artefacto tiene que casar con su sha256 del manifest: un backup
# corrupto en disco/R2 se detecta ANTES de restaurarlo.
grep '^sha256\.' "${BACKUP_PATH}/manifest.txt" | while IFS= read -r LINE; do
  KEY="${LINE#sha256.}"; FILE="${KEY%%=*}"; WANT="${KEY#*=}"
  GOT=$(sha256sum "${BACKUP_PATH}/${FILE}" | awk '{print $1}')
  [ "${GOT}" = "${WANT}" ] || { echo "[verify] ERROR: checksum no casa en ${FILE}"; exit 1; }
done || exit 1
echo "[verify] checksums del backup: OK"
./scripts/restore.sh "${BACKUP_PATH}" --confirm-restore

# ---------------------------------------------------------------- 4/5 ----
echo "[verify] 4/5 comprobaciones…"
PG_COUNT() { ${COMPOSE_CMD} exec -T postgres psql -U "${POSTGRES_USER:-portfolio}" -d "${POSTGRES_DB:-cavaai_research}" -tAc "$1"; }

# Comparacion REAL contra el manifest del backup (no contra produccion en
# vivo): cada conteo restaurado tiene que igualar lo que el backup declaro.
MANIFEST="${BACKUP_PATH}/manifest.txt"
grep -q '^pg_table_count\.' "${MANIFEST}" || {
  echo "[verify] ERROR: el manifest no tiene conteos por tabla (pg_table_count.*)."
  echo "[verify] Regenera el backup con el scripts/backup.sh actualizado y repite el drill."
  exit 1
}
MISMATCHES=0
while IFS= read -r LINE; do
  KEY="${LINE#pg_table_count.}"; T="${KEY%%=*}"; WANT="${KEY#*=}"
  GOT=$(PG_COUNT "SELECT count(*) FROM \"${T}\"")
  if [ "${GOT}" != "${WANT}" ]; then
    echo "[verify] ERROR: tabla ${T}: restaurado=${GOT} manifest=${WANT}"
    MISMATCHES=$((MISMATCHES + 1))
  fi
done < <(grep '^pg_table_count\.' "${MANIFEST}")
[ "${MISMATCHES}" -eq 0 ] || { echo "[verify] ERROR: ${MISMATCHES} tablas no casan con el backup"; exit 1; }
echo "[verify] postgres: $(grep -c '^pg_table_count\.' "${MANIFEST}") tablas con conteos identicos al backup: OK"

while IFS= read -r LINE; do
  KEY="${LINE#qdrant_points.}"; C="${KEY%%=*}"; WANT="${KEY#*=}"
  GOT=$(curl -fsS "${QDRANT_API_URL}/collections/${C}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["points_count"])')
  if [ "${GOT}" != "${WANT}" ]; then
    echo "[verify] ERROR: coleccion ${C}: restaurado=${GOT} manifest=${WANT}"
    MISMATCHES=$((MISMATCHES + 1))
  fi
done < <(grep '^qdrant_points\.' "${MANIFEST}" || true)
[ "${MISMATCHES}" -eq 0 ] || { echo "[verify] ERROR: colecciones qdrant no casan con el backup"; exit 1; }
QCOLLS_OK=$(grep -c '^qdrant_points\.' "${MANIFEST}" || true)
echo "[verify] qdrant: ${QCOLLS_OK} colecciones con puntos identicos al backup: OK"

# MinIO y DuckDB: numero de ficheros restaurados = entradas fichero del tar.
for V in "minio:${MINIO_VOLUME}:minio.tar.gz" "duckdb:${DUCKDB_VOLUME}:duckdb.tar.gz"; do
  NAME="${V%%:*}"; REST="${V#*:}"; VOL="${REST%%:*}"; TAR="${REST#*:}"
  WANT=$(grep "^file_count\.${TAR}=" "${MANIFEST}" | cut -d= -f2 || true)
  [ -n "${WANT}" ] || { echo "[verify] aviso: manifest sin file_count.${TAR}; se omite ${NAME}"; continue; }
  # MinIO regenera .minio.sys al arrancar (metadato vivo, no va en el tar):
  # contar solo ficheros de usuario o el drill falla en falso.
  GOT=$(docker run --rm -v "${VOL}":/data:ro alpine sh -c 'find /data -type f ! -path "/data/.minio.sys/*" | wc -l')
  if [ "${GOT}" != "${WANT}" ]; then
    echo "[verify] ERROR: ${NAME}: ${GOT} ficheros restaurados, ${WANT} en el backup"
    exit 1
  fi
  echo "[verify] ${NAME}: ${GOT} ficheros, identico al backup: OK"
done

# ---------------------------------------------------------------- 5/5 ----
echo "[verify] 5/5 DRILL COMPLETO: el backup restaura y cada conteo y checksum"
echo "    casa con el manifest. La limpieza del proyecto aislado corre sola al salir."
