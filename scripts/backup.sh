#!/usr/bin/env bash
# Backup de GerarAI (produccion personal, Linux/Oracle VM).
#
# Genera backups/YYYYMMDD-HHMMSS/ con:
#   - postgres.dump      (pg_dump -Fc, canonico: research/evidence/thesis)
#   - qdrant-snapshots/  (un .snapshot por coleccion, via API de Qdrant)
#   - minio.tar.gz       (documentos crudos; volumen parado si --stop-storage)
#   - duckdb.tar.gz      (analytics local)
#   - manifest.txt       (fecha, versiones, conteos basicos)
#
# Retencion: conserva los ultimos ${BACKUP_RETENTION_COUNT:-8} backups locales
# y borra los mas antiguos al final de cada ejecucion correcta. En R2, la
# retencion la impone el lifecycle del bucket (ver docs/BACKUP_RESTORE.md).
#
# Mongo Atlas M0 NO incluye backups gestionados: los datos de auth se cubren
# aparte con scripts/mongo-backup.sh (cron semanal, ver docs/BACKUP_RESTORE.md).
#
# Subida opcional a Cloudflare R2 (free tier 10 GB) con rclone:
#   RCLONE_REMOTE=r2:cavaai-backups ./scripts/backup.sh
#
# Uso:
#   ./scripts/backup.sh [--stop-storage]
set -euo pipefail

# .env.production no se carga solo (no es el nombre por defecto de compose);
# sin el las variables obligatorias (POSTGRES_PASSWORD, MINIO_ROOT_*, ...)
# hacen fallar cualquier subcomando. COMPOSE_CMD externo tiene prioridad.
if [ -z "${COMPOSE_CMD:-}" ] && [ -f .env.production ]; then
  COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"
else
  COMPOSE="${COMPOSE_CMD:-docker compose -f docker-compose.prod.yml}"
fi
# Knobs para el drill de verificacion en proyecto aislado (ver
# scripts/verify-backup-restore.sh); en produccion no hace falta definirlos.
QDRANT_API_URL="${QDRANT_API_URL:-http://127.0.0.1:6333}"
QDRANT_VOLUME="${QDRANT_VOLUME:-cavaai-prod-qdrant}"
MINIO_VOLUME="${MINIO_VOLUME:-cavaai-prod-minio}"
DUCKDB_VOLUME="${DUCKDB_VOLUME:-cavaai-prod-duckdb}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
DEST="backups/${STAMP}"
STOP_STORAGE=0
[ "${1:-}" = "--stop-storage" ] && STOP_STORAGE=1

mkdir -p "${DEST}"
echo "[backup] destino: ${DEST}"

# 1) Postgres: dump consistente en caliente (formato custom comprimido).
echo "[backup] postgres…"
${COMPOSE} exec -T postgres pg_dump -U "${POSTGRES_USER:-portfolio}" -Fc "${POSTGRES_DB:-cavaai_research}" > "${DEST}/postgres.dump"

# 2) Qdrant: snapshot POR COLECCION via API (puerto solo-loopback del compose).
#    Los snapshots por coleccion se restauran con la API de upload sin tocar el
#    volumen; un snapshot full-storage exigiria copiar el fichero dentro del
#    volumen a mano y por eso se evita.
echo "[backup] qdrant…"
if COLLECTIONS_JSON=$(curl -fsS "${QDRANT_API_URL}/collections"); then
  mapfile -t QDRANT_COLLECTIONS < <(printf '%s' "${COLLECTIONS_JSON}" | python3 -c 'import json,sys; [print(c["name"]) for c in json.load(sys.stdin)["result"]["collections"]]')
  mkdir -p "${DEST}/qdrant-snapshots"
  for COLL in "${QDRANT_COLLECTIONS[@]}"; do
    echo "[backup] qdrant: snapshot de ${COLL}…"
    SNAP_NAME=$(curl -fsS -X POST "${QDRANT_API_URL}/collections/${COLL}/snapshots" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["name"])')
    curl -fsS "${QDRANT_API_URL}/collections/${COLL}/snapshots/${SNAP_NAME}" -o "${DEST}/qdrant-snapshots/${COLL}.snapshot"
  done
else
  echo "[backup] aviso: API de qdrant no disponible; se copiara el volumen en crudo"
  docker run --rm -v "${QDRANT_VOLUME}":/data:ro -v "$(pwd)/${DEST}":/out alpine tar czf /out/qdrant-raw.tar.gz -C /data .
fi

if [ "${STOP_STORAGE}" = "1" ]; then
  echo "[backup] parando backend, TODOS los workers, scheduler y minio para snapshot consistente…"
  # Lista completa: con un worker vivo el tar de MinIO puede capturar un
  # original a medio escribir. Criterio conservador: se para todo servicio
  # que fusiona el ancla x-app-env del compose (hereda MINIO_*), lo escriba
  # o no (un actor puede llegar al storage transitivamente). Lo ata al
  # compose scripts/backup-stop-storage-coverage-guard.test.ts.
  ${COMPOSE} stop backend worker worker-thesis worker-kpis worker-alerts worker-gdelt worker-knowledge worker-official-closes worker-prices worker-externa worker-finnhub worker-yahoo worker-dca-manual scheduler minio
fi

# 3) MinIO: tar del volumen (datos en reposo, consistencia garantizada si parado).
echo "[backup] minio…"
# .minio.sys es metadato vivo de MinIO (locks, formato, tmp): lo regenera al
# arrancar y reescribirlo tras el restore falseaba el conteo del drill.
docker run --rm -v "${MINIO_VOLUME}":/data:ro -v "$(pwd)/${DEST}":/out alpine tar czf /out/minio.tar.gz --exclude='./.minio.sys' -C /data .

