#!/usr/bin/env bash
# Latido del planificador: quien vigila al vigilante.
#
# Motivo (medido 18-nov-2026): los watchdogs in-app (colas, salud de
# fuentes, conexiones PG, frescura) los dispara el planificador
# (cavaai-scheduler). Si ese proceso muere o un job deja de registrarse,
# TODO queda en silencio y el panel parece sano: ningun watchdog puede
# alertar de su propia muerte. Cada job que termina bien escribe
# scheduler:heartbeat:<job> en Redis (ISO UTC; ver
# app/services/scheduler_heartbeat.py). Este chequeo corre en el host por
# cron: para cada job vigilado exige latido presente, legible y dentro de
# su margen; si no, exit 1 nombrando los jobs. Nunca escribe ni borra nada:
# lo no verificable alerta, no pasa por sano.
#
# Uso: ./check-scheduler-heartbeat.sh [JOB:MAX_AGE_SEG ...]
#   Sin argumentos vigila los watchdogs con 2x su cadencia + 10 min:
#     source_health_watchdog:1200      (cadencia 5 min)
#     queue_watchdog:1200              (cadencia 5 min)
#     db_connection_watchdog:1200      (cadencia 5 min)
#     source_freshness_watchdog:7800   (cadencia 60 min)
#   Entorno: REDIS_CONTAINER (defecto cavaai-redis), DOCKER_BIN (defecto docker).
# Cron sugerido (host): */10 * * * * /ruta/check-scheduler-heartbeat.sh || avisar
set -u

REDIS_CONTAINER="${REDIS_CONTAINER:-cavaai-redis}"
DOCKER_BIN="${DOCKER_BIN:-docker}"

if [ "$#" -gt 0 ]; then
  WATCHED=("$@")
else
  WATCHED=(
    source_health_watchdog:1200
    queue_watchdog:1200
    db_connection_watchdog:1200
    source_freshness_watchdog:7800
  )
fi

NOW=$(date +%s)
FAIL=0
for par in "${WATCHED[@]}"; do
  job="${par%%:*}"
  max="${par##*:}"
  case "${job}" in
    ''|*[!A-Za-z0-9_-]*) echo "[scheduler-hb] ERROR: nombre de job invalido: ${job}"; exit 2;;
  esac
  case "${max}" in
    ''|*[!0-9]*) echo "[scheduler-hb] ERROR: margen invalido para ${job}: ${max}"; exit 2;;
  esac

  raw="$("${DOCKER_BIN}" exec "${REDIS_CONTAINER}" redis-cli GET "scheduler:heartbeat:${job}" 2>/dev/null)"
  if [ $? -ne 0 ]; then
    echo "[scheduler-hb] ALERTA ${job}: no se pudo leer Redis (${REDIS_CONTAINER}); latido no verificable"
    FAIL=1
    continue
  fi
  if [ -z "${raw}" ]; then
    echo "[scheduler-hb] ALERTA ${job}: sin latido registrado (planificador parado o job no registrado)"
    FAIL=1
    continue
  fi
  ts=$(date -d "${raw}" +%s 2>/dev/null)
  if [ -z "${ts}" ]; then
    echo "[scheduler-hb] ALERTA ${job}: latido ilegible (${raw})"
    FAIL=1
    continue
  fi
  age=$(( NOW - ts ))
  if [ "${age}" -gt "${max}" ]; then
    echo "[scheduler-hb] ALERTA ${job}: ultimo latido hace ${age}s (margen ${max}s); planificador parado o job caido"
    FAIL=1
    continue
  fi
  echo "[scheduler-hb] OK ${job}: ultimo latido hace ${age}s (margen ${max}s)"
done

[ "${FAIL}" -eq 0 ] || exit 1
echo "[scheduler-hb] OK: ${#WATCHED[@]} jobs con latido fresco"
