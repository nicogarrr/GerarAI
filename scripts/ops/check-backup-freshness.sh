#!/usr/bin/env bash
# Frescura de backups de la VM (complemento de check-disk-space.sh).
#
# Motivo (medido 18-nov-2026): los backups diarios de Postgres, Mongo y Garage
# escriben en su log y nadie los vigila; si el cron deja de correr, nadie se
# entera hasta el desastre (memoria del proyecto: "no failure alert yet").
# Este chequeo sale con codigo 1 si el artefacto mas reciente de un pilar
# supera su edad maxima o no existe, e imprime una linea por pilar con la edad
# MEDIDA para que un cron la mande por el canal de alertas. SOLO LEE: nunca
# borra, crea ni modifica nada.
#
# Pilares y contratos (medidos en el repo):
#   - postgres: solo cuentan dumps con marca .verified de
#     scripts/ops/pg-daily-backup.sh (un dump sin restaurar no es un backup).
#   - mongo: artefactos mongo-*.archive.gz.age de scripts/mongo-backup.sh.
#   - garage: el backup diario vive hoy SOLO en la VM (sin script en el repo),
#     asi que hay que declarar GARAGE_DIR (y si hace falta GARAGE_PATTERN).
#     Sin GARAGE_DIR el chequeo ALERTA: un pilar sin vigilar es el fallo.
#   - qdrant: snapshots *.snapshot de scripts/ops/qdrant-snapshot.sh.
#
# Variables (todas opcionales salvo la vigilancia de garage):
#   PG_DIR (defecto ~/backups)          PG_MAX_AGE_H (defecto 26)
#   MONGO_DIR (defecto ~/backups-mongo) MONGO_MAX_AGE_H (defecto 26)
#   GARAGE_DIR (sin defecto)            GARAGE_PATTERN (defecto 'garage-*')
#   GARAGE_MAX_AGE_H (defecto 26)       GARAGE_CHECK=off lo desactiva a sabiendas
#   QDRANT_DIR (defecto ~/backups/qdrant)  QDRANT_PATTERN (defecto '*.snapshot')
#   QDRANT_MAX_AGE_H (defecto 26)       QDRANT_CHECK=off lo desactiva a sabiendas
#
# Uso: ./scripts/ops/check-backup-freshness.sh
# Cron sugerido (host): 30 8 * * * /ruta/check-backup-freshness.sh || avisar
set -euo pipefail

es_entero() { case "${1}" in ''|*[!0-9]*) return 1;; esac; }

PG_DIR="${PG_DIR:-$HOME/backups}"
MONGO_DIR="${MONGO_DIR:-$HOME/backups-mongo}"
PG_MAX_AGE_H="${PG_MAX_AGE_H:-26}"
MONGO_MAX_AGE_H="${MONGO_MAX_AGE_H:-26}"
GARAGE_MAX_AGE_H="${GARAGE_MAX_AGE_H:-26}"
GARAGE_DIR="${GARAGE_DIR:-}"
GARAGE_PATTERN="${GARAGE_PATTERN:-garage-*}"
GARAGE_CHECK="${GARAGE_CHECK:-on}"
QDRANT_DIR="${QDRANT_DIR:-$HOME/backups/qdrant}"
QDRANT_PATTERN="${QDRANT_PATTERN:-*.snapshot}"
QDRANT_MAX_AGE_H="${QDRANT_MAX_AGE_H:-26}"
QDRANT_CHECK="${QDRANT_CHECK:-on}"

for var in PG_MAX_AGE_H MONGO_MAX_AGE_H GARAGE_MAX_AGE_H QDRANT_MAX_AGE_H; do
  eval "valor=\${${var}}"
  es_entero "${valor}" || { echo "[backup-freshness] ${var} debe ser un entero de horas (p. ej. 26)"; exit 2; }
done

fail=0

check_pillar() {
  local nombre="$1" dir="$2" patron="$3" max_h="$4"
  local ahora corte linea ts edad_h reciente
  ahora=$(date +%s)
  corte=$(( ahora - max_h * 3600 ))
  if [ ! -d "${dir}" ]; then
    echo "[backup-freshness] ALERTA ${nombre}: no existe el directorio ${dir}"
    return 1
  fi
  linea=$(find "${dir}" -maxdepth 1 -type f -name "${patron}" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 || true)
  if [ -z "${linea}" ]; then
    echo "[backup-freshness] ALERTA ${nombre}: ningun artefacto '${patron}' en ${dir}"
    return 1
  fi
  ts="${linea%% *}"; ts="${ts%.*}"
  reciente="${linea#* }"
  edad_h=$(( (ahora - ts) / 3600 ))
  if [ "${ts}" -lt "${corte}" ]; then
    echo "[backup-freshness] ALERTA ${nombre}: el mas reciente tiene ${edad_h} h (max ${max_h} h): ${reciente}"
    return 1
  fi
  echo "[backup-freshness] OK ${nombre}: ${edad_h} h desde el ultimo backup verificado (max ${max_h} h)"
  return 0
}

check_pillar postgres "${PG_DIR}" 'pg-daily-*.sql.gz.verified' "${PG_MAX_AGE_H}" || fail=1
check_pillar mongo "${MONGO_DIR}" 'mongo-*.archive.gz.age' "${MONGO_MAX_AGE_H}" || fail=1
if [ "${GARAGE_CHECK}" = "off" ]; then
  echo "[backup-freshness] garage: chequeo desactivado explicitamente (GARAGE_CHECK=off)"
elif [ -z "${GARAGE_DIR}" ]; then
  echo "[backup-freshness] ALERTA garage: GARAGE_DIR no definido; el backup diario de Garage vive solo en la VM y queda sin vigilar"
  fail=1
else
  check_pillar garage "${GARAGE_DIR}" "${GARAGE_PATTERN}" "${GARAGE_MAX_AGE_H}" || fail=1
fi
if [ "${QDRANT_CHECK}" = "off" ]; then
  echo "[backup-freshness] qdrant: chequeo desactivado explicitamente (QDRANT_CHECK=off)"
else
  check_pillar qdrant "${QDRANT_DIR}" "${QDRANT_PATTERN}" "${QDRANT_MAX_AGE_H}" || fail=1
fi
exit "${fail}"