# 4) DuckDB: fichero unico.
echo "[backup] duckdb…"
docker run --rm -v "${DUCKDB_VOLUME}":/data:ro -v "$(pwd)/${DEST}":/out alpine sh -c 'cd /data && tar czf /out/duckdb.tar.gz . || true'

if [ "${STOP_STORAGE}" = "1" ]; then
  ${COMPOSE} start minio backend worker worker-thesis worker-kpis worker-alerts worker-gdelt worker-knowledge worker-official-closes worker-prices worker-externa worker-finnhub worker-yahoo worker-dca-manual scheduler
fi

# 5) Manifest verificable: conteos por tabla, puntos qdrant, checksums y
#    numero de ficheros por tar. El drill (verify-backup-restore.sh) compara
#    lo restaurado contra estos valores; sin ellos el restore no es prueba.
echo "[backup] manifest verificable…"
{
  echo "timestamp_utc=${STAMP}"
  echo "postgres_db=${POSTGRES_DB:-cavaai_research}"
  echo "git_commit=$(git rev-parse --short HEAD 2>/dev/null || echo n/a)"
} > "${DEST}/manifest.txt"

# LIMITACION conocida: los conteos del manifest (tablas postgres y puntos
# qdrant) se leen del sistema VIVO tras el pg_dump/snapshot, no del propio
# artefacto. Con escrituras concurrentes durante el backup puede haber drift
# entre el manifest y lo restaurado; la verificacion entonces fallaria en
# falso o pasaria con un conteo distinto del real. Eliminarlo exige parar el
# writer durante el backup o exportar un snapshot consistente de postgres
# (pg_dump --snapshot); para un despliegue personal de baja concurrencia el
# drift esperado es cero y se documenta aqui como deuda consciente.
${COMPOSE} exec -T postgres psql -U "${POSTGRES_USER:-portfolio}" -d "${POSTGRES_DB:-cavaai_research}" -tAc \
  "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1" \
  | while read -r T; do
      [ -n "${T}" ] || continue
      C=$(${COMPOSE} exec -T postgres psql -U "${POSTGRES_USER:-portfolio}" -d "${POSTGRES_DB:-cavaai_research}" -tAc "SELECT count(*) FROM \"${T}\"")
      echo "pg_table_count.${T}=${C}" >> "${DEST}/manifest.txt"
    done

# Puntos por coleccion de Qdrant (si la API respondio).
if [ -d "${DEST}/qdrant-snapshots" ]; then
  for SNAP in "${DEST}"/qdrant-snapshots/*.snapshot; do
    COLL="$(basename "${SNAP}" .snapshot)"
    PTS=$(curl -fsS "${QDRANT_API_URL}/collections/${COLL}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["points_count"])')
    echo "qdrant_points.${COLL}=${PTS}" >> "${DEST}/manifest.txt"
  done
fi

# Checksums y numero de ficheros de cada artefacto.
( cd "${DEST}" && find . -maxdepth 2 -type f ! -name manifest.txt -print0 | sort -z | xargs -0 sha256sum ) \
  | awk '{f=$2; sub(/^\.\//,"",f); print "sha256." f "=" $1}' >> "${DEST}/manifest.txt"
for TAR in minio.tar.gz duckdb.tar.gz qdrant-raw.tar.gz; do
  if [ -f "${DEST}/${TAR}" ]; then
    echo "file_count.${TAR}=$(tar tzf "${DEST}/${TAR}" | grep -cv '/$')" >> "${DEST}/manifest.txt"
  fi
done

# Verificacion inmediata: un backup no esta completado hasta que sus propios
# checksums cuadran. Se recalcula contra el manifest (misma fuente que usara
# restore.sh) y se aborta sin subir ni purgar si algo no cuadra.
echo "[backup] verificando checksums del manifest…"
(
  cd "${DEST}"
  while IFS='=' read -r KEY VALUE; do
    case "${KEY}" in
      sha256.*) printf '%s  %s\n' "${VALUE}" "${KEY#sha256.}" ;;
    esac
  done < manifest.txt | sha256sum -c -
) || { echo "[backup] ERROR: los checksums del backup no cuadran; no se sube ni se purga"; exit 1; }

echo "[backup] completado: ${DEST}"

# 6) Subida opcional a R2 (rclone config previamente: rclone config → S3-compatible).
if [ -n "${RCLONE_REMOTE:-}" ]; then
  echo "[backup] subiendo a ${RCLONE_REMOTE}…"
  rclone copy "${DEST}" "${RCLONE_REMOTE}/${STAMP}" --transfers 4
  echo "[backup] subida completada"
fi

# 7) Retencion local: conserva los N mas recientes, borra el resto.
# Solo tras ejecucion correcta (set -e: si algo fallo, no se llega aqui).
RETENTION_COUNT="${BACKUP_RETENTION_COUNT:-8}"
if [ "${RETENTION_COUNT}" -ge 1 ] 2>/dev/null; then
  mapfile -t OLD_DIRS < <(ls -1d backups/*/ 2>/dev/null | sort | head -n "-${RETENTION_COUNT}") || true
  if [ "${#OLD_DIRS[@]}" -gt 0 ]; then
    echo "[backup] retencion: borrando ${#OLD_DIRS[@]} backup(s) antiguos (conservo ${RETENTION_COUNT})…"
    printf '%s\n' "${OLD_DIRS[@]}"
    rm -rf "${OLD_DIRS[@]}"
  fi
fi
