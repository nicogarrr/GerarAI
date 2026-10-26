#!/usr/bin/env bash
# Restore de GerarAI (produccion personal). DESTRUCTIVO: sobrescribe Postgres
# y los volumenes de MinIO/DuckDB. Solo en ventana de mantenimiento.
#
# Uso: ./scripts/restore.sh backups/YYYYMMDD-HHMMSS --confirm-restore
#
# Knobs de entorno (para el drill de verificacion en proyecto aislado; en
# produccion no hace falta definir nada):
#   COMPOSE_CMD          compose completo a usar (def.: docker compose -f docker-compose.prod.yml
#                        --env-file .env.production si existe)
#   QDRANT_API_URL       API de Qdrant (def.: http://127.0.0.1:6333)
#   QDRANT_VOLUME        volumen para el fallback en crudo (def.: cavaai-prod-qdrant)
#   MINIO_VOLUME         volumen de MinIO (def.: cavaai-prod-minio)
#   DUCKDB_VOLUME        volumen de DuckDB (def.: cavaai-prod-duckdb)
#   RESTORE_UP_SERVICES  servicios a levantar al final (def.: todos)
set -euo pipefail

BACKUP_PATH="${1:?Uso: ./scripts/restore.sh <backup-path> --confirm-restore}"
[ "${2:-}" = "--confirm-restore" ] || { echo "Falta --confirm-restore (operacion destructiva)"; exit 1; }
case "${BACKUP_PATH}" in backups/*) ;; *) echo "El backup debe estar dentro de ./backups/"; exit 1;; esac
[ -f "${BACKUP_PATH}/postgres.dump" ] || { echo "No existe ${BACKUP_PATH}/postgres.dump"; exit 1; }

# Mismo fallback que backup.sh: .env.production no se carga solo (no es el
# nombre por defecto de compose) y sin el las variables obligatorias hacen
# fallar cualquier subcomando. COMPOSE_CMD externo tiene prioridad.
if [ -z "${COMPOSE_CMD:-}" ] && [ -f .env.production ]; then
  COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"
else
  COMPOSE="${COMPOSE_CMD:-docker compose -f docker-compose.prod.yml}"
fi
QDRANT_API_URL="${QDRANT_API_URL:-http://127.0.0.1:6333}"
QDRANT_VOLUME="${QDRANT_VOLUME:-cavaai-prod-qdrant}"
MINIO_VOLUME="${MINIO_VOLUME:-cavaai-prod-minio}"
DUCKDB_VOLUME="${DUCKDB_VOLUME:-cavaai-prod-duckdb}"

echo "[restore] desde: ${BACKUP_PATH}"

# Fail-closed: no se destruye nada hasta comprobar que los artefactos son los
# que declara el manifest. Un dump truncado o un tar corrupto se detecta aqui,
# no despues del dropdb.
[ -f "${BACKUP_PATH}/manifest.txt" ] || { echo "[restore] ERROR: falta ${BACKUP_PATH}/manifest.txt"; exit 1; }
echo "[restore] verificando checksums del manifest…"
(
  cd "${BACKUP_PATH}"
  while IFS='=' read -r KEY VALUE; do
    case "${KEY}" in
      sha256.*) printf '%s  %s\n' "${VALUE}" "${KEY#sha256.}" ;;
    esac
  done < manifest.txt | sha256sum -c -
) || { echo "[restore] ERROR: checksums invalidos; restore abortado antes de tocar datos"; exit 1; }

echo "[restore] parando servicios…"
# Todos los escritores, no solo backend/worker: un worker dedicado vivo podia
# seguir escribiendo en Postgres/MinIO durante el restore.
${COMPOSE} stop backend worker worker-thesis worker-kpis worker-alerts worker-gdelt worker-knowledge scheduler minio

# 1) Postgres: drop + restore.
echo "[restore] postgres…"
# El contenedor puede estar recien creado (drill, desastre): sin espera, el
# createdb choca con "Connection refused" y el restore muere a medias.
# 180s: un initdb en volumen fresco bajo carga (drill en paralelo con builds)
# o una WAL recovery larga superan los 60s sin que nada este roto.
for _ in $(seq 1 90); do
  ${COMPOSE} exec -T postgres pg_isready -U "${POSTGRES_USER:-portfolio}" >/dev/null 2>&1 && break
  sleep 2
done
${COMPOSE} exec -T postgres pg_isready -U "${POSTGRES_USER:-portfolio}" >/dev/null \
  || { echo "[restore] ERROR: postgres no responde tras 180s"; exit 1; }
${COMPOSE} exec -T postgres dropdb -U "${POSTGRES_USER:-portfolio}" --if-exists "${POSTGRES_DB:-cavaai_research}"
${COMPOSE} exec -T postgres createdb -U "${POSTGRES_USER:-portfolio}" "${POSTGRES_DB:-cavaai_research}"
${COMPOSE} exec -T postgres pg_restore -U "${POSTGRES_USER:-portfolio}" -d "${POSTGRES_DB:-cavaai_research}" --no-owner < "${BACKUP_PATH}/postgres.dump"

# 2) Qdrant (indice vectorial). backup.sh produce una de estas dos formas:
#    - qdrant-snapshots/*.snapshot  (uno por coleccion, via API)
#    - qdrant-raw.tar.gz            (copia del volumen, si la API no respondio)
#    Sin este paso el restore terminaba sin error y sin indice vectorial: el
#    RAG de los tenants volvia vacio.
#
#    El restore por snapshots usa SOLO la API de Qdrant: POST
#    /collections/{c}/snapshots/upload?priority=snapshot. La API crea la
#    coleccion si no existe y la sobrescribe si existe, asi que NO se borra
#    nada antes: un upload fallido deja la coleccion anterior intacta.
#    Qdrant debe estar ARRIBA; el intento anterior montaba el volumen :ro y
#    luego hacia rm/mkdir/cp dentro, paso imposible.
if [ -d "${BACKUP_PATH}/qdrant-snapshots" ]; then
  echo "[restore] qdrant (snapshots por API)…"
  shopt -s nullglob
  QDRANT_SNAPS=("${BACKUP_PATH}"/qdrant-snapshots/*.snapshot)
  if [ "${#QDRANT_SNAPS[@]}" -eq 0 ]; then
    echo "[restore] AVISO: qdrant-snapshots/ esta vacio; el indice vectorial quedara vacio"
  fi
  for SNAP in "${QDRANT_SNAPS[@]}"; do
    COLL="$(basename "${SNAP}" .snapshot)"
    echo "[restore] qdrant: recuperando coleccion ${COLL}…"
    RESP=$(curl -fsS -X POST "${QDRANT_API_URL}/collections/${COLL}/snapshots/upload?priority=snapshot" \
      -H "Content-Type: multipart/form-data" -F "snapshot=@${SNAP}")
    # El HTTP 200 no basta: exigir status=ok y result=true en el cuerpo.
    printf '%s' "${RESP}" | python3 -c 'import json,sys; r=json.load(sys.stdin); sys.exit(0 if r.get("status")=="ok" and r.get("result") is True else 1)' \
      || { echo "[restore] ERROR: upload de ${COLL} no devolvio status ok: ${RESP}"; exit 1; }
  done
elif [ -f "${BACKUP_PATH}/qdrant-raw.tar.gz" ]; then
  echo "[restore] qdrant (volumen en crudo)…"
  ${COMPOSE} stop qdrant
  docker run --rm -v "${QDRANT_VOLUME}":/data -v "$(pwd)/${BACKUP_PATH}":/in:ro alpine sh -c 'rm -rf /data/* && tar xzf /in/qdrant-raw.tar.gz -C /data'
  ${COMPOSE} start qdrant
else
  echo "[restore] AVISO: el backup no contiene qdrant; el indice vectorial quedara vacio"
fi

# 3) MinIO.
if [ -f "${BACKUP_PATH}/minio.tar.gz" ]; then
  echo "[restore] minio…"
  docker run --rm -v "${MINIO_VOLUME}":/data -v "$(pwd)/${BACKUP_PATH}":/in:ro alpine sh -c 'rm -rf /data/* /data/.minio.sys && tar xzf /in/minio.tar.gz -C /data'
fi

# 4) DuckDB.
if [ -f "${BACKUP_PATH}/duckdb.tar.gz" ]; then
  echo "[restore] duckdb…"
  docker run --rm -v "${DUCKDB_VOLUME}":/data -v "$(pwd)/${BACKUP_PATH}":/in:ro alpine sh -c 'rm -rf /data/* && tar xzf /in/duckdb.tar.gz -C /data'
fi

echo "[restore] arrancando servicios…"
# En el drill de verificacion se levanta un subconjunto (RESTORE_UP_SERVICES);
# en produccion, todo.
if [ -n "${RESTORE_UP_SERVICES:-}" ]; then
  ${COMPOSE} up -d ${RESTORE_UP_SERVICES}
else
  ${COMPOSE} up -d
fi
echo "[restore] aplicando migraciones por si el backup es de otra version…"
${COMPOSE} exec -T backend python -m alembic upgrade head
# El compose de produccion no publica el puerto del backend, asi que el
# healthcheck va por Caddy.
echo "[restore] listo. Verifica: curl -fsS https://${BACKEND_DOMAIN:-localhost}/health/ready"
